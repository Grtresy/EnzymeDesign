from __future__ import annotations

import sqlite3
from datetime import UTC
from datetime import datetime

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import WorkspaceGenerationStatus
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel import MessageIngressCommand
from openzyme_kernel import MessageIngressKernelApplicationService
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_standard import standard_kernel_entity_codecs
from openzyme_store_sqlite import SQLiteControlStore
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
        codecs=standard_kernel_entity_codecs(),
    )


def _seed_runtime_binding(store: SQLiteControlStore) -> AgentAuthorityLease:
    now = "2026-08-21T12:00:00+00:00"
    lease = AgentAuthorityLease.create(
        lease_id="lease-master-1",
        session_id="session-1",
        agent_member_id="master-1",
        grants=(
            AuthorityGrant.create(
                grant_id="grant-message-1",
                scope_id="session-1",
                operations=("conversation.message.ingress",),
                generation=1,
                fence=1,
            ),
        ),
        generation=1,
        fence=1,
        state=AgentAuthorityLeaseState.ACTIVE,
        issued_at=now,
        expires_at=None,
        agent_id="agent-master-1",
        workspace_generation=1,
        policy_digest=_digest("message-policy"),
        idempotency_key="bootstrap-master-1",
        updated_at=now,
    )
    payloads = (
        (
            "session",
            "session-1",
            {
                "session_id": "session-1",
                "project_id": "project-1",
                "title": "SQLite message qualification",
                "objective": "Prove durable user ingress",
                "status": "active",
                "created_at": now,
                "updated_at": now,
            },
        ),
        (
            "agent_member",
            "master-1",
            {
                "agent_member_id": "master-1",
                "agent_id": "agent-master-1",
                "session_id": "session-1",
                "parent_agent_id": None,
                "lane_id": None,
                "name": "Master",
                "role": "master",
                "status": "active",
                "process_epoch": 1,
                "active_authority_lease_id": lease.lease_id,
                "workspace_generation": 1,
                "owned_task_ids": [],
                "retirement_reason": None,
                "terminal_proof_digest": None,
                "retirement_settled": False,
                "retired_at": None,
                "created_at": now,
                "updated_at": now,
            },
        ),
        (
            "workspace_generation",
            "workspace-1",
            WorkspaceGeneration(
                workspace_id="workspace-1",
                workspace_kind=WorkspaceKind.AGENT_LOCAL,
                session_id="session-1",
                owner_member_id="master-1",
                generation=1,
                state_version=3,
                status=WorkspaceGenerationStatus.READY,
                provider_id="openzyme.workspace.git-lfs",
                target_id="local:host",
                created_at=now,
                updated_at=now,
                root_identity_digest=_digest("workspace-root-1"),
                transition_receipt_digest=_digest("workspace-ready-1"),
                controlled_operation_id="workspace-provision-1",
            ).to_dict(),
        ),
        ("agent_authority_lease", lease.lease_id, lease.to_dict()),
    )
    for index, (entity_type, entity_id, payload) in enumerate(payloads, start=1):
        command_id = f"command-seed-message-runtime-{index}"
        request = UnitOfWorkRequest(
            unit_of_work_id=f"uow-seed-message-runtime-{index}",
            command_id=command_id,
            session_id="session-1",
            actor_id="master-1",
            authority_lease_id=lease.lease_id,
            authority_generation=1,
            authority_fence=1,
            expected_session_version=1,
            idempotency_key=f"seed-message-runtime-{index}",
            command_digest=_digest(f"seed-message-runtime-{index}"),
        )
        unit = store.begin(request)
        unit.stage(
            KernelStateMutation.create(
                mutation_id=f"mutation-{index:02d}-{entity_id}",
                kind=KernelMutationKind.CREATE,
                entity_type=entity_type,
                entity_id=entity_id,
                expected_state_version=None,
                payload=payload,
            )
        )
        event = DurableEventRecord.create(
            event_id=f"event-seed-message-runtime-{index}",
            session_id="session-1",
            event_type="qualification.message-runtime.seeded",
            source_entity_type=entity_type,
            source_entity_id=entity_id,
            source_state_version=1,
            command_id=command_id,
            payload={"mutation_applied": True},
        )
        unit.append_event(event)
        outbox_payload = {"event_id": event.event_id}
        unit.append_outbox(
            OutboxRecord(
                outbox_id=f"outbox-seed-message-runtime-{index}",
                session_id="session-1",
                topic="openzyme.qualification",
                occurrence_id=event.event_id,
                payload=outbox_payload,
                payload_digest=canonical_sha256_digest(outbox_payload),
                created_at=now,
            )
        )
        unit.commit()
        assert store.read(entity_type=entity_type, entity_id=entity_id) is not None
    return lease


def test_message_ingress_persists_exact_user_and_runtime_facts_in_sqlite() -> None:
    connection, store = _store()
    lease = _seed_runtime_binding(store)
    clock = DeterministicClock(datetime(2026, 8, 21, 12, tzinfo=UTC))
    service = MessageIngressKernelApplicationService(
        store=store,
        clock=clock,
        ids=DeterministicIdGenerator(),
    )

    receipt = service.execute(
        MessageIngressCommand(
            context=KernelCommandContext(
                command_id="command-message-1",
                session_id="session-1",
                actor_id="master-1",
                owner_plugin_id="openzyme.kernel",
                authority_lease_id=lease.lease_id,
                authority_generation=1,
                authority_fence=1,
                expected_session_version=1,
                extension_bundle_digest=_digest("plugin-free"),
                capability_binding_digest=_digest("binding"),
                idempotency_key="message-1",
                correlation_id="request-message-1",
                workspace_generation=1,
            ),
            message_id="message-1",
            source_actor_id="user:operator-1",
            content="Continue the bounded task",
            task_id=None,
            skill_keys=("workflow.code-review",),
        )
    )

    message = store.read(entity_type="conversation_message", entity_id="message-1")
    assert message is not None
    assert message.payload["sender_actor_id"] == "user:operator-1"
    assert message.payload["skill_keys"] == ("workflow.code-review",)
    inbox_row = connection.execute(
        "SELECT sender, sender_kind, recipient, payload_ref FROM inbox_messages"
    ).fetchone()
    assert inbox_row == (
        "user:operator-1",
        "user",
        "master-1",
        "message-1",
    )
    assert receipt.result["runtime_executed"] is False
    assert receipt.result["task_transition_performed"] is False
