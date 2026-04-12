from __future__ import annotations

from datetime import UTC
from datetime import datetime
import operator
from typing import Annotated
from typing import Any
from typing import Literal
from typing import TypedDict

from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph
from langgraph.types import Command
from langgraph.types import Send
from langgraph.types import interrupt
from openzyme_domain import Approval
from openzyme_domain import ApprovalStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import ArtifactRecord
from openzyme_domain import CandidateRankingRecord
from openzyme_domain import CandidateRecord
from openzyme_domain import EvidenceRecord
from openzyme_domain import ReportRecord
from openzyme_domain import ReportStatus
from openzyme_domain import ResearchSummaryRecord
from openzyme_domain import Run
from openzyme_domain import RunStatus
from openzyme_domain import SelectedCandidateRecord
from openzyme_domain import SourceRef
from openzyme_domain import SourceRefKind
from openzyme_domain import UnresolvedGapRecord
from openzyme_research import ResearchUnit
from openzyme_runtime.bootstrap import GraphAssemblyInputs

from .report_review import create_canonical_report
from .state import GraphPhase
from .state import InterruptType
from .state import ProgressStatus
from .state import SupervisorStatus


MAX_RESEARCH_UNITS = 3


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _progress(
    phase: GraphPhase,
    active_node: str,
    status: ProgressStatus,
    message: str | None = None,
) -> dict[str, Any]:
    return {
        "phase": phase.value,
        "active_node": active_node,
        "status": status.value,
        "updated_at": _utc_now_iso(),
        "message": message,
    }


def _build_design_approval_id(episode_id: str) -> str:
    return f"{episode_id}-design-approval"


def _build_execution_approval_id(episode_id: str) -> str:
    return f"{episode_id}-execution-approval"


def _build_artifact_id(run_id: str, index: int) -> str:
    return f"{run_id}-artifact-{index}"


def _resolve_artifact_kind(value: str) -> ArtifactKind:
    try:
        return ArtifactKind(value)
    except ValueError:
        return ArtifactKind.RESULT


def _default_research_units(state: "UnifiedSupervisorState") -> list[ResearchUnit]:
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


def _unit_from_payload(payload: dict[str, Any]) -> ResearchUnit:
    return ResearchUnit(
        unit_id=str(payload["unit_id"]),
        topic=str(payload["topic"]),
        query=str(payload["query"]),
    )


def _build_interrupt_payload(
    interrupt_type: InterruptType,
    *,
    episode_id: str,
    phase: GraphPhase,
    reason: str,
    details: dict[str, Any] | None = None,
    approval_id: str | None = None,
    requested_action: str | None = None,
) -> dict[str, Any]:
    return {
        "type": interrupt_type.value,
        "episode_id": episode_id,
        "phase": phase.value,
        "reason": reason,
        "active_state_version": 1,
        "checkpoint_ns": phase.value,
        "checkpoint_id": f"{episode_id}-{phase.value}",
        "approval_id": approval_id,
        "requested_action": requested_action,
        "details": details,
    }


class ResearchWorkerOutputPayload(TypedDict):
    unit_id: str
    summary: str
    findings: list[dict[str, Any]]
    unresolved_gaps: list[str]
    error_message: str | None
    escalation_reason: str | None
    status: str


class UnifiedSupervisorState(TypedDict, total=False):
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
    recommended_next_phase: str | None
    research_units: list[dict[str, Any]]
    worker_outputs: Annotated[list[ResearchWorkerOutputPayload], operator.add]
    research_summary: dict[str, Any] | None
    evidence_payloads: list[dict[str, Any]]
    evidence_refs: list[dict[str, Any]]
    unresolved_gap_payloads: list[str]
    unresolved_gaps: list[dict[str, Any]]
    candidate_payloads: list[dict[str, Any]]
    ranking_payloads: list[dict[str, Any]]
    selected_candidate_id: str | None
    selected_candidate_rationale: str | None
    candidate_plan: dict[str, Any] | None
    run_request: dict[str, Any] | None
    approval_id: str | None
    approval_decision: dict[str, Any] | None
    run_summary: dict[str, Any] | None
    artifact_refs: list[dict[str, Any]]
    report_summary: dict[str, Any] | None
    report_artifact_id: str | None


