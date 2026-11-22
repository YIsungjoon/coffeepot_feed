"""Run and manage the Obsidian feed collector from a local browser."""

import json
import logging
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime, time, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from time import sleep
from urllib.parse import quote, urlsplit

import yaml

from classify_feeds import FRONTMATTER, HEADINGS, TOPICS, public_excerpt
from collect_feeds import VAULT, public_link
from feed_briefing import daily_briefing
from recommend_feeds import MAX_INTEREST, recommend_news
from run_service import LOG_PATH
from save_feed import KST


ROOT = Path(__file__).resolve().parent
LISTEN = ("127.0.0.1", 8765)
HOSTS = {f"127.0.0.1:{LISTEN[1]}", f"localhost:{LISTEN[1]}"}
DAILY_AT = time(7, 30)
RETRY_DELAY = timedelta(minutes=15)
MAX_ATTEMPTS = 4


def article_list(vault: Path) -> dict:
    articles = []
    unreadable = 0
    for path in (vault / "10_Feeds" / "Articles").rglob("*.md"):
        if path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8")
            block = FRONTMATTER.match(text)
            props = yaml.safe_load(block["yaml"]) if block else None
        except (ValueError, OSError, yaml.YAMLError):
            unreadable += 1
            continue
        if not isinstance(props, dict) or props.get("type") != "feed-article":
            continue
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


class FeedJobs:
    def __init__(self, database: Path):
        self.database = database
        self.lock = Lock()
        self.running = False
        with closing(self.connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY,
                started_at TEXT NOT NULL,
                scheduled_day TEXT,
                finished_at TEXT,
                exit_code INTEGER
            )""")
            db.execute(
                "UPDATE runs SET finished_at = ?, exit_code = -1 WHERE finished_at IS NULL",
                (datetime.now(KST).isoformat(),),
            )

    def connect(self):
        db = sqlite3.connect(self.database)
        db.row_factory = sqlite3.Row
        return db

    def next_run(self, now: datetime) -> datetime:
        today = datetime.combine(now.date(), DAILY_AT, KST)
        tomorrow = today + timedelta(days=1)
        with closing(self.connect()) as db:
            attempts = db.execute(
                "SELECT finished_at, exit_code FROM runs WHERE scheduled_day = ? ORDER BY id DESC",
                (now.date().isoformat(),),
            ).fetchall()
        if not attempts:
            return today
        last = attempts[0]
        if last["exit_code"] in (0, None) or len(attempts) >= MAX_ATTEMPTS:
            return tomorrow
        return min(datetime.fromisoformat(last["finished_at"]) + RETRY_DELAY, tomorrow)

    def start(self, scheduled_day: str | None = None) -> bool:
        with self.lock:
            if self.running:
                return False
            with closing(self.connect()) as db, db:
                run_id = db.execute(
                    "INSERT INTO runs(started_at, scheduled_day) VALUES (?, ?)",
                    (datetime.now(KST).isoformat(), scheduled_day),
                ).lastrowid
            self.running = True
            Thread(target=self.collect, args=(run_id,), daemon=True).start()
            return True

    def collect(self, run_id: int):
        exit_code = -1
        try:
            worker = subprocess.run(
                [sys.executable, "-B", "-X", "utf8", str(ROOT / "run_service.py")],
                cwd=ROOT, timeout=300,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            exit_code = worker.returncode
        except (OSError, subprocess.TimeoutExpired):
            logging.exception("Collector process could not finish")
        finally:
            with self.lock:
                try:
                    with closing(self.connect()) as db, db:
                        db.execute(
                            "UPDATE runs SET finished_at = ?, exit_code = ? WHERE id = ?",
                            (datetime.now(KST).isoformat(), exit_code, run_id),
                        )
                finally:
                    self.running = False

    def schedule(self):
        while True:
            try:
                now = datetime.now(KST)
                if self.next_run(now) <= now:
                    self.start(now.date().isoformat())
            except sqlite3.Error:
                logging.exception("Could not check the daily collection schedule")
            sleep(10)

    def status(self) -> dict:
        with self.lock, closing(self.connect()) as db:
            last = db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
            running = self.running
        try:
            log = LOG_PATH.read_text(encoding="utf-8").splitlines()[-20:]
        except FileNotFoundError:
            log = []
        return {
            "running": running,
            "next_run": self.next_run(datetime.now(KST)).isoformat(),
            "last_run": dict(last) if last else None,
            "log": log,
        }


class FeedServer(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(LISTEN, Dashboard)
        try:
            self.jobs = FeedJobs(ROOT / "feed_server.sqlite3")
            self.recommendation_lock = Lock()
        except Exception:
            self.server_close()
            raise


class Dashboard(BaseHTTPRequestHandler):
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
        return self.headers.get("Host") in HOSTS

    def do_GET(self):
        if not self.local_host():
            self.send_json(403, {"error": "이 PC에서만 접근할 수 있습니다."})
            return
        path = urlsplit(self.path).path
        if path == "/":
            self.send_content(200, "text/html; charset=utf-8", (ROOT / "feed_reader.html").read_bytes())
        elif path in ("/admin", "/admin/"):
            self.send_content(200, "text/html; charset=utf-8", (ROOT / "feed_server.html").read_bytes())
        elif path == "/assets/feed-reader-hero.png" and (ROOT / "feed-reader-hero.png").is_file():
            self.send_content(200, "image/png", (ROOT / "feed-reader-hero.png").read_bytes())
        elif path == "/api/reader":
            self.send_json(200, reader_feed(VAULT))
        elif path == "/api/status":
            self.send_json(200, self.server.jobs.status())
        elif path == "/api/articles":
            self.send_json(200, article_list(VAULT))
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
            self.send_json(200, recommend_news(interest.strip(), reader_feed(VAULT)))
        except (OSError, ValueError) as error:
            self.send_json(503, {"error": f"추천을 완료하지 못했습니다. {error}"})
        finally:
            self.server.recommendation_lock.release()

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    logging.basicConfig(filename=ROOT / "feed_server.log", encoding="utf-8", level=logging.INFO)
    try:
        with FeedServer() as server:
            Thread(target=server.jobs.schedule, daemon=True).start()
            logging.info("Feed server listening on http://%s:%d", *LISTEN)
            server.serve_forever()
    except Exception:
        logging.exception("Feed server stopped")
        raise
