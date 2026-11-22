"""Build the admin article index and the public reader feed from vault notes."""

from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import yaml

from .briefing import daily_briefing
from .links import public_link
from .settings import KST
from .topics import TOPICS
from .vault import HEADINGS, feed_note, public_excerpt


def article_list(vault: Path) -> dict:
    articles = []
    unreadable = 0
    for path in (vault / "10_Feeds" / "Articles").rglob("*.md"):
        if path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8")
            note = feed_note(text)
        except (ValueError, OSError, yaml.YAMLError):
            unreadable += 1
            continue
        if note is None:
            continue
        props, block = note
        note_file = path.relative_to(vault).with_suffix("").as_posix()
        status = props.get("classification_status")
        manual = props.get("manual_topic")
        topic = manual or props.get("primary_topic") or ""
        if manual:
            status = "classified"
        elif status not in ("classified", "review"):
            status = "pending" if props.get("content_basis") else "unclassified"
        related = props.get("related_topics")
        basis = props.get("content_basis")
        articles.append({
            "id": note_file,
            "title": str(props.get("title") or path.stem),
            "source": str(props.get("source") or "출처 미상"),
            "date": str(props.get("published_at") or props.get("date") or "")[:10],
            "published_at": str(props.get("published_at") or ""),
            "collected_at": str(props.get("created_at") or ""),
            "topic": str(topic),
            "related": [str(item) for item in related] if isinstance(related, list) else [],
            "status": status,
            "manual": bool(manual),
            "evidence": str(props.get("classification_evidence") or ""),
            "model": str(props.get("classification_model") or ""),
            "url": public_link(str(props.get("url") or "")),
            "note_url": f"obsidian://open?vault={quote(vault.name)}&file={quote(note_file, safe='')}",
            "excerpt": public_excerpt(text[block.end():], basis),
            "excerpt_label": HEADINGS.get(basis, "") if isinstance(basis, str) else "",
        })
    articles.sort(key=lambda article: (article["collected_at"], article["date"], article["title"]), reverse=True)
    return {"articles": articles, "topics": list(TOPICS), "unreadable": unreadable}


def reader_feed(vault: Path) -> dict:
    public_fields = (
        "id", "title", "source", "date", "published_at", "topic", "related", "url", "note_url", "excerpt", "excerpt_label",
    )
    articles = article_list(vault)["articles"]
    articles.sort(key=lambda item: (item["date"], bool(item["published_at"]), item["published_at"] or item["collected_at"], item["title"]), reverse=True)
    return {
        "articles": [{key: item[key] for key in public_fields} for item in articles],
        "briefing": daily_briefing(articles, datetime.now(KST).date().isoformat()),
    }
