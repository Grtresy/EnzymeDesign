from __future__ import annotations

from dataclasses import dataclass
import os
import signal
import sqlite3
import subprocess
import sys
import time

from openzyme_host_api.aox_cutover_evidence import AttemptRunContext


@dataclass(frozen=True, slots=True)
class ReturningRunner:
    create_sqlite: bool = True

    def __call__(self, context: AttemptRunContext) -> dict[str, object]:
        if self.create_sqlite:
            connection = sqlite3.connect(context.roots.sqlite_path)
            try:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("CREATE TABLE child_fact(value TEXT NOT NULL)")
                connection.execute("INSERT INTO child_fact VALUES ('sealed')")
                connection.commit()
            finally:
                connection.close()
        return {
            "product_path": {
                "runner_process_id": os.getpid(),
            },
            "scientific_outcome": {
                "status": "incomplete",
                "cutover_eligible": False,
            },
        }


@dataclass(frozen=True, slots=True)
class BlockingRunner:
    seconds: float = 60.0

    def __call__(self, context: AttemptRunContext) -> dict[str, object]:
        del context
        time.sleep(self.seconds)
        return {}


@dataclass(frozen=True, slots=True)
class IgnoringTermRunner:
    seconds: float = 60.0

    def __call__(self, context: AttemptRunContext) -> dict[str, object]:
        del context
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(self.seconds)
        return {}


@dataclass(frozen=True, slots=True)
class FailingRunner:
    def __call__(self, context: AttemptRunContext) -> dict[str, object]:
        del context
        raise RuntimeError("private /tmp/provider-secret")


@dataclass(frozen=True, slots=True)
class TruncatedRunner:
    def __call__(self, context: AttemptRunContext) -> dict[str, object]:
        del context
        os._exit(0)


@dataclass(frozen=True, slots=True)
class DescendantRunner:
    seconds: float = 60.0

    def __call__(self, context: AttemptRunContext) -> dict[str, object]:
        del context
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                f"import time; time.sleep({self.seconds!r})",
            ],
            close_fds=True,
        )
        return {"product_path": {}}


__all__ = [
    "BlockingRunner",
    "DescendantRunner",
    "FailingRunner",
    "IgnoringTermRunner",
    "ReturningRunner",
    "TruncatedRunner",
]
