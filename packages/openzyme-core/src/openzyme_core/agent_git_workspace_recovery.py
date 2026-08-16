from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from typing import Protocol

from openzyme_domain import AgentGitDirectoryKind
from openzyme_domain import AgentGitWorkspace
from openzyme_domain import AgentGitWorkspaceBlockerCode
from openzyme_domain import AgentGitWorkspaceObservation
from openzyme_domain import AgentGitWorkspaceStatus
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentWorkspaceGenerationStatus
from openzyme_domain import GitObjectFormat
from openzyme_domain import SandboxWorkspaceStatus

from .agent_capability_service import ActiveAgentCapabilityLeaseValidator
from .agent_capability_service import AgentCapabilityError
from .agent_capability_service import AgentCapabilityLeaseService
from .agent_capsule_image import AgentCapsuleImageQualification
from .agent_capsule_runtime import AgentCapsuleProcessRunner
from .agent_git_workspace_provisioner import AgentGitWorkspaceProvisioner
from .agent_git_workspace_service import AgentGitWorkspaceLifecycleService
from .agent_workspace_volumes import AGENT_WORKSPACE_VOLUME_SCHEMA_VERSION
from .agent_workspace_volumes import AgentWorkspaceVolumeAllocator
from .agent_workspace_volumes import AgentWorkspaceVolumeBackend
from .agent_workspace_volumes import AgentWorkspaceVolumeIdentityError
from .repositories import CoreRepositories


_RESTORE_OBSERVATION_SCRIPT = r"""
set -eu
remote=$(git remote get-url origin)
object_format=$(git rev-parse --show-object-format)
head_commit=$(git rev-parse --verify HEAD)
head_tree=$(git rev-parse --verify 'HEAD^{tree}')
git cat-file -e "${1}^{commit}"
git_dir=$(git rev-parse --git-dir)
git_kind=corrupt
if [ "$git_dir" = ".git" ] && [ -d .git ]; then
  git_kind=independent
fi
if [ -f .git ]; then
  git_kind=linked_worktree
fi
if [ -e .git/commondir ] || [ -s .git/objects/info/alternates ]; then
  git_kind=shared
fi
printf 'OPENZYME_REMOTE=%s\n' "$remote"
printf 'OPENZYME_OBJECT_FORMAT=%s\n' "$object_format"
printf 'OPENZYME_HEAD=%s\n' "$head_commit"
printf 'OPENZYME_TREE=%s\n' "$head_tree"
printf 'OPENZYME_GIT_DIRECTORY=%s\n' "$git_kind"
""".strip()


class AgentGitWorkspaceRecoveryError(RuntimeError):
    error_code = "agent_git_workspace_recovery_rejected"


class AgentGitWorkspaceObservationProvider(Protocol):
    def observe(
        self,
        workspace: AgentGitWorkspace,
    ) -> AgentGitWorkspaceObservation: ...


@dataclass(slots=True)
class PodmanAgentGitWorkspaceObservationProvider:
    process_runner: AgentCapsuleProcessRunner

    def observe(self, workspace: AgentGitWorkspace) -> AgentGitWorkspaceObservation:
        result = self.process_runner.run(
            workspace=workspace,
            argv=(
                "/bin/sh",
                "-c",
                _RESTORE_OBSERVATION_SCRIPT,
                "openzyme-workspace-restore",
                workspace.base_commit,
            ),
            credential_environment=(),
            timeout_seconds=120,
        )
        if result.returncode != 0:
            raise AgentGitWorkspaceRecoveryError(
                result.stderr.strip()
                or f"workspace restore probe exited {result.returncode}"
            )
        facts = _parse_restore_facts(result.stdout)
        return AgentGitWorkspaceObservation(
            workspace_id=workspace.workspace_id,
            session_id=workspace.session_id,
            agent_member_id=workspace.agent_member_id,
            agent_id=workspace.agent_id,
            workspace_generation=workspace.workspace_generation,
            volume_id=workspace.volume_id,
            clone_logical_root=workspace.clone_logical_root,
            git_directory_kind=AgentGitDirectoryKind(
                facts["OPENZYME_GIT_DIRECTORY"]
            ),
            internal_git_service_id=workspace.internal_git_service_id,
            internal_git_endpoint=facts["OPENZYME_REMOTE"],
            repository_id=workspace.repository_id,
            object_format=GitObjectFormat(facts["OPENZYME_OBJECT_FORMAT"]),
            base_commit=workspace.base_commit,
            head_commit=facts["OPENZYME_HEAD"],
            head_tree=facts["OPENZYME_TREE"],
            head_readable=True,
            private_ref_namespace=workspace.private_ref_namespace,
            repository_policy_digest=workspace.repository_policy_digest,
            capability_policy_digest=workspace.capability_policy_digest,
            observed_at=datetime.now(tz=UTC).isoformat(),
        )


