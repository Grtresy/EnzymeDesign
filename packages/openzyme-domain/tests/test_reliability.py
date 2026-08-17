from __future__ import annotations

import pytest

from openzyme_domain import CONTROLLED_OPERATION_EXECUTION_SCHEMA_VERSION
from openzyme_domain import CONTINUATION_STATE_SCHEMA_VERSION
from openzyme_domain import MUTATION_SCOPE_SCHEMA_VERSION
from openzyme_domain import RUNTIME_COMMAND_SCHEMA_VERSION
from openzyme_domain import ContinuationDeliveryState
from openzyme_domain import ContinuationResumeStrategy
from openzyme_domain import ContinuationState
from openzyme_domain import ContinuationStateStatus
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionEvent
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationExecutionPhase
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ControlledOperationResultHandle
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import MutationScope
from openzyme_domain import MutationScopeKind
from openzyme_domain import MutationScopeState
from openzyme_domain import MutationWriter
from openzyme_domain import MutationWriterKind
from openzyme_domain import MutationWriterState
from openzyme_domain import QuiescenceReceipt
from openzyme_domain import RetryEligibility
from openzyme_domain import RuntimeCommandRecord
from openzyme_domain import RuntimeCommandStatus
from openzyme_domain import RuntimeCommandType


def _execution() -> ControlledOperationExecution:
    return ControlledOperationExecution(
        execution_id="exec_001",
        operation_id="op_001",
        session_id="sess_001",
        owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
        operation_digest="sha256:operation",
        approval_digest="sha256:approval",
        route_policy_id="fixture_v1",
        selected_backend="fixture",
        adapter_policy_id="fixture_adapter_v1",
        input_identity_digest="sha256:inputs",
        expected_output_contract_digest="sha256:outputs",
        runtime_identity_digest="sha256:runtime",
        lifecycle_state=ControlledOperationExecutionLifecycle.READY,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
        dispatch_generation=0,
        state_version=1,
        fencing_token=0,
        created_at="2026-07-21T00:00:00+00:00",
        updated_at="2026-07-21T00:00:00+00:00",
        approval_id="approval_001",
    )


def test_controlled_operation_execution_contract_is_closed_and_versioned() -> None:
    execution = _execution()

    payload = execution.to_dict()
    assert payload["schema_version"] == CONTROLLED_OPERATION_EXECUTION_SCHEMA_VERSION
    assert payload["owner_mode"] == "durable_async_v1"
    assert payload["lifecycle_state"] == "ready"
    assert payload["effect_certainty"] == "no_effect"
    assert payload["retry_eligibility"] == "same_phase_safe"
    assert ControlledOperationExecutionLifecycle.TERMINAL.is_terminal is True

    with pytest.raises(ValueError):
        ExternalEffectCertainty("unknown")
    with pytest.raises(ValueError):
        RetryEligibility("retryable")


def test_execution_event_and_result_handle_keep_audit_and_result_separate() -> None:
    event = ControlledOperationExecutionEvent(
        event_id="event_001",
        execution_id="exec_001",
        operation_id="op_001",
        session_id="sess_001",
        state_version=2,
        dispatch_generation=1,
        phase=ControlledOperationExecutionPhase.DISPATCH,
        lifecycle_state=ControlledOperationExecutionLifecycle.DISPATCHING,
        previous_lifecycle_state=ControlledOperationExecutionLifecycle.CLAIMED,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.VERIFY_THEN_RETRY,
        fencing_token=4,
        safe_receipt_digest="sha256:receipt",
        created_at="2026-07-21T00:00:01+00:00",
    )
    result = ControlledOperationResultHandle(
        result_handle_id="result_001",
        execution_id="exec_001",
        operation_id="op_001",
        session_id="sess_001",
        dispatch_generation=1,
        terminal_outcome=ControlledOperationExecutionTerminalOutcome.SUCCEEDED,
        bounded_result_envelope={"summary": "completed"},
        result_digest="sha256:result",
        origin="host_adapter_executor",
        created_at="2026-07-21T00:00:02+00:00",
    )

    assert event.to_dict()["previous_lifecycle_state"] == "claimed"
    assert event.to_dict()["phase"] == "dispatch"
    assert result.to_dict()["terminal_outcome"] == "succeeded"
    assert result.to_dict()["bounded_result_envelope"] == {"summary": "completed"}


