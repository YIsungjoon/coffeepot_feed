"""Import public RSS, Atom and COFFEEPOT entries into the separate feed vault."""

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from feed_settings import ROOT, vault_path
from save_feed import KST, save_article


VAULT = vault_path()
ATOM = "{http://www.w3.org/2005/Atom}"
XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"
MAX_BYTES = 2_000_000
BLOCK_TAGS = {"article", "br", "div", "h1", "h2", "h3", "hr", "li", "p", "td"}


@dataclass(frozen=True)
class Entry:
    url: str
    title: str
    excerpt: str
    topics: tuple[str, ...] = ()
    published_at: datetime | None = None


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = None

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden = tag
        elif tag in BLOCK_TAGS and not self.hidden:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag == self.hidden:
            self.hidden = None
        elif tag in BLOCK_TAGS and not self.hidden:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def excerpt_text(html: str) -> str:
    parser = PlainText()
    parser.feed(html)
    parser.close()
    text = " ".join("".join(parser.parts).split())
    return f"{text[:600].rstrip()}…" if len(text) > 600 else text


def publication_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (ValueError, TypeError):
            return None
    return parsed if parsed.utcoffset() is not None else None


def element_text(element: ET.Element, *names: str) -> str:
    for name in names:
        child = element.find(name)
        if child is not None:
            value = " ".join(child.itertext()).strip()
            if value:
                return value
    return ""


def public_link(url: str) -> str | None:
    try:
        link = urlsplit(url)
        if link.scheme not in {"http", "https"} or not link.hostname or link.username is not None:
            return None
        if any(char.isspace() or ord(char) < 32 for char in url):
            return None
    except ValueError:
        return None
    if link.hostname == "news.hada.io" and link.path == "/topic":
        item_id = parse_qs(link.query).get("id", [""])[0]
        if item_id.isascii() and item_id.isdecimal():
            return f"https://news.hada.io/topic?id={item_id}"
    return url


def parse_feed(document: str, response_url: str) -> list[Entry]:
    if "<!DOCTYPE" in document:
        raise ValueError("Document type declarations are not supported in feeds")
    root = ET.fromstring(document)
    entries = []
    if root.tag == f"{ATOM}feed":
        base = urljoin(response_url, root.get(XML_BASE, ""))
        for item in root.findall(f"{ATOM}entry"):
            entry_base = urljoin(base, item.get(XML_BASE, ""))
            urls = (
                urljoin(urljoin(entry_base, link.get(XML_BASE, "")), link.attrib["href"])
                for link in item.findall(f"{ATOM}link")
                if link.get("rel", "alternate") == "alternate" and link.get("href")
            )
            url = next((valid for link in urls if (valid := public_link(link))), None)
            title = element_text(item, f"{ATOM}title")
            if url and title:
                entries.append(Entry(
                    url, title, excerpt_text(element_text(item, f"{ATOM}summary", f"{ATOM}content")),
                    tuple(category.attrib["term"] for category in item.findall(f"{ATOM}category") if category.get("term")),
                    publication_time(element_text(item, f"{ATOM}published", f"{ATOM}updated")),
                ))
    elif root.tag == "rss" and root.find("channel") is not None:
        for item in root.findall("channel/item"):
            link = element_text(item, "link")
            guid = item.find("guid")
            if not link and guid is not None and guid.get("isPermaLink", "true") == "true":
                link = guid.text or ""
            url = public_link(urljoin(response_url, link)) if link else None
            title = element_text(item, "title")
            if url and title:
                entries.append(Entry(
                    url, title, excerpt_text(element_text(item, "description")),
                    tuple(category.text for category in item.findall("category") if category.text),
                    publication_time(element_text(item, "pubDate")),
                ))
    else:
        raise ValueError("Expected an RSS 2.0 or Atom 1.0 feed")
    return entries


class CoffeepotCards(HTMLParser):
    def __init__(self):
        super().__init__()
        self.entries = []
        self.url = None
        self.part = None
        self.div_depth = 0
        self.card_text = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        href = attrs.get("href") or ""
        if tag == "a" and self.url is None and href.startswith("/library/?"):
            query = parse_qs(urlsplit(href).query)
            item_id = query.get("idx", [""])[0]
            if query.get("bmode") == ["view"] and item_id.isascii() and item_id.isdecimal():
                self.url = f"https://coffeepot.me/library/?bmode=view&idx={item_id}"
                self.card_text = {"title-block": [], "text-block": []}
        if tag == "div" and self.url:
            if self.part:
                self.div_depth += 1
            else:
                classes = (attrs.get("class") or "").split()
                self.part = next((name for name in classes if name in self.card_text), None)
                self.div_depth = 1 if self.part else 0

    def handle_data(self, data):
        if self.part:
            self.card_text[self.part].append(data)

    def handle_endtag(self, tag):
        if tag == "div" and self.part:
            self.div_depth -= 1
            if not self.div_depth:
                self.part = None
        if tag == "a" and self.url:
            title = " ".join("".join(self.card_text["title-block"]).split())
            excerpt = " ".join("".join(self.card_text["text-block"]).split())
            if title:
                self.entries.append(Entry(self.url, title, excerpt))
            self.url = self.part = None
            self.div_depth = 0


def read_source(source: dict) -> list[Entry]:
    url = source["url"]
    if not public_link(url):
        raise ValueError("Source URL must use HTTP(S)")
    request = Request(url, headers={"User-Agent": "ObsidianFeedCollector/1.0"})
    with urlopen(request, timeout=15) as response:
        data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("Source exceeds the 2 MB download limit")
        document = data.decode(response.headers.get_content_charset() or "utf-8-sig").lstrip("\ufeff")
        response_url = response.geturl()

    if source["format"] == "feed":
        return parse_feed(document, response_url)
    if source["format"] == "coffeepot":
        parser = CoffeepotCards()
        parser.feed(document)
        parser.close()
        if not parser.entries:
            raise ValueError("COFFEEPOT listing did not expose any article cards")
        return parser.entries
    raise ValueError(f"Unknown source format: {source['format']}")


def collect(vault: Path, sources: list[dict], limit: int | None) -> int:
    if not (vault / ".obsidian").is_dir():
        raise ValueError(f"Open the separate Obsidian vault first: {vault}")
    collected_at = datetime.now(KST)
    existing = set((vault / "10_Feeds" / "Articles").glob("????-??/*.md"))
    failed = False
    for source in sources:
        name = source["name"]
        imported = retained = 0
        try:
            unique = {}
            for entry in read_source(source):
                unique.setdefault(entry.url, entry)
            basis = "public-listing" if source["format"] == "coffeepot" else "feed-excerpt"
            for entry in list(unique.values())[:limit]:
                note = save_article(
                    vault, url=entry.url, title=entry.title, source=name,
                    summary=entry.excerpt or "원문 링크에서 내용을 확인할 수 있습니다.",
                    topics=list(entry.topics), collected_at=collected_at,
                    content_basis=basis, published_at=entry.published_at,
                )
                if note in existing:
                    retained += 1
                else:
                    existing.add(note)
                    imported += 1
        except (OSError, ValueError, LookupError, ET.ParseError) as error:
            print(f"{name}: {error}", file=sys.stderr)
            failed = True
        print(f"{name}: 새 노트 {imported}건, 기존 노트 {retained}건")
    return int(failed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="Max entries to read per source (default: all available)")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    try:
        sources = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
        return collect(VAULT, sources, args.limit)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
