from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import replace

import pytest

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import FILE_WORKSPACE_FAILURE_FACT_PUBLIC_FIELDS
from openzyme_contracts import FILE_WORKSPACE_FAILURE_IDENTITY_PUBLIC_FIELDS
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import RetryEligibility
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import WorkspaceGenerationStatus
from openzyme_contracts import WorkspacePortError
from openzyme_contracts import WorkspaceProvisioningIntent
from openzyme_contracts import WorkspaceProvisioningReceipt
from openzyme_contracts import WorkspaceProvisioningReceiptDisposition
from openzyme_contracts import WorkspaceProvisioningReconciliation
from openzyme_contracts import (
    WORKSPACE_PROVISIONING_RECONCILIATION_ADMISSION_RESULT_FIELDS,
)
from openzyme_contracts import WorkspaceProvisioningReconciliationStatus
from openzyme_contracts import WorkspaceProvisioningRequest
from openzyme_contracts import WorkspaceProvisioningStatus
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_extension_spi import WorkspaceProvisionerPortError
from openzyme_kernel import KernelContractError
from openzyme_kernel import SessionBootstrapKernelApplicationService
from openzyme_kernel.workspace_provisioning_application import (
    WorkspaceProvisioningClaimCommand,
)
from openzyme_kernel.workspace_provisioning_application import (
    WorkspaceProvisioningKernelApplicationService,
)
from openzyme_kernel.workspace_provisioning_application import (
    WorkspaceProvisioningReconciliationAdmissionCommand,
)
from openzyme_kernel.workspace_provisioning_application import (
    WorkspaceProvisioningReconciliationClaimCommand,
)
from openzyme_kernel.workspace_provisioning_application import (
    WorkspaceProvisioningReconciliationSettlementCommand,
)
from openzyme_kernel.workspace_provisioning_application import (
    WorkspaceProvisioningReplacementCommand,
)
from openzyme_kernel.workspace_provisioning_application import (
    WorkspaceProvisioningSettlementCommand,
)
from openzyme_kernel.workspace_provisioning_application import (
    WorkspaceProvisioningWorker,
)
from openzyme_kernel.workspace_provisioning_application import (
    WorkspaceProvisioningWorkerContext,
)

from test_controlled_operation_application import _Ids
from test_controlled_operation_application import _Store
from test_session_bootstrap_application import _Verifier
from test_session_bootstrap_application import _command
from test_session_bootstrap_application import _seed_repository_binding


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _assert_public_failure_allowlisted(payload: object) -> None:
    assert isinstance(payload, Mapping)
    assert set(payload["facts"]) <= FILE_WORKSPACE_FAILURE_FACT_PUBLIC_FIELDS
    assert set(payload["identities"]) <= FILE_WORKSPACE_FAILURE_IDENTITY_PUBLIC_FIELDS


@dataclass
class _Clock:
    value: str = "2026-08-20T10:00:00+00:00"

    def now_iso(self) -> str:
        return self.value


class _Provisioner:
    provider_id = "openzyme.workspace.git.lfs"
    adapter_binding_digest = _digest("selected-workspace-adapter")

    def __init__(
        self,
        *,
        fail_dispatch: bool = False,
        fail_reconcile: bool = False,
        reconcile_no_effect: bool = False,
        provision_no_effect: bool = False,
        observed_root_identity_digest: str | None = None,
        ready_receipt_override: tuple[str, object] | None = None,
    ) -> None:
        self.fail_dispatch = fail_dispatch
        self.fail_reconcile = fail_reconcile
        self.reconcile_no_effect = reconcile_no_effect
        self.provision_no_effect = provision_no_effect
        self.observed_root_identity_digest = observed_root_identity_digest
        self.ready_receipt_override = ready_receipt_override
        self.provision_calls = 0
        self.reconcile_calls = 0
        self.reconciliation_ids: list[str] = []
        self.last_receipt: WorkspaceProvisioningReceipt | None = None

    def provision(self, request):  # noqa: ANN001, ANN201
        self.provision_calls += 1
        if self.fail_dispatch:
            raise WorkspaceProvisionerPortError(
                code="git_lfs_dispatch_response_lost",
                diagnostic_id="diagnostic-dispatch-response-lost",
                summary="Adapter dispatch response was lost",
            )
        if self.provision_no_effect:
            raise WorkspacePortError(
                "git_lfs_clone_failed_before_effect",
                "Git/LFS clone failed before creating the workspace",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
                diagnostic_id="diagnostic-provision-no-effect",
            )
        self.last_receipt = _ready_receipt(
            request,
            suffix="provision",
            observed_root_identity_digest=self.observed_root_identity_digest,
        )
        if self.ready_receipt_override is not None:
            field_name, value = self.ready_receipt_override
            self.last_receipt = replace(
                self.last_receipt,
                **{field_name: value},
            )
        return self.last_receipt

    def reconcile(self, request):  # noqa: ANN001, ANN201
        self.reconcile_calls += 1
        self.reconciliation_ids.append(request.reconciliation_id)
        if self.fail_reconcile:
            raise WorkspaceProvisionerPortError(
                code="git_lfs_reconciliation_response_lost",
                diagnostic_id="diagnostic-reconciliation-response-lost",
                summary="Adapter reconciliation response was lost",
            )
        if self.reconcile_no_effect:
            raise WorkspacePortError(
                "git_lfs_reconciliation_observed_no_effect",
                "Reconciliation proved the dispatch had no effect",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
                diagnostic_id="diagnostic-reconciliation-no-effect",
            )
        self.last_receipt = _ready_receipt(
            request.provision_request,
            suffix="reconcile",
        )
        return self.last_receipt


