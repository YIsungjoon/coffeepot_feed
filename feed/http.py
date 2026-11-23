"""Serve the local web pages and their HTTP APIs."""

import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from .archive import import_article
from .articles import article_list, reader_feed
from .jobs import FeedJobs
from .papers import ARXIV_DOI, DOI, MAX_PAGE, PaperLibrary, paper_topics, papers_in_topic, search_papers
from .recommendations import MAX_INTEREST, recommend_news
from .settings import ROOT
from .sources import search_coffeepot


WEB_ROOT = ROOT / "web"
STATIC_FILES = {
    "/": ("reader/index.html", "text/html; charset=utf-8"),
    "/admin": ("admin/index.html", "text/html; charset=utf-8"),
    "/admin/": ("admin/index.html", "text/html; charset=utf-8"),
    "/paper": ("paper/index.html", "text/html; charset=utf-8"),
    "/paper/": ("paper/index.html", "text/html; charset=utf-8"),
    "/assets/feed-reader-hero.png": ("reader/hero.png", "image/png"),
    "/assets/reader.css": ("reader/style.css", "text/css; charset=utf-8"),
    "/assets/reader.js": ("reader/main.js", "text/javascript; charset=utf-8"),
    "/assets/admin.css": ("admin/style.css", "text/css; charset=utf-8"),
    "/assets/admin.js": ("admin/main.js", "text/javascript; charset=utf-8"),
    "/assets/paper.css": ("paper/style.css", "text/css; charset=utf-8"),
    "/assets/paper.js": ("paper/main.js", "text/javascript; charset=utf-8"),
}
PAPER_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)


class FeedServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], *, vault: Path, database: Path):
        super().__init__(address, FeedHandler)
        self.vault = vault
        self.allowed_hosts = {f"127.0.0.1:{self.server_port}", f"localhost:{self.server_port}"}
        try:
            self.jobs = FeedJobs(database)
            self.recommendation_lock = Lock()
            self.paper_library = PaperLibrary(database.with_name("paper_library.sqlite3"))
        except Exception:
            self.server_close()
            raise


