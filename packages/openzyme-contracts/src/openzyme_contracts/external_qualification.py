from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from enum import StrEnum
from typing import Any
from typing import ClassVar

from .diagnostics import sanitize_public_diagnostic_payload
from .diagnostics import sanitize_public_diagnostic_text
from .identity import canonical_sha256_digest
from .identity import canonical_string_tuple
from .identity import require_digest
from .identity import require_identifier
from .reliability import ExternalEffectCertainty


EXTERNAL_QUALIFICATION_UNIT_SCHEMA = "external_qualification_unit@1"
EXTERNAL_QUALIFICATION_PLAN_SCHEMA = "external_qualification_plan@1"
EXTERNAL_QUALIFICATION_PROBE_REQUEST_SCHEMA = "external_qualification_probe_request@1"
EXTERNAL_QUALIFICATION_PROBE_OUTCOME_SCHEMA = "external_qualification_probe_outcome@1"
EXTERNAL_QUALIFICATION_READINESS_RECEIPT_SCHEMA = (
    "external_qualification_readiness_receipt@1"
)
EXTERNAL_QUALIFICATION_READINESS_REPORT_SCHEMA = (
    "external_qualification_readiness_report@1"
)
EXTERNAL_QUALIFICATION_FAILURE_SCHEMA = "external_qualification_failure@1"


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


def _optional_identifier(value: str | None, *, field_name: str) -> None:
    if value is not None:
        require_identifier(value, field_name=field_name)


class ExternalQualificationLifecycle(StrEnum):
    SELECTED = "selected"
    RUNTIME_MOUNTED = "runtime_mounted"
    READY_NON_LIVE = "ready_non_live"
    QUALIFIED = "qualified"
    CUTOVER = "cutover"
    LIVE_OCCURRENCE = "live_occurrence"


class ExternalQualificationSubjectKind(StrEnum):
    PROVIDER = "provider"
    TARGET = "target"


class ExternalQualificationReadinessStatus(StrEnum):
    READY_NON_LIVE = "ready_non_live"
    BLOCKED_READINESS = "blocked_readiness"


class ExternalQualificationProbeDisposition(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RECONCILE_REQUIRED = "reconcile_required"


class ExternalQualificationError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        diagnostic_id: str | None = None,
    ) -> None:
        self.error_code = require_identifier(error_code, field_name="error_code")
        self.diagnostic_id = diagnostic_id
        self.mutation_applied = False
        self.fallback_performed = False
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class QualificationCredentialLocator:
    credential_slot_id: str
    credential_locator_id: str
    scope_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.credential_slot_id, field_name="credential_slot_id")
        require_identifier(self.credential_locator_id, field_name="credential_locator_id")
        require_digest(self.scope_digest, field_name="scope_digest")

    def to_dict(self) -> dict[str, object]:
        return {
            "credential_slot_id": self.credential_slot_id,
            "credential_locator_id": self.credential_locator_id,
            "scope_digest": self.scope_digest,
        }


@dataclass(frozen=True, slots=True)
class ExternalQualificationUnit:
    component_id: str
    capability_id: str
    operation: str
    route_id: str
    subject_kind: ExternalQualificationSubjectKind
    subject_id: str
    source_digest: str
    build_digest: str
    configuration_digest: str
    contract_digest: str
    qualification_spec_id: str
    qualification_spec_digest: str
    validator_id: str
    expected_result_schema_digest: str
    credential_locator: QualificationCredentialLocator | None = None
    unit_digest: str = ""

    SCHEMA_VERSION: ClassVar[str] = EXTERNAL_QUALIFICATION_UNIT_SCHEMA

    @classmethod
    def create(cls, **values: Any) -> "ExternalQualificationUnit":
        unit = cls(**values, unit_digest="sha256:" + "0" * 64)
        return replace(unit, unit_digest=canonical_sha256_digest(unit.identity_payload))

    def __post_init__(self) -> None:
        for field_name in (
            "component_id",
            "capability_id",
            "operation",
            "route_id",
            "subject_id",
            "qualification_spec_id",
            "validator_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "source_digest",
            "build_digest",
            "configuration_digest",
            "contract_digest",
            "qualification_spec_digest",
            "expected_result_schema_digest",
            "unit_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if self.unit_digest != "sha256:" + "0" * 64 and self.unit_digest != (
            canonical_sha256_digest(self.identity_payload)
        ):
            raise ExternalQualificationError(
                "qualification_unit_digest_mismatch",
                "external qualification unit digest does not match its identity",
            )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "component_id": self.component_id,
            "capability_id": self.capability_id,
            "operation": self.operation,
            "route_id": self.route_id,
            "subject_kind": self.subject_kind.value,
            "subject_id": self.subject_id,
            "source_digest": self.source_digest,
            "build_digest": self.build_digest,
            "configuration_digest": self.configuration_digest,
            "contract_digest": self.contract_digest,
            "qualification_spec_id": self.qualification_spec_id,
            "qualification_spec_digest": self.qualification_spec_digest,
            "validator_id": self.validator_id,
            "expected_result_schema_digest": self.expected_result_schema_digest,
            "credential_locator": (
                None
                if self.credential_locator is None
                else self.credential_locator.to_dict()
            ),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "unit_digest": self.unit_digest}