def _ready_receipt(
    request,  # noqa: ANN001
    *,
    suffix: str,
    observed_root_identity_digest: str | None = None,
) -> WorkspaceProvisioningReceipt:
    receipt_id = f"workspace-receipt-{suffix}-{request.claim_epoch}"
    return WorkspaceProvisioningReceipt(
        receipt_id=receipt_id,
        request_id=request.request_id,
        request_digest=request.request_digest,
        intent_id=request.intent_id,
        intent_digest=request.intent_digest,
        claim_token=request.claim_token,
        claim_epoch=request.claim_epoch,
        controlled_operation_id=request.controlled_operation_id,
        disposition=WorkspaceProvisioningReceiptDisposition.READY,
        session_id=request.session_id,
        agent_member_id=request.agent_member_id,
        workspace_id=request.workspace_id,
        generation=request.generation,
        repository_pin_digest=request.repository_pin_digest,
        provider_id=request.provider_id,
        target_id=request.target_id,
        adapter_binding_digest=request.adapter_binding_digest,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        mutation_applied=True,
        fallback_performed=False,
        retry_eligibility=RetryEligibility.TERMINAL,
        reconcile_required=False,
        observed_root_identity_digest=(
            observed_root_identity_digest or _digest(f"observed-root-{suffix}")
        ),
        terminal_receipt_digest=_digest(f"terminal-receipt-{suffix}"),
        completed_at="2026-08-20T10:00:00+00:00",
    )


def _bootstrapped() -> tuple[_Store, _Clock]:
    store = _Store()
    store.records.clear()
    _seed_repository_binding(store)
    clock = _Clock()
    SessionBootstrapKernelApplicationService(
        store=store,
        clock=clock,
        ids=_Ids(),
        authority_verifier=_Verifier(),
    ).bootstrap(_command())
    return store, clock


def _reserve_root_identity(store: _Store, root_identity_digest: str) -> None:
    generation = store.read(
        entity_type="workspace_generation",
        entity_id="workspace-master-1",
    )
    assert generation is not None
    payload = dict(generation.payload)
    payload["root_identity_digest"] = root_identity_digest
    store.records[("workspace_generation", "workspace-master-1")] = (
        KernelRecordSnapshot.create(
            entity_type="workspace_generation",
            entity_id="workspace-master-1",
            state_version=generation.state_version,
            payload=payload,
        )
    )


def _context(
    store: _Store,
    *,
    command: str,
    worker: str = "provisioning-worker-1",
) -> WorkspaceProvisioningWorkerContext:
    session = store.read(entity_type="session", entity_id="session-1")
    assert session is not None
    return WorkspaceProvisioningWorkerContext(
        command_id=f"command-{command}",
        idempotency_key=f"idempotency-{command}",
        correlation_id=f"correlation-{command}",
        session_id="session-1",
        worker_id=worker,
        worker_authority_id="provisioning-worker-authority-1",
        worker_authority_generation=1,
        worker_authority_fence=1,
        expected_session_version=session.state_version,
    )


def _application(
    store: _Store,
    clock: _Clock,
) -> WorkspaceProvisioningKernelApplicationService:
    return WorkspaceProvisioningKernelApplicationService(
        store=store,
        reader=store,
        clock=clock,
        ids=_Ids(),
    )


def _worker(
    store: _Store,
    clock: _Clock,
    port: _Provisioner,
) -> WorkspaceProvisioningWorker:
    return WorkspaceProvisioningWorker(
        application=_application(store, clock),
        reader=store,
        ports={port.adapter_binding_digest: port},
        clock=clock,
        ids=_Ids(),
    )


def _blocked_workspace(
    *,
    fail_reconcile: bool = False,
) -> tuple[_Store, _Clock, _Provisioner, WorkspaceProvisioningWorker]:
    store, clock = _bootstrapped()
    port = _Provisioner(fail_dispatch=True, fail_reconcile=fail_reconcile)
    worker = _worker(store, clock, port)
    worker.run(
        context=_context(store, command="provision-uncertain"),
        intent_id="workspace-intent-1",
        expected_intent_version=1,
        claim_seconds=60,
    )
    port.fail_dispatch = False
    return store, clock, port, worker


def _pending_reconciliation(
    store: _Store,
    *,
    reconciliation_id: str = "workspace-reconciliation-test-1",
) -> WorkspaceProvisioningReconciliation:
    intent_record = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id="workspace-intent-1",
    )
    assert intent_record is not None
    intent = WorkspaceProvisioningIntent.from_dict(intent_record.payload)
    receipt_records = store.list_for_session(
        entity_type="workspace_provisioning_receipt",
        session_id="session-1",
        max_items=10,
    )
    assert len(receipt_records) == 1
    source = WorkspaceProvisioningReceipt.from_dict(receipt_records[0].payload)
    request = WorkspaceProvisioningRequest(
        request_id=source.request_id,
        intent_id=source.intent_id,
        intent_digest=source.intent_digest,
        claim_token=source.claim_token,
        claim_epoch=source.claim_epoch,
        session_id=source.session_id,
        agent_member_id=source.agent_member_id,
        workspace_id=source.workspace_id,
        generation=source.generation,
        repository_pin_digest=source.repository_pin_digest,
        provider_id=source.provider_id,
        target_id=source.target_id,
        adapter_binding_digest=source.adapter_binding_digest,
        controlled_operation_id=source.controlled_operation_id,
    )
    return WorkspaceProvisioningReconciliation(
        reconciliation_id=reconciliation_id,
        session_id=intent.session_id,
        intent_id=intent.intent_id,
        blocked_intent_state_version=intent_record.state_version,
        blocked_intent_digest=intent.intent_digest,
        source_receipt_id=source.receipt_id,
        source_receipt_digest=source.receipt_digest,
        dispatch_receipt_digest=source.terminal_receipt_digest,
        provision_request=request,
        attempt=1,
        parent_reconciliation_id=None,
        reason_code="explicit_operator_reconciliation",
        requested_at=source.completed_at,
        requested_claim_seconds=60,
        status=WorkspaceProvisioningReconciliationStatus.PENDING,
        state_version=1,
        claim_epoch=0,
        created_at=source.completed_at,
        updated_at=source.completed_at,
    )


