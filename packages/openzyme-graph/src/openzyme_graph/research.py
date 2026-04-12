from __future__ import annotations

from datetime import UTC
from datetime import datetime
import operator
from typing import Annotated
from typing import Any
from typing import TypedDict

from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph
from langgraph.types import Send
from openzyme_domain import EvidenceRecord
from openzyme_domain import ResearchSummaryRecord
from openzyme_domain import SourceRef
from openzyme_domain import SourceRefKind
from openzyme_domain import UnresolvedGapRecord
from openzyme_research import ResearchUnit
from openzyme_research import ResearchUnitResult
from openzyme_runtime import EvidenceSynthesis
from openzyme_runtime.bootstrap import GraphAssemblyInputs
from openzyme_runtime import ResearchUnitDraft
from openzyme_runtime import ResearchUnitPlan

from .state import GraphPhase
from .state import InterruptType
from .state import ProgressStatus
from .state import ResearchHandoff
from .state import SupervisorStatus


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _progress(active_node: str, status: ProgressStatus, message: str) -> dict[str, Any]:
    return {
        "phase": GraphPhase.RESEARCH.value,
        "active_node": active_node,
        "status": status.value,
        "updated_at": _utc_now_iso(),
        "message": message,
    }


class ResearchWorkerOutputPayload(TypedDict):
    unit_id: str
    summary: str
    findings: list[dict[str, Any]]
    unresolved_gaps: list[str]
    error_message: str | None
    escalation_reason: str | None
    status: str


class ResearchSupervisorState(TypedDict, total=False):
    episode_id: str
    project_id: str
    objective: str
    design_brief: str
    research_brief: str
    research_units: list[dict[str, Any]]
    worker_outputs: Annotated[list[ResearchWorkerOutputPayload], operator.add]
    current_phase: str
    status: str
    progress: dict[str, Any]
    pending_interrupt: dict[str, Any] | None
    research_summary: dict[str, Any] | None
    evidence_payloads: list[dict[str, Any]]
    evidence_refs: list[dict[str, Any]]
    unresolved_gap_payloads: list[str]
    unresolved_gaps: list[dict[str, Any]]
    recommended_next_phase: str
    research_handoff: ResearchHandoff | None


class ResearchWorkerState(TypedDict):
    episode_id: str
    research_brief: str
    research_unit: dict[str, Any]


def _default_research_units(state: ResearchSupervisorState) -> list[ResearchUnit]:
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


def _fallback_research_plan(state: ResearchSupervisorState) -> ResearchUnitPlan:
    return ResearchUnitPlan(
        units=[
            ResearchUnitDraft(
                unit_id=unit.unit_id,
                topic=unit.topic,
                query=unit.query,
                rationale=f"Investigate {unit.topic} for the current objective.",
            )
            for unit in _default_research_units(state)
        ],
        synthesis_goal="Summarize evidence relevant to the objective and highlight remaining gaps.",
    )


def _build_interrupt_payload(
    interrupt_type: InterruptType,
    *,
    episode_id: str,
    reason: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": interrupt_type.value,
        "episode_id": episode_id,
        "phase": GraphPhase.RESEARCH.value,
        "reason": reason,
        "active_state_version": 1,
        "checkpoint_ns": "research",
        "checkpoint_id": f"{episode_id}-research",
        "approval_id": None,
        "requested_action": None,
        "details": details,
    }


def _unit_from_payload(payload: dict[str, Any]) -> ResearchUnit:
    return ResearchUnit(
        unit_id=str(payload["unit_id"]),
        topic=str(payload["topic"]),
        query=str(payload["query"]),
    )


