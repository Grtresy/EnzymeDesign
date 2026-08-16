from __future__ import annotations

from dataclasses import fields
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from openzyme_domain import AgentCapabilityLeaseStatus
from openzyme_domain import AgentGitWorkspace
from openzyme_domain import AgentGitWorkspaceBlockerCode
from openzyme_domain import AgentGitWorkspaceIdentityDriftKind
from openzyme_domain import AgentGitWorkspaceObservation
from openzyme_domain import AgentGitWorkspaceRestoreComparison
from openzyme_domain import AgentGitWorkspaceStatus
from openzyme_domain import AgentWorkspaceGenerationStatus
from openzyme_domain import canonical_workspace_digest
from openzyme_domain import compare_agent_git_workspace_identity
from openzyme_domain.control_plane import utc_now_iso

from .agent_capability_service import DEFAULT_AGENT_CAPABILITY_POLICY
from .agent_capsule_image import AgentCapsuleImageQualification
from .repositories import CoreRepositories
from .repositories import _managed_transaction_depth
from .repository_credentials import private_ref_prefix


class AgentGitWorkspaceError(RuntimeError):
    error_code = "agent_git_workspace_error"


class AgentGitWorkspaceConflictError(AgentGitWorkspaceError):
    error_code = "agent_git_workspace_conflict"


class AgentGitWorkspaceIdentityDriftError(AgentGitWorkspaceError):
    error_code = "agent_git_workspace_identity_drift"

    def __init__(self, comparison: AgentGitWorkspaceRestoreComparison) -> None:
        self.comparison = comparison
        drift = ", ".join(item.value for item in comparison.drift)
        super().__init__(f"agent Git workspace identity drift: {drift}")


class AgentGitWorkspaceTransitionError(AgentGitWorkspaceError):
    error_code = "agent_git_workspace_transition_rejected"


