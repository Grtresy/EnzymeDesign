from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re
from typing import Protocol

from .contracts import ExecutorHpcCredentialClaim
from .contracts import ExecutorHpcWorkspace
from .contracts import ExecutorHpcWorkspaceCleanupIntent
from .contracts import ExecutorHpcWorkspaceCleanupReceipt
from .contracts import ExecutorHpcWorkspaceProvisionIntent
from .contracts import ExecutorHpcWorkspaceProvisionReceipt
from .contracts import canonical_executor_hpc_digest


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
    def create(cls, **values: object) -> ExecutorHpcWorkspaceObservation:
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
        if any("SBATCH" in key or "SCHEDULER" in key for key in keys):
            raise ValueError("native credential environment contains scheduler authority")
        if not set(keys) <= allowed:
            raise ValueError("credential provider returned an unknown environment name")
        if (
            not self.exact_secret_material
            or len(set(self.exact_secret_material)) != len(self.exact_secret_material)
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
    ) -> ExecutorHpcWorkspaceSettlementProof: ...


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
    def create(cls, **values: object) -> ExecutorHpcWorkspaceSettlementProof:
        payload = {
            "schema_version": "executor_hpc_workspace_settlement_proof@1",
            **values,
        }
        return cls(**values, proof_digest=canonical_executor_hpc_digest(payload))


class UnavailableExecutorHpcCredentialProvider:
    provider_id = "executor-hpc-native-unavailable"
    authenticator_id = "executor-hpc-native-unavailable"

    def issue(
        self,
        claim: ExecutorHpcCredentialClaim,
    ) -> IssuedExecutorHpcCredential:
        del claim
        raise ExecutorHpcWorkspaceProvisioningRequired(
            "native executor HPC credential provider is not configured"
        )

    def revoke(self, credential_fingerprint: str) -> None:
        del credential_fingerprint


def credential_fingerprint(credential_value: str) -> str:
    return canonical_executor_hpc_digest({"credential": credential_value})


__all__ = [
    "ExecutorHpcCredentialProvider",
    "ExecutorHpcWorkspaceCleaner",
    "ExecutorHpcWorkspaceDispatchInDoubt",
    "ExecutorHpcWorkspaceError",
    "ExecutorHpcWorkspaceExecutionRequired",
    "ExecutorHpcWorkspaceIdentityConflict",
    "ExecutorHpcWorkspaceObservation",
    "ExecutorHpcWorkspaceObservationKind",
    "ExecutorHpcWorkspaceProvisioner",
    "ExecutorHpcWorkspaceProvisioningRequired",
    "ExecutorHpcWorkspaceSettlementInspector",
    "ExecutorHpcWorkspaceSettlementProof",
    "IssuedExecutorHpcCredential",
    "UnavailableExecutorHpcCredentialProvider",
    "credential_fingerprint",
]