@dataclass(frozen=True, slots=True)
class ExternalQualificationProfileRef:
    profile_id: str
    required: bool
    unit_digests: tuple[str, ...]
    required_negative_tests: tuple[str, ...]

    def __post_init__(self) -> None:
        require_identifier(self.profile_id, field_name="profile_id")
        object.__setattr__(
            self,
            "unit_digests",
            tuple(sorted(self.unit_digests)),
        )
        if not self.unit_digests or len(set(self.unit_digests)) != len(
            self.unit_digests
        ):
            raise ValueError("profile unit_digests must be non-empty and unique")
        for digest in self.unit_digests:
            require_digest(digest, field_name="unit_digest")
        object.__setattr__(
            self,
            "required_negative_tests",
            canonical_string_tuple(
                self.required_negative_tests,
                field_name="required_negative_tests",
                allow_empty=False,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "required": self.required,
            "unit_digests": list(self.unit_digests),
            "required_negative_tests": list(self.required_negative_tests),
        }


@dataclass(frozen=True, slots=True)
class ExternalQualificationPlan:
    plan_id: str
    distribution_id: str
    distribution_digest: str
    enabled_profiles: tuple[str, ...]
    profiles: tuple[ExternalQualificationProfileRef, ...]
    units: tuple[ExternalQualificationUnit, ...]
    created_at: str
    live_allowed: bool
    plan_digest: str = ""

    SCHEMA_VERSION: ClassVar[str] = EXTERNAL_QUALIFICATION_PLAN_SCHEMA

    @classmethod
    def create(cls, **values: Any) -> "ExternalQualificationPlan":
        plan = cls(**values, plan_digest="sha256:" + "0" * 64)
        return replace(plan, plan_digest=canonical_sha256_digest(plan.identity_payload))

    def __post_init__(self) -> None:
        require_identifier(self.plan_id, field_name="plan_id")
        require_identifier(self.distribution_id, field_name="distribution_id")
        require_digest(self.distribution_digest, field_name="distribution_digest")
        require_digest(self.plan_digest, field_name="plan_digest")
        _timestamp(self.created_at, field_name="created_at")
        object.__setattr__(
            self,
            "enabled_profiles",
            canonical_string_tuple(
                self.enabled_profiles,
                field_name="enabled_profiles",
            ),
        )
        profiles = tuple(sorted(self.profiles, key=lambda item: item.profile_id))
        if not profiles or len({item.profile_id for item in profiles}) != len(profiles):
            raise ValueError("plan profiles must be non-empty and unique")
        object.__setattr__(self, "profiles", profiles)
        units = tuple(sorted(self.units, key=lambda item: item.unit_digest))
        if not units or len({item.unit_digest for item in units}) != len(units):
            raise ValueError("plan units must be non-empty and unique")
        identities = {
            (
                item.capability_id,
                item.operation,
                item.route_id,
                item.subject_kind.value,
                item.subject_id,
            )
            for item in units
        }
        if len(identities) != len(units):
            raise ExternalQualificationError(
                "qualification_unit_identity_collision",
                "qualification plan contains colliding operational identities",
            )
        object.__setattr__(self, "units", units)
        available = {item.unit_digest for item in units}
        referenced = {digest for profile in profiles for digest in profile.unit_digests}
        if referenced != available:
            raise ExternalQualificationError(
                "qualification_profile_incomplete",
                "qualification profiles and plan units do not form one exact closure",
            )
        required_profiles = {item.profile_id for item in profiles if item.required}
        present_profiles = {item.profile_id for item in profiles}
        enabled = set(self.enabled_profiles)
        if not required_profiles.issubset(enabled) or enabled != present_profiles:
            raise ExternalQualificationError(
                "qualification_profile_incomplete",
                "enabled profiles must name all and only materialized profiles",
            )
        if self.plan_digest != "sha256:" + "0" * 64 and self.plan_digest != (
            canonical_sha256_digest(self.identity_payload)
        ):
            raise ExternalQualificationError(
                "qualification_plan_digest_mismatch",
                "qualification plan digest does not match its identity",
            )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "distribution_id": self.distribution_id,
            "distribution_digest": self.distribution_digest,
            "enabled_profiles": list(self.enabled_profiles),
            "profiles": [item.to_dict() for item in self.profiles],
            "units": [item.to_dict() for item in self.units],
            "created_at": self.created_at,
            "live_allowed": self.live_allowed,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "plan_digest": self.plan_digest}


