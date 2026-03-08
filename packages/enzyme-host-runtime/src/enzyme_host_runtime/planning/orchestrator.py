from __future__ import annotations

from typing import Any
from typing import TypedDict

from mcp_project_memory.models import utc_now_iso

from .adapters import AgentModelAdapter
from .adapters import HeuristicAgentAdapter
from .models import AgentAction
from .models import AgentInterrupt
from .models import AgentObservation
from .models import AgentState
from .models import DecisionTraceEntry
from .models import HumanFeedback
from .models import new_object_id
from .policy import ApprovalPolicy

try:
    from langgraph.graph import END
    from langgraph.graph import StateGraph
except ImportError:  # pragma: no cover
    END = None
    StateGraph = None


class WorkflowPayload(TypedDict, total=False):
    state: AgentState


class AgentWorkflowOrchestrator:
    def __init__(
        self,
        adapter: AgentModelAdapter | None = None,
        approval_policy: ApprovalPolicy | None = None,
    ) -> None:
        self.adapter = adapter or HeuristicAgentAdapter()
        self.approval_policy = approval_policy or ApprovalPolicy()
        self._graph = self._build_graph()

    @property
    def backend_name(self) -> str:
        return "langgraph" if self._graph is not None else "linear-fallback"

    def initialize(self, state: AgentState) -> AgentState:
        next_state = self._copy_state(state)
        if not next_state.design_contract.summary:
            next_state.design_contract = self.adapter.derive_design_contract(
                episode_id=next_state.episode_id,
                goal=next_state.objective,
                current_state=next_state,
            )
            next_state.decision_trace.append(
                self._trace("design_contract", "Derived design contract from episode objective.")
            )
        return self.continue_workflow(next_state)

    def continue_workflow(self, state: AgentState) -> AgentState:
        if state.termination_status == "completed":
            return self._stamp_session(state)
        if any(item.status == "pending" for item in state.pending_interrupts):
            state.status = "awaiting_feedback"
            return self._stamp_session(state)
        payload = {"state": state}
        if self._graph is not None:
            return self._graph.invoke(payload)["state"]
        return self._linear_decide(state)

    def apply_feedback(
        self,
        state: AgentState,
        *,
        interrupt_id: str,
        content: str,
        kind: str,
        actor: str,
    ) -> AgentState:
        feedback = HumanFeedback(
            feedback_id=new_object_id("feedback"),
            kind=kind,
            content=content,
            actor=actor,
            created_at=utc_now_iso(),
            interrupt_id=interrupt_id,
        )
        state.human_feedback.append(feedback)
        resolved_gate = False
        approved_gate = False
        for interrupt in state.pending_interrupts:
            if interrupt.interrupt_id == interrupt_id and interrupt.status == "pending":
                interrupt.status = "resolved"
                interrupt.resolved_at = utc_now_iso()
                interrupt.updated_at = interrupt.resolved_at
                interrupt.resolution = content
                if interrupt.gate_id:
                    resolved_gate = True
                    for gate in state.approval_gates:
                        if gate.gate_id == interrupt.gate_id and gate.status == "pending":
                            approved_gate = kind == "approval"
                            gate.status = "approved" if approved_gate else "rejected"
                            gate.resolved_by = actor
                            gate.resolved_at = utc_now_iso()
                break
        state.decision_trace.append(
            self._trace("feedback", f"Resolved interrupt {interrupt_id} with feedback kind={kind}.", refs=[feedback.feedback_id])
        )
        state.status = "idle"
        if resolved_gate and approved_gate:
            state.status = "awaiting_action"
            return self._stamp_session(state)
        return self.continue_workflow(state)

    def record_observation(self, state: AgentState, observation: AgentObservation) -> AgentState:
        state.observations.append(observation)
        summary = self.adapter.summarize_observation(state=state, observation=observation)
        state.decision_trace.append(self._trace("observation", summary, refs=[observation.observation_id]))
        state.selected_action = None
        state.candidate_actions = []
        state.status = "idle"
        return self.continue_workflow(state)

    def _build_graph(self) -> Any | None:
        if StateGraph is None:
            return None
        graph = StateGraph(WorkflowPayload)
        graph.add_node("decide_next_action", self._graph_decide_next_action)
        graph.add_node("apply_policy", self._graph_apply_policy)
        graph.add_node("materialize_interrupt", self._graph_materialize_interrupt)
        graph.add_node("finish", self._graph_finish)
        graph.set_entry_point("decide_next_action")
        graph.add_edge("decide_next_action", "apply_policy")
        graph.add_edge("apply_policy", "materialize_interrupt")
        graph.add_edge("materialize_interrupt", "finish")
        graph.add_edge("finish", END)
        return graph.compile()

    def _graph_decide_next_action(self, payload: WorkflowPayload) -> WorkflowPayload:
        return {"state": self._decide_next_action(payload["state"])}

    def _graph_apply_policy(self, payload: WorkflowPayload) -> WorkflowPayload:
        return {"state": self._apply_policy(payload["state"])}

    def _graph_materialize_interrupt(self, payload: WorkflowPayload) -> WorkflowPayload:
        return {"state": self._materialize_interrupt(payload["state"])}

    def _graph_finish(self, payload: WorkflowPayload) -> WorkflowPayload:
        return {"state": self._stamp_session(payload["state"])}

    def _linear_decide(self, state: AgentState) -> AgentState:
        return self._stamp_session(self._materialize_interrupt(self._apply_policy(self._decide_next_action(state))))

    def _decide_next_action(self, state: AgentState) -> AgentState:
        candidates = self.adapter.propose_candidate_actions(state=state)
        state.candidate_actions = candidates
        state.working_plan = self.adapter.build_working_plan(state=state, candidates=candidates)
        selected = self.adapter.select_action(state=state, candidates=candidates)
        self._supersede_stale_pending_items(state, selected)
        state.selected_action = selected
        state.status = "awaiting_action"
        state.decision_trace.append(
            self._trace("selected_action", f"Selected action `{selected.title}`.", refs=[selected.action_id])
        )
        if selected.kind == "complete":
            state.status = "completed"
            state.termination_status = "completed"
        return state

    def _apply_policy(self, state: AgentState) -> AgentState:
        action = state.selected_action
        if action is None or action.kind != "tool":
            return state
        for gate in state.approval_gates:
            if (
                gate.action_id == action.action_id
                and gate.action_revision == action.action_revision
                and gate.status in {"pending", "approved"}
            ):
                action.gate_id = gate.gate_id
                return state
        decision = self.approval_policy.evaluate(action)
        if decision is None:
            return state
        gate = self.approval_policy.build_gate(action, decision)
        gate.created_at = utc_now_iso()
        action.gate_id = gate.gate_id
        state.approval_gates.append(gate)
        state.decision_trace.append(
            self._trace("approval_gate", f"Created approval gate `{gate.gate_id}` for action `{action.action_id}`.", refs=[gate.gate_id, action.action_id])
        )
        return state

    def _materialize_interrupt(self, state: AgentState) -> AgentState:
        action = state.selected_action
        if action is None:
            return state
        if action.kind == "clarification":
            for interrupt in state.pending_interrupts:
                if (
                    interrupt.status == "pending"
                    and interrupt.kind == "clarification_request"
                    and interrupt.related_action_id == action.action_id
                ):
                    return state
            interrupt = self.adapter.build_clarification_interrupt(
                state=state,
                reason=action.rationale,
            )
            interrupt.related_action_id = action.action_id
            state.pending_interrupts.append(interrupt)
            state.status = "awaiting_feedback"
            state.decision_trace.append(
                self._trace("interrupt", f"Created clarification interrupt `{interrupt.interrupt_id}`.", refs=[interrupt.interrupt_id])
            )
            return state
        if action.gate_id and any(gate.gate_id == action.gate_id and gate.status == "pending" for gate in state.approval_gates):
            for interrupt in state.pending_interrupts:
                if (
                    interrupt.status == "pending"
                    and interrupt.kind == "approval_request"
                    and interrupt.gate_id == action.gate_id
                ):
                    return state
            interrupt = AgentInterrupt(
                interrupt_id=new_object_id("interrupt"),
                kind="approval_request",
                status="pending",
                title="Approval required",
                prompt=f"Approve action `{action.title}` before execution.",
                created_at=utc_now_iso(),
                related_action_id=action.action_id,
                gate_id=action.gate_id,
                updated_at=utc_now_iso(),
            )
            state.pending_interrupts.append(interrupt)
            state.status = "awaiting_feedback"
            state.decision_trace.append(
                self._trace("interrupt", f"Created approval interrupt `{interrupt.interrupt_id}`.", refs=[interrupt.interrupt_id, action.gate_id])
            )
        return state

    def _stamp_session(self, state: AgentState) -> AgentState:
        state.state_version += 1
        resume_token = new_object_id("resume")
        updated_at = utc_now_iso()
        state.session.active_state_version = state.state_version
        state.session.pending_interrupt_ids = [
            item.interrupt_id for item in state.pending_interrupts if item.status == "pending"
        ]
        state.session.last_selected_action_id = state.selected_action.action_id if state.selected_action else None
        state.session.last_observation_ids = [item.observation_id for item in state.observations[-3:]]
        state.session.awaiting_feedback = any(item.status == "pending" for item in state.pending_interrupts)
        state.session.resume_token = resume_token
        state.session.updated_at = updated_at
        for interrupt in state.pending_interrupts:
            if interrupt.status == "pending":
                interrupt.active_state_version = state.state_version
                interrupt.resume_token = resume_token
                interrupt.updated_at = updated_at
            elif interrupt.updated_at is None:
                interrupt.updated_at = updated_at
        return state

    def _supersede_stale_pending_items(self, state: AgentState, selected: AgentAction) -> None:
        stale_gate_ids: set[str] = set()
        superseded = False
        for gate in state.approval_gates:
            if gate.status != "pending":
                continue
            if gate.action_id == selected.action_id and gate.action_revision == selected.action_revision:
                continue
            gate.status = "superseded"
            gate.resolved_by = "agent"
            gate.resolved_at = utc_now_iso()
            stale_gate_ids.add(gate.gate_id)
            superseded = True
        for interrupt in state.pending_interrupts:
            if interrupt.status != "pending":
                continue
            if interrupt.gate_id and interrupt.gate_id not in stale_gate_ids:
                continue
            if interrupt.related_action_id and interrupt.related_action_id == selected.action_id and not interrupt.gate_id:
                continue
            interrupt.status = "superseded"
            interrupt.resolved_at = utc_now_iso()
            interrupt.updated_at = interrupt.resolved_at
            interrupt.resolution = "superseded by newer action selection"
            superseded = True
        if superseded:
            refs = list(stale_gate_ids) or ([selected.action_id] if selected.action_id else [])
            state.decision_trace.append(
                self._trace(
                    "supersede",
                    "Superseded pending approvals or interrupts tied to an older action.",
                    refs=refs,
                )
            )

    def _copy_state(self, state: AgentState) -> AgentState:
        return AgentState.from_dict(state.to_dict(), episode_id=state.episode_id, objective=state.objective)

    def _trace(self, kind: str, summary: str, refs: list[str] | None = None) -> DecisionTraceEntry:
        return DecisionTraceEntry(
            entry_id=new_object_id("trace"),
            kind=kind,
            summary=summary,
            created_at=utc_now_iso(),
            refs=list(refs or []),
        )
