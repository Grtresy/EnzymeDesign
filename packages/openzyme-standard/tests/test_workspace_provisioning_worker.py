from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from datetime import UTC
from datetime import datetime

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import RetryEligibility
from openzyme_contracts import WorkspaceProvisioningIntent
from openzyme_contracts import WorkspaceProvisioningReconciliation
from openzyme_contracts import WorkspaceProvisioningReconciliationStatus
from openzyme_contracts import WorkspaceProvisioningRequest
from openzyme_contracts import WorkspaceProvisioningStatus
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_kernel.testing import InMemoryControlStore
from openzyme_standard import StandardWorkspaceProvisioningWorker


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _intent() -> WorkspaceProvisioningIntent:
    return WorkspaceProvisioningIntent(
        intent_id="intent-1",
        session_id="session-1",
        agent_member_id="master-1",
        workspace_id="workspace-1",
        generation=1,
        repository_pin_digest=_digest("repository-pin"),
        provider_id="openzyme.workspace.git-lfs",
        target_id="local-host",
        adapter_binding_digest=_digest("workspace-provisioner"),
        controlled_operation_id="operation-1",
        status=WorkspaceProvisioningStatus.BLOCKED,
        state_version=3,
        claim_epoch=1,
        created_at="2026-08-21T09:00:00+00:00",
        updated_at="2026-08-21T09:10:00+00:00",
        claim_owner_id="worker-before-crash",
        claim_token="claim-before-crash",
        claim_expires_at="2026-08-21T09:05:00+00:00",
        terminal_receipt_digest=_digest("terminal-receipt"),
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        mutation_applied=None,
        retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
        reconcile_required=True,
        failure_id="failure-1",
        diagnostic_id="diagnostic-1",
        settled_at="2026-08-21T09:10:00+00:00",
    )


def _reconciliation(
    *,
    status: WorkspaceProvisioningReconciliationStatus = (
        WorkspaceProvisioningReconciliationStatus.PENDING
    ),
    claim_expires_at: str | None = None,
) -> WorkspaceProvisioningReconciliation:
    intent = _intent()
    pending = WorkspaceProvisioningReconciliation(
        reconciliation_id="reconciliation-1",
        session_id=intent.session_id,
        intent_id=intent.intent_id,
        blocked_intent_state_version=intent.state_version,
        blocked_intent_digest=intent.intent_digest,
        source_receipt_id="receipt-1",
        source_receipt_digest=_digest("receipt-1"),
        dispatch_receipt_digest=_digest("dispatch-receipt"),
        provision_request=WorkspaceProvisioningRequest(
            request_id="request-1",
            intent_id=intent.intent_id,
            intent_digest=intent.intent_digest,
            claim_token="source-claim",
            claim_epoch=1,
            session_id=intent.session_id,
            agent_member_id=intent.agent_member_id,
            workspace_id=intent.workspace_id,
            generation=intent.generation,
            repository_pin_digest=intent.repository_pin_digest,
            provider_id=intent.provider_id,
            target_id=intent.target_id,
            adapter_binding_digest=intent.adapter_binding_digest,
            controlled_operation_id=intent.controlled_operation_id,
        ),
        attempt=1,
        parent_reconciliation_id=None,
        reason_code="explicit_operator_reconciliation",
        requested_at="2026-08-21T09:30:00+00:00",
        requested_claim_seconds=47,
        status=WorkspaceProvisioningReconciliationStatus.PENDING,
        state_version=1,
        claim_epoch=0,
        created_at="2026-08-21T09:30:00+00:00",
        updated_at="2026-08-21T09:30:00+00:00",
    )
    if status is WorkspaceProvisioningReconciliationStatus.PENDING:
        return pending
    assert status is WorkspaceProvisioningReconciliationStatus.CLAIMED
    assert claim_expires_at is not None
    return replace(
        pending,
        status=status,
        state_version=2,
        claim_epoch=1,
        claim_owner_id="worker-before-crash",
        claim_token="reconciliation-claim-before-crash",
        claim_expires_at=claim_expires_at,
        updated_at="2026-08-21T09:31:00+00:00",
    )


