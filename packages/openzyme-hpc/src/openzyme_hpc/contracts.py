from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import re
from typing import Any


EXECUTOR_HPC_WORKSPACE_SCHEMA_VERSION = "executor_hpc_workspace@1"
EXECUTOR_HPC_PROVISION_INTENT_SCHEMA_VERSION = (
    "executor_hpc_workspace_provision_intent@1"
)
EXECUTOR_HPC_PROVISION_RECEIPT_SCHEMA_VERSION = (
    "executor_hpc_workspace_provision_receipt@1"
)
EXECUTOR_HPC_CREDENTIAL_CLAIM_SCHEMA_VERSION = "executor_hpc_credential_claim@1"
EXECUTOR_HPC_CLEANUP_RECEIPT_SCHEMA_VERSION = (
    "executor_hpc_workspace_cleanup_receipt@1"
)
EXECUTOR_HPC_CLEANUP_INTENT_SCHEMA_VERSION = (
    "executor_hpc_workspace_cleanup_intent@1"
)
EXECUTOR_HPC_TARGET_QUALIFICATION_SCHEMA_VERSION = (
    "executor_hpc_target_qualification@2"
)

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class ExecutorHpcWorkspaceState(StrEnum):
    PROVISIONING = "provisioning"
    READY = "ready"
    INVALID = "invalid"
    MISSING = "missing"
    PROVISION_RECONCILIATION_REQUIRED = "provision_reconciliation_required"
    RETENTION_ELIGIBLE = "retention_eligible"
    CLEANING = "cleaning"
    CLEANUP_RECONCILIATION_REQUIRED = "cleanup_reconciliation_required"
    CLEANED = "cleaned"


class ExecutorHpcCredentialOperation(StrEnum):
    SSH_LOGIN = "ssh_login"
    RSYNC = "rsync"
    SCP = "scp"
    GIT = "git"
    GIT_LFS = "git_lfs"
    WORKSPACE_CRUD = "workspace_crud"


class ExecutorHpcCleanupDisposition(StrEnum):
    DELETED = "deleted"
    RETAINED = "retained"
    UNCERTAIN = "uncertain"


def _require_identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{name} must be a closed non-empty identifier")


def _require_digest(value: str, name: str) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase sha256 digest")


def _require_remote_locator(value: str, name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or len(value.encode("utf-8")) > 2048
    ):
        raise ValueError(f"{name} must be a bounded exact remote locator")


def _require_timestamp(value: str, name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(character.isspace() for character in value)
        or len(value.encode("utf-8")) > 128
    ):
        raise ValueError(f"{name} must be a bounded exact timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include an explicit timezone")