def _admit_reconciliation(
    worker: WorkspaceProvisioningWorker,
    store: _Store,
    *,
    command: str,
    claim_seconds: int = 60,
) -> KernelMutationReceipt:
    intent = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id="workspace-intent-1",
    )
    assert intent is not None
    return worker.admit_reconciliation(
        context=_context(store, command=f"{command}-admit"),
        intent_id=intent.entity_id,
        expected_intent_version=intent.state_version,
        claim_seconds=claim_seconds,
    )


def test_ready_receipt_atomically_activates_workspace_and_pending_root_lease() -> None:
    store, clock = _bootstrapped()
    port = _Provisioner()

    receipt = _worker(store, clock, port).run(
        context=_context(store, command="provision-ready"),
        intent_id="workspace-intent-1",
        expected_intent_version=1,
        claim_seconds=60,
    )

    intent = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id="workspace-intent-1",
    )
    generation = store.read(
        entity_type="workspace_generation",
        entity_id="workspace-master-1",
    )
    lease = store.read(entity_type="agent_authority_lease", entity_id="root-lease-1")
    operation = store.read(
        entity_type="controlled_operation",
        entity_id="workspace-provision-1",
    )
    runtime = store.read(
        entity_type="workspace_runtime_binding",
        entity_id="workspace-master-1",
    )
    assert intent is not None and intent.payload["status"] == "ready"
    assert generation is not None and generation.payload["status"] == "ready"
    assert lease is not None and lease.payload["state"] == "active"
    assert operation is not None and operation.payload["state"] == "settled"
    assert runtime is not None and runtime.payload["generation"] == 1
    assert port.provision_calls == 1
    assert receipt.result["readiness"] == "ready"
    assert receipt.result["runtime_executed"] is False
    assert receipt.result["task_transition_performed"] is False


@pytest.mark.parametrize(
    ("field_name", "mismatched_value"),
    (
        pytest.param("request_id", "workspace-request-other", id="request"),
        pytest.param("request_digest", _digest("request-other"), id="request-digest"),
        pytest.param("intent_id", "workspace-intent-other", id="intent"),
        pytest.param("intent_digest", _digest("intent-other"), id="intent-digest"),
        pytest.param("claim_token", "claim-other", id="claim-token"),
        pytest.param("claim_epoch", 2, id="claim-epoch"),
        pytest.param(
            "controlled_operation_id",
            "workspace-provision-other",
            id="controlled-operation",
        ),
        pytest.param("session_id", "session-other", id="session"),
        pytest.param("agent_member_id", "member-other", id="member"),
        pytest.param("workspace_id", "workspace-other", id="workspace"),
        pytest.param("generation", 2, id="generation"),
        pytest.param(
            "repository_pin_digest",
            _digest("repository-other"),
            id="repository",
        ),
        pytest.param("provider_id", "workspace.provider.other", id="provider"),
        pytest.param("target_id", "target-other", id="target"),
        pytest.param(
            "adapter_binding_digest",
            _digest("adapter-other"),
            id="adapter-binding",
        ),
        pytest.param(
            "observed_root_identity_digest",
            _digest("root-other"),
            id="root-observation",
        ),
    ),
)
def test_ready_receipt_identity_mismatch_becomes_structured_blocker_before_activation(
    field_name: str,
    mismatched_value: object,
) -> None:
    store, clock = _bootstrapped()
    reserved_root = _digest("reserved-root")
    _reserve_root_identity(store, reserved_root)
    port = _Provisioner(
        observed_root_identity_digest=reserved_root,
        ready_receipt_override=(field_name, mismatched_value),
    )

    result = _worker(store, clock, port).run(
        context=_context(store, command=f"provision-mismatch-{field_name}"),
        intent_id="workspace-intent-1",
        expected_intent_version=1,
        claim_seconds=60,
    )

    intent = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id="workspace-intent-1",
    )
    generation = store.read(
        entity_type="workspace_generation",
        entity_id="workspace-master-1",
    )
    lease = store.read(entity_type="agent_authority_lease", entity_id="root-lease-1")
    runtime = store.read(
        entity_type="workspace_runtime_binding",
        entity_id="workspace-master-1",
    )
    receipts = store.list_for_session(
        entity_type="workspace_provisioning_receipt",
        session_id="session-1",
        max_items=10,
    )
    failures = store.list_for_session(
        entity_type="failure_observation",
        session_id="session-1",
        max_items=10,
    )
    diagnostics = store.list_for_session(
        entity_type="private_diagnostic",
        session_id="session-1",
        max_items=10,
    )

    assert port.last_receipt is not None
    assert intent is not None and intent.payload["status"] == "blocked"
    assert intent.payload["effect_certainty"] == "terminal_known"
    assert intent.payload["mutation_applied"] is True
    assert intent.payload["retry_eligibility"] == "terminal"
    assert intent.payload["reconcile_required"] is False
    assert intent.payload["fallback_performed"] is False
    assert generation is not None and generation.payload["status"] == "failed"
    assert lease is not None and lease.payload["state"] == "pending"
    assert runtime is None
    assert len(receipts) == 1
    assert receipts[0].payload["disposition"] == "blocked"
    assert receipts[0].payload["intent_id"] == "workspace-intent-1"
    assert receipts[0].payload["fallback_performed"] is False
    assert len(failures) == 1
    assert (
        failures[0].payload["error_code"]
        == "workspace_provisioner_receipt_identity_mismatch"
    )
    assert failures[0].payload["effect_certainty"] == "terminal_known"
    assert failures[0].payload["mutation_applied"] is True
    assert failures[0].payload["fallback_performed"] is False
    assert port.last_receipt.receipt_digest in failures[0].payload["evidence_refs"]
    assert len(diagnostics) == 1
    assert failures[0].payload["private_diagnostic_digest"] == (
        diagnostics[0].payload["record_digest"]
    )
    _assert_public_failure_allowlisted(failures[0].payload)
    assert diagnostics[0].payload["failure_id"] == failures[0].entity_id
    assert result.result["readiness"] == "blocked"
    assert result.result["runtime_executed"] is False
    assert result.result["task_transition_performed"] is False
    assert result.result["fallback_performed"] is False
    assert port.provision_calls == 1


