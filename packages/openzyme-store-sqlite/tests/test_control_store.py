from __future__ import annotations

import json
import sqlite3

import pytest

from openzyme_contracts import DurableEventRecord
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_store_sqlite import SQLiteControlStore
from openzyme_store_sqlite import SQLiteControlStoreError


class _Codec:
    owner_id = "openzyme.kernel"
    table_names = ("test_owner_records",)

    def __init__(self, entity_type: str) -> None:
        self.entity_type = entity_type

    def read(self, connection, *, entity_id):  # noqa: ANN001
        row = connection.execute(
            "SELECT state_version, payload_json FROM test_owner_records "
            "WHERE entity_type = ? AND entity_id = ?",
            (self.entity_type, entity_id),
        ).fetchone()
        if row is None:
            return None
        return KernelRecordSnapshot.create(
            entity_type=self.entity_type,
            entity_id=entity_id,
            state_version=int(row[0]),
            payload=json.loads(row[1]),
        )

    def apply(self, connection, *, mutation, next_state_version):  # noqa: ANN001
        if mutation.kind is KernelMutationKind.DELETE:
            connection.execute(
                "DELETE FROM test_owner_records WHERE entity_type = ? AND entity_id = ?",
                (self.entity_type, mutation.entity_id),
            )
            return
        payload_json = json.dumps(dict(mutation.payload or {}), sort_keys=True)
        if mutation.kind is KernelMutationKind.CREATE:
            connection.execute(
                "INSERT INTO test_owner_records VALUES (?, ?, ?, ?)",
                (self.entity_type, mutation.entity_id, next_state_version, payload_json),
            )
        else:
            connection.execute(
                "UPDATE test_owner_records SET state_version = ?, payload_json = ? "
                "WHERE entity_type = ? AND entity_id = ?",
                (next_state_version, payload_json, self.entity_type, mutation.entity_id),
            )


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE test_owner_records (
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            state_version INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (entity_type, entity_id)
        );
        CREATE TABLE openzyme_store_durable_event_records (
            event_id TEXT PRIMARY KEY, command_id TEXT NOT NULL,
            event_kind TEXT NOT NULL, event_digest TEXT NOT NULL UNIQUE,
            event_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE openzyme_store_outbox_records (
            outbox_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL REFERENCES openzyme_store_durable_event_records(event_id),
            destination TEXT NOT NULL, payload_digest TEXT NOT NULL,
            payload_json TEXT NOT NULL, created_at TEXT NOT NULL, delivered_at TEXT
        );
        INSERT INTO test_owner_records VALUES
            ('session', 'session-1', 4, '{"status":"active"}'),
            ('task', 'task-1', 2, '{"status":"in_progress"}');
        """
    )
    return connection


def _request() -> UnitOfWorkRequest:
    return UnitOfWorkRequest(
        unit_of_work_id="uow-1",
        command_id="command-1",
        session_id="session-1",
        actor_id="agent-1",
        authority_lease_id="lease-1",
        authority_generation=3,
        authority_fence=8,
        expected_session_version=4,
        idempotency_key="task-update-1",
        command_digest=canonical_sha256_digest({"command": 1}),
    )


def _store(connection: sqlite3.Connection) -> SQLiteControlStore:
    return SQLiteControlStore(
        connection,
        codecs=(_Codec("session"), _Codec("task")),
    )


def test_control_store_commits_owner_table_event_and_outbox_atomically() -> None:
    connection = _connection()
    store = _store(connection)
    unit = store.begin(_request())
    unit.stage(
        KernelStateMutation.create(
            mutation_id="mutation-1",
            kind=KernelMutationKind.REPLACE,
            entity_type="task",
            entity_id="task-1",
            expected_state_version=2,
            payload={"status": "blocked"},
        )
    )
    event = DurableEventRecord.create(
        event_id="event-1",
        session_id="session-1",
        event_type="task.update_non_terminal",
        source_entity_type="task",
        source_entity_id="task-1",
        source_state_version=3,
        command_id="command-1",
        payload={"task_id": "task-1"},
    )
    unit.append_event(event)
    outbox_payload = {"event_id": event.event_id}
    unit.append_outbox(
        OutboxRecord(
            outbox_id="outbox-1",
            session_id="session-1",
            topic="openzyme.kernel.task-events",
            occurrence_id=event.event_id,
            payload=outbox_payload,
            payload_digest=canonical_sha256_digest(outbox_payload),
            created_at="2026-08-20T10:00:00+00:00",
        )
    )

    receipt = unit.commit()

    assert receipt.committed is True
    assert store.read(entity_type="task", entity_id="task-1").state_version == 3
    assert connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_durable_event_records"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_outbox_records"
    ).fetchone()[0] == 1


def test_control_store_cas_failure_rolls_back_business_event_and_outbox() -> None:
    connection = _connection()
    store = _store(connection)
    unit = store.begin(_request())
    unit.stage(
        KernelStateMutation.create(
            mutation_id="mutation-1",
            kind=KernelMutationKind.REPLACE,
            entity_type="task",
            entity_id="task-1",
            expected_state_version=1,
            payload={"status": "blocked"},
        )
    )
    with pytest.raises(SQLiteControlStoreError) as stale:
        unit.commit()
    assert stale.value.code == "sqlite_kernel_record_stale"
    assert store.read(entity_type="task", entity_id="task-1").state_version == 2
    assert connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_durable_event_records"
    ).fetchone()[0] == 0


def test_control_store_rejects_unmapped_entity_without_fallback_table() -> None:
    store = _store(_connection())
    with pytest.raises(SQLiteControlStoreError) as unmapped:
        store.read(entity_type="scientific_attempt", entity_id="attempt-1")
    assert unmapped.value.code == "sqlite_kernel_entity_unmapped"
