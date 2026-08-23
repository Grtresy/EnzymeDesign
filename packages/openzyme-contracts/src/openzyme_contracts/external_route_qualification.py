from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from datetime import datetime
from enum import StrEnum
import math
from typing import Any
from typing import ClassVar
from typing import Mapping
from typing import Protocol

from .diagnostics import sanitize_public_diagnostic_text
from .external_qualification import ExternalQualificationError
from .external_qualification import ExternalQualificationProbeDisposition
from .external_qualification import ExternalQualificationProbeOutcome
from .external_qualification import ExternalQualificationProbeRequest
from .external_qualification import ExternalQualificationSubjectKind
from .identity import canonical_sha256_digest
from .identity import canonical_string_tuple
from .identity import require_digest
from .identity import require_identifier
from .reliability import ExternalEffectCertainty


EXTERNAL_SUBJECT_IDENTITY_OBSERVATION_SCHEMA = "external_subject_identity_observation@1"
EXTERNAL_SUBJECT_IDENTITY_DISCOVERY_REPORT_SCHEMA = (
    "external_subject_identity_discovery_report@1"
)
EXTERNAL_IDENTITY_GAP_SCHEMA = "external_identity_gap@1"
EXTERNAL_IDENTITY_RESOLUTION_CANDIDATE_SCHEMA = (
    "external_identity_resolution_candidate@1"
)
EXTERNAL_IDENTITY_RESOLUTION_DECISION_SCHEMA = "external_identity_resolution_decision@1"
EXTERNAL_REAL_SUBJECT_IDENTITY_SCHEMA = "external_real_subject_identity@1"
EXTERNAL_QUALIFICATION_BRIDGE_BINDING_SCHEMA = "external_qualification_bridge_binding@1"
EXTERNAL_IDENTITY_PREPARATION_ACTION_SCHEMA = "external_identity_preparation_action@2"
EXTERNAL_IDENTITY_PREPARATION_PLAN_SCHEMA = "external_identity_preparation_plan@1"
EXTERNAL_IDENTITY_PREPARATION_OCCURRENCE_AUTHORIZATION_SCHEMA = (
    "external_identity_preparation_occurrence_authorization@2"
)
EXTERNAL_IDENTITY_PREPARATION_AUTHORIZATION_REVOCATION_SCHEMA = (
    "external_identity_preparation_authorization_revocation@1"
)
EXTERNAL_IDENTITY_PREPARATION_RESULT_SCHEMA = "external_identity_preparation_result@1"
EXTERNAL_QUALIFICATION_DRY_PLAN_SCHEMA = "external_qualification_dry_plan@1"
EXTERNAL_QUALIFICATION_OCCURRENCE_AUTHORIZATION_SCHEMA = (
    "external_qualification_occurrence_authorization@1"
)
EXTERNAL_QUALIFICATION_SAFE_RECEIPT_SCHEMA = "external_qualification_safe_receipt@1"


def _timestamp(value: str, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be one bounded ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be one ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include an explicit timezone")
    return parsed


def _safe_text(value: str, *, field_name: str, maximum: int = 2048) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be one non-empty bounded string")
    if len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{field_name} exceeds the public bound")
    if sanitize_public_diagnostic_text(value) != value:
        raise ExternalQualificationError(
            "qualification_public_identity_not_secret_safe",
            f"{field_name} is not secret-safe",
        )
    return value


class ExternalSubjectIdentityStatus(StrEnum):
    RESOLVED = "resolved"
    PARTIAL = "partial"
    MISSING = "missing"
    UNSAFE = "unsafe"
    DRIFTED = "drifted"


@dataclass(frozen=True, slots=True)
class SafeIdentityField:
    field_id: str
    value: str

    def __post_init__(self) -> None:
        require_identifier(self.field_id, field_name="field_id")
        _safe_text(self.value, field_name=f"safe identity field {self.field_id}")

    def to_dict(self) -> dict[str, str]:
        return {"field_id": self.field_id, "value": self.value}


@dataclass(frozen=True, slots=True)
class ExternalSubjectIdentityObservation:
    observation_id: str
    logical_subject_id: str
    subject_kind: ExternalQualificationSubjectKind
    status: ExternalSubjectIdentityStatus
    source_id: str
    source_digest: str
    safe_fields: tuple[SafeIdentityField, ...]
    missing_fields: tuple[str, ...]
    affected_unit_digests: tuple[str, ...]
    observation_digest: str = ""

    SCHEMA_VERSION: ClassVar[str] = EXTERNAL_SUBJECT_IDENTITY_OBSERVATION_SCHEMA

    @classmethod
    def create(cls, **values: Any) -> "ExternalSubjectIdentityObservation":
        item = cls(**values, observation_digest="sha256:" + "0" * 64)
        return replace(
            item,
            observation_digest=canonical_sha256_digest(item.identity_payload),
        )

    def __post_init__(self) -> None:
        require_identifier(self.observation_id, field_name="observation_id")
        require_identifier(self.logical_subject_id, field_name="logical_subject_id")
        require_identifier(self.source_id, field_name="source_id")
        require_digest(self.source_digest, field_name="source_digest")
        fields = tuple(sorted(self.safe_fields, key=lambda item: item.field_id))
        if len({item.field_id for item in fields}) != len(fields):
            raise ValueError("safe identity fields must be unique")
        object.__setattr__(self, "safe_fields", fields)
        object.__setattr__(
            self,
            "missing_fields",
            canonical_string_tuple(self.missing_fields, field_name="missing_fields"),
        )
        units = tuple(sorted(self.affected_unit_digests))
        if not units or len(set(units)) != len(units):
            raise ValueError("affected_unit_digests must be non-empty and unique")
        for digest in units:
            require_digest(digest, field_name="affected_unit_digest")
        object.__setattr__(self, "affected_unit_digests", units)
        if (
            self.status is ExternalSubjectIdentityStatus.RESOLVED
            and self.missing_fields
        ):
            raise ValueError("resolved identity must not have missing fields")
        if self.status is ExternalSubjectIdentityStatus.MISSING and self.safe_fields:
            raise ValueError("missing identity must not claim safe identity fields")
        require_digest(self.observation_digest, field_name="observation_digest")
        if self.observation_digest != "sha256:" + "0" * 64:
            expected = canonical_sha256_digest(self.identity_payload)
            if self.observation_digest != expected:
                raise ExternalQualificationError(
                    "qualification_identity_observation_digest_mismatch",
                    "identity observation digest does not match its payload",
                )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "observation_id": self.observation_id,
            "logical_subject_id": self.logical_subject_id,
            "subject_kind": self.subject_kind.value,
            "status": self.status.value,
            "source_id": self.source_id,
            "source_digest": self.source_digest,
            "safe_fields": [item.to_dict() for item in self.safe_fields],
            "missing_fields": list(self.missing_fields),
            "affected_unit_digests": list(self.affected_unit_digests),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "observation_digest": self.observation_digest}


@dataclass(frozen=True, slots=True)
class ExternalSubjectIdentityDiscoveryReport:
    report_id: str
    readiness_plan_digest: str
    source_digest: str
    observations: tuple[ExternalSubjectIdentityObservation, ...]
    observed_at: str
    credential_material_accessed: bool = False
    external_effect_performed: bool = False
    report_digest: str = ""

    SCHEMA_VERSION: ClassVar[str] = EXTERNAL_SUBJECT_IDENTITY_DISCOVERY_REPORT_SCHEMA

    @classmethod
    def create(cls, **values: Any) -> "ExternalSubjectIdentityDiscoveryReport":
        item = cls(**values, report_digest="sha256:" + "0" * 64)
        return replace(
            item, report_digest=canonical_sha256_digest(item.identity_payload)
        )

    def __post_init__(self) -> None:
        require_identifier(self.report_id, field_name="report_id")
        require_digest(self.readiness_plan_digest, field_name="readiness_plan_digest")
        require_digest(self.source_digest, field_name="source_digest")
        _timestamp(self.observed_at, field_name="observed_at")
        observations = tuple(
            sorted(self.observations, key=lambda item: item.observation_id)
        )
        if not observations or len(
            {item.observation_id for item in observations}
        ) != len(observations):
            raise ValueError("identity observations must be non-empty and unique")
        object.__setattr__(self, "observations", observations)
        if self.credential_material_accessed or self.external_effect_performed:
            raise ExternalQualificationError(
                "qualification_identity_discovery_effect_violation",
                "identity discovery must be credential-free and no-effect",
            )
        require_digest(self.report_digest, field_name="report_digest")
        if self.report_digest != "sha256:" + "0" * 64:
            expected = canonical_sha256_digest(self.identity_payload)
            if self.report_digest != expected:
                raise ExternalQualificationError(
                    "qualification_identity_discovery_digest_mismatch",
                    "identity discovery report digest does not match its payload",
                )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "report_id": self.report_id,
            "readiness_plan_digest": self.readiness_plan_digest,
            "source_digest": self.source_digest,
            "observations": [item.to_dict() for item in self.observations],
            "observed_at": self.observed_at,
            "credential_material_accessed": self.credential_material_accessed,
            "external_effect_performed": self.external_effect_performed,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "report_digest": self.report_digest}