def test_initial_no_effect_port_error_blocks_without_retry_reconcile_or_activation() -> (
    None
):
    store, clock = _bootstrapped()
    port = _Provisioner(provision_no_effect=True)
    worker = _worker(store, clock, port)

    result = worker.run(
        context=_context(store, command="provision-no-effect"),
        intent_id="workspace-intent-1",
        expected_intent_version=1,
        claim_seconds=60,
    )

    intent = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id="workspace-intent-1",
    )
    generation = store.read(
        entity_type="workspace_generation",
        entity_id="workspace-master-1",
    )
    lease = store.read(entity_type="agent_authority_lease", entity_id="root-lease-1")
    runtime = store.read(
        entity_type="workspace_runtime_binding",
        entity_id="workspace-master-1",
    )
    operation = store.read(
        entity_type="controlled_operation",
        entity_id="workspace-provision-1",
    )
    reconciliations = store.list_for_session(
        entity_type="workspace_provisioning_reconciliation",
        session_id="session-1",
        max_items=10,
    )
    failures = store.list_for_session(
        entity_type="failure_observation",
        session_id="session-1",
        max_items=10,
    )
    diagnostics = store.list_for_session(
        entity_type="private_diagnostic",
        session_id="session-1",
        max_items=10,
    )

    assert intent is not None and intent.payload["status"] == "blocked"
    assert intent.payload["effect_certainty"] == "no_effect"
    assert intent.payload["mutation_applied"] is False
    assert intent.payload["retry_eligibility"] == "terminal"
    assert intent.payload["reconcile_required"] is False
    assert intent.payload["fallback_performed"] is False
    assert generation is not None and generation.payload["status"] == "failed"
    assert lease is not None and lease.payload["state"] == "pending"
    assert runtime is None
    assert operation is not None and operation.payload["state"] == "settled"
    assert operation.payload["effect_certainty"] == "no_effect"
    assert operation.payload["mutation_applied"] is False
    assert operation.payload["fallback_performed"] is False
    assert reconciliations == ()
    assert len(failures) == 1
    assert failures[0].payload["error_code"] == "git_lfs_clone_failed_before_effect"
    assert len(diagnostics) == 1
    assert diagnostics[0].payload["exception_type"] == "WorkspacePortError"
    assert failures[0].payload["private_diagnostic_digest"] == (
        diagnostics[0].payload["record_digest"]
    )
    _assert_public_failure_allowlisted(failures[0].payload)
    assert result.result["readiness"] == "blocked"
    assert result.result["reconcile_required"] is False
    assert result.result["fallback_performed"] is False
    assert port.provision_calls == 1

    with pytest.raises(KernelContractError) as terminal:
        worker.run(
            context=_context(store, command="provision-no-effect-redispatch"),
            intent_id="workspace-intent-1",
            expected_intent_version=intent.state_version,
            claim_seconds=60,
        )

    assert terminal.value.code == "workspace_provisioning_intent_terminal"
    assert port.provision_calls == 1


