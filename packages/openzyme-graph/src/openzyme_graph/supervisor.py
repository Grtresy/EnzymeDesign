from __future__ import annotations

import operator
from typing import Annotated
from typing import Any
from typing import TypedDict

from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph
from openzyme_research import ResearchUnit
from openzyme_runtime.bootstrap import GraphAssemblyInputs

from .design import DesignSupervisorState
from .design import build_phase_c_design_graph
from .execution import ExecutionSubgraphState
from .execution import build_execution_subgraph
from .intake import IntakeSubgraphState
from .intake import build_intake_subgraph
from .report_review import ReportReviewSubgraphState
from .report_review import build_report_review_subgraph
from .research import ResearchSupervisorState
from .research import ResearchWorkerOutputPayload
from .research import build_phase_c_research_graph
from .state import DesignHandoff
from .state import ExecutionHandoff
from .state import GraphPhase
from .state import IntakeHandoff
from .state import ResearchHandoff
from .state import SupervisorStatus


class SupervisorGraphState(
    IntakeSubgraphState,
    ResearchSupervisorState,
    DesignSupervisorState,
    ExecutionSubgraphState,
    ReportReviewSubgraphState,
    total=False,
):
    current_phase: str
    status: str
    pending_interrupt: dict[str, Any] | None
    recommended_next_phase: str | None
    intake_handoff: IntakeHandoff | None
    research_handoff: ResearchHandoff | None
    design_handoff: DesignHandoff | None
    execution_handoff: ExecutionHandoff | None
    latest_run_id: str | None
    research_units: list[dict[str, Any]]
    worker_outputs: Annotated[list[ResearchWorkerOutputPayload], operator.add]


def _phase_entry_update(phase: GraphPhase, active_node: str, message: str) -> dict[str, Any]:
    return {
        "current_phase": phase.value,
        "status": SupervisorStatus.ACTIVE.value,
        "progress": {
            "phase": phase.value,
            "active_node": active_node,
            "status": "running",
            "updated_at": "phase-entry",
            "message": message,
        },
    }


def _default_research_units(state: SupervisorGraphState) -> list[ResearchUnit]:
    objective = state.get("objective") or state.get("design_brief") or "enzyme redesign objective"
    return [
        ResearchUnit(
            unit_id="literature",
            topic="literature evidence",
            query=f"{objective} thermostability evidence",
        ),
        ResearchUnit(
            unit_id="structures",
            topic="structure and homolog evidence",
            query=f"{objective} homolog structure stability",
        ),
    ]


def build_v2_supervisor_graph(inputs: GraphAssemblyInputs) -> Any:
    intake_subgraph = build_intake_subgraph(inputs, include_checkpointer=False)
    research_subgraph = build_phase_c_research_graph(inputs, include_checkpointer=False)
    design_subgraph = build_phase_c_design_graph(inputs, include_checkpointer=False)
    execution_subgraph = build_execution_subgraph(inputs, include_checkpointer=False)
    report_review_subgraph = build_report_review_subgraph(inputs, include_checkpointer=False)

    def seed_research_defaults(state: SupervisorGraphState) -> dict[str, Any]:
        if state.get("research_units"):
            return {}
        return {"research_units": [unit.to_dict() for unit in _default_research_units(state)]}

    def enter_research_phase(state: SupervisorGraphState) -> dict[str, Any]:
        del state
        return _phase_entry_update(
            GraphPhase.RESEARCH,
            "enter_research_phase",
            "Supervisor routed episode into research",
        )

    def enter_design_phase(state: SupervisorGraphState) -> dict[str, Any]:
        del state
        return _phase_entry_update(
            GraphPhase.DESIGN,
            "enter_design_phase",
            "Supervisor routed episode into design",
        )

    def enter_execution_phase(state: SupervisorGraphState) -> dict[str, Any]:
        del state
        return _phase_entry_update(
            GraphPhase.EXECUTION,
            "enter_execution_phase",
            "Supervisor routed episode into execution",
        )

    def enter_report_review_phase(state: SupervisorGraphState) -> dict[str, Any]:
        del state
        return _phase_entry_update(
            GraphPhase.REPORT_REVIEW,
            "enter_report_review_phase",
            "Supervisor routed episode into report review",
        )

    def route_after_intake(state: SupervisorGraphState) -> str:
        handoff = state.get("intake_handoff") or {}
        next_phase = handoff.get("recommended_next_phase") or state.get("recommended_next_phase")
        if next_phase == GraphPhase.EXECUTION.value:
            return "enter_execution_phase"
        if next_phase == GraphPhase.DESIGN.value:
            return "enter_design_phase"
        return "enter_research_phase"

    def route_after_research(state: SupervisorGraphState) -> str:
        if state.get("status") == SupervisorStatus.INTERRUPTED.value:
            return END
        handoff = state.get("research_handoff") or {}
        next_phase = handoff.get("recommended_next_phase") or state.get("recommended_next_phase")
        if next_phase == GraphPhase.DESIGN.value:
            return "enter_design_phase"
        return END

    def route_after_design(state: SupervisorGraphState) -> str:
        if state.get("status") == SupervisorStatus.COMPLETED.value and state.get("design_handoff") is not None:
            return "enter_execution_phase"
        return END

    def route_after_execution(state: SupervisorGraphState) -> str:
        if state.get("status") != SupervisorStatus.COMPLETED.value:
            return END
        handoff = state.get("execution_handoff") or {}
        next_phase = handoff.get("recommended_next_phase") or state.get("recommended_next_phase")
        if next_phase == GraphPhase.REPORT_REVIEW.value:
            return "enter_report_review_phase"
        return END

    graph = StateGraph(SupervisorGraphState)
    graph.add_node("intake_phase", intake_subgraph)
    graph.add_node("enter_research_phase", enter_research_phase)
    graph.add_node("seed_research_defaults", seed_research_defaults)
    graph.add_node("enter_design_phase", enter_design_phase)
    graph.add_node("enter_execution_phase", enter_execution_phase)
    graph.add_node("enter_report_review_phase", enter_report_review_phase)
    graph.add_node("research_phase", research_subgraph)
    graph.add_node("design_phase", design_subgraph)
    graph.add_node("execution_phase", execution_subgraph)
    graph.add_node("report_review_phase", report_review_subgraph)
    graph.add_edge(START, "intake_phase")
    graph.add_conditional_edges(
        "intake_phase",
        route_after_intake,
        {
            "enter_research_phase": "enter_research_phase",
            "enter_design_phase": "enter_design_phase",
            "enter_execution_phase": "enter_execution_phase",
        },
    )
    graph.add_edge("enter_research_phase", "seed_research_defaults")
    graph.add_edge("seed_research_defaults", "research_phase")
    graph.add_conditional_edges(
        "research_phase",
        route_after_research,
        {
            "enter_design_phase": "enter_design_phase",
            END: END,
        },
    )
    graph.add_edge("enter_design_phase", "design_phase")
    graph.add_conditional_edges(
        "design_phase",
        route_after_design,
        {
            "enter_execution_phase": "enter_execution_phase",
            END: END,
        },
    )
    graph.add_edge("enter_execution_phase", "execution_phase")
    graph.add_conditional_edges(
        "execution_phase",
        route_after_execution,
        {
            "enter_report_review_phase": "enter_report_review_phase",
            END: END,
        },
    )
    graph.add_edge("enter_report_review_phase", "report_review_phase")
    graph.add_edge("report_review_phase", END)
    return graph.compile(checkpointer=inputs.checkpointer)