@dataclass(frozen=True, slots=True)
class ExternalIdentityResolutionCandidate:
    candidate_id: str
    title: str
    operator_action: str
    effect_summary: str
    cost_summary: str
    security_summary: str
    prerequisite_ids: tuple[str, ...] = ()
    recommended: bool = False

    SCHEMA_VERSION: ClassVar[str] = EXTERNAL_IDENTITY_RESOLUTION_CANDIDATE_SCHEMA

    def __post_init__(self) -> None:
        require_identifier(self.candidate_id, field_name="candidate_id")
        for field_name in (
            "title",
            "operator_action",
            "effect_summary",
            "cost_summary",
            "security_summary",
        ):
            _safe_text(getattr(self, field_name), field_name=field_name)
        object.__setattr__(
            self,
            "prerequisite_ids",
            canonical_string_tuple(
                self.prerequisite_ids, field_name="prerequisite_ids"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "candidate_id": self.candidate_id,
            "title": self.title,
            "operator_action": self.operator_action,
            "effect_summary": self.effect_summary,
            "cost_summary": self.cost_summary,
            "security_summary": self.security_summary,
            "prerequisite_ids": list(self.prerequisite_ids),
            "recommended": self.recommended,
        }


@dataclass(frozen=True, slots=True)
class ExternalIdentityGap:
    gap_id: str
    logical_subject_id: str
    observation_digest: str
    missing_fields: tuple[str, ...]
    affected_unit_digests: tuple[str, ...]
    candidates: tuple[ExternalIdentityResolutionCandidate, ...]
    error_code: str = "blocked_identity"
    gap_digest: str = ""

    SCHEMA_VERSION: ClassVar[str] = EXTERNAL_IDENTITY_GAP_SCHEMA

    @classmethod
    def create(cls, **values: Any) -> "ExternalIdentityGap":
        item = cls(**values, gap_digest="sha256:" + "0" * 64)
        return replace(item, gap_digest=canonical_sha256_digest(item.identity_payload))

    def __post_init__(self) -> None:
        require_identifier(self.gap_id, field_name="gap_id")
        require_identifier(self.logical_subject_id, field_name="logical_subject_id")
        require_identifier(self.error_code, field_name="error_code")
        require_digest(self.observation_digest, field_name="observation_digest")
        object.__setattr__(
            self,
            "missing_fields",
            canonical_string_tuple(
                self.missing_fields, field_name="missing_fields", allow_empty=False
            ),
        )
        units = tuple(sorted(self.affected_unit_digests))
        if not units or len(set(units)) != len(units):
            raise ValueError("gap affected units must be non-empty and unique")
        for digest in units:
            require_digest(digest, field_name="affected_unit_digest")
        object.__setattr__(self, "affected_unit_digests", units)
        candidates = tuple(sorted(self.candidates, key=lambda item: item.candidate_id))
        if len(candidates) < 2 or len(
            {item.candidate_id for item in candidates}
        ) != len(candidates):
            raise ValueError("identity gap requires at least two unique candidates")
        if sum(item.recommended for item in candidates) != 1:
            raise ValueError("identity gap requires exactly one recommended candidate")
        object.__setattr__(self, "candidates", candidates)
        require_digest(self.gap_digest, field_name="gap_digest")
        if self.gap_digest != "sha256:" + "0" * 64:
            expected = canonical_sha256_digest(self.identity_payload)
            if self.gap_digest != expected:
                raise ExternalQualificationError(
                    "qualification_identity_gap_digest_mismatch",
                    "identity gap digest does not match its payload",
                )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "gap_id": self.gap_id,
            "logical_subject_id": self.logical_subject_id,
            "observation_digest": self.observation_digest,
            "missing_fields": list(self.missing_fields),
            "affected_unit_digests": list(self.affected_unit_digests),
            "candidates": [item.to_dict() for item in self.candidates],
            "error_code": self.error_code,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "gap_digest": self.gap_digest}


@dataclass(frozen=True, slots=True)
class ExternalIdentityResolutionDecision:
    decision_id: str
    gap_digest: str
    candidate_id: str
    operator_id: str
    decided_at: str
    decision_digest: str = ""

    SCHEMA_VERSION: ClassVar[str] = EXTERNAL_IDENTITY_RESOLUTION_DECISION_SCHEMA

    @classmethod
    def create(cls, **values: Any) -> "ExternalIdentityResolutionDecision":
        item = cls(**values, decision_digest="sha256:" + "0" * 64)
        return replace(
            item, decision_digest=canonical_sha256_digest(item.identity_payload)
        )

    def __post_init__(self) -> None:
        require_identifier(self.decision_id, field_name="decision_id")
        require_identifier(self.candidate_id, field_name="candidate_id")
        require_identifier(self.operator_id, field_name="operator_id")
        require_digest(self.gap_digest, field_name="gap_digest")
        _timestamp(self.decided_at, field_name="decided_at")
        require_digest(self.decision_digest, field_name="decision_digest")
        if self.decision_digest != "sha256:" + "0" * 64:
            expected = canonical_sha256_digest(self.identity_payload)
            if self.decision_digest != expected:
                raise ExternalQualificationError(
                    "qualification_identity_decision_digest_mismatch",
                    "identity decision digest does not match its payload",
                )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "decision_id": self.decision_id,
            "gap_digest": self.gap_digest,
            "candidate_id": self.candidate_id,
            "operator_id": self.operator_id,
            "decided_at": self.decided_at,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "decision_digest": self.decision_digest}


def verify_external_identity_decision(
    gap: ExternalIdentityGap,
    decision: ExternalIdentityResolutionDecision,
) -> ExternalIdentityResolutionCandidate:
    if decision.gap_digest != gap.gap_digest:
        raise ExternalQualificationError(
            "qualification_identity_decision_stale",
            "identity decision does not bind the current gap digest",
        )
    matches = tuple(
        item for item in gap.candidates if item.candidate_id == decision.candidate_id
    )
    if len(matches) != 1:
        raise ExternalQualificationError(
            "qualification_identity_candidate_unknown",
            "identity decision does not select one declared candidate",
        )
    return matches[0]


@dataclass(frozen=True, slots=True)
class ExternalRealSubjectIdentity:
    identity_id: str
    logical_subject_id: str
    subject_kind: ExternalQualificationSubjectKind
    endpoint_or_runtime_id: str
    account_or_deployment_digest: str
    api_or_route_variant: str
    environment_or_inventory_digest: str
    policy_digest: str
    source_observation_digest: str
    subject_digest: str = ""

    SCHEMA_VERSION: ClassVar[str] = EXTERNAL_REAL_SUBJECT_IDENTITY_SCHEMA

    @classmethod
    def create(cls, **values: Any) -> "ExternalRealSubjectIdentity":
        item = cls(**values, subject_digest="sha256:" + "0" * 64)
        return replace(
            item, subject_digest=canonical_sha256_digest(item.identity_payload)
        )

    def __post_init__(self) -> None:
        for field_name in (
            "identity_id",
            "logical_subject_id",
            "endpoint_or_runtime_id",
            "api_or_route_variant",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "account_or_deployment_digest",
            "environment_or_inventory_digest",
            "policy_digest",
            "source_observation_digest",
            "subject_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if self.subject_digest != "sha256:" + "0" * 64:
            expected = canonical_sha256_digest(self.identity_payload)
            if self.subject_digest != expected:
                raise ExternalQualificationError(
                    "qualification_real_subject_digest_mismatch",
                    "real subject digest does not match its payload",
                )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "identity_id": self.identity_id,
            "logical_subject_id": self.logical_subject_id,
            "subject_kind": self.subject_kind.value,
            "endpoint_or_runtime_id": self.endpoint_or_runtime_id,
            "account_or_deployment_digest": self.account_or_deployment_digest,
            "api_or_route_variant": self.api_or_route_variant,
            "environment_or_inventory_digest": self.environment_or_inventory_digest,
            "policy_digest": self.policy_digest,
            "source_observation_digest": self.source_observation_digest,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "subject_digest": self.subject_digest}


