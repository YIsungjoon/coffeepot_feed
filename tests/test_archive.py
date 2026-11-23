import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError

from feed.archive import import_article
from feed.articles import article_list
from feed.links import publisher_article
from feed.sources import coffeepot_cards


class ArchiveTests(unittest.TestCase):
    def test_library_parser_uses_board_link_and_excludes_notice(self):
        html = """
        <div class="card-body _card_body list-group"
             onclick="location.href='/library/?q=search&amp;bmode=view&amp;idx=20&amp;t=board'">
          <div class="text_wrap">
            <div class="title title-block"><em class="notice-block">공지</em>
              <a href="?category="></a>지난 기사
            </div>
            <div class="text text-block show_body"><span>기사 소개</span></div>
          </div>
        </div>
        """
        [entry] = coffeepot_cards(html)
        self.assertEqual(entry.url, "https://coffeepot.me/library/?bmode=view&idx=20")
        self.assertEqual(entry.title, "지난 기사")
        self.assertEqual(entry.excerpt, "기사 소개")

    def test_bookmark_survives_unavailable_geeknews_metadata(self):
        url = "https://news.hada.io/topic?go=comments&id=5674#discussion"
        unavailable = HTTPError(url, 403, "Forbidden", {}, None)
        with TemporaryDirectory() as folder:
            vault = Path(folder)
            (vault / ".obsidian").mkdir()
            with patch("feed.archive.article_metadata", side_effect=unavailable) as request:
                self.assertFalse(import_article(vault, url, "이전 긱뉴스 글")["already_saved"])
                self.assertTrue(import_article(vault, url, "")["already_saved"])
                request.assert_called_once()
            [article] = article_list(vault)["articles"]
            self.assertEqual(article["title"], "이전 긱뉴스 글")
            self.assertEqual(article["url"], "https://news.hada.io/topic?id=5674")

    def test_publisher_url_does_not_accept_other_origins(self):
        for url in (
            "http://127.0.0.1/topic?id=1",
            "https://news.hada.io:8000/topic?id=1",
            "https://news.hada.io@example.org/topic?id=1",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                publisher_article(url)
