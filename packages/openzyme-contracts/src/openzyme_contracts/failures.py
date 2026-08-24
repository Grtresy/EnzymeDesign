from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import fields
from enum import StrEnum
import hashlib
import json
import re
import traceback
from typing import Any
from typing import ClassVar
from typing import Mapping

from .identity import json_compatible
from .reliability import ExternalEffectCertainty
from .reliability import RetryEligibility


FAILURE_OBSERVATION_SCHEMA_VERSION = "failure_observation@2"
LEGACY_FAILURE_OBSERVATION_SCHEMA_VERSION = "failure_observation@1"
PRIVATE_DIAGNOSTIC_SCHEMA_VERSION = "private_diagnostic_record@1"
AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE = "agent_turn_budget_exhausted"

_MACHINE_ID = re.compile(r"[A-Za-z][A-Za-z0-9._:@-]{0,127}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class FailureClass(StrEnum):
    VALIDATION = "validation"
    TOOL = "tool"
    PROVIDER = "provider"
    CONTROLLED_EFFECT = "controlled_effect"
    HARNESS = "harness"
    RUNTIME = "runtime"
    SYSTEM = "system"


class FailureRecoverability(StrEnum):
    AGENT_CAN_RETRY = "agent_can_retry"
    AGENT_CAN_REPLAN = "agent_can_replan"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    AUTHORIZATION_REQUIRED = "authorization_required"
    RUNTIME_RETRY = "runtime_retry"
    TERMINAL = "terminal"


class FailureActorKind(StrEnum):
    HARNESS = "harness"
    SYSTEM = "system"
    AGENT = "agent"


@dataclass(frozen=True, slots=True)
class FailureObservation:
    """Immutable public-safe facts about one exact failure source version."""

    SCHEMA_VERSION: ClassVar[str] = FAILURE_OBSERVATION_SCHEMA_VERSION

    failure_id: str
    session_id: str
    source_kind: str
    source_ref: str
    source_version: str
    phase: str
    failure_class: FailureClass
    recoverability: FailureRecoverability
    effect_certainty: ExternalEffectCertainty
    retry_eligibility: RetryEligibility
    actor_kind: FailureActorKind
    error_code: str
    safe_summary: str
    facts: dict[str, Any]
    likely_causes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    created_at: str
    task_id: str | None = None
    lane_id: str | None = None
    agent_id: str | None = None
    safe_hint: str | None = None
    private_diagnostic_digest: str | None = None
    component: str = "unknown_component"
    operation: str = "unknown_operation"
    identities: dict[str, str] | None = None
    mutation_applied: bool | None = False
    fallback_performed: bool = False
    cause_chain: tuple[dict[str, str], ...] = ()
    diagnostic_id: str = "diagnostic_unknown"
    next_action: str = "inspect_diagnostic"

    def __post_init__(self) -> None:
        if self.component == "unknown_component":
            object.__setattr__(self, "component", self.source_kind)
        if self.operation == "unknown_operation":
            object.__setattr__(self, "operation", self.phase)
        if self.diagnostic_id == "diagnostic_unknown":
            suffix = _canonical_digest(
                {"failure_id": self.failure_id, "schema_version": self.SCHEMA_VERSION}
            ).removeprefix("sha256:")[:20]
            object.__setattr__(self, "diagnostic_id", f"diagnostic_{suffix}")
        for name in (
            "component",
            "operation",
            "phase",
            "error_code",
            "diagnostic_id",
            "next_action",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or _MACHINE_ID.fullmatch(value) is None:
                raise ValueError(f"FailureObservation.{name} must be a safe identifier")
        if self.mutation_applied is not None and not isinstance(
            self.mutation_applied, bool
        ):
            raise ValueError(
                "FailureObservation.mutation_applied must be boolean or null"
            )
        if not isinstance(self.fallback_performed, bool):
            raise ValueError("FailureObservation.fallback_performed must be boolean")
        identities = self.identities or {}
        if any(
            not isinstance(key, str)
            or _MACHINE_ID.fullmatch(key) is None
            or not isinstance(value, str)
            or not value
            for key, value in identities.items()
        ):
            raise ValueError("FailureObservation.identities must be typed string facts")
        object.__setattr__(self, "identities", dict(sorted(identities.items())))
        for cause in self.cause_chain:
            if set(cause) != {"type", "code", "message_digest"}:
                raise ValueError("FailureObservation.cause_chain fields are closed")
            if (
                _MACHINE_ID.fullmatch(cause["type"]) is None
                or _MACHINE_ID.fullmatch(cause["code"]) is None
                or _DIGEST.fullmatch(cause["message_digest"]) is None
            ):
                raise ValueError("FailureObservation.cause_chain contains unsafe facts")
        if (
            self.private_diagnostic_digest is not None
            and _DIGEST.fullmatch(self.private_diagnostic_digest) is None
        ):
            raise ValueError("FailureObservation.private_diagnostic_digest is invalid")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["schema_version"] = self.SCHEMA_VERSION
        data["failure_class"] = self.failure_class.value
        data["recoverability"] = self.recoverability.value
        data["effect_certainty"] = self.effect_certainty.value
        data["retry_eligibility"] = self.retry_eligibility.value
        data["actor_kind"] = self.actor_kind.value
        data["likely_causes"] = list(self.likely_causes)
        data["evidence_refs"] = list(self.evidence_refs)
        data["cause_chain"] = [dict(item) for item in self.cause_chain]
        data.pop("private_diagnostic_digest", None)
        return data

    def to_internal_dict(self) -> dict[str, Any]:
        """Return the canonical owner payload, including only an opaque private link.

        Public callers must use :meth:`to_dict`.  The private diagnostic body is
        never embedded here; the optional digest exists solely so the Kernel can
        atomically bind the public observation to its operator-only sidecar.
        """

        data = self.to_dict()
        if self.private_diagnostic_digest is not None:
            data["private_diagnostic_digest"] = self.private_diagnostic_digest
        return data


@dataclass(frozen=True, slots=True)
class LegacyFailureObservationV1:
    """Read-only representation for historical v1 evidence; never written."""

    payload: dict[str, Any]
    schema_version: str = LEGACY_FAILURE_OBSERVATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


@dataclass(frozen=True, slots=True)
class PrivateDiagnosticRecord:
    """Immutable operator-only evidence paired with one public observation."""

    diagnostic_id: str
    failure_id: str
    session_id: str
    component: str
    operation: str
    phase: str
    exception_type: str
    exception_message: str
    traceback_text: str
    cause_chain: tuple[dict[str, Any], ...]
    errno: int | None
    return_code: int | None
    bounded_stdout: str | None
    bounded_stderr: str | None
    private_context: dict[str, Any]
    source_kind: str
    source_ref: str
    source_version: str
    correlation_id: str | None
    created_at: str
    record_digest: str
    schema_version: str = PRIVATE_DIAGNOSTIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PRIVATE_DIAGNOSTIC_SCHEMA_VERSION:
            raise ValueError("unsupported private diagnostic schema")
        for name in (
            "diagnostic_id",
            "failure_id",
            "session_id",
            "component",
            "operation",
            "phase",
            "source_kind",
            "source_ref",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or _MACHINE_ID.fullmatch(value) is None:
                raise ValueError(f"PrivateDiagnosticRecord.{name} is invalid")
        if (
            self.correlation_id is not None
            and _MACHINE_ID.fullmatch(self.correlation_id) is None
        ):
            raise ValueError("PrivateDiagnosticRecord.correlation_id is invalid")
        if not isinstance(self.source_version, str) or not self.source_version:
            raise ValueError("PrivateDiagnosticRecord.source_version is required")
        if not isinstance(self.created_at, str) or not self.created_at:
            raise ValueError("PrivateDiagnosticRecord.created_at is required")
        for name, maximum in (
            ("exception_type", 256),
            ("exception_message", 8192),
            ("traceback_text", 65536),
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) > maximum:
                raise ValueError(f"PrivateDiagnosticRecord.{name} is invalid")
        for name in ("bounded_stdout", "bounded_stderr"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or len(value) > 65536):
                raise ValueError(f"PrivateDiagnosticRecord.{name} is invalid")
        if not isinstance(self.private_context, dict):
            raise ValueError(
                "PrivateDiagnosticRecord.private_context must be an object"
            )
        if not isinstance(self.errno, int | type(None)) or isinstance(self.errno, bool):
            raise ValueError("PrivateDiagnosticRecord.errno must be integer or null")
        if not isinstance(self.return_code, int | type(None)) or isinstance(
            self.return_code, bool
        ):
            raise ValueError(
                "PrivateDiagnosticRecord.return_code must be integer or null"
            )
        if _DIGEST.fullmatch(self.record_digest) is None:
            raise ValueError("PrivateDiagnosticRecord.record_digest is invalid")
        if self.record_digest != _canonical_digest(self.payload):
            raise ValueError("PrivateDiagnosticRecord digest mismatch")

    @property
    def payload(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("record_digest")
        data["cause_chain"] = [dict(item) for item in self.cause_chain]
        return data

    @classmethod
    def create(cls, **values: Any) -> "PrivateDiagnosticRecord":
        payload = {"schema_version": PRIVATE_DIAGNOSTIC_SCHEMA_VERSION, **values}
        return cls(**values, record_digest=_canonical_digest(payload))

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload, "record_digest": self.record_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PrivateDiagnosticRecord":
        thawed = json_compatible(value)
        if not isinstance(thawed, dict):
            raise ValueError("private diagnostic must be an object")
        value = thawed
        expected = {field.name for field in fields(cls)}
        if set(value) != expected:
            raise ValueError("private diagnostic fields are closed")
        cause_chain = value.get("cause_chain")
        private_context = value.get("private_context")
        if not isinstance(cause_chain, list | tuple) or any(
            not isinstance(item, Mapping) for item in cause_chain
        ):
            raise ValueError("private diagnostic cause_chain must be an array")
        if not isinstance(private_context, Mapping):
            raise ValueError("private diagnostic context must be an object")
        errno = value["errno"]
        return_code = value["return_code"]
        if (
            errno is not None
            and (not isinstance(errno, int) or isinstance(errno, bool))
        ) or (
            return_code is not None
            and (not isinstance(return_code, int) or isinstance(return_code, bool))
        ):
            raise ValueError("private diagnostic numeric fields are invalid")
        return cls(
            diagnostic_id=str(value["diagnostic_id"]),
            failure_id=str(value["failure_id"]),
            session_id=str(value["session_id"]),
            component=str(value["component"]),
            operation=str(value["operation"]),
            phase=str(value["phase"]),
            exception_type=str(value["exception_type"]),
            exception_message=str(value["exception_message"]),
            traceback_text=str(value["traceback_text"]),
            cause_chain=tuple(dict(item) for item in cause_chain),
            errno=errno,
            return_code=(None if return_code is None else return_code),
            bounded_stdout=(
                None
                if value["bounded_stdout"] is None
                else str(value["bounded_stdout"])
            ),
            bounded_stderr=(
                None
                if value["bounded_stderr"] is None
                else str(value["bounded_stderr"])
            ),
            private_context=dict(private_context),
            source_kind=str(value["source_kind"]),
            source_ref=str(value["source_ref"]),
            source_version=str(value["source_version"]),
            correlation_id=(
                None
                if value["correlation_id"] is None
                else str(value["correlation_id"])
            ),
            created_at=str(value["created_at"]),
            record_digest=str(value["record_digest"]),
            schema_version=str(value["schema_version"]),
        )


@dataclass(frozen=True, slots=True)
class StructuredFailureContext:
    """Exact occurrence identities used by the shared failure observer."""

    failure_id: str
    diagnostic_id: str
    session_id: str
    component: str
    operation: str
    phase: str
    source_kind: str
    source_ref: str
    source_version: str
    created_at: str
    task_id: str | None = None
    lane_id: str | None = None
    agent_id: str | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "failure_id",
            "diagnostic_id",
            "session_id",
            "component",
            "operation",
            "phase",
            "source_kind",
            "source_ref",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or _MACHINE_ID.fullmatch(value) is None:
                raise ValueError(f"StructuredFailureContext.{name} is invalid")
        if not isinstance(self.source_version, str) or not self.source_version:
            raise ValueError("StructuredFailureContext.source_version is required")
        if not isinstance(self.created_at, str) or not self.created_at:
            raise ValueError("StructuredFailureContext.created_at is required")
        for name in ("task_id", "lane_id", "agent_id", "correlation_id"):
            value = getattr(self, name)
            if value is not None and _MACHINE_ID.fullmatch(value) is None:
                raise ValueError(f"StructuredFailureContext.{name} is invalid")


@dataclass(frozen=True, slots=True)
class StructuredFailureRecords:
    """One public observation and its exact operator-only diagnostic sidecar."""

    public: FailureObservation
    private: PrivateDiagnosticRecord

    def __post_init__(self) -> None:
        validate_failure_diagnostic_pair(self.public, self.private)


def validate_failure_diagnostic_pair(
    observation: FailureObservation,
    diagnostic: PrivateDiagnosticRecord,
) -> None:
    """Fail closed unless a public/private pair names the same occurrence."""

    expected = (
        observation.failure_id,
        observation.session_id,
        observation.component,
        observation.operation,
        observation.phase,
        observation.source_kind,
        observation.source_ref,
        observation.source_version,
        observation.diagnostic_id,
        observation.private_diagnostic_digest,
    )
    observed = (
        diagnostic.failure_id,
        diagnostic.session_id,
        diagnostic.component,
        diagnostic.operation,
        diagnostic.phase,
        diagnostic.source_kind,
        diagnostic.source_ref,
        diagnostic.source_version,
        diagnostic.diagnostic_id,
        diagnostic.record_digest,
    )
    if expected != observed:
        raise ValueError("failure observation and private diagnostic identity drifted")


def observe_structured_failure(
    error: BaseException,
    *,
    context: StructuredFailureContext,
    failure_class: FailureClass,
    recoverability: FailureRecoverability,
    effect_certainty: ExternalEffectCertainty,
    retry_eligibility: RetryEligibility,
    actor_kind: FailureActorKind,
    error_code: str,
    safe_summary: str,
    safe_hint: str,
    next_action: str,
    mutation_applied: bool | None,
    fallback_performed: bool = False,
    reconcile_required: bool = False,
    retry_performed: bool = False,
    public_facts: Mapping[str, Any] | None = None,
    identities: Mapping[str, str] | None = None,
    likely_causes: tuple[str, ...] = (),
    evidence_refs: tuple[str, ...] = (),
    private_context: Mapping[str, Any] | None = None,
) -> StructuredFailureRecords:
    """Build one secret-safe public failure and bounded private diagnostic.

    This function is intentionally implementation-neutral so Kernel workflow,
    tool, provider, provisioning, and composition owners can share one closed
    failure boundary instead of hand-rolling subtly different payloads.
    """

    facts = dict(public_facts or {})
    facts.update(
        {
            "fallback_performed": fallback_performed,
            "retry_performed": retry_performed,
            "retry_eligibility": retry_eligibility.value,
            "reconcile_required": reconcile_required,
        }
    )
    if mutation_applied is not None:
        facts["mutation_applied"] = mutation_applied
    else:
        facts.pop("mutation_applied", None)
    diagnostic = PrivateDiagnosticRecord.create(
        diagnostic_id=context.diagnostic_id,
        failure_id=context.failure_id,
        session_id=context.session_id,
        component=context.component,
        operation=context.operation,
        phase=context.phase,
        exception_type=type(error).__name__[:256],
        exception_message=str(error)[:8192],
        traceback_text="".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )[:65536],
        cause_chain=_private_exception_chain(error),
        errno=_optional_int(getattr(error, "errno", None)),
        return_code=_optional_int(getattr(error, "returncode", None)),
        bounded_stdout=_bounded_private_text(getattr(error, "stdout", None)),
        bounded_stderr=_bounded_private_text(getattr(error, "stderr", None)),
        private_context=_bounded_private_mapping(private_context or {}),
        source_kind=context.source_kind,
        source_ref=context.source_ref,
        source_version=context.source_version,
        correlation_id=context.correlation_id,
        created_at=context.created_at,
    )
    observation = FailureObservation(
        failure_id=context.failure_id,
        session_id=context.session_id,
        source_kind=context.source_kind,
        source_ref=context.source_ref,
        source_version=context.source_version,
        phase=context.phase,
        failure_class=failure_class,
        recoverability=recoverability,
        effect_certainty=effect_certainty,
        retry_eligibility=retry_eligibility,
        actor_kind=actor_kind,
        error_code=error_code,
        safe_summary=safe_summary,
        facts=_safe_public_mapping(facts),
        likely_causes=likely_causes,
        evidence_refs=evidence_refs,
        created_at=context.created_at,
        task_id=context.task_id,
        lane_id=context.lane_id,
        agent_id=context.agent_id,
        safe_hint=safe_hint,
        private_diagnostic_digest=diagnostic.record_digest,
        component=context.component,
        operation=context.operation,
        identities=dict(identities or {}),
        mutation_applied=mutation_applied,
        fallback_performed=fallback_performed,
        cause_chain=_public_exception_chain(error),
        diagnostic_id=context.diagnostic_id,
        next_action=next_action,
    )
    return StructuredFailureRecords(public=observation, private=diagnostic)


def _walk_exception_chain(error: BaseException) -> tuple[BaseException, ...]:
    values: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(values) < 16:
        seen.add(id(current))
        values.append(current)
        current = current.__cause__ or current.__context__
    return tuple(values)


def _public_exception_chain(error: BaseException) -> tuple[dict[str, str], ...]:
    values: list[dict[str, str]] = []
    for item in _walk_exception_chain(error):
        exception_type = type(item).__name__[:128]
        if _MACHINE_ID.fullmatch(exception_type) is None:
            exception_type = "InternalError"
        code = getattr(item, "code", "internal_cause")
        if not isinstance(code, str) or _MACHINE_ID.fullmatch(code) is None:
            code = "internal_cause"
        values.append(
            {
                "type": exception_type,
                "code": code,
                "message_digest": _canonical_digest({"message": str(item)}),
            }
        )
    return tuple(values)


def _private_exception_chain(error: BaseException) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "type": type(item).__name__[:256],
            "code": str(getattr(item, "code", "internal_cause"))[:256],
            "message": str(item)[:8192],
        }
        for item in _walk_exception_chain(error)
    )


def _safe_public_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    from .diagnostics import sanitize_public_diagnostic_payload

    sanitized = sanitize_public_diagnostic_payload(dict(value))
    if not isinstance(sanitized, dict):
        raise ValueError("public failure facts must sanitize to an object")
    return sanitized


def _bounded_private_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key)[:256]: _bounded_private_value(item)
        for key, item in list(value.items())[:128]
    }