@dataclass(frozen=True, slots=True)
class ExternalQualificationBridgeBinding:
    component_id: str
    operation: str
    route_id: str
    plan_digest: str
    unit_digest: str
    subject_digest: str
    input_digest: str
    expected_result_schema_digest: str
    authorization_digest: str
    credential_locator_id: str | None = None
    binding_digest: str = ""

    SCHEMA_VERSION: ClassVar[str] = EXTERNAL_QUALIFICATION_BRIDGE_BINDING_SCHEMA

    @classmethod
    def create(cls, **values: Any) -> "ExternalQualificationBridgeBinding":
        item = cls(**values, binding_digest="sha256:" + "0" * 64)
        return replace(
            item, binding_digest=canonical_sha256_digest(item.identity_payload)
        )

    def __post_init__(self) -> None:
        for field_name in ("component_id", "operation", "route_id"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "plan_digest",
            "unit_digest",
            "subject_digest",
            "input_digest",
            "expected_result_schema_digest",
            "authorization_digest",
            "binding_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if self.credential_locator_id is not None:
            require_identifier(
                self.credential_locator_id,
                field_name="credential_locator_id",
            )
        if self.binding_digest != "sha256:" + "0" * 64:
            expected = canonical_sha256_digest(self.identity_payload)
            if self.binding_digest != expected:
                raise ExternalQualificationError(
                    "qualification_bridge_binding_digest_mismatch",
                    "qualification bridge binding digest does not match its payload",
                )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "component_id": self.component_id,
            "operation": self.operation,
            "route_id": self.route_id,
            "plan_digest": self.plan_digest,
            "unit_digest": self.unit_digest,
            "subject_digest": self.subject_digest,
            "input_digest": self.input_digest,
            "expected_result_schema_digest": self.expected_result_schema_digest,
            "authorization_digest": self.authorization_digest,
            "credential_locator_id": self.credential_locator_id,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "binding_digest": self.binding_digest}


def verify_external_qualification_probe_request_binding(
    binding: ExternalQualificationBridgeBinding,
    request: ExternalQualificationProbeRequest,
) -> None:
    observed = (
        request.plan_digest,
        request.unit_digest,
        request.operation,
        request.input_digest,
        request.expected_result_schema_digest,
        request.credential_locator_id,
    )
    expected = (
        binding.plan_digest,
        binding.unit_digest,
        binding.operation,
        binding.input_digest,
        binding.expected_result_schema_digest,
        binding.credential_locator_id,
    )
    if observed != expected:
        raise ExternalQualificationError(
            "qualification_bridge_request_binding_mismatch",
            "qualification probe request differs from the exact bridge binding",
        )


