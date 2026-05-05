from __future__ import annotations

from datetime import UTC
from datetime import datetime
from typing import Any
from typing import TypedDict

from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph
from openzyme_runtime import ConstraintItem
from openzyme_runtime import ConstraintSet
from openzyme_runtime.bootstrap import GraphAssemblyInputs
from openzyme_runtime import DesignBriefDraft
from openzyme_runtime import IntakeClarification
from openzyme_runtime import IntakePhaseOutput
from openzyme_runtime import ResearchBriefDraft

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
    run_request: dict[str, Any] | None
    recommended_next_phase: str | None
    intake_handoff: IntakeHandoff | None
    clarification: dict[str, Any] | None
    constraint_set: dict[str, Any] | None


def _fallback_intake_output(state: IntakeSubgraphState) -> IntakePhaseOutput:
    objective = state.get("objective") or state.get("user_goal") or "OpenZyme objective"
    return IntakePhaseOutput(
        clarification=IntakeClarification(),
        constraint_set=ConstraintSet(
            objective_summary=objective,
            constraints=[
                ConstraintItem(
                    category="technical",
                    description="Preserve current graph workflow boundaries while refining typed contracts.",
                )
            ],
        ),
        design_brief=DesignBriefDraft(
            design_brief=f"Design brief for {objective}".strip(),
            success_criteria=["Produce an artifact workspace suitable for execution handoff."],
        ),
        research_brief=ResearchBriefDraft(
            research_brief=f"Research brief for {objective}".strip(),
            focus_areas=["relevant evidence", "unresolved gaps"],
            expected_outputs=["canonical research summary", "evidence refs"],
        ),
    )


def build_intake_subgraph(inputs: GraphAssemblyInputs, *, include_checkpointer: bool = True) -> Any:
    def collect_intake(state: IntakeSubgraphState) -> dict[str, Any]:
        if inputs.model_factory is not None:
            invoker = inputs.model_factory.create_structured_invoker(purpose="intake_collect")
            intake_output = invoker.invoke_structured(
                schema=IntakePhaseOutput,
                system_prompt=(
                    "You are the intake layer for an enzyme design workflow. "
                    "Produce a concise constraint set, a design brief, and a research brief."
                ),
                user_payload={
                    "episode_id": state.get("episode_id"),
                    "project_id": state.get("project_id"),
                    "objective": state.get("objective"),
                    "user_goal": state.get("user_goal"),
                    "project_context": state.get("project_context") or {},
                },
            )
        else:
            intake_output = _fallback_intake_output(state)

        design_brief = state.get("design_brief") or intake_output.design_brief.design_brief
        research_brief = state.get("research_brief") or intake_output.research_brief.research_brief
        next_phase = GraphPhase.DESIGN
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
            "clarification": intake_output.clarification.model_dump(),
            "constraint_set": intake_output.constraint_set.model_dump(),
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
