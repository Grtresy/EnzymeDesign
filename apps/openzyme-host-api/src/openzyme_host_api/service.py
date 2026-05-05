from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Callable
from uuid import uuid4

from langgraph.types import Command
from openzyme_domain import ApprovalStatus
from openzyme_domain import Episode
from openzyme_domain import EpisodeStatus
from openzyme_runtime import GraphRuntimeFacade

from .projections import HostProjectionLoader
from .projections import WorkflowEventProjector
from .tracing import workflow_trace

GraphBuilder = Callable[[Any], Any]


@dataclass(frozen=True, slots=True)
class HostCommandResult:
    workspace: dict[str, Any]
    events: list[dict[str, Any]]


def _build_episode_status(workflow_status: str, had_interrupt: bool) -> EpisodeStatus:
    if workflow_status == "completed":
        return EpisodeStatus.COMPLETED
    if workflow_status == "failed":
        return EpisodeStatus.FAILED
    if had_interrupt or workflow_status == "interrupted":
        return EpisodeStatus.INTERRUPTED
    return EpisodeStatus.ACTIVE


@dataclass(slots=True)
class HostApiService:
    runtime: GraphRuntimeFacade
    projection_loader: HostProjectionLoader
    event_projector: WorkflowEventProjector
    graph_builder: GraphBuilder

    def create_episode(self, project_id: str, objective: str) -> HostCommandResult:
        project = self.runtime.repositories.projects.get(project_id)
        if project is None:
            msg = f"project {project_id!r} does not exist"
            raise KeyError(msg)

        episode_id = f"ep_{uuid4().hex[:12]}"
        episode = Episode.create(
            episode_id=episode_id,
            project_id=project_id,
            objective=objective,
            status=EpisodeStatus.ACTIVE,
        )
        self.runtime.repositories.episodes.save(episode)

        with workflow_trace(
            "host.create_episode",
            action="create_episode",
            project_id=project_id,
            episode_id=episode_id,
            phase="intake",
            inputs={"project_id": project_id, "objective": objective},
        ) as run:
            with self.runtime.compile_graph(self.graph_builder) as graph:
                result = graph.invoke(
                    {
                        "episode_id": episode_id,
                        "project_id": project_id,
                        "objective": objective,
                        "user_goal": objective,
                    },
                    self.runtime.build_episode_graph_config(episode_id),
                )

            workflow = self.projection_loader.load_workflow_projection(episode_id)
            persisted = Episode(
                episode_id=episode.episode_id,
                project_id=episode.project_id,
                objective=episode.objective,
                status=_build_episode_status(workflow["status"], "__interrupt__" in result),
                created_at=episode.created_at,
                updated_at=workflow["updated_at"],
            )
            self.runtime.repositories.episodes.save(persisted)

            workspace = self.projection_loader.load_episode_workspace(episode_id)
            if run is not None:
                run.end(
                    outputs={
                        "episode_id": episode_id,
                        "status": workspace["workflow"]["status"],
                        "phase": workspace["workflow"]["current_phase"],
                    }
                )
        return HostCommandResult(
            workspace=workspace,
            events=self.event_projector.project_snapshot_events(workspace),
        )

    def resume_episode(self, episode_id: str, resume_payload: Any) -> HostCommandResult:
        episode = self.runtime.repositories.episodes.get(episode_id)
        if episode is None:
            msg = f"episode {episode_id!r} does not exist"
            raise KeyError(msg)

        before = self.projection_loader.load_episode_workspace(episode_id)
        with workflow_trace(
            "host.resume_episode",
            action="resume_episode",
            project_id=episode.project_id,
            episode_id=episode_id,
            phase=before["workflow"]["current_phase"],
            inputs={"resume_payload": resume_payload},
        ) as run:
            with self.runtime.compile_graph(self.graph_builder) as graph:
                graph.invoke(
                    Command(resume=resume_payload),
                    self.runtime.build_episode_graph_config(episode_id),
                )
            workflow = self.projection_loader.load_workflow_projection(episode_id)
            persisted = Episode(
                episode_id=episode.episode_id,
                project_id=episode.project_id,
                objective=episode.objective,
                status=_build_episode_status(
                    workflow["status"],
                    workflow["pending_interrupt"] is not None,
                ),
                created_at=episode.created_at,
                updated_at=workflow["updated_at"],
            )
            self.runtime.repositories.episodes.save(persisted)

            after = self.projection_loader.load_episode_workspace(episode_id)
            if run is not None:
                run.end(
                    outputs={
                        "episode_id": episode_id,
                        "status": after["workflow"]["status"],
                        "phase": after["workflow"]["current_phase"],
                    }
                )
        return HostCommandResult(
            workspace=after,
            events=self.event_projector.project_delta_events(before, after),
        )

    def resolve_approval(self, episode_id: str, approval_id: str, decision: str) -> HostCommandResult:
        approval = self.runtime.repositories.approvals.get(approval_id)
        if approval is None or approval.episode_id != episode_id:
            msg = f"approval {approval_id!r} does not exist for episode {episode_id!r}"
            raise KeyError(msg)
        if approval.status is not ApprovalStatus.PENDING:
            msg = f"approval {approval_id!r} is not pending"
            raise ValueError(msg)
        if decision not in {"approved", "rejected"}:
            msg = "decision must be 'approved' or 'rejected'"
            raise ValueError(msg)
        with workflow_trace(
            "host.resolve_approval",
            action="resolve_approval",
            project_id=approval.project_id if hasattr(approval, "project_id") else None,
            episode_id=episode_id,
            approval_id=approval_id,
            inputs={"decision": decision},
        ) as run:
            result = self.resume_episode(episode_id, {"approved": decision == "approved"})
            if run is not None:
                run.end(
                    outputs={
                        "episode_id": episode_id,
                        "status": result.workspace["workflow"]["status"],
                        "phase": result.workspace["workflow"]["current_phase"],
                    }
                )
            return result