@dataclass(slots=True)
class AgentGitWorkspaceRecoveryService:
    repositories: CoreRepositories
    volume_backend: AgentWorkspaceVolumeBackend
    observation_provider: AgentGitWorkspaceObservationProvider

    def restore(self, workspace_id: str) -> AgentGitWorkspace:
        workspace = self.repositories.agent_git_workspaces.get(workspace_id)
        if workspace is None or workspace.status is not AgentGitWorkspaceStatus.READY:
            raise AgentGitWorkspaceRecoveryError(
                "restore requires an exact ready workspace record"
            )
        volume = self.volume_backend.inspect(workspace.volume_id)
        if volume is None:
            return self._block(
                workspace,
                blocker_code=AgentGitWorkspaceBlockerCode.MISSING_VOLUME,
                detail={"volume_id": workspace.volume_id},
            )
        try:
            AgentWorkspaceVolumeAllocator.require_exact_owner(
                volume,
                expected_labels=_expected_volume_labels(workspace),
            )
        except AgentWorkspaceVolumeIdentityError as exc:
            return self._block(
                workspace,
                blocker_code=AgentGitWorkspaceBlockerCode.CROSS_AGENT_VOLUME,
                detail={"diagnostic": str(exc)},
            )
        try:
            observation = self.observation_provider.observe(workspace)
        except Exception as exc:
            return self._block(
                workspace,
                blocker_code=AgentGitWorkspaceBlockerCode.CORRUPT_GIT_DIRECTORY,
                detail={"diagnostic": str(exc)},
            )
        lifecycle = AgentGitWorkspaceLifecycleService(self.repositories)
        comparison = lifecycle.compare_restore(
            workspace_id=workspace.workspace_id,
            observation=observation,
        )
        if not comparison.matches:
            blocked = lifecycle.block_from_restore_comparison(
                workspace_id=workspace.workspace_id,
                comparison=comparison,
            )
            self._mark_agent_blocked(blocked, "workspace_identity_drift")
            return blocked
        agent = self.repositories.agents.get(
            workspace.session_id,
            workspace.agent_id,
        )
        if (
            agent is None
            or agent.member_id != workspace.agent_member_id
            or agent.runtime_state == "provisioning_required"
            or agent.status is AgentMemberStatus.BLOCKED
        ):
            return self._block(
                workspace,
                blocker_code=AgentGitWorkspaceBlockerCode.LEASE_INTENT_MISMATCH,
                detail={"reason": "agent provisioning blocker is not cleared"},
            )
        try:
            ActiveAgentCapabilityLeaseValidator(
                self.repositories
            ).require_current_agent(
                session_id=workspace.session_id,
                agent_id=workspace.agent_id,
                expected_lease_id=workspace.capability_lease_id,
                expected_workspace_generation=workspace.workspace_generation,
            )
        except AgentCapabilityError as exc:
            return self._block(
                workspace,
                blocker_code=AgentGitWorkspaceBlockerCode.LEASE_INTENT_MISMATCH,
                detail={"diagnostic": str(exc)},
            )
        return workspace

    def _block(
        self,
        workspace: AgentGitWorkspace,
        *,
        blocker_code: AgentGitWorkspaceBlockerCode,
        detail: dict[str, object],
    ) -> AgentGitWorkspace:
        blocked = AgentGitWorkspaceLifecycleService(self.repositories).block(
            workspace_id=workspace.workspace_id,
            blocker_code=blocker_code,
            blocker_detail=detail,
        )
        self._mark_agent_blocked(blocked, blocker_code.value)
        return blocked

    def _mark_agent_blocked(
        self,
        workspace: AgentGitWorkspace,
        runtime_state: str,
    ) -> None:
        agent = self.repositories.agents.get(
            workspace.session_id,
            workspace.agent_id,
        )
        if agent is not None:
            self.repositories.agents.save(
                replace(
                    agent,
                    status=AgentMemberStatus.BLOCKED,
                    runtime_state=runtime_state,
                    updated_at=datetime.now(tz=UTC).isoformat(),
                )
            )


