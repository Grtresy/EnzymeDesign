from __future__ import annotations

from dataclasses import replace
from datetime import UTC
from datetime import datetime

import pytest

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import WorkflowAuthorityBinding
from openzyme_contracts import WorkflowAuthorityDerivationKind
from openzyme_contracts import WorkflowAuthorityStatus
from openzyme_contracts import WorkflowAuthorityTransitionRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel import KernelContractError
from openzyme_kernel import WorkflowAuthorityKernelApplicationService
from openzyme_kernel import WorkflowAuthorityTransitionCommand
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_kernel.testing import InMemoryControlStore


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _binding() -> WorkflowAuthorityBinding:
    registry_digest = _digest("workflow-registry")
    return WorkflowAuthorityBinding(
        authority_id="workflow-authority-1",
        session_id="session-1",
        project_id="project-1",
        request_lineage_id="request-lineage-1",
        source_message_id="message-1",
        source_principal_id="user-1",
        authorized_actor_id="master-1",
        selected_workflow_refs=("workflow.code-review@1",),
        selection_digest=canonical_sha256_digest(
            {
                "schema_version": "workflow_selection_binding@1",
                "registry_snapshot_digest": registry_digest,
                "selected_workflow_refs": ["workflow.code-review@1"],
            }
        ),
        registry_snapshot_digest=registry_digest,
        derivation_kind=WorkflowAuthorityDerivationKind.ROOT_MESSAGE,
        status=WorkflowAuthorityStatus.ACTIVE,
        epoch=1,
        state_version=1,
        created_at="2026-08-24T00:00:00+00:00",
        updated_at="2026-08-24T00:00:00+00:00",
    )


def _fixture() -> tuple[
    InMemoryControlStore,
    WorkflowAuthorityKernelApplicationService,
    KernelCommandContext,
    WorkflowAuthorityBinding,
]:
    clock = DeterministicClock(datetime(2026, 8, 24, tzinfo=UTC))
    binding = _binding()
    lease = AgentAuthorityLease.create(
        lease_id="lease-master-1",
        session_id="session-1",
        agent_member_id="master-1",
        grants=(
            AuthorityGrant.create(
                grant_id="grant-workflow-authority-1",
                scope_id=binding.authority_id,
                operations=(
                    "workflow.authority.consumed",
                    "workflow.authority.expired",
                    "workflow.authority.revoked",
                ),
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
        workspace_generation=1,
        policy_digest=_digest("workflow-transition-policy"),
        idempotency_key="bootstrap-master-1",
        updated_at=clock.now_iso(),
    )
    store = InMemoryControlStore(
        (
            KernelRecordSnapshot.create(
                entity_type="session",
                entity_id="session-1",
                state_version=1,
                payload={
                    "session_id": "session-1",
                    "status": "active",
                    "updated_at": clock.now_iso(),
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
                entity_id=binding.authority_id,
                state_version=1,
                payload=binding.to_dict(),
            ),
        )
    )
    context = KernelCommandContext(
        command_id="workflow-transition-1",
        session_id="session-1",
        actor_id="master-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id=lease.lease_id,
        authority_generation=1,
        authority_fence=1,
        expected_session_version=1,
        extension_bundle_digest=_digest("extensions"),
        capability_binding_digest=_digest("binding"),
        idempotency_key="workflow-transition-1",
        correlation_id="workflow-transition-correlation-1",
        workspace_generation=1,
    )
    service = WorkflowAuthorityKernelApplicationService(
        store=store,
        clock=clock,
        ids=DeterministicIdGenerator(),
    )
    return store, service, context, binding


@pytest.mark.parametrize(
    "target_status",
    (
        WorkflowAuthorityStatus.REVOKED,
        WorkflowAuthorityStatus.EXPIRED,
        WorkflowAuthorityStatus.CONSUMED,
    ),
)
def test_workflow_authority_terminal_transition_is_cas_and_never_reopens(
    target_status: WorkflowAuthorityStatus,
) -> None:
    store, service, context, binding = _fixture()
    transitioned_at = "2026-08-24T00:01:00+00:00"
    request = WorkflowAuthorityTransitionRequest(
        request_id=f"workflow-{target_status.value}-1",
        authority_id=binding.authority_id,
        expected_binding_digest=binding.binding_digest,
        expected_epoch=binding.epoch,
        target_status=target_status,
        actor_id=context.actor_id,
        reason_code=f"operator_{target_status.value}",
        transitioned_at=transitioned_at,
    )

    receipt = service.transition(
        WorkflowAuthorityTransitionCommand(
            context=context,
            request=request,
            expected_record_version=1,
        )
    )

    record = store.read(
        entity_type="workflow_authority_binding",
        entity_id=binding.authority_id,
    )
    assert record is not None
    terminal = WorkflowAuthorityBinding.from_dict(record.payload)
    assert terminal.status is target_status
    assert terminal.epoch == 2
    assert terminal.state_version == 2
    assert terminal.revoked_at == (
        transitioned_at if target_status is WorkflowAuthorityStatus.REVOKED else None
    )
    assert terminal.expires_at == (
        transitioned_at if target_status is WorkflowAuthorityStatus.EXPIRED else None
    )
    assert terminal.consumed_at == (
        transitioned_at if target_status is WorkflowAuthorityStatus.CONSUMED else None
    )
    assert receipt.mutation_applied is True
    assert receipt.effect_certainty.value == "no_effect"
    assert receipt.result["runtime_executed"] is False
    assert receipt.result["fallback_performed"] is False
    assert [event.event_type for event in store.events] == [
        f"workflow.authority.{target_status.value}"
    ]
    assert len(store.outbox) == 1

    stale_context = replace(
        context,
        command_id="workflow-transition-stale",
        expected_session_version=2,
        idempotency_key="workflow-transition-stale",
    )
    with pytest.raises(KernelContractError) as stale:
        service.transition(
            WorkflowAuthorityTransitionCommand(
                context=stale_context,
                request=request,
                expected_record_version=2,
            )
        )

    assert stale.value.code == "workflow_authority_state_stale"
    assert store.commit_count == 1
    assert len(store.events) == 1
    assert len(store.outbox) == 1
