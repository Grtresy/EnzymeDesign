from __future__ import annotations

from datetime import UTC
from datetime import datetime
from typing import Any
from typing import TypedDict

from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph
from openzyme_runtime.bootstrap import GraphAssemblyInputs

from .state import GraphPhase
from .state import IntakeHandoff
from .state import ProgressStatus
from .state import SupervisorStatus


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _progress(active_node: str, status: ProgressStatus, message: str) -> dict[str, Any]:
    return {
        "phase": GraphPhase.INTAKE.value,
        "active_node": active_node,
        "status": status.value,
        "updated_at": _utc_now_iso(),
        "message": message,
    }


class IntakeSubgraphState(TypedDict, total=False):
    episode_id: str
    project_id: str
    objective: str
    user_goal: str
    project_context: dict[str, Any]
    current_phase: str
    status: str
    progress: dict[str, Any]
    pending_interrupt: dict[str, Any] | None
    design_brief: str
    research_brief: str
    candidate_plan: dict[str, Any] | None
    run_request: dict[str, Any] | None
    recommended_next_phase: str | None
    intake_handoff: IntakeHandoff | None


def build_intake_subgraph(inputs: GraphAssemblyInputs, *, include_checkpointer: bool = True) -> Any:
    def collect_intake(state: IntakeSubgraphState) -> dict[str, Any]:
        objective = state.get("objective") or state.get("user_goal") or ""
        design_brief = state.get("design_brief") or f"Design brief for {objective}".strip()
        research_brief = state.get("research_brief") or f"Research brief for {objective}".strip()
        if state.get("run_request"):
            next_phase = GraphPhase.EXECUTION
        elif state.get("candidate_plan"):
            next_phase = GraphPhase.EXECUTION
        else:
            next_phase = GraphPhase.RESEARCH
        intake_handoff: IntakeHandoff = {
            "design_brief": design_brief,
            "research_brief": research_brief,
            "recommended_next_phase": next_phase.value,
        }
        return {
            "current_phase": GraphPhase.INTAKE.value,
            "status": SupervisorStatus.ACTIVE.value,
            "pending_interrupt": None,
            "design_brief": design_brief,
            "research_brief": research_brief,
            "recommended_next_phase": next_phase.value,
            "intake_handoff": intake_handoff,
            "progress": _progress(
                "collect_intake",
                ProgressStatus.SUCCEEDED,
                f"Intake completed; routing to {next_phase.value}",
            ),
        }

    graph = StateGraph(IntakeSubgraphState)
    graph.add_node("collect_intake", collect_intake)
    graph.add_edge(START, "collect_intake")
    graph.add_edge("collect_intake", END)
    if include_checkpointer:
        return graph.compile(checkpointer=inputs.checkpointer)
    return graph.compile()
