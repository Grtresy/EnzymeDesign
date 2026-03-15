from __future__ import annotations

from enzyme_host_runtime.planning import AgentAction
from enzyme_host_runtime.planning import AgentBackendBlockedError
from enzyme_host_runtime.planning import AgentInterrupt
from enzyme_host_runtime.planning import AgentObservation
from enzyme_host_runtime.planning import AgentState
from enzyme_host_runtime.planning import AgentWorkflowOrchestrator
from enzyme_host_runtime.planning import ApprovalGate
from enzyme_host_runtime.planning import ApprovalPolicy
from enzyme_host_runtime.planning import DesignContract
from enzyme_host_runtime.planning import ToolAction
from enzyme_host_runtime.workspace import TrustPolicyConfig
from enzyme_host_runtime.workspace import TrustPolicyRuleConfig
from enzyme_host_runtime.planning.models import new_object_id


class _FakeAdapter:
    def derive_design_contract(self, *, episode_id: str, goal: str, current_state: AgentState) -> DesignContract:
        return DesignContract(
            summary=f"contract for {episode_id}",
            goals=[goal],
            constraints=[],
            assumptions=["fake adapter"],
            open_questions=[],
        )

    def build_working_plan(self, *, state: AgentState, candidates: list[AgentAction]) -> dict[str, object]:
        return {"steps": [item.title for item in candidates]}

    def propose_candidate_actions(self, *, state: AgentState) -> list[AgentAction]:
        latest = state.observations[-1] if state.observations else None
        if latest and latest.payload.get("status") == "failed":
            return [
                AgentAction(
                    action_id=new_object_id("action"),
                    kind="clarification",
                    title="Need guidance",
                    rationale="tool failed",
                )
            ]
        return [
            AgentAction(
                action_id=new_object_id("action"),
                kind="tool",
                title="Run preprocessing",
                rationale="prepare context",
                tool_action=ToolAction(tool="prepare_receptor", inputs={"input": "data/inputs/receptor.pdb"}),
            )
        ]

    def select_action(self, *, state: AgentState, candidates: list[AgentAction]) -> AgentAction:
        return candidates[0]

    def build_clarification_interrupt(self, *, state: AgentState, reason: str) -> AgentInterrupt:
        return AgentInterrupt(
            interrupt_id=new_object_id("interrupt"),
            kind="clarification_request",
            status="pending",
            title="Need feedback",
            prompt=reason,
            created_at=state.session.updated_at,
        )

    def summarize_observation(self, *, state: AgentState, observation: AgentObservation) -> str:
        return observation.summary

    def current_backend_status(self) -> dict[str, object]:
        return {
            "backend": "heuristic",
            "degraded": False,
            "fallback_used": False,
            "last_error_summary": None,
        }


class _ClarificationBlockedAdapter(_FakeAdapter):
    def build_clarification_interrupt(self, *, state: AgentState, reason: str) -> AgentInterrupt:
        del state, reason
        raise AgentBackendBlockedError(
            "sidecar unavailable",
            operation="build_clarification_interrupt",
            backend_status={
                "backend": "llm-sidecar",
                "degraded": False,
                "fallback_used": False,
                "last_error_summary": "sidecar unavailable",
            },
        )

    def current_backend_status(self) -> dict[str, object]:
        return {
            "backend": "llm-sidecar",
            "degraded": False,
            "fallback_used": False,
            "last_error_summary": None,
        }


class _ClarificationFallbackAdapter(_FakeAdapter):
    def __init__(self) -> None:
        self._backend_status = {
            "backend": "llm-sidecar",
            "degraded": False,
            "fallback_used": False,
            "last_error_summary": None,
        }

    def build_clarification_interrupt(self, *, state: AgentState, reason: str) -> AgentInterrupt:
        self._backend_status = {
            "backend": "llm-sidecar",
            "degraded": True,
            "fallback_used": True,
            "last_error_summary": "schema validation failed",
        }
        return super().build_clarification_interrupt(state=state, reason=reason)

    def current_backend_status(self) -> dict[str, object]:
        return dict(self._backend_status)


def test_workflow_orchestrator_selects_tool_action() -> None:
    orchestrator = AgentWorkflowOrchestrator(adapter=_FakeAdapter())
    state = AgentState.from_dict({}, episode_id="0001", objective="improve binding")

    updated = orchestrator.initialize(state)

    assert updated.design_contract.summary == "contract for 0001"
    assert updated.selected_action is not None
    assert updated.selected_action.kind == "tool"
    assert updated.pending_interrupts == []
    assert updated.selected_action.trust_decision == "auto_allowed"
    assert updated.selected_action.policy_summary