@dataclass(frozen=True, slots=True)
class ExternalQualificationProbeRequest:
    attempt_id: str
    plan_digest: str
    unit_digest: str
    operation: str
    timeout_seconds: int
    input_digest: str
    expected_result_schema_digest: str
    credential_locator_id: str | None
    request_digest: str = ""

    SCHEMA_VERSION: ClassVar[str] = EXTERNAL_QUALIFICATION_PROBE_REQUEST_SCHEMA

    @classmethod
    def create(cls, **values: Any) -> "ExternalQualificationProbeRequest":
        request = cls(**values, request_digest="sha256:" + "0" * 64)
        return replace(
            request,
            request_digest=canonical_sha256_digest(request.identity_payload),
        )

    def __post_init__(self) -> None:
        require_identifier(self.attempt_id, field_name="attempt_id")
        require_identifier(self.operation, field_name="operation")
        _optional_identifier(
            self.credential_locator_id,
            field_name="credential_locator_id",
        )
        for field_name in (
            "plan_digest",
            "unit_digest",
            "input_digest",
            "expected_result_schema_digest",
            "request_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if not isinstance(self.timeout_seconds, int) or isinstance(
            self.timeout_seconds, bool
        ) or not 1 <= self.timeout_seconds <= 3600:
            raise ValueError("timeout_seconds must be in [1, 3600]")
        if self.request_digest != "sha256:" + "0" * 64 and self.request_digest != (
            canonical_sha256_digest(self.identity_payload)
        ):
            raise ExternalQualificationError(
                "qualification_probe_request_digest_mismatch",
                "qualification probe request digest does not match its identity",
            )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "attempt_id": self.attempt_id,
            "plan_digest": self.plan_digest,
            "unit_digest": self.unit_digest,
            "operation": self.operation,
            "timeout_seconds": self.timeout_seconds,
            "input_digest": self.input_digest,
            "expected_result_schema_digest": self.expected_result_schema_digest,
            "credential_locator_id": self.credential_locator_id,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "request_digest": self.request_digest}


@dataclass(frozen=True, slots=True)
class ExternalQualificationProbeOutcome:
    attempt_id: str
    request_digest: str
    disposition: ExternalQualificationProbeDisposition
    effect_certainty: ExternalEffectCertainty
    observed_operation: str | None
    output_digest: str | None
    observed_result_schema_digest: str | None
    backend_receipt_digest: str | None
    error_code: str | None = None
    external_effect_performed: bool = False
    credential_material_accessed: bool = False
    fallback_performed: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.attempt_id, field_name="attempt_id")
        require_digest(self.request_digest, field_name="request_digest")
        _optional_identifier(self.observed_operation, field_name="observed_operation")
        _optional_identifier(self.error_code, field_name="error_code")
        for field_name in (
            "output_digest",
            "observed_result_schema_digest",
            "backend_receipt_digest",
        ):
            value = getattr(self, field_name)
            if value is not None:
                require_digest(value, field_name=field_name)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": EXTERNAL_QUALIFICATION_PROBE_OUTCOME_SCHEMA,
            "attempt_id": self.attempt_id,
            "request_digest": self.request_digest,
            "disposition": self.disposition.value,
            "effect_certainty": self.effect_certainty.value,
            "observed_operation": self.observed_operation,
            "output_digest": self.output_digest,
            "observed_result_schema_digest": self.observed_result_schema_digest,
            "backend_receipt_digest": self.backend_receipt_digest,
            "error_code": self.error_code,
            "external_effect_performed": self.external_effect_performed,
            "credential_material_accessed": self.credential_material_accessed,
            "fallback_performed": self.fallback_performed,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ExternalQualificationProbeOutcome":
        if payload.get("schema_version") != EXTERNAL_QUALIFICATION_PROBE_OUTCOME_SCHEMA:
            raise ValueError("qualification probe outcome schema is unsupported")

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
            disposition=ExternalQualificationProbeDisposition(
                required_string("disposition")
            ),
            effect_certainty=ExternalEffectCertainty(
                required_string("effect_certainty")
            ),
            observed_operation=optional_string("observed_operation"),
            output_digest=optional_string("output_digest"),
            observed_result_schema_digest=optional_string(
                "observed_result_schema_digest"
            ),
            backend_receipt_digest=optional_string("backend_receipt_digest"),
            error_code=optional_string("error_code"),
            external_effect_performed=required_bool("external_effect_performed"),
            credential_material_accessed=required_bool(
                "credential_material_accessed"
            ),
            fallback_performed=required_bool("fallback_performed"),
        )


