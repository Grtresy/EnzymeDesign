from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import time

from .observation import QualificationObservation


class QualificationScenarioStatus(StrEnum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNPROVEN = "unproven"


@dataclass(frozen=True, slots=True)
class ScenarioBudget:
    max_steps: int
    max_ticks: int
    max_state_version_delta: int
    max_event_delta: int
    max_effect_count: int
    deadline_seconds: int

    def __post_init__(self) -> None:
        values = (
            self.max_steps,
            self.max_ticks,
            self.max_state_version_delta,
            self.max_event_delta,
            self.max_effect_count,
        )
        if any(value < 0 for value in values):
            raise ValueError("scenario budget counters must be non-negative")
        if self.deadline_seconds <= 0:
            raise ValueError("scenario deadline must be positive")

    @classmethod
    def from_registry(cls, value: object) -> "ScenarioBudget":
        if not isinstance(value, dict):
            raise ValueError("registry scenario budget must be an object")
        expected = {
            "deadline_seconds",
            "max_effect_count",
            "max_event_delta",
            "max_state_version_delta",
            "max_steps",
            "max_ticks",
        }
        if set(value) != expected or any(
            isinstance(item, bool) or not isinstance(item, int)
            for item in value.values()
        ):
            raise ValueError("registry scenario budget is not closed integer data")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class BudgetDeltas:
    steps: int
    ticks: int
    state_versions: int
    events: int
    effects: int
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class BudgetEvaluation:
    status: QualificationScenarioStatus
    deltas: BudgetDeltas
    rejection_reasons: tuple[str, ...]


class ScenarioBudgetTracker:
    def __init__(
        self,
        *,
        budget: ScenarioBudget,
        before: QualificationObservation,
    ) -> None:
        self.budget = budget
        self.before = before
        self.steps = 0
        self._started_at = time.monotonic()

    def step(self, count: int = 1) -> None:
        if count <= 0:
            raise ValueError("scenario step increment must be positive")
        self.steps += count

    def evaluate(
        self,
        *,
        after: QualificationObservation,
        allowed_terminal_observed: bool,
        evidence_complete: bool,
        now: float | None = None,
    ) -> BudgetEvaluation:
        before_counts = self.before.counts
        after_counts = after.counts
        deltas = BudgetDeltas(
            steps=self.steps,
            ticks=max(0, after_counts.worker_tick_count - before_counts.worker_tick_count),
            state_versions=max(
                0,
                after_counts.state_version_total
                - before_counts.state_version_total,
            ),
            events=max(0, after_counts.event_count - before_counts.event_count),
            effects=max(0, after_counts.effect_count - before_counts.effect_count),
            elapsed_seconds=(time.monotonic() if now is None else now)
            - self._started_at,
        )
        exceeded: list[str] = []
        limits = (
            ("max_steps", deltas.steps, self.budget.max_steps),
            ("max_ticks", deltas.ticks, self.budget.max_ticks),
            (
                "max_state_version_delta",
                deltas.state_versions,
                self.budget.max_state_version_delta,
            ),
            ("max_event_delta", deltas.events, self.budget.max_event_delta),
            ("max_effect_count", deltas.effects, self.budget.max_effect_count),
        )
        for name, actual, limit in limits:
            if actual > limit:
                exceeded.append(f"{name}:{actual}>{limit}")
        if deltas.elapsed_seconds > self.budget.deadline_seconds:
            exceeded.append(
                "deadline_seconds:"
                f"{deltas.elapsed_seconds:.6f}>{self.budget.deadline_seconds}"
            )
        if exceeded:
            return BudgetEvaluation(
                status=QualificationScenarioStatus.VIOLATED,
                deltas=deltas,
                rejection_reasons=tuple(exceeded),
            )
        if not evidence_complete:
            return BudgetEvaluation(
                status=QualificationScenarioStatus.UNPROVEN,
                deltas=deltas,
                rejection_reasons=("required_cross_layer_evidence_missing",),
            )
        if not allowed_terminal_observed:
            return BudgetEvaluation(
                status=QualificationScenarioStatus.UNPROVEN,
                deltas=deltas,
                rejection_reasons=("allowed_terminal_observation_missing",),
            )
        return BudgetEvaluation(
            status=QualificationScenarioStatus.SATISFIED,
            deltas=deltas,
            rejection_reasons=(),
        )


__all__ = [
    "BudgetDeltas",
    "BudgetEvaluation",
    "QualificationScenarioStatus",
    "ScenarioBudget",
    "ScenarioBudgetTracker",
]