def canonical_executor_hpc_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True, slots=True)
class ExecutorHpcWorkspace:
    workspace_id: str
    project_id: str
    repository_binding_id: str
    repository_binding_version: int
    repository_id: str
    session_id: str
    executor_agent_member_id: str
    executor_agent_id: str
    local_workspace_id: str
    local_workspace_generation: int
    capability_lease_id: str
    capability_lease_version: int
    target_profile_id: str
    target_profile_digest: str
    remote_workspace_generation: int
    provision_intent_id: str
    runner_handle: str | None
    provision_receipt_id: str | None
    login_alias: str | None
    remote_workspace_path: str | None
    remote_root_digest: str | None
    os_principal_identity_digest: str | None
    isolation_receipt_digest: str | None
    state: ExecutorHpcWorkspaceState
    state_version: int
    created_at: str
    updated_at: str
    invalid_reason: str | None = None
    schema_version: str = EXECUTOR_HPC_WORKSPACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTOR_HPC_WORKSPACE_SCHEMA_VERSION:
            raise ValueError("unsupported executor HPC workspace schema")
        for name in (
            "workspace_id",
            "project_id",
            "repository_binding_id",
            "repository_id",
            "session_id",
            "executor_agent_member_id",
            "executor_agent_id",
            "local_workspace_id",
            "capability_lease_id",
            "target_profile_id",
            "provision_intent_id",
        ):
            _require_identifier(getattr(self, name), name)
        _require_timestamp(self.created_at, "created_at")
        _require_timestamp(self.updated_at, "updated_at")
        for name in (
            "repository_binding_version",
            "local_workspace_generation",
            "capability_lease_version",
            "remote_workspace_generation",
            "state_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        _require_digest(self.target_profile_digest, "target_profile_digest")
        if not isinstance(self.state, ExecutorHpcWorkspaceState):
            raise TypeError("state must be an ExecutorHpcWorkspaceState")
        locator_values = (
            self.runner_handle,
            self.login_alias,
            self.remote_workspace_path,
            self.remote_root_digest,
            self.os_principal_identity_digest,
            self.isolation_receipt_digest,
        )
        if self.state in {
            ExecutorHpcWorkspaceState.PROVISIONING,
            ExecutorHpcWorkspaceState.PROVISION_RECONCILIATION_REQUIRED,
        }:
            if any(value is not None for value in locator_values):
                raise ValueError(
                    "unsettled provisioning workspace cannot claim remote locators"
                )
            if self.provision_receipt_id is not None:
                raise ValueError(
                    "unsettled provisioning workspace cannot claim a receipt"
                )
        elif self.state is ExecutorHpcWorkspaceState.READY:
            if any(value is None for value in locator_values):
                raise ValueError("ready workspace requires exact remote locators")
            if self.provision_receipt_id is None:
                raise ValueError("ready workspace requires a provision receipt")
        elif self.state in {
            ExecutorHpcWorkspaceState.CLEANING,
            ExecutorHpcWorkspaceState.CLEANUP_RECONCILIATION_REQUIRED,
            ExecutorHpcWorkspaceState.CLEANED,
        } and (
            any(value is None for value in locator_values)
            or self.provision_receipt_id is None
        ):
            raise ValueError("cleanup lifecycle requires exact remote identity")
        if self.runner_handle is not None:
            _require_identifier(self.runner_handle, "runner_handle")
        if self.provision_receipt_id is not None:
            _require_identifier(self.provision_receipt_id, "provision_receipt_id")
        if self.login_alias is not None:
            _require_remote_locator(self.login_alias, "login_alias")
        if self.remote_workspace_path is not None:
            _require_remote_locator(
                self.remote_workspace_path,
                "remote_workspace_path",
            )
        if self.remote_root_digest is not None:
            _require_digest(self.remote_root_digest, "remote_root_digest")
        if self.os_principal_identity_digest is not None:
            _require_digest(
                self.os_principal_identity_digest,
                "os_principal_identity_digest",
            )
        if self.isolation_receipt_digest is not None:
            _require_digest(
                self.isolation_receipt_digest,
                "isolation_receipt_digest",
            )
        if self.invalid_reason is not None and (
            not self.invalid_reason
            or len(self.invalid_reason.encode("utf-8")) > 512
        ):
            raise ValueError("invalid_reason must be bounded and non-empty")

    def to_dict(self, *, include_owner_locator: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "workspace_id": self.workspace_id,
            "remote_workspace_generation": self.remote_workspace_generation,
            "state": self.state.value,
            "state_version": self.state_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if include_owner_locator:
            payload.update(
                {
                    "project_id": self.project_id,
                    "repository_binding_id": self.repository_binding_id,
                    "repository_binding_version": self.repository_binding_version,
                    "repository_id": self.repository_id,
                    "session_id": self.session_id,
                    "executor_agent_member_id": self.executor_agent_member_id,
                    "executor_agent_id": self.executor_agent_id,
                    "local_workspace_id": self.local_workspace_id,
                    "local_workspace_generation": self.local_workspace_generation,
                    "capability_lease_id": self.capability_lease_id,
                    "capability_lease_version": self.capability_lease_version,
                    "target_profile_id": self.target_profile_id,
                    "target_profile_digest": self.target_profile_digest,
                    "provision_intent_id": self.provision_intent_id,
                    "runner_handle": self.runner_handle,
                    "provision_receipt_id": self.provision_receipt_id,
                    "login_alias": self.login_alias,
                    "remote_workspace_path": self.remote_workspace_path,
                    "remote_root_digest": self.remote_root_digest,
                    "os_principal_identity_digest": (
                        self.os_principal_identity_digest
                    ),
                    "isolation_receipt_digest": self.isolation_receipt_digest,
                    "invalid_reason": self.invalid_reason,
                }
            )
        return payload


@dataclass(frozen=True, slots=True)
class ExecutorHpcWorkspaceProvisionIntent:
    intent_id: str
    workspace_id: str
    project_id: str
    session_id: str
    executor_agent_member_id: str
    local_workspace_generation: int
    remote_workspace_generation: int
    repository_binding_id: str
    repository_binding_version: int
    repository_id: str
    base_commit: str
    target_profile_id: str
    target_profile_digest: str
    root_policy_digest: str
    capability_lease_id: str
    capability_lease_version: int
    idempotency_key: str
    absolute_deadline: str
    created_at: str
    intent_digest: str
    schema_version: str = EXECUTOR_HPC_PROVISION_INTENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTOR_HPC_PROVISION_INTENT_SCHEMA_VERSION:
            raise ValueError("unsupported executor HPC provision intent schema")
        for name in (
            "intent_id",
            "workspace_id",
            "project_id",
            "session_id",
            "executor_agent_member_id",
            "repository_binding_id",
            "repository_id",
            "target_profile_id",
            "capability_lease_id",
            "idempotency_key",
        ):
            _require_identifier(getattr(self, name), name)
        _require_timestamp(self.absolute_deadline, "absolute_deadline")
        _require_timestamp(self.created_at, "created_at")
        for name in (
            "local_workspace_generation",
            "remote_workspace_generation",
            "repository_binding_version",
            "capability_lease_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", self.base_commit) is None:
            raise ValueError("base_commit must be a lowercase Git commit id")
        for name in (
            "target_profile_digest",
            "root_policy_digest",
            "intent_digest",
        ):
            _require_digest(getattr(self, name), name)
        if self.intent_digest != canonical_executor_hpc_digest(self.payload):
            raise ValueError("executor HPC provision intent digest mismatch")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "intent_id": self.intent_id,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "session_id": self.session_id,
            "executor_agent_member_id": self.executor_agent_member_id,
            "local_workspace_generation": self.local_workspace_generation,
            "remote_workspace_generation": self.remote_workspace_generation,
            "repository_binding_id": self.repository_binding_id,
            "repository_binding_version": self.repository_binding_version,
            "repository_id": self.repository_id,
            "base_commit": self.base_commit,
            "target_profile_id": self.target_profile_id,
            "target_profile_digest": self.target_profile_digest,
            "root_policy_digest": self.root_policy_digest,
            "capability_lease_id": self.capability_lease_id,
            "capability_lease_version": self.capability_lease_version,
            "idempotency_key": self.idempotency_key,
            "absolute_deadline": self.absolute_deadline,
            "created_at": self.created_at,
        }

    @classmethod
    def create(cls, **values: Any) -> ExecutorHpcWorkspaceProvisionIntent:
        payload = {
            "schema_version": EXECUTOR_HPC_PROVISION_INTENT_SCHEMA_VERSION,
            **values,
        }
        return cls(**values, intent_digest=canonical_executor_hpc_digest(payload))


@dataclass(frozen=True, slots=True)
class ExecutorHpcWorkspaceProvisionReceipt:
    receipt_id: str
    intent_id: str
    intent_digest: str
    workspace_id: str
    runner_handle: str
    target_profile_digest: str
    login_alias: str
    remote_workspace_path: str
    remote_root_digest: str
    repository_remote_digest: str
    clone_head_commit: str
    owner_identity_digest: str
    os_principal_identity_digest: str
    isolation_receipt_digest: str
    created_at: str
    receipt_digest: str
    schema_version: str = EXECUTOR_HPC_PROVISION_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTOR_HPC_PROVISION_RECEIPT_SCHEMA_VERSION:
            raise ValueError("unsupported executor HPC provision receipt schema")
        for name in (
            "receipt_id",
            "intent_id",
            "workspace_id",
            "runner_handle",
        ):
            _require_identifier(getattr(self, name), name)
        _require_timestamp(self.created_at, "created_at")
        for name in (
            "intent_digest",
            "target_profile_digest",
            "remote_root_digest",
            "repository_remote_digest",
            "owner_identity_digest",
            "os_principal_identity_digest",
            "isolation_receipt_digest",
            "receipt_digest",
        ):
            _require_digest(getattr(self, name), name)
        _require_remote_locator(self.login_alias, "login_alias")
        _require_remote_locator(self.remote_workspace_path, "remote_workspace_path")
        if (
            re.fullmatch(
                r"(?:[0-9a-f]{40}|[0-9a-f]{64})",
                self.clone_head_commit,
            )
            is None
        ):
            raise ValueError("clone_head_commit must be a lowercase Git commit id")
        if self.receipt_digest != canonical_executor_hpc_digest(self.payload):
            raise ValueError("executor HPC provision receipt digest mismatch")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "intent_id": self.intent_id,
            "intent_digest": self.intent_digest,
            "workspace_id": self.workspace_id,
            "runner_handle": self.runner_handle,
            "target_profile_digest": self.target_profile_digest,
            "login_alias": self.login_alias,
            "remote_workspace_path": self.remote_workspace_path,
            "remote_root_digest": self.remote_root_digest,
            "repository_remote_digest": self.repository_remote_digest,
            "clone_head_commit": self.clone_head_commit,
            "owner_identity_digest": self.owner_identity_digest,
            "os_principal_identity_digest": self.os_principal_identity_digest,
            "isolation_receipt_digest": self.isolation_receipt_digest,
            "created_at": self.created_at,
        }

    @classmethod
    def create(cls, **values: Any) -> ExecutorHpcWorkspaceProvisionReceipt:
        payload = {
            "schema_version": EXECUTOR_HPC_PROVISION_RECEIPT_SCHEMA_VERSION,
            **values,
        }
        return cls(**values, receipt_digest=canonical_executor_hpc_digest(payload))


