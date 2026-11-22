"""Create an article note in a local Obsidian vault from one feed item."""

import json
import os
import re
import string
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote, urlsplit


KST = timezone(timedelta(hours=9))
MARKDOWN_PUNCTUATION = re.compile(f"([{re.escape(string.punctuation)}])")
YAML_ESCAPE = re.compile(r"[\x7f-\x9f\u2028\u2029]")


def plain_markdown(text: str) -> str:
    return MARKDOWN_PUNCTUATION.sub(r"\\\1", " ".join(text.split()))


def yaml_value(value: str | list[str]) -> str:
    quoted = json.dumps(value, ensure_ascii=False)
    return YAML_ESCAPE.sub(lambda match: f"\\u{ord(match[0]):04x}", quoted)


def write_new_note(destination: Path, markdown: str) -> Path:
    temporary_path = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n",
            dir=destination.parent, prefix=".feed-", suffix=".tmp", delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(markdown)
            temporary.flush()
            os.fsync(temporary.fileno())

        try:
            if os.name == "nt":
                temporary_path.rename(destination)
            else:
                os.link(temporary_path, destination)
        except FileExistsError:
            if not destination.is_file():
                raise
        return destination
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def save_article(
    vault: Path,
    *,
    url: str,
    title: str,
    source: str,
    summary: str,
    topics: list[str],
    collected_at: datetime | None = None,
    content_basis: str | None = None,
    published_at: datetime | None = None,
) -> Path:
    """Return the new or existing note path. Use one collection process per vault."""
    vault = vault.resolve(strict=True)
    if not vault.is_dir():
        raise NotADirectoryError(vault)

    url = url.strip()
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or any(char.isspace() or ord(char) < 32 for char in url)
    ):
        raise ValueError("url must be an HTTP(S) article URL")
    if not title.strip() or not source.strip() or not summary.strip():
        raise ValueError("title, source, and summary are required")

    if collected_at is None:
        collected_at = datetime.now(KST)
    elif collected_at.utcoffset() is None:
        raise ValueError("collected_at must include a timezone")
    collected_at = collected_at.astimezone(KST)
    day = collected_at.date().isoformat()

    articles = vault / "10_Feeds" / "Articles"
    key = sha256(url.encode("utf-8")).hexdigest()[:24]
    # shortcut: Looks up names produced by this writer. Add a URL index for large or legacy archives.
    for existing in articles.glob(f"????-??/????-??-??_{key}.md"):
        if existing.is_file():
            return existing

    topics = list(dict.fromkeys(topic.strip() for topic in topics if topic.strip()))
    properties = {
        "title": " ".join(title.split()),
        "created_at": collected_at.isoformat(timespec="seconds"),
        "source": " ".join(source.split()),
        "url": url,
        "topics": topics or ["미분류"],
        "tags": ["feed/web" if content_basis == "public-listing" else "feed/rss"],
    }
    heading = "요약"
    if content_basis is not None:
        properties["content_basis"] = content_basis
        heading = "공개 목록 소개" if content_basis == "public-listing" else "피드 발췌"
    if published_at is not None:
        properties["published_at"] = published_at.isoformat(timespec="seconds")
    metadata = "\n".join(f"{key}: {yaml_value(value)}" for key, value in properties.items())
    bullets = "\n".join(
        f"- {plain_markdown(line)}" for line in summary.splitlines() if line.strip()
    )
    link_url = quote(url, safe=":/?#[]@!$&'()*+,;=%~")
    markdown = (
        f"---\ndate: {day}\ntype: feed-article\nstatus: unread\n{metadata}\n---\n\n"
        f"# {plain_markdown(title)}\n\n"
        f"[원문 보기](<{link_url}>)\n\n"
        f"## {heading}\n\n{bullets}\n"
    )
    destination = articles / day[:7] / f"{day}_{key}.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    return write_new_note(destination, markdown)
