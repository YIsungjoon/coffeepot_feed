"""Run the local Obsidian feed web server and collection scheduler."""

import logging
from threading import Thread

from feed.http import FeedServer
from feed.settings import runtime_path, vault_path


LISTEN = ("127.0.0.1", 8765)


if __name__ == "__main__":
    log = runtime_path("feed_server.log")
    database = runtime_path("feed_server.sqlite3")
    for path in (log, database):
        path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log, encoding="utf-8", level=logging.INFO)
    try:
        with FeedServer(LISTEN, vault=vault_path(), database=database) as server:
            Thread(target=server.jobs.schedule, daemon=True).start()
            logging.info("Feed server listening on http://%s:%d", *LISTEN)
            server.serve_forever()
    except Exception:
        logging.exception("Feed server stopped")
        raise