@dataclass(frozen=True, slots=True)
class ExecutorHpcCredentialClaim:
    claim_id: str
    workspace_id: str
    session_id: str
    executor_agent_member_id: str
    local_workspace_generation: int
    remote_workspace_generation: int
    target_profile_id: str
    target_profile_digest: str
    capability_lease_id: str
    capability_lease_version: int
    credential_provider_id: str
    authenticator_id: str
    login_alias: str
    remote_workspace_path: str
    remote_root_digest: str
    os_principal_identity_digest: str
    operations: tuple[ExecutorHpcCredentialOperation, ...]
    issued_at: str
    expires_at: str
    revoked_at: str | None = None
    schema_version: str = EXECUTOR_HPC_CREDENTIAL_CLAIM_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTOR_HPC_CREDENTIAL_CLAIM_SCHEMA_VERSION:
            raise ValueError("unsupported executor HPC credential claim schema")
        for name in (
            "claim_id",
            "workspace_id",
            "session_id",
            "executor_agent_member_id",
            "target_profile_id",
            "capability_lease_id",
            "credential_provider_id",
            "authenticator_id",
        ):
            _require_identifier(getattr(self, name), name)
        _require_timestamp(self.issued_at, "issued_at")
        _require_timestamp(self.expires_at, "expires_at")
        _require_remote_locator(self.login_alias, "login_alias")
        _require_remote_locator(
            self.remote_workspace_path,
            "remote_workspace_path",
        )
        _require_digest(self.target_profile_digest, "target_profile_digest")
        _require_digest(self.remote_root_digest, "remote_root_digest")
        _require_digest(
            self.os_principal_identity_digest,
            "os_principal_identity_digest",
        )
        if not self.operations or len(set(self.operations)) != len(self.operations):
            raise ValueError("credential operations must be a non-empty unique set")
        if any(
            not isinstance(item, ExecutorHpcCredentialOperation)
            for item in self.operations
        ):
            raise TypeError("credential operation is not closed")
        for name in (
            "local_workspace_generation",
            "remote_workspace_generation",
            "capability_lease_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.revoked_at is not None:
            _require_timestamp(self.revoked_at, "revoked_at")
        issued = datetime.fromisoformat(self.issued_at)
        expires = datetime.fromisoformat(self.expires_at)
        if expires <= issued:
            raise ValueError("credential expires_at must follow issued_at")
        if self.revoked_at is not None and datetime.fromisoformat(
            self.revoked_at
        ) < issued:
            raise ValueError("credential revoked_at cannot precede issued_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "claim_id": self.claim_id,
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "executor_agent_member_id": self.executor_agent_member_id,
            "local_workspace_generation": self.local_workspace_generation,
            "remote_workspace_generation": self.remote_workspace_generation,
            "target_profile_id": self.target_profile_id,
            "target_profile_digest": self.target_profile_digest,
            "capability_lease_id": self.capability_lease_id,
            "capability_lease_version": self.capability_lease_version,
            "credential_provider_id": self.credential_provider_id,
            "authenticator_id": self.authenticator_id,
            "login_alias": self.login_alias,
            "remote_workspace_path": self.remote_workspace_path,
            "remote_root_digest": self.remote_root_digest,
            "os_principal_identity_digest": self.os_principal_identity_digest,
            "operations": [item.value for item in self.operations],
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "revoked_at": self.revoked_at,
        }


@dataclass(frozen=True, slots=True)
class ExecutorHpcTargetQualification:
    target_profile_id: str
    target_profile_digest: str
    root_policy_digest: str
    os_principal_policy_id: str
    credential_provider_id: str
    authenticator_id: str
    login_alias: str
    workspace_root: str
    sidecar_root_digest: str
    inventory_generation: int
    inventory_digest: str
    native_positive_proof_digest: str
    native_negative_proof_digest: str
    activated: bool
    qualified_at: str
    schema_version: str = EXECUTOR_HPC_TARGET_QUALIFICATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTOR_HPC_TARGET_QUALIFICATION_SCHEMA_VERSION:
            raise ValueError("unsupported executor HPC target qualification schema")
        for name in (
            "target_profile_id",
            "os_principal_policy_id",
            "credential_provider_id",
            "authenticator_id",
        ):
            _require_identifier(getattr(self, name), name)
        for name in (
            "target_profile_digest",
            "root_policy_digest",
            "sidecar_root_digest",
            "inventory_digest",
            "native_positive_proof_digest",
            "native_negative_proof_digest",
        ):
            _require_digest(getattr(self, name), name)
        _require_remote_locator(self.login_alias, "login_alias")
        _require_remote_locator(self.workspace_root, "workspace_root")
        _require_timestamp(self.qualified_at, "qualified_at")
        if (
            not isinstance(self.inventory_generation, int)
            or isinstance(self.inventory_generation, bool)
            or self.inventory_generation < 1
        ):
            raise ValueError("inventory_generation must be a positive integer")
        if not isinstance(self.activated, bool):
            raise TypeError("activated must be boolean")
        if not self.activated:
            raise ValueError(
                "only native-proof-qualified executor HPC targets may be persisted"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "target_profile_id": self.target_profile_id,
            "target_profile_digest": self.target_profile_digest,
            "root_policy_digest": self.root_policy_digest,
            "os_principal_policy_id": self.os_principal_policy_id,
            "credential_provider_id": self.credential_provider_id,
            "authenticator_id": self.authenticator_id,
            "login_alias": self.login_alias,
            "workspace_root": self.workspace_root,
            "sidecar_root_digest": self.sidecar_root_digest,
            "inventory_generation": self.inventory_generation,
            "inventory_digest": self.inventory_digest,
            "native_positive_proof_digest": self.native_positive_proof_digest,
            "native_negative_proof_digest": self.native_negative_proof_digest,
            "activated": self.activated,
            "qualified_at": self.qualified_at,
        }


@dataclass(frozen=True, slots=True)
class ExecutorHpcWorkspaceCleanupIntent:
    cleanup_intent_id: str
    workspace_id: str
    workspace_state_version: int
    runner_handle: str
    remote_root_digest: str
    settlement_proof_digest: str
    idempotency_key: str
    created_at: str
    intent_digest: str
    schema_version: str = EXECUTOR_HPC_CLEANUP_INTENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTOR_HPC_CLEANUP_INTENT_SCHEMA_VERSION:
            raise ValueError("unsupported executor HPC cleanup intent schema")
        for name in (
            "cleanup_intent_id",
            "workspace_id",
            "runner_handle",
            "idempotency_key",
        ):
            _require_identifier(getattr(self, name), name)
        if (
            not isinstance(self.workspace_state_version, int)
            or isinstance(self.workspace_state_version, bool)
            or self.workspace_state_version < 1
        ):
            raise ValueError("workspace_state_version must be positive")
        for name in (
            "remote_root_digest",
            "settlement_proof_digest",
            "intent_digest",
        ):
            _require_digest(getattr(self, name), name)
        _require_timestamp(self.created_at, "created_at")
        if self.intent_digest != canonical_executor_hpc_digest(self.payload):
            raise ValueError("executor HPC cleanup intent digest mismatch")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "cleanup_intent_id": self.cleanup_intent_id,
            "workspace_id": self.workspace_id,
            "workspace_state_version": self.workspace_state_version,
            "runner_handle": self.runner_handle,
            "remote_root_digest": self.remote_root_digest,
            "settlement_proof_digest": self.settlement_proof_digest,
            "idempotency_key": self.idempotency_key,
            "created_at": self.created_at,
        }

    @classmethod
    def create(cls, **values: Any) -> "ExecutorHpcWorkspaceCleanupIntent":
        payload = {
            "schema_version": EXECUTOR_HPC_CLEANUP_INTENT_SCHEMA_VERSION,
            **values,
        }
        return cls(**values, intent_digest=canonical_executor_hpc_digest(payload))