def test_dispatch_in_doubt_blocks_and_only_explicit_reconciliation_can_activate() -> (
    None
):
    store, clock = _bootstrapped()
    port = _Provisioner(fail_dispatch=True)
    worker = _worker(store, clock, port)

    blocked = worker.run(
        context=_context(store, command="provision-uncertain"),
        intent_id="workspace-intent-1",
        expected_intent_version=1,
        claim_seconds=60,
    )

    intent = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id="workspace-intent-1",
    )
    lease = store.read(entity_type="agent_authority_lease", entity_id="root-lease-1")
    assert intent is not None and intent.payload["status"] == "blocked"
    assert intent.payload["effect_certainty"] == "dispatch_in_doubt"
    assert intent.payload["mutation_applied"] is None
    assert intent.payload["reconcile_required"] is True
    assert lease is not None and lease.payload["state"] == "pending"
    assert blocked.result["readiness"] == "blocked"

    port.fail_dispatch = False
    admitted = _admit_reconciliation(
        worker,
        store,
        command="reconcile-ready",
    )
    assert admitted.result["reconciliation_enqueued"] is True
    assert admitted.result["external_effect_performed"] is False
    assert port.reconcile_calls == 0
    ready = worker.run(
        context=_context(store, command="reconcile-ready"),
        intent_id="workspace-intent-1",
        expected_intent_version=intent.state_version,
        claim_seconds=60,
        reconcile=True,
    )

    reconciled = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id="workspace-intent-1",
    )
    reconciliation_records = store.list_for_session(
        entity_type="workspace_provisioning_reconciliation",
        session_id="session-1",
        max_items=10,
    )
    lease = store.read(entity_type="agent_authority_lease", entity_id="root-lease-1")
    generation = store.read(
        entity_type="workspace_generation",
        entity_id="workspace-master-1",
    )
    runtime = store.read(
        entity_type="workspace_runtime_binding",
        entity_id="workspace-master-1",
    )
    assert reconciled is not None and reconciled.record_digest == intent.record_digest
    assert reconciled.payload["status"] == "blocked"
    assert len(reconciliation_records) == 1
    assert reconciliation_records[0].payload["status"] == "ready"
    assert (
        reconciliation_records[0].payload["blocked_intent_digest"]
        == intent.payload["intent_digest"]
    )
    assert lease is not None and lease.payload["state"] == "active"
    assert generation is not None and generation.payload["status"] == "ready"
    assert runtime is not None and runtime.payload["generation"] == 1
    assert port.provision_calls == 1
    assert port.reconcile_calls == 1
    assert ready.result["readiness"] == "ready"
    assert ready.result["historical_intent_preserved"] is True

    duplicate = worker.run(
        context=_context(store, command="reconcile-duplicate"),
        intent_id="workspace-intent-1",
        expected_intent_version=intent.state_version,
        claim_seconds=60,
        reconcile=True,
    )
    assert duplicate.mutation_applied is False
    assert port.provision_calls == 1
    assert port.reconcile_calls == 1


def test_claim_is_cas_fenced_and_unexpired_owner_cannot_be_stolen() -> None:
    store, clock = _bootstrapped()
    application = _application(store, clock)

    claimed = application.claim(
        WorkspaceProvisioningClaimCommand(
            context=_context(store, command="claim-first", worker="worker-first"),
            intent_id="workspace-intent-1",
            expected_intent_version=1,
            claim_seconds=60,
        )
    )
    with pytest.raises(KernelContractError) as busy:
        application.claim(
            WorkspaceProvisioningClaimCommand(
                context=_context(store, command="claim-second", worker="worker-second"),
                intent_id="workspace-intent-1",
                expected_intent_version=2,
                claim_seconds=60,
            )
        )

    assert busy.value.code == "workspace_provisioning_claim_busy"
    current = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id="workspace-intent-1",
    )
    assert current is not None
    assert current.payload["claim_owner_id"] == "worker-first"
    assert current.payload["claim_token"] == claimed.result["claim_token"]


def test_reconciliation_admission_is_idempotent_and_fences_claim_duration() -> None:
    store, _clock, port, worker = _blocked_workspace()
    intent = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id="workspace-intent-1",
    )
    assert intent is not None
    admitted = worker.admit_reconciliation(
        context=_context(store, command="reconcile-admit-73"),
        intent_id=intent.entity_id,
        expected_intent_version=intent.state_version,
        claim_seconds=73,
    )
    duplicate = worker.admit_reconciliation(
        context=_context(store, command="reconcile-admit-73-duplicate"),
        intent_id=intent.entity_id,
        expected_intent_version=intent.state_version,
        claim_seconds=73,
    )

    assert admitted.mutation_applied is True
    assert set(admitted.result) == (
        WORKSPACE_PROVISIONING_RECONCILIATION_ADMISSION_RESULT_FIELDS
    )
    assert admitted.result["requested_claim_seconds"] == 73
    assert duplicate.mutation_applied is False
    assert duplicate.result == admitted.result
    for private_field in (
        "claim_owner_id",
        "claim_token",
        "claim_epoch",
        "claim_expires_at",
        "receipt_id",
        "failure_id",
        "diagnostic_id",
    ):
        assert private_field not in admitted.result
    assert port.reconcile_calls == 0
    with pytest.raises(KernelContractError) as conflict:
        worker.admit_reconciliation(
            context=_context(store, command="reconcile-admit-conflict"),
            intent_id=intent.entity_id,
            expected_intent_version=intent.state_version,
            claim_seconds=74,
        )
    assert (
        conflict.value.code == "workspace_provisioning_reconciliation_identity_conflict"
    )
    with pytest.raises(KernelContractError) as duration:
        worker.run(
            context=_context(store, command="reconcile-wrong-duration"),
            intent_id=intent.entity_id,
            expected_intent_version=intent.state_version,
            claim_seconds=60,
            reconcile=True,
        )
    assert (
        duration.value.code
        == "workspace_provisioning_reconciliation_claim_duration_mismatch"
    )
    assert port.reconcile_calls == 0


def test_duplicate_terminal_callback_is_idempotent_without_second_activation() -> None:
    store, clock = _bootstrapped()
    port = _Provisioner()
    worker = _worker(store, clock, port)
    worker.run(
        context=_context(store, command="provision-once"),
        intent_id="workspace-intent-1",
        expected_intent_version=1,
        claim_seconds=60,
    )
    assert port.last_receipt is not None
    application = _application(store, clock)
    intent = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id="workspace-intent-1",
    )
    generation = store.read(
        entity_type="workspace_generation",
        entity_id="workspace-master-1",
    )
    assert intent is not None and generation is not None

    duplicate = application.settle(
        WorkspaceProvisioningSettlementCommand(
            context=_context(store, command="duplicate-callback"),
            receipt=port.last_receipt,
            expected_intent_version=intent.state_version,
        )
    )

    unchanged = store.read(
        entity_type="workspace_generation",
        entity_id="workspace-master-1",
    )
    assert duplicate.mutation_applied is False
    assert unchanged is not None and unchanged.record_digest == generation.record_digest


