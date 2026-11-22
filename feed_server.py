"""Run the local Obsidian feed web server and collection scheduler."""

import logging
from threading import Thread

from feed.http import FeedServer
from feed.settings import ROOT, vault_path


LISTEN = ("127.0.0.1", 8765)


if __name__ == "__main__":
    logging.basicConfig(filename=ROOT / "feed_server.log", encoding="utf-8", level=logging.INFO)
    try:
        with FeedServer(LISTEN, vault=vault_path(), database=ROOT / "feed_server.sqlite3") as server:
            Thread(target=server.jobs.schedule, daemon=True).start()
            logging.info("Feed server listening on http://%s:%d", *LISTEN)
            server.serve_forever()
    except Exception:
        logging.exception("Feed server stopped")
        raise