@dataclass(frozen=True, slots=True)
class ExternalQualificationOperationObservation:
    attempt_id: str
    request_digest: str
    operation: str
    effect_certainty: str
    terminal: bool
    succeeded: bool
    output_digest: str | None
    receipt_digest: str | None
    error_code: str | None
    external_effect_performed: bool
    credential_material_accessed: bool
    fallback_performed: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.attempt_id, field_name="attempt_id")
        require_identifier(self.operation, field_name="operation")
        require_digest(self.request_digest, field_name="request_digest")
        if self.effect_certainty not in {
            "no_effect",
            "terminal_known",
            "dispatch_in_doubt",
        }:
            raise ValueError("operation observation effect certainty is unsupported")
        for field_name in ("output_digest", "receipt_digest"):
            value = getattr(self, field_name)
            if value is not None:
                require_digest(value, field_name=field_name)
        if self.error_code is not None:
            require_identifier(self.error_code, field_name="error_code")
        if self.succeeded and (
            not self.terminal
            or self.output_digest is None
            or self.receipt_digest is None
            or self.error_code is not None
        ):
            raise ValueError(
                "successful operation observation requires terminal evidence"
            )
        if not self.terminal and self.effect_certainty != "dispatch_in_doubt":
            raise ValueError("non-terminal observation must remain dispatch_in_doubt")
        if self.fallback_performed:
            raise ExternalQualificationError(
                "qualification_probe_fallback_forbidden",
                "owner qualification operation cannot report fallback",
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "request_digest": self.request_digest,
            "operation": self.operation,
            "effect_certainty": self.effect_certainty,
            "terminal": self.terminal,
            "succeeded": self.succeeded,
            "output_digest": self.output_digest,
            "receipt_digest": self.receipt_digest,
            "error_code": self.error_code,
            "external_effect_performed": self.external_effect_performed,
            "credential_material_accessed": self.credential_material_accessed,
            "fallback_performed": self.fallback_performed,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, object]
    ) -> "ExternalQualificationOperationObservation":
        def required_string(field_name: str) -> str:
            value = payload.get(field_name)
            if not isinstance(value, str):
                raise ValueError(f"{field_name} must be a string")
            return value

        def optional_string(field_name: str) -> str | None:
            value = payload.get(field_name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{field_name} must be a string or null")
            return value

        def required_bool(field_name: str) -> bool:
            value = payload.get(field_name)
            if not isinstance(value, bool):
                raise ValueError(f"{field_name} must be a boolean")
            return value

        return cls(
            attempt_id=required_string("attempt_id"),
            request_digest=required_string("request_digest"),
            operation=required_string("operation"),
            effect_certainty=required_string("effect_certainty"),
            terminal=required_bool("terminal"),
            succeeded=required_bool("succeeded"),
            output_digest=optional_string("output_digest"),
            receipt_digest=optional_string("receipt_digest"),
            error_code=optional_string("error_code"),
            external_effect_performed=required_bool("external_effect_performed"),
            credential_material_accessed=required_bool("credential_material_accessed"),
            fallback_performed=required_bool("fallback_performed"),
        )


class ExternalQualificationOperationPort(Protocol):
    def dispatch(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationOperationObservation: ...

    def reconcile(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationOperationObservation: ...


class ExternalBoundQualificationOperationPort(
    ExternalQualificationOperationPort,
    Protocol,
):
    component_id: str
    route_id: str
    subject_digest: str


class ExternalScientificQualificationOperationPort(
    ExternalBoundQualificationOperationPort,
    Protocol,
):
    driver_component_id: str
    workload_input_digest: str
    result_schema_digest: str
    formal_compute_only: bool


@dataclass(slots=True)
class BoundExternalQualificationOperationBridge:
    binding: ExternalQualificationBridgeBinding
    operation_port: ExternalQualificationOperationPort
    allowed_operations: tuple[str, ...]
    _dispatched_attempts: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "allowed_operations",
            canonical_string_tuple(
                self.allowed_operations,
                field_name="allowed_operations",
                allow_empty=False,
            ),
        )
        if self.binding.operation not in self.allowed_operations:
            raise ExternalQualificationError(
                "qualification_bridge_operation_unsupported",
                "exact binding operation is not owned by this qualification bridge",
            )

    def dispatch(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        verify_external_qualification_probe_request_binding(self.binding, request)
        if request.attempt_id in self._dispatched_attempts:
            raise ExternalQualificationError(
                "qualification_probe_redispatch_forbidden",
                "owner qualification attempt cannot be dispatched twice",
            )
        self._dispatched_attempts.add(request.attempt_id)
        return self._convert(request, self.operation_port.dispatch(request))

    def reconcile(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        verify_external_qualification_probe_request_binding(self.binding, request)
        if request.attempt_id not in self._dispatched_attempts:
            raise ExternalQualificationError(
                "qualification_probe_reconcile_without_dispatch",
                "owner qualification reconcile requires the same prior attempt",
            )
        return self._convert(request, self.operation_port.reconcile(request))

    @staticmethod
    def _convert(
        request: ExternalQualificationProbeRequest,
        observation: ExternalQualificationOperationObservation,
    ) -> ExternalQualificationProbeOutcome:
        if (
            observation.attempt_id != request.attempt_id
            or observation.request_digest != request.request_digest
            or observation.operation != request.operation
        ):
            raise ExternalQualificationError(
                "qualification_bridge_observation_identity_mismatch",
                "owner observation differs from the exact probe attempt",
            )
        if observation.succeeded:
            disposition = ExternalQualificationProbeDisposition.SUCCEEDED
        elif observation.terminal:
            disposition = ExternalQualificationProbeDisposition.FAILED
        else:
            disposition = ExternalQualificationProbeDisposition.RECONCILE_REQUIRED
        effect_certainty = {
            "no_effect": ExternalEffectCertainty.NO_EFFECT,
            "terminal_known": ExternalEffectCertainty.TERMINAL_KNOWN,
            "dispatch_in_doubt": ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        }[observation.effect_certainty]
        return ExternalQualificationProbeOutcome(
            attempt_id=request.attempt_id,
            request_digest=request.request_digest,
            disposition=disposition,
            effect_certainty=effect_certainty,
            observed_operation=request.operation if observation.terminal else None,
            output_digest=observation.output_digest,
            observed_result_schema_digest=(
                request.expected_result_schema_digest if observation.succeeded else None
            ),
            backend_receipt_digest=observation.receipt_digest,
            error_code=observation.error_code,
            external_effect_performed=observation.external_effect_performed,
            credential_material_accessed=observation.credential_material_accessed,
            fallback_performed=False,
        )


@dataclass(frozen=True, slots=True)
class ExternalQualificationBudgetPolicy:
    budget_id: str
    scope_id: str
    resource_kind: str
    warning_limit: float
    hard_limit: float
    unit: str

    def __post_init__(self) -> None:
        for field_name in ("budget_id", "scope_id", "resource_kind", "unit"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if not math.isfinite(self.warning_limit) or self.warning_limit < 0:
            raise ValueError("warning_limit must be finite and non-negative")
        if not math.isfinite(self.hard_limit) or self.hard_limit <= 0:
            raise ValueError("hard_limit must be finite and positive")
        if self.warning_limit >= self.hard_limit:
            raise ValueError("warning_limit must be lower than hard_limit")

    def to_dict(self) -> dict[str, object]:
        return {
            "budget_id": self.budget_id,
            "scope_id": self.scope_id,
            "resource_kind": self.resource_kind,
            "warning_limit": self.warning_limit,
            "hard_limit": self.hard_limit,
            "unit": self.unit,
        }


@dataclass(frozen=True, slots=True)
class ExternalQualificationEffectPolicy:
    effect_id: str
    scope_id: str
    mutating: bool
    cleanup_action_id: str | None
    cleanup_deadline_seconds: int | None

    def __post_init__(self) -> None:
        require_identifier(self.effect_id, field_name="effect_id")
        require_identifier(self.scope_id, field_name="scope_id")
        if self.mutating:
            if self.cleanup_action_id is None or self.cleanup_deadline_seconds is None:
                raise ValueError("mutating effect requires cleanup action and deadline")
            require_identifier(self.cleanup_action_id, field_name="cleanup_action_id")
            if self.cleanup_deadline_seconds <= 0:
                raise ValueError("cleanup deadline must be positive")
        elif (
            self.cleanup_action_id is not None
            or self.cleanup_deadline_seconds is not None
        ):
            raise ValueError("read-only effect must not invent cleanup")

    def to_dict(self) -> dict[str, object]:
        return {
            "effect_id": self.effect_id,
            "scope_id": self.scope_id,
            "mutating": self.mutating,
            "cleanup_action_id": self.cleanup_action_id,
            "cleanup_deadline_seconds": self.cleanup_deadline_seconds,
        }


@dataclass(frozen=True, slots=True)
class ExternalQualificationFaultPolicy:
    fault_id: str
    injection_point: str
    same_attempt_reconcile: bool
    retry_allowed: bool = False
    fallback_allowed: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.fault_id, field_name="fault_id")
        require_identifier(self.injection_point, field_name="injection_point")
        if self.retry_allowed or self.fallback_allowed:
            raise ExternalQualificationError(
                "qualification_fault_policy_fallback_forbidden",
                "qualification fault policy cannot enable retry or fallback",
            )
        if "response-loss" in self.fault_id and not self.same_attempt_reconcile:
            raise ValueError("response-loss fault requires same-attempt reconcile")

    def to_dict(self) -> dict[str, object]:
        return {
            "fault_id": self.fault_id,
            "injection_point": self.injection_point,
            "same_attempt_reconcile": self.same_attempt_reconcile,
            "retry_allowed": self.retry_allowed,
            "fallback_allowed": self.fallback_allowed,
        }


@dataclass(frozen=True, slots=True)
class ExternalQualificationTtlPolicy:
    policy_id: str
    scope_id: str
    ttl_seconds: int
    identity_drift_revokes_immediately: bool = True
    operator_revocation_supported: bool = True

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, field_name="policy_id")
        require_identifier(self.scope_id, field_name="scope_id")
        if self.ttl_seconds <= 0:
            raise ValueError("qualification TTL must be positive")
        if (
            not self.identity_drift_revokes_immediately
            or not self.operator_revocation_supported
        ):
            raise ExternalQualificationError(
                "qualification_ttl_revocation_policy_unsafe",
                "qualification TTL must fail closed on drift and operator revocation",
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "scope_id": self.scope_id,
            "ttl_seconds": self.ttl_seconds,
            "identity_drift_revokes_immediately": self.identity_drift_revokes_immediately,
            "operator_revocation_supported": self.operator_revocation_supported,
        }


@dataclass(frozen=True, slots=True)
class ExternalQualificationUnitSubjectBinding:
    unit_digest: str
    profile_id: str
    subject_digest: str | None
    credential_locator_id: str | None = None
    gap_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_digest(self.unit_digest, field_name="unit_digest")
        require_identifier(self.profile_id, field_name="profile_id")
        if self.subject_digest is not None:
            require_digest(self.subject_digest, field_name="subject_digest")
        if self.credential_locator_id is not None:
            require_identifier(
                self.credential_locator_id,
                field_name="credential_locator_id",
            )
        object.__setattr__(
            self,
            "gap_ids",
            canonical_string_tuple(self.gap_ids, field_name="gap_ids"),
        )
        if (self.subject_digest is None) == (not self.gap_ids):
            raise ValueError(
                "unit binding requires either one subject or explicit gaps"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "unit_digest": self.unit_digest,
            "profile_id": self.profile_id,
            "subject_digest": self.subject_digest,
            "credential_locator_id": self.credential_locator_id,
            "gap_ids": list(self.gap_ids),
        }


@dataclass(frozen=True, slots=True)
class ExternalQualificationStoragePolicy:
    ledger_id: str
    private_evidence_root_id: str
    public_export_secret_safe: bool
    credential_material_persisted: bool

    def __post_init__(self) -> None:
        require_identifier(self.ledger_id, field_name="ledger_id")
        require_identifier(
            self.private_evidence_root_id, field_name="private_evidence_root_id"
        )
        if not self.public_export_secret_safe or self.credential_material_persisted:
            raise ExternalQualificationError(
                "qualification_storage_policy_unsafe",
                "qualification storage must be secret-safe and credential-free",
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "ledger_id": self.ledger_id,
            "private_evidence_root_id": self.private_evidence_root_id,
            "public_export_secret_safe": self.public_export_secret_safe,
            "credential_material_persisted": self.credential_material_persisted,
        }


@dataclass(frozen=True, slots=True)
class ExternalIdentityPreparationAction:
    action_id: str
    owner_component_id: str
    logical_subject_id: str
    gap_digests: tuple[str, ...]
    decision_digests: tuple[str, ...]
    effect_id: str
    input_schema_id: str
    safe_input_fields: tuple[SafeIdentityField, ...]
    credential_locator_id: str | None
    mutating: bool
    requires_credential_material: bool
    expected_identity_fields: tuple[str, ...]
    cleanup_action_id: str | None
    cleanup_deadline_seconds: int | None
    input_binding_digest: str = ""

    SCHEMA_VERSION: ClassVar[str] = EXTERNAL_IDENTITY_PREPARATION_ACTION_SCHEMA

    @classmethod
    def create(cls, **values: Any) -> "ExternalIdentityPreparationAction":
        item = cls(**values, input_binding_digest="sha256:" + "0" * 64)
        return replace(
            item,
            input_binding_digest=canonical_sha256_digest(item.input_binding_payload),
        )

    def __post_init__(self) -> None:
        for field_name in (
            "action_id",
            "owner_component_id",
            "logical_subject_id",
            "effect_id",
            "input_schema_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in ("gap_digests", "decision_digests"):
            values = tuple(sorted(getattr(self, field_name)))
            if not values or len(set(values)) != len(values):
                raise ValueError(f"{field_name} must be non-empty and unique")
            for digest in values:
                require_digest(digest, field_name=field_name.removesuffix("s"))
            object.__setattr__(self, field_name, values)
        safe_fields = tuple(
            sorted(self.safe_input_fields, key=lambda item: item.field_id)
        )
        if not safe_fields or len({item.field_id for item in safe_fields}) != len(
            safe_fields
        ):
            raise ValueError("safe_input_fields must be non-empty and unique")
        object.__setattr__(self, "safe_input_fields", safe_fields)
        if self.credential_locator_id is not None:
            require_identifier(
                self.credential_locator_id,
                field_name="credential_locator_id",
            )
        if self.requires_credential_material != (
            self.credential_locator_id is not None
        ):
            raise ExternalQualificationError(
                "qualification_preparation_credential_binding_mismatch",
                "preparation credential requirement must bind one exact locator",
            )
        object.__setattr__(
            self,
            "expected_identity_fields",
            canonical_string_tuple(
                self.expected_identity_fields,
                field_name="expected_identity_fields",
                allow_empty=False,
            ),
        )
        if self.mutating:
            if self.cleanup_action_id is None or self.cleanup_deadline_seconds is None:
                raise ValueError("mutating preparation action requires cleanup")
            require_identifier(self.cleanup_action_id, field_name="cleanup_action_id")
            if self.cleanup_deadline_seconds <= 0:
                raise ValueError("cleanup deadline must be positive")
        elif (
            self.cleanup_action_id is not None
            or self.cleanup_deadline_seconds is not None
        ):
            raise ValueError("read-only preparation action must not invent cleanup")
        require_digest(self.input_binding_digest, field_name="input_binding_digest")
        if self.input_binding_digest != "sha256:" + "0" * 64:
            expected = canonical_sha256_digest(self.input_binding_payload)
            if self.input_binding_digest != expected:
                raise ExternalQualificationError(
                    "qualification_preparation_input_binding_digest_mismatch",
                    "preparation input binding digest does not match its payload",
                )

    @property
    def input_binding_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "action_id": self.action_id,
            "owner_component_id": self.owner_component_id,
            "logical_subject_id": self.logical_subject_id,
            "effect_id": self.effect_id,
            "input_schema_id": self.input_schema_id,
            "safe_input_fields": [item.to_dict() for item in self.safe_input_fields],
            "credential_locator_id": self.credential_locator_id,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "action_id": self.action_id,
            "owner_component_id": self.owner_component_id,
            "logical_subject_id": self.logical_subject_id,
            "gap_digests": list(self.gap_digests),
            "decision_digests": list(self.decision_digests),
            "effect_id": self.effect_id,
            "input_schema_id": self.input_schema_id,
            "safe_input_fields": [item.to_dict() for item in self.safe_input_fields],
            "credential_locator_id": self.credential_locator_id,
            "input_binding_digest": self.input_binding_digest,
            "mutating": self.mutating,
            "requires_credential_material": self.requires_credential_material,
            "expected_identity_fields": list(self.expected_identity_fields),
            "cleanup_action_id": self.cleanup_action_id,
            "cleanup_deadline_seconds": self.cleanup_deadline_seconds,
        }


@dataclass(frozen=True, slots=True)
class ExternalIdentityPreparationPlan:
    plan_id: str
    batch_id: str
    source_digest: str
    discovery_report_digest: str
    decisions: tuple[ExternalIdentityResolutionDecision, ...]
    actions: tuple[ExternalIdentityPreparationAction, ...]
    budgets: tuple[ExternalQualificationBudgetPolicy, ...]
    credential_locator_ids: tuple[str, ...]
    operator_constraints: tuple[str, ...]
    storage_policy: ExternalQualificationStoragePolicy
    max_retries: int
    created_at: str
    live_effect_authorized: bool = False
    preparation_plan_digest: str = ""

    SCHEMA_VERSION: ClassVar[str] = EXTERNAL_IDENTITY_PREPARATION_PLAN_SCHEMA

    @classmethod
    def create(cls, **values: Any) -> "ExternalIdentityPreparationPlan":
        item = cls(**values, preparation_plan_digest="sha256:" + "0" * 64)
        return replace(
            item,
            preparation_plan_digest=canonical_sha256_digest(item.identity_payload),
        )

    def __post_init__(self) -> None:
        require_identifier(self.plan_id, field_name="plan_id")
        require_identifier(self.batch_id, field_name="batch_id")
        for field_name in (
            "source_digest",
            "discovery_report_digest",
            "preparation_plan_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        _timestamp(self.created_at, field_name="created_at")
        if self.max_retries != 0:
            raise ExternalQualificationError(
                "qualification_retry_policy_forbidden",
                "identity preparation plan must set max_retries to zero",
            )
        if self.live_effect_authorized:
            raise ExternalQualificationError(
                "qualification_preparation_plan_cannot_authorize_effect",
                "identity preparation plan cannot authorize its own effects",
            )
        decisions = tuple(sorted(self.decisions, key=lambda item: item.gap_digest))
        if not decisions or len({item.gap_digest for item in decisions}) != len(
            decisions
        ):
            raise ValueError("preparation decisions must cover unique non-empty gaps")
        object.__setattr__(self, "decisions", decisions)
        actions = tuple(sorted(self.actions, key=lambda item: item.action_id))
        if not actions or len({item.action_id for item in actions}) != len(actions):
            raise ValueError("preparation actions must be non-empty and unique")
        object.__setattr__(self, "actions", actions)
        decision_digests = {item.decision_digest for item in decisions}
        referenced_decisions = {
            digest for action in actions for digest in action.decision_digests
        }
        if referenced_decisions != decision_digests:
            raise ExternalQualificationError(
                "qualification_preparation_decision_coverage_mismatch",
                "preparation actions must cover every exact decision once or more",
            )
        decision_gaps = {item.gap_digest for item in decisions}
        referenced_gaps = {
            digest for action in actions for digest in action.gap_digests
        }
        if referenced_gaps != decision_gaps:
            raise ExternalQualificationError(
                "qualification_preparation_gap_coverage_mismatch",
                "preparation actions must cover every selected identity gap",
            )
        budgets = tuple(sorted(self.budgets, key=lambda item: item.budget_id))
        if not budgets or len({item.budget_id for item in budgets}) != len(budgets):
            raise ValueError("preparation budgets must be non-empty and unique")
        object.__setattr__(self, "budgets", budgets)
        object.__setattr__(
            self,
            "credential_locator_ids",
            canonical_string_tuple(
                self.credential_locator_ids,
                field_name="credential_locator_ids",
            ),
        )
        action_locators = tuple(
            sorted(
                {
                    item.credential_locator_id
                    for item in actions
                    if item.credential_locator_id is not None
                }
            )
        )
        if self.credential_locator_ids != action_locators:
            raise ExternalQualificationError(
                "qualification_preparation_credential_locator_coverage_mismatch",
                "preparation plan locators must exactly match action bindings",
            )
        object.__setattr__(
            self,
            "operator_constraints",
            canonical_string_tuple(
                self.operator_constraints,
                field_name="operator_constraints",
                allow_empty=False,
            ),
        )
        require_digest(
            self.preparation_plan_digest,
            field_name="preparation_plan_digest",
        )
        if self.preparation_plan_digest != "sha256:" + "0" * 64:
            expected = canonical_sha256_digest(self.identity_payload)
            if self.preparation_plan_digest != expected:
                raise ExternalQualificationError(
                    "qualification_preparation_plan_digest_mismatch",
                    "identity preparation plan digest does not match its payload",
                )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "batch_id": self.batch_id,
            "source_digest": self.source_digest,
            "discovery_report_digest": self.discovery_report_digest,
            "decisions": [item.to_dict() for item in self.decisions],
            "actions": [item.to_dict() for item in self.actions],
            "budgets": [item.to_dict() for item in self.budgets],
            "credential_locator_ids": list(self.credential_locator_ids),
            "operator_constraints": list(self.operator_constraints),
            "storage_policy": self.storage_policy.to_dict(),
            "max_retries": self.max_retries,
            "created_at": self.created_at,
            "live_effect_authorized": self.live_effect_authorized,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload,
            "authorizable": True,
            "preparation_plan_digest": self.preparation_plan_digest,
        }


def verify_external_identity_preparation_plan(
    plan: ExternalIdentityPreparationPlan,
    *,
    expected_source_digest: str,
    expected_discovery_report_digest: str,
    expected_gap_digests: tuple[str, ...],
) -> None:
    require_digest(expected_source_digest, field_name="expected_source_digest")
    require_digest(
        expected_discovery_report_digest,
        field_name="expected_discovery_report_digest",
    )
    if plan.source_digest != expected_source_digest:
        raise ExternalQualificationError(
            "qualification_preparation_source_drift",
            "identity preparation plan source differs from the expected checkout",
        )
    if plan.discovery_report_digest != expected_discovery_report_digest:
        raise ExternalQualificationError(
            "qualification_preparation_discovery_drift",
            "identity preparation plan does not bind the expected discovery report",
        )
    expected = tuple(sorted(expected_gap_digests))
    for digest in expected:
        require_digest(digest, field_name="expected_gap_digest")
    if tuple(item.gap_digest for item in plan.decisions) != expected:
        raise ExternalQualificationError(
            "qualification_preparation_gap_coverage_mismatch",
            "identity preparation decisions do not cover the expected batch gaps",
        )
    if canonical_sha256_digest(plan.identity_payload) != plan.preparation_plan_digest:
        raise ExternalQualificationError(
            "qualification_preparation_plan_digest_mismatch",
            "identity preparation plan digest does not verify",
        )


@dataclass(frozen=True, slots=True)
class ExternalIdentityPreparationOccurrenceAuthorization:
    authorization_id: str
    preparation_plan_digest: str
    batch_id: str
    operator_id: str
    authorized_at: str
    authorization_digest: str = ""

    SCHEMA_VERSION: ClassVar[str] = (
        EXTERNAL_IDENTITY_PREPARATION_OCCURRENCE_AUTHORIZATION_SCHEMA
    )

    @classmethod
    def create(
        cls, **values: Any
    ) -> "ExternalIdentityPreparationOccurrenceAuthorization":
        item = cls(**values, authorization_digest="sha256:" + "0" * 64)
        return replace(
            item,
            authorization_digest=canonical_sha256_digest(item.identity_payload),
        )

    def __post_init__(self) -> None:
        require_identifier(self.authorization_id, field_name="authorization_id")
        require_identifier(self.batch_id, field_name="batch_id")
        require_identifier(self.operator_id, field_name="operator_id")
        require_digest(
            self.preparation_plan_digest,
            field_name="preparation_plan_digest",
        )
        _timestamp(self.authorized_at, field_name="authorized_at")
        require_digest(self.authorization_digest, field_name="authorization_digest")
        if self.authorization_digest != "sha256:" + "0" * 64:
            expected = canonical_sha256_digest(self.identity_payload)
            if self.authorization_digest != expected:
                raise ExternalQualificationError(
                    "qualification_preparation_authorization_digest_mismatch",
                    "identity preparation authorization digest does not match",
                )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "authorization_id": self.authorization_id,
            "preparation_plan_digest": self.preparation_plan_digest,
            "batch_id": self.batch_id,
            "operator_id": self.operator_id,
            "authority_mode": "durable_one_shot",
            "authorized_at": self.authorized_at,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload,
            "authorization_digest": self.authorization_digest,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, object]
    ) -> "ExternalIdentityPreparationOccurrenceAuthorization":
        allowed = {
            "schema_version",
            "authorization_id",
            "preparation_plan_digest",
            "batch_id",
            "operator_id",
            "authority_mode",
            "authorized_at",
            "authorization_digest",
        }
        if (
            set(payload) != allowed
            or payload.get("schema_version") != cls.SCHEMA_VERSION
            or payload.get("authority_mode") != "durable_one_shot"
        ):
            raise ValueError("preparation authorization payload is unsupported")

        def required_string(field_name: str) -> str:
            value = payload.get(field_name)
            if not isinstance(value, str):
                raise ValueError(f"{field_name} must be a string")
            return value

        return cls(
            authorization_id=required_string("authorization_id"),
            preparation_plan_digest=required_string("preparation_plan_digest"),
            batch_id=required_string("batch_id"),
            operator_id=required_string("operator_id"),
            authorized_at=required_string("authorized_at"),
            authorization_digest=required_string("authorization_digest"),
        )


@dataclass(frozen=True, slots=True)
class ExternalIdentityPreparationAuthorizationRevocation:
    revocation_id: str
    authorization_digest: str
    operator_id: str
    revoked_at: str
    reason_code: str
    revocation_digest: str = ""

    SCHEMA_VERSION: ClassVar[str] = (
        EXTERNAL_IDENTITY_PREPARATION_AUTHORIZATION_REVOCATION_SCHEMA
    )

    @classmethod
    def create(
        cls, **values: Any
    ) -> "ExternalIdentityPreparationAuthorizationRevocation":
        item = cls(**values, revocation_digest="sha256:" + "0" * 64)
        return replace(
            item,
            revocation_digest=canonical_sha256_digest(item.identity_payload),
        )

    def __post_init__(self) -> None:
        require_identifier(self.revocation_id, field_name="revocation_id")
        require_identifier(self.operator_id, field_name="operator_id")
        require_identifier(self.reason_code, field_name="reason_code")
        require_digest(self.authorization_digest, field_name="authorization_digest")
        _timestamp(self.revoked_at, field_name="revoked_at")
        require_digest(self.revocation_digest, field_name="revocation_digest")
        if self.revocation_digest != "sha256:" + "0" * 64:
            expected = canonical_sha256_digest(self.identity_payload)
            if self.revocation_digest != expected:
                raise ExternalQualificationError(
                    "qualification_preparation_revocation_digest_mismatch",
                    "identity preparation authorization revocation digest does not match",
                )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "revocation_id": self.revocation_id,
            "authorization_digest": self.authorization_digest,
            "operator_id": self.operator_id,
            "revoked_at": self.revoked_at,
            "reason_code": self.reason_code,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload,
            "revocation_digest": self.revocation_digest,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, object]
    ) -> "ExternalIdentityPreparationAuthorizationRevocation":
        allowed = {
            "schema_version",
            "revocation_id",
            "authorization_digest",
            "operator_id",
            "revoked_at",
            "reason_code",
            "revocation_digest",
        }
        if (
            set(payload) != allowed
            or payload.get("schema_version") != cls.SCHEMA_VERSION
        ):
            raise ValueError(
                "preparation authorization revocation payload is unsupported"
            )

        def required_string(field_name: str) -> str:
            value = payload.get(field_name)
            if not isinstance(value, str):
                raise ValueError(f"{field_name} must be a string")
            return value

        return cls(
            revocation_id=required_string("revocation_id"),
            authorization_digest=required_string("authorization_digest"),
            operator_id=required_string("operator_id"),
            revoked_at=required_string("revoked_at"),
            reason_code=required_string("reason_code"),
            revocation_digest=required_string("revocation_digest"),
        )


