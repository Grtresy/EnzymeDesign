from __future__ import annotations

from typing import Any
from typing import TypedDict

from mcp_project_memory.models import utc_now_iso

from .adapters import AgentModelAdapter
from .adapters import AgentBackendBlockedError
from .adapters import HeuristicAgentAdapter
from .models import AgentAction
from .models import AgentInterrupt
from .models import AgentObservation
from .models import AgentState
from .models import DecisionTraceEntry
from .models import HumanFeedback
from .models import ProgressSummary
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
        *,
        max_decision_rounds: int = 6,
        max_auto_actions: int = 3,
    ) -> None:
        self.adapter = adapter or HeuristicAgentAdapter()
        self.approval_policy = approval_policy or ApprovalPolicy()
        self.max_decision_rounds = max_decision_rounds
        self.max_auto_actions = max_auto_actions
        self._graph = self._build_graph()

    @property
    def backend_name(self) -> str:
        return "langgraph" if self._graph is not None else "linear-fallback"

    def initialize(self, state: AgentState) -> AgentState:
        next_state = self._copy_state(state)
        if not next_state.design_contract.summary:
            try:
                next_state.design_contract = self.adapter.derive_design_contract(
                    episode_id=next_state.episode_id,
                    goal=next_state.objective,
                    current_state=next_state,
                )
            except AgentBackendBlockedError as exc:
                return self._stamp_session(self._block_state(next_state, exc))
            next_state.decision_trace.append(
                self._trace(
                    "design_contract",
                    "Derived design contract from episode objective.",
                    meta=self._artifact_meta(next_state.design_contract),
                )
            )
            self._capture_backend_status(next_state)
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
        # Treat explicit human feedback as a new recovery attempt instead of
        # carrying stale failed-observation streaks into the next planning loop.
        state.meta["consecutive_failed_observations"] = 0
        state.session.decision_rounds = 0
        state.session.auto_action_count = 0
        state.status = "idle"
        if resolved_gate and approved_gate:
            state.status = "awaiting_action"
            return self._stamp_session(state)
        if resolved_gate:
            state.status = "blocked"
            state.termination_status = "blocked"
            state.selected_action = None
            state.candidate_actions = []
            state.decision_trace.append(
                self._trace(
                    "gate_rejected",
                    "Stopped after the user rejected the pending approval gate.",
                    refs=[interrupt_id],
                )
            )
            return self._stamp_session(state)
        return self.continue_workflow(state)

    def record_observation(self, state: AgentState, observation: AgentObservation) -> AgentState:
        state.observations.append(observation)
        try:
            summary = self.adapter.summarize_observation(state=state, observation=observation)
        except AgentBackendBlockedError as exc:
            blocked = self._block_state(state, exc, refs=[observation.observation_id])
            return self._stamp_session(blocked)
        self._capture_backend_status(state)
        state.decision_trace.append(
            self._trace(
                "observation",
                summary,
                refs=[observation.observation_id],
                meta=self._current_backend_status(),
            )
        )
        if str(observation.payload.get("status") or "") == "failed":
            state.meta["consecutive_failed_observations"] = int(state.meta.get("consecutive_failed_observations") or 0) + 1
        else:
            state.meta["consecutive_failed_observations"] = 0
        state.session.decision_rounds = 0
        state.session.auto_action_count = 0
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
        if self._decision_budget_exhausted(state):
            return self._max_turns_exceeded_state(state)
        if self._should_escalate(state):
            return self._escalate_state(state)
        try:
            candidates = self.adapter.propose_candidate_actions(state=state)
        except AgentBackendBlockedError as exc:
            return self._block_state(state, exc)
        state.candidate_actions = candidates
        try:
            state.working_plan = self.adapter.build_working_plan(state=state, candidates=candidates)
            selected = self.adapter.select_action(state=state, candidates=candidates)
        except AgentBackendBlockedError as exc:
            state.candidate_actions = []
            state.selected_action = None
            return self._block_state(state, exc)
        self._capture_backend_status(state)
        self._supersede_stale_pending_items(state, selected)
        self._describe_selected_action(selected)
        state.selected_action = selected
        state.status = "awaiting_action"
        state.session.decision_rounds += 1
        state.session.auto_action_count += 1
        state.decision_trace.append(
            self._trace(
                "selected_action",
                f"Selected action `{selected.title}`.",
                refs=[selected.action_id],
                meta=self._artifact_meta(selected),
            )
        )
        if selected.kind == "complete":
            state.status = "completed"
            state.termination_status = "completed"
        return state

    def _apply_policy(self, state: AgentState) -> AgentState:
        action = state.selected_action
        if action is None or action.kind != "tool":
            return state
        decision = self.approval_policy.evaluate(action)
        if decision is None:
            return state
        action.trust_decision = decision.trust_decision
        action.policy_reason = decision.policy_reason
        action.policy_summary = decision.plain_language_reason
        action.policy_rule_id = decision.rule_id
        action.policy_scope = decision.policy_scope
        for gate in state.approval_gates:
            if (
                gate.action_id == action.action_id
                and gate.action_revision == action.action_revision
                and gate.status in {"pending", "approved"}
            ):
                action.gate_id = gate.gate_id
                return state
        if decision.decision == "allow":
            return state
        if decision.decision == "block":
            return self._policy_block_state(state, action, decision)
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
            try:
                interrupt = self.adapter.build_clarification_interrupt(
                    state=state,
                    reason=action.rationale,
                )
            except AgentBackendBlockedError as exc:
                return self._block_state(state, exc, refs=[action.action_id])
            interrupt.related_action_id = action.action_id
            interrupt.plain_language_explanation = interrupt.plain_language_explanation or "系统需要你补充信息后，才能继续判断下一步。"
            interrupt.technical_explanation = (
                interrupt.technical_explanation or f"Clarification interrupt created for action `{action.action_id}`."
            )
            interrupt.suggested_user_action = interrupt.suggested_user_action or "直接回答系统问题，或修改目标约束后再继续。"
            self._capture_backend_status(state)
            state.pending_interrupts.append(interrupt)
            state.status = "awaiting_feedback"
            state.decision_trace.append(
                self._trace(
                    "interrupt",
                    f"Created clarification interrupt `{interrupt.interrupt_id}`.",
                    refs=[interrupt.interrupt_id],
                    meta=self._current_backend_status(),
                )
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
                plain_language_explanation=action.policy_summary or "系统在等待你确认后再继续这个动作。",
                technical_explanation=action.policy_reason or f"Pending approval gate for action `{action.action_id}`.",
                suggested_user_action="审批、拒绝，或修改约束后重新规划。",
            )
            state.pending_interrupts.append(interrupt)
            state.status = "awaiting_feedback"
            state.decision_trace.append(
                self._trace("interrupt", f"Created approval interrupt `{interrupt.interrupt_id}`.", refs=[interrupt.interrupt_id, action.gate_id])
            )
        return state

    def _stamp_session(self, state: AgentState) -> AgentState:
        self._refresh_decision_experience(state)
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

    def _trace(
        self,
        kind: str,
        summary: str,
        refs: list[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> DecisionTraceEntry:
        return DecisionTraceEntry(
            entry_id=new_object_id("trace"),
            kind=kind,
            summary=summary,
            created_at=utc_now_iso(),
            refs=list(refs or []),
            meta=dict(meta or {}),
        )

    def _block_state(
        self,
        state: AgentState,
        exc: AgentBackendBlockedError,
        refs: list[str] | None = None,
    ) -> AgentState:
        state.status = "blocked"
        state.termination_status = "blocked"
        state.selected_action = None
        state.candidate_actions = []
        state.meta["backend_status"] = dict(exc.backend_status)
        state.decision_trace.append(
            self._trace(
                "backend_error",
                f"{exc.operation} blocked: {exc.summary}",
                refs=refs,
                meta=exc.backend_status,
            )
        )
        return state

    def _decision_budget_exhausted(self, state: AgentState) -> bool:
        return (
            state.session.decision_rounds >= self.max_decision_rounds
            or state.session.auto_action_count >= self.max_auto_actions
        )

    def _should_escalate(self, state: AgentState) -> bool:
        return int(state.meta.get("consecutive_failed_observations") or 0) >= 2

    def _describe_selected_action(self, action: AgentAction) -> None:
        tool_name = action.tool_action.tool if action.tool_action else None
        if action.kind == "tool":
            action.plain_language_explanation = f"系统准备执行“{action.title}”，因为这一步最直接地推进当前目标。"
            action.technical_explanation = (
                f"Selected tool action `{tool_name or action.title}` with rationale: {action.rationale or 'none'}."
            )
            return
        if action.kind == "inspect_capability":
            action.plain_language_explanation = f"系统先检查能力“{action.title}”，确认接下来该调用哪类工具。"
            action.technical_explanation = (
                f"Inspect capability `{action.capability_id or action.title}` before materializing a concrete tool action."
            )
            return
        if action.kind == "clarification":
            action.plain_language_explanation = "系统现在缺少继续执行所需的信息，先请求你补充说明。"
            action.technical_explanation = f"Clarification required because: {action.rationale or 'unspecified'}."
            return
        if action.kind == "complete":
            action.plain_language_explanation = "系统判断当前目标已经达到可交付状态。"
            action.technical_explanation = f"Workflow marked complete because: {action.rationale or 'goal satisfied'}."

    def _policy_block_state(self, state: AgentState, action: AgentAction, decision) -> AgentState:
        state.status = "blocked"
        state.termination_status = "blocked"
        state.selected_action = None
        state.candidate_actions = []
        state.meta["policy_block"] = {
            "action_id": action.action_id,
            "action_title": action.title,
            "policy_reason": decision.policy_reason,
            "plain_language_reason": decision.plain_language_reason,
            "trust_decision": decision.trust_decision,
            "rule_id": decision.rule_id,
            "scope": decision.policy_scope,
        }
        state.decision_trace.append(
            self._trace(
                "policy_block",
                f"Blocked action `{action.title}` by trust policy.",
                refs=[action.action_id],
                meta=state.meta["policy_block"],
            )
        )
        return state

    def _max_turns_exceeded_state(self, state: AgentState) -> AgentState:
        rounds = state.session.decision_rounds
        state.status = "idle"
        state.termination_status = "max_turns_exceeded"
        state.selected_action = None
        state.candidate_actions = []
        state.meta["max_turns_exceeded"] = {
            "decision_rounds": rounds,
            "limit": self.max_decision_rounds,
            "auto_action_count": state.session.auto_action_count,
            "auto_action_limit": self.max_auto_actions,
        }
        state.decision_trace.append(
            self._trace(
                "max_turns_exceeded",
                f"Paused after {rounds} automatic decision rounds without a stable resolution.",
                meta=state.meta["max_turns_exceeded"],
            )
        )
        return state

    def _escalate_state(self, state: AgentState) -> AgentState:
        failures = int(state.meta.get("consecutive_failed_observations") or 0)
        state.status = "blocked"
        state.termination_status = "escalated"
        state.selected_action = None
        state.candidate_actions = []
        state.meta["escalation"] = {
            "reason": "Repeated failed observations left the workflow without a reliable next action.",
            "failed_observation_count": failures,
        }
        state.decision_trace.append(
            self._trace(
                "escalated",
                "Escalated to a human after repeated failed observations.",
                meta=state.meta["escalation"],
            )
        )
        return state

    def _refresh_decision_experience(self, state: AgentState) -> None:
        stop_reason = self._stop_reason(state)
        current_focus = self._current_focus(state, stop_reason)
        waiting_on = self._waiting_on(state, stop_reason)
        next_step = self._next_step(state, stop_reason)
        needs_user_intervention = stop_reason in {
            "needs_input",
            "awaiting_approval",
            "blocked",
            "max_turns_exceeded",
            "escalated",
        }
        recent_completed = self._recent_completed(state)
        plain_language = self._plain_language_explanation(state, stop_reason)
        technical = self._technical_explanation(state, stop_reason)
        state.stop_reason = stop_reason
        state.next_step_suggestion = next_step
        state.needs_user_intervention = needs_user_intervention
        state.plain_language_explanation = plain_language
        state.technical_explanation = technical
        state.progress_summary = ProgressSummary(
            current_focus=current_focus,
            recent_completed=recent_completed,
            current_blocker=self._current_blocker(state, stop_reason),
            waiting_on=waiting_on,
            next_step=next_step,
            needs_user_intervention=needs_user_intervention,
        )
        if stop_reason in {"completed", "failed", "blocked", "max_turns_exceeded", "escalated"}:
            state.termination_status = stop_reason
        elif state.termination_status not in {"completed", "failed"}:
            state.termination_status = "active"

    def _stop_reason(self, state: AgentState) -> str:
        if state.termination_status == "completed" or state.status == "completed":
            return "completed"
        if state.termination_status == "failed" or state.status == "failed":
            return "failed"
        if any(item.status == "pending" and item.kind == "approval_request" for item in state.pending_interrupts):
            return "awaiting_approval"
        if any(item.status == "pending" for item in state.pending_interrupts):
            return "needs_input"
        if state.termination_status == "max_turns_exceeded":
            return "max_turns_exceeded"
        if state.termination_status == "escalated":
            return "escalated"
        if state.status == "blocked" or state.termination_status == "blocked":
            return "blocked"
        return "active"

    def _current_focus(self, state: AgentState, stop_reason: str) -> str:
        if stop_reason == "completed":
            return "当前目标已经完成。"
        if stop_reason == "awaiting_approval":
            gate = self._pending_gate(state)
            if gate is not None:
                return f"系统正在等待你审批动作“{gate.action_snapshot.get('title', gate.action_id)}”。"
            return "系统正在等待审批。"
        if stop_reason == "needs_input":
            interrupt = self._pending_interrupt(state)
            if interrupt is not None:
                return interrupt.title or "系统正在等待你补充输入。"
            return "系统正在等待你补充输入。"
        if stop_reason == "max_turns_exceeded":
            return "自动推进预算已经耗尽。"
        if stop_reason == "escalated":
            return "系统建议转为人工接管。"
        if stop_reason == "blocked":
            return "系统目前被策略或后端问题阻断。"
        if state.selected_action is not None:
            return f"当前准备执行：{state.selected_action.title}"
        return "系统正在准备下一步。"

    def _waiting_on(self, state: AgentState, stop_reason: str) -> str:
        if stop_reason == "awaiting_approval":
            gate = self._pending_gate(state)
            if gate is not None:
                return gate.plain_language_reason or gate.policy_reason
            return "等待审批结果。"
        if stop_reason == "needs_input":
            interrupt = self._pending_interrupt(state)
            if interrupt is not None:
                return interrupt.prompt or interrupt.title
            return "等待用户输入。"
        if stop_reason == "blocked":
            policy_block = state.meta.get("policy_block")
            if isinstance(policy_block, dict):
                return str(policy_block.get("plain_language_reason") or policy_block.get("policy_reason") or "策略阻断。")
            backend = state.meta.get("backend_status")
            if isinstance(backend, dict) and backend.get("last_error_summary"):
                return str(backend.get("last_error_summary"))
            return "等待问题解除后再继续。"
        if stop_reason == "max_turns_exceeded":
            return "等待新的目标、补充信息或人工接管。"
        if stop_reason == "escalated":
            return "等待人工判断下一步。"
        return ""

    def _current_blocker(self, state: AgentState, stop_reason: str) -> str:
        if stop_reason in {"awaiting_approval", "needs_input", "blocked", "max_turns_exceeded", "escalated"}:
            return self._waiting_on(state, stop_reason)
        return ""

    def _next_step(self, state: AgentState, stop_reason: str) -> str:
        if stop_reason == "completed":
            return "检查结果并决定是否开启下一轮 episode。"
        if stop_reason == "awaiting_approval":
            return "审批、拒绝，或先修改目标约束后再继续。"
        if stop_reason == "needs_input":
            interrupt = self._pending_interrupt(state)
            if interrupt is not None and interrupt.suggested_user_action:
                return interrupt.suggested_user_action
            return "补齐系统请求的信息后继续 workflow。"
        if stop_reason == "blocked":
            policy_block = state.meta.get("policy_block")
            if isinstance(policy_block, dict):
                return "调整项目 trust policy、修改动作约束，或人工改走别的路径。"
            return "检查后端配置或输入条件，修复后重试。"
        if stop_reason == "max_turns_exceeded":
            return "补充关键输入、缩小范围，或人工指定下一步。"
        if stop_reason == "escalated":
            return "由人工决定是否继续、改目标，或直接接管执行。"
        if state.selected_action is not None:
            return f"继续执行“{state.selected_action.title}”。"
        return "继续 workflow 以选择下一步动作。"

    def _plain_language_explanation(self, state: AgentState, stop_reason: str) -> str:
        if stop_reason == "awaiting_approval":
            gate = self._pending_gate(state)
            if gate is not None:
                return gate.plain_language_reason or "系统先停下来等你确认，再决定要不要继续执行这个动作。"
            return "系统在等待审批。"
        if stop_reason == "needs_input":
            interrupt = self._pending_interrupt(state)
            if interrupt is not None:
                return interrupt.plain_language_explanation or "系统缺少继续执行所需的信息。"
            return "系统缺少继续执行所需的信息。"
        if stop_reason == "blocked":
            policy_block = state.meta.get("policy_block")
            if isinstance(policy_block, dict):
                return str(policy_block.get("plain_language_reason") or "这个动作被当前 trust policy 阻断了。")
            return "系统现在无法可靠继续，需要先解决阻断问题。"
        if stop_reason == "max_turns_exceeded":
            return "系统已经连续尝试多轮，但还没有找到可靠的自动下一步，所以先停下来等你决定。"
        if stop_reason == "escalated":
            return "系统多次尝试后仍缺少可靠路径，建议你现在人工接管。"
        if stop_reason == "completed":
            return "当前 workflow 已经完成。"
        if state.selected_action is not None and state.selected_action.plain_language_explanation:
            return state.selected_action.plain_language_explanation
        return "系统正在评估下一步。"

    def _technical_explanation(self, state: AgentState, stop_reason: str) -> str:
        if stop_reason == "awaiting_approval":
            gate = self._pending_gate(state)
            if gate is not None:
                return (
                    f"Gate `{gate.gate_id}` is pending for action revision {gate.action_revision}; "
                    f"trust_decision={gate.trust_decision}; policy_reason={gate.policy_reason}"
                )
            return "Pending approval interrupt detected."
        if stop_reason == "needs_input":
            interrupt = self._pending_interrupt(state)
            if interrupt is not None:
                return interrupt.technical_explanation or f"Pending interrupt `{interrupt.interrupt_id}` requires feedback."
            return "Pending feedback required."
        if stop_reason == "blocked":
            policy_block = state.meta.get("policy_block")
            if isinstance(policy_block, dict):
                return (
                    f"Trust policy blocked action `{policy_block.get('action_title')}`; "
                    f"rule_id={policy_block.get('rule_id')}; policy_reason={policy_block.get('policy_reason')}"
                )
            backend = state.meta.get("backend_status")
            if isinstance(backend, dict):
                return (
                    f"Backend blocked execution; backend={backend.get('backend')}; "
                    f"error={backend.get('last_error_summary')}"
                )
            return "Workflow blocked."
        if stop_reason == "max_turns_exceeded":
            info = state.meta.get("max_turns_exceeded") or {}
            return (
                f"Automatic decision budget exhausted after {info.get('decision_rounds', 0)} "
                f"rounds (limit={info.get('limit', self.max_decision_rounds)}); "
                f"auto_action_count={info.get('auto_action_count', 0)} "
                f"(limit={info.get('auto_action_limit', self.max_auto_actions)})."
            )
        if stop_reason == "escalated":
            info = state.meta.get("escalation") or {}
            return (
                f"Escalated after repeated failures; failed_observation_count="
                f"{info.get('failed_observation_count', 0)}."
            )
        if state.selected_action is not None and state.selected_action.technical_explanation:
            return state.selected_action.technical_explanation
        return "No additional technical explanation available."

    def _recent_completed(self, state: AgentState) -> list[str]:
        items: list[str] = []
        for observation in reversed(state.observations):
            status = str(observation.payload.get("status") or "")
            if status == "completed":
                items.append(observation.summary)
            if len(items) == 2:
                break
        if len(items) < 2:
            for entry in reversed(state.decision_trace):
                if entry.kind in {"feedback", "capability_inspected"}:
                    items.append(entry.summary)
                if len(items) == 2:
                    break
        return list(reversed(items))

    def _pending_interrupt(self, state: AgentState) -> AgentInterrupt | None:
        for interrupt in state.pending_interrupts:
            if interrupt.status == "pending" and interrupt.kind != "approval_request":
                return interrupt
        return None

    def _pending_gate(self, state: AgentState):
        for gate in state.approval_gates:
            if gate.status == "pending":
                return gate
        return None

    def _capture_backend_status(self, state: AgentState) -> None:
        state.meta["backend_status"] = self._current_backend_status()

    def _current_backend_status(self) -> dict[str, Any]:
        status_getter = getattr(self.adapter, "current_backend_status", None)
        if callable(status_getter):
            return dict(status_getter())
        return {
            "adapter": type(self.adapter).__name__,
            "backend": "unknown",
            "provider": None,
            "model": None,
            "sidecar": None,
            "degraded": False,
            "fallback_used": False,
            "fallback_backend": None,
            "last_error_summary": None,
        }

    def _artifact_meta(self, artifact: Any) -> dict[str, Any]:
        if hasattr(artifact, "meta"):
            return dict(getattr(artifact, "meta") or {})
        if isinstance(artifact, dict):
            return dict(artifact.get("_meta") or {})
        return self._current_backend_status()
