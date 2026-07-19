from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC
from datetime import datetime
import sqlite3
from threading import Event
from threading import Thread
import time

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import RuntimeWriteFencingError
from openzyme_core import SessionRuntimeLeaseAcquireResult
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import Lane
from openzyme_domain import LaneStatus
from openzyme_domain import Session
from openzyme_domain import SessionRuntimeLease
from openzyme_domain import SessionRuntimeLeaseMode
from openzyme_domain import Task


def _provider(tmp_path, *, busy_timeout_ms: int = 5_000) -> SQLiteRepositoryProvider:
    database_path = tmp_path / "uow.sqlite3"
    return SQLiteRepositoryProvider(
        str(database_path),
        busy_timeout_ms=busy_timeout_ms,
    )


@pytest.mark.parametrize(
    ("database_path", "uri"),
    (
        (":memory:", False),
        ("file::memory:?cache=shared", True),
        ("file:openzyme-uow?mode=memory&cache=shared", True),
    ),
)
def test_repository_provider_rejects_process_local_memory_databases(
    database_path: str,
    uri: bool,
) -> None:
    with pytest.raises(ValueError, match="file-backed SQLite database"):
        SQLiteRepositoryProvider(database_path, uri=uri)


def test_repository_provider_initializes_an_empty_file_database(tmp_path) -> None:
    provider = SQLiteRepositoryProvider(str(tmp_path / "fresh.sqlite3"))

    with provider.read() as uow:
        assert uow.connection.execute("PRAGMA user_version").fetchone()[0] > 0
        assert uow.repositories.sessions.list_by_project("missing") == []


def test_connect_sqlite_is_thread_affine_by_default(tmp_path) -> None:
    connection = connect_sqlite(str(tmp_path / "thread-affine.sqlite3"))
    errors: list[BaseException] = []
    try:
        thread = Thread(
            target=lambda: _capture_connection_error(connection, errors),
        )
        thread.start()
        thread.join(timeout=5)
    finally:
        connection.close()

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], sqlite3.ProgrammingError)


def test_repository_provider_configures_owned_connections(tmp_path) -> None:
    provider = _provider(tmp_path, busy_timeout_ms=3_210)

    with provider.read() as uow:
        connection = uow.connection
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 3_210
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        assert connection.in_transaction is False
        with pytest.raises(sqlite3.OperationalError, match="readonly database"):
            uow.repositories.sessions.save(
                Session.create("sess_read_only", "proj_001", "Read", "Read")
            )


def test_repository_provider_initializes_schema_once_before_scopes(tmp_path) -> None:
    database_path = tmp_path / "provider-initialized.sqlite3"

    provider = SQLiteRepositoryProvider(str(database_path))

    assert database_path.is_file()
    with provider.read() as uow:
        table = uow.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'sessions'"
        ).fetchone()
        assert table is not None


def test_repository_provider_connections_reject_cross_thread_use(tmp_path) -> None:
    provider = _provider(tmp_path)
    errors: list[BaseException] = []

    with provider.read() as uow:
        thread = Thread(
            target=lambda: _capture_connection_error(uow.connection, errors),
        )
        thread.start()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], sqlite3.ProgrammingError)
    assert "created in a thread" in str(errors[0])


def _capture_connection_error(
    connection: sqlite3.Connection,
    errors: list[BaseException],
) -> None:
    try:
        connection.execute("SELECT 1").fetchone()
    except BaseException as exc:
        errors.append(exc)


def test_repository_provider_scopes_never_share_a_connection(tmp_path) -> None:
    provider = _provider(tmp_path)

    with provider.read() as first:
        with provider.read() as second:
            assert first.connection is not second.connection
            assert first.repositories.sessions.connection is first.connection
            assert second.repositories.sessions.connection is second.connection


@pytest.mark.parametrize("mode", ("read", "write", "connection_scope"))
def test_repository_provider_scope_closes_its_owned_connection(
    tmp_path,
    mode: str,
) -> None:
    provider = _provider(tmp_path)
    scope_factory = getattr(provider, mode)

    with scope_factory() as scope:
        connection = scope.connection
        assert connection.execute("SELECT 1").fetchone()[0] == 1

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")


