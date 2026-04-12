from __future__ import annotations

from datetime import UTC
from datetime import datetime
from typing import Any
from typing import TypedDict

from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph
from openzyme_domain import ArtifactKind
from openzyme_domain import ArtifactRecord
from openzyme_domain import ReportRecord
from openzyme_domain import ReportStatus
from openzyme_runtime import ReportDraft
from openzyme_runtime.bootstrap import GraphAssemblyInputs

from .state import GraphPhase
from .state import ProgressStatus
from .state import SupervisorStatus


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def build_report_record_id(episode_id: str) -> str:
    return f"{episode_id}-report"


def build_report_artifact_id(episode_id: str) -> str:
    return f"{episode_id}-report-artifact"


def _build_report_storage_uri(episode_id: str) -> str:
    return f"/tmp/openzyme-reports/{episode_id}/final-report.md"


def _progress(active_node: str, status: ProgressStatus, message: str) -> dict[str, Any]:
    return {
        "phase": GraphPhase.REPORT_REVIEW.value,
        "active_node": active_node,
        "status": status.value,
        "updated_at": _utc_now_iso(),
        "message": message,
    }


class ReportReviewSubgraphState(TypedDict, total=False):
    episode_id: str
    objective: str
    user_goal: str
    current_phase: str
    status: str
    progress: dict[str, Any]
    pending_interrupt: dict[str, Any] | None
    research_summary: dict[str, Any] | None
    selected_candidate_id: str | None
    run_summary: dict[str, Any] | None
    artifact_refs: list[dict[str, Any]]
    report_summary: dict[str, Any] | None
    report_artifact_id: str | None
    report_draft: dict[str, Any] | None


def create_canonical_report(
    inputs: GraphAssemblyInputs,
    state: dict[str, Any],
    draft: ReportDraft | None = None,
) -> tuple[ReportRecord, ArtifactRecord]:
    episode_id = str(state["episode_id"])
    objective = str(state.get("objective") or state.get("user_goal") or "OpenZyme episode")
    run_summary = dict(state.get("run_summary") or {})
    artifact_refs = list(state.get("artifact_refs") or [])
    research_summary = dict(state.get("research_summary") or {})
    now = _utc_now_iso()

    report_artifact = ArtifactRecord(
        artifact_id=build_report_artifact_id(episode_id),
        episode_id=episode_id,
        run_id=None if run_summary.get("run_id") is None else str(run_summary["run_id"]),
        kind=ArtifactKind.REPORT,
        storage_uri=_build_report_storage_uri(episode_id),
        created_at=now,
    )
    inputs.repositories.artifact_records.save(report_artifact)

    report = ReportRecord(
        report_id=build_report_record_id(episode_id),
        episode_id=episode_id,
        run_id=None if run_summary.get("run_id") is None else str(run_summary["run_id"]),
        status=ReportStatus.READY,
        title=draft.title if draft is not None else f"Final report for {objective}",
        summary=(
            draft.summary
            if draft is not None
            else (
                f"Objective '{objective}' completed with run "
                f"{run_summary.get('run_id', 'unknown')} in mode "
                f"{run_summary.get('execution_mode', 'unknown')}."
            )
        ),
        stage_summary=(
            draft.stage_summary
            if draft is not None
            else (
                f"Research summary: {research_summary.get('summary', 'No research summary available.')} "
                f"Selected candidate: {state.get('selected_candidate_id', 'none')}. "
                f"Execution artifacts available: {len(artifact_refs)}."
            )
        ),
        created_at=now,
        updated_at=now,
        artifact_id=report_artifact.artifact_id,
    )
    inputs.repositories.reports.save(report)
    return report, report_artifact


def build_report_review_subgraph(inputs: GraphAssemblyInputs, *, include_checkpointer: bool = True) -> Any:
    def prepare_report_review(state: ReportReviewSubgraphState) -> dict[str, Any]:
        return {
            "current_phase": GraphPhase.REPORT_REVIEW.value,
            "status": SupervisorStatus.ACTIVE.value,
            "pending_interrupt": None,
            "progress": _progress(
                "prepare_report_review",
                ProgressStatus.RUNNING,
                "Preparing final report review",
            ),
        }

    def generate_report(state: ReportReviewSubgraphState) -> dict[str, Any]:
        draft: ReportDraft | None = None
        if inputs.model_factory is not None:
            invoker = inputs.model_factory.create_structured_invoker(purpose="report_review")
            draft = invoker.invoke_structured(
                schema=ReportDraft,
                system_prompt=(
                    "You write a concise final report for an enzyme design workflow. "
                    "Summarize the outcome, execution status, and key stage transitions."
                ),
                user_payload={
                    "episode_id": state.get("episode_id"),
                    "objective": state.get("objective") or state.get("user_goal"),
                    "research_summary": state.get("research_summary") or {},
                    "selected_candidate_id": state.get("selected_candidate_id"),
                    "run_summary": state.get("run_summary") or {},
                    "artifact_refs": state.get("artifact_refs") or [],
                },
            )
        report, artifact = create_canonical_report(inputs, state, draft=draft)
        return {
            "current_phase": GraphPhase.REPORT_REVIEW.value,
            "status": SupervisorStatus.COMPLETED.value,
            "pending_interrupt": None,
            "report_summary": report.to_dict(),
            "report_artifact_id": artifact.artifact_id,
            "report_draft": None if draft is None else draft.model_dump(),
            "progress": _progress(
                "generate_report",
                ProgressStatus.SUCCEEDED,
                "Final report generated",
            ),
        }

    graph = StateGraph(ReportReviewSubgraphState)
    graph.add_node("prepare_report_review", prepare_report_review)
    graph.add_node("generate_report", generate_report)
    graph.add_edge(START, "prepare_report_review")
    graph.add_edge("prepare_report_review", "generate_report")
    graph.add_edge("generate_report", END)
    if include_checkpointer:
        return graph.compile(checkpointer=inputs.checkpointer)
    return graph.compile()
