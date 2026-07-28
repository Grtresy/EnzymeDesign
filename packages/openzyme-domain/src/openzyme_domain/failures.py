from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from typing import ClassVar

from .reliability import ExternalEffectCertainty
from .reliability import RetryEligibility


FAILURE_OBSERVATION_SCHEMA_VERSION = "failure_observation@1"
AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE = "agent_turn_budget_exhausted"


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
        data.pop("private_diagnostic_digest", None)
        return data


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
    "FailureActorKind",
    "FailureClass",
    "FailureObservation",
    "FailureRecoverability",
    "likely_causes_for_error_code",
]
