from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TeammateRole:
    role: str
    responsibility: str
    task_kinds: tuple[str, ...]


TEAMMATE_ROSTER: tuple[TeammateRole, ...] = (
    TeammateRole(
        role="researcher",
        responsibility="literature and data research",
        task_kinds=("research",),
    ),
    TeammateRole(
        role="executor",
        responsibility="approved computational execution",
        task_kinds=("execution",),
    ),
    TeammateRole(
        role="reporter",
        responsibility="report drafting and publishing",
        task_kinds=("reporting", "report"),
    ),
)

TEAMMATE_ROLE_NAMES: tuple[str, ...] = tuple(role.role for role in TEAMMATE_ROSTER)
_ROLE_BY_TASK_KIND: dict[str, str] = {
    task_kind: role.role
    for role in TEAMMATE_ROSTER
    for task_kind in role.task_kinds
}


def teammate_roster_prompt_line() -> str:
    roster = ", ".join(f"{role.role} for {role.responsibility}" for role in TEAMMATE_ROSTER)
    return f"Available teammate agents: {roster}."


def teammate_role_for_task_kind(task_kind: str) -> str | None:
    return _ROLE_BY_TASK_KIND.get(task_kind)


def is_valid_teammate_role(role: str) -> bool:
    return role in TEAMMATE_ROLE_NAMES


__all__ = [
    "TEAMMATE_ROLE_NAMES",
    "TEAMMATE_ROSTER",
    "TeammateRole",
    "is_valid_teammate_role",
    "teammate_role_for_task_kind",
    "teammate_roster_prompt_line",
]
