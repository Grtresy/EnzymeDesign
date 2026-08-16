from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Protocol
from uuid import uuid4

from openzyme_domain import AgentCapability
from openzyme_domain import ExecutorHpcCredentialClaim
from openzyme_domain import ExecutorHpcCredentialOperation
from openzyme_domain import ExecutorHpcCleanupDisposition
from openzyme_domain import ExecutorHpcWorkspace
from openzyme_domain import ExecutorHpcWorkspaceCleanupIntent
from openzyme_domain import ExecutorHpcWorkspaceCleanupReceipt
from openzyme_domain import ExecutorHpcWorkspaceProvisionIntent
from openzyme_domain import ExecutorHpcWorkspaceProvisionReceipt
from openzyme_domain import ExecutorHpcWorkspaceState
from openzyme_domain import canonical_executor_hpc_digest

from .agent_capability_service import ActiveAgentCapabilityLeaseValidator
from .agent_capability_service import AgentCapabilityError
from .repositories import CoreRepositories


class ExecutorHpcWorkspaceError(RuntimeError):
    error_code = "executor_hpc_workspace_error"


class ExecutorHpcWorkspaceProvisioningRequired(ExecutorHpcWorkspaceError):
    error_code = "executor_hpc_workspace_provisioning_required"


class ExecutorHpcWorkspaceIdentityConflict(ExecutorHpcWorkspaceError):
    error_code = "executor_hpc_workspace_identity_conflict"


class ExecutorHpcWorkspaceDispatchInDoubt(ExecutorHpcWorkspaceError):
    error_code = "executor_hpc_workspace_dispatch_in_doubt"


class ExecutorHpcWorkspaceExecutionRequired(ExecutorHpcWorkspaceError):
    error_code = "workspace_revision_execution_required"


class ExecutorHpcWorkspaceObservationKind(StrEnum):
    MATCHES = "matches"
    MISSING = "missing"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class ExecutorHpcWorkspaceObservation:
    workspace_id: str
    intent_digest: str
    runner_handle: str
    remote_root_digest: str
    kind: ExecutorHpcWorkspaceObservationKind
    repository_remote_digest: str | None
    head_commit: str | None
    independent_git_directory: bool
    protected_root_mode: str | None
    os_principal_identity_digest: str | None
    isolation_receipt_digest: str | None
    observed_at: str
    observation_digest: str
    schema_version: str = "executor_hpc_workspace_observation@1"

    def __post_init__(self) -> None:
        if self.schema_version != "executor_hpc_workspace_observation@1":
            raise ValueError("unsupported executor HPC workspace observation schema")
        for name in ("workspace_id", "runner_handle"):
            if re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}",
                getattr(self, name),
            ) is None:
                raise ValueError(f"{name} is not a safe identity")
        for name in ("intent_digest", "remote_root_digest"):
            if re.fullmatch(r"sha256:[0-9a-f]{64}", getattr(self, name)) is None:
                raise ValueError(f"{name} is not a sha256 digest")
        if not isinstance(self.kind, ExecutorHpcWorkspaceObservationKind):
            raise TypeError("workspace observation kind is not closed")
        try:
            observed = datetime.fromisoformat(self.observed_at)
        except ValueError as exc:
            raise ValueError("observed_at is not ISO-8601") from exc
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("observed_at must include an explicit timezone")
        if not isinstance(self.independent_git_directory, bool):
            raise TypeError("independent_git_directory must be boolean")
        if self.repository_remote_digest is not None and re.fullmatch(
            r"sha256:[0-9a-f]{64}", self.repository_remote_digest
        ) is None:
            raise ValueError("repository_remote_digest is invalid")
        if self.head_commit is not None and re.fullmatch(
            r"(?:[0-9a-f]{40}|[0-9a-f]{64})", self.head_commit
        ) is None:
            raise ValueError("head_commit is invalid")
        if self.protected_root_mode is not None and re.fullmatch(
            r"[0-7]{3,4}", self.protected_root_mode
        ) is None:
            raise ValueError("protected_root_mode is invalid")
        for name in (
            "os_principal_identity_digest",
            "isolation_receipt_digest",
        ):
            value = getattr(self, name)
            if value is not None and re.fullmatch(
                r"sha256:[0-9a-f]{64}", value
            ) is None:
                raise ValueError(f"{name} is invalid")
        if self.kind is ExecutorHpcWorkspaceObservationKind.MATCHES and (
            self.repository_remote_digest is None
            or self.head_commit is None
            or not self.independent_git_directory
            or self.protected_root_mode != "700"
            or self.os_principal_identity_digest is None
            or self.isolation_receipt_digest is None
        ):
            raise ValueError("matching observation lacks protected clone facts")
        if self.observation_digest != canonical_executor_hpc_digest(self.payload):
            raise ValueError("executor HPC workspace observation digest mismatch")

    @property
    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "workspace_id": self.workspace_id,
            "intent_digest": self.intent_digest,
            "runner_handle": self.runner_handle,
            "remote_root_digest": self.remote_root_digest,
            "kind": self.kind.value,
            "repository_remote_digest": self.repository_remote_digest,
            "head_commit": self.head_commit,
            "independent_git_directory": self.independent_git_directory,
            "protected_root_mode": self.protected_root_mode,
            "os_principal_identity_digest": self.os_principal_identity_digest,
            "isolation_receipt_digest": self.isolation_receipt_digest,
            "observed_at": self.observed_at,
        }

    @classmethod
    def create(cls, **values: object) -> "ExecutorHpcWorkspaceObservation":
        payload = {
            "schema_version": "executor_hpc_workspace_observation@1",
            **{
                key: value.value if isinstance(value, StrEnum) else value
                for key, value in values.items()
            },
        }
        return cls(**values, observation_digest=canonical_executor_hpc_digest(payload))


