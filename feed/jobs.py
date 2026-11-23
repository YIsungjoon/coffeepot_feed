"""Schedule collection jobs and track their runs in SQLite."""

import logging
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime, time, timedelta
from pathlib import Path
from threading import Lock, Thread
from time import monotonic, sleep

from .settings import KST, ROOT, runtime_path


DAILY_AT = time(7, 30)
REFRESH_SECONDS = 300
RETRY_DELAY = timedelta(minutes=15)
MAX_ATTEMPTS = 4


class FeedJobs:
    def __init__(self, database: Path):
        self.database = database
        self.lock = Lock()
        self.running = False
        self.refresh_at = monotonic()
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
            self.refresh_at = monotonic() + REFRESH_SECONDS
            Thread(target=self.collect, args=(run_id,), daemon=True).start()
            return True

    def collect(self, run_id: int):
        exit_code = -1
        try:
            worker = subprocess.run(
                [sys.executable, "-B", "-X", "utf8", "-m", "feed.worker"],
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
                elif monotonic() >= self.refresh_at:
                    self.start()
            except sqlite3.Error:
                logging.exception("Could not check the daily collection schedule")
            sleep(10)

    def collection_state(self) -> dict:
        with self.lock, closing(self.connect()) as db:
            last = db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
            return {"running": self.running, "last_run": dict(last) if last else None}

    def status(self) -> dict:
        collection = self.collection_state()
        refresh_in = max(0, self.refresh_at - monotonic())
        try:
            log = runtime_path("collector.log").read_text(encoding="utf-8").splitlines()[-20:]
        except FileNotFoundError:
            log = []
        now = datetime.now(KST)
        daily = self.next_run(now)
        return {
            **collection,
            "next_run": daily.isoformat(),
            "next_refresh": min(daily, now + timedelta(seconds=refresh_in)).isoformat(),
            "log": log,
        }
