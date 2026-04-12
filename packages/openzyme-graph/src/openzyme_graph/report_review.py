from __future__ import annotations

from datetime import UTC
from datetime import datetime
from typing import Any

from openzyme_domain import ArtifactKind
from openzyme_domain import ArtifactRecord
from openzyme_domain import ReportRecord
from openzyme_domain import ReportStatus
from openzyme_runtime.bootstrap import GraphAssemblyInputs


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def build_report_record_id(episode_id: str) -> str:
    return f"{episode_id}-report"


def build_report_artifact_id(episode_id: str) -> str:
    return f"{episode_id}-report-artifact"


def _build_report_storage_uri(episode_id: str) -> str:
    return f"/tmp/openzyme-reports/{episode_id}/final-report.md"


def create_canonical_report(
    inputs: GraphAssemblyInputs,
    state: dict[str, Any],
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
        title=f"Final report for {objective}",
        summary=(
            f"Objective '{objective}' completed with run "
            f"{run_summary.get('run_id', 'unknown')} in mode "
            f"{run_summary.get('execution_mode', 'unknown')}."
        ),
        stage_summary=(
            f"Research summary: {research_summary.get('summary', 'No research summary available.')} "
            f"Selected candidate: {state.get('selected_candidate_id', 'none')}. "
            f"Execution artifacts available: {len(artifact_refs)}."
        ),
        created_at=now,
        updated_at=now,
        artifact_id=report_artifact.artifact_id,
    )
    inputs.repositories.reports.save(report)
    return report, report_artifact