@dataclass(frozen=True, slots=True)
class IssuedExecutorHpcCredential:
    claim: ExecutorHpcCredentialClaim
    credential_fingerprint: str
    authentication_receipt_digest: str
    environment: tuple[tuple[str, str], ...]
    exact_secret_material: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "credential_fingerprint",
            "authentication_receipt_digest",
        ):
            if re.fullmatch(r"sha256:[0-9a-f]{64}", getattr(self, name)) is None:
                raise ValueError(f"{name} must be a lowercase sha256 digest")
        keys = tuple(key for key, _ in self.environment)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("credential environment names must be unique and sorted")
        allowed = {
            "OPENZYME_HPC_AUTHENTICATOR_ID",
            "OPENZYME_HPC_CREDENTIAL_ID",
            "OPENZYME_HPC_LOGIN_ALIAS",
            "OPENZYME_HPC_OS_PRINCIPAL_IDENTITY_DIGEST",
            "OPENZYME_HPC_REMOTE_ROOT",
            "OPENZYME_HPC_SSH_CERTIFICATE_B64",
            "OPENZYME_HPC_SSH_PRIVATE_KEY_B64",
            "OPENZYME_HPC_TARGET_PROFILE_ID",
        }
        if not set(keys) <= allowed:
            raise ValueError("credential provider returned an unknown environment name")
        if any("SBATCH" in key or "SCHEDULER" in key for key in keys):
            raise ValueError("native credential environment contains scheduler authority")
        if (
            not self.exact_secret_material
            or len(set(self.exact_secret_material))
            != len(self.exact_secret_material)
            or any(not value for value in self.exact_secret_material)
        ):
            raise ValueError("issued native credential has no exact secret material")


class ExecutorHpcWorkspaceProvisioner(Protocol):
    def provision(
        self,
        intent: ExecutorHpcWorkspaceProvisionIntent,
    ) -> ExecutorHpcWorkspaceProvisionReceipt: ...

    def reconcile(
        self,
        intent: ExecutorHpcWorkspaceProvisionIntent,
    ) -> ExecutorHpcWorkspaceProvisionReceipt | None: ...

    def inspect_state(
        self,
        intent: ExecutorHpcWorkspaceProvisionIntent,
        workspace: ExecutorHpcWorkspace,
    ) -> ExecutorHpcWorkspaceObservation: ...


class ExecutorHpcCredentialProvider(Protocol):
    provider_id: str
    authenticator_id: str

    def issue(
        self,
        claim: ExecutorHpcCredentialClaim,
    ) -> IssuedExecutorHpcCredential: ...

    def revoke(self, credential_fingerprint: str) -> None: ...


class ExecutorHpcWorkspaceCleaner(Protocol):
    def cleanup(
        self,
        workspace: ExecutorHpcWorkspace,
        intent: ExecutorHpcWorkspaceProvisionIntent,
        cleanup_intent: ExecutorHpcWorkspaceCleanupIntent,
    ) -> ExecutorHpcWorkspaceCleanupReceipt: ...

    def reconcile_cleanup(
        self,
        workspace: ExecutorHpcWorkspace,
        intent: ExecutorHpcWorkspaceProvisionIntent,
        cleanup_intent: ExecutorHpcWorkspaceCleanupIntent,
    ) -> ExecutorHpcWorkspaceCleanupReceipt | None: ...


class ExecutorHpcWorkspaceSettlementInspector(Protocol):
    def prove_settled(
        self,
        workspace: ExecutorHpcWorkspace,
    ) -> "ExecutorHpcWorkspaceSettlementProof": ...


