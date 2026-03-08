from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import AgentAction
from .models import AgentInterrupt
from .models import AgentObservation
from .models import AgentState
from .models import DesignContract
from .models import ToolAction
from .models import new_object_id


class AgentModelAdapter(Protocol):
    def derive_design_contract(self, *, episode_id: str, goal: str, current_state: AgentState) -> DesignContract: ...

    def build_working_plan(self, *, state: AgentState, candidates: list[AgentAction]) -> dict[str, object]: ...

    def propose_candidate_actions(self, *, state: AgentState) -> list[AgentAction]: ...

    def select_action(self, *, state: AgentState, candidates: list[AgentAction]) -> AgentAction: ...

    def build_clarification_interrupt(self, *, state: AgentState, reason: str) -> AgentInterrupt: ...

    def summarize_observation(self, *, state: AgentState, observation: AgentObservation) -> str: ...


@dataclass(slots=True)
class HeuristicAgentAdapter:
    adapter_name: str = "heuristic-agent-adapter"

    def derive_design_contract(self, *, episode_id: str, goal: str, current_state: AgentState) -> DesignContract:
        goal_text = _first_goal_line(goal)
        return DesignContract(
            summary=goal_text or f"Episode {episode_id} objective",
            goals=[goal_text] if goal_text else [],
            constraints=[],
            assumptions=[
                "Use the canonical episode workspace as the source of truth.",
                "Keep tool execution inside the controlled runtime boundary.",
            ],
            open_questions=[] if goal_text else ["What is the concrete design objective for this episode?"],
        )

    def build_working_plan(self, *, state: AgentState, candidates: list[AgentAction]) -> dict[str, object]:
        tool_steps = [
            {
                "id": action.action_id,
                "title": action.title,
                "tool": action.tool_action.tool,
                "inputs": action.tool_action.inputs,
            }
            for action in candidates
            if action.tool_action is not None
        ]
        return {
            "summary": state.design_contract.summary,
            "candidate_actions": [action.title for action in candidates],
            "steps": tool_steps,
            "_meta": {"adapter": self.adapter_name},
        }

    def propose_candidate_actions(self, *, state: AgentState) -> list[AgentAction]:
        latest_observation = state.observations[-1] if state.observations else None
        latest_feedback = state.human_feedback[-1] if state.human_feedback else None
        if latest_observation and latest_observation.payload.get("status") == "completed":
            return [
                AgentAction(
                    action_id=new_object_id("action"),
                    kind="complete",
                    title="Complete episode",
                    rationale="A successful observation was recorded and no further work is required by the heuristic adapter.",
                )
            ]
        if latest_observation and latest_observation.payload.get("status") == "failed":
            if latest_feedback is not None:
                return [
                    AgentAction(
                        action_id=new_object_id("action"),
                        kind="tool",
                        title="Retry receptor preparation",
                        rationale=f"Retry after human feedback: {latest_feedback.content}",
                        tool_action=ToolAction(
                            tool="prepare_receptor",
                            inputs={"input": "data/inputs/receptor.pdb"},
                            risk_level="normal",
                        ),
                    )
                ]
            return [
                AgentAction(
                    action_id=new_object_id("action"),
                    kind="clarification",
                    title="Request human guidance",
                    rationale="The latest observation indicates a failure and requires operator feedback.",
                )
            ]
        if not state.design_contract.summary:
            return [
                AgentAction(
                    action_id=new_object_id("action"),
                    kind="clarification",
                    title="Request objective clarification",
                    rationale="The design objective is missing or underspecified.",
                )
            ]
        return [
            AgentAction(
                action_id=new_object_id("action"),
                kind="tool",
                title="Prepare receptor context",
                rationale="Create a controlled preprocessing result before downstream analysis.",
                tool_action=ToolAction(
                    tool="prepare_receptor",
                    inputs={"input": "data/inputs/receptor.pdb"},
                    risk_level="normal",
                ),
            )
        ]

    def select_action(self, *, state: AgentState, candidates: list[AgentAction]) -> AgentAction:
        return candidates[0]

    def build_clarification_interrupt(self, *, state: AgentState, reason: str) -> AgentInterrupt:
        return AgentInterrupt(
            interrupt_id=new_object_id("interrupt"),
            kind="clarification_request",
            status="pending",
            title="Human feedback required",
            prompt=reason,
            created_at=state.session.updated_at,
            related_action_id=state.selected_action.action_id if state.selected_action else None,
        )

    def summarize_observation(self, *, state: AgentState, observation: AgentObservation) -> str:
        if observation.payload.get("status") == "completed":
            return f"Observation {observation.observation_id} completed successfully."
        return f"Observation {observation.observation_id} failed: {observation.summary}"


def _first_goal_line(goal: str) -> str:
    for line in goal.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return ""
