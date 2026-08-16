from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from openzyme_domain import AgentCapability
from openzyme_domain import AgentGitWorkspace
from openzyme_domain import AgentGitWorkspaceStatus
from openzyme_domain import AgentWorkspaceStateObservation
from openzyme_domain import CleanCommittedRevisionProof
from openzyme_domain import PrivateRefAdvanceKind
from openzyme_domain import ProjectRepositoryBinding
from openzyme_domain import VerifiedWorkspaceCheckpoint
from openzyme_domain import WorkspaceCheckpointProofInput
from openzyme_domain import WorkspaceDirtyState

from .agent_capability_service import ActiveAgentCapabilityLeaseValidator
from .repositories import CoreRepositories


class WorkspaceCheckpointError(RuntimeError):
    error_code = "workspace_checkpoint_rejected"


class WorkspaceCheckpointGitReader(Protocol):
    def read_exact_ref(
        self,
        binding: ProjectRepositoryBinding,
        *,
        ref_name: str,
    ) -> str | None: ...

    def read_commit_tree(
        self,
        binding: ProjectRepositoryBinding,
        *,
        commit: str,
    ) -> str: ...

    def is_ancestor(
        self,
        binding: ProjectRepositoryBinding,
        *,
        ancestor: str,
        descendant: str,
        extra_env: dict[str, str] | None = None,
    ) -> bool: ...