@dataclass(frozen=True, slots=True)
class ExecutorHpcWorkspaceSettlementProof:
    workspace_id: str
    workspace_state_version: int
    unsettled_effect_count: int
    observed_at: str
    proof_digest: str
    schema_version: str = "executor_hpc_workspace_settlement_proof@1"

    def __post_init__(self) -> None:
        if self.schema_version != "executor_hpc_workspace_settlement_proof@1":
            raise ValueError("unsupported executor HPC settlement proof schema")
        if re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", self.workspace_id
        ) is None:
            raise ValueError("settlement workspace_id is invalid")
        if (
            not isinstance(self.workspace_state_version, int)
            or not isinstance(self.unsettled_effect_count, int)
            or self.workspace_state_version < 1
            or self.unsettled_effect_count < 0
            or isinstance(self.workspace_state_version, bool)
            or isinstance(self.unsettled_effect_count, bool)
        ):
            raise ValueError("executor HPC settlement proof counters are invalid")
        try:
            observed = datetime.fromisoformat(self.observed_at)
        except ValueError as exc:
            raise ValueError("settlement observed_at is not ISO-8601") from exc
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("settlement observed_at must include an explicit timezone")
        if self.proof_digest != canonical_executor_hpc_digest(self.payload):
            raise ValueError("executor HPC settlement proof digest mismatch")

    @property
    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "workspace_id": self.workspace_id,
            "workspace_state_version": self.workspace_state_version,
            "unsettled_effect_count": self.unsettled_effect_count,
            "observed_at": self.observed_at,
        }

    @classmethod
    def create(cls, **values: object) -> "ExecutorHpcWorkspaceSettlementProof":
        payload = {
            "schema_version": "executor_hpc_workspace_settlement_proof@1",
            **values,
        }
        return cls(**values, proof_digest=canonical_executor_hpc_digest(payload))


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class ExecutorHpcWorkspaceService:
    repositories: CoreRepositories
    provisioner: ExecutorHpcWorkspaceProvisioner | None = None
    credential_provider: ExecutorHpcCredentialProvider | None = None
    cleaner: ExecutorHpcWorkspaceCleaner | None = None
    settlement_inspector: ExecutorHpcWorkspaceSettlementInspector | None = None

    def prepare_provisioning(
        self,
        *,
        session_id: str,
        executor_agent_id: str,
        target_profile_id: str,
        remote_workspace_generation: int,
        idempotency_key: str,
        absolute_deadline: str,
        workspace_id: str | None = None,
        intent_id: str | None = None,
        created_at: str | None = None,
    ) -> ExecutorHpcWorkspace:
        claims = ActiveAgentCapabilityLeaseValidator(
            self.repositories
        ).require_current_agent(
            session_id=session_id,
            agent_id=executor_agent_id,
            service_id="executor_hpc_workspace",
            protocol="native_hpc_login_workspace",
            operation_class="workspace_provision",
            required_capabilities=(
                AgentCapability.SSH,
                AgentCapability.RSYNC_SCP,
                AgentCapability.HPC_LOGIN_WORKSPACE_CRUD,
                AgentCapability.GIT,
                AgentCapability.GIT_LFS,
            ),
            target_id=target_profile_id,
        )
        target = self.repositories.executor_hpc_workspaces.get_target_qualification(
            target_profile_id
        )
        if target is None or not target.activated:
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "HPC target lacks native owner and isolation qualification"
            )
        session = self.repositories.sessions.get(session_id)
        if session is None:
            raise ExecutorHpcWorkspaceProvisioningRequired("session does not exist")
        pin = self.repositories.session_repository_binding_pins.get(session_id)
        if pin is None:
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "session has no exact repository binding pin"
            )
        local_workspace = claims.require_workspace()
        if (
            local_workspace.repository_binding_id != pin.binding_id
            or local_workspace.repository_binding_version != pin.binding_version
            or local_workspace.repository_id != pin.repository_id
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "local workspace and session repository identities differ"
            )
        replay = (
            self.repositories.executor_hpc_workspaces.get_intent_by_idempotency(
                session_id=session_id,
                executor_agent_member_id=claims.lease.agent_member_id,
                idempotency_key=idempotency_key,
            )
        )
        if replay is not None:
            replay_workspace = self._require_workspace(replay.workspace_id)
            if (
                replay.target_profile_id != target_profile_id
                or replay.remote_workspace_generation
                != remote_workspace_generation
                or replay.local_workspace_generation
                != local_workspace.workspace_generation
                or replay.absolute_deadline != absolute_deadline
                or (workspace_id is not None and workspace_id != replay.workspace_id)
                or (intent_id is not None and intent_id != replay.intent_id)
            ):
                raise ExecutorHpcWorkspaceIdentityConflict(
                    "provision idempotency key was reused with different identity"
                )
            return replay_workspace
        prior_workspaces = [
            prior
            for prior in self.repositories.executor_hpc_workspaces.list_by_agent_member(
                session_id=session_id,
                agent_member_id=claims.lease.agent_member_id,
            )
            if prior.target_profile_id == target_profile_id
        ]
        if any(
            prior.local_workspace_generation > local_workspace.workspace_generation
            or (
                prior.local_workspace_generation
                == local_workspace.workspace_generation
                and prior.remote_workspace_generation
                >= remote_workspace_generation
            )
            for prior in prior_workspaces
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "replacement requires a strictly higher local or remote generation"
            )
        now = created_at or _utc_now_iso()
        now_value = datetime.fromisoformat(now)
        deadline_value = datetime.fromisoformat(absolute_deadline)
        if (
            now_value.tzinfo is None
            or deadline_value.tzinfo is None
            or deadline_value <= now_value
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "provision absolute deadline must be an aware future timestamp"
            )
        allocated_workspace_id = workspace_id or f"hpcws_{uuid4().hex}"
        allocated_intent_id = intent_id or f"hpcintent_{uuid4().hex}"
        intent = ExecutorHpcWorkspaceProvisionIntent.create(
            intent_id=allocated_intent_id,
            workspace_id=allocated_workspace_id,
            project_id=session.project_id,
            session_id=session_id,
            executor_agent_member_id=claims.lease.agent_member_id,
            local_workspace_generation=local_workspace.workspace_generation,
            remote_workspace_generation=remote_workspace_generation,
            repository_binding_id=pin.binding_id,
            repository_binding_version=pin.binding_version,
            repository_id=pin.repository_id,
            base_commit=pin.resolved_base_commit,
            target_profile_id=target_profile_id,
            target_profile_digest=target.target_profile_digest,
            root_policy_digest=target.root_policy_digest,
            capability_lease_id=claims.lease.lease_id,
            capability_lease_version=claims.lease.state_version,
            idempotency_key=idempotency_key,
            absolute_deadline=absolute_deadline,
            created_at=now,
        )
        workspace = ExecutorHpcWorkspace(
            workspace_id=allocated_workspace_id,
            project_id=session.project_id,
            repository_binding_id=pin.binding_id,
            repository_binding_version=pin.binding_version,
            repository_id=pin.repository_id,
            session_id=session_id,
            executor_agent_member_id=claims.lease.agent_member_id,
            executor_agent_id=executor_agent_id,
            local_workspace_id=local_workspace.workspace_id,
            local_workspace_generation=local_workspace.workspace_generation,
            capability_lease_id=claims.lease.lease_id,
            capability_lease_version=claims.lease.state_version,
            target_profile_id=target_profile_id,
            target_profile_digest=target.target_profile_digest,
            remote_workspace_generation=remote_workspace_generation,
            provision_intent_id=allocated_intent_id,
            runner_handle=None,
            provision_receipt_id=None,
            login_alias=None,
            remote_workspace_path=None,
            remote_root_digest=None,
            os_principal_identity_digest=None,
            isolation_receipt_digest=None,
            state=ExecutorHpcWorkspaceState.PROVISIONING,
            state_version=1,
            created_at=now,
            updated_at=now,
        )
        with self.repositories.atomic(prefix="executor_hpc_workspace_prepare"):
            self.repositories.executor_hpc_workspaces.add_intent(
                intent,
                local_workspace_id=local_workspace.workspace_id,
            )
            self.repositories.executor_hpc_workspaces.add_workspace(workspace)
        for prior in prior_workspaces:
            if (
                prior.workspace_id != workspace.workspace_id
                and prior.target_profile_id == workspace.target_profile_id
                and prior.state
                not in {
                    ExecutorHpcWorkspaceState.RETENTION_ELIGIBLE,
                    ExecutorHpcWorkspaceState.CLEANING,
                    ExecutorHpcWorkspaceState.CLEANED,
                }
            ):
                self.mark_retention_eligible(
                    prior.workspace_id,
                    reason="superseded_by_explicit_higher_generation",
                )
        return workspace

    def provision(self, workspace_id: str) -> ExecutorHpcWorkspace:
        if self.provisioner is None:
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "executor HPC workspace provisioner is unavailable"
            )
        workspace = self._require_workspace(workspace_id)
        if workspace.state is ExecutorHpcWorkspaceState.READY:
            return workspace
        if (
            workspace.state
            is ExecutorHpcWorkspaceState.PROVISION_RECONCILIATION_REQUIRED
        ):
            return self.reconcile(workspace_id)
        if workspace.state is not ExecutorHpcWorkspaceState.PROVISIONING:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "workspace state cannot dispatch provisioning"
            )
        self._require_active_workspace_owner(workspace)
        intent = self._require_intent(workspace.provision_intent_id)
        try:
            receipt = self.provisioner.provision(intent)
        except ExecutorHpcWorkspaceDispatchInDoubt:
            return self._transition(
                workspace,
                ExecutorHpcWorkspaceState.PROVISION_RECONCILIATION_REQUIRED,
            )
        return self.accept_provision_receipt(receipt)

    def reconcile(self, workspace_id: str) -> ExecutorHpcWorkspace:
        if self.provisioner is None:
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "executor HPC workspace provisioner is unavailable"
            )
        workspace = self._require_workspace(workspace_id)
        if workspace.state is ExecutorHpcWorkspaceState.READY:
            return workspace
        if workspace.state not in {
            ExecutorHpcWorkspaceState.PROVISIONING,
            ExecutorHpcWorkspaceState.PROVISION_RECONCILIATION_REQUIRED,
        }:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "workspace state cannot reconcile provisioning"
            )
        intent = self._require_intent(workspace.provision_intent_id)
        receipt = self.provisioner.reconcile(intent)
        if receipt is None:
            if workspace.state is ExecutorHpcWorkspaceState.PROVISIONING:
                return self._transition(
                    workspace,
                    ExecutorHpcWorkspaceState.PROVISION_RECONCILIATION_REQUIRED,
                )
            return workspace
        return self.accept_provision_receipt(receipt)

    def verify_remote_state(self, workspace_id: str) -> ExecutorHpcWorkspace:
        if self.provisioner is None or not callable(
            getattr(self.provisioner, "inspect_state", None)
        ):
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "executor HPC exact remote verifier is unavailable"
            )
        workspace = self._require_workspace(workspace_id)
        if workspace.state is not ExecutorHpcWorkspaceState.READY:
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "formal remote verification requires exact ready state"
            )
        intent = self._require_intent(workspace.provision_intent_id)
        observation = self.provisioner.inspect_state(intent, workspace)
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
                != self._require_binding_digest(intent)
                or not observation.independent_git_directory
            ):
                return self._transition(
                    workspace,
                    ExecutorHpcWorkspaceState.INVALID,
                    invalid_reason="remote_clone_identity_drift",
                )
            return workspace
        if observation.kind is ExecutorHpcWorkspaceObservationKind.MISSING:
            return self._transition(
                workspace,
                ExecutorHpcWorkspaceState.MISSING,
                invalid_reason="canonical_remote_root_missing",
            )
        return self._transition(
            workspace,
            ExecutorHpcWorkspaceState.INVALID,
            invalid_reason="remote_root_or_clone_identity_invalid",
        )

    def accept_provision_receipt(
        self,
        receipt: ExecutorHpcWorkspaceProvisionReceipt,
    ) -> ExecutorHpcWorkspace:
        workspace = self._require_workspace(receipt.workspace_id)
        intent = self._require_intent(receipt.intent_id)
        binding_digest = self._require_binding_digest(intent)
        target = self.repositories.executor_hpc_workspaces.get_target_qualification(
            intent.target_profile_id
        )
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
            or receipt.repository_remote_digest != binding_digest
            or receipt.owner_identity_digest != expected_owner_digest
            or target is None
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
        ready = replace(
            workspace,
            runner_handle=receipt.runner_handle,
            provision_receipt_id=receipt.receipt_id,
            login_alias=receipt.login_alias,
            remote_workspace_path=receipt.remote_workspace_path,
            remote_root_digest=receipt.remote_root_digest,
            os_principal_identity_digest=(
                receipt.os_principal_identity_digest
            ),
            isolation_receipt_digest=receipt.isolation_receipt_digest,
            state=ExecutorHpcWorkspaceState.READY,
            state_version=workspace.state_version + 1,
            updated_at=receipt.created_at,
            invalid_reason=None,
        )
        with self.repositories.atomic(prefix="executor_hpc_workspace_accept"):
            self.repositories.executor_hpc_workspaces.add_receipt(receipt)
            self.repositories.executor_hpc_workspaces.transition(
                ready,
                expected_state_version=workspace.state_version,
            )
        try:
            self._require_active_workspace_owner(ready)
        except AgentCapabilityError:
            return self.mark_retention_eligible(
                ready.workspace_id,
                reason="owner_lease_inactive_after_provision_reconciliation",
            )
        return ready

    def owner_projection(
        self,
        *,
        workspace_id: str,
        session_id: str,
        agent_id: str,
    ) -> dict[str, object]:
        workspace = self._require_workspace(workspace_id)
        include_locator = (
            workspace.session_id == session_id
            and workspace.executor_agent_id == agent_id
            and workspace.state is ExecutorHpcWorkspaceState.READY
        )
        if include_locator:
            ActiveAgentCapabilityLeaseValidator(
                self.repositories
            ).require_current_agent(
                session_id=session_id,
                agent_id=agent_id,
                expected_lease_id=workspace.capability_lease_id,
                expected_workspace_generation=workspace.local_workspace_generation,
                service_id="executor_hpc_workspace_projection",
                protocol="owner_native_view",
                operation_class="workspace_inspect",
                required_capabilities=(AgentCapability.SSH,),
                target_id=workspace.target_profile_id,
            )
        projected = workspace.to_dict(include_owner_locator=include_locator)
        if include_locator:
            projected["credential_service_id"] = (
                f"hpc-native:{workspace.target_profile_id}"
            )
            projected["credential_audience"] = workspace.workspace_id
            projected["credential_protocols"] = [
                item.value for item in ExecutorHpcCredentialOperation
            ]
            projected["scheduler_submit_authorized"] = False
            projected["native_admission_available"] = True
        else:
            projected["native_admission_available"] = False
        return projected

    def owner_projections_for_agent(
        self,
        *,
        session_id: str,
        agent_id: str,
    ) -> tuple[dict[str, object], ...]:
        agent = self.repositories.agents.get(session_id, agent_id)
        if agent is None or agent.member_id is None:
            return ()
        projections: list[dict[str, object]] = []
        for workspace in self.repositories.executor_hpc_workspaces.list_by_agent_member(
            session_id=session_id,
            agent_member_id=agent.member_id,
        ):
            try:
                projections.append(
                    self.owner_projection(
                        workspace_id=workspace.workspace_id,
                        session_id=session_id,
                        agent_id=agent_id,
                    )
                )
            except AgentCapabilityError:
                safe = workspace.to_dict(include_owner_locator=False)
                safe["native_admission_available"] = False
                projections.append(safe)
        return tuple(projections)

    def revision_sync_identity(
        self,
        *,
        workspace_id: str,
        session_id: str,
        agent_id: str,
        checkpoint_id: str | None = None,
        publication_id: str | None = None,
    ) -> dict[str, object]:
        if (checkpoint_id is None) == (publication_id is None):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "revision sync requires exactly one checkpoint or publication"
            )
        workspace = self._require_workspace(workspace_id)
        if (
            workspace.state is not ExecutorHpcWorkspaceState.READY
            or workspace.session_id != session_id
            or workspace.executor_agent_id != agent_id
        ):
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "revision sync identity requires the exact ready workspace owner"
            )
        self._require_active_workspace_owner(workspace)
        workspace = self.verify_remote_state(workspace.workspace_id)
        if workspace.state is not ExecutorHpcWorkspaceState.READY:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "remote workspace drift blocks revision sync"
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
        }
        if checkpoint_id is not None:
            checkpoint = self.repositories.verified_workspace_checkpoints.get(
                checkpoint_id
            )
            if (
                checkpoint is None
                or checkpoint.workspace_id != workspace.local_workspace_id
                or checkpoint.session_id != workspace.session_id
                or checkpoint.agent_member_id
                != workspace.executor_agent_member_id
                or checkpoint.workspace_generation
                != workspace.local_workspace_generation
                or checkpoint.repository_binding_id
                != workspace.repository_binding_id
                or checkpoint.repository_binding_version
                != workspace.repository_binding_version
                or checkpoint.repository_id != workspace.repository_id
            ):
                raise ExecutorHpcWorkspaceIdentityConflict(
                    "private checkpoint is outside the exact workspace generation"
                )
            payload.update(
                {
                    "source_kind": "private_checkpoint",
                    "source_id": checkpoint.checkpoint_id,
                    "ref": checkpoint.private_ref,
                    "commit": checkpoint.commit,
                    "tree": checkpoint.tree,
                    "source_digest": checkpoint.checkpoint_digest,
                    "lfs_closure": None,
                }
            )
        else:
            revision = self.repositories.published_revisions.get(
                str(publication_id)
            )
            lfs_closure = self.repositories.git_lfs.publication_closure_projection(
                str(publication_id)
            )
            if (
                revision is None
                or revision.project_id != workspace.project_id
                or revision.session_id != workspace.session_id
                or revision.repository_binding_id
                != workspace.repository_binding_id
                or revision.repository_binding_version
                != workspace.repository_binding_version
                or revision.repository_id != workspace.repository_id
                or lfs_closure is None
            ):
                raise ExecutorHpcWorkspaceIdentityConflict(
                    "published revision lacks exact binding or LFS closure"
                )
            payload.update(
                {
                    "source_kind": "published_revision",
                    "source_id": revision.publication_id,
                    "ref": revision.publication_ref,
                    "commit": revision.commit,
                    "tree": revision.tree,
                    "source_digest": revision.revision_digest,
                    "publication_manifest_digest": (
                        revision.manifest.manifest_digest
                    ),
                    "lfs_closure": lfs_closure,
                }
            )
        payload["identity_digest"] = canonical_executor_hpc_digest(payload)
        return payload

    def issue_native_credential(
        self,
        *,
        workspace_id: str,
        session_id: str,
        agent_id: str,
        claim_id: str,
        expires_at: str,
        issued_at: str | None = None,
        operations: tuple[ExecutorHpcCredentialOperation, ...] | None = None,
    ) -> IssuedExecutorHpcCredential:
        if self.credential_provider is None:
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "executor HPC credential provider is unavailable"
            )
        workspace = self._require_workspace(workspace_id)
        if (
            workspace.state is not ExecutorHpcWorkspaceState.READY
            or workspace.session_id != session_id
            or workspace.executor_agent_id != agent_id
            or workspace.login_alias is None
            or workspace.remote_workspace_path is None
            or workspace.remote_root_digest is None
            or workspace.os_principal_identity_digest is None
        ):
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "executor HPC workspace is not exact ready owner state"
            )
        ActiveAgentCapabilityLeaseValidator(
            self.repositories
        ).require_current_agent(
            session_id=session_id,
            agent_id=agent_id,
            expected_lease_id=workspace.capability_lease_id,
            expected_workspace_generation=workspace.local_workspace_generation,
            service_id="executor_hpc_native_credential",
            protocol="target_scoped_ssh",
            operation_class="credential_issue",
            required_capabilities=(
                AgentCapability.SSH,
                AgentCapability.RSYNC_SCP,
                AgentCapability.HPC_LOGIN_WORKSPACE_CRUD,
                AgentCapability.GIT,
                AgentCapability.GIT_LFS,
            ),
            target_id=workspace.target_profile_id,
        )
        target = self.repositories.executor_hpc_workspaces.get_target_qualification(
            workspace.target_profile_id
        )
        if (
            target is None
            or self.credential_provider.provider_id != target.credential_provider_id
            or self.credential_provider.authenticator_id != target.authenticator_id
        ):
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "credential provider/authenticator does not match target qualification"
            )
        claim = ExecutorHpcCredentialClaim(
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
            os_principal_identity_digest=(
                workspace.os_principal_identity_digest
            ),
            operations=(
                tuple(ExecutorHpcCredentialOperation)
                if operations is None
                else operations
            ),
            issued_at=issued_at or _utc_now_iso(),
            expires_at=expires_at,
        )
        issued_time = datetime.fromisoformat(claim.issued_at)
        expiry_time = datetime.fromisoformat(claim.expires_at)
        if (
            issued_time.tzinfo is None
            or expiry_time.tzinfo is None
            or expiry_time <= issued_time
            or (expiry_time - issued_time).total_seconds() > 300
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "native workspace credential TTL must be positive and at most 300 seconds"
            )
        issued = self.credential_provider.issue(claim)
        if issued.claim != claim:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "credential provider changed the authorized claim"
            )
        environment = dict(issued.environment)
        if (
            environment.get("OPENZYME_HPC_CREDENTIAL_ID") != claim.claim_id
            or environment.get("OPENZYME_HPC_LOGIN_ALIAS")
            != workspace.login_alias
            or environment.get("OPENZYME_HPC_TARGET_PROFILE_ID")
            != workspace.target_profile_id
            or environment.get("OPENZYME_HPC_REMOTE_ROOT")
            != workspace.remote_workspace_path
            or environment.get(
                "OPENZYME_HPC_OS_PRINCIPAL_IDENTITY_DIGEST"
            )
            != workspace.os_principal_identity_digest
            or environment.get("OPENZYME_HPC_AUTHENTICATOR_ID")
            != target.authenticator_id
            or any(
                token in value.casefold()
                for _, value in issued.environment
                for token in ("scheduler.submit", "sbatch")
            )
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "native workspace credential changed its exact non-scheduler audience"
            )
        self.repositories.executor_hpc_workspaces.add_credential_claim(
            claim,
            credential_fingerprint=issued.credential_fingerprint,
            authentication_receipt_digest=(
                issued.authentication_receipt_digest
            ),
        )
        return issued

    def revoke_native_credential(
        self,
        *,
        claim_id: str,
        revoked_at: str | None = None,
    ) -> ExecutorHpcCredentialClaim:
        if self.credential_provider is None:
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "executor HPC credential provider is unavailable"
            )
        persisted = self.repositories.executor_hpc_workspaces.get_credential_claim(
            claim_id
        )
        if persisted is None:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "executor HPC credential claim does not exist"
            )
        claim, fingerprint = persisted
        if claim.revoked_at is not None:
            return claim
        self.credential_provider.revoke(fingerprint)
        return self.repositories.executor_hpc_workspaces.revoke_credential_claim(
            claim_id,
            revoked_at=revoked_at or _utc_now_iso(),
        )

    def mark_retention_eligible(
        self,
        workspace_id: str,
        *,
        reason: str,
    ) -> ExecutorHpcWorkspace:
        workspace = self._require_workspace(workspace_id)
        if workspace.state is ExecutorHpcWorkspaceState.RETENTION_ELIGIBLE:
            return workspace
        if (
            workspace.state
            is ExecutorHpcWorkspaceState.PROVISION_RECONCILIATION_REQUIRED
        ):
            # An accepted remote create may still exist. Preserve the exact
            # provisioning reconciler until it adopts or rejects that handle;
            # the inactive lease already closes new native admission.
            return workspace
        if workspace.state in {
            ExecutorHpcWorkspaceState.CLEANING,
            ExecutorHpcWorkspaceState.CLEANUP_RECONCILIATION_REQUIRED,
            ExecutorHpcWorkspaceState.CLEANED,
        }:
            return workspace
        self._revoke_active_workspace_credentials(workspace)
        return self._transition(
            workspace,
            ExecutorHpcWorkspaceState.RETENTION_ELIGIBLE,
            invalid_reason=reason,
        )

    def reconcile_owner_admission(
        self,
        *,
        session_id: str,
    ) -> tuple[ExecutorHpcWorkspace, ...]:
        reconciled: list[ExecutorHpcWorkspace] = []
        for workspace in self.repositories.executor_hpc_workspaces.list_by_session(
            session_id
        ):
            if workspace.state in {
                ExecutorHpcWorkspaceState.RETENTION_ELIGIBLE,
                ExecutorHpcWorkspaceState.CLEANING,
                ExecutorHpcWorkspaceState.CLEANED,
            }:
                reconciled.append(workspace)
                continue
            try:
                ActiveAgentCapabilityLeaseValidator(
                    self.repositories
                ).require_current_agent(
                    session_id=session_id,
                    agent_id=workspace.executor_agent_id,
                    expected_lease_id=workspace.capability_lease_id,
                    expected_workspace_generation=(
                        workspace.local_workspace_generation
                    ),
                    service_id="executor_hpc_workspace_admission_reconcile",
                    protocol="native_hpc_login_workspace",
                    operation_class="workspace_admission_reconcile",
                    required_capabilities=(
                        AgentCapability.SSH,
                        AgentCapability.RSYNC_SCP,
                        AgentCapability.HPC_LOGIN_WORKSPACE_CRUD,
                        AgentCapability.GIT,
                        AgentCapability.GIT_LFS,
                    ),
                    target_id=workspace.target_profile_id,
                )
            except AgentCapabilityError:
                reconciled.append(
                    self.mark_retention_eligible(
                        workspace.workspace_id,
                        reason=(
                            "owner_session_retirement_lease_or_generation_inactive"
                        ),
                    )
                )
            else:
                reconciled.append(workspace)
        return tuple(reconciled)

    def cleanup(
        self,
        workspace_id: str,
        *,
        idempotency_key: str,
    ) -> ExecutorHpcWorkspace:
        if self.cleaner is None or self.settlement_inspector is None:
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "executor HPC cleanup requires exact cleaner and settlement inspector"
            )
        workspace = self._require_workspace(workspace_id)
        if workspace.state is ExecutorHpcWorkspaceState.CLEANED:
            return workspace
        if workspace.state not in {
            ExecutorHpcWorkspaceState.RETENTION_ELIGIBLE,
            ExecutorHpcWorkspaceState.CLEANING,
            ExecutorHpcWorkspaceState.CLEANUP_RECONCILIATION_REQUIRED,
        }:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "executor HPC workspace is not cleanup eligible"
            )
        if (
            workspace.state
            is ExecutorHpcWorkspaceState.CLEANUP_RECONCILIATION_REQUIRED
        ):
            return self.reconcile_cleanup(workspace_id)
        self._revoke_active_workspace_credentials(workspace)
        cleanup_intent = (
            self.repositories.executor_hpc_workspaces.get_cleanup_intent_by_workspace(
                workspace.workspace_id
            )
        )
        if workspace.state is ExecutorHpcWorkspaceState.RETENTION_ELIGIBLE:
            if (
                workspace.runner_handle is None
                or workspace.remote_root_digest is None
                or workspace.provision_receipt_id is None
            ):
                raise ExecutorHpcWorkspaceProvisioningRequired(
                    "retained pre-dispatch workspace has no remote cleanup effect"
                )
            workspace = self._transition(
                workspace,
                ExecutorHpcWorkspaceState.CLEANING,
                invalid_reason="cleanup_started_pending_settlement_proof",
            )
        if cleanup_intent is None:
            settlement_proof = self.settlement_inspector.prove_settled(workspace)
            if (
                settlement_proof.workspace_id != workspace.workspace_id
                or settlement_proof.workspace_state_version
                != workspace.state_version
            ):
                raise ExecutorHpcWorkspaceIdentityConflict(
                    "settlement proof does not bind the exact workspace version"
                )
            if settlement_proof.unsettled_effect_count:
                raise ExecutorHpcWorkspaceProvisioningRequired(
                    "executor HPC workspace retains unsettled controlled effects"
                )
            if workspace.runner_handle is None or workspace.remote_root_digest is None:
                raise ExecutorHpcWorkspaceIdentityConflict(
                    "cleanup workspace lacks exact remote identity"
                )
            cleanup_intent = ExecutorHpcWorkspaceCleanupIntent.create(
                cleanup_intent_id=f"hpccleanupintent_{uuid4().hex}",
                workspace_id=workspace.workspace_id,
                workspace_state_version=workspace.state_version,
                runner_handle=workspace.runner_handle,
                remote_root_digest=workspace.remote_root_digest,
                settlement_proof_digest=settlement_proof.proof_digest,
                idempotency_key=idempotency_key,
                created_at=_utc_now_iso(),
            )
            self.repositories.executor_hpc_workspaces.add_cleanup_intent(
                cleanup_intent
            )
        elif cleanup_intent.idempotency_key != idempotency_key:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "cleanup replay changed the immutable idempotency key"
            )
        intent = self._require_intent(workspace.provision_intent_id)
        try:
            receipt = self.cleaner.cleanup(workspace, intent, cleanup_intent)
        except ExecutorHpcWorkspaceDispatchInDoubt:
            return self._transition(
                workspace,
                ExecutorHpcWorkspaceState.CLEANUP_RECONCILIATION_REQUIRED,
                invalid_reason="cleanup_dispatch_in_doubt",
            )
        return self._accept_cleanup_receipt(
            workspace,
            receipt,
            cleanup_intent,
        )

    def reconcile_cleanup(self, workspace_id: str) -> ExecutorHpcWorkspace:
        if self.cleaner is None:
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "executor HPC cleanup reconciler is unavailable"
            )
        workspace = self._require_workspace(workspace_id)
        if workspace.state is ExecutorHpcWorkspaceState.CLEANED:
            return workspace
        if workspace.state not in {
            ExecutorHpcWorkspaceState.CLEANING,
            ExecutorHpcWorkspaceState.CLEANUP_RECONCILIATION_REQUIRED,
        }:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "workspace state cannot reconcile cleanup"
            )
        cleanup_intent = (
            self.repositories.executor_hpc_workspaces.get_cleanup_intent_by_workspace(
                workspace.workspace_id
            )
        )
        if cleanup_intent is None:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "cleanup reconciliation has no immutable intent"
            )
        receipt = self.cleaner.reconcile_cleanup(
            workspace,
            self._require_intent(workspace.provision_intent_id),
            cleanup_intent,
        )
        if receipt is None:
            return workspace
        return self._accept_cleanup_receipt(
            workspace,
            receipt,
            cleanup_intent,
        )

    def _accept_cleanup_receipt(
        self,
        workspace: ExecutorHpcWorkspace,
        receipt: ExecutorHpcWorkspaceCleanupReceipt,
        cleanup_intent: ExecutorHpcWorkspaceCleanupIntent,
    ) -> ExecutorHpcWorkspace:
        if (
            receipt.workspace_id != workspace.workspace_id
            or receipt.runner_handle != workspace.runner_handle
            or receipt.remote_root_digest != workspace.remote_root_digest
            or receipt.unsettled_effect_count != 0
            or receipt.cleanup_intent_id != cleanup_intent.cleanup_intent_id
            or receipt.cleanup_intent_digest != cleanup_intent.intent_digest
            or receipt.settlement_proof_digest
            != cleanup_intent.settlement_proof_digest
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
            return self._transition(
                workspace,
                ExecutorHpcWorkspaceState.CLEANUP_RECONCILIATION_REQUIRED,
                invalid_reason="cleanup_effect_uncertain",
            )
        target_state = (
            ExecutorHpcWorkspaceState.CLEANED
            if receipt.disposition in {
                ExecutorHpcCleanupDisposition.DELETED,
                ExecutorHpcCleanupDisposition.RETAINED,
            }
            else ExecutorHpcWorkspaceState.CLEANUP_RECONCILIATION_REQUIRED
        )
        transitioned = replace(
            workspace,
            state=target_state,
            state_version=workspace.state_version + 1,
            updated_at=receipt.created_at,
            invalid_reason=(
                None
                if target_state is ExecutorHpcWorkspaceState.CLEANED
                else "cleanup_effect_uncertain"
            ),
        )
        with self.repositories.atomic(prefix="executor_hpc_workspace_cleanup_accept"):
            self.repositories.executor_hpc_workspaces.add_cleanup_receipt(receipt)
            self.repositories.executor_hpc_workspaces.transition(
                transitioned,
                expected_state_version=workspace.state_version,
            )
        return transitioned

    def _revoke_active_workspace_credentials(
        self,
        workspace: ExecutorHpcWorkspace,
    ) -> None:
        for claim, _ in (
            self.repositories.executor_hpc_workspaces.list_active_credential_claims(
                workspace.workspace_id
            )
        ):
            self.revoke_native_credential(claim_id=claim.claim_id)

    def require_job_change(self, workspace_id: str) -> None:
        self._require_workspace(workspace_id)
        raise ExecutorHpcWorkspaceExecutionRequired(
            "HPC job admission remains closed until workspace-revision execution is installed"
        )

    def _transition(
        self,
        workspace: ExecutorHpcWorkspace,
        state: ExecutorHpcWorkspaceState,
        *,
        invalid_reason: str | None = None,
    ) -> ExecutorHpcWorkspace:
        transitioned = replace(
            workspace,
            state=state,
            state_version=workspace.state_version + 1,
            updated_at=_utc_now_iso(),
            invalid_reason=invalid_reason,
        )
        return self.repositories.executor_hpc_workspaces.transition(
            transitioned,
            expected_state_version=workspace.state_version,
        )

    def _require_workspace(self, workspace_id: str) -> ExecutorHpcWorkspace:
        workspace = self.repositories.executor_hpc_workspaces.get(workspace_id)
        if workspace is None:
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "executor HPC workspace does not exist"
            )
        return workspace

    def _require_intent(
        self,
        intent_id: str,
    ) -> ExecutorHpcWorkspaceProvisionIntent:
        intent = self.repositories.executor_hpc_workspaces.get_intent(intent_id)
        if intent is None:
            raise ExecutorHpcWorkspaceIdentityConflict(
                "executor HPC provision intent does not exist"
            )
        return intent

    def _require_binding_digest(
        self,
        intent: ExecutorHpcWorkspaceProvisionIntent,
    ) -> str:
        binding = self.repositories.project_repository_bindings.get(
            intent.repository_binding_id
        )
        if (
            binding is None
            or binding.binding_version != intent.repository_binding_version
            or binding.repository_id != intent.repository_id
        ):
            raise ExecutorHpcWorkspaceIdentityConflict(
                "executor HPC workspace repository binding is unavailable"
            )
        return binding.canonical_digest

    def _require_active_workspace_owner(
        self,
        workspace: ExecutorHpcWorkspace,
    ) -> None:
        ActiveAgentCapabilityLeaseValidator(
            self.repositories
        ).require_current_agent(
            session_id=workspace.session_id,
            agent_id=workspace.executor_agent_id,
            expected_lease_id=workspace.capability_lease_id,
            expected_workspace_generation=workspace.local_workspace_generation,
            service_id="executor_hpc_workspace",
            protocol="native_hpc_login_workspace",
            operation_class="workspace_provision",
            required_capabilities=(
                AgentCapability.SSH,
                AgentCapability.RSYNC_SCP,
                AgentCapability.HPC_LOGIN_WORKSPACE_CRUD,
                AgentCapability.GIT,
                AgentCapability.GIT_LFS,
            ),
            target_id=workspace.target_profile_id,
        )