@dataclass(frozen=True, slots=True)
class ExecutorHpcWorkspaceCleanupReceipt:
    cleanup_receipt_id: str
    cleanup_intent_id: str
    cleanup_intent_digest: str
    workspace_id: str
    runner_handle: str
    remote_root_digest: str
    disposition: ExecutorHpcCleanupDisposition
    unsettled_effect_count: int
    settlement_proof_digest: str
    isolation_cleanup_receipt_digest: str
    created_at: str
    receipt_digest: str
    schema_version: str = EXECUTOR_HPC_CLEANUP_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTOR_HPC_CLEANUP_RECEIPT_SCHEMA_VERSION:
            raise ValueError("unsupported executor HPC cleanup receipt schema")
        for name in (
            "cleanup_receipt_id",
            "cleanup_intent_id",
            "workspace_id",
            "runner_handle",
        ):
            _require_identifier(getattr(self, name), name)
        _require_digest(self.cleanup_intent_digest, "cleanup_intent_digest")
        _require_digest(self.remote_root_digest, "remote_root_digest")
        _require_digest(self.settlement_proof_digest, "settlement_proof_digest")
        _require_digest(
            self.isolation_cleanup_receipt_digest,
            "isolation_cleanup_receipt_digest",
        )
        _require_digest(self.receipt_digest, "receipt_digest")
        _require_timestamp(self.created_at, "created_at")
        if not isinstance(self.disposition, ExecutorHpcCleanupDisposition):
            raise TypeError("disposition must be an ExecutorHpcCleanupDisposition")
        if (
            not isinstance(self.unsettled_effect_count, int)
            or isinstance(self.unsettled_effect_count, bool)
            or self.unsettled_effect_count < 0
        ):
            raise ValueError("unsettled_effect_count must be a non-negative integer")
        if self.receipt_digest != canonical_executor_hpc_digest(self.payload):
            raise ValueError("executor HPC cleanup receipt digest mismatch")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "cleanup_receipt_id": self.cleanup_receipt_id,
            "cleanup_intent_id": self.cleanup_intent_id,
            "cleanup_intent_digest": self.cleanup_intent_digest,
            "workspace_id": self.workspace_id,
            "runner_handle": self.runner_handle,
            "remote_root_digest": self.remote_root_digest,
            "disposition": self.disposition.value,
            "unsettled_effect_count": self.unsettled_effect_count,
            "settlement_proof_digest": self.settlement_proof_digest,
            "isolation_cleanup_receipt_digest": (
                self.isolation_cleanup_receipt_digest
            ),
            "created_at": self.created_at,
        }

    @classmethod
    def create(cls, **values: Any) -> ExecutorHpcWorkspaceCleanupReceipt:
        payload = {
            "schema_version": EXECUTOR_HPC_CLEANUP_RECEIPT_SCHEMA_VERSION,
            **{
                key: value.value if isinstance(value, StrEnum) else value
                for key, value in values.items()
            },
        }
        return cls(**values, receipt_digest=canonical_executor_hpc_digest(payload))


