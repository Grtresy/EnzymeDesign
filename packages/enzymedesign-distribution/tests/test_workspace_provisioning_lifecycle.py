from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from datetime import UTC
from datetime import datetime

from enzymedesign_distribution import (
    EnzymeDesignWorkspaceProvisioningLifecycleWorker,
)
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
from openzyme_kernel.testing import InMemoryControlStore


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _blocked_intent() -> WorkspaceProvisioningIntent:
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


def _pending_intent() -> WorkspaceProvisioningIntent:
    blocked = _blocked_intent()
    return replace(
        blocked,
        intent_id="intent-pending",
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
    )


def _reconciliation() -> WorkspaceProvisioningReconciliation:
    intent = _blocked_intent()
    return WorkspaceProvisioningReconciliation(
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


def _snapshot(entity_type: str, value: object) -> KernelRecordSnapshot:
    entity_id = (
        value.reconciliation_id
        if isinstance(value, WorkspaceProvisioningReconciliation)
        else value.intent_id  # type: ignore[union-attr]
    )
    return KernelRecordSnapshot.create(
        entity_type=entity_type,
        entity_id=entity_id,
        state_version=value.state_version,  # type: ignore[union-attr]
        payload=value.to_dict(),  # type: ignore[union-attr]
    )


@dataclass(slots=True)
class _Runner:
    reconciliations: list[WorkspaceProvisioningReconciliation] = field(
        default_factory=list
    )
    provisions: list[tuple[str, int, int]] = field(default_factory=list)

    def run_admitted_reconciliation(
        self,
        reconciliation: WorkspaceProvisioningReconciliation,
    ) -> KernelMutationReceipt:
        self.reconciliations.append(reconciliation)
        return _receipt("settle_reconciliation")

    def run(
        self,
        *,
        intent_id: str,
        expected_intent_version: int,
        claim_seconds: int,
    ) -> KernelMutationReceipt:
        self.provisions.append(
            (intent_id, expected_intent_version, claim_seconds)
        )
        return _receipt("settle")


def _receipt(operation: str) -> KernelMutationReceipt:
    return KernelMutationReceipt.create(
        command_id=f"command-{operation}",
        service_id="openzyme.kernel.workspace-provisioning",
        operation=operation,
        mutation_applied=True,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
    )


def _worker(
    store: InMemoryControlStore,
    runner: _Runner,
) -> EnzymeDesignWorkspaceProvisioningLifecycleWorker:
    return EnzymeDesignWorkspaceProvisioningLifecycleWorker(
        runner=runner,  # type: ignore[arg-type]
        records=store,
        clock=DeterministicClock(datetime(2026, 8, 21, 10, tzinfo=UTC)),
        claim_seconds=300,
    )


def test_tick_prioritizes_admitted_reconciliation_and_durable_claim_seconds() -> None:
    reconciliation = _reconciliation()
    store = InMemoryControlStore(
        (
            _snapshot("workspace_provisioning_reconciliation", reconciliation),
            _snapshot("workspace_provisioning_intent", _pending_intent()),
        )
    )
    runner = _Runner()

    receipts = _worker(store, runner).tick(session_id="session-1", maximum=1)

    assert len(receipts) == 1
    assert runner.reconciliations == [reconciliation]
    assert runner.reconciliations[0].requested_claim_seconds == 47
    assert runner.provisions == []


def test_tick_reclaims_only_expired_claimed_reconciliation() -> None:
    pending = _reconciliation()
    expired = replace(
        pending,
        status=WorkspaceProvisioningReconciliationStatus.CLAIMED,
        state_version=2,
        claim_epoch=1,
        claim_owner_id="worker-before-crash",
        claim_token="reconciliation-claim-before-crash",
        claim_expires_at="2026-08-21T09:59:59+00:00",
        updated_at="2026-08-21T09:31:00+00:00",
    )
    unexpired = replace(
        expired,
        reconciliation_id="reconciliation-2",
        claim_expires_at="2026-08-21T10:00:01+00:00",
    )
    store = InMemoryControlStore(
        (
            _snapshot("workspace_provisioning_reconciliation", expired),
            _snapshot("workspace_provisioning_reconciliation", unexpired),
        )
    )
    runner = _Runner()

    receipts = _worker(store, runner).tick(session_id="session-1", maximum=4)

    assert len(receipts) == 1
    assert runner.reconciliations == [expired]


def test_terminal_reconciliation_is_ignored_and_never_creates_an_attempt() -> None:
    pending = _reconciliation()
    terminal = replace(
        pending,
        status=WorkspaceProvisioningReconciliationStatus.READY,
        state_version=3,
        claim_epoch=1,
        claim_owner_id="enzymedesign-worker",
        claim_token="terminal-claim",
        claim_expires_at="2026-08-21T10:05:00+00:00",
        result_receipt_id="receipt-terminal",
        result_receipt_digest=_digest("receipt-terminal"),
        result_terminal_receipt_digest=_digest("terminal-result"),
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        mutation_applied=True,
        retry_eligibility=RetryEligibility.TERMINAL,
        settled_at="2026-08-21T09:40:00+00:00",
        updated_at="2026-08-21T09:40:00+00:00",
    )
    store = InMemoryControlStore(
        (_snapshot("workspace_provisioning_reconciliation", terminal),)
    )
    runner = _Runner()

    assert _worker(store, runner).tick(session_id="session-1", maximum=4) == ()
    assert runner.reconciliations == []
    assert runner.provisions == []
    assert len(
        store.list_for_session(
            entity_type="workspace_provisioning_reconciliation",
            session_id="session-1",
            max_items=8,
        )
    ) == 1