def verify_external_identity_preparation_occurrence_authorization(
    plan: ExternalIdentityPreparationPlan,
    authorization: ExternalIdentityPreparationOccurrenceAuthorization | None,
    *,
    observed_at: str,
) -> None:
    if authorization is None:
        raise ExternalQualificationError(
            "blocked_preparation_authorization",
            "exact identity preparation authorization is required before any effect",
        )
    if (
        authorization.preparation_plan_digest != plan.preparation_plan_digest
        or authorization.batch_id != plan.batch_id
    ):
        raise ExternalQualificationError(
            "qualification_preparation_authorization_mismatch",
            "preparation authorization does not bind the exact plan and batch",
        )
    _timestamp(observed_at, field_name="observed_at")


def verify_external_identity_preparation_authorization_not_revoked(
    authorization: ExternalIdentityPreparationOccurrenceAuthorization,
    revocation: ExternalIdentityPreparationAuthorizationRevocation | None,
) -> None:
    if revocation is None:
        return
    if (
        revocation.authorization_digest != authorization.authorization_digest
        or revocation.operator_id != authorization.operator_id
    ):
        raise ExternalQualificationError(
            "qualification_preparation_revocation_mismatch",
            "preparation authorization revocation does not bind the exact authority",
        )
    raise ExternalQualificationError(
        "qualification_preparation_authorization_revoked",
        "identity preparation authorization was explicitly revoked",
    )


