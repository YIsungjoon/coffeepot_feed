"""Run the feed collector in the background and record its exit status."""

import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from traceback import print_exc

from collect_feeds import main
from feed.settings import COLLECTOR_LOG, KST


def run() -> int:
    with COLLECTOR_LOG.open("a", encoding="utf-8", buffering=1) as log:
        with redirect_stdout(log), redirect_stderr(log):
            print(f"[{datetime.now(KST).isoformat(timespec='seconds')}] Collection started")
            try:
                collection_code = main()
                from classify_feeds import run as classify

                classification_code = classify()
                exit_code = int(bool(collection_code or classification_code))
            except SystemExit as error:
                exit_code = error.code if isinstance(error.code, int) else 1
            except (ValueError, OSError) as error:
                print(f"주제 분류: {error}", file=sys.stderr)
                exit_code = 1
            except Exception:
                print_exc()
                exit_code = 1
            print(f"[{datetime.now(KST).isoformat(timespec='seconds')}] Collection finished, exit={exit_code}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run())