__all__ = [
    "EXECUTOR_HPC_CLEANUP_INTENT_SCHEMA_VERSION",
    "EXECUTOR_HPC_CLEANUP_RECEIPT_SCHEMA_VERSION",
    "EXECUTOR_HPC_CREDENTIAL_CLAIM_SCHEMA_VERSION",
    "EXECUTOR_HPC_PROVISION_INTENT_SCHEMA_VERSION",
    "EXECUTOR_HPC_PROVISION_RECEIPT_SCHEMA_VERSION",
    "EXECUTOR_HPC_TARGET_QUALIFICATION_SCHEMA_VERSION",
    "EXECUTOR_HPC_WORKSPACE_SCHEMA_VERSION",
    "ExecutorHpcCredentialClaim",
    "ExecutorHpcCredentialOperation",
    "ExecutorHpcCleanupDisposition",
    "ExecutorHpcTargetQualification",
    "ExecutorHpcWorkspace",
    "ExecutorHpcWorkspaceCleanupIntent",
    "ExecutorHpcWorkspaceCleanupReceipt",
    "ExecutorHpcWorkspaceProvisionIntent",
    "ExecutorHpcWorkspaceProvisionReceipt",
    "ExecutorHpcWorkspaceState",
    "canonical_executor_hpc_digest",
]
