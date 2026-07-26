from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from typing import ClassVar


SCIENTIFIC_ATTEMPT_AUTHORIZATION_SCHEMA_VERSION = (
    "scientific_attempt_authorization@1"
)
SCIENTIFIC_ATTEMPT_ADMISSION_REQUEST_SCHEMA_VERSION = (
    "scientific_attempt_admission_request@1"
)
SCIENTIFIC_ATTEMPT_SCHEMA_VERSION = "scientific_attempt@1"
SCIENTIFIC_CHAIN_SELECTION_SCHEMA_VERSION = "scientific_chain_selection@1"
SCIENTIFIC_OPERATION_DISPOSITION_SCHEMA_VERSION = (
    "scientific_operation_disposition@1"
)
SCIENTIFIC_EFFECT_ADOPTION_SCHEMA_VERSION = "scientific_effect_adoption@1"
SCIENTIFIC_ARTIFACT_MATERIALIZATION_SCHEMA_VERSION = (
    "scientific_artifact_materialization@1"
)
SCIENTIFIC_ATTEMPT_CLOSURE_REQUEST_SCHEMA_VERSION = (
    "scientific_attempt_closure_request@1"
)
SCIENTIFIC_ATTEMPT_CLOSURE_RESPONSE_SCHEMA_VERSION = (
    "scientific_attempt_closure_response@1"
)
SCIENTIFIC_ATTEMPT_CLOSURE_SCHEMA_VERSION = "scientific_attempt_closure@1"


def _serialize_record(record: object, *, schema_version: str) -> dict[str, Any]:
    def serialize(value: Any) -> Any:
        if isinstance(value, StrEnum):
            return value.value
        if isinstance(value, tuple):
            return [serialize(item) for item in value]
        if isinstance(value, dict):
            return {str(key): serialize(item) for key, item in value.items()}
        return value

    return {
        "schema_version": schema_version,
        **{key: serialize(value) for key, value in asdict(record).items()},
    }


def _require_nonempty(record_name: str, **values: str) -> None:
    for field_name, value in values.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{record_name}.{field_name} must be non-empty")


def _require_unique_nonempty_tuple(
    record_name: str,
    field_name: str,
    values: tuple[str, ...],
    *,
    allow_empty: bool = False,
) -> None:
    if not allow_empty and not values:
        raise ValueError(f"{record_name}.{field_name} must not be empty")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(
            f"{record_name}.{field_name} must contain only non-empty strings"
        )
    if len(set(values)) != len(values):
        raise ValueError(f"{record_name}.{field_name} must not contain duplicates")


class ScientificAttemptScope(StrEnum):
    FORMAL = "formal"
    PROBE = "probe"
    FAULT = "fault"


class ScientificAttemptAuthorityStatus(StrEnum):
    ACTIVE = "active"
    EXHAUSTED = "exhausted"
    EXPIRED = "expired"
    REVOKED = "revoked"

    @property
    def is_terminal(self) -> bool:
        return self is not self.ACTIVE


class ScientificAttemptStatus(StrEnum):
    ACTIVE = "active"
    CLOSING = "closing"
    CLOSED = "closed"
    BLOCKED = "blocked"

    @property
    def is_terminal(self) -> bool:
        return self in {self.CLOSED, self.BLOCKED}


class ScientificAttemptLifecyclePhase(StrEnum):
    """Derived lifecycle phase; never persisted as attempt-row truth."""

    OPEN = "open"
    CLOSURE_REQUESTED = "closure_requested"
    CLOSED = "closed"
    BLOCKED = "blocked"

    @property
    def accepts_scientific_mutation(self) -> bool:
        return self is self.OPEN


class ScientificSelectionState(StrEnum):
    DRAFT = "draft"
    SEALED = "sealed"
    INVALIDATED = "invalidated"

    @property
    def is_terminal(self) -> bool:
        return self in {self.SEALED, self.INVALIDATED}