@dataclass(slots=True)
class WorkspaceCheckpointService:
    repositories: CoreRepositories
    git_reader: WorkspaceCheckpointGitReader

    def record_state_observation(
        self,
        observation: AgentWorkspaceStateObservation,
    ) -> AgentWorkspaceStateObservation:
        workspace, _ = self._require_active_workspace(
            session_id=observation.session_id,
            agent_id=observation.agent_id,
            workspace_id=observation.workspace_id,
            workspace_generation=observation.workspace_generation,
        )
        if observation.agent_member_id != workspace.agent_member_id:
            raise WorkspaceCheckpointError(
                "workspace state observation does not match the exact owner"
            )
        return self.repositories.agent_workspace_state_observations.add(observation)

    def verify_checkpoint(
        self,
        proof: WorkspaceCheckpointProofInput,
        *,
        checkpoint_id: str | None = None,
        verified_at: str | None = None,
    ) -> VerifiedWorkspaceCheckpoint:
        workspace, binding = self._require_active_workspace(
            session_id=proof.session_id,
            agent_id=proof.agent_id,
            workspace_id=proof.workspace_id,
            workspace_generation=proof.workspace_generation,
        )
        if (
            proof.agent_member_id != workspace.agent_member_id
            or proof.repository_binding_id != workspace.repository_binding_id
            or proof.repository_binding_version != workspace.repository_binding_version
            or proof.remote_observation.service_id
            != workspace.internal_git_service_id
            or proof.remote_observation.repository_id != workspace.repository_id
            or not proof.private_ref.startswith(
                f"{workspace.private_ref_namespace}/"
            )
        ):
            raise WorkspaceCheckpointError(
                "checkpoint proof does not match exact workspace or private namespace"
            )
        remote_commit = self.git_reader.read_exact_ref(
            binding,
            ref_name=proof.private_ref,
        )
        if remote_commit != proof.commit:
            raise WorkspaceCheckpointError(
                "remote private ref does not point to the declared commit"
            )
        if self.git_reader.read_commit_tree(binding, commit=proof.commit) != proof.tree:
            raise WorkspaceCheckpointError(
                "declared checkpoint tree does not match the remote commit"
            )
        latest = self.repositories.verified_workspace_checkpoints.latest_for_ref(
            workspace_id=workspace.workspace_id,
            private_ref=proof.private_ref,
        )
        observation = proof.remote_observation
        if observation.advance_kind is PrivateRefAdvanceKind.CREATE:
            if latest is not None:
                raise WorkspaceCheckpointError(
                    "existing private checkpoint ref cannot be observed as create"
                )
        else:
            if observation.prior_commit is None:
                raise WorkspaceCheckpointError(
                    "fast-forward checkpoint is missing its prior commit"
                )
            if observation.prior_commit == proof.commit:
                raise WorkspaceCheckpointError(
                    "private checkpoint fast-forward must advance to a new commit"
                )
            if latest is not None and latest.commit != observation.prior_commit:
                raise WorkspaceCheckpointError(
                    "checkpoint prior commit differs from the last verified checkpoint"
                )
            if not self.git_reader.is_ancestor(
                binding,
                ancestor=observation.prior_commit,
                descendant=proof.commit,
            ):
                raise WorkspaceCheckpointError(
                    "private checkpoint update is not a fast-forward"
                )
        checkpoint = VerifiedWorkspaceCheckpoint.create(
            checkpoint_id=(
                checkpoint_id or f"workspace_checkpoint_{uuid4().hex}"
            ),
            boundary=proof.boundary,
            workspace_id=workspace.workspace_id,
            session_id=workspace.session_id,
            agent_member_id=workspace.agent_member_id,
            agent_id=workspace.agent_id,
            workspace_generation=workspace.workspace_generation,
            repository_binding_id=workspace.repository_binding_id,
            repository_binding_version=workspace.repository_binding_version,
            repository_id=workspace.repository_id,
            commit=proof.commit,
            tree=proof.tree,
            private_ref=proof.private_ref,
            prior_commit=observation.prior_commit,
            advance_kind=observation.advance_kind,
            remote_observed_at=observation.observed_at,
            verified_at=(
                verified_at or datetime.now(tz=UTC).isoformat()
            ),
        )
        return self.repositories.verified_workspace_checkpoints.add(checkpoint)

    def validate_clean_committed_revision(
        self,
        *,
        workspace_id: str,
        expected_commit: str,
        expected_tree: str,
        verified_at: str | None = None,
    ) -> CleanCommittedRevisionProof:
        workspace = self.repositories.agent_git_workspaces.get(workspace_id)
        if workspace is None:
            raise WorkspaceCheckpointError("workspace does not exist")
        workspace, binding = self._require_active_workspace(
            session_id=workspace.session_id,
            agent_id=workspace.agent_id,
            workspace_id=workspace_id,
            workspace_generation=workspace.workspace_generation,
        )
        observation = (
            self.repositories.agent_workspace_state_observations.latest_for_workspace(
                workspace.workspace_id
            )
        )
        checkpoint = self.repositories.verified_workspace_checkpoints.latest_for_workspace(
            workspace.workspace_id
        )
        if observation is None or observation.dirty_state is not WorkspaceDirtyState.CLEAN:
            raise WorkspaceCheckpointError(
                "clean committed revision requires an exact clean state observation"
            )
        if checkpoint is None:
            raise WorkspaceCheckpointError(
                "clean committed revision requires a verified private checkpoint"
            )
        if (
            observation.head_commit != expected_commit
            or observation.head_tree != expected_tree
            or checkpoint.commit != expected_commit
            or checkpoint.tree != expected_tree
        ):
            raise WorkspaceCheckpointError(
                "workspace HEAD, tree, and private checkpoint do not agree"
            )
        if self.git_reader.read_commit_tree(binding, commit=expected_commit) != expected_tree:
            raise WorkspaceCheckpointError(
                "expected committed revision is absent from the pinned repository"
            )
        return CleanCommittedRevisionProof(
            workspace_id=workspace.workspace_id,
            workspace_generation=workspace.workspace_generation,
            repository_binding_id=workspace.repository_binding_id,
            repository_binding_version=workspace.repository_binding_version,
            commit=expected_commit,
            tree=expected_tree,
            state_observation_id=observation.observation_id,
            verified_checkpoint_id=checkpoint.checkpoint_id,
            verified_at=verified_at or datetime.now(tz=UTC).isoformat(),
        )

    def validate_immutable_revision_handoff(
        self,
        *,
        checkpoint_id: str,
        expected_commit: str,
        expected_tree: str,
    ) -> VerifiedWorkspaceCheckpoint:
        checkpoint = self.repositories.verified_workspace_checkpoints.get(
            checkpoint_id
        )
        if checkpoint is None:
            raise WorkspaceCheckpointError("verified checkpoint does not exist")
        if checkpoint.commit != expected_commit or checkpoint.tree != expected_tree:
            raise WorkspaceCheckpointError(
                "immutable revision handoff does not match checkpoint identity"
            )
        return checkpoint

    def _require_active_workspace(
        self,
        *,
        session_id: str,
        agent_id: str,
        workspace_id: str,
        workspace_generation: int,
    ) -> tuple[AgentGitWorkspace, ProjectRepositoryBinding]:
        workspace = self.repositories.agent_git_workspaces.get(workspace_id)
        if (
            workspace is None
            or workspace.status is not AgentGitWorkspaceStatus.READY
            or workspace.session_id != session_id
            or workspace.agent_id != agent_id
            or workspace.workspace_generation != workspace_generation
        ):
            raise WorkspaceCheckpointError(
                "formal workspace boundary requires the exact ready generation"
            )
        ActiveAgentCapabilityLeaseValidator(self.repositories).require_current_agent(
            session_id=session_id,
            agent_id=agent_id,
            expected_lease_id=workspace.capability_lease_id,
            expected_workspace_generation=workspace.workspace_generation,
            service_id="workspace_checkpoint",
            protocol="read_only_remote_verification",
            operation_class="workspace_checkpoint_verify",
            required_capabilities=(AgentCapability.GIT,),
            target_id="repository:session-pinned",
        )
        binding = self.repositories.project_repository_bindings.get(
            workspace.repository_binding_id
        )
        if (
            binding is None
            or binding.binding_version != workspace.repository_binding_version
            or binding.repository_id != workspace.repository_id
        ):
            raise WorkspaceCheckpointError(
                "workspace repository binding is missing or drifted"
            )
        return workspace, binding


__all__ = [
    "WorkspaceCheckpointError",
    "WorkspaceCheckpointGitReader",
    "WorkspaceCheckpointService",
]
