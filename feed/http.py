"""Serve the two web pages and their local HTTP API."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from .articles import article_list, reader_feed
from .jobs import FeedJobs
from .recommendations import MAX_INTEREST, recommend_news
from .settings import ROOT


WEB_ROOT = ROOT / "web"
STATIC_FILES = {
    "/": ("reader/index.html", "text/html; charset=utf-8"),
    "/admin": ("admin/index.html", "text/html; charset=utf-8"),
    "/admin/": ("admin/index.html", "text/html; charset=utf-8"),
    "/assets/feed-reader-hero.png": ("reader/hero.png", "image/png"),
    "/assets/reader.css": ("reader/style.css", "text/css; charset=utf-8"),
    "/assets/reader.js": ("reader/main.js", "text/javascript; charset=utf-8"),
    "/assets/admin.css": ("admin/style.css", "text/css; charset=utf-8"),
    "/assets/admin.js": ("admin/main.js", "text/javascript; charset=utf-8"),
}


class FeedServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], *, vault: Path, database: Path):
        super().__init__(address, FeedHandler)
        self.vault = vault
        self.allowed_hosts = {f"127.0.0.1:{self.server_port}", f"localhost:{self.server_port}"}
        try:
            self.jobs = FeedJobs(database)
            self.recommendation_lock = Lock()
        except Exception:
            self.server_close()
            raise


class FeedHandler(BaseHTTPRequestHandler):
    server: FeedServer

    def send_content(self, status: int, content_type: str, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
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
        path = urlsplit(self.path).path
        if path in STATIC_FILES:
            name, content_type = STATIC_FILES[path]
            try:
                body = (WEB_ROOT / name).read_bytes()
            except FileNotFoundError:
                self.send_json(404, {"error": "페이지가 없습니다."})
                return
            self.send_content(200, content_type, body)
        elif path == "/api/reader":
            self.send_json(200, reader_feed(self.server.vault))
        elif path == "/api/status":
            self.send_json(200, self.server.jobs.status())
        elif path == "/api/articles":
            self.send_json(200, article_list(self.server.vault))
        else:
            self.send_json(404, {"error": "페이지가 없습니다."})

    def do_POST(self):
        host = self.headers.get("Host")
        if not self.local_host() or self.headers.get("Origin") != f"http://{host}":
            self.send_json(403, {"error": "관리 화면에서 다시 시도하세요."})
        elif self.path == "/api/recommend":
            self.recommend()
        elif self.path != "/api/run":
            self.send_json(404, {"error": "페이지가 없습니다."})
        elif self.server.jobs.start():
            self.send_json(202, {"running": True})
        else:
            self.send_json(409, {"error": "이미 수집 중입니다."})

    def recommend(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4096:
                raise ValueError
            payload = json.loads(self.rfile.read(size))
            interest = payload.get("interest") if isinstance(payload, dict) else None
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
