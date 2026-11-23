"""Run the feed collector in the background and record its exit status."""

import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from traceback import print_exc

from .classify import run as classify
from .collect import main as collect
from .graph import refresh_graph
from .settings import KST, runtime_path, vault_path


def run() -> int:
    path = runtime_path("collector.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", buffering=1) as log:
        with redirect_stdout(log), redirect_stderr(log):
            print(f"[{datetime.now(KST).isoformat(timespec='seconds')}] Collection started")
            try:
                collection_code = collect()
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
            try:
                topics, days = refresh_graph(vault_path())
                print(f"그래프 갱신: 주제 {topics}개, 일간 브리핑 {days}개")
            except (ValueError, OSError) as error:
                print(f"그래프 갱신: {error}", file=sys.stderr)
                exit_code = 1
            print(f"[{datetime.now(KST).isoformat(timespec='seconds')}] Collection finished, exit={exit_code}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run())
