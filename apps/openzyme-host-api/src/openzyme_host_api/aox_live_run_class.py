from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import re


class AoxLiveRunClass(StrEnum):
    FORMAL_ACCEPTANCE = "formal_acceptance"
    DIAGNOSTIC = "diagnostic"


@dataclass(frozen=True, slots=True)
class AoxLiveRunPolicy:
    run_class: AoxLiveRunClass
    attempt_id_pattern: re.Pattern[str]
    campaign_id_pattern: re.Pattern[str]
    session_prefix: str
    task_prefix: str
    lane_prefix: str
    root_ref_prefix: str
    root_namespace_prefix: str | None

    def identities(
        self,
        attempt_id: str,
    ) -> tuple[str, str, str, str]:
        suffix = attempt_id.replace("-", "_")
        return (
            f"{self.session_prefix}{suffix}",
            f"{self.task_prefix}{suffix}",
            f"{self.lane_prefix}{suffix}",
            f"{self.root_ref_prefix}/{attempt_id}",
        )


FORMAL_ACCEPTANCE_RUN_POLICY = AoxLiveRunPolicy(
    run_class=AoxLiveRunClass.FORMAL_ACCEPTANCE,
    attempt_id_pattern=re.compile(r"^(positive|fault)-[a-f0-9]{32}$"),
    campaign_id_pattern=re.compile(r"^aox_campaign_[a-f0-9]{24}$"),
    session_prefix="sess_formal_",
    task_prefix="aox_execution_cutover_",
    lane_prefix="lane_aox_execution_",
    root_ref_prefix="attempts",
    root_namespace_prefix=None,
)

DIAGNOSTIC_RUN_POLICY = AoxLiveRunPolicy(
    run_class=AoxLiveRunClass.DIAGNOSTIC,
    attempt_id_pattern=re.compile(r"^diagnostic-positive-[a-f0-9]{32}$"),
    campaign_id_pattern=re.compile(r"^aox_diagnostic_[a-f0-9]{24}$"),
    session_prefix="sess_diagnostic_",
    task_prefix="aox_execution_diagnostic_",
    lane_prefix="lane_aox_diagnostic_",
    root_ref_prefix="diagnostic-attempts",
    root_namespace_prefix="aox-diagnostic-",
)

def policy_for_run_class(
    run_class: AoxLiveRunClass | str,
) -> AoxLiveRunPolicy:
    normalized = AoxLiveRunClass(run_class)
    if normalized is AoxLiveRunClass.FORMAL_ACCEPTANCE:
        return FORMAL_ACCEPTANCE_RUN_POLICY
    if normalized is AoxLiveRunClass.DIAGNOSTIC:
        return DIAGNOSTIC_RUN_POLICY
    raise ValueError(f"unsupported AOX live run class: {normalized!s}")


def authority_run_class(authority: object) -> AoxLiveRunClass:
    if not isinstance(authority, Mapping):
        raise ValueError("AOX attempt authority must be an object")
    raw_run_class = authority.get("run_class")
    if raw_run_class is None:
        return AoxLiveRunClass.FORMAL_ACCEPTANCE
    return AoxLiveRunClass(str(raw_run_class))


def authority_root_ref(authority: Mapping[str, object]) -> str:
    run_class = authority_run_class(authority)
    attempt_id = str(authority.get("attempt_id") or "")
    return policy_for_run_class(run_class).identities(attempt_id)[3]


__all__ = [
    "AoxLiveRunClass",
    "AoxLiveRunPolicy",
    "DIAGNOSTIC_RUN_POLICY",
    "FORMAL_ACCEPTANCE_RUN_POLICY",
    "authority_root_ref",
    "authority_run_class",
    "policy_for_run_class",
]
