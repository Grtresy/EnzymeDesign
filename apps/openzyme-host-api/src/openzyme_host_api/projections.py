from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from typing import Any
from typing import Callable

from openzyme_domain import EpisodeStatus
from openzyme_domain import SourceRef
from openzyme_graph import GraphPhase
from openzyme_graph import ProgressStatus
from openzyme_runtime import GraphRuntimeFacade
from openzyme_runtime import ProjectionLoader


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _default_progress(updated_at: str) -> dict[str, Any]:
    return {
        "phase": GraphPhase.INTAKE.value,
        "active_node": "host",
        "status": ProgressStatus.IDLE.value,
        "updated_at": updated_at,
        "message": "Episode created; graph execution has not produced progress yet.",
    }


def _derive_episode_status(workflow: dict[str, Any]) -> EpisodeStatus:
    status = workflow.get("status")
    if status == "completed":
        return EpisodeStatus.COMPLETED
    if status == "failed":
        return EpisodeStatus.FAILED
    if status == "interrupted":
        return EpisodeStatus.INTERRUPTED
    return EpisodeStatus.ACTIVE


def _build_workflow_summary(
    workflow: dict[str, Any],
    research: dict[str, Any],
    design: dict[str, Any],
    report: dict[str, Any] | None,
) -> dict[str, Any]:
    selected_candidate = design.get("selected_candidate")
    return {
        "current_phase": workflow["current_phase"],
        "workflow_status": workflow["status"],
        "active_node": workflow["progress"]["active_node"],
        "message": workflow["progress"]["message"],
        "wait_state": None if workflow["pending_interrupt"] is None else workflow["pending_interrupt"]["type"],
        "evidence_count": len(research.get("evidence", [])),
        "candidate_count": len(design.get("candidates", [])),
        "selected_candidate_id": None
        if selected_candidate is None
        else selected_candidate["candidate_id"],
        "report_id": None if report is None else report["report_id"],
        "report_status": None if report is None else report["status"],
    }


GraphBuilder = Callable[[Any], Any]