def test_workflow_orchestrator_creates_interrupt_after_failed_observation() -> None:
    orchestrator = AgentWorkflowOrchestrator(adapter=_FakeAdapter())
    state = orchestrator.initialize(AgentState.from_dict({}, episode_id="0001", objective="improve binding"))

    observation = AgentObservation(
        observation_id=new_object_id("obs"),
        source="tool",
        summary="tool failed",
        created_at=state.session.updated_at,
        payload={"status": "failed"},
    )
    updated = orchestrator.record_observation(state, observation)

    assert updated.pending_interrupts
    assert updated.pending_interrupts[-1].kind == "clarification_request"
    assert updated.status == "awaiting_feedback"


def test_feedback_resets_failed_observation_streak_before_next_retry() -> None:
    class _RetryAfterFeedbackAdapter(_FakeAdapter):
        def propose_candidate_actions(self, *, state: AgentState) -> list[AgentAction]:
            if state.human_feedback:
                return [
                    AgentAction(
                        action_id=new_object_id("action"),
                        kind="tool",
                        title="Retry preprocessing",
                        rationale="user provided guidance",
                        tool_action=ToolAction(tool="prepare_receptor", inputs={"input": "data/inputs/receptor.pdb"}),
                    )
                ]
            return super().propose_candidate_actions(state=state)

    orchestrator = AgentWorkflowOrchestrator(adapter=_RetryAfterFeedbackAdapter())
    state = orchestrator.initialize(AgentState.from_dict({}, episode_id="0001", objective="improve binding"))

    first_failure = AgentObservation(
        observation_id=new_object_id("obs"),
        source="tool",
        summary="tool failed once",
        created_at=state.session.updated_at,
        payload={"status": "failed"},
    )
    interrupted = orchestrator.record_observation(state, first_failure)

    assert interrupted.pending_interrupts
    interrupt_id = interrupted.pending_interrupts[-1].interrupt_id
    assert interrupted.meta["consecutive_failed_observations"] == 1

    resumed = orchestrator.apply_feedback(
        interrupted,
        interrupt_id=interrupt_id,
        content="retry with updated guidance",
        kind="clarification",
        actor="host-user",
    )

    assert resumed.meta["consecutive_failed_observations"] == 0
    assert resumed.selected_action is not None
    assert resumed.stop_reason == "active"

    second_failure = AgentObservation(
        observation_id=new_object_id("obs"),
        source="tool",
        summary="tool failed again",
        created_at=resumed.session.updated_at,
        payload={"status": "failed"},
    )
    retried = orchestrator.record_observation(resumed, second_failure)

    assert retried.termination_status != "escalated"
    assert retried.stop_reason == "active"
    assert retried.selected_action is not None
    assert retried.meta["consecutive_failed_observations"] == 1


def test_new_selected_action_supersedes_pending_gate() -> None:
    orchestrator = AgentWorkflowOrchestrator(adapter=_FakeAdapter())
    state = AgentState.from_dict({}, episode_id="0001", objective="improve binding")
    state.selected_action = AgentAction(
        action_id="action-old",
        kind="tool",
        title="Old action",
        rationale="old pending action",
        tool_action=ToolAction(tool="vina", inputs={"receptor_pdbqt": "a", "ligand_pdbqt": "b"}, risk_level="high"),
    )
    state.approval_gates.append(
        ApprovalGate(
            gate_id="gate-old",
            action_id="action-old",
            action_revision=1,
            action_type="tool",
            risk_level="high",
            policy_reason="approval required",
            required_feedback_type="approval",
            status="pending",
            created_at=state.session.updated_at,
            action_snapshot=state.selected_action.to_dict(),
        )
    )

    updated = orchestrator.continue_workflow(state)

    assert updated.selected_action is not None
    assert updated.selected_action.action_id != "action-old"
    assert updated.approval_gates[0].status == "superseded"


def test_clarification_backend_block_marks_workflow_blocked() -> None:
    orchestrator = AgentWorkflowOrchestrator(adapter=_ClarificationBlockedAdapter())
    state = orchestrator.initialize(AgentState.from_dict({}, episode_id="0001", objective="improve binding"))

    observation = AgentObservation(
        observation_id=new_object_id("obs"),
        source="tool",
        summary="tool failed",
        created_at=state.session.updated_at,
        payload={"status": "failed"},
    )
    updated = orchestrator.record_observation(state, observation)

    assert updated.status == "blocked"
    assert updated.selected_action is None
    assert updated.meta["backend_status"]["backend"] == "llm-sidecar"
    assert updated.decision_trace[-1].kind == "backend_error"