def _bounded_private_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value[:8192]
    if isinstance(value, Mapping):
        return _bounded_private_mapping(value)
    if isinstance(value, list | tuple):
        return [_bounded_private_value(item) for item in value[:128]]
    return repr(value)[:8192]


def _bounded_private_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)[:65536]


def _optional_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def parse_failure_observation(
    value: Mapping[str, Any],
) -> FailureObservation | LegacyFailureObservationV1:
    """Parse current observations and quarantine historical v1 as read-only data."""

    schema_version = value.get("schema_version")
    if schema_version == LEGACY_FAILURE_OBSERVATION_SCHEMA_VERSION:
        return LegacyFailureObservationV1(payload=dict(value))
    if schema_version != FAILURE_OBSERVATION_SCHEMA_VERSION:
        raise ValueError("failure observation schema is unsupported")
    internal_fields = {field.name for field in fields(FailureObservation)}
    public_fields = internal_fields - {"private_diagnostic_digest"}
    observed_fields = set(value) - {"schema_version"}
    if observed_fields not in {frozenset(internal_fields), frozenset(public_fields)}:
        raise ValueError("failure observation fields are closed")
    return FailureObservation(
        **{
            key: value.get(key)
            for key in internal_fields
            if key
            not in {
                "failure_class",
                "recoverability",
                "effect_certainty",
                "retry_eligibility",
                "actor_kind",
                "likely_causes",
                "evidence_refs",
                "cause_chain",
                "facts",
            }
        },
        failure_class=FailureClass(value["failure_class"]),
        recoverability=FailureRecoverability(value["recoverability"]),
        effect_certainty=ExternalEffectCertainty(value["effect_certainty"]),
        retry_eligibility=RetryEligibility(value["retry_eligibility"]),
        actor_kind=FailureActorKind(value["actor_kind"]),
        facts=dict(value["facts"]),
        likely_causes=tuple(value["likely_causes"]),
        evidence_refs=tuple(value["evidence_refs"]),
        cause_chain=tuple(dict(item) for item in value["cause_chain"]),
    )


