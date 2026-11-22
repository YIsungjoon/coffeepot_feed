"""Import public RSS, Atom and COFFEEPOT entries into the separate feed vault."""


import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from feed.settings import KST, ROOT, vault_path
from feed.sources import read_source
from feed.vault import save_article


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
        return collect(vault_path(), sources, args.limit)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
