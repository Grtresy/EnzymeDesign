from __future__ import annotations

from dataclasses import replace
from datetime import UTC
from datetime import datetime

import pytest

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AgentRuntimeSignalReason
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import RuntimeSignalAuthorityLink
from openzyme_contracts import WorkflowAuthorityBinding
from openzyme_contracts import WorkflowAuthorityDerivationKind
from openzyme_contracts import WorkflowAuthoritySignalSourceKind
from openzyme_contracts import WorkflowAuthorityStatus
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel import KernelContractError
from openzyme_kernel import RuntimeContinuationDeliveryCommand
from openzyme_kernel import RuntimeContinuationDeliveryKernelApplicationService
from openzyme_kernel import RuntimeContinuationDeliveryStatus
from openzyme_kernel import RuntimeContinuationDeliveryWorker
from openzyme_kernel import RuntimeContinuationIntent
from openzyme_kernel.runtime_coordination_application import (
    build_runtime_signal_payload,
)
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_kernel.testing import InMemoryControlStore


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _workflow() -> WorkflowAuthorityBinding:
    registry_digest = _digest("registry")
    selected = ("workflow.continuation@1",)
    return WorkflowAuthorityBinding(
        authority_id="workflow-authority-1",
        session_id="session-1",
        project_id="project-1",
        request_lineage_id="request-lineage-1",
        source_message_id="message-1",
        source_principal_id="user-1",
        authorized_actor_id="member-1",
        selected_workflow_refs=selected,
        selection_digest=canonical_sha256_digest(
            {
                "schema_version": "workflow_selection_binding@1",
                "registry_snapshot_digest": registry_digest,
                "selected_workflow_refs": list(selected),
            }
        ),
        registry_snapshot_digest=registry_digest,
        derivation_kind=WorkflowAuthorityDerivationKind.ROOT_MESSAGE,
        task_id="task-1",
        lane_id="lane-1",
        status=WorkflowAuthorityStatus.ACTIVE,
        epoch=1,
        state_version=1,
        created_at="2026-08-24T00:00:00+00:00",
        updated_at="2026-08-24T00:00:00+00:00",
    )


def _lease(clock: DeterministicClock) -> AgentAuthorityLease:
    return AgentAuthorityLease.create(
        lease_id="lease-1",
        session_id="session-1",
        agent_member_id="member-1",
        grants=(
            AuthorityGrant.create(
                grant_id="grant-1",
                scope_id="session-1",
                operations=("continuation.deliver",),
                generation=1,
                fence=1,
            ),
        ),
        generation=1,
        fence=1,
        state=AgentAuthorityLeaseState.ACTIVE,
        issued_at=clock.now_iso(),
        expires_at="2026-08-24T01:00:00+00:00",
        agent_id="agent-1",
        workspace_generation=1,
        policy_digest=_digest("policy"),
        idempotency_key="lease-bootstrap-1",
        updated_at=clock.now_iso(),
    )