@dataclass(frozen=True, slots=True)
class ExternalIdentityPreparationResult:
    occurrence_id: str
    preparation_plan_digest: str
    authorization_digest: str
    action_id: str
    owner_component_id: str
    input_binding_digest: str
    safe_identity_fields: tuple[SafeIdentityField, ...]
    observation: ExternalQualificationOperationObservation
    result_digest: str = ""

    SCHEMA_VERSION: ClassVar[str] = EXTERNAL_IDENTITY_PREPARATION_RESULT_SCHEMA

    @classmethod
    def create(cls, **values: Any) -> "ExternalIdentityPreparationResult":
        item = cls(**values, result_digest="sha256:" + "0" * 64)
        return replace(
            item,
            result_digest=canonical_sha256_digest(item.identity_payload),
        )

    def __post_init__(self) -> None:
        for field_name in ("occurrence_id", "action_id", "owner_component_id"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "preparation_plan_digest",
            "authorization_digest",
            "input_binding_digest",
            "result_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        fields = tuple(
            sorted(self.safe_identity_fields, key=lambda item: item.field_id)
        )
        if not fields or len({item.field_id for item in fields}) != len(fields):
            raise ValueError(
                "preparation safe identity fields must be non-empty and unique"
            )
        object.__setattr__(self, "safe_identity_fields", fields)
        safe_output_digest = canonical_sha256_digest(
            {
                "schema_version": "external_identity_preparation_safe_output@1",
                "action_id": self.action_id,
                "safe_identity_fields": [item.to_dict() for item in fields],
            }
        )
        if (
            not self.observation.succeeded
            or self.observation.output_digest != safe_output_digest
        ):
            raise ExternalQualificationError(
                "qualification_preparation_safe_output_mismatch",
                "successful preparation must bind its exact safe identity output",
            )
        if self.result_digest != "sha256:" + "0" * 64:
            expected = canonical_sha256_digest(self.identity_payload)
            if self.result_digest != expected:
                raise ExternalQualificationError(
                    "qualification_preparation_result_digest_mismatch",
                    "identity preparation result digest does not match its payload",
                )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "occurrence_id": self.occurrence_id,
            "preparation_plan_digest": self.preparation_plan_digest,
            "authorization_digest": self.authorization_digest,
            "action_id": self.action_id,
            "owner_component_id": self.owner_component_id,
            "input_binding_digest": self.input_binding_digest,
            "safe_identity_fields": [
                item.to_dict() for item in self.safe_identity_fields
            ],
            "observation": self.observation.to_dict(),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "result_digest": self.result_digest}

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, object]
    ) -> "ExternalIdentityPreparationResult":
        if payload.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("preparation result schema version is unsupported")

        def required_string(field_name: str) -> str:
            value = payload.get(field_name)
            if not isinstance(value, str):
                raise ValueError(f"{field_name} must be a string")
            return value

        raw_fields = payload.get("safe_identity_fields")
        if not isinstance(raw_fields, list):
            raise ValueError("safe_identity_fields must be a list")
        safe_identity_fields: list[SafeIdentityField] = []
        for raw_field in raw_fields:
            if not isinstance(raw_field, dict):
                raise ValueError("safe identity field must be an object")
            field_id = raw_field.get("field_id")
            value = raw_field.get("value")
            if not isinstance(field_id, str) or not isinstance(value, str):
                raise ValueError("safe identity field values must be strings")
            safe_identity_fields.append(SafeIdentityField(field_id, value))

        raw_observation = payload.get("observation")
        if not isinstance(raw_observation, dict):
            raise ValueError("observation must be an object")
        return cls(
            occurrence_id=required_string("occurrence_id"),
            preparation_plan_digest=required_string("preparation_plan_digest"),
            authorization_digest=required_string("authorization_digest"),
            action_id=required_string("action_id"),
            owner_component_id=required_string("owner_component_id"),
            input_binding_digest=required_string("input_binding_digest"),
            safe_identity_fields=tuple(safe_identity_fields),
            observation=ExternalQualificationOperationObservation.from_dict(
                raw_observation
            ),
            result_digest=required_string("result_digest"),
        )