def test_unit_of_work_rolls_back_all_repositories_and_provider_recovers(
    tmp_path,
) -> None:
    provider = _provider(tmp_path)
    session = Session.create("sess_rollback", "proj_001", "Rollback", "Rollback")
    lane = Lane(
        lane_id="lane_rollback",
        session_id=session.session_id,
        name="rollback",
        status=LaneStatus.IDLE,
        cwd="/tmp/rollback",
        branch_name=None,
        claimed_ref=None,
        created_at="2026-07-16T00:00:00+00:00",
        updated_at="2026-07-16T00:00:00+00:00",
    )

    with pytest.raises(ValueError, match="missing_lane"):
        with provider.write() as uow:
            uow.repositories.sessions.save(session)
            uow.repositories.lanes.save(lane)
            uow.repositories.tasks.save(
                Task.create(
                    "task_invalid_lane",
                    session.session_id,
                    "Invalid lane",
                    "Force the command to fail midway.",
                    lane_id="missing_lane",
                )
            )

    with provider.read() as uow:
        assert uow.repositories.sessions.get(session.session_id) is None
        assert uow.repositories.lanes.get(lane.lane_id) is None

    recovered = Session.create("sess_recovered", "proj_001", "Recovered", "Recovered")
    with provider.write() as uow:
        uow.repositories.sessions.save(recovered)
    with provider.read() as uow:
        assert uow.repositories.sessions.get(recovered.session_id) == recovered


def test_standalone_repository_save_still_commits(tmp_path) -> None:
    database_path = tmp_path / "standalone.sqlite3"
    connection = connect_sqlite(str(database_path))
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    session = Session.create("sess_standalone", "proj_001", "Standalone", "Standalone")

    repositories.sessions.save(session)
    connection.close()

    reopened = connect_sqlite(str(database_path))
    try:
        assert CoreRepositories.from_connection(reopened).sessions.get(session.session_id) == session
    finally:
        reopened.close()


def test_runtime_write_fence_rejects_stale_worker_business_write(tmp_path) -> None:
    provider = _provider(tmp_path)
    session = Session.create("sess_fenced", "proj_001", "Fenced", "Fenced")
    task = Task.create(
        "task_fenced",
        session.session_id,
        "Original subject",
        "Reject late worker writes.",
    )
    with provider.write() as owner:
        owner.repositories.sessions.save(session)
        owner.repositories.tasks.save(task)

    with provider.connection_scope() as coordinator:
        acquired = coordinator.repositories.session_runtime_leases.acquire(
            session_id=session.session_id,
            owner_id="worker:first",
            mode=SessionRuntimeLeaseMode.TEST,
            lease_seconds=60,
        )
        assert acquired.lease is not None
        first_lease = acquired.lease
        with provider.connection_scope() as worker:
            with worker.repositories.runtime_write_fence(first_lease):
                coordinator.connection.execute(
                    "UPDATE session_runtime_leases SET expires_at = ? WHERE lease_token = ?",
                    ("2020-01-01T00:00:00+00:00", first_lease.lease_token),
                )
                coordinator.connection.commit()
                replacement = coordinator.repositories.session_runtime_leases.acquire(
                    session_id=session.session_id,
                    owner_id="worker:replacement",
                    mode=SessionRuntimeLeaseMode.TEST,
                    lease_seconds=60,
                )
                assert replacement.acquired is True
                assert replacement.lease is not None
                assert replacement.lease.fencing_token == first_lease.fencing_token + 1

                with pytest.raises(RuntimeWriteFencingError, match="stale business write"):
                    worker.repositories.tasks.save(
                        replace(task, subject="Late stale write")
                    )

    with provider.read() as owner:
        assert owner.repositories.tasks.get(task.task_id) == task


def test_runtime_write_fence_rejects_cross_session_write(tmp_path) -> None:
    provider = _provider(tmp_path)
    first = Session.create("sess_fence_a", "proj_001", "A", "A")
    second = Session.create("sess_fence_b", "proj_001", "B", "B")
    with provider.write() as owner:
        owner.repositories.sessions.save(first)
        owner.repositories.sessions.save(second)
    with provider.connection_scope() as owner:
        acquired = owner.repositories.session_runtime_leases.acquire(
            session_id=first.session_id,
            owner_id="worker:first",
            mode=SessionRuntimeLeaseMode.TEST,
            lease_seconds=60,
        )
        assert acquired.lease is not None
        with owner.repositories.runtime_write_fence(acquired.lease):
            with pytest.raises(RuntimeWriteFencingError, match="crossed"):
                owner.repositories.tasks.save(
                    Task.create(
                        "task_other_session",
                        second.session_id,
                        "Cross-session write",
                        "Must be rejected by the lease scope.",
                    )
                )


def test_read_scope_does_not_block_a_short_write_scope(tmp_path) -> None:
    provider = _provider(tmp_path)
    session = Session.create("sess_during_read", "proj_001", "Read", "Read")

    with provider.read() as read_uow:
        assert read_uow.connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_save_session, provider, session)
            future.result(timeout=5)

    with provider.read() as uow:
        assert uow.repositories.sessions.get(session.session_id) == session