class FeedHandler(BaseHTTPRequestHandler):
    server: FeedServer

    def send_content(self, status: int, content_type: str, body: bytes, *, csp: str | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        if csp:
            self.send_header("Content-Security-Policy", csp)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, body: dict):
        self.send_content(status, "application/json; charset=utf-8", json.dumps(body, ensure_ascii=False).encode())

    def local_host(self) -> bool:
        return self.headers.get("Host") in self.server.allowed_hosts

    def do_GET(self):
        if not self.local_host():
            self.send_json(403, {"error": "이 PC에서만 접근할 수 있습니다."})
            return
        request = urlsplit(self.path)
        path = request.path
        if path in STATIC_FILES:
            name, content_type = STATIC_FILES[path]
            try:
                body = (WEB_ROOT / name).read_bytes()
            except FileNotFoundError:
                self.send_json(404, {"error": "페이지가 없습니다."})
                return
            self.send_content(200, content_type, body, csp=PAPER_CSP if name == "paper/index.html" else None)
        elif path == "/api/reader":
            self.send_json(200, reader_feed(self.server.vault))
        elif path == "/api/status":
            self.send_json(200, self.server.jobs.status())
        elif path == "/api/articles":
            self.send_json(200, article_list(self.server.vault))
        elif path == "/api/archive/coffeepot":
            self.coffeepot_search(parse_qs(request.query).get("q", [""])[0].strip())
        elif path == "/api/paper/search":
            self.paper_search(request.query)
        elif path == "/api/paper/topics":
            self.paper_results(paper_topics, wrap="topics")
        elif path == "/api/paper/topic-works":
            self.topic_works(request.query)
        elif path == "/api/paper/library":
            try:
                self.send_json(200, {"papers": self.server.paper_library.list()})
            except (sqlite3.Error, ValueError):
                self.send_json(500, {"error": "논문 보관함을 읽지 못했습니다."})
        else:
            self.send_json(404, {"error": "페이지가 없습니다."})

    def do_POST(self):
        host = self.headers.get("Host")
        if not self.local_host() or self.headers.get("Origin") != f"http://{host}":
            self.send_json(403, {"error": "피드 서비스 화면에서 다시 시도하세요."})
        elif self.path == "/api/recommend":
            self.recommend()
        elif self.path == "/api/archive/import":
            self.save_archive_article()
        elif self.path == "/api/paper/save":
            self.save_paper()
        elif self.path != "/api/run":
            self.send_json(404, {"error": "페이지가 없습니다."})
        elif self.server.jobs.start():
            self.send_json(202, {"running": True})
        else:
            self.send_json(409, {"error": "이미 수집 중입니다."})

    def read_json(self):
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 4096:
            raise ValueError
        data = json.loads(self.rfile.read(size))
        if not isinstance(data, dict):
            raise ValueError
        return data

    def coffeepot_search(self, query):
        if not 1 <= len(query) <= 120:
            self.send_json(400, {"error": "검색어를 1~120자로 입력해 주세요."})
            return
        try:
            results = search_coffeepot(query)
        except (ValueError, OSError):
            self.send_json(502, {"error": "커피팟 검색 결과를 불러오지 못했습니다."})
            return
        self.send_json(200, {"articles": [
            {"url": entry.url, "title": entry.title, "excerpt": entry.excerpt}
            for entry in results
        ]})

    def paper_search(self, query_string: str):
        try:
            params = {key: values[0] for key, values in parse_qs(query_string).items()}
            query = params.get("q", "").strip()
            source = params.get("source", "arxiv")
            page = int(params.get("page", "1"))
            order = params.get("order", "relevance")
            if (not 1 <= len(query) <= 180 or not 1 <= page <= MAX_PAGE
                    or source not in {"arxiv", "crossref"} or order not in {"relevance", "recent"}):
                raise ValueError
        except ValueError:
            self.send_json(400, {"error": "검색어와 검색 조건을 확인해 주세요."})
            return
        self.paper_results(search_papers, source, query, page, order)

    def topic_works(self, query_string: str):
        try:
            params = {key: values[0] for key, values in parse_qs(query_string).items()}
            subfield = params.get("subfield", "")
            page = int(params.get("page", "1"))
            order = params.get("order", "recent")
            if (not subfield.isascii() or not subfield.isdecimal() or not 1 <= len(subfield) <= 6
                    or not 1 <= page <= MAX_PAGE or order not in {"recent", "cited"}):
                raise ValueError
        except ValueError:
            self.send_json(400, {"error": "분야와 조회 조건을 확인해 주세요."})
            return
        self.paper_results(papers_in_topic, subfield, page, order)

    def paper_results(self, fetch, *args, wrap=None):
        try:
            result = fetch(*args)
        except HTTPError as error:
            if error.code == 429:
                self.send_json(429, {"error": "검색 출처가 요청을 일시 제한했습니다. 잠시 뒤 다시 시도해 주세요."})
            else:
                self.send_json(502, {"error": "논문 검색 출처에 연결하지 못했습니다."})
            return
        except (OSError, ValueError, KeyError, TypeError):
            self.send_json(502, {"error": "검색 결과를 불러오지 못했습니다. 잠시 뒤 다시 시도해 주세요."})
            return
        self.send_json(200, {wrap: result} if wrap else result)

    def save_archive_article(self):
        try:
            data = self.read_json()
            url, title = data.get("url"), data.get("title", "")
            if not isinstance(url, str) or not 1 <= len(url.strip()) <= 2000 or not isinstance(title, str) or len(title) > 400:
                raise ValueError
        except ValueError:
            self.send_json(400, {"error": "기사 주소와 제목을 확인해 주세요."})
            return
        try:
            result = import_article(self.server.vault, url.strip(), title.strip())
        except ValueError as error:
            self.send_json(422, {"error": str(error)})
            return
        except OSError:
            self.send_json(500, {"error": "기사를 벌트에 저장하지 못했습니다."})
            return
        self.send_json(200 if result["already_saved"] else 201, result)

    def save_paper(self):
        try:
            params = self.read_json()
            source, doi = params.get("source"), params.get("doi")
            if source not in ("arxiv", "crossref", "openalex") or not isinstance(doi, str) or len(doi) > 400:
                raise ValueError
            doi = doi.strip().lower()
            if not (ARXIV_DOI if source == "arxiv" else DOI).fullmatch(doi):
                raise ValueError
        except ValueError:
            self.send_json(400, {"error": "저장할 논문 정보가 올바르지 않습니다."})
            return
        try:
            paper, added = self.server.paper_library.save(source, doi)
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            self.send_json(502, {"error": "논문 정보를 저장하지 못했습니다. 잠시 뒤 다시 시도해 주세요."})
            return
        if paper is None:
            self.send_json(404, {"error": "출처에서 논문을 찾지 못했습니다."})
        else:
            self.send_json(201 if added else 200, {"paper": paper})

    def recommend(self):
        try:
            interest = self.read_json().get("interest")
            if not isinstance(interest, str) or not 1 <= len(interest.strip()) <= MAX_INTEREST:
                raise ValueError
        except ValueError:
            self.send_json(400, {"error": "관심사를 1~400자로 입력하세요."})
            return
        if not self.server.recommendation_lock.acquire(blocking=False):
            self.send_json(409, {"error": "추천을 만드는 중입니다. 잠시 뒤에 다시 시도하세요."})
            return
        try:
            self.send_json(200, recommend_news(interest.strip(), reader_feed(self.server.vault)))
        except (OSError, ValueError) as error:
            self.send_json(503, {"error": f"추천을 완료하지 못했습니다. {error}"})
        finally:
            self.server.recommendation_lock.release()

    def log_message(self, format, *args):
        pass
