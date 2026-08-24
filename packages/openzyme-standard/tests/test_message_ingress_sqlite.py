from __future__ import annotations

import sqlite3
from datetime import UTC
from datetime import datetime
from pathlib import Path

import pytest

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
from openzyme_kernel import KernelContractError
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_standard import standard_kernel_entity_codecs
from openzyme_standard.workflow_registry import StandardExplicitEmptyWorkflowRegistry
from openzyme_store_sqlite import SQLiteControlStore
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _store(
    database: str | Path = ":memory:",
) -> tuple[sqlite3.Connection, SQLiteControlStore]:
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(connection)
    install_store_schema_for_offline_migration(connection)
    return connection, SQLiteControlStore(
        connection,
        codecs=standard_kernel_entity_codecs(),
    )


class _ExplodingWorkflowRegistry(StandardExplicitEmptyWorkflowRegistry):
    def resolve(self, request):  # noqa: ANN001, ANN201
        del request
        raise RuntimeError("registry-private-token-should-stay-private")


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
        reader=store,
        clock=clock,
        ids=DeterministicIdGenerator(),
        workflow_registry=StandardExplicitEmptyWorkflowRegistry(clock=clock),
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
            distribution_id="openzyme.standard",
            request_lineage_id="request-lineage-1",
            task_id=None,
            workflow_refs=(),
        )
    )

    message = store.read(entity_type="conversation_message", entity_id="message-1")
    assert message is not None
    assert message.payload["sender_actor_id"] == "user:operator-1"
    assert message.payload["skill_keys"] == ()
    assert message.payload["workflow_refs"] == ()
    assert message.payload["request_lineage_id"] == "request-lineage-1"
    workflow_authorities = store.list_for_session(
        entity_type="workflow_authority_binding",
        session_id="session-1",
        max_items=4,
    )
    assert len(workflow_authorities) == 1
    assert workflow_authorities[0].payload["request_lineage_id"] == (
        "request-lineage-1"
    )
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


def test_workflow_resolution_failure_pair_is_restart_stable_without_admission(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "workflow-resolution.sqlite3"
    connection, store = _store(database_path)
    lease = _seed_runtime_binding(store)
    clock = DeterministicClock(datetime(2026, 8, 21, 12, tzinfo=UTC))
    command = MessageIngressCommand(
        context=KernelCommandContext(
            command_id="command-message-failed-resolution",
            session_id="session-1",
            actor_id="master-1",
            owner_plugin_id="openzyme.kernel",
            authority_lease_id=lease.lease_id,
            authority_generation=1,
            authority_fence=1,
            expected_session_version=1,
            extension_bundle_digest=_digest("plugin-free"),
            capability_binding_digest=_digest("binding"),
            idempotency_key="message-failed-resolution",
            correlation_id="request-message-failed-resolution",
            workspace_generation=1,
        ),
        message_id="message-failed-resolution",
        source_actor_id="user:operator-1",
        content="Use only the exact adopted workflow",
        distribution_id="openzyme.standard",
        request_lineage_id="request-lineage-failed-resolution",
        workflow_refs=(),
    )
    service = MessageIngressKernelApplicationService(
        store=store,
        reader=store,
        clock=clock,
        ids=DeterministicIdGenerator(),
        workflow_registry=_ExplodingWorkflowRegistry(clock=clock),
    )

    with pytest.raises(KernelContractError) as rejected:
        service.execute(command)

    assert rejected.value.code == "workflow_registry_resolution_failed"
    assert rejected.value.details["diagnostic_recorded"] is True
    assert store.read(
        entity_type="conversation_message",
        entity_id=command.message_id,
    ) is None
    for entity_type in (
        "inbox_message",
        "agent_runtime_signal",
        "workflow_authority_binding",
        "runtime_signal_authority_link",
    ):
        assert store.list_for_session(
            entity_type=entity_type,
            session_id="session-1",
            max_items=8,
        ) == ()
    failures = store.list_for_session(
        entity_type="failure_observation",
        session_id="session-1",
        max_items=8,
    )
    diagnostics = store.list_for_session(
        entity_type="private_diagnostic",
        session_id="session-1",
        max_items=8,
    )
    assert len(failures) == len(diagnostics) == 1
    assert "registry-private-token" not in str(failures[0].payload)
    assert "registry-private-token" in diagnostics[0].payload["exception_message"]
    assert failures[0].payload["private_diagnostic_digest"] == (
        diagnostics[0].payload["record_digest"]
    )
    event_count = connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_durable_event_records"
    ).fetchone()[0]
    outbox_count = connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_outbox_records"
    ).fetchone()[0]
    failure_digest = failures[0].record_digest
    diagnostic_digest = diagnostics[0].record_digest
    connection.close()

    restarted_connection = sqlite3.connect(database_path)
    restarted_connection.execute("PRAGMA foreign_keys = ON")
    restarted_store = SQLiteControlStore(
        restarted_connection,
        codecs=standard_kernel_entity_codecs(),
    )
    restarted_clock = DeterministicClock(datetime(2026, 8, 21, 13, tzinfo=UTC))
    restarted_service = MessageIngressKernelApplicationService(
        store=restarted_store,
        reader=restarted_store,
        clock=restarted_clock,
        ids=DeterministicIdGenerator(),
        workflow_registry=_ExplodingWorkflowRegistry(clock=restarted_clock),
    )

    with pytest.raises(KernelContractError) as duplicate:
        restarted_service.execute(command)

    assert duplicate.value.code == "workflow_registry_resolution_failed"
    assert duplicate.value.details["failure_id"] == rejected.value.details["failure_id"]
    assert duplicate.value.details["diagnostic_id"] == (
        rejected.value.details["diagnostic_id"]
    )
    restarted_failures = restarted_store.list_for_session(
        entity_type="failure_observation",
        session_id="session-1",
        max_items=8,
    )
    restarted_diagnostics = restarted_store.list_for_session(
        entity_type="private_diagnostic",
        session_id="session-1",
        max_items=8,
    )
    assert restarted_failures[0].record_digest == failure_digest
    assert restarted_diagnostics[0].record_digest == diagnostic_digest
    assert restarted_connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_durable_event_records"
    ).fetchone()[0] == event_count
    assert restarted_connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_outbox_records"
    ).fetchone()[0] == outbox_count
    assert restarted_connection.execute("PRAGMA foreign_key_check").fetchall() == []
    restarted_connection.close()