def _root_records(*extra: KernelRecordSnapshot) -> InMemoryControlStore:
    lease = AgentAuthorityLease.create(
        lease_id="lease-1",
        session_id="session-1",
        agent_member_id="master-1",
        grants=(),
        generation=1,
        fence=1,
        state=AgentAuthorityLeaseState.ACTIVE,
        issued_at="2026-08-21T09:00:00+00:00",
        expires_at=None,
        agent_id="master-1",
        workspace_generation=1,
    )
    return InMemoryControlStore(
        (
            KernelRecordSnapshot.create(
                entity_type="session",
                entity_id="session-1",
                state_version=4,
                payload={"session_id": "session-1"},
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_member",
                entity_id="master-1",
                state_version=2,
                payload={
                    "session_id": "session-1",
                    "role": "master",
                    "parent_agent_id": None,
                    "status": "active",
                    "active_authority_lease_id": lease.lease_id,
                },
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_authority_lease",
                entity_id=lease.lease_id,
                state_version=1,
                payload=lease.to_dict(),
            ),
            *extra,
        )
    )


@dataclass(slots=True)
class _KernelWorker:
    calls: list[dict[str, object]] = field(default_factory=list)

    def run(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(dict(kwargs))
        context = kwargs["context"]
        return KernelMutationReceipt.create(
            command_id=context.command_id,
            service_id="openzyme.kernel.workspace-provisioning",
            operation="settle_reconciliation",
            mutation_applied=True,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        )


def _snapshot(entity_type: str, value) -> KernelRecordSnapshot:  # noqa: ANN001
    return KernelRecordSnapshot.create(
        entity_type=entity_type,
        entity_id=(
            value.reconciliation_id
            if isinstance(value, WorkspaceProvisioningReconciliation)
            else value.intent_id
        ),
        state_version=value.state_version,
        payload=value.to_dict(),
    )


def test_tick_prioritizes_only_admitted_reconciliation_and_uses_durable_claim() -> None:
    reconciliation = _reconciliation()
    store = _root_records(
        _snapshot("workspace_provisioning_reconciliation", reconciliation),
        _snapshot(
            "workspace_provisioning_intent",
            replace(
                _intent(),
                intent_id="pending-intent-2",
                status=WorkspaceProvisioningStatus.PENDING,
                state_version=1,
                claim_epoch=0,
                claim_owner_id=None,
                claim_token=None,
                claim_expires_at=None,
                terminal_receipt_digest=None,
                effect_certainty=None,
                mutation_applied=None,
                retry_eligibility=None,
                reconcile_required=False,
                failure_id=None,
                diagnostic_id=None,
                settled_at=None,
            ),
        ),
    )
    kernel = _KernelWorker()
    driver = StandardWorkspaceProvisioningWorker(
        worker=kernel,  # type: ignore[arg-type]
        records=store,
        clock=DeterministicClock(datetime(2026, 8, 21, 10, tzinfo=UTC)),
        ids=DeterministicIdGenerator(),
    )

    receipts = driver.tick(session_id="session-1", maximum=1)

    assert len(receipts) == 1
    assert len(kernel.calls) == 1
    call = kernel.calls[0]
    assert call["intent_id"] == reconciliation.intent_id
    assert call["expected_intent_version"] == 3
    assert call["claim_seconds"] == 47
    assert call["reconcile"] is True
    context = call["context"]
    assert context.worker_id == "openzyme-standard-workspace-provisioning-worker"
    assert context.requested_by_actor_id is None
    assert context.idempotency_key == "workspace-reconciliation-reconciliation-1"


def test_tick_reclaims_only_an_expired_reconciliation_occurrence() -> None:
    expired = _reconciliation(
        status=WorkspaceProvisioningReconciliationStatus.CLAIMED,
        claim_expires_at="2026-08-21T09:59:59+00:00",
    )
    unexpired = replace(
        _reconciliation(
            status=WorkspaceProvisioningReconciliationStatus.CLAIMED,
            claim_expires_at="2026-08-21T10:00:01+00:00",
        ),
        reconciliation_id="reconciliation-2",
    )
    store = _root_records(
        _snapshot("workspace_provisioning_reconciliation", expired),
        _snapshot("workspace_provisioning_reconciliation", unexpired),
    )
    kernel = _KernelWorker()
    driver = StandardWorkspaceProvisioningWorker(
        worker=kernel,  # type: ignore[arg-type]
        records=store,
        clock=DeterministicClock(datetime(2026, 8, 21, 10, tzinfo=UTC)),
        ids=DeterministicIdGenerator(),
    )

    receipts = driver.tick(session_id="session-1", maximum=4)

    assert len(receipts) == 1
    assert [call["intent_id"] for call in kernel.calls] == [expired.intent_id]
    assert kernel.calls[0]["claim_seconds"] == expired.requested_claim_seconds
