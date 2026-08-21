from __future__ import annotations

import sqlite3

import pytest

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_store_sqlite import AgentAuthorityLeaseSQLiteKernelEntityCodec
from openzyme_store_sqlite import AgentMemberSQLiteKernelEntityCodec
from openzyme_store_sqlite import SessionSQLiteKernelEntityCodec
from openzyme_store_sqlite import SQLiteControlStore
from openzyme_store_sqlite import SQLiteControlStoreError
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _store() -> tuple[sqlite3.Connection, SQLiteControlStore]:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(connection)
    install_store_schema_for_offline_migration(connection)
    return connection, SQLiteControlStore(
        connection,
        codecs=(
            AgentAuthorityLeaseSQLiteKernelEntityCodec(),
            AgentMemberSQLiteKernelEntityCodec(),
            SessionSQLiteKernelEntityCodec(),
        ),
    )


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


def _commit(
    store: SQLiteControlStore,
    *,
    command: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, object],
    kind: KernelMutationKind = KernelMutationKind.CREATE,
    expected_state_version: int | None = None,
) -> None:
    unit = store.begin(_request(command))
    unit.stage(
        KernelStateMutation.create(
            mutation_id=f"mutation-{command}",
            kind=kind,
            entity_type=entity_type,
            entity_id=entity_id,
            expected_state_version=expected_state_version,
            payload=payload,
        )
    )
    state_version = 1 if expected_state_version is None else expected_state_version + 1
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
            topic="openzyme.kernel.authority-events",
            occurrence_id=event.event_id,
            payload=occurrence,
            payload_digest=canonical_sha256_digest(occurrence),
            created_at="2026-08-20T00:00:00+00:00",
        )
    )
    unit.commit()


def _bootstrap_owner_rows(store: SQLiteControlStore) -> None:
    _commit(
        store,
        command="session-created",
        entity_type="session",
        entity_id="session-1",
        payload={
            "session_id": "session-1",
            "project_id": "project-1",
            "title": "Authority codec qualification",
            "objective": "prove target authority owner mapping",
            "status": "active",
            "created_at": "2026-08-20T00:00:00+00:00",
            "updated_at": "2026-08-20T00:00:00+00:00",
        },
    )
    _commit(
        store,
        command="agent-created",
        entity_type="agent_member",
        entity_id="agent-1",
        payload={
            "agent_member_id": "agent-1",
            "agent_id": "agent-1",
            "session_id": "session-1",
            "parent_agent_id": None,
            "lane_id": None,
            "name": "Master",
            "role": "master",
            "status": "active",
            "process_epoch": 1,
            "active_authority_lease_id": None,
            "workspace_generation": None,
            "owned_task_ids": [],
            "retirement_reason": None,
            "terminal_proof_digest": None,
            "retirement_settled": False,
            "retired_at": None,
            "created_at": "2026-08-20T00:01:00+00:00",
            "updated_at": "2026-08-20T00:01:00+00:00",
        },
    )


def _lease(*, generation: int, fence: int, state: AgentAuthorityLeaseState) -> AgentAuthorityLease:
    grant = AuthorityGrant.create(
        grant_id=f"grant-{generation}",
        scope_id="session-1",
        operations=("task.create", "workspace.fs.read"),
        generation=generation,
        fence=fence,
    )
    return AgentAuthorityLease.create(
        lease_id="lease-1",
        session_id="session-1",
        agent_member_id="agent-1",
        grants=(grant,),
        generation=generation,
        fence=fence,
        state=state,
        issued_at="2026-08-20T00:02:00+00:00",
        expires_at="2026-08-21T00:02:00+00:00",
        agent_id="agent-1",
        workspace_generation=None,
        parent_lease_id=None,
        policy_digest=_digest("policy"),
        idempotency_key="authority-lease-1",
        updated_at="2026-08-20T00:02:00+00:00",
    )


