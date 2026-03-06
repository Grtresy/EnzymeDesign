from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_project_memory.models import utc_now_iso

from .execution import RoutedExecutionAdapter
from .memory_client import MemoryClient
from .plan_runtime import load_confirmed_plan
from .plan_runtime import load_plan_payload
from .plan_runtime import select_steps
from .reporting import build_report
from .reporting import report_path
from .workspace import ProjectContext
from .workspace import allocate_episode_id
from .workspace import list_episode_ids
from .workspace import init_project
from .workspace import load_project_context
from .workspace import resolve_episode_id
from .workspace import set_current_episode
from .workspace import set_last_run


@dataclass(slots=True)
class RunRequest:
    step_id: str | None = None
    resume: bool = False
    force: bool = False


@dataclass(slots=True)
class RunCommandResult:
    run_id: str
    step_id: str
    tool: str
    status: str
    manifest_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EpisodeSnapshot:
    project_id: str
    project_name: str
    project_root: str
    episode_id: str
    goal: str
    state: dict[str, Any]
    plan: dict[str, Any] | None
    runs: list[dict[str, Any]]
    available_episode_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HostRuntime:
    def __init__(self, executor: RoutedExecutionAdapter | None = None) -> None:
        self.executor = executor or RoutedExecutionAdapter()

    def init_project(self, base_dir: Path, name: str) -> ProjectContext:
        return init_project(base_dir, name)

    def load_project(self, start: Path) -> ProjectContext:
        return load_project_context(start)

    def create_episode(self, start: Path, goal: str) -> EpisodeSnapshot:
        context = self.load_project(start)
        memory = MemoryClient(context)
        episode_id = allocate_episode_id(context.root)
        memory.create_episode(episode_id, goal)
        set_current_episode(context.root, episode_id)
        return self.get_episode_snapshot(context, memory, episode_id)

    def switch_episode(self, start: Path, episode_id: str) -> EpisodeSnapshot:
        context = self.load_project(start)
        memory = MemoryClient(context)
        available = list_episode_ids(context.root)
        if episode_id not in available:
            raise ValueError(f"Unknown episode: {episode_id}")
        set_current_episode(context.root, episode_id)
        return self.get_episode_snapshot(context, memory, episode_id)

    def confirm_plan(
        self,
        start: Path,
        *,
        plan: dict[str, Any] | None = None,
        plan_file: Path | None = None,
        episode_id: str | None = None,
        imported_at: str | None = None,
    ) -> dict[str, Any]:
        context = self.load_project(start)
        memory = MemoryClient(context)
        selected_episode = resolve_episode_id(context.root, episode_id)
        if plan is None:
            if plan_file is None:
                plan_file = context.root / "episodes" / selected_episode / "plan.yaml"
            plan = load_plan_payload(plan_file)
        source_path = plan_file
        return memory.confirm_plan(
            selected_episode,
            plan,
            source_path=source_path,
            imported_at=imported_at,
        )

    def run_plan(
        self,
        start: Path,
        request: RunRequest | None = None,
        *,
        episode_id: str | None = None,
    ) -> list[RunCommandResult]:
        context = self.load_project(start)
        memory = MemoryClient(context)
        selected_episode = resolve_episode_id(context.root, episode_id)
        state = memory.load_state(selected_episode)
        plan_steps = load_confirmed_plan(memory, selected_episode)
        request = request or RunRequest()
        selected = select_steps(
            plan_steps,
            state,
            step_id=request.step_id,
            resume=request.resume,
            force=request.force,
        )
        if not selected:
            return []
        unsupported_tools = sorted({step.tool for step in selected if not self.executor.supports(step.tool)})
        if unsupported_tools:
            rendered = ", ".join(unsupported_tools)
            raise RuntimeError(f"Unsupported execution tool(s): {rendered}")

        all_step_ids = [step.step_id for step in plan_steps]
        completed_runs: list[RunCommandResult] = []
        for step in selected:
            memory.update_state(
                selected_episode,
                lambda current: _mark_step_started(current, step.step_id, step.tool),
            )
            try:
                result = self.executor.run_step(context.root, selected_episode, step)
            except Exception as exc:
                memory.update_state(
                    selected_episode,
                    lambda current: _mark_step_failed(
                        current,
                        step.step_id,
                        step.tool,
                        str(exc),
                    ),
                )
                raise
            memory.write_run_manifest(selected_episode, result.run_id, result.manifest_payload)
            set_last_run(context.root, result.run_id)
            updated = memory.update_state(
                selected_episode,
                lambda current: _mark_step_finished(
                    current,
                    selected_episode,
                    step.step_id,
                    step.tool,
                    result.run_id,
                    result.status,
                    all_step_ids,
                ),
            )
            run_record = updated["runs"][-1]
            completed_runs.append(
                RunCommandResult(
                    run_id=result.run_id,
                    step_id=step.step_id,
                    tool=step.tool,
                    status=result.status,
                    manifest_path=str(run_record["manifest_path"]),
                )
            )
            if result.status != "completed":
                raise RuntimeError(f"Step {step.step_id} finished with status {result.status}")
        return completed_runs

    def get_status(self, start: Path, *, episode_id: str | None = None) -> EpisodeSnapshot:
        context = self.load_project(start)
        memory = MemoryClient(context)
        selected_episode = resolve_episode_id(context.root, episode_id)
        return self.get_episode_snapshot(context, memory, selected_episode)

    def get_episode_snapshot(
        self,
        context: ProjectContext,
        memory: MemoryClient,
        episode_id: str,
    ) -> EpisodeSnapshot:
        goal = memory.load_goal(episode_id)
        state = memory.load_state(episode_id)
        try:
            plan = memory.load_plan(episode_id)
        except FileNotFoundError:
            plan = None
        runs = memory.list_episode_runs(episode_id)
        return EpisodeSnapshot(
            project_id=context.config.project_id,
            project_name=context.config.project_name,
            project_root=str(context.root),
            episode_id=episode_id,
            goal=goal,
            state=state,
            plan=plan,
            runs=runs,
            available_episode_ids=list_episode_ids(context.root),
        )

    def get_run(self, start: Path, run_id: str) -> dict[str, Any]:
        context = self.load_project(start)
        memory = MemoryClient(context)
        return memory.load_run_manifest(run_id)

    def materialize_report(self, start: Path, *, episode_id: str | None = None) -> Path:
        context = self.load_project(start)
        memory = MemoryClient(context)
        selected_episode = resolve_episode_id(context.root, episode_id)
        goal = memory.load_goal(selected_episode)
        try:
            plan = memory.load_plan(selected_episode)
        except FileNotFoundError:
            plan = None
        state = memory.load_state(selected_episode)
        target = report_path(context.root, selected_episode)
        target.write_text(
            build_report(context.config.project_name, selected_episode, goal, plan, state),
            encoding="utf-8",
        )
        memory.update_state(
            selected_episode,
            lambda current: {
                **current,
                "report": {
                    "path": str(target.relative_to(context.root)),
                    "updated_at": utc_now_iso(),
                },
            },
        )
        return target


