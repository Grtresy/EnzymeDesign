from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Protocol

from ..capability import configured_capability_summaries
from ..capability import visible_capability_bindings
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

    def current_backend_status(self) -> dict[str, Any]: ...


class AgentBackendBlockedError(RuntimeError):
    def __init__(self, summary: str, *, operation: str, backend_status: dict[str, Any]) -> None:
        super().__init__(summary)
        self.summary = summary
        self.operation = operation
        self.backend_status = dict(backend_status)


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
            meta=self._artifact_meta("derive_design_contract"),
        )

    def build_working_plan(self, *, state: AgentState, candidates: list[AgentAction]) -> dict[str, object]:
        capability_summaries = configured_capability_summaries(state.meta)
        tool_steps = [
            {
                "id": action.action_id,
                "title": action.title,
                "capability_id": action.capability_id,
                "tool": action.tool_action.tool,
                "inputs": action.tool_action.inputs,
            }
            for action in candidates
            if action.tool_action is not None
        ]
        return {
            "summary": state.design_contract.summary,
            "candidate_actions": [action.title for action in candidates],
            "capability_summaries": [item.capability_id for item in capability_summaries],
            "steps": tool_steps,
            "_meta": self._artifact_meta("build_working_plan"),
        }

    def propose_candidate_actions(self, *, state: AgentState) -> list[AgentAction]:
        capability_summaries = configured_capability_summaries(state.meta)
        visible_bindings = visible_capability_bindings(
            state.meta,
            episode_id=state.episode_id,
            active_state_version=state.state_version,
            role="host-agent",
        )
        bound_capability_ids = {item.contract.capability_id for item in visible_bindings}
        latest_observation = state.observations[-1] if state.observations else None
        latest_feedback = state.human_feedback[-1] if state.human_feedback else None
        if latest_observation and latest_observation.payload.get("status") == "completed":
                return [
                    AgentAction(
                        action_id=new_object_id("action"),
                        kind="complete",
                        title="Complete episode",
                        rationale="A successful observation was recorded and no further work is required by the heuristic adapter.",
                        meta=self._artifact_meta("propose_candidate_actions"),
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
                            capability_id="mcp-preprocess",
                            tool_action=ToolAction(
                                tool="prepare_receptor",
                                inputs={"input": "data/inputs/receptor.pdb"},
                                risk_level="normal",
                            ),
                            meta=self._artifact_meta("propose_candidate_actions"),
                        )
                    ]
            return [
                AgentAction(
                    action_id=new_object_id("action"),
                    kind="clarification",
                    title="Request human guidance",
                    rationale="The latest observation indicates a failure and requires operator feedback.",
                    meta=self._artifact_meta("propose_candidate_actions"),
                )
            ]
        if not state.design_contract.summary:
            return [
                AgentAction(
                    action_id=new_object_id("action"),
                    kind="clarification",
                    title="Request objective clarification",
                    rationale="The design objective is missing or underspecified.",
                    meta=self._artifact_meta("propose_candidate_actions"),
                    )
            ]
        preprocess_summary = next(
            (item for item in capability_summaries if item.capability_id == "mcp-preprocess"),
            None,
        )
        if preprocess_summary is not None and "mcp-preprocess" not in bound_capability_ids:
            return [
                AgentAction(
                    action_id=new_object_id("action"),
                    kind="inspect_capability",
                    title="Inspect preprocess capability",
                    rationale="Review the preprocess capability detail contract before selecting a concrete tool.",
                    capability_id="mcp-preprocess",
                    meta=self._artifact_meta("propose_candidate_actions"),
                )
            ]
        return [
            AgentAction(
                action_id=new_object_id("action"),
                kind="tool",
                title="Prepare receptor context",
                rationale="Create a controlled preprocessing result before downstream analysis.",
                capability_id="mcp-preprocess",
                tool_action=ToolAction(
                    tool="prepare_receptor",
                    inputs={"input": "data/inputs/receptor.pdb"},
                    risk_level="normal",
                ),
                meta=self._artifact_meta("propose_candidate_actions"),
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
            plain_language_explanation="系统现在缺少继续执行所需的关键信息，需要你补充说明后再继续。",
            technical_explanation=f"Clarification interrupt created because: {reason or 'missing context'}.",
            suggested_user_action="补充缺失输入、澄清目标，或直接告诉系统下一步该怎么做。",
        )

    def summarize_observation(self, *, state: AgentState, observation: AgentObservation) -> str:
        if observation.payload.get("status") == "completed":
            return f"Observation {observation.observation_id} completed successfully."
        return f"Observation {observation.observation_id} failed: {observation.summary}"

    def current_backend_status(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter_name,
            "backend": "heuristic",
            "provider": None,
            "model": None,
            "sidecar": None,
            "degraded": False,
            "fallback_used": False,
            "fallback_backend": None,
            "last_error_summary": None,
        }

    def _artifact_meta(self, operation: str) -> dict[str, Any]:
        return {
            **self.current_backend_status(),
            "operation": operation,
        }


def _first_goal_line(goal: str) -> str:
    for line in goal.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return ""