def test_authority_codec_round_trips_target_record_without_legacy_semantics() -> None:
    connection, store = _store()
    _bootstrap_owner_rows(store)
    active = _lease(generation=1, fence=1, state=AgentAuthorityLeaseState.ACTIVE)
    _commit(
        store,
        command="authority-created",
        entity_type="agent_authority_lease",
        entity_id=active.lease_id,
        payload=active.to_dict(),
    )

    assert store.read(
        entity_type="agent_authority_lease", entity_id=active.lease_id
    ) == KernelRecordSnapshot.create(
        entity_type="agent_authority_lease",
        entity_id=active.lease_id,
        state_version=1,
        payload=active.to_dict(),
    )
    row = connection.execute(
        """
        SELECT record_kind, profile, status, schema_version,
               authority_state, authority_schema_version
        FROM agent_capability_lease_records WHERE lease_id = ?
        """,
        (active.lease_id,),
    ).fetchone()
    assert row == (
        "agent_authority_lease",
        None,
        None,
        None,
        "active",
        "agent_authority_lease@1",
    )

    revoked = _lease(
        generation=2,
        fence=2,
        state=AgentAuthorityLeaseState.REVOKED,
    )
    _commit(
        store,
        command="authority-revoked",
        entity_type="agent_authority_lease",
        entity_id=revoked.lease_id,
        payload=revoked.to_dict(),
        kind=KernelMutationKind.REPLACE,
        expected_state_version=1,
    )
    restored = store.read(
        entity_type="agent_authority_lease", entity_id=revoked.lease_id
    )
    assert restored is not None
    assert restored.state_version == 2
    assert AgentAuthorityLease.from_dict(restored.payload).state is (
        AgentAuthorityLeaseState.REVOKED
    )


def test_authority_codec_rejects_unadopted_legacy_row() -> None:
    connection, store = _store()
    _bootstrap_owner_rows(store)
    store._activate_mutation_gate(  # noqa: SLF001 - exact legacy fixture admission
        session_id="session-1",
        codecs=(AgentAuthorityLeaseSQLiteKernelEntityCodec(),),
    )
    # This is a pre-adoption historical row fixture, not a valid current graph.
    # Load it with FK enforcement disabled, as the offline reader would observe
    # legacy bytes before the owner-mapping transaction establishes target refs.
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute(
        """
        INSERT INTO agent_workspace_generation_reservations
        (reservation_id, session_id, agent_member_id, agent_id,
         workspace_generation, status, readiness_owner_kind,
         readiness_owner_ref, readiness_ref, readiness_digest, ready_at,
         replaced_by_generation, replaced_at, state_version, reserved_at,
         updated_at, immutable_fingerprint, canonical_digest, schema_version)
        VALUES ('reservation-1', 'session-1', 'agent-1', 'agent-1', 1,
                'reserved', NULL, NULL, NULL, NULL, NULL, NULL, NULL, 1,
                '2026-08-20T00:02:00+00:00',
                '2026-08-20T00:02:00+00:00', ?, ?,
                'agent_workspace_generation_reservation@1')
        """
        ,
        (_digest("reservation"), _digest("reservation-canonical")),
    )
    capabilities = (
        '["filesystem_read","filesystem_write","shell_process","git",'
        '"git_lfs","ordinary_network","upload","download"]'
    )
    digest = _digest("legacy")
    connection.execute(
        """
        INSERT INTO agent_capability_lease_records
        (lease_id, session_id, agent_member_id, agent_id, workspace_generation,
         profile, capabilities_json, capability_set_digest, target_ids_json,
         target_scope_digest, policy_version, policy_digest, idempotency_key,
         status, state_version, issued_at, updated_at, immutable_fingerprint,
         canonical_digest, schema_version)
        VALUES ('legacy-lease', 'session-1', 'agent-1', 'agent-1', 1,
                'general', ?, ?, '["local"]', ?, 'legacy@1', ?,
                'legacy-lease', 'pending_workspace', 1,
                '2026-08-20T00:02:00+00:00', '2026-08-20T00:02:00+00:00',
                ?, ?, 'agent_capability_lease@1')
        """,
        (capabilities, digest, digest, digest, digest, _digest("legacy-canonical")),
    )
    connection.commit()
    connection.execute("PRAGMA foreign_keys = ON")
    store._clear_mutation_gate()  # noqa: SLF001 - exact legacy fixture admission

    with pytest.raises(SQLiteControlStoreError) as error:
        store.read(entity_type="agent_authority_lease", entity_id="legacy-lease")

    assert error.value.code == "sqlite_authority_lease_not_adopted"
    assert error.value.mutation_applied is False
    assert error.value.fallback_performed is False