def _mark_step_started(state: dict[str, Any], step_id: str, tool: str) -> dict[str, Any]:
    steps = _coerce_steps(state)
    runs = _coerce_runs(state)
    steps[step_id] = {
        **steps.get(step_id, {}),
        "tool": tool,
        "status": "running",
        "started_at": utc_now_iso(),
    }
    return {
        **state,
        "status": "running",
        "steps": steps,
        "runs": runs,
    }


def _mark_step_finished(
    state: dict[str, Any],
    episode_id: str,
    step_id: str,
    tool: str,
    run_id: str,
    status: str,
    all_step_ids: list[str],
) -> dict[str, Any]:
    steps = _coerce_steps(state)
    runs = _coerce_runs(state)
    steps[step_id] = {
        **steps.get(step_id, {}),
        "tool": tool,
        "status": status,
        "run_id": run_id,
        "manifest_path": f"episodes/{episode_id}/runs/{run_id}/manifest.json",
        "updated_at": utc_now_iso(),
    }
    runs = [item for item in runs if item.get("run_id") != run_id]
    runs.append(
        {
            "run_id": run_id,
            "step_id": step_id,
            "tool": tool,
            "status": status,
            "manifest_path": steps[step_id]["manifest_path"],
        }
    )
    episode_status = "completed" if all(
        steps.get(candidate_step_id, {}).get("status") == "completed"
        for candidate_step_id in all_step_ids
    ) else ("failed" if status != "completed" else "running")
    return {
        **state,
        "status": episode_status,
        "steps": steps,
        "runs": runs,
    }


def _mark_step_failed(
    state: dict[str, Any],
    step_id: str,
    tool: str,
    error_message: str,
) -> dict[str, Any]:
    steps = _coerce_steps(state)
    runs = _coerce_runs(state)
    steps[step_id] = {
        **steps.get(step_id, {}),
        "tool": tool,
        "status": "failed",
        "error": error_message,
        "updated_at": utc_now_iso(),
    }
    return {
        **state,
        "status": "failed",
        "steps": steps,
        "runs": runs,
    }


def _coerce_steps(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = state.get("steps")
    if not isinstance(raw, dict):
        return {}
    return {str(key): dict(value) for key, value in raw.items() if isinstance(value, dict)}


def _coerce_runs(state: dict[str, Any]) -> list[dict[str, Any]]:
    raw = state.get("runs")
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]
