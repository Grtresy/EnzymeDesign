from __future__ import annotations

import sqlite3

import pytest

from openzyme_contracts import DurableEventRecord
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import WorkspaceGenerationStatus
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import canonical_sha256_digest
from openzyme_store_sqlite import AgentMemberSQLiteKernelEntityCodec
from openzyme_store_sqlite import SessionSQLiteKernelEntityCodec
from openzyme_store_sqlite import SQLiteControlStore
from openzyme_store_sqlite import WorkspaceGenerationSQLiteKernelEntityCodec
from openzyme_store_sqlite import WorkspaceRuntimeBindingSQLiteKernelEntityCodec
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration


NOW = "2026-08-21T00:00:00+00:00"


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
        actor_id="member-1",
        authority_lease_id="authority-1",
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
    mutations: tuple[KernelStateMutation, ...],
) -> None:
    unit = store.begin(_request(command))
    for mutation in mutations:
        unit.stage(mutation)
    source = mutations[0]
    next_version = (
        1 if source.expected_state_version is None else source.expected_state_version + 1
    )
    event = DurableEventRecord.create(
        event_id=f"event-{command}",
        session_id="session-1",
        event_type=f"{source.entity_type}.{command}",
        source_entity_type=source.entity_type,
        source_entity_id=source.entity_id,
        source_state_version=next_version,
        command_id=f"command-{command}",
        payload={"entity_id": source.entity_id},
    )
    unit.append_event(event)
    payload = {"event_id": event.event_id}
    unit.append_outbox(
        OutboxRecord(
            outbox_id=f"outbox-{command}",
            session_id="session-1",
            topic="openzyme.kernel.workspace-identity-qualification",
            occurrence_id=event.event_id,
            payload=payload,
            payload_digest=canonical_sha256_digest(payload),
            created_at=NOW,
        )
    )
    unit.commit()


def _generation(
    *,
    status: WorkspaceGenerationStatus,
    state_version: int,
    ready_identity: bool,
    generation: int = 1,
) -> WorkspaceGeneration:
    return WorkspaceGeneration(
        workspace_id="workspace-1",
        workspace_kind=WorkspaceKind.AGENT_LOCAL,
        session_id="session-1",
        owner_member_id="member-1",
        generation=generation,
        state_version=state_version,
        status=status,
        provider_id="openzyme.workspace.git.lfs",
        target_id="local:host",
        created_at=NOW,
        updated_at=NOW,
        root_identity_digest=(
            canonical_sha256_digest({"root": "workspace-1"})
            if ready_identity
            else None
        ),
        transition_receipt_digest=(
            canonical_sha256_digest({"receipt": status.value})
            if ready_identity
            else None
        ),
        controlled_operation_id=(
            f"operation-{status.value}" if ready_identity else None
        ),
    )