def create_external_identity_preparation_success(
    *,
    occurrence_id: str,
    preparation_plan_digest: str,
    authorization_digest: str,
    action_id: str,
    owner_component_id: str,
    effect_id: str,
    input_binding_digest: str,
    request_digest: str,
    safe_identity_fields: tuple[SafeIdentityField, ...],
    receipt_payload: dict[str, object],
    external_effect_performed: bool,
    credential_material_accessed: bool,
) -> ExternalIdentityPreparationResult:
    output_digest = canonical_sha256_digest(
        {
            "schema_version": "external_identity_preparation_safe_output@1",
            "action_id": action_id,
            "safe_identity_fields": [
                item.to_dict()
                for item in sorted(
                    safe_identity_fields, key=lambda field: field.field_id
                )
            ],
        }
    )
    observation = ExternalQualificationOperationObservation(
        attempt_id=occurrence_id,
        request_digest=request_digest,
        operation=effect_id,
        effect_certainty="terminal_known",
        terminal=True,
        succeeded=True,
        output_digest=output_digest,
        receipt_digest=canonical_sha256_digest(receipt_payload),
        error_code=None,
        external_effect_performed=external_effect_performed,
        credential_material_accessed=credential_material_accessed,
        fallback_performed=False,
    )
    return ExternalIdentityPreparationResult.create(
        occurrence_id=occurrence_id,
        preparation_plan_digest=preparation_plan_digest,
        authorization_digest=authorization_digest,
        action_id=action_id,
        owner_component_id=owner_component_id,
        input_binding_digest=input_binding_digest,
        safe_identity_fields=safe_identity_fields,
        observation=observation,
    )


@dataclass(frozen=True, slots=True)
class ExternalQualificationDryPlan:
    plan_id: str
    batch_id: str
    source_digest: str
    readiness_plan_digest: str
    discovery_report_digest: str
    unit_bindings: tuple[ExternalQualificationUnitSubjectBinding, ...]
    subjects: tuple[ExternalRealSubjectIdentity, ...]
    budgets: tuple[ExternalQualificationBudgetPolicy, ...]
    credential_locator_ids: tuple[str, ...]
    effect_policies: tuple[ExternalQualificationEffectPolicy, ...]
    fault_policies: tuple[ExternalQualificationFaultPolicy, ...]
    ttl_policies: tuple[ExternalQualificationTtlPolicy, ...]
    storage_policy: ExternalQualificationStoragePolicy
    max_retries: int
    created_at: str
    live_effect_authorized: bool = False
    dry_plan_digest: str = ""

    SCHEMA_VERSION: ClassVar[str] = EXTERNAL_QUALIFICATION_DRY_PLAN_SCHEMA

    @classmethod
    def create(cls, **values: Any) -> "ExternalQualificationDryPlan":
        item = cls(**values, dry_plan_digest="sha256:" + "0" * 64)
        return replace(
            item, dry_plan_digest=canonical_sha256_digest(item.identity_payload)
        )

    def __post_init__(self) -> None:
        require_identifier(self.plan_id, field_name="plan_id")
        require_identifier(self.batch_id, field_name="batch_id")
        for field_name in (
            "source_digest",
            "readiness_plan_digest",
            "discovery_report_digest",
            "dry_plan_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        _timestamp(self.created_at, field_name="created_at")
        if self.max_retries != 0:
            raise ExternalQualificationError(
                "qualification_retry_policy_forbidden",
                "real qualification dry plan must set max_retries to zero",
            )
        if self.live_effect_authorized:
            raise ExternalQualificationError(
                "qualification_dry_plan_cannot_authorize_effect",
                "dry plan cannot authorize live effects",
            )
        bindings = tuple(sorted(self.unit_bindings, key=lambda item: item.unit_digest))
        if not bindings or len({item.unit_digest for item in bindings}) != len(
            bindings
        ):
            raise ValueError("dry plan unit bindings must be non-empty and unique")
        object.__setattr__(self, "unit_bindings", bindings)
        subjects = tuple(sorted(self.subjects, key=lambda item: item.subject_digest))
        if len({item.subject_digest for item in subjects}) != len(subjects):
            raise ValueError("dry plan subjects must be unique")
        object.__setattr__(self, "subjects", subjects)
        subject_digests = {item.subject_digest for item in subjects}
        if any(
            item.subject_digest is not None
            and item.subject_digest not in subject_digests
            for item in bindings
        ):
            raise ExternalQualificationError(
                "qualification_dry_plan_subject_missing",
                "unit binding references a subject outside the dry plan",
            )
        budgets = tuple(sorted(self.budgets, key=lambda item: item.budget_id))
        if not budgets or len({item.budget_id for item in budgets}) != len(budgets):
            raise ValueError("dry plan budgets must be non-empty and unique")
        object.__setattr__(self, "budgets", budgets)
        object.__setattr__(
            self,
            "credential_locator_ids",
            canonical_string_tuple(
                self.credential_locator_ids, field_name="credential_locator_ids"
            ),
        )
        binding_locators = tuple(
            sorted(
                {
                    item.credential_locator_id
                    for item in bindings
                    if item.credential_locator_id is not None
                }
            )
        )
        if self.credential_locator_ids != binding_locators:
            raise ExternalQualificationError(
                "qualification_credential_locator_coverage_mismatch",
                "dry plan credential locators must exactly match unit bindings",
            )
        for field_name, identity_field in (
            ("effect_policies", "effect_id"),
            ("fault_policies", "fault_id"),
            ("ttl_policies", "policy_id"),
        ):
            values = tuple(
                sorted(
                    getattr(self, field_name),
                    key=lambda item: getattr(item, identity_field),
                )
            )
            if not values or len(
                {getattr(item, identity_field) for item in values}
            ) != len(values):
                raise ValueError(f"{field_name} must be non-empty and unique")
            object.__setattr__(self, field_name, values)
        require_digest(self.dry_plan_digest, field_name="dry_plan_digest")
        if self.dry_plan_digest != "sha256:" + "0" * 64:
            expected = canonical_sha256_digest(self.identity_payload)
            if self.dry_plan_digest != expected:
                raise ExternalQualificationError(
                    "qualification_dry_plan_digest_mismatch",
                    "dry plan digest does not match its payload",
                )

    @property
    def unresolved_gap_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted({gap for item in self.unit_bindings for gap in item.gap_ids})
        )

    @property
    def authorizable(self) -> bool:
        return not self.unresolved_gap_ids

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "batch_id": self.batch_id,
            "source_digest": self.source_digest,
            "readiness_plan_digest": self.readiness_plan_digest,
            "discovery_report_digest": self.discovery_report_digest,
            "unit_bindings": [item.to_dict() for item in self.unit_bindings],
            "subjects": [item.to_dict() for item in self.subjects],
            "budgets": [item.to_dict() for item in self.budgets],
            "credential_locator_ids": list(self.credential_locator_ids),
            "effect_policies": [item.to_dict() for item in self.effect_policies],
            "fault_policies": [item.to_dict() for item in self.fault_policies],
            "ttl_policies": [item.to_dict() for item in self.ttl_policies],
            "storage_policy": self.storage_policy.to_dict(),
            "max_retries": self.max_retries,
            "created_at": self.created_at,
            "live_effect_authorized": self.live_effect_authorized,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload,
            "authorizable": self.authorizable,
            "unresolved_gap_ids": list(self.unresolved_gap_ids),
            "dry_plan_digest": self.dry_plan_digest,
        }