@dataclass(slots=True)
class AgentGitWorkspaceLifecycleService:
    repositories: CoreRepositories

    def create_provisioning(
        self,
        *,
        session_id: str,
        agent_member_id: str,
        workspace_generation: int,
        volume_id: str,
        clone_logical_root: str,
        image_qualification: AgentCapsuleImageQualification,
        workspace_id: str | None = None,
        created_at: str | None = None,
    ) -> AgentGitWorkspace:
        existing = self.repositories.agent_git_workspaces.get_by_generation(
            session_id=session_id,
            agent_member_id=agent_member_id,
            workspace_generation=workspace_generation,
        )
        if existing is not None:
            if (
                existing.volume_id == volume_id
                and existing.clone_logical_root == clone_logical_root
            ):
                return existing
            raise AgentGitWorkspaceConflictError(
                "workspace generation already owns another volume or clone root"
            )
        current = self.repositories.agent_git_workspaces.get_current(
            session_id=session_id,
            agent_member_id=agent_member_id,
        )
        if current is not None:
            raise AgentGitWorkspaceConflictError(
                "agent already has a non-replaced canonical Git workspace"
            )
        reservation, lease = self._require_pending_intent(
            session_id=session_id,
            agent_member_id=agent_member_id,
            workspace_generation=workspace_generation,
        )
        pin = self.repositories.session_repository_binding_pins.require(session_id)
        binding = self.repositories.project_repository_bindings.get(pin.binding_id)
        if binding is None:
            raise AgentGitWorkspaceConflictError(
                "session repository binding no longer exists"
            )
        if (
            binding.binding_version != pin.binding_version
            or binding.repository_id != pin.repository_id
            or binding.canonical_digest != pin.binding_canonical_digest
            or pin.resolved_base_commit != binding.default_base_commit
        ):
            raise AgentGitWorkspaceConflictError(
                "session repository binding pin has identity drift"
            )
        expected_private_namespace = private_ref_prefix(
            binding,
            session_id=session_id,
            agent_member_id=agent_member_id,
            workspace_generation=workspace_generation,
        )
        now = created_at or utc_now_iso()
        workspace = AgentGitWorkspace.create(
            workspace_id=workspace_id or f"agent_git_workspace_{uuid4().hex}",
            session_id=session_id,
            agent_member_id=agent_member_id,
            agent_id=reservation.agent_id,
            workspace_generation=workspace_generation,
            reservation_id=reservation.reservation_id,
            reservation_fingerprint=reservation.immutable_fingerprint,
            capability_lease_id=lease.lease_id,
            capability_lease_intent_digest=lease.canonical_digest,
            repository_binding_id=binding.binding_id,
            repository_binding_version=binding.binding_version,
            repository_binding_digest=binding.canonical_digest,
            repository_id=binding.repository_id,
            internal_git_service_id=binding.internal_git_service_id,
            internal_git_endpoint=binding.internal_git_endpoint,
            object_format=binding.object_format,
            base_commit=pin.resolved_base_commit,
            volume_id=volume_id,
            clone_logical_root=clone_logical_root,
            image_ref=image_qualification.image_ref,
            image_manifest_digest=image_qualification.image_manifest_digest,
            image_qualification_digest=(
                image_qualification.qualification_output_digest
            ),
            private_ref_namespace=expected_private_namespace,
            repository_policy_version=binding.repository_policy_version,
            repository_policy_digest=binding.repository_policy_digest,
            capability_policy_version=lease.policy_version,
            capability_policy_digest=lease.policy_digest,
            status=AgentGitWorkspaceStatus.PROVISIONING,
            state_version=1,
            created_at=now,
            updated_at=now,
        )
        return self.repositories.agent_git_workspaces.add(workspace)

    def compare_restore(
        self,
        *,
        workspace_id: str,
        observation: AgentGitWorkspaceObservation,
    ) -> AgentGitWorkspaceRestoreComparison:
        workspace = self._require_workspace(workspace_id)
        return compare_agent_git_workspace_identity(workspace, observation)

    def block(
        self,
        *,
        workspace_id: str,
        blocker_code: AgentGitWorkspaceBlockerCode,
        blocker_detail: dict[str, Any],
        blocked_at: str | None = None,
    ) -> AgentGitWorkspace:
        workspace = self._require_workspace(workspace_id)
        if workspace.status not in {
            AgentGitWorkspaceStatus.PROVISIONING,
            AgentGitWorkspaceStatus.READY,
        }:
            raise AgentGitWorkspaceTransitionError(
                "only provisioning or ready workspace can become blocked"
            )
        now = blocked_at or utc_now_iso()
        return self._save_transition(
            workspace,
            status=AgentGitWorkspaceStatus.BLOCKED,
            updated_at=now,
            blocker_code=blocker_code,
            blocker_detail_digest=canonical_workspace_digest(blocker_detail),
            blocked_at=now,
        )

    def block_from_restore_comparison(
        self,
        *,
        workspace_id: str,
        comparison: AgentGitWorkspaceRestoreComparison,
    ) -> AgentGitWorkspace:
        if comparison.workspace_id != workspace_id or comparison.matches:
            raise AgentGitWorkspaceTransitionError(
                "a non-matching comparison for the exact workspace is required"
            )
        blocker = _blocker_for_drift(comparison.drift)
        return self.block(
            workspace_id=workspace_id,
            blocker_code=blocker,
            blocker_detail={
                "schema_version": comparison.schema_version,
                "workspace_id": comparison.workspace_id,
                "workspace_identity_digest": comparison.workspace_identity_digest,
                "observation_digest": comparison.observation_digest,
                "drift": [item.value for item in comparison.drift],
                "compared_at": comparison.compared_at,
            },
            blocked_at=comparison.compared_at,
        )

    def stage_ready_in_current_transaction(
        self,
        *,
        workspace_id: str,
        observation: AgentGitWorkspaceObservation,
    ) -> AgentGitWorkspace:
        """Stage workspace readiness inside the C2 atomic activation transaction.

        This method deliberately refuses a standalone transaction. The caller must
        atomically activate the exact C2 reservation/lease and clear the exact
        provisioning blocker before the surrounding transaction commits.
        """

        connection = self.repositories.tasks.connection
        if _managed_transaction_depth(connection) <= 0:
            raise AgentGitWorkspaceTransitionError(
                "workspace readiness requires the C2 atomic activation transaction"
            )
        workspace = self._require_workspace(workspace_id)
        if workspace.status not in {
            AgentGitWorkspaceStatus.PROVISIONING,
            AgentGitWorkspaceStatus.BLOCKED,
        }:
            raise AgentGitWorkspaceTransitionError(
                "only provisioning or blocked workspace can become ready"
            )
        self._require_pending_intent(
            session_id=workspace.session_id,
            agent_member_id=workspace.agent_member_id,
            workspace_generation=workspace.workspace_generation,
            expected_workspace=workspace,
        )
        comparison = compare_agent_git_workspace_identity(workspace, observation)
        if not comparison.matches:
            raise AgentGitWorkspaceIdentityDriftError(comparison)
        if observation.head_commit != workspace.base_commit:
            raise AgentGitWorkspaceTransitionError(
                "initial workspace readiness HEAD must equal the pinned base commit"
            )
        self._require_open_private_namespace(workspace)
        return self._save_transition(
            workspace,
            status=AgentGitWorkspaceStatus.READY,
            updated_at=observation.observed_at,
            head_commit=observation.head_commit,
            head_tree=observation.head_tree,
            readiness_observation_digest=observation.observation_digest,
            ready_at=observation.observed_at,
            blocker_code=None,
            blocker_detail_digest=None,
            blocked_at=None,
        )

    def freeze(
        self,
        *,
        workspace_id: str,
        reason: str,
        frozen_at: str | None = None,
    ) -> AgentGitWorkspace:
        workspace = self._require_workspace(workspace_id)
        if workspace.status not in {
            AgentGitWorkspaceStatus.PROVISIONING,
            AgentGitWorkspaceStatus.READY,
            AgentGitWorkspaceStatus.BLOCKED,
        }:
            raise AgentGitWorkspaceTransitionError(
                "only a current workspace can be frozen"
            )
        now = frozen_at or utc_now_iso()
        return self._save_transition(
            workspace,
            status=AgentGitWorkspaceStatus.FROZEN,
            updated_at=now,
            frozen_reason=reason,
            frozen_at=now,
        )

    def mark_replaced(
        self,
        *,
        workspace_id: str,
        replaced_by_generation: int,
        replaced_at: str | None = None,
    ) -> AgentGitWorkspace:
        workspace = self._require_workspace(workspace_id)
        if workspace.status is not AgentGitWorkspaceStatus.FROZEN:
            raise AgentGitWorkspaceTransitionError(
                "workspace must be frozen before explicit replacement"
            )
        lease = self.repositories.agent_capability_leases.get(
            workspace.capability_lease_id
        )
        if lease is None or lease.status is not AgentCapabilityLeaseStatus.REVOKED:
            raise AgentGitWorkspaceTransitionError(
                "workspace replacement requires the exact revoked capability lease"
            )
        now = replaced_at or utc_now_iso()
        return self._save_transition(
            workspace,
            status=AgentGitWorkspaceStatus.REPLACED,
            updated_at=now,
            replaced_by_generation=replaced_by_generation,
            replaced_at=now,
        )

    def _require_pending_intent(
        self,
        *,
        session_id: str,
        agent_member_id: str,
        workspace_generation: int,
        expected_workspace: AgentGitWorkspace | None = None,
    ) -> tuple[Any, Any]:
        reservation = (
            self.repositories.agent_workspace_generation_reservations.get_by_generation(
                session_id=session_id,
                agent_member_id=agent_member_id,
                workspace_generation=workspace_generation,
            )
        )
        lease = self.repositories.agent_capability_leases.get_by_generation(
            session_id=session_id,
            agent_member_id=agent_member_id,
            workspace_generation=workspace_generation,
        )
        if (
            reservation is None
            or reservation.status is not AgentWorkspaceGenerationStatus.RESERVED
            or lease is None
            or lease.status is not AgentCapabilityLeaseStatus.PENDING_WORKSPACE
            or lease.agent_id != reservation.agent_id
        ):
            raise AgentGitWorkspaceConflictError(
                "workspace requires the exact reserved generation and pending lease"
            )
        if expected_workspace is not None and (
            reservation.reservation_id != expected_workspace.reservation_id
            or reservation.immutable_fingerprint
            != expected_workspace.reservation_fingerprint
            or lease.lease_id != expected_workspace.capability_lease_id
            or lease.canonical_digest
            != expected_workspace.capability_lease_intent_digest
            or lease.policy_version
            != expected_workspace.capability_policy_version
            or lease.policy_digest != expected_workspace.capability_policy_digest
        ):
            raise AgentGitWorkspaceConflictError(
                "workspace identity no longer matches its C2 pending intent"
            )
        if lease.policy_version != DEFAULT_AGENT_CAPABILITY_POLICY.policy_version or (
            lease.policy_digest != DEFAULT_AGENT_CAPABILITY_POLICY.policy_digest
        ):
            raise AgentGitWorkspaceConflictError(
                "pending capability lease policy no longer matches current policy"
            )
        return reservation, lease

    def _require_open_private_namespace(self, workspace: AgentGitWorkspace) -> None:
        row = self.repositories.tasks.connection.execute(
            """
            SELECT namespace_prefix, status
            FROM repository_private_namespace_records
            WHERE binding_id = ?
              AND binding_version = ?
              AND session_id = ?
              AND agent_member_id = ?
              AND workspace_generation = ?
            """,
            (
                workspace.repository_binding_id,
                workspace.repository_binding_version,
                workspace.session_id,
                workspace.agent_member_id,
                workspace.workspace_generation,
            ),
        ).fetchone()
        if (
            row is None
            or row["status"] != "open"
            or row["namespace_prefix"] != workspace.private_ref_namespace
        ):
            raise AgentGitWorkspaceTransitionError(
                "workspace readiness requires its exact open private namespace"
            )

    def _require_workspace(self, workspace_id: str) -> AgentGitWorkspace:
        workspace = self.repositories.agent_git_workspaces.get(workspace_id)
        if workspace is None:
            raise AgentGitWorkspaceConflictError(
                f"agent Git workspace {workspace_id!r} does not exist"
            )
        return workspace

    def _save_transition(
        self,
        workspace: AgentGitWorkspace,
        **updates: Any,
    ) -> AgentGitWorkspace:
        values = {
            field.name: getattr(workspace, field.name)
            for field in fields(AgentGitWorkspace)
            if field.name not in {"workspace_identity_digest", "canonical_digest"}
        }
        values.update(updates)
        values["state_version"] = workspace.state_version + 1
        transitioned = AgentGitWorkspace.create(**values)
        return self.repositories.agent_git_workspaces.update(
            transitioned,
            expected_state_version=workspace.state_version,
        )