@dataclass(slots=True)
class UnavailableExecutorHpcCredentialProvider:
    provider_id: str = "unavailable"
    authenticator_id: str = "unavailable"

    def issue(
        self,
        claim: ExecutorHpcCredentialClaim,
    ) -> IssuedExecutorHpcCredential:
        raise ExecutorHpcWorkspaceProvisioningRequired(
            "real target credential provider is not configured"
        )

    def revoke(self, credential_fingerprint: str) -> None:
        raise ExecutorHpcWorkspaceProvisioningRequired(
            "real target credential provider is not configured"
        )


def credential_fingerprint(secret: bytes) -> str:
    return f"sha256:{hashlib.sha256(secret).hexdigest()}"


def register_executor_hpc_workspace_tools(
    registry: object,
    *,
    agent_id: str,
) -> None:
    from .harness import SessionRuntimeContext
    from .harness import ToolInvocation
    from .harness import ToolResult

    def _service(context: SessionRuntimeContext) -> ExecutorHpcWorkspaceService:
        service = context.executor_hpc_workspace_service
        if (
            service is None
            or service.repositories.connection is not context.repositories.connection
        ):
            raise ExecutorHpcWorkspaceProvisioningRequired(
                "executor HPC workspace service is unavailable in this repository scope"
            )
        return service

    def _error(
        invocation: ToolInvocation,
        exc: Exception,
    ) -> ToolResult:
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=False,
            content=str(exc),
            status="executor_hpc_workspace_rejected",
            summary="Executor HPC workspace request was rejected.",
            error_code=getattr(exc, "error_code", "executor_hpc_workspace_error"),
            details={"fallback_performed": False, "external_effect_replayed": False},
        )

    def _string_argument(invocation: ToolInvocation, name: str) -> str:
        value = invocation.arguments[name]
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
        return value

    def request_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        try:
            generation = invocation.arguments["remote_workspace_generation"]
            if not isinstance(generation, int) or isinstance(generation, bool):
                raise ValueError("remote_workspace_generation must be an integer")
            service = _service(context)
            workspace = service.prepare_provisioning(
                session_id=context.snapshot.session.session_id,
                executor_agent_id=agent_id,
                target_profile_id=_string_argument(
                    invocation, "target_profile_id"
                ),
                remote_workspace_generation=generation,
                idempotency_key=_string_argument(invocation, "idempotency_key"),
                absolute_deadline=_string_argument(
                    invocation, "absolute_deadline"
                ),
            )
            workspace = service.provision(workspace.workspace_id)
            payload = service.owner_projection(
                workspace_id=workspace.workspace_id,
                session_id=workspace.session_id,
                agent_id=agent_id,
            )
        except (KeyError, ValueError, ExecutorHpcWorkspaceError) as exc:
            return _error(invocation, exc)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=workspace.state is ExecutorHpcWorkspaceState.READY,
            content=json.dumps(payload, sort_keys=True),
            status=f"executor_hpc_workspace_{workspace.state.value}",
            summary=(
                "Executor HPC workspace is ready for owner-scoped native login."
                if workspace.state is ExecutorHpcWorkspaceState.READY
                else "Executor HPC workspace requires exact reconciliation."
            ),
            error_code=(
                None
                if workspace.state is ExecutorHpcWorkspaceState.READY
                else "executor_hpc_workspace_dispatch_in_doubt"
            ),
            details=payload,
        )

    def inspect_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        try:
            payload = _service(context).owner_projection(
                workspace_id=_string_argument(invocation, "workspace_id"),
                session_id=context.snapshot.session.session_id,
                agent_id=agent_id,
            )
        except (KeyError, ValueError, ExecutorHpcWorkspaceError) as exc:
            return _error(invocation, exc)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            status="executor_hpc_workspace_observed",
            summary="Projected the exact owner-authorized HPC workspace view.",
            details=payload,
        )

    def verify_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        try:
            service = _service(context)
            workspace = service.verify_remote_state(
                _string_argument(invocation, "workspace_id")
            )
            payload = service.owner_projection(
                workspace_id=workspace.workspace_id,
                session_id=context.snapshot.session.session_id,
                agent_id=agent_id,
            )
        except (KeyError, ValueError, ExecutorHpcWorkspaceError) as exc:
            return _error(invocation, exc)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=workspace.state is ExecutorHpcWorkspaceState.READY,
            content=json.dumps(payload, sort_keys=True),
            status=f"executor_hpc_workspace_{workspace.state.value}",
            summary="Verified exact remote root and clone identity.",
            error_code=(
                None
                if workspace.state is ExecutorHpcWorkspaceState.READY
                else "executor_hpc_workspace_identity_drift"
            ),
            details=payload,
        )

    def sync_source_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        try:
            checkpoint_id = invocation.arguments.get("checkpoint_id")
            publication_id = invocation.arguments.get("publication_id")
            if checkpoint_id is not None and not isinstance(checkpoint_id, str):
                raise ValueError("checkpoint_id must be a string")
            if publication_id is not None and not isinstance(publication_id, str):
                raise ValueError("publication_id must be a string")
            payload = _service(context).revision_sync_identity(
                workspace_id=_string_argument(invocation, "workspace_id"),
                session_id=context.snapshot.session.session_id,
                agent_id=agent_id,
                checkpoint_id=checkpoint_id,
                publication_id=publication_id,
            )
        except (KeyError, ValueError, ExecutorHpcWorkspaceError) as exc:
            return _error(invocation, exc)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            status="executor_hpc_revision_sync_identity_ready",
            summary=(
                "Projected an exact revision identity; no Git working tree mutation was performed."
            ),
            details=payload,
        )

    registry.register("hpc.workspace.request", request_handler)
    registry.register("hpc.workspace.inspect", inspect_handler)
    registry.register("hpc.workspace.verify", verify_handler)
    registry.register("hpc.workspace.sync_source", sync_source_handler)


__all__ = [
    "ExecutorHpcCredentialProvider",
    "ExecutorHpcWorkspaceDispatchInDoubt",
    "ExecutorHpcWorkspaceError",
    "ExecutorHpcWorkspaceExecutionRequired",
    "ExecutorHpcWorkspaceObservation",
    "ExecutorHpcWorkspaceObservationKind",
    "ExecutorHpcWorkspaceIdentityConflict",
    "ExecutorHpcWorkspaceProvisioner",
    "ExecutorHpcWorkspaceCleaner",
    "ExecutorHpcWorkspaceSettlementInspector",
    "ExecutorHpcWorkspaceSettlementProof",
    "ExecutorHpcWorkspaceProvisioningRequired",
    "ExecutorHpcWorkspaceService",
    "IssuedExecutorHpcCredential",
    "UnavailableExecutorHpcCredentialProvider",
    "credential_fingerprint",
    "register_executor_hpc_workspace_tools",
]
