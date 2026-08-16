from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from openzyme_domain import AgentCapabilityLeaseStatus
from openzyme_domain import ExecutorOwnerWorkspaceView
from openzyme_domain import FileWorkspacePublicProjection

from .repositories import CoreRepositories


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
            {
                "workspace_id": item.workspace_id,
                "workspace_generation": item.workspace_generation,
                "head_commit": item.head_commit,
                "head_tree": item.head_tree,
                "status": item.status.value,
                "blocker_code": (
                    None if item.blocker_code is None else item.blocker_code.value
                ),
            }
            for item in workspaces
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
                        "handle_id": handle.handle_id,
                        "execution_id": handle.execution_id,
                        "operation_id": handle.operation_id,
                        "workspace_id": handle.workspace_id,
                        "source_commit": handle.source_commit,
                        "backend": handle.backend.value,
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
        return FileWorkspacePublicProjection(
            session={
                "session_id": session.session_id,
                "status": session.status.value,
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
            tool_catalog_digest=self.tool_catalog_digest,
            schema_bundle_digest=file_workspace_public_schema_bundle_digest(),
        )

    def _owner_workspace_view(
        self,
        *,
        session_id: str,
        subject_agent_member_id: str | None,
        leases: list[object],
    ) -> ExecutorOwnerWorkspaceView | None:
        if subject_agent_member_id is None:
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