def test_reconciliation_stale_source_is_rejected_before_adapter_observation() -> None:
    store, _clock, port, worker = _blocked_workspace()
    intent = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id="workspace-intent-1",
    )
    assert intent is not None

    with pytest.raises(KernelContractError) as stale:
        worker.run(
            context=_context(store, command="reconcile-stale"),
            intent_id="workspace-intent-1",
            expected_intent_version=intent.state_version - 1,
            claim_seconds=60,
            reconcile=True,
        )

    assert stale.value.code == "workspace_provisioning_intent_stale"
    assert port.provision_calls == 1
    assert port.reconcile_calls == 0
    assert (
        store.list_for_session(
            entity_type="workspace_provisioning_reconciliation",
            session_id="session-1",
            max_items=10,
        )
        == ()
    )


def test_reconciliation_claim_race_loser_performs_no_adapter_effect() -> None:
    store, clock, port, _worker_instance = _blocked_workspace()
    application = _application(store, clock)
    pending = _pending_reconciliation(store)
    application.admit_reconciliation(
        WorkspaceProvisioningReconciliationAdmissionCommand(
            context=_context(store, command="reconcile-admit", worker="worker-first"),
            reconciliation=pending,
            expected_intent_version=pending.blocked_intent_state_version,
        )
    )
    application.claim_reconciliation(
        WorkspaceProvisioningReconciliationClaimCommand(
            context=_context(store, command="reconcile-claim", worker="worker-first"),
            reconciliation_id=pending.reconciliation_id,
            expected_reconciliation_version=1,
            claim_seconds=60,
        )
    )

    with pytest.raises(KernelContractError) as busy:
        application.claim_reconciliation(
            WorkspaceProvisioningReconciliationClaimCommand(
                context=_context(
                    store,
                    command="reconcile-race",
                    worker="worker-second",
                ),
                reconciliation_id=pending.reconciliation_id,
                expected_reconciliation_version=2,
                claim_seconds=60,
            )
        )

    assert busy.value.code == "workspace_provisioning_reconciliation_claim_busy"
    assert port.provision_calls == 1
    assert port.reconcile_calls == 0


def test_restart_resumes_same_claimed_reconciliation_without_provision_redispatch() -> (
    None
):
    store, clock, port, _worker_instance = _blocked_workspace()
    application = _application(store, clock)
    pending = _pending_reconciliation(store)
    owner_context = _context(
        store,
        command="reconcile-before-restart",
        worker="stable-reconciliation-worker",
    )
    application.admit_reconciliation(
        WorkspaceProvisioningReconciliationAdmissionCommand(
            context=owner_context,
            reconciliation=pending,
            expected_intent_version=pending.blocked_intent_state_version,
        )
    )
    application.claim_reconciliation(
        WorkspaceProvisioningReconciliationClaimCommand(
            context=owner_context,
            reconciliation_id=pending.reconciliation_id,
            expected_reconciliation_version=1,
            claim_seconds=60,
        )
    )

    restarted_worker = _worker(store, clock, port)
    settled = restarted_worker.run(
        context=_context(
            store,
            command="reconcile-after-restart",
            worker="stable-reconciliation-worker",
        ),
        intent_id="workspace-intent-1",
        expected_intent_version=pending.blocked_intent_state_version,
        claim_seconds=60,
        reconcile=True,
    )

    records = store.list_for_session(
        entity_type="workspace_provisioning_reconciliation",
        session_id="session-1",
        max_items=10,
    )
    assert len(records) == 1
    assert records[0].entity_id == pending.reconciliation_id
    assert records[0].payload["status"] == "ready"
    assert settled.result["readiness"] == "ready"
    assert port.provision_calls == 1
    assert port.reconcile_calls == 1


def test_uncertain_reconciliation_requires_explicit_parent_linked_successor() -> None:
    store, _clock, port, worker = _blocked_workspace(fail_reconcile=True)
    intent = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id="workspace-intent-1",
    )
    assert intent is not None
    _admit_reconciliation(worker, store, command="reconcile-uncertain-1")
    first = worker.run(
        context=_context(store, command="reconcile-uncertain-1"),
        intent_id="workspace-intent-1",
        expected_intent_version=intent.state_version,
        claim_seconds=60,
        reconcile=True,
    )
    assert first.result["status"] == "blocked"
    assert first.result["reconcile_required"] is True

    with pytest.raises(KernelContractError) as requires_admission:
        worker.run(
            context=_context(store, command="reconcile-no-hidden-attempt"),
            intent_id="workspace-intent-1",
            expected_intent_version=intent.state_version,
            claim_seconds=60,
            reconcile=True,
        )
    assert (
        requires_admission.value.code
        == "workspace_provisioning_reconciliation_terminal"
    )
    assert port.reconcile_calls == 1
    assert (
        len(
            store.list_for_session(
                entity_type="workspace_provisioning_reconciliation",
                session_id="session-1",
                max_items=10,
            )
        )
        == 1
    )

    port.fail_reconcile = False
    _admit_reconciliation(worker, store, command="reconcile-ready-2")
    second = worker.run(
        context=_context(store, command="reconcile-ready-2"),
        intent_id="workspace-intent-1",
        expected_intent_version=intent.state_version,
        claim_seconds=60,
        reconcile=True,
    )

    records = tuple(
        WorkspaceProvisioningReconciliation.from_dict(record.payload)
        for record in store.list_for_session(
            entity_type="workspace_provisioning_reconciliation",
            session_id="session-1",
            max_items=10,
        )
    )
    first_record, second_record = sorted(records, key=lambda item: item.attempt)
    assert first_record.status is WorkspaceProvisioningReconciliationStatus.BLOCKED
    assert second_record.status is WorkspaceProvisioningReconciliationStatus.READY
    assert second_record.parent_reconciliation_id == first_record.reconciliation_id
    assert second.result["readiness"] == "ready"
    assert len(set(port.reconciliation_ids)) == 2
    assert port.provision_calls == 1
    assert port.reconcile_calls == 2


