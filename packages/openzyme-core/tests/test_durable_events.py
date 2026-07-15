from datetime import UTC
from datetime import datetime
import sqlite3

import pytest

from openzyme_core import CommandIdempotencyConflictError
from openzyme_core import CommandReceiptRecord
from openzyme_core import CoreRepositories
from openzyme_core import DurableEventConflictError
from openzyme_core import DurableEventRecord
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import Session
from openzyme_domain import SessionStatus


def _repositories() -> tuple[sqlite3.Connection, CoreRepositories]:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    now = datetime.now(UTC).isoformat()
    repositories.sessions.save(
        Session(
            session_id="sess_events",
            project_id="proj_events",
            title="Events",
            objective="Prove durable delivery",
            status=SessionStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
    )
    return connection, repositories


def _event(
    *,
    event_id: str = "evt_1",
    payload: dict[str, object] | None = None,
    event_type: str = "task.created",
) -> DurableEventRecord:
    return DurableEventRecord(
        event_id=event_id,
        session_id="sess_events",
        event_type=event_type,
        payload={"task_id": "task_1"} if payload is None else payload,
        created_at="2026-07-16T00:00:00+00:00",
    )


def test_durable_events_assign_monotonic_cursor_and_replay_after_cursor() -> None:
    connection, repositories = _repositories()
    first = repositories.durable_events.append(_event())
    second = repositories.durable_events.append(_event(event_id="evt_2"))

    assert first.cursor == 1
    assert second.cursor == 2
    assert repositories.durable_events.list_by_session(
        "sess_events", after_cursor=1
    ) == [second]
    assert repositories.durable_events.latest_cursor("sess_events") == 2
    connection.close()


def test_durable_event_identity_is_idempotent_but_conflicting_content_fails() -> None:
    connection, repositories = _repositories()
    first = repositories.durable_events.append(_event())

    assert repositories.durable_events.append(_event()) == first
    with pytest.raises(DurableEventConflictError):
        repositories.durable_events.append(_event(payload={"task_id": "task_2"}))
    connection.close()


def test_llm_trace_id_is_unique_per_session_and_conflicts_fail_closed() -> None:
    connection, repositories = _repositories()
    first = repositories.durable_events.append(
        _event(
            event_type="llm.response.created",
            payload={"trace_id": "trace_1", "output": "first"},
        )
    )

    with pytest.raises(DurableEventConflictError):
        repositories.durable_events.append(
            _event(
                event_id="evt_2",
                event_type="llm.response.created",
                payload={"trace_id": "trace_1", "output": "changed"},
            )
        )
    assert repositories.durable_events.latest_cursor("sess_events") == first.cursor
    connection.close()


def test_durable_event_rows_are_append_only() -> None:
    connection, repositories = _repositories()
    repositories.durable_events.append(_event())

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(
            "UPDATE durable_event_records SET event_type = 'changed' WHERE event_id = 'evt_1'"
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("DELETE FROM durable_event_records WHERE event_id = 'evt_1'")
    connection.close()


def test_command_receipt_reuses_same_request_and_rejects_key_collision() -> None:
    connection, repositories = _repositories()
    receipt = CommandReceiptRecord(
        command_receipt_id="receipt_1",
        scope_ref="session:sess_events",
        session_id="sess_events",
        command_type="task.create",
        idempotency_key="idem_1",
        request_digest="sha256:first",
        response={"task_id": "task_1"},
        created_at="2026-07-16T00:00:00+00:00",
        completed_at="2026-07-16T00:00:01+00:00",
    )

    stored = repositories.command_receipts.save(receipt)
    assert repositories.command_receipts.save(receipt) == stored
    with pytest.raises(CommandIdempotencyConflictError):
        repositories.command_receipts.save(
            CommandReceiptRecord(
                command_receipt_id="receipt_2",
                scope_ref=receipt.scope_ref,
                session_id=receipt.session_id,
                command_type=receipt.command_type,
                idempotency_key=receipt.idempotency_key,
                request_digest="sha256:different",
                response={"task_id": "task_2"},
                created_at=receipt.created_at,
                completed_at=receipt.completed_at,
            )
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            "UPDATE command_receipt_records SET response_json = '{}' "
            "WHERE command_receipt_id = 'receipt_1'"
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            "DELETE FROM command_receipt_records "
            "WHERE command_receipt_id = 'receipt_1'"
        )
    connection.close()
