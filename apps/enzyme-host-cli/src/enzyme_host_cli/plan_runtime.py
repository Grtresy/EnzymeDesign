from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .memory_client import MemoryClient


class PlanValidationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PlanStep:
    step_id: str
    tool: str
    payload: dict[str, Any]


def load_confirmed_plan(memory: MemoryClient, episode_id: str) -> list[PlanStep]:
    try:
        plan = memory.load_plan(episode_id)
    except FileNotFoundError as exc:
        raise PlanValidationError(
            f"No confirmed plan for episode {episode_id}. Run `enzyme plan import` first."
        ) from exc

    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        raise PlanValidationError(
            f"Episode {episode_id} has no runnable steps in the confirmed plan."
        )

    parsed: list[PlanStep] = []
    seen_ids: set[str] = set()
    for raw in steps:
        if not isinstance(raw, dict):
            raise PlanValidationError("Plan steps must be objects.")
        step_id = str(raw.get("id") or "").strip()
        tool = str(raw.get("tool") or raw.get("adapter") or "").strip()
        if not step_id:
            raise PlanValidationError("Each plan step must include `id`.")
        if step_id in seen_ids:
            raise PlanValidationError(f"Duplicate plan step id: {step_id}")
        if not tool:
            raise PlanValidationError(f"Plan step {step_id} is missing `tool`.")
        seen_ids.add(step_id)
        parsed.append(PlanStep(step_id=step_id, tool=tool, payload=raw))
    return parsed


def select_steps(
    steps: list[PlanStep],
    state: dict[str, Any],
    *,
    step_id: str | None,
    resume: bool,
    force: bool = False,
) -> list[PlanStep]:
    if step_id and resume:
        raise PlanValidationError("Use either `--step` or `--resume`, not both.")
    if force and not step_id:
        raise PlanValidationError("Use `--force` together with `--step`.")

    step_state = state.get("steps")
    status_by_id: dict[str, dict[str, Any]] = (
        step_state if isinstance(step_state, dict) else {}
    )

    if step_id:
        for step in steps:
            if step.step_id == step_id:
                if status_by_id.get(step_id, {}).get("status") == "completed" and not force:
                    raise PlanValidationError(
                        f"Plan step {step_id} is already completed. "
                        f"Use `enzyme run --step {step_id} --force` to rerun it."
                    )
                return [step]
        raise PlanValidationError(f"Unknown plan step: {step_id}")

    if not resume:
        return steps

    start_index = None
    for index, step in enumerate(steps):
        record = status_by_id.get(step.step_id, {})
        if record.get("status") != "completed":
            start_index = index
            break
    if start_index is None:
        return []
    return steps[start_index:]


def load_plan_payload(path: Path) -> dict[str, Any]:
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PlanValidationError(f"Plan file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PlanValidationError(
            f"Plan file must be valid JSON for the MVP: {path}"
        ) from exc
