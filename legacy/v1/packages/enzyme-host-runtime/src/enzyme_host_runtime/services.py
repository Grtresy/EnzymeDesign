from __future__ import annotations

import atexit
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import uuid

from mcp_project_memory.store import StaleStateError
from mcp_project_memory.models import utc_now_iso

from .agent_backend import LLMSidecarClient
from .agent_backend import load_agent_backend_config
from .capability import CapabilitySummary
from .capability import CapabilityVisibilityScope
from .capability import HostCapabilityGateway
from .capability import InspectedCapabilityBinding
from .capability import WorkflowAuditEvent
from .capability import capability_context_payload
from .capability import configured_capability_summaries
from .execution import RoutedExecutionAdapter
from .memory_client import MemoryClient
from .plan_runtime import PlanStep
from .plan_runtime import load_confirmed_plan
from .plan_runtime import load_plan_payload
from .plan_runtime import select_steps
from .planning import AgentAction
from .planning import AgentObservation
from .planning import AgentState
from .planning import AgentWorkflowOrchestrator
from .planning import ApprovalPolicy
from .planning import DecisionTraceEntry
from .planning import HeuristicAgentAdapter
from .planning import LLMAgentAdapter
from .reporting import build_report
from .reporting import report_path
from .workspace import ProjectContext
from .workspace import allocate_episode_id
from .workspace import list_episode_ids
from .workspace import init_project
from .workspace import load_project_context
from .workspace import load_project_config
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
    capability_summaries: list[dict[str, Any]]
    workflow_audit: list[dict[str, Any]]
    stop_reason: str
    next_step_suggestion: str
    needs_user_intervention: bool
    plain_language_explanation: str
    technical_explanation: str
    progress_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HostRuntime:
    def __init__(
        self,
        executor: RoutedExecutionAdapter | None = None,
        workflow: AgentWorkflowOrchestrator | None = None,
        capability_gateway: HostCapabilityGateway | None = None,
    ) -> None:
        self.executor = executor or RoutedExecutionAdapter()
        self.workflow = workflow
        self.capability_gateway = capability_gateway or HostCapabilityGateway(executor=self.executor)
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
        agent_state = self._prepare_agent_state(agent_state, selected_episode)
        updated = self._workflow_for_root(context.root).initialize(agent_state)
        memory.save_agent_state(selected_episode, updated)
        self._append_action_selected_event(
            memory,
            selected_episode,
            previous_action=agent_state.selected_action,
            current_action=updated.selected_action,
            state_version=updated.state_version,
        )
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
        agent_state = self._prepare_agent_state(agent_state, selected_episode)
        updated = self._workflow_for_root(context.root).continue_workflow(agent_state)
        memory.save_agent_state(
            selected_episode,
            updated,
            expected_state_version=expected_state_version,
        )
        self._append_action_selected_event(
            memory,
            selected_episode,
            previous_action=agent_state.selected_action,
            current_action=updated.selected_action,
            state_version=updated.state_version,
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
        agent_state = self._prepare_agent_state(agent_state, selected_episode)
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
        memory.append_workflow_event(
            selected_episode,
            self._workflow_event(
                "feedback_recorded",
                episode_id=selected_episode,
                state_version=updated.state_version,
                refs={"interrupt_id": interrupt_id},
                details={"kind": kind, "actor": actor},
            ),
        )
        if interrupt.gate_id:
            memory.append_workflow_event(
                selected_episode,
                self._workflow_event(
                    "gate_transitioned",
                    episode_id=selected_episode,
                    state_version=updated.state_version,
                    refs={"gate_id": interrupt.gate_id, "interrupt_id": interrupt_id},
                    details={"kind": kind, "actor": actor},
                ),
            )
        self._append_action_selected_event(
            memory,
            selected_episode,
            previous_action=agent_state.selected_action,
            current_action=updated.selected_action,
            state_version=updated.state_version,
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
        agent_state = self._prepare_agent_state(agent_state, selected_episode)
        agent_state = self._advance_capability_inspection(
            context.root,
            memory,
            selected_episode,
            agent_state,
        )
        action = agent_state.selected_action
        if action is None:
            raise ValueError("No executable tool action is currently selected.")
        if any(item.status == "pending" for item in agent_state.pending_interrupts):
            raise ValueError("Cannot execute while pending interrupts are unresolved.")
        if action.gate_id:
            gate = next((item for item in agent_state.approval_gates if item.gate_id == action.gate_id), None)
            if gate is None or gate.status != "approved":
                raise ValueError("Selected action requires an approved gate before execution.")
            if gate.action_id != action.action_id or gate.action_revision != action.action_revision:
                raise ValueError("Approved gate does not match the selected action revision.")
        if action.tool_action is None:
            raise ValueError("No executable tool action is currently selected.")
        capability_id = action.capability_id or self.capability_gateway.resolve_capability_for_tool(action.tool_action.tool) or "unknown"
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
        memory.append_workflow_event(
            selected_episode,
            self._workflow_event(
                "action_execution_started",
                episode_id=selected_episode,
                state_version=agent_state.state_version,
                refs={"action_id": action.action_id, "capability_id": capability_id, "tool": plan_step.tool},
            ),
        )
        try:
            normalized = self.capability_gateway.run_step(context.root, selected_episode, plan_step)
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
            memory.append_workflow_event(
                selected_episode,
                self._workflow_event(
                    "observation_recorded",
                    episode_id=selected_episode,
                    state_version=updated.state_version,
                    refs={"action_id": action.action_id, "capability_id": capability_id, "observation_id": observation.observation_id},
                    details={"status": "failed", "tool": plan_step.tool},
                ),
            )
            self._append_action_selected_event(
                memory,
                selected_episode,
                previous_action=agent_state.selected_action,
                current_action=updated.selected_action,
                state_version=updated.state_version,
            )
            raise
        result = normalized.to_execution_result()
        memory.write_run_manifest(selected_episode, result.run_id, result.manifest_payload)
        set_last_run(context.root, result.run_id)
        memory.append_workflow_event(
            selected_episode,
            self._workflow_event(
                "action_execution_finished",
                episode_id=selected_episode,
                state_version=agent_state.state_version,
                refs={
                    "action_id": action.action_id,
                    "capability_id": capability_id,
                    "run_id": result.run_id,
                    "tool": plan_step.tool,
                },
                details={"status": result.status},
            ),
        )
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
        memory.append_workflow_event(
            selected_episode,
            self._workflow_event(
                "observation_recorded",
                episode_id=selected_episode,
                state_version=updated.state_version,
                refs={
                    "action_id": action.action_id,
                    "capability_id": capability_id,
                    "run_id": result.run_id,
                    "observation_id": observation.observation_id,
                },
                details={"status": result.status, "tool": plan_step.tool},
            ),
        )
        self._append_action_selected_event(
            memory,
            selected_episode,
            previous_action=agent_state.selected_action,
            current_action=updated.selected_action,
            state_version=updated.state_version,
        )
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
        agent_state = self._prepare_agent_state(agent_state, episode_id)
        self._workflow_for_root(context.root)._refresh_decision_experience(agent_state)
        pending_interrupts = [item.to_dict() for item in agent_state.pending_interrupts if item.status == "pending"]
        agent_backend = dict(agent_state.meta.get("backend_status") or {})
        if not agent_backend:
            agent_backend = _configured_backend_status(context.root)
        capability_summaries = [item.to_dict() for item in configured_capability_summaries(agent_state.meta)]
        workflow_audit = memory.load_workflow_audit(episode_id)
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
                "workflow_event_count": len(workflow_audit),
            },
            agent_backend=agent_backend,
            capability_summaries=capability_summaries,
            workflow_audit=workflow_audit[-12:],
            stop_reason=agent_state.stop_reason,
            next_step_suggestion=agent_state.next_step_suggestion,
            needs_user_intervention=agent_state.needs_user_intervention,
            plain_language_explanation=agent_state.plain_language_explanation,
            technical_explanation=agent_state.technical_explanation,
            progress_summary=agent_state.progress_summary.to_dict(),
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

    def list_capability_summaries(
        self,
        start: Path,
        *,
        episode_id: str | None = None,
    ) -> list[dict[str, Any]]:
        context, memory, selected_episode, goal = self._context_for_episode(start, episode_id)
        agent_state = memory.load_agent_state(selected_episode, objective=goal)
        agent_state = self._prepare_agent_state(agent_state, selected_episode)
        return [item.to_dict() for item in configured_capability_summaries(agent_state.meta)]

    def inspect_capability(
        self,
        start: Path,
        capability_id: str,
        *,
        episode_id: str | None = None,
    ) -> dict[str, Any]:
        _context, memory, selected_episode, goal = self._context_for_episode(start, episode_id)
        agent_state = memory.load_agent_state(selected_episode, objective=goal)
        agent_state = self._prepare_agent_state(agent_state, selected_episode)
        detail = self.capability_gateway.inspect(capability_id)
        binding = InspectedCapabilityBinding(
            contract=detail,
            scope=CapabilityVisibilityScope(
                episode_id=selected_episode,
                active_state_version=agent_state.state_version,
                role="host-agent",
            ),
            inspected_at=utc_now_iso(),
        )
        updated_state = self._add_inspected_capability(agent_state, binding)
        memory.save_agent_state(selected_episode, updated_state)
        memory.append_workflow_event(
            selected_episode,
            self._workflow_event(
                "capability_inspected",
                episode_id=selected_episode,
                state_version=updated_state.state_version,
                refs={"capability_id": capability_id},
                details={"role": "host-agent", "server_name": detail.server_name},
            ),
        )
        return detail.to_dict()

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
        project_config = load_project_config(root)
        if backend_config.backend == "llm-sidecar":
            adapter = LLMAgentAdapter(
                client=self._sidecar_client(backend_config),
                config=backend_config.llm_sidecar,
            )
        else:
            adapter = HeuristicAgentAdapter()
        return AgentWorkflowOrchestrator(
            adapter=adapter,
            approval_policy=ApprovalPolicy(config=project_config.host.trust_policy),
            max_decision_rounds=project_config.host.workflow_budget.max_decision_rounds,
            max_auto_actions=project_config.host.workflow_budget.max_auto_actions,
        )

    def _prepare_agent_state(self, state: AgentState, episode_id: str) -> AgentState:
        summaries = self.capability_gateway.list_summaries()
        bindings = _load_inspected_bindings(state.meta)
        state.meta = {
            **state.meta,
            **capability_context_payload(summaries, bindings),
        }
        return state

    def _advance_capability_inspection(
        self,
        project_root: Path,
        memory: MemoryClient,
        episode_id: str,
        state: AgentState,
    ) -> AgentState:
        while state.selected_action and state.selected_action.kind == "inspect_capability":
            action = state.selected_action
            if not action.capability_id:
                raise ValueError("Selected inspect action is missing capability_id.")
            detail = self.capability_gateway.inspect(action.capability_id)
            binding = InspectedCapabilityBinding(
                contract=detail,
                scope=CapabilityVisibilityScope(
                    episode_id=episode_id,
                    active_state_version=state.state_version,
                    role="host-agent",
                ),
                inspected_at=utc_now_iso(),
            )
            state = self._add_inspected_capability(state, binding)
            state.decision_trace.append(
                DecisionTraceEntry(
                    entry_id=_new_event_id("trace"),
                    kind="capability_inspected",
                    summary=f"Inspected capability `{detail.capability_id}` before selecting a concrete tool.",
                    created_at=utc_now_iso(),
                    refs=[detail.capability_id],
                    meta={"role": "host-agent"},
                )
            )
            memory.append_workflow_event(
                episode_id,
                self._workflow_event(
                    "capability_inspected",
                    episode_id=episode_id,
                    state_version=state.state_version,
                    refs={"capability_id": detail.capability_id},
                    details={"role": "host-agent", "server_name": detail.server_name},
                ),
            )
            state.selected_action = None
            state.candidate_actions = []
            state.status = "idle"
            state = self._workflow_for_root(project_root).continue_workflow(state)
            memory.save_agent_state(episode_id, state)
            self._append_action_selected_event(
                memory,
                episode_id,
                previous_action=action,
                current_action=state.selected_action,
                state_version=state.state_version,
            )
        return state

    def _add_inspected_capability(
        self,
        state: AgentState,
        binding: InspectedCapabilityBinding,
    ) -> AgentState:
        bindings = _load_inspected_bindings(state.meta)
        bindings = [
            item
            for item in bindings
            if not (
                item.contract.capability_id == binding.contract.capability_id
                and item.scope.episode_id == binding.scope.episode_id
                and item.scope.active_state_version == binding.scope.active_state_version
                and item.scope.role == binding.scope.role
            )
        ]
        bindings.append(binding)
        state.meta = {
            **state.meta,
            **capability_context_payload(
                self.capability_gateway.list_summaries(),
                bindings,
            ),
        }
        return state

    def _workflow_event(
        self,
        event_type: str,
        *,
        episode_id: str,
        state_version: int,
        refs: dict[str, str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> WorkflowAuditEvent:
        return WorkflowAuditEvent(
            event_id=_new_event_id("workflow-event"),
            event_type=event_type,
            episode_id=episode_id,
            state_version=state_version,
            timestamp=utc_now_iso(),
            refs=dict(refs or {}),
            details=dict(details or {}),
        )

    def _append_action_selected_event(
        self,
        memory: MemoryClient,
        episode_id: str,
        *,
        previous_action: AgentAction | None,
        current_action: AgentAction | None,
        state_version: int,
    ) -> None:
        if current_action is None:
            return
        if (
            previous_action is not None
            and previous_action.action_id == current_action.action_id
            and previous_action.action_revision == current_action.action_revision
        ):
            return
        refs = {"action_id": current_action.action_id}
        if current_action.capability_id:
            refs["capability_id"] = current_action.capability_id
        if current_action.tool_action is not None:
            refs["tool"] = current_action.tool_action.tool
        if current_action.gate_id:
            refs["gate_id"] = current_action.gate_id
        memory.append_workflow_event(
            episode_id,
            self._workflow_event(
                "action_selected",
                episode_id=episode_id,
                state_version=state_version,
                refs=refs,
                details={
                    "kind": current_action.kind,
                    "title": current_action.title,
                    "action_revision": current_action.action_revision,
                },
            ),
        )

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


def _load_inspected_bindings(meta: dict[str, Any]) -> list[InspectedCapabilityBinding]:
    return [
        InspectedCapabilityBinding.from_dict(item)
        for item in meta.get("inspected_capabilities") or []
        if isinstance(item, dict)
    ]


def _new_event_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