def test_reconciliation_terminal_collision_and_legacy_in_place_path_fail_closed() -> (
    None
):
    store, clock, port, worker = _blocked_workspace()
    intent = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id="workspace-intent-1",
    )
    assert intent is not None
    _admit_reconciliation(worker, store, command="reconcile-ready")
    worker.run(
        context=_context(store, command="reconcile-ready"),
        intent_id="workspace-intent-1",
        expected_intent_version=intent.state_version,
        claim_seconds=60,
        reconcile=True,
    )
    assert port.last_receipt is not None
    reconciliation_record = store.list_for_session(
        entity_type="workspace_provisioning_reconciliation",
        session_id="session-1",
        max_items=10,
    )[0]
    reconciliation = WorkspaceProvisioningReconciliation.from_dict(
        reconciliation_record.payload
    )
    collision_receipt = replace(
        port.last_receipt,
        receipt_id="workspace-receipt-reconciliation-collision",
        terminal_receipt_digest=_digest("reconciliation-terminal-collision"),
    )
    application = _application(store, clock)

    with pytest.raises(KernelContractError) as collision:
        application.settle_reconciliation(
            WorkspaceProvisioningReconciliationSettlementCommand(
                context=_context(store, command="reconcile-collision"),
                reconciliation_id=reconciliation.reconciliation_id,
                reconciliation_claim_token=reconciliation.claim_token or "",
                reconciliation_claim_epoch=reconciliation.claim_epoch,
                receipt=collision_receipt,
                expected_reconciliation_version=reconciliation_record.state_version,
                expected_intent_version=intent.state_version,
            )
        )
    assert (
        collision.value.code
        == "workspace_provisioning_reconciliation_terminal_collision"
    )

    with pytest.raises(KernelContractError) as legacy:
        application.reconcile(
            WorkspaceProvisioningSettlementCommand(
                context=_context(store, command="legacy-in-place-reconcile"),
                receipt=port.last_receipt,
                expected_intent_version=intent.state_version,
                reconciliation_of_blocked=True,
            )
        )
    assert (
        legacy.value.code == "workspace_provisioning_reconciliation_occurrence_required"
    )


def test_diagnosed_reconciliation_allows_explicit_successor_without_history_rewrite() -> (
    None
):
    store, clock = _bootstrapped()
    port = _Provisioner(fail_dispatch=True, reconcile_no_effect=True)
    worker = _worker(store, clock, port)
    worker.run(
        context=_context(store, command="provision-uncertain"),
        intent_id="workspace-intent-1",
        expected_intent_version=1,
        claim_seconds=60,
    )
    port.fail_dispatch = False
    failed_record = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id="workspace-intent-1",
    )
    assert failed_record is not None
    _admit_reconciliation(worker, store, command="reconcile-no-effect")
    worker.run(
        context=_context(store, command="reconcile-no-effect"),
        intent_id="workspace-intent-1",
        expected_intent_version=failed_record.state_version,
        claim_seconds=60,
        reconcile=True,
    )
    reconciliation_record = store.list_for_session(
        entity_type="workspace_provisioning_reconciliation",
        session_id="session-1",
        max_items=10,
    )[0]
    reconciliation = WorkspaceProvisioningReconciliation.from_dict(
        reconciliation_record.payload
    )
    assert reconciliation.status is WorkspaceProvisioningReconciliationStatus.BLOCKED
    assert reconciliation.reconcile_required is False

    generation_record = store.read(
        entity_type="workspace_generation",
        entity_id="workspace-master-1",
    )
    lease_record = store.read(
        entity_type="agent_authority_lease",
        entity_id="root-lease-1",
    )
    assert generation_record is not None and lease_record is not None
    failed_generation = WorkspaceGeneration.from_dict(generation_record.payload)
    old_lease = AgentAuthorityLease.from_dict(lease_record.payload)
    successor_operation_id = "workspace-provision-successor-2"
    successor_generation = WorkspaceGeneration(
        workspace_id=failed_generation.workspace_id,
        workspace_kind=failed_generation.workspace_kind,
        session_id=failed_generation.session_id,
        owner_member_id=failed_generation.owner_member_id,
        generation=failed_generation.generation + 1,
        state_version=failed_generation.state_version + 1,
        status=WorkspaceGenerationStatus.RESERVED,
        provider_id=failed_generation.provider_id,
        target_id=failed_generation.target_id,
        created_at=clock.now_iso(),
        updated_at=clock.now_iso(),
        target_qualification_digest=failed_generation.target_qualification_digest,
        controlled_operation_id=successor_operation_id,
    )
    failed_intent = WorkspaceProvisioningIntent.from_dict(failed_record.payload)
    successor_intent = WorkspaceProvisioningIntent(
        intent_id="workspace-intent-successor-2",
        session_id=failed_intent.session_id,
        agent_member_id=failed_intent.agent_member_id,
        workspace_id=failed_intent.workspace_id,
        generation=failed_intent.generation + 1,
        repository_pin_digest=failed_intent.repository_pin_digest,
        provider_id=failed_intent.provider_id,
        target_id=failed_intent.target_id,
        adapter_binding_digest=failed_intent.adapter_binding_digest,
        controlled_operation_id=successor_operation_id,
        status=WorkspaceProvisioningStatus.PENDING,
        state_version=1,
        claim_epoch=0,
        created_at=clock.now_iso(),
        updated_at=clock.now_iso(),
    )
    successor_lease = AgentAuthorityLease.create(
        lease_id="root-lease-successor-2",
        session_id=old_lease.session_id,
        agent_member_id=old_lease.agent_member_id,
        grants=tuple(
            type(grant).create(
                grant_id=grant.grant_id,
                scope_id=grant.scope_id,
                operations=grant.operations,
                generation=old_lease.generation + 1,
                fence=old_lease.fence + 1,
            )
            for grant in old_lease.grants
        ),
        generation=old_lease.generation + 1,
        fence=old_lease.fence + 1,
        state=AgentAuthorityLeaseState.PENDING,
        issued_at=old_lease.issued_at,
        expires_at=old_lease.expires_at,
        agent_id=old_lease.agent_id,
        workspace_generation=successor_generation.generation,
        parent_lease_id=old_lease.lease_id,
        policy_digest=old_lease.policy_digest,
        idempotency_key="root-lease-successor-2",
        updated_at=clock.now_iso(),
    )

    replaced = _application(store, clock).replace_failed_generation(
        WorkspaceProvisioningReplacementCommand(
            context=_context(store, command="replace-diagnosed-generation"),
            failed_intent_id=failed_intent.intent_id,
            expected_failed_intent_version=failed_record.state_version,
            successor_generation=successor_generation,
            successor_intent=successor_intent,
            successor_lease=successor_lease,
            resolved_reconciliation_id=reconciliation.reconciliation_id,
        )
    )

    preserved_failed = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id=failed_intent.intent_id,
    )
    preserved_reconciliation = store.read(
        entity_type="workspace_provisioning_reconciliation",
        entity_id=reconciliation.reconciliation_id,
    )
    successor_record = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id=successor_intent.intent_id,
    )
    current_generation = store.read(
        entity_type="workspace_generation",
        entity_id=successor_generation.workspace_id,
    )
    assert preserved_failed is not None
    assert preserved_failed.record_digest == failed_record.record_digest
    assert preserved_reconciliation is not None
    assert preserved_reconciliation.record_digest == reconciliation_record.record_digest
    assert (
        successor_record is not None and successor_record.payload["status"] == "pending"
    )
    assert current_generation is not None
    assert current_generation.payload["generation"] == 2
    assert current_generation.payload["status"] == "reserved"
    assert (
        replaced.result["resolved_reconciliation_id"]
        == reconciliation.reconciliation_id
    )
    assert port.provision_calls == 1
    assert port.reconcile_calls == 1