def test_workspace_generation_and_runtime_binding_share_exact_generation_identity() -> None:
    connection = _database()
    store = SQLiteControlStore(
        connection,
        codecs=(
            AgentMemberSQLiteKernelEntityCodec(),
            SessionSQLiteKernelEntityCodec(),
            WorkspaceGenerationSQLiteKernelEntityCodec(),
            WorkspaceRuntimeBindingSQLiteKernelEntityCodec(),
        ),
    )
    _commit(
        store,
        command="session-create",
        mutations=(
            KernelStateMutation.create(
                mutation_id="mutation-session",
                kind=KernelMutationKind.CREATE,
                entity_type="session",
                entity_id="session-1",
                expected_state_version=None,
                payload={
                    "session_id": "session-1",
                    "project_id": "project-1",
                    "title": "Workspace identity qualification",
                    "objective": "prove generation and runtime binding codecs",
                    "status": "active",
                    "created_at": NOW,
                    "updated_at": NOW,
                },
            ),
        ),
    )
    _commit(
        store,
        command="member-create",
        mutations=(
            KernelStateMutation.create(
                mutation_id="mutation-member",
                kind=KernelMutationKind.CREATE,
                entity_type="agent_member",
                entity_id="member-1",
                expected_state_version=None,
                payload={
                    "agent_member_id": "member-1",
                    "agent_id": "agent-1",
                    "session_id": "session-1",
                    "parent_agent_id": None,
                    "lane_id": None,
                    "name": "Master",
                    "role": "master",
                    "status": "active",
                    "process_epoch": 1,
                    "active_authority_lease_id": None,
                    "workspace_generation": 1,
                    "owned_task_ids": [],
                    "retirement_reason": None,
                    "terminal_proof_digest": None,
                    "retirement_settled": False,
                    "retired_at": None,
                    "created_at": NOW,
                    "updated_at": NOW,
                },
            ),
        ),
    )

    reserved = _generation(
        status=WorkspaceGenerationStatus.RESERVED,
        state_version=1,
        ready_identity=False,
    )
    _commit(
        store,
        command="workspace-reserve",
        mutations=(
            KernelStateMutation.create(
                mutation_id="mutation-workspace-reserve",
                kind=KernelMutationKind.CREATE,
                entity_type="workspace_generation",
                entity_id="workspace-1",
                expected_state_version=None,
                payload=reserved.to_dict(),
            ),
        ),
    )
    assert store.read(
        entity_type="workspace_generation", entity_id="workspace-1"
    ) == KernelRecordSnapshot.create(
        entity_type="workspace_generation",
        entity_id="workspace-1",
        state_version=1,
        payload=reserved.to_dict(),
    )

    provisioning = _generation(
        status=WorkspaceGenerationStatus.PROVISIONING,
        state_version=2,
        ready_identity=False,
    )
    _commit(
        store,
        command="workspace-provisioning",
        mutations=(
            KernelStateMutation.create(
                mutation_id="mutation-workspace-provisioning",
                kind=KernelMutationKind.REPLACE,
                entity_type="workspace_generation",
                entity_id="workspace-1",
                expected_state_version=1,
                payload=provisioning.to_dict(),
            ),
        ),
    )

    ready = _generation(
        status=WorkspaceGenerationStatus.READY,
        state_version=3,
        ready_identity=True,
    )
    runtime = ready.runtime_binding()
    _commit(
        store,
        command="workspace-ready",
        mutations=(
            KernelStateMutation.create(
                mutation_id="mutation-workspace-ready",
                kind=KernelMutationKind.REPLACE,
                entity_type="workspace_generation",
                entity_id="workspace-1",
                expected_state_version=2,
                payload=ready.to_dict(),
            ),
            KernelStateMutation.create(
                mutation_id="mutation-runtime-binding",
                kind=KernelMutationKind.CREATE,
                entity_type="workspace_runtime_binding",
                entity_id="workspace-1",
                expected_state_version=None,
                payload=runtime.to_dict(),
            ),
        ),
    )
    assert store.read(
        entity_type="workspace_runtime_binding", entity_id="workspace-1"
    ) == KernelRecordSnapshot.create(
        entity_type="workspace_runtime_binding",
        entity_id="workspace-1",
        state_version=1,
        payload=runtime.to_dict(),
    )

    retiring = _generation(
        status=WorkspaceGenerationStatus.RETIRING,
        state_version=4,
        ready_identity=True,
    )
    _commit(
        store,
        command="workspace-retiring",
        mutations=(
            KernelStateMutation.create(
                mutation_id="mutation-workspace-retiring",
                kind=KernelMutationKind.REPLACE,
                entity_type="workspace_generation",
                entity_id="workspace-1",
                expected_state_version=3,
                payload=retiring.to_dict(),
            ),
            KernelStateMutation.create(
                mutation_id="mutation-runtime-binding-delete",
                kind=KernelMutationKind.DELETE,
                    entity_type="workspace_runtime_binding",
                    entity_id="workspace-1",
                    expected_state_version=1,
                    payload=None,
                ),
        ),
    )
    assert store.read(
        entity_type="workspace_runtime_binding", entity_id="workspace-1"
    ) is None

    successor = _generation(
        generation=2,
        status=WorkspaceGenerationStatus.RESERVED,
        state_version=5,
        ready_identity=False,
    )
    _commit(
        store,
        command="workspace-successor",
        mutations=(
            KernelStateMutation.create(
                mutation_id="mutation-workspace-successor",
                kind=KernelMutationKind.REPLACE,
                entity_type="workspace_generation",
                entity_id="workspace-1",
                expected_state_version=4,
                payload=successor.to_dict(),
            ),
        ),
    )
    current = store.read(
        entity_type="workspace_generation",
        entity_id="workspace-1",
    )
    assert current == KernelRecordSnapshot.create(
        entity_type="workspace_generation",
        entity_id="workspace-1",
        state_version=5,
        payload=successor.to_dict(),
    )
    assert connection.execute(
        "SELECT generation, workspace_state_version, status "
        "FROM workspace_generation_records WHERE workspace_id = ? "
        "ORDER BY generation",
        ("workspace-1",),
    ).fetchall() == [(1, 4, "retiring"), (2, 5, "reserved")]
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    with pytest.raises(sqlite3.IntegrityError, match="mutation write authority rejected"):
        connection.execute(
            "UPDATE workspace_generation_records SET updated_at = ? WHERE workspace_id = ?",
            ("2026-08-21T00:01:00+00:00", "workspace-1"),
        )
