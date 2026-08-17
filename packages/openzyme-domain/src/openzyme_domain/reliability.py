from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from typing import ClassVar


CONTROLLED_OPERATION_EXECUTION_SCHEMA_VERSION = "controlled_operation_execution@1"
CONTROLLED_OPERATION_EXECUTION_EVENT_SCHEMA_VERSION = (
    "controlled_operation_execution_event@1"
)
CONTROLLED_OPERATION_RESULT_HANDLE_SCHEMA_VERSION = (
    "controlled_operation_result_handle@1"
)
CONTROLLED_OPERATION_DISPATCH_REQUEST_SCHEMA_VERSION = (
    "controlled_operation_dispatch_request@1"
)
CONTROLLED_OPERATION_PROVIDER_DISPATCH_RECEIPT_SCHEMA_VERSION = (
    "controlled_operation_provider_dispatch_receipt@1"
)
CONTROLLED_OPERATION_PROVIDER_OBSERVATION_RECEIPT_SCHEMA_VERSION = (
    "controlled_operation_provider_observation_receipt@1"
)
CONTINUATION_STATE_SCHEMA_VERSION = "continuation_state@2"
RUNTIME_COMMAND_SCHEMA_VERSION = "runtime_command@1"
MUTATION_SCOPE_SCHEMA_VERSION = "mutation_scope@1"
MUTATION_WRITER_SCHEMA_VERSION = "mutation_writer@1"
QUIESCENCE_RECEIPT_SCHEMA_VERSION = "quiescence_receipt@1"
QUIESCENCE_SNAPSHOT_SCHEMA_VERSION = "quiescence_snapshot@1"


def _serialize_record(record: object, *, schema_version: str) -> dict[str, Any]:
    def serialize(value: Any) -> Any:
        if isinstance(value, StrEnum):
            return value.value
        if isinstance(value, tuple):
            return [serialize(item) for item in value]
        if isinstance(value, list):
            return [serialize(item) for item in value]
        if isinstance(value, dict):
            return {str(key): serialize(item) for key, item in value.items()}
        return value

    return {
        "schema_version": schema_version,
        **{key: serialize(value) for key, value in asdict(record).items()},
    }


class ControlledOperationOwnerMode(StrEnum):
    LEGACY_SYNC = "legacy_sync"
    DURABLE_ASYNC_V1 = "durable_async_v1"


class ControlledOperationExecutionLifecycle(StrEnum):
    AWAITING_APPROVAL = "awaiting_approval"
    READY = "ready"
    CLAIMED = "claimed"
    DISPATCHING = "dispatching"
    WAITING_EXTERNAL = "waiting_external"
    RESULT_STAGING = "result_staging"
    RESULT_READY = "result_ready"
    RECONCILE_REQUIRED = "reconcile_required"
    TERMINAL = "terminal"

    @property
    def is_terminal(self) -> bool:
        return self is self.TERMINAL


class ControlledOperationExecutionPhase(StrEnum):
    ADMISSION = "admission"
    APPROVAL = "approval"
    CLAIM = "claim"
    DISPATCH = "dispatch"
    POLL = "poll"
    RECONCILE = "reconcile"
    RESULT_STAGING = "result_staging"
    TERMINAL = "terminal"


class ControlledOperationExecutionTerminalOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RECOVERY_FAILED = "recovery_failed"


class ExternalEffectCertainty(StrEnum):
    NO_EFFECT = "no_effect"
    DISPATCH_IN_DOUBT = "dispatch_in_doubt"
    EFFECT_KNOWN = "effect_known"
    TERMINAL_KNOWN = "terminal_known"


class RetryEligibility(StrEnum):
    SAME_PHASE_SAFE = "same_phase_safe"
    VERIFY_THEN_RETRY = "verify_then_retry"
    RECONCILE_REQUIRED = "reconcile_required"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class ControlledOperationExecution:
    SCHEMA_VERSION: ClassVar[str] = CONTROLLED_OPERATION_EXECUTION_SCHEMA_VERSION

    execution_id: str
    operation_id: str
    session_id: str
    owner_mode: ControlledOperationOwnerMode
    operation_digest: str
    approval_digest: str | None
    route_policy_id: str
    selected_backend: str
    adapter_policy_id: str
    input_identity_digest: str
    expected_output_contract_digest: str
    runtime_identity_digest: str
    lifecycle_state: ControlledOperationExecutionLifecycle
    effect_certainty: ExternalEffectCertainty
    retry_eligibility: RetryEligibility
    dispatch_generation: int
    state_version: int
    fencing_token: int
    created_at: str
    updated_at: str
    task_id: str | None = None
    lane_id: str | None = None
    approval_id: str | None = None
    terminal_outcome: ControlledOperationExecutionTerminalOutcome | None = None
    lease_owner: str | None = None
    lease_token: str | None = None
    lease_expires_at: str | None = None
    backend_handle_ref: str | None = None
    result_handle_ref: str | None = None
    result_digest: str | None = None
    error_code: str | None = None
    safe_error_summary: str | None = None
    terminal_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


