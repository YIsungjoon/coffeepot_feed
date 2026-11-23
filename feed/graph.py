"""Generate Obsidian notes that link feed articles by topic and collection day."""

import os
import re
from collections import defaultdict
from datetime import date
from hashlib import sha256
from pathlib import Path
from posixpath import relpath
from tempfile import NamedTemporaryFile
from urllib.parse import quote

from .articles import article_list
from .briefing import ALIASES, daily_briefing, keywords
from .settings import vault_path
from .topics import TOPICS
from .vault import plain_markdown, write_new_note


GRAPH = Path("30_Graph")
TOPIC_NOTES = GRAPH / "주제"
DAILY_NOTES = GRAPH / "브리핑"
ARTICLE_NODES = GRAPH / "기사"
MARKER = "<!-- obsidian-feed:graph -->\n"
GRAPH_TOPICS = (TOPICS.keys() - {"기타"}) | ALIASES.keys()
FILENAME_PUNCTUATION = str.maketrans('<>:"/\\|?*', '＜＞：＂／＼｜？＊')
WINDOWS_DEVICE = re.compile(r"(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[1-9¹²³])(?:\.|$)", re.I)


def link(source: Path, target: Path, title: str) -> str:
    relative = relpath(target.as_posix(), source.parent.as_posix())
    return f"[{plain_markdown(title)}]({quote(relative, safe='/')})"


def article_node(article: dict) -> Path:
    title = " ".join(article["title"].split()).translate(FILENAME_PUNCTUATION)
    title = "".join(char for char in title if char.isprintable())
    title = title.encode("utf-16-le")[:200].decode("utf-16-le", errors="ignore").strip(" .") or "기사"
    if WINDOWS_DEVICE.match(title):
        title = "기사 " + title
    article_id = sha256(article["id"].encode()).hexdigest()[:16]
    return ARTICLE_NODES / article_id / f"{title}.md"


def article_link(source: Path, article: dict) -> str:
    title = link(source, article_node(article), article["title"])
    return f"{title} · {original_link(article, '원본 노트')}"


def original_link(article: dict, label: str) -> str:
    return f"[{label}]({article['note_url']}&paneType=tab)"


def article_node_lines(article: dict) -> list[str]:
    name = "커피팟" if article["source"] == "COFFEEPOT" else article["source"]
    date = article["date"]
    return [
        plain_markdown(" · ".join(value for value in (name, date) if value)),
        "",
        original_link(article, "원본 옵시디언 노트 열기"),
        "",
        plain_markdown(article["excerpt"]) if article["excerpt"] else "기사 내용은 원본 노트에서 확인할 수 있습니다.",
    ]


def article_topics(article: dict) -> list[str]:
    keyword = next((name for name in keywords(article["title"]) if name in ALIASES), "")
    names = (article["topic"], keyword, *article["related"])
    return list(dict.fromkeys(name for name in names if name in GRAPH_TOPICS))[:2]


def write_generated(vault: Path, path: Path, lines: list[str]) -> None:
    destination = vault / path
    if not destination.parent.resolve().is_relative_to(vault) or destination.is_symlink():
        raise ValueError(f"그래프 노트 경로를 확인해 주세요. {path}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    markdown = "\n".join(lines).rstrip() + "\n\n" + MARKER
    try:
        previous = destination.read_text(encoding="utf-8")
    except FileNotFoundError:
        write_new_note(destination, markdown)
        return
    if previous == markdown or not (previous.startswith(MARKER) or previous.endswith("\n\n" + MARKER)):
        return

    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=destination.parent,
                                prefix=".graph-", suffix=".tmp", delete=False) as note:
            temporary = Path(note.name)
            note.write(markdown)
            note.flush()
            os.fsync(note.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def refresh_graph(vault: Path) -> tuple[int, int]:
    vault = vault.resolve(strict=True)
    if not (vault / ".obsidian").is_dir():
        raise ValueError("옵시디언 벌트를 먼저 초기화해 주세요.")

    by_topic = defaultdict(list)
    by_day = defaultdict(list)
    linked_articles = {}
    graph_notes = {}
    for article in article_list(vault)["articles"]:
        for name in article_topics(article):
            by_topic[name].append(article)
            linked_articles[article["id"]] = article
        try:
            day = date.fromisoformat(article["collected_at"][:10] or article["date"]).isoformat()
        except ValueError:
            continue
        by_day[day].append({**article, "collected_at": day})

    for name in sorted(GRAPH_TOPICS):
        path = TOPIC_NOTES / f"{name}.md"
        related = by_topic.get(name, [])
        if related or (vault / path).exists():
            lines = [f"연결된 기사 {len(related)}건", ""]
            for article in related:
                source = "커피팟" if article["source"] == "COFFEEPOT" else plain_markdown(article["source"])
                lines.append(f"- {article_link(path, article)} · {source}")
            graph_notes[path] = lines

    for existing in (vault / DAILY_NOTES).glob("* 브리핑.md"):
        day = existing.name.removesuffix(" 브리핑.md")
        try:
            if date.fromisoformat(day).isoformat() == day:
                by_day.setdefault(day, [])
        except ValueError:
            continue
    for day, articles in sorted(by_day.items()):
        path = DAILY_NOTES / f"{day} 브리핑.md"
        lines = [f"수집 기사 {len(articles)}건", "", "## 먼저 볼 기사", ""]
        lookup = {article["id"]: article for article in articles}
        for pick in daily_briefing(articles, day)["picks"]:
            article = lookup[pick["article_id"]]
            linked_articles[article["id"]] = article
            lines.append(f"- {article_link(path, article)} · {plain_markdown(pick['reason'])}")
        graph_notes[path] = lines

    for article in linked_articles.values():
        write_generated(vault, article_node(article), article_node_lines(article))
    for path, lines in graph_notes.items():
        write_generated(vault, path, lines)

    index = GRAPH / "피드 그래프.md"
    lines = ["브리핑이나 주제 노트를 연 뒤 **로컬 그래프 열기**를 실행하세요.",
             "", "## 최근 브리핑", ""]
    days = sorted((day for day, articles in by_day.items() if articles), reverse=True)
    for day in days[:7]:
        name = f"{day} 브리핑"
        lines.append(f"- {link(index, DAILY_NOTES / (name + '.md'), name)}")
    if not days:
        lines.append("수집한 기사가 생기면 브리핑이 표시됩니다.")
    lines.extend(["", "## 주제", ""])
    for name in sorted(by_topic, key=lambda topic: (-len(by_topic[topic]), topic)):
        lines.append(f"- {link(index, TOPIC_NOTES / (name + '.md'), name)} · {len(by_topic[name])}건")
    write_generated(vault, index, lines)
    return len(by_topic), len(days)


if __name__ == "__main__":
    topics, days = refresh_graph(vault_path())
    print(f"그래프 갱신: 주제 {topics}개, 일간 브리핑 {days}개")