def _fixture(
    *,
    binding: WorkflowAuthorityBinding | None = None,
    intent_payload: dict[str, object] | None = None,
) -> tuple[
    InMemoryControlStore,
    RuntimeContinuationDeliveryKernelApplicationService,
    RuntimeContinuationDeliveryWorker,
    KernelCommandContext,
    RuntimeContinuationIntent,
]:
    clock = DeterministicClock(datetime(2026, 8, 24, tzinfo=UTC))
    ids = DeterministicIdGenerator()
    workflow = binding or _workflow()
    lease = _lease(clock)
    source_link = RuntimeSignalAuthorityLink(
        signal_id="source-signal-1",
        session_id="session-1",
        authority_id="workflow-authority-1",
        authority_epoch=1,
        authority_binding_digest=_workflow().binding_digest,
        causation_ref="message-1",
        source_kind=WorkflowAuthoritySignalSourceKind.ROOT_MESSAGE,
        created_at=clock.now_iso(),
    )
    source_signal = build_runtime_signal_payload(
        signal_id="source-signal-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_member_id="member-1",
        reason=AgentRuntimeSignalReason.INBOX_UNREAD,
        target_authority_lease_id=lease.lease_id,
        target_authority_lease_digest=lease.lease_digest,
        workspace_generation=1,
        process_epoch=1,
        correlation_id="request-lineage-1",
        source_ref="message-1",
        task_id="task-1",
        lane_id="lane-1",
        created_at=clock.now_iso(),
        enqueue_command_digest=_digest("source-enqueue"),
    )
    source_signal.update(
        {
            "status": "completed",
            "completed_at": clock.now_iso(),
        }
    )
    intent = RuntimeContinuationIntent(
        continuation_id="continuation-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_member_id="member-1",
        source_command_id="runtime-command-1",
        source_command_digest=_digest("runtime-command-1"),
        source_outcome_id="runtime-outcome-1",
        source_outcome_digest=_digest("runtime-outcome-1"),
        source_signal_id="source-signal-1",
        source_signal_authority_link_digest=source_link.link_digest,
        source_workflow_authority_id="workflow-authority-1",
        source_workflow_authority_epoch=1,
        source_workflow_authority_binding_digest=_workflow().binding_digest,
        process_epoch=1,
        release_digest=_digest("release"),
        extension_bundle_digest=_digest("extensions"),
        declared_tool_catalog_digest=_digest("tools"),
        capability_binding_id="capability-binding-1",
        capability_binding_revision=1,
        capability_binding_digest=_digest("capability-binding"),
        affordance_snapshot_id="affordance-1",
        affordance_snapshot_digest=_digest("affordance-1"),
        delivery_status=RuntimeContinuationDeliveryStatus.PENDING,
        delivery_attempt=0,
        created_at=clock.now_iso(),
    )
    records = (
        KernelRecordSnapshot.create(
            entity_type="session",
            entity_id="session-1",
            state_version=1,
            payload={"session_id": "session-1", "status": "active"},
        ),
        KernelRecordSnapshot.create(
            entity_type="agent_member",
            entity_id="member-1",
            state_version=1,
            payload={
                "agent_member_id": "member-1",
                "session_id": "session-1",
                "agent_id": "agent-1",
                "role": "master",
                "parent_agent_id": None,
                "status": "active",
                "process_epoch": 1,
                "active_authority_lease_id": lease.lease_id,
                "workspace_generation": 1,
            },
        ),
        KernelRecordSnapshot.create(
            entity_type="agent_authority_lease",
            entity_id=lease.lease_id,
            state_version=1,
            payload=lease.to_dict(),
        ),
        KernelRecordSnapshot.create(
            entity_type="workflow_authority_binding",
            entity_id=workflow.authority_id,
            state_version=workflow.state_version,
            payload=workflow.to_dict(),
        ),
        KernelRecordSnapshot.create(
            entity_type="agent_runtime_signal",
            entity_id="source-signal-1",
            state_version=3,
            payload=source_signal,
        ),
        KernelRecordSnapshot.create(
            entity_type="runtime_signal_authority_link",
            entity_id="source-signal-1",
            state_version=1,
            payload=source_link.to_dict(),
        ),
        KernelRecordSnapshot.create(
            entity_type="runtime_continuation_intent",
            entity_id="continuation-1",
            state_version=1,
            payload=intent.to_dict() if intent_payload is None else intent_payload,
        ),
    )
    store = InMemoryControlStore(records)
    application = RuntimeContinuationDeliveryKernelApplicationService(
        store=store,
        clock=clock,
        ids=ids,
    )
    worker = RuntimeContinuationDeliveryWorker(
        application=application,
        records=store,
        ids=ids,
    )
    context = KernelCommandContext(
        command_id="continuation-delivery-1",
        session_id="session-1",
        actor_id="member-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id=lease.lease_id,
        authority_generation=1,
        authority_fence=1,
        expected_session_version=1,
        extension_bundle_digest=_digest("extensions"),
        capability_binding_digest=_digest("capability-binding"),
        idempotency_key="continuation-delivery-1",
        correlation_id="request-lineage-1",
        workspace_generation=1,
    )
    return store, application, worker, context, intent


