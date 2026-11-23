import re
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, unquote, urlsplit

from feed.graph import article_node, refresh_graph
from feed.settings import KST
from feed.vault import save_article


class GraphTests(unittest.TestCase):
    def test_graph_links_to_articles_and_preserves_existing_notes(self):
        with TemporaryDirectory() as folder:
            vault = Path(folder)
            (vault / ".obsidian").mkdir()
            timestamp = datetime(2026, 11, 22, 8, tzinfo=KST)
            saved = [
                save_article(
                    vault, url=f"https://example.com/{index}", title="AI 에이전트: 시작할까?",
                    source=source, summary="공개 발췌", topics=[], collected_at=timestamp,
                )
                for index, source in enumerate(("GeekNews", "COFFEEPOT"))
            ]
            personal = vault / "20_Notes" / "메모.md"
            personal.parent.mkdir()
            personal.write_text("개인 메모", encoding="utf-8")
            ownership_collision = vault / "30_Graph" / "주제" / "데이터센터.md"
            ownership_collision.parent.mkdir(parents=True)
            ownership_collision.write_text("사용자가 만든 노트", encoding="utf-8")
            original = [note.read_bytes() for note in [*saved, personal, ownership_collision]]

            self.assertEqual(refresh_graph(vault), (1, 1))
            topic = ownership_collision.with_name("AI 에이전트.md")
            digest = vault / "30_Graph" / "브리핑" / "2026-11-22 브리핑.md"
            index = vault / "30_Graph" / "피드 그래프.md"
            nodes = list((vault / "30_Graph" / "기사").glob("*/*.md"))
            self.assertEqual(len(nodes), 2)
            self.assertEqual({note.name for note in nodes}, {"AI 에이전트： 시작할까？.md"})
            self.assertNotEqual(nodes[0].parent, nodes[1].parent)
            for note, targets in [(topic, nodes), (digest, nodes), (index, [topic, digest])]:
                urls = re.findall(r"\]\(([^)]+)\)", note.read_text(encoding="utf-8"))
                linked = {(note.parent / unquote(url)).resolve() for url in urls if not urlsplit(url).scheme}
                self.assertEqual(linked, set(targets))
            for note in [topic, digest, *nodes]:
                urls = re.findall(r"\]\((obsidian://[^)]+)\)", note.read_text(encoding="utf-8"))
                self.assertTrue(all(parse_qs(urlsplit(url).query)["paneType"] == ["tab"] for url in urls))
                originals = {
                    vault / (parse_qs(urlsplit(url).query)["file"][0] + ".md") for url in urls
                }
                self.assertTrue(originals)
                self.assertTrue(originals <= set(saved))
            mtime = topic.stat().st_mtime_ns
            self.assertEqual(refresh_graph(vault), (1, 1))
            self.assertEqual(topic.stat().st_mtime_ns, mtime)
            self.assertEqual([note.read_bytes() for note in [*saved, personal, ownership_collision]], original)

    def test_article_node_uses_windows_safe_names(self):
        self.assertEqual(article_node({"id": "note", "title": "CON"}).stem, "기사 CON")
        long_title = "가" * 99 + "🙆"
        self.assertEqual(article_node({"id": "note", "title": long_title}).stem, "가" * 99)