def test_concurrent_short_write_scopes_serialize_without_shared_connection(
    tmp_path,
) -> None:
    provider = _provider(tmp_path)
    first_entered = Event()
    release_first = Event()
    second_attempting = Event()
    connection_ids: list[int] = []
    first_session = Session.create("sess_first", "proj_001", "First", "First")
    second_session = Session.create("sess_second", "proj_001", "Second", "Second")

    def hold_first_write() -> None:
        with provider.write() as uow:
            connection_ids.append(id(uow.connection))
            uow.repositories.sessions.save(first_session)
            first_entered.set()
            assert release_first.wait(timeout=5)

    def wait_for_sqlite_write_lock() -> None:
        assert first_entered.wait(timeout=5)
        second_attempting.set()
        with provider.write() as uow:
            connection_ids.append(id(uow.connection))
            uow.repositories.sessions.save(second_session)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(hold_first_write)
        assert first_entered.wait(timeout=5)
        second = executor.submit(wait_for_sqlite_write_lock)
        assert second_attempting.wait(timeout=5)
        assert second.done() is False
        release_first.set()
        first.result(timeout=5)
        second.result(timeout=5)

    assert len(connection_ids) == 2
    assert connection_ids[0] != connection_ids[1]
    with provider.read() as uow:
        assert uow.repositories.sessions.get(first_session.session_id) == first_session
        assert uow.repositories.sessions.get(second_session.session_id) == second_session


def test_heartbeat_cannot_revive_lease_expired_while_waiting_for_write_lock(
    tmp_path,
) -> None:
    provider = _provider(tmp_path)
    session = Session.create(
        "sess_heartbeat_lock",
        "proj_001",
        "Heartbeat lock",
        "Do not revive an expired lease.",
    )
    with provider.write() as owner:
        owner.repositories.sessions.save(session)
    with provider.connection_scope() as owner:
        acquired = owner.repositories.session_runtime_leases.acquire(
            session_id=session.session_id,
            owner_id="worker:heartbeat",
            mode=SessionRuntimeLeaseMode.TEST,
            lease_seconds=1,
        )
    assert acquired.lease is not None
    original_lease = acquired.lease
    heartbeat_attempting = Event()

    def heartbeat_after_lock() -> SessionRuntimeLease | None:
        with provider.connection_scope() as owner:
            heartbeat_attempting.set()
            return owner.repositories.session_runtime_leases.heartbeat(
                session_id=session.session_id,
                owner_id=original_lease.owner_id,
                lease_token=original_lease.lease_token,
                lease_seconds=30,
            )

    with provider.connection_scope() as blocker:
        blocker.connection.execute("BEGIN IMMEDIATE")
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(heartbeat_after_lock)
            assert heartbeat_attempting.wait(timeout=5)
            expiry = datetime.fromisoformat(original_lease.expires_at)
            time.sleep(
                max(0.0, (expiry - datetime.now(tz=UTC)).total_seconds()) + 0.2
            )
            assert future.done() is False
            blocker.connection.rollback()
            heartbeat = future.result(timeout=5)

    assert heartbeat is None
    with provider.read() as owner:
        persisted = owner.repositories.session_runtime_leases.get_by_token(
            original_lease.lease_token
        )
        assert persisted is not None
        assert persisted.heartbeat_at == original_lease.heartbeat_at
        assert persisted.expires_at == original_lease.expires_at
        assert (
            owner.repositories.session_runtime_leases.get_active(session.session_id)
            is None
        )


def test_lease_acquire_timestamps_after_waiting_for_write_lock(tmp_path) -> None:
    provider = _provider(tmp_path)
    session = Session.create(
        "sess_acquire_lock",
        "proj_001",
        "Acquire lock",
        "Start the lease only after acquiring the writer lock.",
    )
    with provider.write() as owner:
        owner.repositories.sessions.save(session)
    acquire_attempting = Event()

    def acquire_after_lock() -> SessionRuntimeLeaseAcquireResult:
        with provider.connection_scope() as owner:
            acquire_attempting.set()
            return owner.repositories.session_runtime_leases.acquire(
                session_id=session.session_id,
                owner_id="worker:acquire",
                mode=SessionRuntimeLeaseMode.TEST,
                lease_seconds=1,
            )

    with provider.connection_scope() as blocker:
        blocker.connection.execute("BEGIN IMMEDIATE")
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(acquire_after_lock)
            assert acquire_attempting.wait(timeout=5)
            time.sleep(1.2)
            assert future.done() is False
            blocker.connection.rollback()
            acquired = future.result(timeout=5)

    assert acquired.acquired is True
    lease = acquired.lease
    assert lease is not None
    assert datetime.fromisoformat(lease.expires_at) > datetime.now(tz=UTC)


def _save_session(provider: SQLiteRepositoryProvider, session: Session) -> None:
    with provider.write() as uow:
        uow.repositories.sessions.save(session)