def _command(
    context: KernelCommandContext,
    *,
    signal_id: str = "delivery-signal-1",
) -> RuntimeContinuationDeliveryCommand:
    return RuntimeContinuationDeliveryCommand(
        context=context,
        continuation_id="continuation-1",
        expected_intent_version=1,
        delivery_signal_id=signal_id,
    )


def test_delivery_atomically_inherits_exact_authority_and_only_queues() -> None:
    store, application, _, context, intent = _fixture()

    receipt = application.deliver(_command(context))

    delivered_record = store.read(
        entity_type="runtime_continuation_intent",
        entity_id=intent.continuation_id,
    )
    signal = store.read(
        entity_type="agent_runtime_signal",
        entity_id="delivery-signal-1",
    )
    link = store.read(
        entity_type="runtime_signal_authority_link",
        entity_id="delivery-signal-1",
    )
    assert delivered_record is not None and signal is not None and link is not None
    delivered = RuntimeContinuationIntent.from_dict(delivered_record.payload)
    assert delivered.delivery_status is RuntimeContinuationDeliveryStatus.DELIVERED
    assert delivered.delivery_signal_id == "delivery-signal-1"
    assert signal.payload["status"] == "pending"
    assert signal.payload["reason"] == "manual_resume"
    assert signal.payload["correlation_id"] == "request-lineage-1"
    assert signal.payload["source_ref"] == intent.continuation_id
    assert link.payload["authority_id"] == intent.source_workflow_authority_id
    assert link.payload["authority_epoch"] == intent.source_workflow_authority_epoch
    assert (
        link.payload["authority_binding_digest"]
        == intent.source_workflow_authority_binding_digest
    )
    assert link.payload["source_kind"] == "continuation_delivery"
    assert link.payload["causation_ref"] == intent.continuation_id
    assert receipt.mutation_applied is True
    assert receipt.result["recipient_runtime_executed"] is False
    assert receipt.result["task_transition_performed"] is False
    assert receipt.result["fallback_performed"] is False
    assert store.read(entity_type="task", entity_id="task-1") is None
    assert store.commit_count == 1


def test_exact_duplicate_is_idempotent_but_collision_is_rejected() -> None:
    store, application, _, context, _ = _fixture()
    application.deliver(_command(context))
    before_commits = store.commit_count

    duplicate = application.deliver(
        _command(
            replace(
                context,
                command_id="continuation-delivery-duplicate",
                idempotency_key="continuation-delivery-duplicate",
            )
        )
    )

    assert duplicate.mutation_applied is False
    assert duplicate.result["duplicate"] is True
    assert store.commit_count == before_commits
    with pytest.raises(KernelContractError) as collision:
        application.deliver(
            _command(
                replace(
                    context,
                    command_id="continuation-delivery-collision",
                    idempotency_key="continuation-delivery-collision",
                ),
                signal_id="another-delivery-signal",
            )
        )
    assert collision.value.code == "runtime_continuation_delivery_identity_conflict"
    assert (
        store.read(
            entity_type="agent_runtime_signal",
            entity_id="another-delivery-signal",
        )
        is None
    )
    assert store.commit_count == before_commits