def test_clarification_fallback_persists_degraded_backend_status() -> None:
    orchestrator = AgentWorkflowOrchestrator(adapter=_ClarificationFallbackAdapter())
    state = orchestrator.initialize(AgentState.from_dict({}, episode_id="0001", objective="improve binding"))

    observation = AgentObservation(
        observation_id=new_object_id("obs"),
        source="tool",
        summary="tool failed",
        created_at=state.session.updated_at,
        payload={"status": "failed"},
    )
    updated = orchestrator.record_observation(state, observation)

    assert updated.status == "awaiting_feedback"
    assert updated.meta["backend_status"]["degraded"] is True
    assert updated.meta["backend_status"]["fallback_used"] is True
    assert updated.decision_trace[-1].meta["degraded"] is True


def test_workflow_budget_exhaustion_sets_structured_stop_reason() -> None:
    orchestrator = AgentWorkflowOrchestrator(adapter=_FakeAdapter(), max_decision_rounds=1)
    state = orchestrator.initialize(AgentState.from_dict({}, episode_id="0001", objective="improve binding"))

    updated = orchestrator.continue_workflow(state)

    assert updated.stop_reason == "max_turns_exceeded"
    assert updated.next_step_suggestion
    assert updated.needs_user_intervention is True
    assert updated.progress_summary.current_blocker


def test_manual_gate_rejection_stops_workflow_as_blocked() -> None:
    state = AgentState.from_dict({}, episode_id="0001", objective="improve binding")
    state.selected_action = AgentAction(
        action_id="action-1",
        kind="tool",
        title="Run docking",
        rationale="Needs approval",
        tool_action=ToolAction(tool="vina", inputs={"receptor_pdbqt": "a", "ligand_pdbqt": "b"}, risk_level="high"),
        gate_id="gate-1",
    )
    state.approval_gates.append(
        ApprovalGate(
            gate_id="gate-1",
            action_id="action-1",
            action_revision=1,
            action_type="tool",
            risk_level="high",
            policy_reason="approval required",
            plain_language_reason="这是高成本远程计算，继续前需要确认。",
            trust_decision="approval_required",
            required_feedback_type="approval",
            status="pending",
            created_at=state.session.updated_at,
            action_snapshot=state.selected_action.to_dict(),
        )
    )
    state.pending_interrupts.append(
        AgentInterrupt(
            interrupt_id="interrupt-1",
            kind="approval_request",
            status="pending",
            title="Approval required",
            prompt="approve or reject",
            created_at=state.session.updated_at,
            gate_id="gate-1",
            related_action_id="action-1",
        )
    )
    orchestrator = AgentWorkflowOrchestrator(adapter=_FakeAdapter())

    updated = orchestrator.apply_feedback(
        state,
        interrupt_id="interrupt-1",
        content="rejected",
        kind="rejection",
        actor="host-user",
    )

    assert updated.stop_reason == "blocked"
    assert updated.needs_user_intervention is True
    assert updated.selected_action is None


def test_allowed_tool_action_keeps_policy_explanation_without_gate() -> None:
    orchestrator = AgentWorkflowOrchestrator(adapter=_FakeAdapter())

    updated = orchestrator.initialize(AgentState.from_dict({}, episode_id="0001", objective="improve binding"))

    assert updated.selected_action is not None
    assert updated.selected_action.trust_decision == "auto_allowed"
    assert updated.selected_action.policy_summary
    assert updated.approval_gates == []


def test_budget_exhaustion_sets_max_turns_exceeded() -> None:
    orchestrator = AgentWorkflowOrchestrator(adapter=_FakeAdapter(), max_decision_rounds=1)
    state = orchestrator.initialize(AgentState.from_dict({}, episode_id="0001", objective="improve binding"))

    updated = orchestrator.continue_workflow(state)

    assert updated.stop_reason == "max_turns_exceeded"
    assert updated.next_step_suggestion
    assert updated.progress_summary.current_blocker


def test_project_trust_policy_can_block_selected_action() -> None:
    policy = ApprovalPolicy(
        config=TrustPolicyConfig(
            rules=[
                TrustPolicyRuleConfig(
                    tool="prepare_receptor",
                    decision="block",
                    policy_reason="Project policy blocks local preprocessing until the inputs are reviewed.",
                    plain_language_reason="项目要求先人工检查输入，所以系统现在不能直接跑预处理。",
                    trust_decision="blocked",
                    rule_id="project:block-prepare",
                )
            ]
        )
    )
    orchestrator = AgentWorkflowOrchestrator(adapter=_FakeAdapter(), approval_policy=policy)

    updated = orchestrator.initialize(AgentState.from_dict({}, episode_id="0001", objective="improve binding"))

    assert updated.stop_reason == "blocked"
    assert updated.plain_language_explanation == "项目要求先人工检查输入，所以系统现在不能直接跑预处理。"
    assert updated.technical_explanation.startswith("Trust policy blocked action")
