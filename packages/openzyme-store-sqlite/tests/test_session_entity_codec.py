from __future__ import annotations

import sqlite3

from openzyme_contracts import DurableEventRecord
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_store_sqlite import SQLiteControlStore
from openzyme_store_sqlite import SessionSQLiteKernelEntityCodec
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration


def _database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(connection)
    install_store_schema_for_offline_migration(connection)
    return connection


def _request(command: str, expected: int) -> UnitOfWorkRequest:
    return UnitOfWorkRequest(
        unit_of_work_id=f"uow-{command}",
        command_id=f"command-{command}",
        session_id="session-1",
        actor_id="operator-1",
        authority_lease_id="bootstrap-authority",
        authority_generation=1,
        authority_fence=1,
        expected_session_version=expected,
        idempotency_key=f"idempotency-{command}",
        command_digest=canonical_sha256_digest({"command": command}),
    )


def _event(command: str, version: int) -> tuple[DurableEventRecord, OutboxRecord]:
    event = DurableEventRecord.create(
        event_id=f"event-{command}",
        session_id="session-1",
        event_type=f"session.{command}",
        source_entity_type="session",
        source_entity_id="session-1",
        source_state_version=version,
        command_id=f"command-{command}",
        payload={"session_id": "session-1"},
    )
    payload = {"event_id": event.event_id}
    return event, OutboxRecord(
        outbox_id=f"outbox-{command}",
        session_id="session-1",
        topic="openzyme.kernel.session-events",
        occurrence_id=event.event_id,
        payload=payload,
        payload_digest=canonical_sha256_digest(payload),
        created_at="2026-08-20T00:00:00+00:00",
    )


def test_existing_sessions_table_codec_uses_non_payload_cas_ledger() -> None:
    connection = _database()
    store = SQLiteControlStore(
        connection,
        codecs=(SessionSQLiteKernelEntityCodec(),),
    )
    created_payload = {
        "session_id": "session-1",
        "project_id": "project-1",
        "title": "Kernel qualification",
        "objective": "prove target Store ownership",
        "status": "active",
        "created_at": "2026-08-20T00:00:00+00:00",
        "updated_at": "2026-08-20T00:00:00+00:00",
    }
    create = store.begin(_request("created", 1))
    create.stage(
        KernelStateMutation.create(
            mutation_id="mutation-created",
            kind=KernelMutationKind.CREATE,
            entity_type="session",
            entity_id="session-1",
            expected_state_version=None,
            payload=created_payload,
        )
    )
    event, outbox = _event("created", 1)
    create.append_event(event)
    create.append_outbox(outbox)
    create.commit()

    first = store.read(entity_type="session", entity_id="session-1")
    assert first is not None and first.state_version == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_kernel_entity_versions"
    ).fetchone()[0] == 1
    assert "payload_json" not in {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(openzyme_store_kernel_entity_versions)"
        ).fetchall()
    }
    assert connection.execute(
        "SELECT session_id FROM openzyme_store_kernel_entity_versions "
        "WHERE entity_type = 'session' AND entity_id = 'session-1'"
    ).fetchone() == ("session-1",)
    assert store.list_for_session(
        entity_type="session",
        session_id="session-1",
        max_items=1,
    ) == (first,)

    replacement = {**created_payload, "updated_at": "2026-08-20T00:01:00+00:00"}
    replace = store.begin(_request("updated", 1))
    replace.stage(
        KernelStateMutation.create(
            mutation_id="mutation-updated",
            kind=KernelMutationKind.REPLACE,
            entity_type="session",
            entity_id="session-1",
            expected_state_version=1,
            payload=replacement,
        )
    )
    event, outbox = _event("updated", 2)
    replace.append_event(event)
    replace.append_outbox(outbox)
    replace.commit()

    second = store.read(entity_type="session", entity_id="session-1")
    assert second is not None and second.state_version == 2
    assert second.payload["updated_at"] == "2026-08-20T00:01:00+00:00"
