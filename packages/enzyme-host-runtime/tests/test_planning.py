from __future__ import annotations

from enzyme_host_runtime.planning import AgentAction
from enzyme_host_runtime.planning import AgentInterrupt
from enzyme_host_runtime.planning import AgentObservation
from enzyme_host_runtime.planning import AgentState
from enzyme_host_runtime.planning import AgentWorkflowOrchestrator
from enzyme_host_runtime.planning import ApprovalGate
from enzyme_host_runtime.planning import DesignContract
from enzyme_host_runtime.planning import ToolAction
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


def test_workflow_orchestrator_selects_tool_action() -> None:
    orchestrator = AgentWorkflowOrchestrator(adapter=_FakeAdapter())
    state = AgentState.from_dict({}, episode_id="0001", objective="improve binding")

    updated = orchestrator.initialize(state)

    assert updated.design_contract.summary == "contract for 0001"
    assert updated.selected_action is not None
    assert updated.selected_action.kind == "tool"
    assert updated.pending_interrupts == []


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