@dataclass(frozen=True, slots=True)
class ExternalQualificationFailure:
    error_code: str
    component: str
    phase: str
    diagnostic_id: str
    plan_digest: str
    unit_digest: str | None
    effect_certainty: ExternalEffectCertainty
    mutation_applied: bool
    fallback_performed: bool
    retry_policy: str
    reconcile_policy: str
    operator_action: str
    safe_summary: str

    def __post_init__(self) -> None:
        for field_name in (
            "error_code",
            "component",
            "phase",
            "diagnostic_id",
            "retry_policy",
            "reconcile_policy",
            "operator_action",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.plan_digest, field_name="plan_digest")
        if self.unit_digest is not None:
            require_digest(self.unit_digest, field_name="unit_digest")
        if sanitize_public_diagnostic_text(self.safe_summary) != self.safe_summary:
            raise ExternalQualificationError(
                "qualification_public_diagnostic_unsafe",
                "public qualification diagnostic is not secret-safe",
                diagnostic_id=self.diagnostic_id,
            )

    def to_dict(self) -> dict[str, object]:
        payload = {
            "schema_version": EXTERNAL_QUALIFICATION_FAILURE_SCHEMA,
            "error_code": self.error_code,
            "component": self.component,
            "phase": self.phase,
            "diagnostic_id": self.diagnostic_id,
            "plan_digest": self.plan_digest,
            "unit_digest": self.unit_digest,
            "effect_certainty": self.effect_certainty.value,
            "mutation_applied": self.mutation_applied,
            "fallback_performed": self.fallback_performed,
            "retry_policy": self.retry_policy,
            "reconcile_policy": self.reconcile_policy,
            "operator_action": self.operator_action,
            "safe_summary": self.safe_summary,
        }
        sanitized = sanitize_public_diagnostic_payload(payload)
        if sanitized != payload:
            raise ExternalQualificationError(
                "qualification_public_diagnostic_unsafe",
                "public qualification diagnostic payload is not secret-safe",
                diagnostic_id=self.diagnostic_id,
            )
        return payload


