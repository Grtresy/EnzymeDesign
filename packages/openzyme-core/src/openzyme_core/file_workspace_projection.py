from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from openzyme_domain import AgentCapabilityLeaseStatus
from openzyme_domain import ExecutorOwnerWorkspaceView
from openzyme_domain import FileWorkspacePublicProjection

from .repositories import CoreRepositories
from .conversation import build_conversation_projection
from .lane_manager import LaneManager
from .task_board import TaskBoardService


def file_workspace_public_schema_bundle_digest() -> str:
    payload = {
        "schema_version": "file_workspace_public_schema_bundle@1",
        "projection": "file_workspace_public@1",
        "owner_view": "executor_owner_workspace_view@1",
        "tool_error": "unsupported_current_file_workspace_contract@1",
        "sdk": "openzyme_pipeline_file_workspace@1",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(slots=True)
class FileWorkspaceProjectionBuilder:
    repositories: CoreRepositories
    tool_catalog_digest: str

    def build(
        self,
        *,
        session_id: str,
        subject_agent_member_id: str | None,
    ) -> FileWorkspacePublicProjection:
        session = self.repositories.sessions.get(session_id)
        if session is None:
            raise ValueError("file-workspace projection session does not exist")
        pin = self.repositories.session_repository_binding_pins.get(session_id)
        repository_binding: dict[str, object] = {
            "status": session.repository_binding_status.value,
        }
        if pin is not None:
            repository_binding.update(
                {
                    "binding_id": pin.binding_id,
                    "binding_version": pin.binding_version,
                    "repository_id": pin.repository_id,
                    "resolved_base_commit": pin.resolved_base_commit,
                }
            )

        workspaces = self.repositories.agent_git_workspaces.list_by_session(session_id)
        agent_workspaces = tuple(
            {
                "schema_version": "agent_workspace_public@1",
                "workspace_id": item.workspace_id,
                "agent_member_id": item.agent_member_id,
                "agent_id": item.agent_id,
                "workspace_generation": item.workspace_generation,
                "repository_binding_id": item.repository_binding_id,
                "repository_binding_version": item.repository_binding_version,
                "base_commit": item.base_commit,
                "status": item.status.value,
                "state_version": item.state_version,
            }
            for item in workspaces
        )
        workspace_status = tuple(
            self._workspace_status(item) for item in workspaces
        )
        private_revisions = tuple(
            {
                "workspace_id": item.workspace_id,
                "workspace_generation": item.workspace_generation,
                "commit": item.head_commit,
                "tree": item.head_tree,
                "shared": False,
            }
            for item in workspaces
            if item.head_commit is not None and item.head_tree is not None
        )
        publications = self.repositories.published_revisions.list_by_session(session_id)
        published_revisions = tuple(
            {
                "publication_id": item.publication_id,
                "publication_ref": item.publication_ref,
                "commit": item.commit,
                "tree": item.tree,
                "manifest_digest": item.manifest.manifest_digest,
                "repository_binding_id": item.repository_binding_id,
                "repository_binding_version": item.repository_binding_version,
                "publisher_agent_member_id": item.publisher_agent_member_id,
                "publisher_workspace_id": item.publisher_workspace_id,
                "publisher_workspace_generation": item.publisher_workspace_generation,
                "revision_digest": item.revision_digest,
                "created_at": item.created_at,
            }
            for item in publications
        )
        reports = tuple(
            {
                "report_id": item.report_id,
                "task_id": item.task_id,
                "lane_id": item.lane_id,
                "status": item.status.value,
                "title": item.title,
                "summary": item.summary,
                "content_ref_id": item.content_ref_id,
                "report_version": item.report_version,
                "supersedes_report_id": item.supersedes_report_id,
                "updated_at": item.updated_at,
            }
            for item in self.repositories.reports.list_by_session(session_id)
        )
        scientific_deliverables = tuple(
            {
                "ref_id": item.ref_id,
                "publication_id": item.publication_id,
                "commit": item.published_commit,
                "tree": item.published_tree,
                "path": item.path,
                "storage": item.storage.value,
                "content_digest": item.content_digest,
                "scientific_role": item.scientific_role,
                "attempt_id": item.attempt_id,
                "selection_id": item.selection_id,
                "ref_digest": item.ref_digest,
            }
            for item in self.repositories.scientific_deliverables.list_refs_by_session(
                session_id
            )
        )

        external_jobs: list[dict[str, object]] = []
        external_results: list[dict[str, object]] = []
        for operation in self.repositories.controlled_operations.list_by_session(
            session_id
        ):
            execution = (
                self.repositories.controlled_operation_executions.get_by_operation_id(
                    operation.operation_id
                )
            )
            if execution is None:
                continue
            handle = self.repositories.workspace_revision_executions.get_handle_by_execution(
                execution.execution_id
            )
            if handle is not None:
                external_jobs.append(
                    {
                        "execution_id": handle.execution_id,
                        "operation_id": handle.operation_id,
                        "source_commit": handle.source_commit,
                        "lifecycle_state": execution.lifecycle_state.value,
                        "effect_certainty": execution.effect_certainty.value,
                        "accepted_at": handle.accepted_at,
                    }
                )
            result = self.repositories.workspace_revision_executions.get_result_by_execution(
                execution.execution_id
            )
            if result is not None:
                external_results.append(
                    {
                        "result_id": result.result_id,
                        "execution_id": result.execution_id,
                        "operation_id": result.operation_id,
                        "terminal_state": result.terminal_state.value,
                        "exit_code": result.exit_code,
                        "source_commit": result.source_commit,
                        "result_digest": result.result_digest,
                        "created_at": result.created_at,
                    }
                )

        leases = self.repositories.agent_capability_leases.list_by_session(session_id)
        capability_leases = tuple(
            {
                "lease_id": item.lease_id,
                "agent_member_id": item.agent_member_id,
                "agent_id": item.agent_id,
                "workspace_generation": item.workspace_generation,
                "profile": item.profile.value,
                "capabilities": [capability.value for capability in item.capabilities],
                "status": item.status.value,
                "state_version": item.state_version,
                "updated_at": item.updated_at,
            }
            for item in leases
        )
        owner_view = self._owner_workspace_view(
            session_id=session_id,
            subject_agent_member_id=subject_agent_member_id,
            leases=leases,
        )
        conversation = tuple(
            entry.to_dict()
            for entry in build_conversation_projection(self.repositories, session_id)
        )
        task_board = TaskBoardService(self.repositories).build_projection(
            session_id
        ).to_dict()
        lane_board = LaneManager(self.repositories).build_projection(session_id).to_dict()
        agents = tuple(
            {
                "member_id": item.member_id,
                "agent_id": item.agent_id,
                "name": item.name,
                "role": item.role,
                "status": item.status.value,
                "task_id": item.task_id,
                "lane_id": item.lane_id,
                "updated_at": item.updated_at,
            }
            for item in self.repositories.agents.list_by_session(session_id)
        )
        pending_approvals = tuple(
            {
                "approval_id": item.approval_id,
                "session_id": item.session_id,
                "task_id": item.task_id,
                "lane_id": item.lane_id,
                "kind": item.kind,
                "status": item.status.value,
                "requested_action": item.requested_action,
                "created_at": item.created_at,
                "resolved_at": item.resolved_at,
            }
            for item in self.repositories.approvals.list_pending_by_session(session_id)
        )
        allowed_event_prefixes = (
            "conversation.",
            "task.",
            "lane.",
            "agent.",
            "protocol.",
            "workspace.",
            "publication.",
            "report.",
            "scientific.",
            "external_job.",
            "runtime.",
            "failure.",
        )
        activity_feed = tuple(
            {
                "event_id": item.event_id,
                "event_type": item.event_type,
                "created_at": item.created_at,
            }
            for item in self.repositories.durable_events.list_by_session(
                session_id,
                after_cursor=0,
                limit=200,
            )
            if item.event_type.startswith(allowed_event_prefixes)
        )
        failure_observations = tuple(
            {
                "failure_id": item.failure_id,
                "failure_class": item.failure_class.value,
                "recoverability": item.recoverability.value,
                "effect_certainty": item.effect_certainty.value,
                "safe_summary": item.safe_summary,
                "created_at": item.created_at,
            }
            for item in self.repositories.failure_observations.list_by_session(session_id)
        )
        return FileWorkspacePublicProjection(
            session={
                "session_id": session.session_id,
                "project_id": session.project_id,
                "title": session.title,
                "objective": session.objective,
                "status": session.status.value,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "repository_binding_status": session.repository_binding_status.value,
            },
            repository_binding=repository_binding,
            agent_workspaces=agent_workspaces,
            workspace_status=workspace_status,
            private_revisions=private_revisions,
            published_revisions=published_revisions,
            reports=reports,
            scientific_deliverables=scientific_deliverables,
            external_jobs=tuple(external_jobs),
            external_job_results=tuple(external_results),
            capability_leases=capability_leases,
            executor_owner_workspace=owner_view,
            conversation=conversation,
            task_board=task_board,
            lane_board=lane_board,
            agents=agents,
            pending_approvals=pending_approvals,
            activity_feed=activity_feed,
            failure_observations=failure_observations,
            tool_catalog_digest=self.tool_catalog_digest,
            schema_bundle_digest=file_workspace_public_schema_bundle_digest(),
        )

    def _workspace_status(self, workspace: object) -> dict[str, object]:
        workspace_id = str(getattr(workspace, "workspace_id"))
        observation = self.repositories.agent_workspace_state_observations.latest_for_workspace(
            workspace_id
        )
        return {
            "workspace_id": workspace_id,
            "workspace_generation": int(getattr(workspace, "workspace_generation")),
            "head_commit": (
                getattr(workspace, "head_commit")
                if observation is None
                else observation.head_commit
            ),
            "head_tree": (
                getattr(workspace, "head_tree")
                if observation is None
                else observation.head_tree
            ),
            "status": getattr(workspace, "status").value,
            "dirty_state": "unknown" if observation is None else observation.dirty_state.value,
            "staged": None if observation is None else observation.staged,
            "unstaged": None if observation is None else observation.unstaged,
            "untracked": None if observation is None else observation.untracked,
            "changed_paths": (
                [] if observation is None else list(observation.changed_paths[:100])
            ),
            "changed_paths_truncated": (
                False
                if observation is None
                else observation.changed_paths_truncated
                or len(observation.changed_paths) > 100
            ),
            "changed_paths_continuation": (
                None
                if observation is None or len(observation.changed_paths) <= 100
                else f"{observation.observation_id}:100"
            ),
            "observed_at": None if observation is None else observation.observed_at,
            "blocker_code": (
                None
                if getattr(workspace, "blocker_code") is None
                else getattr(workspace, "blocker_code").value
            ),
        }

    def build_changed_paths_page(
        self,
        *,
        session_id: str,
        workspace_id: str,
        continuation: str,
    ) -> dict[str, object]:
        observation_id, separator, offset_text = continuation.rpartition(":")
        if not separator or not offset_text.isdigit():
            raise ValueError("changed-path continuation is invalid")
        offset = int(offset_text)
        if offset < 100 or offset % 100:
            raise ValueError("changed-path continuation offset is invalid")
        workspace = self.repositories.agent_git_workspaces.get(workspace_id)
        observation = self.repositories.agent_workspace_state_observations.get(
            observation_id
        )
        if (
            workspace is None
            or observation is None
            or workspace.session_id != session_id
            or observation.session_id != session_id
            or observation.workspace_id != workspace_id
            or observation.workspace_generation != workspace.workspace_generation
        ):
            raise ValueError("changed-path continuation identity is stale")
        paths = observation.changed_paths[offset : offset + 100]
        next_offset = offset + len(paths)
        return {
            "schema_version": "workspace_changed_paths_page@1",
            "workspace_id": workspace_id,
            "workspace_generation": observation.workspace_generation,
            "observation_id": observation.observation_id,
            "head_commit": observation.head_commit,
            "head_tree": observation.head_tree,
            "paths": list(paths),
            "continuation": (
                f"{observation.observation_id}:{next_offset}"
                if next_offset < len(observation.changed_paths)
                else None
            ),
            "source_truncated": observation.changed_paths_truncated,
        }

    def _owner_workspace_view(
        self,
        *,
        session_id: str,
        subject_agent_member_id: str | None,
        leases: list[object],
    ) -> ExecutorOwnerWorkspaceView | None:
        if subject_agent_member_id is None:
            return None
        subject = next(
            (
                item
                for item in self.repositories.agents.list_by_session(session_id)
                if item.member_id == subject_agent_member_id
            ),
            None,
        )
        if subject is None:
            return None
        owned = tuple(
            item
            for item in self.repositories.executor_hpc_workspaces.list_by_session(
                session_id
            )
            if item.executor_agent_member_id == subject_agent_member_id
        )
        if len(owned) > 1:
            raise ValueError("executor owner view is ambiguous")
        if not owned:
            return None
        workspace = owned[0]
        if workspace.executor_agent_id != subject.agent_id:
            return None
        matching_lease = next(
            (
                item
                for item in leases
                if getattr(item, "lease_id", None) == workspace.capability_lease_id
                and getattr(item, "agent_member_id", None) == subject_agent_member_id
                and getattr(item, "workspace_generation", None)
                == workspace.local_workspace_generation
                and getattr(item, "status", None)
                is AgentCapabilityLeaseStatus.ACTIVE
            ),
            None,
        )
        if matching_lease is None:
            return None
        if workspace.login_alias is None or workspace.remote_workspace_path is None:
            return None
        return ExecutorOwnerWorkspaceView.create(
            subject_agent_member_id=subject_agent_member_id,
            workspace_id=workspace.workspace_id,
            workspace_generation=workspace.remote_workspace_generation,
            login_alias=workspace.login_alias,
            workspace_path=workspace.remote_workspace_path,
            capability_lease_id=workspace.capability_lease_id,
        )


__all__ = [
    "FileWorkspaceProjectionBuilder",
    "file_workspace_public_schema_bundle_digest",
]