@dataclass(frozen=True, slots=True)
class ControlledOperationExecutionEvent:
    SCHEMA_VERSION: ClassVar[str] = CONTROLLED_OPERATION_EXECUTION_EVENT_SCHEMA_VERSION

    event_id: str
    execution_id: str
    operation_id: str
    session_id: str
    state_version: int
    dispatch_generation: int
    phase: ControlledOperationExecutionPhase
    lifecycle_state: ControlledOperationExecutionLifecycle
    effect_certainty: ExternalEffectCertainty
    retry_eligibility: RetryEligibility
    fencing_token: int
    created_at: str
    previous_lifecycle_state: ControlledOperationExecutionLifecycle | None = None
    terminal_outcome: ControlledOperationExecutionTerminalOutcome | None = None
    safe_receipt_digest: str | None = None
    safe_summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


@dataclass(frozen=True, slots=True)
class ControlledOperationResultHandle:
    SCHEMA_VERSION: ClassVar[str] = CONTROLLED_OPERATION_RESULT_HANDLE_SCHEMA_VERSION

    result_handle_id: str
    execution_id: str
    operation_id: str
    session_id: str
    dispatch_generation: int
    terminal_outcome: ControlledOperationExecutionTerminalOutcome
    bounded_result_envelope: dict[str, Any]
    result_digest: str
    origin: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


@dataclass(frozen=True, slots=True)
class ControlledOperationDispatchRequest:
    """Host-private immutable input for one canonical durable execution.

    This record intentionally has no public ``to_dict`` projection.  Its envelope
    may contain validated adapter inputs that are required for restart recovery but
    must never be copied into agent, workspace, activity, or API projections.
    """

    SCHEMA_VERSION: ClassVar[str] = CONTROLLED_OPERATION_DISPATCH_REQUEST_SCHEMA_VERSION

    request_id: str
    execution_id: str
    operation_id: str
    session_id: str
    request_digest: str
    request_envelope: dict[str, Any]
    request_size_bytes: int
    created_at: str

    def to_private_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


@dataclass(frozen=True, slots=True)
class ControlledOperationProviderDispatchReceipt:
    """Host-private immutable proof that one provider effect was accepted.

    The bounded envelope is owned by the selected provider adapter.  Core only
    binds its exact bytes to the canonical execution, dispatch generation and
    frozen provider request identity so a restart can reconcile without
    replaying the submit call.
    """

    SCHEMA_VERSION: ClassVar[str] = (
        CONTROLLED_OPERATION_PROVIDER_DISPATCH_RECEIPT_SCHEMA_VERSION
    )

    receipt_id: str
    execution_id: str
    operation_id: str
    session_id: str
    dispatch_generation: int
    provider_request_id: str
    provider_id: str
    external_handle_ref: str
    receipt_digest: str
    receipt_envelope: dict[str, Any]
    receipt_size_bytes: int
    created_at: str

    def to_private_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


@dataclass(frozen=True, slots=True)
class ControlledOperationProviderObservationReceipt:
    """Host-private append-only observation of one exact provider handle."""

    SCHEMA_VERSION: ClassVar[str] = (
        CONTROLLED_OPERATION_PROVIDER_OBSERVATION_RECEIPT_SCHEMA_VERSION
    )

    observation_id: str
    dispatch_receipt_id: str
    execution_id: str
    operation_id: str
    session_id: str
    dispatch_generation: int
    observation_index: int
    provider_request_id: str
    provider_id: str
    external_handle_ref: str
    observation_digest: str
    observation_envelope: dict[str, Any]
    observation_size_bytes: int
    created_at: str

    def to_private_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


class RuntimeCommandType(StrEnum):
    RUNTIME_DRAIN = "runtime.drain"


class RuntimeCommandStatus(StrEnum):
    ACCEPTED = "accepted"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    FAILED = "failed"
    LOCKED = "locked"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            self.COMPLETED,
            self.FAILED,
            self.LOCKED,
            self.CANCELLED,
        }


@dataclass(frozen=True, slots=True)
class RuntimeCommandRecord:
    SCHEMA_VERSION: ClassVar[str] = RUNTIME_COMMAND_SCHEMA_VERSION

    command_id: str
    session_id: str
    command_type: RuntimeCommandType
    request_digest: str
    idempotency_key: str
    status: RuntimeCommandStatus
    max_signals: int
    max_steps_per_agent: int
    auto_enqueue_ready_tasks: bool
    state_version: int
    fencing_token: int
    accepted_at: str
    claim_owner: str | None = None
    lease_token: str | None = None
    lease_expires_at: str | None = None
    bounded_outcome_summary: dict[str, Any] | None = None
    error_code: str | None = None
    safe_error_summary: str | None = None
    safe_retry_hint: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