@dataclass(frozen=True, slots=True)
class ExternalQualificationReadinessReceipt:
    receipt_id: str
    plan_digest: str
    unit_digest: str
    status: ExternalQualificationReadinessStatus
    backend_id: str
    fixture_id: str
    observed_operation: str | None
    expected_result_schema_digest: str
    observed_result_schema_digest: str | None
    backend_receipt_digest: str | None
    negative_tests: tuple[str, ...]
    diagnostic_id: str
    effect_certainty: ExternalEffectCertainty
    external_effect_performed: bool
    credential_material_accessed: bool
    fallback_performed: bool
    observed_at: str
    valid_until: str
    receipt_digest: str = ""

    SCHEMA_VERSION: ClassVar[str] = EXTERNAL_QUALIFICATION_READINESS_RECEIPT_SCHEMA

    @classmethod
    def create(cls, **values: Any) -> "ExternalQualificationReadinessReceipt":
        receipt = cls(**values, receipt_digest="sha256:" + "0" * 64)
        return replace(
            receipt,
            receipt_digest=canonical_sha256_digest(receipt.identity_payload),
        )

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_id",
            "backend_id",
            "fixture_id",
            "diagnostic_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        _optional_identifier(self.observed_operation, field_name="observed_operation")
        for field_name in (
            "plan_digest",
            "unit_digest",
            "expected_result_schema_digest",
            "receipt_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "observed_result_schema_digest",
            "backend_receipt_digest",
        ):
            value = getattr(self, field_name)
            if value is not None:
                require_digest(value, field_name=field_name)
        object.__setattr__(
            self,
            "negative_tests",
            canonical_string_tuple(
                self.negative_tests,
                field_name="negative_tests",
                allow_empty=False,
            ),
        )
        observed = _timestamp(self.observed_at, field_name="observed_at")
        valid = _timestamp(self.valid_until, field_name="valid_until")
        if valid <= observed:
            raise ValueError("valid_until must be later than observed_at")
        if self.status is ExternalQualificationReadinessStatus.READY_NON_LIVE:
            if (
                self.external_effect_performed
                or self.credential_material_accessed
                or self.fallback_performed
                or self.observed_operation is None
                or self.observed_result_schema_digest
                != self.expected_result_schema_digest
                or self.backend_receipt_digest is None
                or self.effect_certainty is not ExternalEffectCertainty.NO_EFFECT
            ):
                raise ExternalQualificationError(
                    "qualification_readiness_claim_invalid",
                    "ready_non_live requires a no-effect exact deterministic result",
                    diagnostic_id=self.diagnostic_id,
                )
        if self.receipt_digest != "sha256:" + "0" * 64 and self.receipt_digest != (
            canonical_sha256_digest(self.identity_payload)
        ):
            raise ExternalQualificationError(
                "qualification_readiness_receipt_digest_mismatch",
                "readiness receipt digest does not match its identity",
                diagnostic_id=self.diagnostic_id,
            )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "receipt_id": self.receipt_id,
            "plan_digest": self.plan_digest,
            "unit_digest": self.unit_digest,
            "status": self.status.value,
            "backend_id": self.backend_id,
            "fixture_id": self.fixture_id,
            "observed_operation": self.observed_operation,
            "expected_result_schema_digest": self.expected_result_schema_digest,
            "observed_result_schema_digest": self.observed_result_schema_digest,
            "backend_receipt_digest": self.backend_receipt_digest,
            "negative_tests": list(self.negative_tests),
            "diagnostic_id": self.diagnostic_id,
            "effect_certainty": self.effect_certainty.value,
            "external_effect_performed": self.external_effect_performed,
            "credential_material_accessed": self.credential_material_accessed,
            "fallback_performed": self.fallback_performed,
            "observed_at": self.observed_at,
            "valid_until": self.valid_until,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "receipt_digest": self.receipt_digest}