def verify_external_qualification_dry_plan(
    plan: ExternalQualificationDryPlan,
    *,
    expected_source_digest: str,
    expected_readiness_plan_digest: str,
) -> None:
    require_digest(expected_source_digest, field_name="expected_source_digest")
    require_digest(
        expected_readiness_plan_digest,
        field_name="expected_readiness_plan_digest",
    )
    if plan.source_digest != expected_source_digest:
        raise ExternalQualificationError(
            "qualification_dry_plan_source_drift",
            "dry plan source identity differs from the expected checkout",
        )
    if plan.readiness_plan_digest != expected_readiness_plan_digest:
        raise ExternalQualificationError(
            "qualification_readiness_plan_drift",
            "dry plan does not bind the expected readiness plan",
        )
    if canonical_sha256_digest(plan.identity_payload) != plan.dry_plan_digest:
        raise ExternalQualificationError(
            "qualification_dry_plan_digest_mismatch",
            "dry plan digest does not verify",
        )


@dataclass(frozen=True, slots=True)
class ExternalQualificationOccurrenceAuthorization:
    authorization_id: str
    dry_plan_digest: str
    batch_id: str
    operator_id: str
    valid_from: str
    valid_until: str
    authorization_digest: str = ""

    SCHEMA_VERSION: ClassVar[str] = (
        EXTERNAL_QUALIFICATION_OCCURRENCE_AUTHORIZATION_SCHEMA
    )

    @classmethod
    def create(cls, **values: Any) -> "ExternalQualificationOccurrenceAuthorization":
        item = cls(**values, authorization_digest="sha256:" + "0" * 64)
        return replace(
            item, authorization_digest=canonical_sha256_digest(item.identity_payload)
        )

    def __post_init__(self) -> None:
        require_identifier(self.authorization_id, field_name="authorization_id")
        require_identifier(self.batch_id, field_name="batch_id")
        require_identifier(self.operator_id, field_name="operator_id")
        require_digest(self.dry_plan_digest, field_name="dry_plan_digest")
        start = _timestamp(self.valid_from, field_name="valid_from")
        end = _timestamp(self.valid_until, field_name="valid_until")
        if end <= start:
            raise ValueError("authorization validity must be positive")
        require_digest(self.authorization_digest, field_name="authorization_digest")
        if self.authorization_digest != "sha256:" + "0" * 64:
            expected = canonical_sha256_digest(self.identity_payload)
            if self.authorization_digest != expected:
                raise ExternalQualificationError(
                    "qualification_occurrence_authorization_digest_mismatch",
                    "occurrence authorization digest does not match its payload",
                )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "authorization_id": self.authorization_id,
            "dry_plan_digest": self.dry_plan_digest,
            "batch_id": self.batch_id,
            "operator_id": self.operator_id,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload,
            "authorization_digest": self.authorization_digest,
        }


def verify_external_qualification_occurrence_authorization(
    plan: ExternalQualificationDryPlan,
    authorization: ExternalQualificationOccurrenceAuthorization | None,
    *,
    observed_at: str,
) -> None:
    if authorization is None:
        raise ExternalQualificationError(
            "blocked_live_authorization",
            "exact occurrence authorization is required before credential resolution",
        )
    if not plan.authorizable:
        raise ExternalQualificationError(
            "blocked_identity",
            "dry plan has unresolved identity gaps and cannot be authorized",
        )
    if (
        authorization.dry_plan_digest != plan.dry_plan_digest
        or authorization.batch_id != plan.batch_id
    ):
        raise ExternalQualificationError(
            "qualification_occurrence_authorization_mismatch",
            "occurrence authorization does not bind the exact dry plan and batch",
        )
    observed = _timestamp(observed_at, field_name="observed_at")
    if not (
        _timestamp(authorization.valid_from, field_name="valid_from")
        <= observed
        < _timestamp(authorization.valid_until, field_name="valid_until")
    ):
        raise ExternalQualificationError(
            "qualification_occurrence_authorization_expired",
            "occurrence authorization is outside its validity window",
        )


@dataclass(frozen=True, slots=True)
class ExternalQualificationSafeReceipt:
    receipt_id: str
    dry_plan_digest: str
    unit_digest: str
    subject_digest: str
    authorization_digest: str
    diagnostic_id: str
    observed_at: str
    valid_until: str
    receipt_digest: str = ""

    SCHEMA_VERSION: ClassVar[str] = EXTERNAL_QUALIFICATION_SAFE_RECEIPT_SCHEMA

    @classmethod
    def create(cls, **values: Any) -> "ExternalQualificationSafeReceipt":
        item = cls(**values, receipt_digest="sha256:" + "0" * 64)
        return replace(
            item, receipt_digest=canonical_sha256_digest(item.identity_payload)
        )

    def __post_init__(self) -> None:
        require_identifier(self.receipt_id, field_name="receipt_id")
        require_identifier(self.diagnostic_id, field_name="diagnostic_id")
        for field_name in (
            "dry_plan_digest",
            "unit_digest",
            "subject_digest",
            "authorization_digest",
            "receipt_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if _timestamp(self.valid_until, field_name="valid_until") <= _timestamp(
            self.observed_at, field_name="observed_at"
        ):
            raise ValueError("receipt validity must be positive")
        if self.receipt_digest != "sha256:" + "0" * 64:
            expected = canonical_sha256_digest(self.identity_payload)
            if self.receipt_digest != expected:
                raise ExternalQualificationError(
                    "qualification_safe_receipt_digest_mismatch",
                    "safe receipt digest does not match its payload",
                )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "receipt_id": self.receipt_id,
            "dry_plan_digest": self.dry_plan_digest,
            "unit_digest": self.unit_digest,
            "subject_digest": self.subject_digest,
            "authorization_digest": self.authorization_digest,
            "diagnostic_id": self.diagnostic_id,
            "observed_at": self.observed_at,
            "valid_until": self.valid_until,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "receipt_digest": self.receipt_digest}


__all__ = [
    "BoundExternalQualificationOperationBridge",
    "ExternalIdentityGap",
    "ExternalIdentityPreparationAction",
    "ExternalIdentityPreparationOccurrenceAuthorization",
    "ExternalIdentityPreparationPlan",
    "ExternalIdentityPreparationResult",
    "ExternalIdentityResolutionCandidate",
    "ExternalIdentityResolutionDecision",
    "ExternalQualificationBridgeBinding",
    "ExternalBoundQualificationOperationPort",
    "ExternalQualificationBudgetPolicy",
    "ExternalQualificationDryPlan",
    "ExternalQualificationEffectPolicy",
    "ExternalQualificationFaultPolicy",
    "ExternalQualificationOccurrenceAuthorization",
    "ExternalQualificationOperationObservation",
    "ExternalQualificationOperationPort",
    "ExternalScientificQualificationOperationPort",
    "ExternalQualificationSafeReceipt",
    "ExternalQualificationStoragePolicy",
    "ExternalQualificationTtlPolicy",
    "ExternalQualificationUnitSubjectBinding",
    "ExternalRealSubjectIdentity",
    "ExternalSubjectIdentityDiscoveryReport",
    "ExternalSubjectIdentityObservation",
    "ExternalSubjectIdentityStatus",
    "SafeIdentityField",
    "create_external_identity_preparation_success",
    "verify_external_identity_decision",
    "verify_external_identity_preparation_occurrence_authorization",
    "verify_external_identity_preparation_plan",
    "verify_external_qualification_probe_request_binding",
    "verify_external_qualification_dry_plan",
    "verify_external_qualification_occurrence_authorization",
]
