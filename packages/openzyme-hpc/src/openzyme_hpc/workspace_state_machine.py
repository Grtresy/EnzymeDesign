from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

from .contracts import ExecutorHpcCleanupDisposition
from .contracts import ExecutorHpcCredentialClaim
from .contracts import ExecutorHpcCredentialOperation
from .contracts import ExecutorHpcTargetQualification
from .contracts import ExecutorHpcWorkspace
from .contracts import ExecutorHpcWorkspaceCleanupIntent
from .contracts import ExecutorHpcWorkspaceCleanupReceipt
from .contracts import ExecutorHpcWorkspaceProvisionIntent
from .contracts import ExecutorHpcWorkspaceProvisionReceipt
from .contracts import ExecutorHpcWorkspaceState
from .contracts import canonical_executor_hpc_digest
from .workspace_lifecycle import ExecutorHpcWorkspaceIdentityConflict
from .workspace_lifecycle import ExecutorHpcWorkspaceObservation
from .workspace_lifecycle import ExecutorHpcWorkspaceObservationKind


@dataclass(frozen=True, slots=True)
class ExecutorHpcProvisionContext:
    project_id: str
    session_id: str
    executor_agent_id: str
    executor_agent_member_id: str
    local_workspace_id: str
    local_workspace_generation: int
    repository_binding_id: str
    repository_binding_version: int
    repository_id: str
    base_commit: str
    capability_lease_id: str
    capability_lease_version: int
    target: ExecutorHpcTargetQualification


class ExecutorHpcRevisionSourceKind(StrEnum):
    PRIVATE_CHECKPOINT = "private_checkpoint"
    PUBLISHED_REVISION = "published_revision"


