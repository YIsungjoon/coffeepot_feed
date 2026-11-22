"""Schedule collection jobs and track their runs in SQLite."""

import logging
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime, time, timedelta
from pathlib import Path
from threading import Lock, Thread
from time import sleep

from .settings import COLLECTOR_LOG, KST, ROOT


DAILY_AT = time(7, 30)
RETRY_DELAY = timedelta(minutes=15)
MAX_ATTEMPTS = 4


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
            log = COLLECTOR_LOG.read_text(encoding="utf-8").splitlines()[-20:]
        except FileNotFoundError:
            log = []
        return {
            "running": running,
            "next_run": self.next_run(datetime.now(KST)).isoformat(),
            "last_run": dict(last) if last else None,
            "log": log,
        }