_LIKELY_CAUSES_BY_ERROR_CODE: dict[str, tuple[str, ...]] = {
    "invalid_tool_arguments": (
        "The tool arguments do not match the current schema or referenced state.",
    ),
    "unknown_tool": (
        "The requested tool is not present in the current agent tool catalog.",
    ),
    "tool_not_visible": (
        "The current agent role or step does not have access to this tool.",
    ),
    "tool_runtime_error": (
        "The tool implementation rejected the request or encountered a local runtime error.",
        "A referenced control-plane object may have changed since the agent planned the call.",
    ),
    "runtime_fencing_rejected": (
        "Another runtime owner holds the current session mutation authority.",
        "The originating runtime lease may have expired or been superseded.",
    ),
    "provider_unavailable": (
        "The configured model or capability provider is temporarily unavailable.",
        "Provider credentials, quota, networking, or service health may require operator attention.",
    ),
    "external_effect_outcome_unknown": (
        "Dispatch may have reached an external system before the response became unavailable.",
    ),
    "harness_plan_failed": (
        "The agent model/provider or planning adapter could not produce a valid next step.",
        "The restore context or tool catalog may have drifted from the current runtime.",
    ),
    "runtime_signal_failed": (
        "The bounded agent turn or runtime owner could not complete the claimed signal.",
    ),
    AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE: (
        "The bounded agent turn used every configured step without producing an explicit terminal task action.",
    ),
}


def likely_causes_for_error_code(error_code: str) -> tuple[str, ...]:
    """Return deterministic likely causes; never infer from raw exception prose."""

    return _LIKELY_CAUSES_BY_ERROR_CODE.get(error_code, ())


__all__ = [
    "AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE",
    "FAILURE_OBSERVATION_SCHEMA_VERSION",
    "LEGACY_FAILURE_OBSERVATION_SCHEMA_VERSION",
    "PRIVATE_DIAGNOSTIC_SCHEMA_VERSION",
    "FailureActorKind",
    "FailureClass",
    "FailureObservation",
    "FailureRecoverability",
    "LegacyFailureObservationV1",
    "PrivateDiagnosticRecord",
    "StructuredFailureContext",
    "StructuredFailureRecords",
    "likely_causes_for_error_code",
    "observe_structured_failure",
    "parse_failure_observation",
    "validate_failure_diagnostic_pair",
]