def build_phase_c_research_graph(inputs: GraphAssemblyInputs, *, include_checkpointer: bool = True) -> Any:
    def plan_research(state: ResearchSupervisorState) -> dict[str, Any]:
        max_research_units = max(1, inputs.settings.research.max_units)
        configured_units = [
            _unit_from_payload(payload)
            for payload in list(state.get("research_units") or [])
        ]
        if configured_units:
            research_units = configured_units
        elif inputs.model_factory is not None:
            invoker = inputs.model_factory.create_structured_invoker(purpose="research_plan")
            plan = invoker.invoke_structured(
                schema=ResearchUnitPlan,
                system_prompt=(
                    "You plan bounded research units for an enzyme design workflow. "
                    "Return at most three concrete units with clear search queries."
                ),
                user_payload={
                    "episode_id": state.get("episode_id"),
                    "objective": state.get("objective"),
                    "design_brief": state.get("design_brief"),
                    "research_brief": state.get("research_brief"),
                },
            )
            research_units = [
                ResearchUnit(
                    unit_id=unit.unit_id,
                    topic=unit.topic,
                    query=unit.query,
                )
                for unit in plan.units
            ]
        else:
            research_units = _default_research_units(state)
        bounded_units = research_units[:max_research_units]
        research_brief = state.get("research_brief") or state.get("objective") or "OpenZyme research brief"
        return {
            "current_phase": GraphPhase.RESEARCH.value,
            "status": SupervisorStatus.ACTIVE.value,
            "research_brief": research_brief,
            "research_units": [unit.to_dict() for unit in bounded_units],
            "pending_interrupt": None,
            "progress": _progress(
                "plan_research",
                ProgressStatus.RUNNING,
                f"Dispatching {len(bounded_units)} research unit(s)",
            ),
        }

    def dispatch_research(state: ResearchSupervisorState) -> list[Send]:
        sends: list[Send] = []
        for payload in list(state.get("research_units") or []):
            sends.append(
                Send(
                    "run_research_unit",
                    {
                        "episode_id": state["episode_id"],
                        "research_brief": state["research_brief"],
                        "research_unit": payload,
                    },
                )
            )
        return sends

    def run_research_unit(state: ResearchWorkerState) -> dict[str, Any]:
        if inputs.research_adapter is None:
            msg = "research_adapter is required for the research node"
            raise RuntimeError(msg)
        unit = _unit_from_payload(state["research_unit"])
        result = inputs.research_adapter.conduct(
            episode_id=state["episode_id"],
            research_brief=state["research_brief"],
            unit=unit,
        )
        return {"worker_outputs": [result.to_dict()]}

    def aggregate_research(state: ResearchSupervisorState) -> dict[str, Any]:
        worker_outputs = list(state.get("worker_outputs") or [])
        escalated = [item for item in worker_outputs if item["status"] == "escalated"]
        failed = [item for item in worker_outputs if item["status"] == "failed"]
        completed = [item for item in worker_outputs if item["status"] == "completed"]

        if escalated:
            return {
                "current_phase": GraphPhase.RESEARCH.value,
                "status": SupervisorStatus.INTERRUPTED.value,
                "pending_interrupt": _build_interrupt_payload(
                    InterruptType.ESCALATION,
                    episode_id=state["episode_id"],
                    reason="research_escalation",
                    details={"worker_outputs": escalated},
                ),
                "progress": _progress(
                    "aggregate_research",
                    ProgressStatus.WAITING,
                    "Research requires escalation",
                ),
            }

        if failed and not completed:
            return {
                "current_phase": GraphPhase.RESEARCH.value,
                "status": SupervisorStatus.INTERRUPTED.value,
                "pending_interrupt": _build_interrupt_payload(
                    InterruptType.RECOVERABLE_FAILURE,
                    episode_id=state["episode_id"],
                    reason="research_unit_failed",
                    details={"worker_outputs": failed},
                ),
                "progress": _progress(
                    "aggregate_research",
                    ProgressStatus.FAILED,
                    "Research encountered a recoverable failure",
                ),
            }

        evidence_payloads: list[dict[str, Any]] = []
        unresolved_gap_payloads: list[str] = []
        summary_lines: list[str] = []
        for output in completed:
            if output["summary"]:
                summary_lines.append(str(output["summary"]))
            for finding in output["findings"]:
                evidence_payloads.append(dict(finding))
            unresolved_gap_payloads.extend(str(gap) for gap in output["unresolved_gaps"])

        if inputs.model_factory is not None:
            invoker = inputs.model_factory.create_structured_invoker(purpose="research_synthesis")
            synthesis = invoker.invoke_structured(
                schema=EvidenceSynthesis,
                system_prompt=(
                    "You synthesize completed research worker outputs into a canonical summary. "
                    "Preserve the main evidence themes and unresolved gaps."
                ),
                user_payload={
                    "episode_id": state.get("episode_id"),
                    "research_brief": state.get("research_brief"),
                    "worker_outputs": worker_outputs,
                },
            )
            research_summary_text = synthesis.summary
            unresolved_gap_payloads = synthesis.unresolved_gaps
        else:
            research_summary_text = " ".join(summary_lines).strip() or "Research completed without findings."
        return {
            "current_phase": GraphPhase.RESEARCH.value,
            "status": SupervisorStatus.ACTIVE.value,
            "pending_interrupt": None,
            "research_summary": {
                "summary": research_summary_text,
                "worker_count": len(completed),
            },
            "evidence_payloads": evidence_payloads,
            "unresolved_gap_payloads": unresolved_gap_payloads,
            "recommended_next_phase": GraphPhase.DESIGN.value,
            "progress": _progress(
                "aggregate_research",
                ProgressStatus.RUNNING,
                "Research findings aggregated",
            ),
        }

    def persist_research_outputs(state: ResearchSupervisorState) -> dict[str, Any]:
        episode_id = state["episode_id"]
        summary_text = str((state.get("research_summary") or {}).get("summary") or "")
        now = _utc_now_iso()
        if summary_text:
            inputs.repositories.research_summaries.save(
                ResearchSummaryRecord(
                    episode_id=episode_id,
                    summary=summary_text,
                    created_at=now,
                    updated_at=now,
                )
            )

        evidence_refs: list[dict[str, Any]] = []
        for index, payload in enumerate(list(state.get("evidence_payloads") or []), start=1):
            evidence_id = f"{episode_id}-evidence-{index}"
            record = EvidenceRecord(
                evidence_id=evidence_id,
                episode_id=episode_id,
                summary=str(payload["summary"]),
                query=str(payload["query"]),
                confidence_label=None if payload.get("confidence_label") is None else str(payload["confidence_label"]),
                created_at=now,
            )
            inputs.repositories.evidence_records.save(record)
            for source_index, source_payload in enumerate(payload.get("sources", []), start=1):
                source_ref = SourceRef(
                    source_ref_id=f"{evidence_id}-source-{source_index}",
                    evidence_id=evidence_id,
                    episode_id=episode_id,
                    title=str(source_payload["title"]),
                    locator=str(source_payload["locator"]),
                    kind=SourceRefKind(str(source_payload.get("kind", SourceRefKind.WEB_PAGE.value))),
                    created_at=now,
                )
                inputs.repositories.source_refs.save(source_ref)
            evidence_refs.append(
                {
                    "evidence_id": evidence_id,
                    "summary": record.summary,
                    "query": record.query,
                }
            )

        unresolved_gaps: list[dict[str, Any]] = []
        for index, summary in enumerate(list(state.get("unresolved_gap_payloads") or []), start=1):
            gap = UnresolvedGapRecord(
                gap_id=f"{episode_id}-gap-{index}",
                episode_id=episode_id,
                summary=summary,
                created_at=now,
            )
            inputs.repositories.unresolved_gaps.save(gap)
            unresolved_gaps.append(gap.to_dict())

        return {
            "status": SupervisorStatus.COMPLETED.value,
            "evidence_refs": evidence_refs,
            "unresolved_gaps": unresolved_gaps,
            "recommended_next_phase": GraphPhase.DESIGN.value,
            "progress": _progress(
                "persist_research_outputs",
                ProgressStatus.SUCCEEDED,
                "Research outputs persisted to canonical storage",
            ),
            "research_handoff": {
                "research_summary": dict(state.get("research_summary") or {}),
                "evidence_refs": evidence_refs,
                "unresolved_gaps": unresolved_gaps,
                "recommended_next_phase": GraphPhase.DESIGN.value,
            },
        }

    def route_after_aggregation(state: ResearchSupervisorState) -> str:
        if state.get("status") == SupervisorStatus.INTERRUPTED.value:
            return END
        return "persist_research_outputs"

    graph = StateGraph(ResearchSupervisorState)
    graph.add_node("plan_research", plan_research)
    graph.add_node("run_research_unit", run_research_unit)
    graph.add_node("aggregate_research", aggregate_research)
    graph.add_node("persist_research_outputs", persist_research_outputs)
    graph.add_edge(START, "plan_research")
    graph.add_conditional_edges("plan_research", dispatch_research, ["run_research_unit"])
    graph.add_edge("run_research_unit", "aggregate_research")
    graph.add_conditional_edges(
        "aggregate_research",
        route_after_aggregation,
        {
            "persist_research_outputs": "persist_research_outputs",
            END: END,
        },
    )
    graph.add_edge("persist_research_outputs", END)
    if include_checkpointer:
        return graph.compile(checkpointer=inputs.checkpointer)
    return graph.compile()
