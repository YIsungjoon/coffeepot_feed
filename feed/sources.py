"""Fetch and parse RSS, Atom and the COFFEEPOT public listing."""

import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from .links import public_link, publisher_article


ATOM = "{http://www.w3.org/2005/Atom}"
XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"
MAX_BYTES = 2_000_000
COFFEEPOT_LIBRARY = "https://coffeepot.me/library/"
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
        self.container = None
        self.depth = 0
        self.notice = False
        self.part = None
        self.div_depth = 0
        self.card_text = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if self.url is None:
            href = attrs.get("href") if tag == "a" else None
            if tag == "div" and "_card_body" in classes:
                target = re.fullmatch(r"""location\.href=['"]([^'"]+)['"];?""", attrs.get("onclick") or "")
                href = target[1] if target else None
            if href:
                try:
                    source, url = publisher_article(urljoin(COFFEEPOT_LIBRARY, href))
                except ValueError:
                    return
                if source == "COFFEEPOT":
                    self.url, self.container, self.depth = url, tag, 1
                    self.card_text = {"title-block": [], "text-block": []}
            return
        if tag == self.container:
            self.depth += 1
        if tag == "em" and "notice-block" in classes:
            self.notice = True
        if tag == "div" and self.url:
            if self.part:
                self.div_depth += 1
            else:
                self.part = next((name for name in classes if name in self.card_text), None)
                self.div_depth = 1 if self.part else 0

    def handle_data(self, data):
        if self.part and not self.notice:
            self.card_text[self.part].append(data)

    def handle_endtag(self, tag):
        if tag == "em":
            self.notice = False
        if tag == "div" and self.part:
            self.div_depth -= 1
            if not self.div_depth:
                self.part = None
        if tag != self.container:
            return
        self.depth -= 1
        if not self.depth:
            title = " ".join("".join(self.card_text["title-block"]).split())
            excerpt = " ".join("".join(self.card_text["text-block"]).split())
            if title:
                self.entries.append(Entry(self.url, title, excerpt))
            self.url = self.part = None
            self.container = None
            self.div_depth = 0


def download(url: str, *, open_url=urlopen) -> tuple[str, str]:
    request = Request(url, headers={"User-Agent": "ObsidianFeedCollector/1.0"})
    with open_url(request, timeout=15) as response:
        data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("Source exceeds the 2 MB download limit")
        document = data.decode(response.headers.get_content_charset() or "utf-8-sig").lstrip("\ufeff")
        response_url = response.geturl()
    return document, response_url


def coffeepot_cards(document: str) -> list[Entry]:
    parser = CoffeepotCards()
    parser.feed(document)
    parser.close()
    return parser.entries


def search_coffeepot(query: str) -> list[Entry]:
    url = COFFEEPOT_LIBRARY + "?" + urlencode({"keyword_type": "all", "keyword": query})
    document, _ = download(url)
    return coffeepot_cards(document)


def read_source(source: dict) -> list[Entry]:
    url = source["url"]
    if not public_link(url):
        raise ValueError("Source URL must use HTTP(S)")
    document, response_url = download(url)

    if source["format"] == "feed":
        return parse_feed(document, response_url)
    if source["format"] == "coffeepot":
        entries = coffeepot_cards(document)
        if not entries:
            raise ValueError("COFFEEPOT listing did not expose any article cards")
        return entries
    raise ValueError(f"Unknown source format: {source['format']}")