@dataclass(slots=True)
class AgentGitWorkspaceGenerationService:
    repositories: CoreRepositories
    provisioner: AgentGitWorkspaceProvisioner

    def replace_and_provision(
        self,
        *,
        workspace_id: str,
        idempotency_key: str,
        actor_ref: str,
        image_qualification: AgentCapsuleImageQualification,
        namespace_retention_deadline: str,
        replacement_workspace_id: str,
    ) -> AgentGitWorkspace:
        workspace = self.repositories.agent_git_workspaces.get(workspace_id)
        if workspace is None:
            raise AgentGitWorkspaceRecoveryError("workspace does not exist")
        lifecycle = AgentGitWorkspaceLifecycleService(self.repositories)
        with self.repositories.atomic(prefix="agent_git_workspace_replace"):
            lifecycle.freeze(
                workspace_id=workspace.workspace_id,
                reason="explicit_generation_replacement",
            )
            issuance = AgentCapabilityLeaseService(
                self.repositories
            ).replace_workspace_generation(
                workspace.capability_lease_id,
                idempotency_key=idempotency_key,
                actor_ref=actor_ref,
            )
            lifecycle.mark_replaced(
                workspace_id=workspace.workspace_id,
                replaced_by_generation=issuance.reservation.workspace_generation,
            )
            self._freeze_legacy_sandbox(workspace)
        self.provisioner.provision_and_activate(
            session_id=workspace.session_id,
            agent_member_id=workspace.agent_member_id,
            workspace_generation=issuance.reservation.workspace_generation,
            image_qualification=image_qualification,
            namespace_retention_deadline=namespace_retention_deadline,
            actor_ref=actor_ref,
            workspace_id=replacement_workspace_id,
        )
        replacement = self.repositories.agent_git_workspaces.get(
            replacement_workspace_id
        )
        if replacement is None:
            raise AgentGitWorkspaceRecoveryError(
                "explicit replacement did not persist its new workspace"
            )
        return replacement

    def migrate_pending_legacy_agent(
        self,
        *,
        session_id: str,
        agent_member_id: str,
        workspace_generation: int,
        actor_ref: str,
        image_qualification: AgentCapsuleImageQualification,
        namespace_retention_deadline: str,
        workspace_id: str,
    ) -> AgentGitWorkspace:
        if self.repositories.agent_git_workspaces.get_by_generation(
            session_id=session_id,
            agent_member_id=agent_member_id,
            workspace_generation=workspace_generation,
        ) is not None:
            raise AgentGitWorkspaceRecoveryError(
                "legacy migration cannot replace an existing Git workspace"
            )
        reservation = (
            self.repositories.agent_workspace_generation_reservations.get_by_generation(
                session_id=session_id,
                agent_member_id=agent_member_id,
                workspace_generation=workspace_generation,
            )
        )
        if reservation is None:
            raise AgentGitWorkspaceRecoveryError(
                "legacy migration requires an exact C2 pending generation"
            )
        if reservation.status is not AgentWorkspaceGenerationStatus.RESERVED:
            raise AgentGitWorkspaceRecoveryError(
                "legacy migration requires a reserved C2 workspace generation"
            )
        agent = self.repositories.agents.get(session_id, reservation.agent_id)
        if (
            agent is None
            or agent.member_id != agent_member_id
            or agent.status is not AgentMemberStatus.BLOCKED
            or agent.runtime_state != "provisioning_required"
        ):
            raise AgentGitWorkspaceRecoveryError(
                "legacy migration requires the exact provisioning-blocked agent"
            )
        sandbox = self.repositories.sandbox_workspaces.get_by_session_member(
            session_id,
            agent_member_id,
        )
        if sandbox is not None:
            self.repositories.sandbox_workspaces.save(
                replace(sandbox, status=SandboxWorkspaceStatus.FROZEN_LEGACY)
            )
        self.provisioner.provision_and_activate(
            session_id=session_id,
            agent_member_id=agent_member_id,
            workspace_generation=workspace_generation,
            image_qualification=image_qualification,
            namespace_retention_deadline=namespace_retention_deadline,
            actor_ref=actor_ref,
            workspace_id=workspace_id,
        )
        migrated = self.repositories.agent_git_workspaces.get(workspace_id)
        if migrated is None:
            raise AgentGitWorkspaceRecoveryError(
                "legacy migration did not persist its Git workspace"
            )
        return migrated

    def _freeze_legacy_sandbox(self, workspace: AgentGitWorkspace) -> None:
        sandbox = self.repositories.sandbox_workspaces.get_by_session_member(
            workspace.session_id,
            workspace.agent_member_id,
        )
        if sandbox is not None:
            self.repositories.sandbox_workspaces.save(
                replace(sandbox, status=SandboxWorkspaceStatus.FROZEN_LEGACY)
            )


def _expected_volume_labels(
    workspace: AgentGitWorkspace,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            {
                "io.openzyme.workspace_id": workspace.workspace_id,
                "io.openzyme.session_id": workspace.session_id,
                "io.openzyme.agent_member_id": workspace.agent_member_id,
                "io.openzyme.workspace_generation": str(
                    workspace.workspace_generation
                ),
                "io.openzyme.volume_schema": AGENT_WORKSPACE_VOLUME_SCHEMA_VERSION,
            }.items()
        )
    )


def _parse_restore_facts(value: str) -> dict[str, str]:
    facts: dict[str, str] = {}
    for line in value.splitlines():
        key, separator, item = line.partition("=")
        if separator and key.startswith("OPENZYME_"):
            facts[key] = item
    required = {
        "OPENZYME_REMOTE",
        "OPENZYME_OBJECT_FORMAT",
        "OPENZYME_HEAD",
        "OPENZYME_TREE",
        "OPENZYME_GIT_DIRECTORY",
    }
    if set(facts) != required:
        raise AgentGitWorkspaceRecoveryError(
            "workspace restore probe output is incomplete"
        )
    return facts


__all__ = [
    "AgentGitWorkspaceGenerationService",
    "AgentGitWorkspaceObservationProvider",
    "AgentGitWorkspaceRecoveryError",
    "AgentGitWorkspaceRecoveryService",
    "PodmanAgentGitWorkspaceObservationProvider",
]