@dataclass(frozen=True, slots=True)
class ExternalQualificationReadinessReport:
    report_id: str
    plan_digest: str
    receipts: tuple[ExternalQualificationReadinessReceipt, ...]
    failures: tuple[ExternalQualificationFailure, ...]
    verified_at: str
    lifecycle_claim: ExternalQualificationLifecycle
    external_effect_performed: bool
    credential_material_accessed: bool
    fallback_performed: bool
    report_digest: str = ""

    SCHEMA_VERSION: ClassVar[str] = EXTERNAL_QUALIFICATION_READINESS_REPORT_SCHEMA

    @classmethod
    def create(cls, **values: Any) -> "ExternalQualificationReadinessReport":
        report = cls(**values, report_digest="sha256:" + "0" * 64)
        return replace(
            report,
            report_digest=canonical_sha256_digest(report.identity_payload),
        )

    def __post_init__(self) -> None:
        require_identifier(self.report_id, field_name="report_id")
        require_digest(self.plan_digest, field_name="plan_digest")
        require_digest(self.report_digest, field_name="report_digest")
        _timestamp(self.verified_at, field_name="verified_at")
        receipts = tuple(sorted(self.receipts, key=lambda item: item.unit_digest))
        if len({item.unit_digest for item in receipts}) != len(receipts):
            raise ExternalQualificationError(
                "qualification_readiness_receipt_duplicate",
                "readiness report contains duplicate unit receipts",
            )
        object.__setattr__(self, "receipts", receipts)
        failures = tuple(sorted(self.failures, key=lambda item: item.diagnostic_id))
        if len({item.diagnostic_id for item in failures}) != len(failures):
            raise ValueError("readiness report diagnostic IDs must be unique")
        object.__setattr__(self, "failures", failures)
        if self.lifecycle_claim not in {
            ExternalQualificationLifecycle.READY_NON_LIVE,
            ExternalQualificationLifecycle.RUNTIME_MOUNTED,
        }:
            raise ExternalQualificationError(
                "qualification_readiness_lifecycle_claim_invalid",
                "a readiness report cannot claim qualified, cutover or live state",
            )
        if self.lifecycle_claim is ExternalQualificationLifecycle.READY_NON_LIVE and (
            self.failures
            or any(
                item.status
                is not ExternalQualificationReadinessStatus.READY_NON_LIVE
                for item in receipts
            )
            or self.external_effect_performed
            or self.credential_material_accessed
            or self.fallback_performed
        ):
            raise ExternalQualificationError(
                "qualification_readiness_report_invalid",
                "ready_non_live report must be complete and side-effect free",
            )
        if self.report_digest != "sha256:" + "0" * 64 and self.report_digest != (
            canonical_sha256_digest(self.identity_payload)
        ):
            raise ExternalQualificationError(
                "qualification_readiness_report_digest_mismatch",
                "readiness report digest does not match its identity",
            )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "report_id": self.report_id,
            "plan_digest": self.plan_digest,
            "receipts": [item.to_dict() for item in self.receipts],
            "failures": [item.to_dict() for item in self.failures],
            "verified_at": self.verified_at,
            "lifecycle_claim": self.lifecycle_claim.value,
            "external_effect_performed": self.external_effect_performed,
            "credential_material_accessed": self.credential_material_accessed,
            "fallback_performed": self.fallback_performed,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "report_digest": self.report_digest}


@dataclass(frozen=True, slots=True)
class ExternalQualificationEvidence:
    """A real-subject receipt shape that readiness code can verify but not issue."""

    receipt_id: str
    lifecycle_claim: ExternalQualificationLifecycle
    unit_digest: str
    capability_id: str
    operation: str
    route_id: str
    subject_kind: ExternalQualificationSubjectKind
    subject_id: str
    source_digest: str
    build_digest: str
    configuration_digest: str
    validator_id: str
    observed_at: str
    valid_until: str
    receipt_digest: str = ""

    @classmethod
    def create(cls, **values: Any) -> "ExternalQualificationEvidence":
        evidence = cls(**values, receipt_digest="sha256:" + "0" * 64)
        return replace(
            evidence,
            receipt_digest=canonical_sha256_digest(evidence.identity_payload),
        )

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_id",
            "capability_id",
            "operation",
            "route_id",
            "subject_id",
            "validator_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "unit_digest",
            "source_digest",
            "build_digest",
            "configuration_digest",
            "receipt_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        observed = _timestamp(self.observed_at, field_name="observed_at")
        valid = _timestamp(self.valid_until, field_name="valid_until")
        if valid <= observed:
            raise ValueError("valid_until must be later than observed_at")
        if self.lifecycle_claim is not ExternalQualificationLifecycle.QUALIFIED:
            raise ExternalQualificationError(
                "qualification_evidence_lifecycle_invalid",
                "external qualification evidence must make an exact qualified claim",
            )
        if self.receipt_digest != "sha256:" + "0" * 64 and self.receipt_digest != (
            canonical_sha256_digest(self.identity_payload)
        ):
            raise ExternalQualificationError(
                "qualification_evidence_digest_mismatch",
                "qualification evidence digest does not match its identity",
            )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "external_qualification_evidence@1",
            "receipt_id": self.receipt_id,
            "lifecycle_claim": self.lifecycle_claim.value,
            "unit_digest": self.unit_digest,
            "capability_id": self.capability_id,
            "operation": self.operation,
            "route_id": self.route_id,
            "subject_kind": self.subject_kind.value,
            "subject_id": self.subject_id,
            "source_digest": self.source_digest,
            "build_digest": self.build_digest,
            "configuration_digest": self.configuration_digest,
            "validator_id": self.validator_id,
            "observed_at": self.observed_at,
            "valid_until": self.valid_until,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "receipt_digest": self.receipt_digest}