def test_worker_builds_explicit_successor_graph_without_adapter_dispatch() -> None:
    store, clock = _bootstrapped()
    port = _Provisioner(fail_dispatch=True, reconcile_no_effect=True)
    worker = _worker(store, clock, port)
    worker.run(
        context=_context(store, command="provision-before-successor"),
        intent_id="workspace-intent-1",
        expected_intent_version=1,
        claim_seconds=60,
    )
    port.fail_dispatch = False
    failed_record = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id="workspace-intent-1",
    )
    assert failed_record is not None
    _admit_reconciliation(worker, store, command="diagnose-before-successor")
    worker.run(
        context=_context(store, command="diagnose-before-successor"),
        intent_id=failed_record.entity_id,
        expected_intent_version=failed_record.state_version,
        claim_seconds=60,
        reconcile=True,
    )
    reconciliation_record = store.list_for_session(
        entity_type="workspace_provisioning_reconciliation",
        session_id="session-1",
        max_items=10,
    )[0]
    failed_before = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id=failed_record.entity_id,
    )
    assert failed_before is not None

    replaced = worker.replace_failed_generation(
        context=_context(store, command="explicit-successor"),
        failed_intent_id=failed_before.entity_id,
        expected_failed_intent_version=failed_before.state_version,
        resolved_reconciliation_id=reconciliation_record.entity_id,
    )

    successor_id = replaced.result["successor_intent_id"]
    successor = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id=successor_id,
    )
    failed_after = store.read(
        entity_type="workspace_provisioning_intent",
        entity_id=failed_before.entity_id,
    )
    current_generation = store.read(
        entity_type="workspace_generation",
        entity_id="workspace-master-1",
    )
    assert successor is not None
    assert successor.payload["status"] == "pending"
    assert successor.payload["generation"] == 2
    assert failed_after is not None
    assert failed_after.record_digest == failed_before.record_digest
    assert current_generation is not None
    assert current_generation.payload["status"] == "reserved"
    assert current_generation.payload["generation"] == 2
    assert replaced.result["resolved_reconciliation_id"] == (
        reconciliation_record.entity_id
    )
    assert dict(replaced.result) == {
        "failed_intent_id": failed_before.entity_id,
        "resolved_reconciliation_id": reconciliation_record.entity_id,
        "successor_intent_id": successor_id,
        "workspace_id": "workspace-master-1",
        "generation": 2,
        "readiness": "provisioning",
        "successor_intent_created": True,
        "workspace_generation_reserved": True,
        "workspace_provisioning_enqueued": True,
        "adapter_invoked": False,
        "external_effect_performed": False,
        "runtime_executed": False,
        "task_transition_performed": False,
        "fallback_performed": False,
    }
    assert port.provision_calls == 1
    assert port.reconcile_calls == 1
