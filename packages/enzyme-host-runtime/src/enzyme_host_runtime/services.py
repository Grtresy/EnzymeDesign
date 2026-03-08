from __future__ import annotations

import atexit
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_project_memory.store import StaleStateError
from mcp_project_memory.models import utc_now_iso

from .agent_backend import LLMSidecarClient
from .agent_backend import load_agent_backend_config
from .execution import RoutedExecutionAdapter
from .memory_client import MemoryClient
from .plan_runtime import PlanStep
from .plan_runtime import load_confirmed_plan
from .plan_runtime import load_plan_payload
from .plan_runtime import select_steps
from .planning import AgentObservation
from .planning import AgentState
from .planning import AgentWorkflowOrchestrator
from .planning import HeuristicAgentAdapter
from .planning import LLMAgentAdapter
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
    agent_state: dict[str, Any]
    pending_interrupts: list[dict[str, Any]]
    approval_gates: list[dict[str, Any]]
    planning_history: list[dict[str, Any]]
    execution_evidence: dict[str, Any]
    agent_backend: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HostRuntime:
    def __init__(
        self,
        executor: RoutedExecutionAdapter | None = None,
        workflow: AgentWorkflowOrchestrator | None = None,
    ) -> None:
        self.executor = executor or RoutedExecutionAdapter()
        self.workflow = workflow
        self._sidecar_clients: dict[tuple[str, tuple[str, ...], str], LLMSidecarClient] = {}
        atexit.register(self.close)

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
        return memory.confirm_plan(
            selected_episode,
            plan,
            source_path=plan_file,
            imported_at=imported_at,
        )

    def start_agent_workflow(self, start: Path, *, episode_id: str | None = None) -> EpisodeSnapshot:
        context, memory, selected_episode, goal = self._context_for_episode(start, episode_id)
        agent_state = memory.load_agent_state(selected_episode, objective=goal)
        updated = self._workflow_for_root(context.root).initialize(agent_state)
        memory.save_agent_state(selected_episode, updated)
        return self.get_episode_snapshot(context, memory, selected_episode)

    def continue_agent_workflow(
        self,
        start: Path,
        *,
        episode_id: str | None = None,
        expected_state_version: int | None = None,
        resume_token: str | None = None,
    ) -> EpisodeSnapshot:
        context, memory, selected_episode, goal = self._context_for_episode(start, episode_id)
        if expected_state_version is not None or resume_token is not None:
            self._consume_resume_token(
                memory,
                selected_episode,
                expected_state_version=expected_state_version,
                resume_token=resume_token,
            )
        agent_state = memory.load_agent_state(selected_episode, objective=goal)
        updated = self._workflow_for_root(context.root).continue_workflow(agent_state)
        memory.save_agent_state(
            selected_episode,
            updated,
            expected_state_version=expected_state_version,
        )
        return self.get_episode_snapshot(context, memory, selected_episode)

    def submit_feedback(
        self,
        start: Path,
        *,
        interrupt_id: str,
        content: str,
        kind: str = "comment",
        actor: str = "host-user",
        episode_id: str | None = None,
        expected_state_version: int | None = None,
        resume_token: str | None = None,
    ) -> EpisodeSnapshot:
        context, memory, selected_episode, goal = self._context_for_episode(start, episode_id)
        agent_state = memory.load_agent_state(selected_episode, objective=goal)
        if expected_state_version is not None or resume_token is not None:
            if (
                agent_state.session.active_state_version != expected_state_version
                or agent_state.session.resume_token != resume_token
            ):
                raise StaleStateError(
                    f"Stale workflow state for {selected_episode}: expected version {expected_state_version} token {resume_token}."
                )
        interrupt = self._require_pending_interrupt(agent_state, interrupt_id)
        if expected_state_version is not None or resume_token is not None:
            self._consume_resume_token(
                memory,
                selected_episode,
                expected_state_version=expected_state_version or interrupt.active_state_version,
                resume_token=resume_token or interrupt.resume_token,
            )
        updated = self._workflow_for_root(context.root).apply_feedback(
            agent_state,
            interrupt_id=interrupt_id,
            content=content,
            kind=kind,
            actor=actor,
        )
        memory.save_agent_state(
            selected_episode,
            updated,
            expected_state_version=expected_state_version or interrupt.active_state_version,
        )
        return self.get_episode_snapshot(context, memory, selected_episode)

    def approve_gate(
        self,
        start: Path,
        *,
        gate_id: str,
        actor: str = "host-user",
        episode_id: str | None = None,
        expected_state_version: int | None = None,
        resume_token: str | None = None,
    ) -> EpisodeSnapshot:
        interrupt_id = self._interrupt_for_gate(start, gate_id, episode_id=episode_id)
        return self.submit_feedback(
            start,
            episode_id=episode_id,
            interrupt_id=interrupt_id,
            content="approved",
            kind="approval",
            actor=actor,
            expected_state_version=expected_state_version,
            resume_token=resume_token,
        )

    def reject_gate(
        self,
        start: Path,
        *,
        gate_id: str,
        actor: str = "host-user",
        episode_id: str | None = None,
        expected_state_version: int | None = None,
        resume_token: str | None = None,
    ) -> EpisodeSnapshot:
        interrupt_id = self._interrupt_for_gate(start, gate_id, episode_id=episode_id)
        return self.submit_feedback(
            start,
            episode_id=episode_id,
            interrupt_id=interrupt_id,
            content="rejected",
            kind="rejection",
            actor=actor,
            expected_state_version=expected_state_version,
            resume_token=resume_token,
        )

    def execute_selected_action(
        self,
        start: Path,
        *,
        episode_id: str | None = None,
    ) -> EpisodeSnapshot:
        context, memory, selected_episode, goal = self._context_for_episode(start, episode_id)
        agent_state = memory.load_agent_state(selected_episode, objective=goal)
        action = agent_state.selected_action
        if action is None or action.tool_action is None:
            raise ValueError("No executable tool action is currently selected.")
        if any(item.status == "pending" for item in agent_state.pending_interrupts):
            raise ValueError("Cannot execute while pending interrupts are unresolved.")
        if action.gate_id:
            gate = next((item for item in agent_state.approval_gates if item.gate_id == action.gate_id), None)
            if gate is None or gate.status != "approved":
                raise ValueError("Selected action requires an approved gate before execution.")
            if gate.action_id != action.action_id or gate.action_revision != action.action_revision:
                raise ValueError("Approved gate does not match the selected action revision.")
        plan_step = PlanStep(
            step_id=action.action_id,
            tool=action.tool_action.tool,
            payload={
                "id": action.action_id,
                "tool": action.tool_action.tool,
                "inputs": action.tool_action.inputs,
            },
        )
        memory.update_state(
            selected_episode,
            lambda current: _mark_step_started(current, plan_step.step_id, plan_step.tool),
        )
        try:
            result = self.executor.run_step(context.root, selected_episode, plan_step)
        except Exception as exc:
            memory.update_state(
                selected_episode,
                lambda current: _mark_step_failed(current, plan_step.step_id, plan_step.tool, str(exc)),
            )
            observation = AgentObservation(
                observation_id=f"obs-{plan_step.step_id}",
                source="tool",
                summary=str(exc),
                created_at=utc_now_iso(),
                payload={"status": "failed", "tool": plan_step.tool, "error": str(exc)},
            )
            updated = self._workflow_for_root(context.root).record_observation(agent_state, observation)
            memory.save_agent_state(selected_episode, updated)
            raise
        memory.write_run_manifest(selected_episode, result.run_id, result.manifest_payload)
        set_last_run(context.root, result.run_id)
        state = memory.update_state(
            selected_episode,
            lambda current: _mark_step_finished(
                current,
                selected_episode,
                plan_step.step_id,
                plan_step.tool,
                result.run_id,
                result.status,
                [plan_step.step_id],
            ),
        )
        observation = AgentObservation(
            observation_id=f"obs-{result.run_id}",
            source="tool",
            summary=f"{plan_step.tool} finished with status {result.status}",
            created_at=utc_now_iso(),
            payload={"status": result.status, "tool": plan_step.tool},
            run_id=result.run_id,
            manifest_path=f"episodes/{selected_episode}/runs/{result.run_id}/manifest.json",
        )
        updated = self._workflow_for_root(context.root).record_observation(agent_state, observation)
        memory.save_agent_state(selected_episode, updated)
        return self.get_episode_snapshot(context, memory, selected_episode)

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
            raise RuntimeError(f"Unsupported execution tool(s): {', '.join(unsupported_tools)}")

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
                    lambda current: _mark_step_failed(current, step.step_id, step.tool, str(exc)),
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
        agent_state = memory.load_agent_state(episode_id, objective=goal)
        pending_interrupts = [item.to_dict() for item in agent_state.pending_interrupts if item.status == "pending"]
        agent_backend = dict(agent_state.meta.get("backend_status") or {})
        if not agent_backend:
            agent_backend = _configured_backend_status(context.root)
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
            agent_state=agent_state.to_dict(),
            pending_interrupts=pending_interrupts,
            approval_gates=[item.to_dict() for item in agent_state.approval_gates],
            planning_history=[],
            execution_evidence={
                "observation_count": len(agent_state.observations),
                "latest_observation_id": agent_state.observations[-1].observation_id if agent_state.observations else None,
                "termination_status": agent_state.termination_status,
            },
            agent_backend=agent_backend,
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
                "report": {"path": str(target.relative_to(context.root)), "updated_at": utc_now_iso()},
            },
        )
        return target

    def _context_for_episode(
        self,
        start: Path,
        episode_id: str | None,
    ) -> tuple[ProjectContext, MemoryClient, str, str]:
        context = self.load_project(start)
        memory = MemoryClient(context)
        selected_episode = resolve_episode_id(context.root, episode_id)
        goal = memory.load_goal(selected_episode)
        return context, memory, selected_episode, goal

    def _interrupt_for_gate(self, start: Path, gate_id: str, *, episode_id: str | None) -> str:
        context, memory, selected_episode, goal = self._context_for_episode(start, episode_id)
        agent_state = memory.load_agent_state(selected_episode, objective=goal)
        for interrupt in agent_state.pending_interrupts:
            if interrupt.gate_id == gate_id and interrupt.status == "pending":
                return interrupt.interrupt_id
        raise ValueError(f"No pending interrupt found for gate {gate_id}")

    def _require_pending_interrupt(self, agent_state: AgentState, interrupt_id: str):
        for interrupt in agent_state.pending_interrupts:
            if interrupt.interrupt_id == interrupt_id and interrupt.status == "pending":
                return interrupt
        raise ValueError(f"No pending interrupt found for {interrupt_id}")

    def _consume_resume_token(
        self,
        memory: MemoryClient,
        episode_id: str,
        *,
        expected_state_version: int | None,
        resume_token: str | None,
    ) -> None:
        if expected_state_version is None or resume_token is None:
            raise ValueError("Both expected_state_version and resume_token are required for versioned resume.")
        memory.consume_resume_token(
            episode_id,
            state_version=expected_state_version,
            resume_token=resume_token,
        )

    def close(self) -> None:
        for client in self._sidecar_clients.values():
            client.close()
        self._sidecar_clients.clear()

    def _workflow_for_root(self, root: Path) -> AgentWorkflowOrchestrator:
        if self.workflow is not None:
            return self.workflow
        backend_config = load_agent_backend_config(root)
        if backend_config.backend == "llm-sidecar":
            adapter = LLMAgentAdapter(
                client=self._sidecar_client(backend_config),
                config=backend_config.llm_sidecar,
            )
        else:
            adapter = HeuristicAgentAdapter()
        return AgentWorkflowOrchestrator(adapter=adapter)

    def _sidecar_client(self, backend_config) -> LLMSidecarClient:
        sidecar_config = backend_config.llm_sidecar
        key = (sidecar_config.config_path, sidecar_config.command, sidecar_config.cwd)
        client = self._sidecar_clients.get(key)
        if client is None:
            client = LLMSidecarClient(sidecar_config)
            self._sidecar_clients[key] = client
        return client