@pytest.mark.parametrize(
    "status",
    (
        WorkflowAuthorityStatus.REVOKED,
        WorkflowAuthorityStatus.EXPIRED,
        WorkflowAuthorityStatus.CONSUMED,
    ),
)
def test_terminal_source_authority_rejects_with_zero_partial_mutation(
    status: WorkflowAuthorityStatus,
) -> None:
    original = _workflow()
    terminal = replace(
        original,
        status=status,
        epoch=2,
        state_version=2,
        updated_at="2026-08-24T00:01:00+00:00",
        revoked_at=(
            "2026-08-24T00:01:00+00:00"
            if status is WorkflowAuthorityStatus.REVOKED
            else None
        ),
        expires_at=(
            "2026-08-24T00:01:00+00:00"
            if status is WorkflowAuthorityStatus.EXPIRED
            else None
        ),
        consumed_at=(
            "2026-08-24T00:01:00+00:00"
            if status is WorkflowAuthorityStatus.CONSUMED
            else None
        ),
    )
    store, application, _, context, intent = _fixture(binding=terminal)

    with pytest.raises(KernelContractError) as rejected:
        application.deliver(_command(context))

    assert rejected.value.code == "workflow_authority_stale"
    assert (
        store.read(
            entity_type="agent_runtime_signal",
            entity_id="delivery-signal-1",
        )
        is None
    )
    current = store.read(
        entity_type="runtime_continuation_intent",
        entity_id=intent.continuation_id,
    )
    assert current is not None and current.state_version == 1
    assert store.commit_count == 0


def test_source_epoch_or_link_digest_drift_rejects_without_fallback() -> None:
    store, application, _, context, intent = _fixture()
    drifted_payload = intent.to_dict()
    drifted_payload["source_signal_authority_link_digest"] = _digest("drifted-link")
    store._records[("runtime_continuation_intent", intent.continuation_id)] = (  # noqa: SLF001
        KernelRecordSnapshot.create(
            entity_type="runtime_continuation_intent",
            entity_id=intent.continuation_id,
            state_version=1,
            payload=drifted_payload,
        )
    )

    with pytest.raises(KernelContractError) as rejected:
        application.deliver(_command(context))

    assert rejected.value.code == "runtime_continuation_source_authority_stale"
    assert rejected.value.mutation_applied is False
    assert rejected.value.fallback_performed is False
    assert store.commit_count == 0


def test_active_source_epoch_drift_and_stale_intent_version_are_rejected() -> None:
    original = _workflow()
    drifted_binding = replace(
        original,
        epoch=2,
        state_version=2,
        updated_at="2026-08-24T00:01:00+00:00",
    )
    store, application, _, context, _ = _fixture(binding=drifted_binding)

    with pytest.raises(KernelContractError) as epoch_drift:
        application.deliver(_command(context))

    assert epoch_drift.value.code == "workflow_authority_stale"
    assert store.commit_count == 0

    store, application, _, context, _ = _fixture()
    with pytest.raises(KernelContractError) as stale_intent:
        application.deliver(
            replace(
                _command(context),
                expected_intent_version=2,
            )
        )
    assert stale_intent.value.code == "runtime_continuation_intent_stale"
    assert (
        store.read(
            entity_type="agent_runtime_signal",
            entity_id="delivery-signal-1",
        )
        is None
    )
    assert store.commit_count == 0


def test_legacy_intent_without_source_link_fails_closed() -> None:
    _, _, _, _, intent = _fixture()
    legacy = intent.to_dict()
    legacy.pop("source_signal_authority_link_digest")
    store, application, _, context, _ = _fixture(intent_payload=legacy)

    with pytest.raises(KernelContractError) as rejected:
        application.deliver(_command(context))

    assert rejected.value.code == "runtime_continuation_source_link_missing"
    assert (
        store.read(
            entity_type="agent_runtime_signal",
            entity_id="delivery-signal-1",
        )
        is None
    )
    assert store.commit_count == 0


def test_bounded_worker_reaches_pending_intent_but_never_runs_recipient() -> None:
    store, _, worker, context, _ = _fixture()

    receipts = worker.tick(context=context, maximum=1)

    assert len(receipts) == 1
    delivery_signal_id = receipts[0].result["delivery_signal_id"]
    assert isinstance(delivery_signal_id, str)
    signal = store.read(
        entity_type="agent_runtime_signal",
        entity_id=delivery_signal_id,
    )
    assert signal is not None and signal.payload["status"] == "pending"
    assert receipts[0].result["recipient_runtime_executed"] is False
    assert (
        len(
            tuple(
                record
                for record in store.records
                if record.entity_type == "agent_runtime_signal"
            )
        )
        == 2
    )
