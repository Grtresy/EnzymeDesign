from __future__ import annotations

import sqlite3

import pytest

from openzyme_contracts import DurableEventRecord
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_store_sqlite import LaneSQLiteKernelEntityCodec
from openzyme_store_sqlite import SQLiteControlStore
from openzyme_store_sqlite import SQLiteControlStoreError
from openzyme_store_sqlite import SessionSQLiteKernelEntityCodec
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
        actor_id="operator-1",
        authority_lease_id="bootstrap-authority",
        authority_generation=1,
        authority_fence=1,
        expected_session_version=1,
        idempotency_key=f"idempotency-{command}",
        command_digest=canonical_sha256_digest({"command": command}),
    )


def _event(
    command: str,
    *,
    entity_type: str,
    entity_id: str,
    state_version: int,
) -> tuple[DurableEventRecord, OutboxRecord]:
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
    payload = {"event_id": event.event_id}
    return event, OutboxRecord(
        outbox_id=f"outbox-{command}",
        session_id="session-1",
        topic="openzyme.kernel.collaboration-events",
        occurrence_id=event.event_id,
        payload=payload,
        payload_digest=canonical_sha256_digest(payload),
        created_at="2026-08-20T00:00:00+00:00",
    )


def _append_event(unit, command: str, **identity: object) -> None:  # noqa: ANN001
    event, outbox = _event(command, **identity)  # type: ignore[arg-type]
    unit.append_event(event)
    unit.append_outbox(outbox)


def test_lane_codec_round_trips_existing_owner_table_without_generic_payload() -> None:
    connection = _database()
    store = SQLiteControlStore(
        connection,
        codecs=(LaneSQLiteKernelEntityCodec(), SessionSQLiteKernelEntityCodec()),
    )
    session_payload = {
        "session_id": "session-1",
        "project_id": "project-1",
        "title": "Kernel qualification",
        "objective": "prove Lane owner mapping",
        "status": "active",
        "created_at": "2026-08-20T00:00:00+00:00",
        "updated_at": "2026-08-20T00:00:00+00:00",
    }
    bootstrap = store.begin(_request("bootstrap"))
    bootstrap.stage(
        KernelStateMutation.create(
            mutation_id="mutation-bootstrap",
            kind=KernelMutationKind.CREATE,
            entity_type="session",
            entity_id="session-1",
            expected_state_version=None,
            payload=session_payload,
        )
    )
    _append_event(
        bootstrap,
        "bootstrap",
        entity_type="session",
        entity_id="session-1",
        state_version=1,
    )
    bootstrap.commit()

    lane_payload = {
        "lane_id": "lane-1",
        "session_id": "session-1",
        "name": "analysis",
        "workspace_binding_id": None,
        "status": "idle",
        "created_at": "2026-08-20T00:01:00+00:00",
        "updated_at": "2026-08-20T00:01:00+00:00",
    }
    create = store.begin(_request("lane-created"))
    create.stage(
        KernelStateMutation.create(
            mutation_id="mutation-lane-created",
            kind=KernelMutationKind.CREATE,
            entity_type="lane",
            entity_id="lane-1",
            expected_state_version=None,
            payload=lane_payload,
        )
    )
    _append_event(
        create,
        "lane-created",
        entity_type="lane",
        entity_id="lane-1",
        state_version=1,
    )
    create.commit()

    first = store.read(entity_type="lane", entity_id="lane-1")
    assert first is not None
    assert first.state_version == 1
    assert first.payload == lane_payload
    assert connection.execute(
        "SELECT cwd, workspace_binding_id FROM lanes WHERE lane_id = 'lane-1'"
    ).fetchone() == (".", None)

    replacement = {
        **lane_payload,
        "workspace_binding_id": "workspace-1",
        "status": "active",
        "updated_at": "2026-08-20T00:02:00+00:00",
    }
    replace = store.begin(_request("lane-updated"))
    replace.stage(
        KernelStateMutation.create(
            mutation_id="mutation-lane-updated",
            kind=KernelMutationKind.REPLACE,
            entity_type="lane",
            entity_id="lane-1",
            expected_state_version=1,
            payload=replacement,
        )
    )
    _append_event(
        replace,
        "lane-updated",
        entity_type="lane",
        entity_id="lane-1",
        state_version=2,
    )
    replace.commit()

    second = store.read(entity_type="lane", entity_id="lane-1")
    assert second is not None
    assert second.state_version == 2
    assert second.payload == replacement
    assert "payload_json" not in {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(openzyme_store_kernel_entity_versions)"
        ).fetchall()
    }


def test_lane_codec_rejects_owner_row_tamper_against_cas_digest() -> None:
    connection = _database()
    store = SQLiteControlStore(
        connection,
        codecs=(LaneSQLiteKernelEntityCodec(), SessionSQLiteKernelEntityCodec()),
    )
    connection.execute(
        """
        INSERT INTO sessions
        (session_id, project_id, title, objective, status, created_at, updated_at)
        VALUES ('session-1', 'project-1', 'title', 'objective', 'active', 'now', 'now')
        """
    )
    connection.execute(
        """
        INSERT INTO lanes
        (lane_id, session_id, name, status, cwd, workspace_binding_id,
         created_at, updated_at)
        VALUES ('lane-1', 'session-1', 'analysis', 'idle', '.', NULL, 'now', 'now')
        """
    )
    expected = {
        "lane_id": "lane-1",
        "session_id": "session-1",
        "name": "analysis",
        "workspace_binding_id": None,
        "status": "idle",
        "created_at": "now",
        "updated_at": "now",
    }
    digest = canonical_sha256_digest(
        {
            "schema_version": "kernel_record_snapshot@1",
            "entity_type": "lane",
            "entity_id": "lane-1",
            "state_version": 1,
            "payload": expected,
        }
    )
    connection.execute(
        """
        INSERT INTO openzyme_store_kernel_entity_versions
        (entity_type, entity_id, owner_component_id, state_version, record_digest)
        VALUES ('lane', 'lane-1', 'openzyme.kernel', 1, ?)
        """,
        (digest,),
    )
    connection.commit()
    connection.execute("UPDATE lanes SET name = 'tampered' WHERE lane_id = 'lane-1'")
    connection.commit()

    with pytest.raises(SQLiteControlStoreError) as error:
        store.read(entity_type="lane", entity_id="lane-1")

    assert error.value.code == "sqlite_kernel_entity_digest_mismatch"
    assert error.value.mutation_applied is False
    assert error.value.fallback_performed is False