class ContinuationResumeStrategy(StrEnum):
    LEGACY_NON_RESUMABLE = "legacy_non_resumable"
    ATTACHED_PROCESS = "attached_process"
    JOURNALED_SDK_CALL_BOUNDARY = "journaled_sdk_call_boundary"


class ContinuationDeliveryState(StrEnum):
    LEGACY_UNAVAILABLE = "legacy_unavailable"
    AWAITING_RESULT = "awaiting_result"
    READY = "ready"
    CLAIMED = "claimed"
    DELIVERED = "delivered"
    FAILED = "failed"
    RECOVERY_FAILED = "recovery_failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            self.LEGACY_UNAVAILABLE,
            self.DELIVERED,
            self.FAILED,
            self.RECOVERY_FAILED,
            self.CANCELLED,
        }


class MutationScopeKind(StrEnum):
    SESSION = "session"
    ATTEMPT = "attempt"


class MutationScopeState(StrEnum):
    OPEN = "open"
    FREEZING = "freezing"
    QUIESCENT = "quiescent"
    SEALED = "sealed"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {self.SEALED, self.FAILED}


class MutationWriterKind(StrEnum):
    AGENT_TURN = "agent_turn"
    RUNTIME_COMMAND = "runtime_command"
    SANDBOX_PROCESS = "sandbox_process"
    CONTROLLED_OPERATION = "controlled_operation"
    CONTINUATION_DELIVERY = "continuation_delivery"
    ENGINE_CALLBACK = "engine_callback"
    FILE_PUBLISHER = "file_publisher"
    REPORT_PUBLISHER = "report_publisher"
    EVENT_OUTBOX_PUBLISHER = "event_outbox_publisher"
    RUNNER_CALLBACK = "runner_callback"
    ATTEMPT_DRIVER = "attempt_driver"
    SEAL_PUBLISHER = "seal_publisher"
    LIVE_TOKEN_LEDGER = "live_token_ledger"


class MutationWriterState(StrEnum):
    REGISTERED = "registered"
    RETIRING = "retiring"
    RETIRED = "retired"
    REJECTED = "rejected"

    @property
    def is_terminal(self) -> bool:
        return self in {self.RETIRED, self.REJECTED}


@dataclass(frozen=True, slots=True)
class MutationScope:
    SCHEMA_VERSION: ClassVar[str] = MUTATION_SCOPE_SCHEMA_VERSION

    scope_id: str
    scope_kind: MutationScopeKind
    scope_ref: str
    state: MutationScopeState
    generation: int
    mutation_fencing_token: int
    state_version: int
    policy_id: str
    writer_coverage_manifest_digest: str
    opened_at: str
    session_id: str | None = None
    parent_scope_id: str | None = None
    freeze_requested_at: str | None = None
    quiescent_at: str | None = None
    sealed_at: str | None = None
    failed_at: str | None = None
    safe_error_summary: str | None = None
    sealed_receipt_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


@dataclass(frozen=True, slots=True)
class MutationWriter:
    SCHEMA_VERSION: ClassVar[str] = MUTATION_WRITER_SCHEMA_VERSION

    writer_id: str
    scope_id: str
    scope_generation: int
    owner_kind: MutationWriterKind
    owner_ref: str
    state: MutationWriterState
    fencing_token: int
    state_version: int
    registered_at: str
    parent_writer_id: str | None = None
    process_epoch: int | None = None
    retired_at: str | None = None
    terminal_proof_digest: str | None = None
    safe_error_summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


@dataclass(frozen=True, slots=True)
class QuiescenceReceipt:
    SCHEMA_VERSION: ClassVar[str] = QUIESCENCE_RECEIPT_SCHEMA_VERSION

    receipt_id: str
    scope_id: str
    seal_generation: int
    policy_digest: str
    coverage_digest: str
    writer_set_digest: str
    terminal_proof_digest: str
    sqlite_high_watermark: str
    event_high_watermark: str
    file_high_watermark: str
    snapshot_digest: str
    receipt_digest: str
    issued_at: str

    def to_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


@dataclass(frozen=True, slots=True)
class QuiescenceSnapshot:
    """Host-private immutable evidence used to verify a quiescence receipt offline."""

    SCHEMA_VERSION: ClassVar[str] = QUIESCENCE_SNAPSHOT_SCHEMA_VERSION

    snapshot_id: str
    receipt_id: str
    scope_id: str
    seal_generation: int
    evidence: dict[str, Any]
    evidence_digest: str
    created_at: str

    def to_private_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)
