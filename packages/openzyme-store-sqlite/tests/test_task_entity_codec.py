from __future__ import annotations

import sqlite3

import pytest

from openzyme_contracts import DurableEventRecord
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_store_sqlite import SessionSQLiteKernelEntityCodec
from openzyme_store_sqlite import SQLiteControlStore
from openzyme_store_sqlite import SQLiteControlStoreError
from openzyme_store_sqlite import TaskSQLiteKernelEntityCodec
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration


def _database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(connection)
    install_store_schema_for_offline_migration(connection)
    return connection


def _request(command: str) -> UnitOfWorkRequest:
    return UnitOfWorkRequest(
        unit_of_work_id=f"uow-{command}",
        command_id=f"command-{command}",
        session_id="session-1",
        actor_id="agent-1",
        authority_lease_id="lease-1",
        authority_generation=1,
        authority_fence=1,
        expected_session_version=1,
        idempotency_key=f"idempotency-{command}",
        command_digest=canonical_sha256_digest({"command": command}),
    )


def _append_event(unit, command: str, *, entity_type: str, entity_id: str, state_version: int) -> None:  # noqa: ANN001, E501
    event = DurableEventRecord.create(
        event_id=f"event-{command}",
        session_id="session-1",
        event_type=f"{entity_type}.{command}",
        source_entity_type=entity_type,
        source_entity_id=entity_id,
        source_state_version=state_version,
        command_id=f"command-{command}",
        payload={"entity_id": entity_id},
    )
    occurrence = {"event_id": event.event_id}
    unit.append_event(event)
    unit.append_outbox(
        OutboxRecord(
            outbox_id=f"outbox-{command}",
            session_id="session-1",
            topic="openzyme.kernel.collaboration-events",
            occurrence_id=event.event_id,
            payload=occurrence,
            payload_digest=canonical_sha256_digest(occurrence),
            created_at="2026-08-20T00:00:00+00:00",
        )
    )


def _commit_create(
    store: SQLiteControlStore,
    *,
    command: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, object],
) -> None:
    unit = store.begin(_request(command))
    unit.stage(
        KernelStateMutation.create(
            mutation_id=f"mutation-{command}",
            kind=KernelMutationKind.CREATE,
            entity_type=entity_type,
            entity_id=entity_id,
            expected_state_version=None,
            payload=payload,
        )
    )
    _append_event(
        unit,
        command,
        entity_type=entity_type,
        entity_id=entity_id,
        state_version=1,
    )
    unit.commit()


def _task_payload(task_id: str, *, blocked_by: list[str]) -> dict[str, object]:
    return {
        "task_id": task_id,
        "session_id": "session-1",
        "subject": f"Task {task_id}",
        "description": "Exercise the explicit owner-table codec",
        "owner_actor_id": "agent-1",
        "priority": "normal",
        "kind": "general",
        "lane_id": None,
        "finish_validator_ids": ["validator.generic@1"],
        "status": "todo",
        "blocked_by": blocked_by,
        "assigned_ref": None,
        "failure_summary": None,
        "failure_ref": None,
        "evidence_refs": [],
        "finish_evidence_refs": [],
        "finish_validation_digest": None,
        "finished_by_actor_id": None,
        "created_at": "2026-08-20T00:01:00+00:00",
        "updated_at": "2026-08-20T00:01:00+00:00",
    }


def test_task_codec_round_trips_owner_and_dependency_tables_without_generic_payload() -> None:
    connection = _database()
    store = SQLiteControlStore(
        connection,
        codecs=(SessionSQLiteKernelEntityCodec(), TaskSQLiteKernelEntityCodec()),
    )
    _commit_create(
        store,
        command="session-created",
        entity_type="session",
        entity_id="session-1",
        payload={
            "session_id": "session-1",
            "project_id": "project-1",
            "title": "Kernel qualification",
            "objective": "prove Task owner mapping",
            "status": "active",
            "created_at": "2026-08-20T00:00:00+00:00",
            "updated_at": "2026-08-20T00:00:00+00:00",
        },
    )
    _commit_create(
        store,
        command="blocker-created",
        entity_type="task",
        entity_id="task-blocker",
        payload=_task_payload("task-blocker", blocked_by=[]),
    )
    created_payload = _task_payload("task-1", blocked_by=["task-blocker"])
    _commit_create(
        store,
        command="task-created",
        entity_type="task",
        entity_id="task-1",
        payload=created_payload,
    )

    first = store.read(entity_type="task", entity_id="task-1")
    assert first is not None
    assert first.state_version == 1
    assert first == KernelRecordSnapshot.create(
        entity_type="task",
        entity_id="task-1",
        state_version=1,
        payload=created_payload,
    )
    assert connection.execute(
        "SELECT blocked_by_task_id FROM task_dependencies WHERE task_id = ?",
        ("task-1",),
    ).fetchall() == [("task-blocker",)]

    replacement = {
        **created_payload,
        "status": "in_progress",
        "blocked_by": [],
        "evidence_refs": ["evidence-1"],
        "updated_at": "2026-08-20T00:02:00+00:00",
    }
    replace = store.begin(_request("task-updated"))
    replace.stage(
        KernelStateMutation.create(
            mutation_id="mutation-task-updated",
            kind=KernelMutationKind.REPLACE,
            entity_type="task",
            entity_id="task-1",
            expected_state_version=1,
            payload=replacement,
        )
    )
    _append_event(
        replace,
        "task-updated",
        entity_type="task",
        entity_id="task-1",
        state_version=2,
    )
    replace.commit()

    second = store.read(entity_type="task", entity_id="task-1")
    assert second is not None
    assert second.state_version == 2
    assert second == KernelRecordSnapshot.create(
        entity_type="task",
        entity_id="task-1",
        state_version=2,
        payload=replacement,
    )
    assert connection.execute(
        "SELECT COUNT(*) FROM task_dependencies WHERE task_id = ?", ("task-1",)
    ).fetchone() == (0,)
    assert "payload_json" not in {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(openzyme_store_kernel_entity_versions)"
        ).fetchall()
    }


def test_task_codec_rejects_owner_row_tamper_against_cas_digest() -> None:
    connection = _database()
    store = SQLiteControlStore(
        connection,
        codecs=(SessionSQLiteKernelEntityCodec(), TaskSQLiteKernelEntityCodec()),
    )
    _commit_create(
        store,
        command="session-created",
        entity_type="session",
        entity_id="session-1",
        payload={
            "session_id": "session-1",
            "project_id": "project-1",
            "title": "Kernel qualification",
            "objective": "prove Task tamper detection",
            "status": "active",
            "created_at": "2026-08-20T00:00:00+00:00",
            "updated_at": "2026-08-20T00:00:00+00:00",
        },
    )
    payload = _task_payload("task-1", blocked_by=[])
    _commit_create(
        store,
        command="task-created",
        entity_type="task",
        entity_id="task-1",
        payload=payload,
    )
    original = KernelRecordSnapshot.create(
        entity_type="task",
        entity_id="task-1",
        state_version=1,
        payload=payload,
    )
    assert store.read(entity_type="task", entity_id="task-1") == original

    connection.execute("UPDATE tasks SET subject = 'tampered' WHERE task_id = 'task-1'")
    connection.commit()

    with pytest.raises(SQLiteControlStoreError) as error:
        store.read(entity_type="task", entity_id="task-1")

    assert error.value.code == "sqlite_kernel_entity_digest_mismatch"
    assert error.value.mutation_applied is False
    assert error.value.fallback_performed is False
