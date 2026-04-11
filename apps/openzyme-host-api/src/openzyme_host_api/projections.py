from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from typing import Any
from typing import Callable

from openzyme_domain import EpisodeStatus
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


GraphBuilder = Callable[[Any], Any]


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

    def load_pending_actions(self, episode_id: str) -> list[dict[str, Any]]:
        return [
            approval.to_dict()
            for approval in self.runtime.repositories.approvals.list_pending_by_episode(episode_id)
        ]

    def load_episode_workspace(self, episode_id: str) -> dict[str, Any]:
        workflow = self.load_workflow_projection(episode_id)
        workflow["episode_status"] = _derive_episode_status(workflow).value
        return {
            "episode_id": episode_id,
            "workflow": workflow,
            "pending_actions": self.load_pending_actions(episode_id),
            "runs": self.load_run_projection(episode_id),
            "artifacts": self.load_artifact_projection(episode_id),
            "report": None,
        }


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
                    "updated_at": workspace["report"]["created_at"],
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
        return events

