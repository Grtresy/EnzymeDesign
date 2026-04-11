from __future__ import annotations

from datetime import UTC
from datetime import datetime
from typing import Any
from typing import Literal
from typing import TypedDict

from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph
from langgraph.types import Command
from langgraph.types import interrupt
from openzyme_domain import Approval
from openzyme_domain import ApprovalStatus
from openzyme_domain import CandidateRankingRecord
from openzyme_domain import CandidateRecord
from openzyme_domain import SelectedCandidateRecord
from openzyme_runtime.bootstrap import GraphAssemblyInputs

from .state import GraphPhase
from .state import InterruptType
from .state import ProgressStatus
from .state import SupervisorStatus


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _progress(active_node: str, status: ProgressStatus, message: str) -> dict[str, Any]:
    return {
        "phase": GraphPhase.DESIGN.value,
        "active_node": active_node,
        "status": status.value,
        "updated_at": _utc_now_iso(),
        "message": message,
    }


class DesignSupervisorState(TypedDict, total=False):
    episode_id: str
    project_id: str
    objective: str
    current_phase: str
    status: str
    progress: dict[str, Any]
    pending_interrupt: dict[str, Any] | None
    research_summary: dict[str, Any] | None
    evidence_refs: list[dict[str, Any]]
    candidate_payloads: list[dict[str, Any]]
    ranking_payloads: list[dict[str, Any]]
    selected_candidate_id: str | None
    selected_candidate_rationale: str | None
    approval_id: str | None
    approval_decision: dict[str, Any] | None
    candidate_plan: dict[str, Any] | None
    run_request: dict[str, Any] | None
    recommended_next_phase: str | None


def _design_interrupt(
    *,
    episode_id: str,
    approval_id: str,
    requested_action: str,
) -> dict[str, Any]:
    return {
        "type": InterruptType.APPROVAL.value,
        "episode_id": episode_id,
        "phase": GraphPhase.DESIGN.value,
        "approval_id": approval_id,
        "requested_action": requested_action,
    }


def _build_design_approval_id(episode_id: str) -> str:
    return f"{episode_id}-design-approval"


def build_phase_c_design_graph(inputs: GraphAssemblyInputs) -> Any:
    def load_research_inputs(state: DesignSupervisorState) -> dict[str, Any]:
        episode_id = state["episode_id"]
        summary = inputs.repositories.research_summaries.get_by_episode(episode_id)
        evidence = inputs.repositories.evidence_records.list_by_episode(episode_id)
        if summary is None or not evidence:
            return {
                "current_phase": GraphPhase.DESIGN.value,
                "status": SupervisorStatus.INTERRUPTED.value,
                "pending_interrupt": {
                    "type": InterruptType.RECOVERABLE_FAILURE.value,
                    "episode_id": episode_id,
                    "phase": GraphPhase.DESIGN.value,
                    "reason": "missing_research_outputs",
                    "active_state_version": 1,
                    "checkpoint_ns": "design",
                    "checkpoint_id": f"{episode_id}-design",
                    "approval_id": None,
                    "requested_action": None,
                    "details": {"research_summary": summary is not None, "evidence_count": len(evidence)},
                },
                "progress": _progress(
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
            "progress": _progress(
                "load_research_inputs",
                ProgressStatus.RUNNING,
                "Loaded research outputs for design ranking",
            ),
        }

    def generate_candidates(state: DesignSupervisorState) -> dict[str, Any]:
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
                "generate_candidates",
                ProgressStatus.RUNNING,
                f"Generated {len(candidate_payloads)} candidate option(s)",
            ),
        }

    def rank_candidates(state: DesignSupervisorState) -> dict[str, Any]:
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
                "rank_candidates",
                ProgressStatus.RUNNING,
                "Ranked design candidates for review",
            ),
        }

    def persist_candidates(state: DesignSupervisorState) -> dict[str, Any]:
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
                "persist_candidates",
                ProgressStatus.RUNNING,
                "Persisted candidate options and rankings",
            ),
        }

    def prepare_design_review(state: DesignSupervisorState) -> dict[str, Any]:
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
            "pending_interrupt": _design_interrupt(
                episode_id=state["episode_id"],
                approval_id=approval_id,
                requested_action=requested_action,
            ),
            "progress": _progress(
                "design_review_gate",
                ProgressStatus.WAITING,
                "Waiting for candidate review approval",
            ),
        }

    def design_review_gate(
        state: DesignSupervisorState,
    ) -> Command[Literal["map_execution_handoff", "__end__"]]:
        approval_id = str(state["approval_id"])
        decision = interrupt(state["pending_interrupt"])
        approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
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
                    "map_execution_handoff",
                    ProgressStatus.RUNNING,
                    "Candidate approved; mapping execution handoff",
                ),
            },
            goto="map_execution_handoff",
        )

    def map_execution_handoff(state: DesignSupervisorState) -> dict[str, Any]:
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
            "candidate_plan": candidate_plan,
            "run_request": run_request,
            "recommended_next_phase": GraphPhase.EXECUTION.value,
            "status": SupervisorStatus.COMPLETED.value,
            "progress": _progress(
                "map_execution_handoff",
                ProgressStatus.SUCCEEDED,
                "Mapped selected candidate into execution contract",
            ),
        }

    def route_after_research_load(state: DesignSupervisorState) -> str:
        if state.get("status") == SupervisorStatus.INTERRUPTED.value:
            return END
        return "generate_candidates"

    graph = StateGraph(DesignSupervisorState)
    graph.add_node("load_research_inputs", load_research_inputs)
    graph.add_node("generate_candidates", generate_candidates)
    graph.add_node("rank_candidates", rank_candidates)
    graph.add_node("persist_candidates", persist_candidates)
    graph.add_node("prepare_design_review", prepare_design_review)
    graph.add_node("design_review_gate", design_review_gate)
    graph.add_node("map_execution_handoff", map_execution_handoff)
    graph.add_edge(START, "load_research_inputs")
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
    graph.add_edge("map_execution_handoff", END)
    return graph.compile(checkpointer=inputs.checkpointer)
