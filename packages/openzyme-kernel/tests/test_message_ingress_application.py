from __future__ import annotations

from datetime import UTC
from datetime import datetime

import pytest

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel import KernelContractError
from openzyme_kernel import MessageIngressCommand
from openzyme_kernel import MessageIngressKernelApplicationService
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_kernel.testing import InMemoryControlStore


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _fixture(
    *,
    workspace_generation: int | None = 1,
) -> tuple[InMemoryControlStore, MessageIngressKernelApplicationService, MessageIngressCommand]:
    clock = DeterministicClock(datetime(2026, 8, 21, 12, tzinfo=UTC))
    ids = DeterministicIdGenerator()
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
        issued_at=clock.now_iso(),
        expires_at=None,
        agent_id="agent-master-1",
        workspace_generation=workspace_generation,
        policy_digest=_digest("message-policy"),
        idempotency_key="bootstrap-master-1",
        updated_at=clock.now_iso(),
    )
    store = InMemoryControlStore(
        (
            KernelRecordSnapshot.create(
                entity_type="session",
                entity_id="session-1",
                state_version=3,
                payload={
                    "session_id": "session-1",
                    "status": "active",
                    "updated_at": clock.now_iso(),
                },
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_member",
                entity_id="master-1",
                state_version=2,
                payload={
                    "agent_member_id": "master-1",
                    "agent_id": "agent-master-1",
                    "session_id": "session-1",
                    "status": "active",
                    "process_epoch": 2,
                    "active_authority_lease_id": lease.lease_id,
                    "workspace_generation": workspace_generation,
                },
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_authority_lease",
                entity_id=lease.lease_id,
                state_version=1,
                payload=lease.to_dict(),
            ),
        )
    )
    context = KernelCommandContext(
        command_id="command-message-1",
        session_id="session-1",
        actor_id="master-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id=lease.lease_id,
        authority_generation=1,
        authority_fence=1,
        expected_session_version=3,
        extension_bundle_digest=_digest("extensions"),
        capability_binding_digest=_digest("binding"),
        idempotency_key="message-1",
        correlation_id="request-message-1",
        workspace_generation=workspace_generation,
    )
    return (
        store,
        MessageIngressKernelApplicationService(
            store=store,
            clock=clock,
            ids=ids,
        ),
        MessageIngressCommand(
            context=context,
            message_id="message-1",
            source_actor_id="user:operator-1",
            content="Continue the bounded task",
            task_id=None,
            skill_keys=("workflow.code-review",),
        ),
    )


def test_message_ingress_atomically_records_inbox_and_wakeup_without_drain() -> None:
    store, service, command = _fixture()

    receipt = service.execute(command)

    message = store.read(entity_type="conversation_message", entity_id="message-1")
    assert message is not None
    assert message.payload["sender_actor_id"] == "user:operator-1"
    assert message.payload["admitted_by_actor_id"] == "master-1"
    assert len(
        tuple(record for record in store.records if record.entity_type == "inbox_message")
    ) == 1
    signals = tuple(
        record
        for record in store.records
        if record.entity_type == "agent_runtime_signal"
    )
    assert len(signals) == 1
    assert signals[0].payload["status"] == "pending"
    assert receipt.result["runtime_executed"] is False
    assert receipt.result["task_transition_performed"] is False
    assert store.commit_count == 1


def test_message_ingress_without_ready_workspace_rolls_back_all_state() -> None:
    store, service, command = _fixture(workspace_generation=None)

    with pytest.raises(KernelContractError) as rejected:
        service.execute(command)

    assert rejected.value.code == "message_target_runtime_binding_missing"
    assert store.read(entity_type="conversation_message", entity_id="message-1") is None
    assert store.events == []
    assert store.commit_count == 0