def _group_source_refs_by_evidence(source_refs: list[SourceRef]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for source_ref in source_refs:
        grouped.setdefault(source_ref.evidence_id, []).append(source_ref.to_dict())
    return grouped


@dataclass(slots=True)
class HostProjectionLoader(ProjectionLoader):
    runtime: GraphRuntimeFacade
    graph_builder: GraphBuilder

    def load_workflow_projection(self, episode_id: str) -> dict[str, Any]:
        episode = self.runtime.repositories.episodes.get(episode_id)
        if episode is None:
            msg = f"episode {episode_id!r} does not exist"
            raise KeyError(msg)

        pending = self.runtime.repositories.approvals.list_pending_by_episode(episode_id)
        with self.runtime.compile_graph(self.graph_builder) as graph:
            snapshot = graph.get_state(self.runtime.build_episode_graph_config(episode_id))

        values = dict(snapshot.values)
        progress = values.get("progress") or _default_progress(episode.updated_at)
        workflow = {
            "episode_id": episode.episode_id,
            "project_id": episode.project_id,
            "objective": episode.objective,
            "episode_status": episode.status.value,
            "current_phase": values.get("current_phase", GraphPhase.INTAKE.value),
            "status": values.get("status", episode.status.value),
            "progress": progress,
            "pending_interrupt": values.get("pending_interrupt"),
            "pending_approval": None if not pending else pending[0].to_dict(),
            "updated_at": progress["updated_at"],
        }
        return workflow

    def load_run_projection(self, episode_id: str) -> list[dict[str, Any]]:
        return [run.to_dict() for run in self.runtime.repositories.runs.list_by_episode(episode_id)]

    def load_artifact_projection(self, episode_id: str) -> list[dict[str, Any]]:
        return [
            artifact.to_dict()
            for artifact in self.runtime.repositories.artifact_records.list_by_episode(episode_id)
        ]

    def load_report_projection(self, episode_id: str) -> dict[str, Any] | None:
        reports = self.runtime.repositories.reports.list_by_episode(episode_id)
        if not reports:
            return None
        report = reports[-1].to_dict()
        artifact_id = report.get("artifact_id")
        artifact = None if artifact_id is None else self.runtime.repositories.artifact_records.get(artifact_id)
        report["artifact_storage_uri"] = None if artifact is None else artifact.storage_uri
        return report

    def load_pending_actions(self, episode_id: str) -> list[dict[str, Any]]:
        return [
            approval.to_dict()
            for approval in self.runtime.repositories.approvals.list_pending_by_episode(episode_id)
        ]

    def load_research_projection(self, episode_id: str) -> dict[str, Any]:
        evidence_records = self.runtime.repositories.evidence_records.list_by_episode(episode_id)
        source_refs = self.runtime.repositories.source_refs.list_by_episode(episode_id)
        grouped_source_refs = _group_source_refs_by_evidence(source_refs)
        evidence: list[dict[str, Any]] = []
        for record in evidence_records:
            item = record.to_dict()
            item["source_refs"] = grouped_source_refs.get(record.evidence_id, [])
            evidence.append(item)

        summary = self.runtime.repositories.research_summaries.get_by_episode(episode_id)
        unresolved_gaps = self.runtime.repositories.unresolved_gaps.list_by_episode(episode_id)
        return {
            "summary": None if summary is None else summary.to_dict(),
            "evidence": evidence,
            "source_refs": [source_ref.to_dict() for source_ref in source_refs],
            "unresolved_gaps": [gap.to_dict() for gap in unresolved_gaps],
        }

    def load_design_projection(self, episode_id: str) -> dict[str, Any]:
        candidates = [candidate.to_dict() for candidate in self.runtime.repositories.candidates.list_by_episode(episode_id)]
        rankings = [ranking.to_dict() for ranking in self.runtime.repositories.candidate_rankings.list_by_episode(episode_id)]
        selected_candidate = self.runtime.repositories.selected_candidates.get_by_episode(episode_id)
        ranking_by_candidate_id = {ranking["candidate_id"]: ranking for ranking in rankings}
        enriched_candidates: list[dict[str, Any]] = []
        for candidate in candidates:
            item = dict(candidate)
            item["ranking"] = ranking_by_candidate_id.get(candidate["candidate_id"])
            enriched_candidates.append(item)
        return {
            "candidates": enriched_candidates,
            "rankings": rankings,
            "selected_candidate": None if selected_candidate is None else selected_candidate.to_dict(),
        }

    def load_episode_workspace(self, episode_id: str) -> dict[str, Any]:
        workflow = self.load_workflow_projection(episode_id)
        workflow["episode_status"] = _derive_episode_status(workflow).value
        research = self.load_research_projection(episode_id)
        design = self.load_design_projection(episode_id)
        report = self.load_report_projection(episode_id)
        workflow["summary"] = _build_workflow_summary(workflow, research, design, report)
        return {
            "episode_id": episode_id,
            "workflow": workflow,
            "pending_actions": self.load_pending_actions(episode_id),
            "runs": self.load_run_projection(episode_id),
            "artifacts": self.load_artifact_projection(episode_id),
            "research": research,
            "design": design,
            "report": report,
        }

    def list_projects(self) -> list[dict[str, Any]]:
        rows = self.runtime.repositories.projects.connection.execute(
            "SELECT * FROM projects ORDER BY created_at, project_id"
        ).fetchall()
        return [dict(row) for row in rows]

    def list_project_episodes(self, project_id: str) -> list[dict[str, Any]]:
        episodes = self.runtime.repositories.episodes.list_by_project(project_id)
        return [episode.to_dict() for episode in episodes]


@dataclass(frozen=True, slots=True)
class WorkflowEventProjector:
    def project_snapshot_events(self, workspace: dict[str, Any]) -> list[dict[str, Any]]:
        workflow = workspace["workflow"]
        events: list[dict[str, Any]] = [
            {
                "event_type": "workflow.phase_changed",
                "episode_id": workspace["episode_id"],
                "phase": workflow["current_phase"],
                "updated_at": workflow["updated_at"],
            },
            {
                "event_type": "workflow.progress_updated",
                "episode_id": workspace["episode_id"],
                "progress": workflow["progress"],
                "updated_at": workflow["progress"]["updated_at"],
            },
            {
                "event_type": "workflow.summary_updated",
                "episode_id": workspace["episode_id"],
                "summary": workflow["summary"],
                "updated_at": workflow["updated_at"],
            },
        ]
        if workflow["pending_interrupt"] is not None:
            events.append(
                {
                    "event_type": "workflow.interrupt_pending",
                    "episode_id": workspace["episode_id"],
                    "interrupt": workflow["pending_interrupt"],
                    "updated_at": workflow["updated_at"],
                }
            )
        if workflow["pending_approval"] is not None:
            events.append(
                {
                    "event_type": "workflow.approval_pending",
                    "episode_id": workspace["episode_id"],
                    "approval": workflow["pending_approval"],
                    "updated_at": workflow["pending_approval"]["created_at"],
                }
            )
        for run in workspace["runs"]:
            events.append(
                {
                    "event_type": "workflow.run_status_changed",
                    "episode_id": workspace["episode_id"],
                    "run": run,
                    "updated_at": run["completed_at"] or run["created_at"],
                }
            )
        for artifact in workspace["artifacts"]:
            events.append(
                {
                    "event_type": "workflow.artifact_available",
                    "episode_id": workspace["episode_id"],
                    "artifact": artifact,
                    "updated_at": artifact["created_at"],
                }
            )
        if workspace["report"] is not None:
            events.append(
                {
                    "event_type": "workflow.report_available",
                    "episode_id": workspace["episode_id"],
                    "report": workspace["report"],
                    "updated_at": workspace["report"]["updated_at"],
                }
            )
        if workspace["research"]["evidence"] or workspace["research"]["summary"] is not None:
            events.append(
                {
                    "event_type": "workflow.evidence_updated",
                    "episode_id": workspace["episode_id"],
                    "research": workspace["research"],
                    "updated_at": workflow["updated_at"],
                }
            )
        if workspace["design"]["candidates"] or workspace["design"]["selected_candidate"] is not None:
            events.append(
                {
                    "event_type": "workflow.candidate_updated",
                    "episode_id": workspace["episode_id"],
                    "design": workspace["design"],
                    "updated_at": workflow["updated_at"],
                }
            )
        if workspace["design"]["selected_candidate"] is not None:
            events.append(
                {
                    "event_type": "workflow.selected_candidate_changed",
                    "episode_id": workspace["episode_id"],
                    "selected_candidate": workspace["design"]["selected_candidate"],
                    "updated_at": workflow["updated_at"],
                }
            )
        return events

    def project_delta_events(
        self,
        before: dict[str, Any] | None,
        after: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if before is None:
            return self.project_snapshot_events(after)

        events: list[dict[str, Any]] = []
        before_workflow = before["workflow"]
        after_workflow = after["workflow"]

        if before_workflow["current_phase"] != after_workflow["current_phase"]:
            events.append(
                {
                    "event_type": "workflow.phase_changed",
                    "episode_id": after["episode_id"],
                    "phase": after_workflow["current_phase"],
                    "updated_at": after_workflow["updated_at"],
                }
            )
        if before_workflow["progress"] != after_workflow["progress"]:
            events.append(
                {
                    "event_type": "workflow.progress_updated",
                    "episode_id": after["episode_id"],
                    "progress": after_workflow["progress"],
                    "updated_at": after_workflow["progress"]["updated_at"],
                }
            )
        if before_workflow.get("summary") != after_workflow.get("summary"):
            events.append(
                {
                    "event_type": "workflow.summary_updated",
                    "episode_id": after["episode_id"],
                    "summary": after_workflow["summary"],
                    "updated_at": after_workflow["updated_at"],
                }
            )
        if before_workflow["pending_interrupt"] != after_workflow["pending_interrupt"]:
            if after_workflow["pending_interrupt"] is not None:
                events.append(
                    {
                        "event_type": "workflow.interrupt_pending",
                        "episode_id": after["episode_id"],
                        "interrupt": after_workflow["pending_interrupt"],
                        "updated_at": after_workflow["updated_at"],
                    }
                )
        if before_workflow["pending_approval"] != after_workflow["pending_approval"]:
            if after_workflow["pending_approval"] is not None:
                events.append(
                    {
                        "event_type": "workflow.approval_pending",
                        "episode_id": after["episode_id"],
                        "approval": after_workflow["pending_approval"],
                        "updated_at": after_workflow["pending_approval"]["created_at"],
                    }
                )

        before_run_ids = {run["run_id"] for run in before["runs"]}
        for run in after["runs"]:
            if run["run_id"] not in before_run_ids:
                events.append(
                    {
                        "event_type": "workflow.run_status_changed",
                        "episode_id": after["episode_id"],
                        "run": run,
                        "updated_at": run["completed_at"] or run["created_at"],
                    }
                )

        before_artifact_ids = {artifact["artifact_id"] for artifact in before["artifacts"]}
        for artifact in after["artifacts"]:
            if artifact["artifact_id"] not in before_artifact_ids:
                events.append(
                    {
                        "event_type": "workflow.artifact_available",
                        "episode_id": after["episode_id"],
                        "artifact": artifact,
                        "updated_at": artifact["created_at"],
                    }
                )
        if before["research"] != after["research"]:
            events.append(
                {
                    "event_type": "workflow.evidence_updated",
                    "episode_id": after["episode_id"],
                    "research": after["research"],
                    "updated_at": after_workflow["updated_at"],
                }
            )
        if before["design"] != after["design"]:
            events.append(
                {
                    "event_type": "workflow.candidate_updated",
                    "episode_id": after["episode_id"],
                    "design": after["design"],
                    "updated_at": after_workflow["updated_at"],
                }
            )
        if before["design"].get("selected_candidate") != after["design"].get("selected_candidate"):
            if after["design"].get("selected_candidate") is not None:
                events.append(
                    {
                        "event_type": "workflow.selected_candidate_changed",
                        "episode_id": after["episode_id"],
                        "selected_candidate": after["design"]["selected_candidate"],
                        "updated_at": after_workflow["updated_at"],
                    }
                )
        if before.get("report") != after.get("report"):
            if after.get("report") is not None:
                events.append(
                    {
                        "event_type": "workflow.report_available",
                        "episode_id": after["episode_id"],
                        "report": after["report"],
                        "updated_at": after["report"]["updated_at"],
                    }
                )
        return events