class ResearchWorkerState(TypedDict):
    episode_id: str
    research_brief: str
    research_unit: dict[str, Any]


def build_v2_supervisor_graph(inputs: GraphAssemblyInputs) -> Any:
    def collect_intake(state: UnifiedSupervisorState) -> dict[str, Any]:
        objective = state.get("objective") or state.get("user_goal") or ""
        design_brief = state.get("design_brief") or f"Design brief for {objective}".strip()
        research_brief = state.get("research_brief") or f"Research brief for {objective}".strip()
        if state.get("run_request"):
            next_phase = GraphPhase.EXECUTION
        elif state.get("candidate_plan"):
            next_phase = GraphPhase.EXECUTION
        elif inputs.repositories.research_summaries.get_by_episode(state["episode_id"]) is not None:
            next_phase = GraphPhase.DESIGN
        else:
            next_phase = GraphPhase.RESEARCH
        return {
            "current_phase": GraphPhase.INTAKE.value,
            "status": SupervisorStatus.ACTIVE.value,
            "pending_interrupt": None,
            "design_brief": design_brief,
            "research_brief": research_brief,
            "recommended_next_phase": next_phase.value,
            "progress": _progress(
                GraphPhase.INTAKE,
                "collect_intake",
                ProgressStatus.SUCCEEDED,
                f"Intake completed; routing to {next_phase.value}",
            ),
        }

    def route_after_intake(state: UnifiedSupervisorState) -> str:
        next_phase = state.get("recommended_next_phase")
        if next_phase == GraphPhase.DESIGN.value:
            return "load_research_inputs"
        if next_phase == GraphPhase.EXECUTION.value:
            return "prepare_execution_approval"
        return "plan_research"

    def plan_research(state: UnifiedSupervisorState) -> dict[str, Any]:
        configured_units = [
            _unit_from_payload(payload)
            for payload in list(state.get("research_units") or [])
        ]
        research_units = configured_units or _default_research_units(state)
        bounded_units = research_units[:MAX_RESEARCH_UNITS]
        return {
            "current_phase": GraphPhase.RESEARCH.value,
            "status": SupervisorStatus.ACTIVE.value,
            "research_units": [unit.to_dict() for unit in bounded_units],
            "pending_interrupt": None,
            "recommended_next_phase": GraphPhase.DESIGN.value,
            "progress": _progress(
                GraphPhase.RESEARCH,
                "plan_research",
                ProgressStatus.RUNNING,
                f"Dispatching {len(bounded_units)} research unit(s)",
            ),
        }

    def dispatch_research(state: UnifiedSupervisorState) -> list[Send]:
        return [
            Send(
                "run_research_unit",
                {
                    "episode_id": state["episode_id"],
                    "research_brief": state["research_brief"],
                    "research_unit": payload,
                },
            )
            for payload in list(state.get("research_units") or [])
        ]

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

    def aggregate_research(state: UnifiedSupervisorState) -> dict[str, Any]:
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
                    phase=GraphPhase.RESEARCH,
                    reason="research_escalation",
                    details={"worker_outputs": escalated},
                ),
                "progress": _progress(
                    GraphPhase.RESEARCH,
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
                    phase=GraphPhase.RESEARCH,
                    reason="research_unit_failed",
                    details={"worker_outputs": failed},
                ),
                "progress": _progress(
                    GraphPhase.RESEARCH,
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
                GraphPhase.RESEARCH,
                "aggregate_research",
                ProgressStatus.RUNNING,
                "Research findings aggregated",
            ),
        }

    def route_after_research(state: UnifiedSupervisorState) -> str:
        if state.get("status") == SupervisorStatus.INTERRUPTED.value:
            return END
        return "persist_research_outputs"

    def persist_research_outputs(state: UnifiedSupervisorState) -> dict[str, Any]:
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
                inputs.repositories.source_refs.save(
                    SourceRef(
                        source_ref_id=f"{evidence_id}-source-{source_index}",
                        evidence_id=evidence_id,
                        episode_id=episode_id,
                        title=str(source_payload["title"]),
                        locator=str(source_payload["locator"]),
                        kind=SourceRefKind(str(source_payload.get("kind", SourceRefKind.WEB_PAGE.value))),
                        created_at=now,
                    )
                )
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
            "current_phase": GraphPhase.RESEARCH.value,
            "status": SupervisorStatus.ACTIVE.value,
            "evidence_refs": evidence_refs,
            "unresolved_gaps": unresolved_gaps,
            "recommended_next_phase": GraphPhase.DESIGN.value,
            "progress": _progress(
                GraphPhase.RESEARCH,
                "persist_research_outputs",
                ProgressStatus.SUCCEEDED,
                "Research outputs persisted to canonical storage",
            ),
        }

    def load_research_inputs(state: UnifiedSupervisorState) -> dict[str, Any]:
        episode_id = state["episode_id"]
        summary = inputs.repositories.research_summaries.get_by_episode(episode_id)
        evidence = inputs.repositories.evidence_records.list_by_episode(episode_id)
        if summary is None or not evidence:
            return {
                "current_phase": GraphPhase.DESIGN.value,
                "status": SupervisorStatus.INTERRUPTED.value,
                "pending_interrupt": _build_interrupt_payload(
                    InterruptType.RECOVERABLE_FAILURE,
                    episode_id=episode_id,
                    phase=GraphPhase.DESIGN,
                    reason="missing_research_outputs",
                    details={"research_summary": summary is not None, "evidence_count": len(evidence)},
                ),
                "progress": _progress(
                    GraphPhase.DESIGN,
                    "load_research_inputs",
                    ProgressStatus.FAILED,
                    "Design phase requires canonical research outputs",
                ),
            }
        return {
            "current_phase": GraphPhase.DESIGN.value,
            "status": SupervisorStatus.ACTIVE.value,
            "pending_interrupt": None,
            "research_summary": summary.to_dict(),
            "evidence_refs": [record.to_dict() for record in evidence],
            "recommended_next_phase": GraphPhase.EXECUTION.value,
            "progress": _progress(
                GraphPhase.DESIGN,
                "load_research_inputs",
                ProgressStatus.RUNNING,
                "Loaded research outputs for design ranking",
            ),
        }

    def route_after_research_load(state: UnifiedSupervisorState) -> str:
        if state.get("status") == SupervisorStatus.INTERRUPTED.value:
            return END
        return "generate_candidates"

    def generate_candidates(state: UnifiedSupervisorState) -> dict[str, Any]:
        evidence_refs = list(state.get("evidence_refs") or [])
        research_summary = str((state.get("research_summary") or {}).get("summary") or "")
        candidate_payloads: list[dict[str, Any]] = []
        for index, evidence in enumerate(evidence_refs[:2], start=1):
            candidate_id = f"{state['episode_id']}-candidate-{index}"
            candidate_payloads.append(
                {
                    "candidate_id": candidate_id,
                    "title": f"Candidate {index}",
                    "summary": f"{research_summary} Focus on evidence: {evidence['summary']}",
                    "supporting_evidence_ids": [evidence["evidence_id"]],
                }
            )
        return {
            "candidate_payloads": candidate_payloads,
            "progress": _progress(
                GraphPhase.DESIGN,
                "generate_candidates",
                ProgressStatus.RUNNING,
                f"Generated {len(candidate_payloads)} candidate option(s)",
            ),
        }

    def rank_candidates(state: UnifiedSupervisorState) -> dict[str, Any]:
        candidate_payloads = list(state.get("candidate_payloads") or [])
        ranking_payloads: list[dict[str, Any]] = []
        for index, candidate in enumerate(candidate_payloads, start=1):
            ranking_payloads.append(
                {
                    "ranking_id": f"{candidate['candidate_id']}-ranking",
                    "candidate_id": candidate["candidate_id"],
                    "rank": index,
                    "rationale": f"Candidate {index} ranked from current research coverage.",
                }
            )
        selected_candidate = candidate_payloads[0] if candidate_payloads else None
        return {
            "ranking_payloads": ranking_payloads,
            "selected_candidate_id": None if selected_candidate is None else selected_candidate["candidate_id"],
            "selected_candidate_rationale": None
            if selected_candidate is None
            else "Top-ranked candidate selected from canonical research evidence.",
            "progress": _progress(
                GraphPhase.DESIGN,
                "rank_candidates",
                ProgressStatus.RUNNING,
                "Ranked design candidates for review",
            ),
        }

    def persist_candidates(state: UnifiedSupervisorState) -> dict[str, Any]:
        now = _utc_now_iso()
        for payload in list(state.get("candidate_payloads") or []):
            inputs.repositories.candidates.save(
                CandidateRecord(
                    candidate_id=str(payload["candidate_id"]),
                    episode_id=state["episode_id"],
                    title=str(payload["title"]),
                    summary=str(payload["summary"]),
                    supporting_evidence_ids=tuple(str(item) for item in payload["supporting_evidence_ids"]),
                    created_at=now,
                )
            )
        for payload in list(state.get("ranking_payloads") or []):
            inputs.repositories.candidate_rankings.save(
                CandidateRankingRecord(
                    ranking_id=str(payload["ranking_id"]),
                    episode_id=state["episode_id"],
                    candidate_id=str(payload["candidate_id"]),
                    rank=int(payload["rank"]),
                    rationale=str(payload["rationale"]),
                    created_at=now,
                )
            )
        return {
            "progress": _progress(
                GraphPhase.DESIGN,
                "persist_candidates",
                ProgressStatus.RUNNING,
                "Persisted candidate options and rankings",
            ),
        }

    def prepare_design_review(state: UnifiedSupervisorState) -> dict[str, Any]:
        approval_id = state.get("approval_id") or _build_design_approval_id(state["episode_id"])
        requested_action = f"Approve selected candidate {state['selected_candidate_id']} for execution handoff"
        inputs.repositories.approvals.save(
            Approval(
                approval_id=approval_id,
                episode_id=state["episode_id"],
                status=ApprovalStatus.PENDING,
                requested_action=requested_action,
                created_at=_utc_now_iso(),
            )
        )
        return {
            "approval_id": approval_id,
            "current_phase": GraphPhase.DESIGN.value,
            "status": SupervisorStatus.INTERRUPTED.value,
            "pending_interrupt": _build_interrupt_payload(
                InterruptType.APPROVAL,
                episode_id=state["episode_id"],
                phase=GraphPhase.DESIGN,
                reason="design_review_required",
                approval_id=approval_id,
                requested_action=requested_action,
            ),
            "progress": _progress(
                GraphPhase.DESIGN,
                "design_review_gate",
                ProgressStatus.WAITING,
                "Waiting for candidate review approval",
            ),
        }

    def design_review_gate(
        state: UnifiedSupervisorState,
    ) -> Command[Literal["map_execution_handoff", "__end__"]]:
        decision = interrupt(state["pending_interrupt"])
        approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
        approval_id = str(state["approval_id"])
        inputs.repositories.approvals.save(
            Approval(
                approval_id=approval_id,
                episode_id=state["episode_id"],
                status=ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED,
                requested_action=f"Approve selected candidate {state['selected_candidate_id']} for execution handoff",
                created_at=_utc_now_iso(),
                resolved_at=_utc_now_iso(),
            )
        )
        if not approved:
            return Command(
                update={
                    "approval_decision": {"approved": False},
                    "pending_interrupt": None,
                    "status": SupervisorStatus.FAILED.value,
                    "progress": _progress(
                        GraphPhase.DESIGN,
                        "design_review_gate",
                        ProgressStatus.FAILED,
                        "Design candidate review rejected",
                    ),
                },
                goto=END,
            )
        inputs.repositories.selected_candidates.save(
            SelectedCandidateRecord(
                episode_id=state["episode_id"],
                candidate_id=str(state["selected_candidate_id"]),
                rationale=str(state["selected_candidate_rationale"]),
                selected_at=_utc_now_iso(),
            )
        )
        return Command(
            update={
                "approval_decision": {"approved": True},
                "pending_interrupt": None,
                "status": SupervisorStatus.ACTIVE.value,
                "progress": _progress(
                    GraphPhase.DESIGN,
                    "map_execution_handoff",
                    ProgressStatus.RUNNING,
                    "Candidate approved; mapping execution handoff",
                ),
            },
            goto="map_execution_handoff",
        )

    def map_execution_handoff(state: UnifiedSupervisorState) -> dict[str, Any]:
        selected = inputs.repositories.selected_candidates.get_by_episode(state["episode_id"])
        if selected is None:
            msg = "selected candidate must be persisted before execution handoff"
            raise RuntimeError(msg)
        candidate = inputs.repositories.candidates.get(selected.candidate_id)
        if candidate is None:
            msg = f"candidate {selected.candidate_id!r} does not exist"
            raise RuntimeError(msg)
        candidate_plan = {
            "candidate_id": candidate.candidate_id,
            "title": candidate.title,
            "summary": candidate.summary,
        }
        run_request = {
            "tool_name": "exec.run",
            "runspec": {
                "name": f"execution-{candidate.candidate_id}",
                "stage": "execution",
                "command": ["echo", candidate.title],
                "execution_mode": "auto",
                "metadata": {
                    "candidate_id": candidate.candidate_id,
                    "supporting_evidence_ids": list(candidate.supporting_evidence_ids),
                },
            },
        }
        return {
            "current_phase": GraphPhase.DESIGN.value,
            "candidate_plan": candidate_plan,
            "run_request": run_request,
            "recommended_next_phase": GraphPhase.EXECUTION.value,
            "status": SupervisorStatus.ACTIVE.value,
            "progress": _progress(
                GraphPhase.DESIGN,
                "map_execution_handoff",
                ProgressStatus.SUCCEEDED,
                "Mapped selected candidate into execution contract",
            ),
        }

    def prepare_execution_approval(state: UnifiedSupervisorState) -> dict[str, Any]:
        approval_id = _build_execution_approval_id(state["episode_id"])
        inputs.repositories.approvals.save(
            Approval(
                approval_id=approval_id,
                episode_id=state["episode_id"],
                status=ApprovalStatus.PENDING,
                requested_action="Approve execution submission",
                created_at=_utc_now_iso(),
            )
        )
        return {
            "approval_id": approval_id,
            "pending_interrupt": _build_interrupt_payload(
                InterruptType.APPROVAL,
                episode_id=state["episode_id"],
                phase=GraphPhase.EXECUTION,
                reason="execution_approval_required",
                approval_id=approval_id,
                requested_action="Approve execution submission",
            ),
            "current_phase": GraphPhase.EXECUTION.value,
            "status": SupervisorStatus.INTERRUPTED.value,
            "progress": _progress(
                GraphPhase.EXECUTION,
                "approval_gate",
                ProgressStatus.WAITING,
                "Waiting for approval",
            ),
        }

    def execution_approval_gate(
        state: UnifiedSupervisorState,
    ) -> Command[Literal["execute_runner", "__end__"]]:
        decision = interrupt(state["pending_interrupt"])
        approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
        approval_id = str(state["approval_id"])
        inputs.repositories.approvals.save(
            Approval(
                approval_id=approval_id,
                episode_id=state["episode_id"],
                status=ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED,
                requested_action="Approve execution submission",
                created_at=_utc_now_iso(),
                resolved_at=_utc_now_iso(),
            )
        )
        if not approved:
            return Command(
                update={
                    "approval_decision": {"approved": False},
                    "pending_interrupt": None,
                    "status": SupervisorStatus.FAILED.value,
                    "progress": _progress(
                        GraphPhase.EXECUTION,
                        "approval_gate",
                        ProgressStatus.FAILED,
                        "Execution rejected",
                    ),
                },
                goto=END,
            )
        return Command(
            update={
                "approval_decision": {"approved": True},
                "pending_interrupt": None,
                "current_phase": GraphPhase.EXECUTION.value,
                "status": SupervisorStatus.ACTIVE.value,
                "progress": _progress(
                    GraphPhase.EXECUTION,
                    "execute_runner",
                    ProgressStatus.RUNNING,
                    "Approval received; executing runner",
                ),
            },
            goto="execute_runner",
        )

    def execute_runner(state: UnifiedSupervisorState) -> dict[str, Any]:
        if inputs.execution_adapter is None:
            msg = "execution_adapter is required for the execution node"
            raise RuntimeError(msg)
        if state.get("run_request") is None:
            msg = "run_request is required for execution"
            raise RuntimeError(msg)
        outcome = inputs.execution_adapter.submit_execution(
            state["episode_id"],
            state["run_request"],
        )
        completed_at = _utc_now_iso() if outcome.status.is_terminal else None
        inputs.repositories.runs.save(
            Run(
                run_id=outcome.run_id,
                episode_id=state["episode_id"],
                approval_id=state.get("approval_id"),
                status=outcome.status,
                execution_mode=outcome.execution_mode,
                created_at=_utc_now_iso(),
                completed_at=completed_at,
            )
        )

        artifact_payloads: list[dict[str, Any]] = []
        for index, artifact in enumerate(outcome.artifacts, start=1):
            record = ArtifactRecord(
                artifact_id=_build_artifact_id(outcome.run_id, index),
                episode_id=state["episode_id"],
                run_id=outcome.run_id,
                kind=_resolve_artifact_kind(artifact.kind.value),
                storage_uri=artifact.storage_uri,
                created_at=_utc_now_iso(),
            )
            inputs.repositories.artifact_records.save(record)
            artifact_payloads.append(
                {
                    "artifact_id": record.artifact_id,
                    "kind": record.kind.value,
                    "storage_uri": record.storage_uri,
                }
            )
        return {
            "current_phase": GraphPhase.EXECUTION.value,
            "recommended_next_phase": (
                GraphPhase.REPORT_REVIEW.value
                if outcome.status is RunStatus.SUCCEEDED
                else None
            ),
            "status": (
                SupervisorStatus.ACTIVE.value
                if outcome.status is RunStatus.SUCCEEDED
                else SupervisorStatus.FAILED.value
            ),
            "run_summary": {
                "run_id": outcome.run_id,
                "status": outcome.status.value,
                "execution_mode": outcome.execution_mode,
                "remote_run_dir": outcome.remote_run_dir,
            },
            "artifact_refs": artifact_payloads,
            "progress": _progress(
                GraphPhase.EXECUTION,
                "execute_runner",
                ProgressStatus.SUCCEEDED
                if outcome.status is RunStatus.SUCCEEDED
                else ProgressStatus.FAILED,
                "Runner execution finished"
                if outcome.status is not RunStatus.SUCCEEDED
                else "Runner execution finished; handing off to report review",
            ),
        }

    def route_after_execution(state: UnifiedSupervisorState) -> str:
        if state.get("status") == SupervisorStatus.FAILED.value:
            return END
        return "prepare_report_review"

    def prepare_report_review(state: UnifiedSupervisorState) -> dict[str, Any]:
        return {
            "current_phase": GraphPhase.REPORT_REVIEW.value,
            "status": SupervisorStatus.ACTIVE.value,
            "pending_interrupt": None,
            "progress": _progress(
                GraphPhase.REPORT_REVIEW,
                "prepare_report_review",
                ProgressStatus.RUNNING,
                "Preparing final report review inputs",
            ),
        }

    def generate_report(state: UnifiedSupervisorState) -> dict[str, Any]:
        report, report_artifact = create_canonical_report(inputs, state)
        return {
            "current_phase": GraphPhase.REPORT_REVIEW.value,
            "status": SupervisorStatus.COMPLETED.value,
            "recommended_next_phase": None,
            "pending_interrupt": None,
            "report_summary": report.to_dict(),
            "report_artifact_id": report_artifact.artifact_id,
            "progress": _progress(
                GraphPhase.REPORT_REVIEW,
                "generate_report",
                ProgressStatus.SUCCEEDED,
                "Report review finished and canonical report persisted",
            ),
        }

    graph = StateGraph(UnifiedSupervisorState)
    graph.add_node("collect_intake", collect_intake)
    graph.add_node("plan_research", plan_research)
    graph.add_node("run_research_unit", run_research_unit)
    graph.add_node("aggregate_research", aggregate_research)
    graph.add_node("persist_research_outputs", persist_research_outputs)
    graph.add_node("load_research_inputs", load_research_inputs)
    graph.add_node("generate_candidates", generate_candidates)
    graph.add_node("rank_candidates", rank_candidates)
    graph.add_node("persist_candidates", persist_candidates)
    graph.add_node("prepare_design_review", prepare_design_review)
    graph.add_node("design_review_gate", design_review_gate)
    graph.add_node("map_execution_handoff", map_execution_handoff)
    graph.add_node("prepare_execution_approval", prepare_execution_approval)
    graph.add_node("execution_approval_gate", execution_approval_gate)
    graph.add_node("execute_runner", execute_runner)
    graph.add_node("prepare_report_review", prepare_report_review)
    graph.add_node("generate_report", generate_report)

    graph.add_edge(START, "collect_intake")
    graph.add_conditional_edges(
        "collect_intake",
        route_after_intake,
        {
            "plan_research": "plan_research",
            "load_research_inputs": "load_research_inputs",
            "prepare_execution_approval": "prepare_execution_approval",
        },
    )
    graph.add_conditional_edges("plan_research", dispatch_research, ["run_research_unit"])
    graph.add_edge("run_research_unit", "aggregate_research")
    graph.add_conditional_edges(
        "aggregate_research",
        route_after_research,
        {
            "persist_research_outputs": "persist_research_outputs",
            END: END,
        },
    )
    graph.add_edge("persist_research_outputs", "load_research_inputs")
    graph.add_conditional_edges(
        "load_research_inputs",
        route_after_research_load,
        {
            "generate_candidates": "generate_candidates",
            END: END,
        },
    )
    graph.add_edge("generate_candidates", "rank_candidates")
    graph.add_edge("rank_candidates", "persist_candidates")
    graph.add_edge("persist_candidates", "prepare_design_review")
    graph.add_edge("prepare_design_review", "design_review_gate")
    graph.add_edge("map_execution_handoff", "prepare_execution_approval")
    graph.add_edge("prepare_execution_approval", "execution_approval_gate")
    graph.add_conditional_edges(
        "execute_runner",
        route_after_execution,
        {
            "prepare_report_review": "prepare_report_review",
            END: END,
        },
    )
    graph.add_edge("prepare_report_review", "generate_report")
    graph.add_edge("generate_report", END)
    return graph.compile(checkpointer=inputs.checkpointer)
