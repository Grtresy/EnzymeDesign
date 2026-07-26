from __future__ import annotations

from dataclasses import dataclass
import os
import signal
import sqlite3
import subprocess
import sys
import time

from openzyme_core import CoreRepositories
from openzyme_core import MutationScopeService
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import MutationScopeKind
from openzyme_domain import MutationWriterKind
from openzyme_domain import Session
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
class TerminalRolloverRunner:
    active_writer: bool = False

    def __call__(self, context: AttemptRunContext) -> dict[str, object]:
        connection = connect_sqlite(
            str(context.roots.sqlite_path),
            enable_wal=True,
        )
        try:
            apply_sqlite_migrations(connection)
            repositories = CoreRepositories.from_connection(connection)
            session = Session.create(
                session_id="sess_supervised_rollover",
                project_id="proj_supervised_rollover",
                title="Supervised rollover",
                objective="Prove writer-free post-closure scope settlement",
            )
            repositories.sessions.save(session)
            service = MutationScopeService(repositories)
            pre_attempt = service.open_scope(
                session_id=session.session_id,
                scope_kind=MutationScopeKind.SESSION,
                scope_ref="pre-attempt",
            )
            service.begin_freeze(pre_attempt.scope_id)
            issued = service.issue_quiescence_receipt(pre_attempt.scope_id)
            service.seal_scope(
                pre_attempt.scope_id,
                receipt_id=issued.receipt.receipt_id,
            )
            post_attempt = service.open_scope(
                session_id=session.session_id,
                scope_kind=MutationScopeKind.SESSION,
                scope_ref="post-attempt",
                parent_scope_id=pre_attempt.scope_id,
            )
            if self.active_writer:
                service.register_writer(
                    scope_id=post_attempt.scope_id,
                    owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
                    owner_ref="still-active",
                    trusted_root=True,
                )
        finally:
            connection.close()
        return {
            "product_path": {
                "runner_process_id": os.getpid(),
                "terminal_rollover_created": True,
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
    "TerminalRolloverRunner",
    "TruncatedRunner",
]