@dataclass(frozen=True, slots=True)
class QualifiedExternalCapabilityFact:
    capability_id: str
    operation: str
    route_id: str
    subject_kind: ExternalQualificationSubjectKind
    subject_id: str
    source_digest: str
    build_digest: str
    configuration_digest: str
    validator_id: str
    qualification_receipt_digest: str
    valid_until: str
    unit_digest: str
    fact_digest: str = ""

    @classmethod
    def create(cls, **values: Any) -> "QualifiedExternalCapabilityFact":
        fact = cls(**values, fact_digest="sha256:" + "0" * 64)
        return replace(fact, fact_digest=canonical_sha256_digest(fact.identity_payload))

    def __post_init__(self) -> None:
        for field_name in (
            "capability_id",
            "operation",
            "route_id",
            "subject_id",
            "validator_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "source_digest",
            "build_digest",
            "configuration_digest",
            "qualification_receipt_digest",
            "unit_digest",
            "fact_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        _timestamp(self.valid_until, field_name="valid_until")
        if self.fact_digest != "sha256:" + "0" * 64 and self.fact_digest != (
            canonical_sha256_digest(self.identity_payload)
        ):
            raise ExternalQualificationError(
                "qualified_external_fact_digest_mismatch",
                "qualified external capability fact digest does not match its identity",
            )

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": "qualified_external_capability_fact@1",
            "capability_id": self.capability_id,
            "operation": self.operation,
            "route_id": self.route_id,
            "subject_kind": self.subject_kind.value,
            "subject_id": self.subject_id,
            "source_digest": self.source_digest,
            "build_digest": self.build_digest,
            "configuration_digest": self.configuration_digest,
            "validator_id": self.validator_id,
            "qualification_receipt_digest": self.qualification_receipt_digest,
            "valid_until": self.valid_until,
            "unit_digest": self.unit_digest,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "fact_digest": self.fact_digest}


def adopt_qualified_external_capability(
    unit: ExternalQualificationUnit,
    evidence: ExternalQualificationEvidence | ExternalQualificationReadinessReceipt,
    *,
    adopted_at: str,
) -> QualifiedExternalCapabilityFact:
    now = _timestamp(adopted_at, field_name="adopted_at")
    if isinstance(evidence, ExternalQualificationReadinessReceipt):
        raise ExternalQualificationError(
            "qualification_readiness_not_adoptable",
            "a non-live readiness receipt cannot qualify an operational route",
            diagnostic_id=evidence.diagnostic_id,
        )
    expected = (
        unit.unit_digest,
        unit.capability_id,
        unit.operation,
        unit.route_id,
        unit.subject_kind,
        unit.subject_id,
        unit.source_digest,
        unit.build_digest,
        unit.configuration_digest,
        unit.validator_id,
    )
    observed = (
        evidence.unit_digest,
        evidence.capability_id,
        evidence.operation,
        evidence.route_id,
        evidence.subject_kind,
        evidence.subject_id,
        evidence.source_digest,
        evidence.build_digest,
        evidence.configuration_digest,
        evidence.validator_id,
    )
    if observed != expected:
        raise ExternalQualificationError(
            "qualification_evidence_identity_drift",
            "qualification evidence differs from the exact operational unit",
        )
    if evidence.receipt_digest != canonical_sha256_digest(evidence.identity_payload):
        raise ExternalQualificationError(
            "qualification_evidence_digest_mismatch",
            "qualification evidence digest does not match its identity",
        )
    if _timestamp(evidence.valid_until, field_name="valid_until") <= now:
        raise ExternalQualificationError(
            "qualification_evidence_expired",
            "qualification evidence is expired",
        )
    return QualifiedExternalCapabilityFact.create(
        capability_id=unit.capability_id,
        operation=unit.operation,
        route_id=unit.route_id,
        subject_kind=unit.subject_kind,
        subject_id=unit.subject_id,
        source_digest=unit.source_digest,
        build_digest=unit.build_digest,
        configuration_digest=unit.configuration_digest,
        validator_id=unit.validator_id,
        qualification_receipt_digest=evidence.receipt_digest,
        valid_until=evidence.valid_until,
        unit_digest=unit.unit_digest,
    )