def test_runtime_command_is_data_only_with_explicit_terminal_statuses() -> None:
    command = RuntimeCommandRecord(
        command_id="cmd_001",
        session_id="sess_001",
        command_type=RuntimeCommandType.RUNTIME_DRAIN,
        request_digest="sha256:request",
        idempotency_key="idem_001",
        status=RuntimeCommandStatus.ACCEPTED,
        max_signals=4,
        max_steps_per_agent=2,
        auto_enqueue_ready_tasks=False,
        state_version=1,
        fencing_token=0,
        accepted_at="2026-07-21T00:00:00+00:00",
    )

    payload = command.to_dict()
    assert payload["schema_version"] == RUNTIME_COMMAND_SCHEMA_VERSION
    assert payload["command_type"] == "runtime.drain"
    assert payload["status"] == "accepted"
    assert RuntimeCommandStatus.ACCEPTED.is_terminal is False
    assert RuntimeCommandStatus.LOCKED.is_terminal is True


def test_legacy_continuation_defaults_do_not_fabricate_resumability() -> None:
    continuation = ContinuationState(
        continuation_id="cont_001",
        session_id="sess_001",
        operation_id="op_001",
        sandbox_run_id="sandbox_run_001",
        approval_id="approval_001",
        status=ContinuationStateStatus.WAITING_APPROVAL,
        created_at="2026-07-21T00:00:00+00:00",
        updated_at="2026-07-21T00:00:00+00:00",
    )

    payload = continuation.to_dict()
    assert continuation.resume_strategy is ContinuationResumeStrategy.LEGACY_NON_RESUMABLE
    assert continuation.delivery_state is ContinuationDeliveryState.LEGACY_UNAVAILABLE
    assert continuation.delivery_fencing_token == 0
    assert payload["schema_version"] == CONTINUATION_STATE_SCHEMA_VERSION
    assert payload["resume_strategy"] == "legacy_non_resumable"
    assert payload["delivery_state"] == "legacy_unavailable"


def test_mutation_scope_writer_and_receipt_are_versioned_data_contracts() -> None:
    scope = MutationScope(
        scope_id="scope_001",
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="attempt:r41",
        state=MutationScopeState.FREEZING,
        generation=3,
        mutation_fencing_token=7,
        state_version=2,
        policy_id="host_mutation_policy_v1",
        writer_coverage_manifest_digest="sha256:coverage",
        opened_at="2026-07-21T00:00:00+00:00",
        freeze_requested_at="2026-07-21T00:01:00+00:00",
    )
    writer = MutationWriter(
        writer_id="writer_001",
        scope_id="scope_001",
        scope_generation=3,
        owner_kind=MutationWriterKind.CONTROLLED_OPERATION,
        owner_ref="exec_001",
        state=MutationWriterState.RETIRED,
        fencing_token=7,
        state_version=2,
        registered_at="2026-07-21T00:00:10+00:00",
        retired_at="2026-07-21T00:00:50+00:00",
        terminal_proof_digest="sha256:terminal-proof",
    )
    receipt = QuiescenceReceipt(
        receipt_id="receipt_001",
        scope_id="scope_001",
        seal_generation=3,
        policy_digest="sha256:policy",
        coverage_digest="sha256:coverage",
        writer_set_digest="sha256:writers",
        terminal_proof_digest="sha256:terminal-proof",
        sqlite_high_watermark="sqlite:25:100",
        event_high_watermark="event:200",
        file_high_watermark="file:50",
        snapshot_digest="sha256:snapshot",
        receipt_digest="sha256:receipt",
        issued_at="2026-07-21T00:02:00+00:00",
    )

    assert scope.to_dict()["schema_version"] == MUTATION_SCOPE_SCHEMA_VERSION
    assert scope.to_dict()["state"] == "freezing"
    assert writer.to_dict()["owner_kind"] == "controlled_operation"
    assert writer.to_dict()["state"] == "retired"
    assert receipt.to_dict()["seal_generation"] == 3
    assert MutationScopeState.QUIESCENT.is_terminal is False
    assert MutationScopeState.SEALED.is_terminal is True