class ScientificOperationDispositionKind(StrEnum):
    ADOPTED = "adopted"
    SUPERSEDED = "superseded"
    FAILED = "failed"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class ScientificAttemptAuthorization:
    SCHEMA_VERSION: ClassVar[str] = (
        SCIENTIFIC_ATTEMPT_AUTHORIZATION_SCHEMA_VERSION
    )

    envelope_id: str
    session_id: str
    task_id: str
    campaign_id: str
    workflow_id: str
    root_ref: str
    grantor_kind: str
    grantor_ref: str
    allowed_scopes: tuple[ScientificAttemptScope, ...]
    allowed_effect_classes: tuple[str, ...]
    allowed_providers: tuple[str, ...]
    allowed_hpc_targets: tuple[str, ...]
    max_attempts: int
    max_micu: int
    max_cost_microunits: int
    max_wall_time_seconds: int
    consumed_attempts: int
    reserved_micu: int
    reserved_cost_microunits: int
    reserved_wall_time_seconds: int
    expires_at: str
    policy_digest: str
    idempotency_key: str
    request_digest: str
    status: ScientificAttemptAuthorityStatus
    state_version: int
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        _require_nonempty(
            type(self).__name__,
            envelope_id=self.envelope_id,
            session_id=self.session_id,
            task_id=self.task_id,
            campaign_id=self.campaign_id,
            workflow_id=self.workflow_id,
            root_ref=self.root_ref,
            grantor_kind=self.grantor_kind,
            grantor_ref=self.grantor_ref,
            expires_at=self.expires_at,
            policy_digest=self.policy_digest,
            idempotency_key=self.idempotency_key,
            request_digest=self.request_digest,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
        _require_unique_nonempty_tuple(
            type(self).__name__,
            "allowed_scopes",
            tuple(scope.value for scope in self.allowed_scopes),
        )
        _require_unique_nonempty_tuple(
            type(self).__name__,
            "allowed_effect_classes",
            self.allowed_effect_classes,
        )
        _require_unique_nonempty_tuple(
            type(self).__name__,
            "allowed_providers",
            self.allowed_providers,
            allow_empty=True,
        )
        _require_unique_nonempty_tuple(
            type(self).__name__,
            "allowed_hpc_targets",
            self.allowed_hpc_targets,
            allow_empty=True,
        )
        ceilings = (
            self.max_attempts,
            self.max_micu,
            self.max_cost_microunits,
            self.max_wall_time_seconds,
        )
        consumed = (
            self.consumed_attempts,
            self.reserved_micu,
            self.reserved_cost_microunits,
            self.reserved_wall_time_seconds,
        )
        if any(value < 0 for value in ceilings + consumed):
            raise ValueError("scientific attempt authority resources must be non-negative")
        if self.max_attempts < 1 or self.state_version < 1:
            raise ValueError(
                "scientific attempt authority must have a positive count and version"
            )
        if (
            self.consumed_attempts > self.max_attempts
            or self.reserved_micu > self.max_micu
            or self.reserved_cost_microunits > self.max_cost_microunits
            or self.reserved_wall_time_seconds > self.max_wall_time_seconds
        ):
            raise ValueError(
                "scientific attempt authority consumption exceeds its ceiling"
            )

    def to_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


@dataclass(frozen=True, slots=True)
class ScientificAttemptAdmissionRequest:
    """Agent intent finalized by the Host after the requesting writer retires."""

    SCHEMA_VERSION: ClassVar[str] = (
        SCIENTIFIC_ATTEMPT_ADMISSION_REQUEST_SCHEMA_VERSION
    )

    admission_request_id: str
    envelope_id: str
    session_id: str
    task_id: str
    lane_id: str
    campaign_id: str
    workflow_id: str
    scope: ScientificAttemptScope
    workflow_contract_digest: str
    requested_effect_classes: tuple[str, ...]
    provider: str | None
    hpc_target: str | None
    reserved_micu: int
    reserved_cost_microunits: int
    reserved_wall_time_seconds: int
    actor_ref: str
    idempotency_key: str
    request_digest: str
    created_at: str

    def __post_init__(self) -> None:
        _require_nonempty(
            type(self).__name__,
            admission_request_id=self.admission_request_id,
            envelope_id=self.envelope_id,
            session_id=self.session_id,
            task_id=self.task_id,
            lane_id=self.lane_id,
            campaign_id=self.campaign_id,
            workflow_id=self.workflow_id,
            workflow_contract_digest=self.workflow_contract_digest,
            actor_ref=self.actor_ref,
            idempotency_key=self.idempotency_key,
            request_digest=self.request_digest,
            created_at=self.created_at,
        )
        _require_unique_nonempty_tuple(
            type(self).__name__,
            "requested_effect_classes",
            self.requested_effect_classes,
        )
        if min(
            self.reserved_micu,
            self.reserved_cost_microunits,
            self.reserved_wall_time_seconds,
        ) < 0:
            raise ValueError(
                "scientific attempt admission reservations must be non-negative"
            )

    def to_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


@dataclass(frozen=True, slots=True)
class ScientificAttempt:
    SCHEMA_VERSION: ClassVar[str] = SCIENTIFIC_ATTEMPT_SCHEMA_VERSION

    attempt_id: str
    admission_request_id: str
    envelope_id: str
    session_id: str
    task_id: str
    lane_id: str
    campaign_id: str
    workflow_id: str
    scope: ScientificAttemptScope
    root_ref: str
    mutation_scope_id: str
    ordinal: int
    request_digest: str
    idempotency_key: str
    workflow_contract_digest: str
    requested_effect_classes: tuple[str, ...]
    provider: str | None
    hpc_target: str | None
    reserved_micu: int
    reserved_cost_microunits: int
    reserved_wall_time_seconds: int
    status: ScientificAttemptStatus
    state_version: int
    created_by: str
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        _require_nonempty(
            type(self).__name__,
            attempt_id=self.attempt_id,
            admission_request_id=self.admission_request_id,
            envelope_id=self.envelope_id,
            session_id=self.session_id,
            task_id=self.task_id,
            lane_id=self.lane_id,
            campaign_id=self.campaign_id,
            workflow_id=self.workflow_id,
            root_ref=self.root_ref,
            mutation_scope_id=self.mutation_scope_id,
            request_digest=self.request_digest,
            idempotency_key=self.idempotency_key,
            workflow_contract_digest=self.workflow_contract_digest,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
        _require_unique_nonempty_tuple(
            type(self).__name__,
            "requested_effect_classes",
            self.requested_effect_classes,
        )
        if self.ordinal < 1 or self.state_version < 1:
            raise ValueError("scientific attempt ordinal and version must be positive")
        if min(
            self.reserved_micu,
            self.reserved_cost_microunits,
            self.reserved_wall_time_seconds,
        ) < 0:
            raise ValueError("scientific attempt reservations must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


@dataclass(frozen=True, slots=True)
class ScientificChainSelection:
    SCHEMA_VERSION: ClassVar[str] = SCIENTIFIC_CHAIN_SELECTION_SCHEMA_VERSION

    selection_id: str
    attempt_id: str
    revision: int
    parent_selection_id: str | None
    state: ScientificSelectionState
    operation_universe_digest: str
    operation_count: int
    disposition_digest: str
    adoption_digest: str
    workflow_contract_digest: str
    actor_ref: str
    idempotency_key: str
    request_digest: str
    created_at: str
    sealed_at: str | None = None

    def __post_init__(self) -> None:
        _require_nonempty(
            type(self).__name__,
            selection_id=self.selection_id,
            attempt_id=self.attempt_id,
            operation_universe_digest=self.operation_universe_digest,
            disposition_digest=self.disposition_digest,
            adoption_digest=self.adoption_digest,
            workflow_contract_digest=self.workflow_contract_digest,
            actor_ref=self.actor_ref,
            idempotency_key=self.idempotency_key,
            request_digest=self.request_digest,
            created_at=self.created_at,
        )
        if self.revision < 1 or self.operation_count < 0:
            raise ValueError(
                "scientific selection revision must be positive and count non-negative"
            )
        if self.revision == 1 and self.parent_selection_id is not None:
            raise ValueError("first scientific selection revision cannot have a parent")
        if self.revision > 1 and not self.parent_selection_id:
            raise ValueError("later scientific selection revision requires a parent")
        if self.state is ScientificSelectionState.SEALED and not self.sealed_at:
            raise ValueError("sealed scientific selection requires sealed_at")

    def to_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


@dataclass(frozen=True, slots=True)
class ScientificOperationDisposition:
    SCHEMA_VERSION: ClassVar[str] = (
        SCIENTIFIC_OPERATION_DISPOSITION_SCHEMA_VERSION
    )

    disposition_id: str
    selection_id: str
    attempt_id: str
    operation_id: str
    kind: ScientificOperationDispositionKind
    workflow_role: str | None
    reason_code: str
    replacement_operation_id: str | None
    actor_ref: str
    idempotency_key: str
    request_digest: str
    created_at: str

    def __post_init__(self) -> None:
        _require_nonempty(
            type(self).__name__,
            disposition_id=self.disposition_id,
            selection_id=self.selection_id,
            attempt_id=self.attempt_id,
            operation_id=self.operation_id,
            reason_code=self.reason_code,
            actor_ref=self.actor_ref,
            idempotency_key=self.idempotency_key,
            request_digest=self.request_digest,
            created_at=self.created_at,
        )
        if self.kind is ScientificOperationDispositionKind.ADOPTED:
            if not self.workflow_role:
                raise ValueError("adopted operation requires a workflow role")
            if self.replacement_operation_id is not None:
                raise ValueError("adopted operation cannot name a replacement")
        elif self.kind is ScientificOperationDispositionKind.SUPERSEDED:
            if not self.replacement_operation_id:
                raise ValueError("superseded operation requires a replacement")
            if self.replacement_operation_id == self.operation_id:
                raise ValueError("operation cannot supersede itself")
        elif self.replacement_operation_id is not None:
            raise ValueError(
                "only a superseded operation may name a replacement operation"
            )

    def to_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


@dataclass(frozen=True, slots=True)
class ScientificEffectAdoption:
    SCHEMA_VERSION: ClassVar[str] = SCIENTIFIC_EFFECT_ADOPTION_SCHEMA_VERSION

    adoption_id: str
    selection_id: str
    attempt_id: str
    workflow_role: str
    operation_id: str
    execution_id: str
    result_handle_id: str
    result_digest: str
    artifact_set_digest: str
    source_sandbox_run_id: str
    effect_certainty: str
    approval_digest: str | None
    actor_ref: str
    idempotency_key: str
    request_digest: str
    created_at: str

    def __post_init__(self) -> None:
        _require_nonempty(
            type(self).__name__,
            adoption_id=self.adoption_id,
            selection_id=self.selection_id,
            attempt_id=self.attempt_id,
            workflow_role=self.workflow_role,
            operation_id=self.operation_id,
            execution_id=self.execution_id,
            result_handle_id=self.result_handle_id,
            result_digest=self.result_digest,
            artifact_set_digest=self.artifact_set_digest,
            source_sandbox_run_id=self.source_sandbox_run_id,
            effect_certainty=self.effect_certainty,
            actor_ref=self.actor_ref,
            idempotency_key=self.idempotency_key,
            request_digest=self.request_digest,
            created_at=self.created_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


@dataclass(frozen=True, slots=True)
class ScientificArtifactMaterialization:
    SCHEMA_VERSION: ClassVar[str] = (
        SCIENTIFIC_ARTIFACT_MATERIALIZATION_SCHEMA_VERSION
    )

    receipt_id: str
    selection_id: str
    attempt_id: str
    adoption_id: str
    source_artifact_id: str
    source_artifact_digest: str
    source_sandbox_run_id: str
    target_sandbox_workspace_id: str
    target_sandbox_run_id: str
    target_path: str
    boundary_materialization_id: str
    actor_ref: str
    idempotency_key: str
    request_digest: str
    created_at: str

    def __post_init__(self) -> None:
        _require_nonempty(
            type(self).__name__,
            receipt_id=self.receipt_id,
            selection_id=self.selection_id,
            attempt_id=self.attempt_id,
            adoption_id=self.adoption_id,
            source_artifact_id=self.source_artifact_id,
            source_artifact_digest=self.source_artifact_digest,
            source_sandbox_run_id=self.source_sandbox_run_id,
            target_sandbox_workspace_id=self.target_sandbox_workspace_id,
            target_sandbox_run_id=self.target_sandbox_run_id,
            target_path=self.target_path,
            boundary_materialization_id=self.boundary_materialization_id,
            actor_ref=self.actor_ref,
            idempotency_key=self.idempotency_key,
            request_digest=self.request_digest,
            created_at=self.created_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


@dataclass(frozen=True, slots=True)
class ScientificAttemptClosureRequest:
    """Agent intent consumed by the Host only after the requesting writer retires."""

    SCHEMA_VERSION: ClassVar[str] = (
        SCIENTIFIC_ATTEMPT_CLOSURE_REQUEST_SCHEMA_VERSION
    )

    closure_request_id: str
    attempt_id: str
    selection_id: str
    actor_ref: str
    idempotency_key: str
    request_digest: str
    created_at: str

    def __post_init__(self) -> None:
        _require_nonempty(
            type(self).__name__,
            closure_request_id=self.closure_request_id,
            attempt_id=self.attempt_id,
            selection_id=self.selection_id,
            actor_ref=self.actor_ref,
            idempotency_key=self.idempotency_key,
            request_digest=self.request_digest,
            created_at=self.created_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


@dataclass(frozen=True, slots=True)
class ScientificAttemptClosureResponse:
    """Immutable binding from one closure intent to its canonical final answer."""

    SCHEMA_VERSION: ClassVar[str] = (
        SCIENTIFIC_ATTEMPT_CLOSURE_RESPONSE_SCHEMA_VERSION
    )

    closure_response_id: str
    closure_request_id: str
    attempt_id: str
    message_id: str
    document_id: str
    recipient: str
    recipient_kind: str
    response_digest: str
    binding_digest: str
    created_at: str

    def __post_init__(self) -> None:
        _require_nonempty(
            type(self).__name__,
            closure_response_id=self.closure_response_id,
            closure_request_id=self.closure_request_id,
            attempt_id=self.attempt_id,
            message_id=self.message_id,
            document_id=self.document_id,
            recipient=self.recipient,
            recipient_kind=self.recipient_kind,
            response_digest=self.response_digest,
            binding_digest=self.binding_digest,
            created_at=self.created_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


@dataclass(frozen=True, slots=True)
class ScientificAttemptClosure:
    SCHEMA_VERSION: ClassVar[str] = SCIENTIFIC_ATTEMPT_CLOSURE_SCHEMA_VERSION

    closure_id: str
    closure_request_id: str
    attempt_id: str
    selection_id: str
    operation_universe_digest: str
    disposition_digest: str
    adoption_digest: str
    materialization_digest: str
    authority_consumption_digest: str
    quiescence_receipt_id: str
    quiescence_receipt_digest: str
    closure_digest: str
    actor_ref: str
    idempotency_key: str
    request_digest: str
    created_at: str

    def __post_init__(self) -> None:
        _require_nonempty(
            type(self).__name__,
            closure_id=self.closure_id,
            closure_request_id=self.closure_request_id,
            attempt_id=self.attempt_id,
            selection_id=self.selection_id,
            operation_universe_digest=self.operation_universe_digest,
            disposition_digest=self.disposition_digest,
            adoption_digest=self.adoption_digest,
            materialization_digest=self.materialization_digest,
            authority_consumption_digest=self.authority_consumption_digest,
            quiescence_receipt_id=self.quiescence_receipt_id,
            quiescence_receipt_digest=self.quiescence_receipt_digest,
            closure_digest=self.closure_digest,
            actor_ref=self.actor_ref,
            idempotency_key=self.idempotency_key,
            request_digest=self.request_digest,
            created_at=self.created_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return _serialize_record(self, schema_version=self.SCHEMA_VERSION)


__all__ = [
    "SCIENTIFIC_ARTIFACT_MATERIALIZATION_SCHEMA_VERSION",
    "SCIENTIFIC_ATTEMPT_ADMISSION_REQUEST_SCHEMA_VERSION",
    "SCIENTIFIC_ATTEMPT_AUTHORIZATION_SCHEMA_VERSION",
    "SCIENTIFIC_ATTEMPT_CLOSURE_REQUEST_SCHEMA_VERSION",
    "SCIENTIFIC_ATTEMPT_CLOSURE_SCHEMA_VERSION",
    "SCIENTIFIC_ATTEMPT_SCHEMA_VERSION",
    "SCIENTIFIC_CHAIN_SELECTION_SCHEMA_VERSION",
    "SCIENTIFIC_EFFECT_ADOPTION_SCHEMA_VERSION",
    "SCIENTIFIC_OPERATION_DISPOSITION_SCHEMA_VERSION",
    "ScientificArtifactMaterialization",
    "ScientificAttempt",
    "ScientificAttemptAdmissionRequest",
    "ScientificAttemptAuthorization",
    "ScientificAttemptAuthorityStatus",
    "ScientificAttemptClosureRequest",
    "ScientificAttemptClosure",
    "ScientificAttemptLifecyclePhase",
    "ScientificAttemptScope",
    "ScientificAttemptStatus",
    "ScientificChainSelection",
    "ScientificEffectAdoption",
    "ScientificOperationDisposition",
    "ScientificOperationDispositionKind",
    "ScientificSelectionState",
]