def verify_external_qualification_readiness(
    plan: ExternalQualificationPlan,
    report: ExternalQualificationReadinessReport,
    *,
    verified_at: str,
) -> None:
    """Independently verify one deterministic readiness proof.

    This verifier deliberately cannot adopt facts or construct a live receipt.
    """

    now = _timestamp(verified_at, field_name="verified_at")
    if plan.live_allowed:
        raise ExternalQualificationError(
            "qualification_readiness_live_plan_forbidden",
            "non-live readiness verifier rejects live-enabled plans",
        )
    if report.plan_digest != plan.plan_digest:
        raise ExternalQualificationError(
            "qualification_readiness_plan_mismatch",
            "readiness report does not bind the exact plan",
        )
    if report.lifecycle_claim is not ExternalQualificationLifecycle.READY_NON_LIVE:
        raise ExternalQualificationError(
            "qualification_readiness_incomplete",
            "readiness report does not claim ready_non_live",
        )
    expected = {item.unit_digest: item for item in plan.units}
    observed = {item.unit_digest: item for item in report.receipts}
    if set(expected) != set(observed):
        raise ExternalQualificationError(
            "qualification_profile_incomplete",
            "readiness receipts do not close the plan unit set",
        )
    required_negative_tests = {
        test_id for profile in plan.profiles for test_id in profile.required_negative_tests
    }
    for unit_digest, unit in expected.items():
        receipt = observed[unit_digest]
        if receipt.plan_digest != plan.plan_digest:
            raise ExternalQualificationError(
                "qualification_readiness_plan_mismatch",
                "unit receipt does not bind the exact plan",
                diagnostic_id=receipt.diagnostic_id,
            )
        if receipt.observed_operation != unit.operation:
            raise ExternalQualificationError(
                "qualification_operation_mismatch",
                "readiness receipt observed a different operation",
                diagnostic_id=receipt.diagnostic_id,
            )
        if receipt.expected_result_schema_digest != unit.expected_result_schema_digest:
            raise ExternalQualificationError(
                "qualification_schema_mismatch",
                "readiness receipt expects a drifted result schema",
                diagnostic_id=receipt.diagnostic_id,
            )
        if not required_negative_tests.issubset(receipt.negative_tests):
            raise ExternalQualificationError(
                "qualification_negative_fixture_incomplete",
                "readiness receipt omits required negative fixtures",
                diagnostic_id=receipt.diagnostic_id,
            )
        if _timestamp(receipt.valid_until, field_name="valid_until") <= now:
            raise ExternalQualificationError(
                "qualification_readiness_receipt_expired",
                "readiness receipt is expired",
                diagnostic_id=receipt.diagnostic_id,
            )
        # Recompute without trusting construction-time validation.
        if receipt.receipt_digest != canonical_sha256_digest(receipt.identity_payload):
            raise ExternalQualificationError(
                "qualification_readiness_receipt_digest_mismatch",
                "readiness receipt digest does not match its identity",
                diagnostic_id=receipt.diagnostic_id,
            )
    if report.report_digest != canonical_sha256_digest(report.identity_payload):
        raise ExternalQualificationError(
            "qualification_readiness_report_digest_mismatch",
            "readiness report digest does not match its identity",
        )


__all__ = [
    "EXTERNAL_QUALIFICATION_FAILURE_SCHEMA",
    "EXTERNAL_QUALIFICATION_PLAN_SCHEMA",
    "EXTERNAL_QUALIFICATION_PROBE_OUTCOME_SCHEMA",
    "EXTERNAL_QUALIFICATION_PROBE_REQUEST_SCHEMA",
    "EXTERNAL_QUALIFICATION_READINESS_RECEIPT_SCHEMA",
    "EXTERNAL_QUALIFICATION_READINESS_REPORT_SCHEMA",
    "EXTERNAL_QUALIFICATION_UNIT_SCHEMA",
    "ExternalQualificationError",
    "ExternalQualificationEvidence",
    "ExternalQualificationFailure",
    "ExternalQualificationLifecycle",
    "ExternalQualificationPlan",
    "ExternalQualificationProbeDisposition",
    "ExternalQualificationProbeOutcome",
    "ExternalQualificationProbeRequest",
    "ExternalQualificationProfileRef",
    "ExternalQualificationReadinessReceipt",
    "ExternalQualificationReadinessReport",
    "ExternalQualificationReadinessStatus",
    "ExternalQualificationSubjectKind",
    "ExternalQualificationUnit",
    "QualifiedExternalCapabilityFact",
    "QualificationCredentialLocator",
    "verify_external_qualification_readiness",
    "adopt_qualified_external_capability",
]