def _mark_step_started(state: dict[str, Any], step_id: str, tool: str) -> dict[str, Any]:
    steps = _coerce_steps(state)
    runs = _coerce_runs(state)
    steps[step_id] = {
        **steps.get(step_id, {}),
        "tool": tool,
        "status": "running",
        "started_at": utc_now_iso(),
    }
    return {**state, "status": "running", "steps": steps, "runs": runs}


def _configured_backend_status(project_root: Path) -> dict[str, Any]:
    config = load_agent_backend_config(project_root)
    if config.backend == "llm-sidecar":
        return {
            "adapter": "llm-agent-adapter",
            "backend": "llm-sidecar",
            "provider": config.llm_sidecar.provider,
            "model": config.llm_sidecar.model,
            "sidecar": {},
            "degraded": False,
            "fallback_used": False,
            "fallback_backend": None,
            "last_error_summary": None,
        }
    return HeuristicAgentAdapter().current_backend_status()


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
    return {**state, "status": episode_status, "steps": steps, "runs": runs}


def _mark_step_failed(state: dict[str, Any], step_id: str, tool: str, error_message: str) -> dict[str, Any]:
    steps = _coerce_steps(state)
    runs = _coerce_runs(state)
    steps[step_id] = {
        **steps.get(step_id, {}),
        "tool": tool,
        "status": "failed",
        "error": error_message,
        "updated_at": utc_now_iso(),
    }
    return {**state, "status": "failed", "steps": steps, "runs": runs}


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
