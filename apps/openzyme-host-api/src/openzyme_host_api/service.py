from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from langgraph.types import Command
from openzyme_domain import ApprovalStatus
from openzyme_domain import Episode
from openzyme_domain import EpisodeStatus
from openzyme_graph.workflow import build_phase_b_supervisor_graph
from openzyme_runtime import GraphRuntimeFacade

from .projections import HostProjectionLoader
from .projections import WorkflowEventProjector


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

        with self.runtime.compile_graph(build_phase_b_supervisor_graph) as graph:
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
        with self.runtime.compile_graph(build_phase_b_supervisor_graph) as graph:
            graph.invoke(
                Command(resume=resume_payload),
                self.runtime.build_episode_graph_config(episode_id),
            )

        workflow = self.projection_loader.load_workflow_projection(episode_id)
        persisted = Episode(
            episode_id=episode.episode_id,
            project_id=episode.project_id,
            objective=episode.objective,
            status=_build_episode_status(workflow["status"], workflow["pending_interrupt"] is not None),
            created_at=episode.created_at,
            updated_at=workflow["updated_at"],
        )
        self.runtime.repositories.episodes.save(persisted)

        after = self.projection_loader.load_episode_workspace(episode_id)
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
        return self.resume_episode(episode_id, {"approved": decision == "approved"})

