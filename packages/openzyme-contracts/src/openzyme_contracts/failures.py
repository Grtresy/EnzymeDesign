from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import fields
from enum import StrEnum
import hashlib
import json
import re
from typing import Any
from typing import ClassVar
from typing import Mapping

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
    mutation_applied: bool = False
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
        if not isinstance(self.mutation_applied, bool):
            raise ValueError("FailureObservation.mutation_applied must be boolean")
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
        if self.private_diagnostic_digest is not None and _DIGEST.fullmatch(
            self.private_diagnostic_digest
        ) is None:
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
        if not isinstance(self.errno, int | type(None)) or isinstance(self.errno, bool):
            raise ValueError("PrivateDiagnosticRecord.errno must be integer or null")
        if not isinstance(self.return_code, int | type(None)) or isinstance(
            self.return_code, bool
        ):
            raise ValueError("PrivateDiagnosticRecord.return_code must be integer or null")
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
            }
        },
        failure_class=FailureClass(value["failure_class"]),
        recoverability=FailureRecoverability(value["recoverability"]),
        effect_certainty=ExternalEffectCertainty(value["effect_certainty"]),
        retry_eligibility=RetryEligibility(value["retry_eligibility"]),
        actor_kind=FailureActorKind(value["actor_kind"]),
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
    "likely_causes_for_error_code",
    "parse_failure_observation",
]