@dataclass(frozen=True, slots=True)
class ExecutorHpcRevisionSource:
    source_kind: ExecutorHpcRevisionSourceKind
    source_id: str
    ref: str
    commit: str
    tree: str
    source_digest: str
    workspace_id: str | None
    project_id: str
    session_id: str
    agent_member_id: str | None
    workspace_generation: int | None
    repository_binding_id: str
    repository_binding_version: int
    repository_id: str
    publication_manifest_digest: str | None = None
    lfs_closure: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ExecutorHpcWorkspaceLifecycle:
    """Pure HPC-owned lifecycle rules; persistence and authority remain injected."""

    def create_provision_records(
        self,
        *,
        context: ExecutorHpcProvisionContext,
        remote_workspace_generation: int,
        idempotency_key: str,
        absolute_deadline: str,
        workspace_id: str,
        intent_id: str,
        created_at: str,
        prior_workspaces: tuple[ExecutorHpcWorkspace, ...] = (),
    ) -> tuple[ExecutorHpcWorkspaceProvisionIntent, ExecutorHpcWorkspace]:
        if remote_workspace_generation < 1:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "remote workspace generation must be positive"
            )
        if any(
            prior.target_profile_id == context.target.target_profile_id
            and (
                prior.local_workspace_generation > context.local_workspace_generation
                or (
                    prior.local_workspace_generation
                    == context.local_workspace_generation
                    and prior.remote_workspace_generation
                    >= remote_workspace_generation
                )
            )
            for prior in prior_workspaces
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "replacement requires a strictly higher local or remote generation"
            )
        try:
            now_value = datetime.fromisoformat(created_at)
            deadline_value = datetime.fromisoformat(absolute_deadline)
        except ValueError as exc:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "provision timestamps must be ISO-8601"
            ) from exc
        if (
            now_value.tzinfo is None
            or now_value.utcoffset() is None
            or deadline_value.tzinfo is None
            or deadline_value.utcoffset() is None
            or deadline_value <= now_value
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "provision absolute deadline must be an aware future timestamp"
            )
        target = context.target
        intent = ExecutorHpcWorkspaceProvisionIntent.create(
            intent_id=intent_id,
            workspace_id=workspace_id,
            project_id=context.project_id,
            session_id=context.session_id,
            executor_agent_member_id=context.executor_agent_member_id,
            local_workspace_generation=context.local_workspace_generation,
            remote_workspace_generation=remote_workspace_generation,
            repository_binding_id=context.repository_binding_id,
            repository_binding_version=context.repository_binding_version,
            repository_id=context.repository_id,
            base_commit=context.base_commit,
            target_profile_id=target.target_profile_id,
            target_profile_digest=target.target_profile_digest,
            root_policy_digest=target.root_policy_digest,
            capability_lease_id=context.capability_lease_id,
            capability_lease_version=context.capability_lease_version,
            idempotency_key=idempotency_key,
            absolute_deadline=absolute_deadline,
            created_at=created_at,
        )
        workspace = ExecutorHpcWorkspace(
            workspace_id=workspace_id,
            project_id=context.project_id,
            repository_binding_id=context.repository_binding_id,
            repository_binding_version=context.repository_binding_version,
            repository_id=context.repository_id,
            session_id=context.session_id,
            executor_agent_member_id=context.executor_agent_member_id,
            executor_agent_id=context.executor_agent_id,
            local_workspace_id=context.local_workspace_id,
            local_workspace_generation=context.local_workspace_generation,
            capability_lease_id=context.capability_lease_id,
            capability_lease_version=context.capability_lease_version,
            target_profile_id=target.target_profile_id,
            target_profile_digest=target.target_profile_digest,
            remote_workspace_generation=remote_workspace_generation,
            provision_intent_id=intent_id,
            runner_handle=None,
            provision_receipt_id=None,
            login_alias=None,
            remote_workspace_path=None,
            remote_root_digest=None,
            os_principal_identity_digest=None,
            isolation_receipt_digest=None,
            state=ExecutorHpcWorkspaceState.PROVISIONING,
            state_version=1,
            created_at=created_at,
            updated_at=created_at,
        )
        return intent, workspace

    def accept_provision_receipt(
        self,
        *,
        workspace: ExecutorHpcWorkspace,
        intent: ExecutorHpcWorkspaceProvisionIntent,
        target: ExecutorHpcTargetQualification,
        repository_binding_digest: str,
        receipt: ExecutorHpcWorkspaceProvisionReceipt,
    ) -> ExecutorHpcWorkspace:
        expected_owner_digest = canonical_executor_hpc_digest(
            {
                "session_id": intent.session_id,
                "executor_agent_member_id": intent.executor_agent_member_id,
                "local_workspace_generation": intent.local_workspace_generation,
                "remote_workspace_generation": intent.remote_workspace_generation,
                "capability_lease_id": intent.capability_lease_id,
                "capability_lease_version": intent.capability_lease_version,
            }
        )
        remote_path = PurePosixPath(receipt.remote_workspace_path)
        expected_root_digest = canonical_executor_hpc_digest(
            {
                "target_profile_digest": intent.target_profile_digest,
                "workspace_path": receipt.remote_workspace_path,
                "runner_handle": receipt.runner_handle,
            }
        )
        if (
            workspace.provision_intent_id != intent.intent_id
            or intent.workspace_id != workspace.workspace_id
            or receipt.intent_digest != intent.intent_digest
            or receipt.target_profile_digest != workspace.target_profile_digest
            or receipt.clone_head_commit != intent.base_commit
            or receipt.repository_remote_digest != repository_binding_digest
            or receipt.owner_identity_digest != expected_owner_digest
            or target.target_profile_id != intent.target_profile_id
            or receipt.login_alias != target.login_alias
            or remote_path.as_posix() != receipt.remote_workspace_path
            or remote_path.parent != PurePosixPath(target.workspace_root)
            or remote_path.name != receipt.runner_handle
            or receipt.remote_root_digest != expected_root_digest
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "provision receipt differs from the frozen workspace intent"
            )
        if workspace.state not in {
            ExecutorHpcWorkspaceState.PROVISIONING,
            ExecutorHpcWorkspaceState.PROVISION_RECONCILIATION_REQUIRED,
        }:
            if (
                workspace.state is ExecutorHpcWorkspaceState.READY
                and workspace.provision_receipt_id == receipt.receipt_id
            ):
                return workspace
            raise ExecutorHpcWorkspaceIdentityConflict(
                "provision receipt targets a non-provisioning workspace"
            )
        return replace(
            workspace,
            runner_handle=receipt.runner_handle,
            provision_receipt_id=receipt.receipt_id,
            login_alias=receipt.login_alias,
            remote_workspace_path=receipt.remote_workspace_path,
            remote_root_digest=receipt.remote_root_digest,
            os_principal_identity_digest=receipt.os_principal_identity_digest,
            isolation_receipt_digest=receipt.isolation_receipt_digest,
            state=ExecutorHpcWorkspaceState.READY,
            state_version=workspace.state_version + 1,
            updated_at=receipt.created_at,
            invalid_reason=None,
        )

    def apply_remote_observation(
        self,
        *,
        workspace: ExecutorHpcWorkspace,
        intent: ExecutorHpcWorkspaceProvisionIntent,
        repository_binding_digest: str,
        observation: ExecutorHpcWorkspaceObservation,
    ) -> ExecutorHpcWorkspace:
        if (
            observation.workspace_id != workspace.workspace_id
            or observation.intent_digest != intent.intent_digest
            or observation.runner_handle != workspace.runner_handle
            or observation.remote_root_digest != workspace.remote_root_digest
            or observation.os_principal_identity_digest
            != workspace.os_principal_identity_digest
            or observation.isolation_receipt_digest
            != workspace.isolation_receipt_digest
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "remote observation differs from canonical workspace identity"
            )
        if observation.kind is ExecutorHpcWorkspaceObservationKind.MATCHES:
            if (
                observation.repository_remote_digest
                == repository_binding_digest
                and observation.independent_git_directory
            ):
                return workspace
            return self.transition(
                workspace,
                ExecutorHpcWorkspaceState.INVALID,
                updated_at=observation.observed_at,
                invalid_reason="remote_clone_identity_drift",
            )
        if observation.kind is ExecutorHpcWorkspaceObservationKind.MISSING:
            return self.transition(
                workspace,
                ExecutorHpcWorkspaceState.MISSING,
                updated_at=observation.observed_at,
                invalid_reason="canonical_remote_root_missing",
            )
        return self.transition(
            workspace,
            ExecutorHpcWorkspaceState.INVALID,
            updated_at=observation.observed_at,
            invalid_reason="remote_root_or_clone_identity_invalid",
        )

    @staticmethod
    def owner_projection(
        workspace: ExecutorHpcWorkspace,
        *,
        owner_authorized: bool,
    ) -> dict[str, object]:
        projected = workspace.to_dict(include_owner_locator=False)
        projected["native_admission_available"] = False
        if owner_authorized and workspace.state is ExecutorHpcWorkspaceState.READY:
            projected.update(
                {
                    "scheduler_submit_authorized": False,
                    "workspace_tool_namespace": "hpc.workspace",
                }
            )
        return projected

    @staticmethod
    def create_native_credential_claim(
        *,
        workspace: ExecutorHpcWorkspace,
        target: ExecutorHpcTargetQualification,
        claim_id: str,
        issued_at: str,
        expires_at: str,
        operations: tuple[ExecutorHpcCredentialOperation, ...],
    ) -> ExecutorHpcCredentialClaim:
        if (
            workspace.state is not ExecutorHpcWorkspaceState.READY
            or workspace.login_alias is None
            or workspace.remote_workspace_path is None
            or workspace.remote_root_digest is None
            or workspace.os_principal_identity_digest is None
            or target.target_profile_id != workspace.target_profile_id
            or target.target_profile_digest != workspace.target_profile_digest
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "native credential requires exact ready workspace and target"
            )
        issued_time = datetime.fromisoformat(issued_at)
        expiry_time = datetime.fromisoformat(expires_at)
        if (
            issued_time.tzinfo is None
            or issued_time.utcoffset() is None
            or expiry_time.tzinfo is None
            or expiry_time.utcoffset() is None
            or expiry_time <= issued_time
            or (expiry_time - issued_time).total_seconds() > 300
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "native workspace credential TTL must be positive and at most 300 seconds"
            )
        return ExecutorHpcCredentialClaim(
            claim_id=claim_id,
            workspace_id=workspace.workspace_id,
            session_id=workspace.session_id,
            executor_agent_member_id=workspace.executor_agent_member_id,
            local_workspace_generation=workspace.local_workspace_generation,
            remote_workspace_generation=workspace.remote_workspace_generation,
            target_profile_id=workspace.target_profile_id,
            target_profile_digest=workspace.target_profile_digest,
            capability_lease_id=workspace.capability_lease_id,
            capability_lease_version=workspace.capability_lease_version,
            credential_provider_id=target.credential_provider_id,
            authenticator_id=target.authenticator_id,
            login_alias=workspace.login_alias,
            remote_workspace_path=workspace.remote_workspace_path,
            remote_root_digest=workspace.remote_root_digest,
            os_principal_identity_digest=workspace.os_principal_identity_digest,
            operations=operations,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    @staticmethod
    def revision_sync_identity(
        *,
        workspace: ExecutorHpcWorkspace,
        source: ExecutorHpcRevisionSource,
    ) -> dict[str, object]:
        if workspace.state is not ExecutorHpcWorkspaceState.READY:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "revision sync requires an exact ready workspace"
            )
        common_mismatch = (
            source.project_id != workspace.project_id
            or source.session_id != workspace.session_id
            or source.repository_binding_id != workspace.repository_binding_id
            or source.repository_binding_version
            != workspace.repository_binding_version
            or source.repository_id != workspace.repository_id
        )
        if common_mismatch:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "revision source is outside the exact workspace binding"
            )
        if source.source_kind is ExecutorHpcRevisionSourceKind.PRIVATE_CHECKPOINT:
            if (
                source.workspace_id != workspace.local_workspace_id
                or source.agent_member_id != workspace.executor_agent_member_id
                or source.workspace_generation
                != workspace.local_workspace_generation
                or source.publication_manifest_digest is not None
                or source.lfs_closure is not None
            ):
                raise ExecutorHpcWorkspaceIdentityConflict(
                    "private checkpoint is outside the exact workspace generation"
                )
        elif (
            source.source_kind is ExecutorHpcRevisionSourceKind.PUBLISHED_REVISION
            and (
                source.publication_manifest_digest is None
                or source.lfs_closure is None
                or source.workspace_id is not None
                or source.agent_member_id is not None
                or source.workspace_generation is not None
            )
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "published revision lacks exact manifest or LFS closure"
            )
        payload: dict[str, object] = {
            "schema_version": "executor_hpc_revision_sync_identity@1",
            "executor_hpc_workspace_id": workspace.workspace_id,
            "local_workspace_generation": workspace.local_workspace_generation,
            "remote_workspace_generation": workspace.remote_workspace_generation,
            "repository_binding_id": workspace.repository_binding_id,
            "repository_binding_version": workspace.repository_binding_version,
            "repository_id": workspace.repository_id,
            "fallback_permitted": False,
            "working_tree_mutation_performed": False,
            "source_kind": source.source_kind.value,
            "source_id": source.source_id,
            "ref": source.ref,
            "commit": source.commit,
            "tree": source.tree,
            "source_digest": source.source_digest,
            "lfs_closure": source.lfs_closure,
        }
        if source.publication_manifest_digest is not None:
            payload["publication_manifest_digest"] = (
                source.publication_manifest_digest
            )
        payload["identity_digest"] = canonical_executor_hpc_digest(payload)
        return payload

    @staticmethod
    def transition(
        workspace: ExecutorHpcWorkspace,
        state: ExecutorHpcWorkspaceState,
        *,
        updated_at: str,
        invalid_reason: str | None = None,
    ) -> ExecutorHpcWorkspace:
        return replace(
            workspace,
            state=state,
            state_version=workspace.state_version + 1,
            updated_at=updated_at,
            invalid_reason=invalid_reason,
        )

    def mark_retention_eligible(
        self,
        workspace: ExecutorHpcWorkspace,
        *,
        updated_at: str,
        reason: str,
    ) -> ExecutorHpcWorkspace:
        if workspace.state is ExecutorHpcWorkspaceState.RETENTION_ELIGIBLE:
            return workspace
        if workspace.state in {
            ExecutorHpcWorkspaceState.PROVISION_RECONCILIATION_REQUIRED,
            ExecutorHpcWorkspaceState.CLEANING,
            ExecutorHpcWorkspaceState.CLEANUP_RECONCILIATION_REQUIRED,
            ExecutorHpcWorkspaceState.CLEANED,
        }:
            return workspace
        return self.transition(
            workspace,
            ExecutorHpcWorkspaceState.RETENTION_ELIGIBLE,
            updated_at=updated_at,
            invalid_reason=reason,
        )

    @staticmethod
    def create_cleanup_intent(
        *,
        workspace: ExecutorHpcWorkspace,
        cleanup_intent_id: str,
        settlement_proof_digest: str,
        idempotency_key: str,
        created_at: str,
    ) -> ExecutorHpcWorkspaceCleanupIntent:
        if (
            workspace.state is not ExecutorHpcWorkspaceState.CLEANING
            or workspace.runner_handle is None
            or workspace.remote_root_digest is None
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "cleanup intent requires exact cleaning workspace identity"
            )
        return ExecutorHpcWorkspaceCleanupIntent.create(
            cleanup_intent_id=cleanup_intent_id,
            workspace_id=workspace.workspace_id,
            workspace_state_version=workspace.state_version,
            runner_handle=workspace.runner_handle,
            remote_root_digest=workspace.remote_root_digest,
            settlement_proof_digest=settlement_proof_digest,
            idempotency_key=idempotency_key,
            created_at=created_at,
        )

    def accept_cleanup_receipt(
        self,
        *,
        workspace: ExecutorHpcWorkspace,
        intent: ExecutorHpcWorkspaceCleanupIntent,
        receipt: ExecutorHpcWorkspaceCleanupReceipt,
    ) -> ExecutorHpcWorkspace:
        if (
            receipt.workspace_id != workspace.workspace_id
            or receipt.runner_handle != workspace.runner_handle
            or receipt.remote_root_digest != workspace.remote_root_digest
            or receipt.unsettled_effect_count != 0
            or receipt.cleanup_intent_id != intent.cleanup_intent_id
            or receipt.cleanup_intent_digest != intent.intent_digest
            or receipt.settlement_proof_digest != intent.settlement_proof_digest
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "cleanup receipt differs from exact settled workspace"
            )
        if receipt.disposition is ExecutorHpcCleanupDisposition.UNCERTAIN:
            if (
                workspace.state
                is ExecutorHpcWorkspaceState.CLEANUP_RECONCILIATION_REQUIRED
            ):
                return workspace
            return self.transition(
                workspace,
                ExecutorHpcWorkspaceState.CLEANUP_RECONCILIATION_REQUIRED,
                updated_at=receipt.created_at,
                invalid_reason="cleanup_effect_uncertain",
            )
        return self.transition(
            workspace,
            ExecutorHpcWorkspaceState.CLEANED,
            updated_at=receipt.created_at,
            invalid_reason=None,
        )


__all__ = [
    "ExecutorHpcProvisionContext",
    "ExecutorHpcRevisionSource",
    "ExecutorHpcRevisionSourceKind",
    "ExecutorHpcWorkspaceLifecycle",
]