def _blocker_for_drift(
    drift: tuple[AgentGitWorkspaceIdentityDriftKind, ...],
) -> AgentGitWorkspaceBlockerCode:
    mapping = {
        AgentGitWorkspaceIdentityDriftKind.VOLUME: (
            AgentGitWorkspaceBlockerCode.MISSING_VOLUME
        ),
        AgentGitWorkspaceIdentityDriftKind.GIT_DIRECTORY: (
            AgentGitWorkspaceBlockerCode.CORRUPT_GIT_DIRECTORY
        ),
        AgentGitWorkspaceIdentityDriftKind.REMOTE_IDENTITY: (
            AgentGitWorkspaceBlockerCode.REMOTE_IDENTITY_DRIFT
        ),
        AgentGitWorkspaceIdentityDriftKind.OBJECT_FORMAT: (
            AgentGitWorkspaceBlockerCode.OBJECT_FORMAT_DRIFT
        ),
        AgentGitWorkspaceIdentityDriftKind.BASE_COMMIT: (
            AgentGitWorkspaceBlockerCode.BASE_COMMIT_DRIFT
        ),
        AgentGitWorkspaceIdentityDriftKind.GENERATION: (
            AgentGitWorkspaceBlockerCode.GENERATION_DRIFT
        ),
        AgentGitWorkspaceIdentityDriftKind.HEAD_UNREADABLE: (
            AgentGitWorkspaceBlockerCode.UNREADABLE_HEAD
        ),
        AgentGitWorkspaceIdentityDriftKind.POLICY: (
            AgentGitWorkspaceBlockerCode.POLICY_DRIFT
        ),
    }
    for item in drift:
        blocker = mapping.get(item)
        if blocker is not None:
            return blocker
    return AgentGitWorkspaceBlockerCode.IDENTITY_DRIFT


__all__ = [
    "AgentGitWorkspaceConflictError",
    "AgentGitWorkspaceError",
    "AgentGitWorkspaceIdentityDriftError",
    "AgentGitWorkspaceLifecycleService",
    "AgentGitWorkspaceTransitionError",
]
