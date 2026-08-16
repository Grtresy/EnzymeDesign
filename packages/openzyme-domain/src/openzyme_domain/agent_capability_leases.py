from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any


AGENT_CAPABILITY_LEASE_SCHEMA_VERSION = "agent_capability_lease@1"
AGENT_CAPABILITY_LEASE_EVENT_SCHEMA_VERSION = "agent_capability_lease_event@1"
AGENT_RETIREMENT_CLEANUP_PROOF_SCHEMA_VERSION = (
    "agent_retirement_cleanup_proof@1"
)
AGENT_RETIREMENT_RECORD_SCHEMA_VERSION = "agent_retirement_record@1"
AGENT_RETIREMENT_REQUEST_SCHEMA_VERSION = "agent_retirement_request@1"
AGENT_WORKSPACE_GENERATION_RESERVATION_SCHEMA_VERSION = (
    "agent_workspace_generation_reservation@1"
)


class AgentCapability(StrEnum):
    FILESYSTEM_READ = "filesystem_read"
    FILESYSTEM_WRITE = "filesystem_write"
    SHELL_PROCESS = "shell_process"
    GIT = "git"
    GIT_LFS = "git_lfs"
    ORDINARY_NETWORK = "ordinary_network"
    UPLOAD = "upload"
    DOWNLOAD = "download"
    SSH = "ssh"
    RSYNC_SCP = "rsync_scp"
    HPC_LOGIN_WORKSPACE_CRUD = "hpc_login_workspace_crud"
    SLURM_OPERATIONS = "slurm_operations"


class AgentCapabilityProfile(StrEnum):
    GENERAL = "general"
    EXECUTOR = "executor"


class AgentCapabilityLeaseStatus(StrEnum):
    PENDING_WORKSPACE = "pending_workspace"
    ACTIVE = "active"
    REVOKED = "revoked"


class AgentCapabilityRevocationScope(StrEnum):
    EXACT = "exact"
    SESSION = "session"
    POLICY = "policy"
    AGENT = "agent"
    WORKSPACE_GENERATION = "workspace_generation"
    DERIVED_SUBTREE = "derived_subtree"


class AgentCapabilityRevocationReason(StrEnum):
    EXPLICIT = "explicit"
    SESSION_ENDED = "session_ended"
    POLICY_INVALIDATED = "policy_invalidated"
    AGENT_RETIRED = "agent_retired"
    WORKSPACE_REPLACED = "workspace_replaced"
    OPERATOR_SUBTREE = "operator_subtree"


class AgentCapabilityLeaseEventKind(StrEnum):
    ISSUED = "issued"
    ACTIVATED = "activated"
    REVOKED = "revoked"


class AgentWorkspaceGenerationStatus(StrEnum):
    RESERVED = "reserved"
    READY = "ready"
    REPLACED = "replaced"


class AgentWorkspaceReadinessOwnerKind(StrEnum):
    WORKSPACE_PROVISIONER = "workspace_provisioner"


class AgentRetirementReason(StrEnum):
    SHUTDOWN_COMPLETED = "shutdown_completed"
    OPERATOR_SHUTDOWN_COMPLETED = "operator_shutdown_completed"
    SESSION_SHUTDOWN_COMPLETED = "session_shutdown_completed"


GENERAL_AGENT_CAPABILITIES: tuple[AgentCapability, ...] = (
    AgentCapability.FILESYSTEM_READ,
    AgentCapability.FILESYSTEM_WRITE,
    AgentCapability.SHELL_PROCESS,
    AgentCapability.GIT,
    AgentCapability.GIT_LFS,
    AgentCapability.ORDINARY_NETWORK,
    AgentCapability.UPLOAD,
    AgentCapability.DOWNLOAD,
)

EXECUTOR_AGENT_CAPABILITIES: tuple[AgentCapability, ...] = (
    *GENERAL_AGENT_CAPABILITIES,
    AgentCapability.SSH,
    AgentCapability.RSYNC_SCP,
    AgentCapability.HPC_LOGIN_WORKSPACE_CRUD,
    AgentCapability.SLURM_OPERATIONS,
)


def capabilities_for_profile(
    profile: AgentCapabilityProfile,
) -> tuple[AgentCapability, ...]:
    if profile is AgentCapabilityProfile.GENERAL:
        return GENERAL_AGENT_CAPABILITIES
    if profile is AgentCapabilityProfile.EXECUTOR:
        return EXECUTOR_AGENT_CAPABILITIES
    raise TypeError("profile must be an AgentCapabilityProfile")


def canonical_capability_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def capability_set_digest(capabilities: tuple[AgentCapability, ...]) -> str:
    return canonical_capability_digest(
        {"capabilities": [capability.value for capability in capabilities]}
    )


def target_scope_digest(target_ids: tuple[str, ...]) -> str:
    return canonical_capability_digest({"target_ids": list(target_ids)})


def _require_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if (
        not value
        or value != value.strip()
        or any(character.isspace() for character in value)
    ):
        raise ValueError(
            f"{field_name} must be a non-empty identifier without whitespace"
        )


def _require_digest(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if len(value) != 71 or not value.startswith("sha256:"):
        raise ValueError(f"{field_name} must be a sha256 digest")
    suffix = value.removeprefix("sha256:")
    if any(character not in "0123456789abcdef" for character in suffix):
        raise ValueError(f"{field_name} must use lowercase hexadecimal")


def _require_positive_integer(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _require_target_ids(target_ids: tuple[str, ...]) -> None:
    if not isinstance(target_ids, tuple) or not target_ids:
        raise ValueError("target_ids must be a non-empty canonical tuple")
    for target_id in target_ids:
        _require_identifier(target_id, "target_id")
    if target_ids != tuple(sorted(set(target_ids))):
        raise ValueError("target_ids must be unique and sorted")


def _enum_value(value: StrEnum | None) -> str | None:
    return None if value is None else value.value


@dataclass(frozen=True, slots=True)
class AgentWorkspaceGenerationReservation:
    reservation_id: str
    session_id: str
    agent_member_id: str
    agent_id: str
    workspace_generation: int
    status: AgentWorkspaceGenerationStatus
    state_version: int
    reserved_at: str
    updated_at: str
    immutable_fingerprint: str
    canonical_digest: str
    readiness_owner_kind: AgentWorkspaceReadinessOwnerKind | None = None
    readiness_owner_ref: str | None = None
    readiness_ref: str | None = None
    readiness_digest: str | None = None
    ready_at: str | None = None
    replaced_by_generation: int | None = None
    replaced_at: str | None = None
    schema_version: str = AGENT_WORKSPACE_GENERATION_RESERVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_WORKSPACE_GENERATION_RESERVATION_SCHEMA_VERSION:
            raise ValueError(
                "unsupported workspace generation reservation schema_version"
            )
        for field_name in (
            "reservation_id",
            "session_id",
            "agent_member_id",
            "agent_id",
            "reserved_at",
            "updated_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_positive_integer(self.workspace_generation, "workspace_generation")
        _require_positive_integer(self.state_version, "state_version")
        if not isinstance(self.status, AgentWorkspaceGenerationStatus):
            raise TypeError("status must be an AgentWorkspaceGenerationStatus")
        readiness_values = (
            self.readiness_owner_kind,
            self.readiness_owner_ref,
            self.readiness_ref,
            self.readiness_digest,
            self.ready_at,
        )
        readiness_absent = all(value is None for value in readiness_values)
        readiness_complete = all(value is not None for value in readiness_values)
        replacement_values = (self.replaced_by_generation, self.replaced_at)
        replacement_absent = all(value is None for value in replacement_values)
        replacement_complete = all(value is not None for value in replacement_values)
        if self.status is AgentWorkspaceGenerationStatus.RESERVED:
            if self.state_version != 1:
                raise ValueError("reserved generation must use state_version 1")
            if not readiness_absent or not replacement_absent:
                raise ValueError(
                    "reserved generation cannot contain readiness or replacement facts"
                )
        elif self.status is AgentWorkspaceGenerationStatus.READY:
            if self.state_version != 2:
                raise ValueError("ready generation must use state_version 2")
            if not readiness_complete or not replacement_absent:
                raise ValueError(
                    "ready generation requires complete readiness facts only"
                )
        else:
            expected_state_version = 2 if readiness_absent else 3
            if self.state_version != expected_state_version:
                raise ValueError(
                    "replaced generation state_version must match its readiness history"
                )
            if not replacement_complete or not (readiness_absent or readiness_complete):
                raise ValueError(
                    "replaced generation requires one complete replacement fact"
                )
        if readiness_complete:
            if not isinstance(
                self.readiness_owner_kind,
                AgentWorkspaceReadinessOwnerKind,
            ):
                raise TypeError(
                    "readiness_owner_kind must be an AgentWorkspaceReadinessOwnerKind"
                )
            assert self.readiness_owner_ref is not None
            assert self.readiness_ref is not None
            assert self.readiness_digest is not None
            assert self.ready_at is not None
            _require_identifier(self.readiness_owner_ref, "readiness_owner_ref")
            _require_identifier(self.readiness_ref, "readiness_ref")
            _require_digest(self.readiness_digest, "readiness_digest")
            _require_identifier(self.ready_at, "ready_at")
        if replacement_complete:
            assert self.replaced_by_generation is not None
            assert self.replaced_at is not None
            _require_positive_integer(
                self.replaced_by_generation,
                "replaced_by_generation",
            )
            if self.replaced_by_generation <= self.workspace_generation:
                raise ValueError("replacement generation must strictly increase")
            _require_identifier(self.replaced_at, "replaced_at")
        _require_digest(self.immutable_fingerprint, "immutable_fingerprint")
        _require_digest(self.canonical_digest, "canonical_digest")
        expected_fingerprint = canonical_capability_digest(self.immutable_payload())
        if self.immutable_fingerprint != expected_fingerprint:
            raise ValueError(
                "immutable_fingerprint does not match reservation identity"
            )
        expected_digest = canonical_capability_digest(self.canonical_payload())
        if self.canonical_digest != expected_digest:
            raise ValueError("canonical_digest does not match reservation payload")

    @classmethod
    def create(
        cls,
        *,
        reservation_id: str,
        session_id: str,
        agent_member_id: str,
        agent_id: str,
        workspace_generation: int,
        status: AgentWorkspaceGenerationStatus,
        state_version: int,
        reserved_at: str,
        updated_at: str,
        readiness_owner_kind: AgentWorkspaceReadinessOwnerKind | None = None,
        readiness_owner_ref: str | None = None,
        readiness_ref: str | None = None,
        readiness_digest: str | None = None,
        ready_at: str | None = None,
        replaced_by_generation: int | None = None,
        replaced_at: str | None = None,
    ) -> AgentWorkspaceGenerationReservation:
        immutable_payload = {
            "schema_version": AGENT_WORKSPACE_GENERATION_RESERVATION_SCHEMA_VERSION,
            "reservation_id": reservation_id,
            "session_id": session_id,
            "agent_member_id": agent_member_id,
            "agent_id": agent_id,
            "workspace_generation": workspace_generation,
            "reserved_at": reserved_at,
        }
        immutable_fingerprint = canonical_capability_digest(immutable_payload)
        canonical_payload = {
            **immutable_payload,
            "status": status.value,
            "state_version": state_version,
            "updated_at": updated_at,
            "readiness_owner_kind": _enum_value(readiness_owner_kind),
            "readiness_owner_ref": readiness_owner_ref,
            "readiness_ref": readiness_ref,
            "readiness_digest": readiness_digest,
            "ready_at": ready_at,
            "replaced_by_generation": replaced_by_generation,
            "replaced_at": replaced_at,
            "immutable_fingerprint": immutable_fingerprint,
        }
        return cls(
            reservation_id=reservation_id,
            session_id=session_id,
            agent_member_id=agent_member_id,
            agent_id=agent_id,
            workspace_generation=workspace_generation,
            status=status,
            state_version=state_version,
            reserved_at=reserved_at,
            updated_at=updated_at,
            immutable_fingerprint=immutable_fingerprint,
            canonical_digest=canonical_capability_digest(canonical_payload),
            readiness_owner_kind=readiness_owner_kind,
            readiness_owner_ref=readiness_owner_ref,
            readiness_ref=readiness_ref,
            readiness_digest=readiness_digest,
            ready_at=ready_at,
            replaced_by_generation=replaced_by_generation,
            replaced_at=replaced_at,
        )

    def immutable_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "reservation_id": self.reservation_id,
            "session_id": self.session_id,
            "agent_member_id": self.agent_member_id,
            "agent_id": self.agent_id,
            "workspace_generation": self.workspace_generation,
            "reserved_at": self.reserved_at,
        }

    def canonical_payload(self) -> dict[str, Any]:
        return {
            **self.immutable_payload(),
            "status": self.status.value,
            "state_version": self.state_version,
            "updated_at": self.updated_at,
            "readiness_owner_kind": _enum_value(self.readiness_owner_kind),
            "readiness_owner_ref": self.readiness_owner_ref,
            "readiness_ref": self.readiness_ref,
            "readiness_digest": self.readiness_digest,
            "ready_at": self.ready_at,
            "replaced_by_generation": self.replaced_by_generation,
            "replaced_at": self.replaced_at,
            "immutable_fingerprint": self.immutable_fingerprint,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_payload(), "canonical_digest": self.canonical_digest}


@dataclass(frozen=True, slots=True)
class AgentCapabilityLease:
    lease_id: str
    session_id: str
    agent_member_id: str
    agent_id: str
    workspace_generation: int
    profile: AgentCapabilityProfile
    capabilities: tuple[AgentCapability, ...]
    capability_set_digest: str
    target_ids: tuple[str, ...]
    target_scope_digest: str
    policy_version: str
    policy_digest: str
    parent_lease_id: str | None
    idempotency_key: str
    status: AgentCapabilityLeaseStatus
    state_version: int
    issued_at: str
    updated_at: str
    immutable_fingerprint: str
    canonical_digest: str
    activated_at: str | None = None
    revoked_at: str | None = None
    revocation_scope: AgentCapabilityRevocationScope | None = None
    revocation_reason: AgentCapabilityRevocationReason | None = None
    schema_version: str = AGENT_CAPABILITY_LEASE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_CAPABILITY_LEASE_SCHEMA_VERSION:
            raise ValueError("unsupported agent capability lease schema_version")
        for field_name in (
            "lease_id",
            "session_id",
            "agent_member_id",
            "agent_id",
            "policy_version",
            "idempotency_key",
            "issued_at",
            "updated_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        if self.parent_lease_id is not None:
            _require_identifier(self.parent_lease_id, "parent_lease_id")
            if self.parent_lease_id == self.lease_id:
                raise ValueError("a lease cannot derive from itself")
        _require_positive_integer(self.workspace_generation, "workspace_generation")
        _require_positive_integer(self.state_version, "state_version")
        if not isinstance(self.profile, AgentCapabilityProfile):
            raise TypeError("profile must be an AgentCapabilityProfile")
        if not isinstance(self.capabilities, tuple) or not all(
            isinstance(capability, AgentCapability) for capability in self.capabilities
        ):
            raise TypeError("capabilities must be a tuple of AgentCapability values")
        if self.capabilities != capabilities_for_profile(self.profile):
            raise ValueError(
                "capabilities must equal the closed profile capability set"
            )
        expected_capability_digest = capability_set_digest(self.capabilities)
        if self.capability_set_digest != expected_capability_digest:
            raise ValueError("capability_set_digest does not match capabilities")
        _require_target_ids(self.target_ids)
        expected_target_digest = target_scope_digest(self.target_ids)
        if self.target_scope_digest != expected_target_digest:
            raise ValueError("target_scope_digest does not match target_ids")
        _require_digest(self.policy_digest, "policy_digest")
        if not isinstance(self.status, AgentCapabilityLeaseStatus):
            raise TypeError("status must be an AgentCapabilityLeaseStatus")
        if self.status is AgentCapabilityLeaseStatus.PENDING_WORKSPACE:
            if self.state_version != 1:
                raise ValueError("pending lease must use state_version 1")
            if any(
                value is not None
                for value in (
                    self.activated_at,
                    self.revoked_at,
                    self.revocation_scope,
                    self.revocation_reason,
                )
            ):
                raise ValueError(
                    "pending lease cannot contain activation or revocation facts"
                )
        elif self.status is AgentCapabilityLeaseStatus.ACTIVE:
            if self.state_version != 2:
                raise ValueError("active lease must use state_version 2")
            if self.activated_at is None or any(
                value is not None
                for value in (
                    self.revoked_at,
                    self.revocation_scope,
                    self.revocation_reason,
                )
            ):
                raise ValueError("active lease requires only an activation fact")
            _require_identifier(self.activated_at, "activated_at")
        else:
            if (
                self.revoked_at is None
                or self.revocation_scope is None
                or self.revocation_reason is None
            ):
                raise ValueError("revoked lease requires complete revocation facts")
            _require_identifier(self.revoked_at, "revoked_at")
            if self.activated_at is not None:
                _require_identifier(self.activated_at, "activated_at")
            expected_state_version = 2 if self.activated_at is None else 3
            if self.state_version != expected_state_version:
                raise ValueError(
                    "revoked lease state_version must match its activation history"
                )
            if not isinstance(
                self.revocation_scope,
                AgentCapabilityRevocationScope,
            ):
                raise TypeError(
                    "revocation_scope must be an AgentCapabilityRevocationScope"
                )
            if not isinstance(
                self.revocation_reason,
                AgentCapabilityRevocationReason,
            ):
                raise TypeError(
                    "revocation_reason must be an AgentCapabilityRevocationReason"
                )
        _require_digest(self.immutable_fingerprint, "immutable_fingerprint")
        _require_digest(self.canonical_digest, "canonical_digest")
        if self.immutable_fingerprint != canonical_capability_digest(
            self.immutable_payload()
        ):
            raise ValueError("immutable_fingerprint does not match lease identity")
        if self.canonical_digest != canonical_capability_digest(
            self.canonical_payload()
        ):
            raise ValueError("canonical_digest does not match lease payload")

    @classmethod
    def create(
        cls,
        *,
        lease_id: str,
        session_id: str,
        agent_member_id: str,
        agent_id: str,
        workspace_generation: int,
        profile: AgentCapabilityProfile,
        capabilities: tuple[AgentCapability, ...],
        target_ids: tuple[str, ...],
        policy_version: str,
        policy_digest: str,
        parent_lease_id: str | None,
        idempotency_key: str,
        status: AgentCapabilityLeaseStatus,
        state_version: int,
        issued_at: str,
        updated_at: str,
        activated_at: str | None = None,
        revoked_at: str | None = None,
        revocation_scope: AgentCapabilityRevocationScope | None = None,
        revocation_reason: AgentCapabilityRevocationReason | None = None,
    ) -> AgentCapabilityLease:
        capabilities_digest = capability_set_digest(capabilities)
        targets_digest = target_scope_digest(target_ids)
        immutable_payload = {
            "schema_version": AGENT_CAPABILITY_LEASE_SCHEMA_VERSION,
            "lease_id": lease_id,
            "session_id": session_id,
            "agent_member_id": agent_member_id,
            "agent_id": agent_id,
            "workspace_generation": workspace_generation,
            "profile": profile.value,
            "capabilities": [capability.value for capability in capabilities],
            "capability_set_digest": capabilities_digest,
            "target_ids": list(target_ids),
            "target_scope_digest": targets_digest,
            "policy_version": policy_version,
            "policy_digest": policy_digest,
            "parent_lease_id": parent_lease_id,
            "idempotency_key": idempotency_key,
            "issued_at": issued_at,
        }
        immutable_fingerprint = canonical_capability_digest(immutable_payload)
        canonical_payload = {
            **immutable_payload,
            "status": status.value,
            "state_version": state_version,
            "updated_at": updated_at,
            "activated_at": activated_at,
            "revoked_at": revoked_at,
            "revocation_scope": _enum_value(revocation_scope),
            "revocation_reason": _enum_value(revocation_reason),
            "immutable_fingerprint": immutable_fingerprint,
        }
        return cls(
            lease_id=lease_id,
            session_id=session_id,
            agent_member_id=agent_member_id,
            agent_id=agent_id,
            workspace_generation=workspace_generation,
            profile=profile,
            capabilities=capabilities,
            capability_set_digest=capabilities_digest,
            target_ids=target_ids,
            target_scope_digest=targets_digest,
            policy_version=policy_version,
            policy_digest=policy_digest,
            parent_lease_id=parent_lease_id,
            idempotency_key=idempotency_key,
            status=status,
            state_version=state_version,
            issued_at=issued_at,
            updated_at=updated_at,
            immutable_fingerprint=immutable_fingerprint,
            canonical_digest=canonical_capability_digest(canonical_payload),
            activated_at=activated_at,
            revoked_at=revoked_at,
            revocation_scope=revocation_scope,
            revocation_reason=revocation_reason,
        )

    def immutable_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "lease_id": self.lease_id,
            "session_id": self.session_id,
            "agent_member_id": self.agent_member_id,
            "agent_id": self.agent_id,
            "workspace_generation": self.workspace_generation,
            "profile": self.profile.value,
            "capabilities": [capability.value for capability in self.capabilities],
            "capability_set_digest": self.capability_set_digest,
            "target_ids": list(self.target_ids),
            "target_scope_digest": self.target_scope_digest,
            "policy_version": self.policy_version,
            "policy_digest": self.policy_digest,
            "parent_lease_id": self.parent_lease_id,
            "idempotency_key": self.idempotency_key,
            "issued_at": self.issued_at,
        }

    def canonical_payload(self) -> dict[str, Any]:
        return {
            **self.immutable_payload(),
            "status": self.status.value,
            "state_version": self.state_version,
            "updated_at": self.updated_at,
            "activated_at": self.activated_at,
            "revoked_at": self.revoked_at,
            "revocation_scope": _enum_value(self.revocation_scope),
            "revocation_reason": _enum_value(self.revocation_reason),
            "immutable_fingerprint": self.immutable_fingerprint,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_payload(), "canonical_digest": self.canonical_digest}


@dataclass(frozen=True, slots=True)
class AgentCapabilityLeaseLifecycleEvent:
    event_id: str
    lease_id: str
    session_id: str
    agent_member_id: str
    agent_id: str
    workspace_generation: int
    event_kind: AgentCapabilityLeaseEventKind
    previous_status: AgentCapabilityLeaseStatus | None
    status: AgentCapabilityLeaseStatus
    state_version: int
    actor_ref: str
    occurred_at: str
    event_digest: str
    revocation_scope: AgentCapabilityRevocationScope | None = None
    revocation_reason: AgentCapabilityRevocationReason | None = None
    schema_version: str = AGENT_CAPABILITY_LEASE_EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_CAPABILITY_LEASE_EVENT_SCHEMA_VERSION:
            raise ValueError("unsupported agent capability lease event schema_version")
        for field_name in (
            "event_id",
            "lease_id",
            "session_id",
            "agent_member_id",
            "agent_id",
            "actor_ref",
            "occurred_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_positive_integer(self.workspace_generation, "workspace_generation")
        _require_positive_integer(self.state_version, "state_version")
        if not isinstance(self.event_kind, AgentCapabilityLeaseEventKind):
            raise TypeError("event_kind must be an AgentCapabilityLeaseEventKind")
        if self.previous_status is not None and not isinstance(
            self.previous_status,
            AgentCapabilityLeaseStatus,
        ):
            raise TypeError("previous_status must be an AgentCapabilityLeaseStatus")
        if not isinstance(self.status, AgentCapabilityLeaseStatus):
            raise TypeError("status must be an AgentCapabilityLeaseStatus")
        if self.event_kind is AgentCapabilityLeaseEventKind.ISSUED:
            if (
                self.previous_status is not None
                or self.status is not AgentCapabilityLeaseStatus.PENDING_WORKSPACE
                or self.state_version != 1
            ):
                raise ValueError(
                    "issued event must create pending_workspace state version 1"
                )
        elif self.event_kind is AgentCapabilityLeaseEventKind.ACTIVATED:
            if (
                self.previous_status is not AgentCapabilityLeaseStatus.PENDING_WORKSPACE
                or self.status is not AgentCapabilityLeaseStatus.ACTIVE
                or self.state_version != 2
            ):
                raise ValueError(
                    "activated event must transition pending_workspace to active "
                    "state version 2"
                )
        else:
            expected_state_version = (
                2
                if self.previous_status
                is AgentCapabilityLeaseStatus.PENDING_WORKSPACE
                else 3
            )
            if (
                self.previous_status
                not in {
                    AgentCapabilityLeaseStatus.PENDING_WORKSPACE,
                    AgentCapabilityLeaseStatus.ACTIVE,
                }
                or self.status is not AgentCapabilityLeaseStatus.REVOKED
                or self.state_version != expected_state_version
            ):
                raise ValueError(
                    "revoked event must advance its exact live lease state version"
                )
        if self.event_kind is AgentCapabilityLeaseEventKind.REVOKED:
            if self.revocation_scope is None or self.revocation_reason is None:
                raise ValueError("revoked event requires scope and reason")
            if not isinstance(
                self.revocation_scope,
                AgentCapabilityRevocationScope,
            ) or not isinstance(
                self.revocation_reason,
                AgentCapabilityRevocationReason,
            ):
                raise TypeError("revoked event scope and reason must use closed enums")
        elif self.revocation_scope is not None or self.revocation_reason is not None:
            raise ValueError("non-revocation event cannot contain revocation facts")
        _require_digest(self.event_digest, "event_digest")
        if self.event_digest != canonical_capability_digest(self.canonical_payload()):
            raise ValueError("event_digest does not match lifecycle event payload")

    @classmethod
    def create(
        cls,
        *,
        event_id: str,
        lease_id: str,
        session_id: str,
        agent_member_id: str,
        agent_id: str,
        workspace_generation: int,
        event_kind: AgentCapabilityLeaseEventKind,
        previous_status: AgentCapabilityLeaseStatus | None,
        status: AgentCapabilityLeaseStatus,
        state_version: int,
        actor_ref: str,
        occurred_at: str,
        revocation_scope: AgentCapabilityRevocationScope | None = None,
        revocation_reason: AgentCapabilityRevocationReason | None = None,
    ) -> AgentCapabilityLeaseLifecycleEvent:
        payload = {
            "schema_version": AGENT_CAPABILITY_LEASE_EVENT_SCHEMA_VERSION,
            "event_id": event_id,
            "lease_id": lease_id,
            "session_id": session_id,
            "agent_member_id": agent_member_id,
            "agent_id": agent_id,
            "workspace_generation": workspace_generation,
            "event_kind": event_kind.value,
            "previous_status": _enum_value(previous_status),
            "status": status.value,
            "state_version": state_version,
            "actor_ref": actor_ref,
            "occurred_at": occurred_at,
            "revocation_scope": _enum_value(revocation_scope),
            "revocation_reason": _enum_value(revocation_reason),
        }
        return cls(
            event_id=event_id,
            lease_id=lease_id,
            session_id=session_id,
            agent_member_id=agent_member_id,
            agent_id=agent_id,
            workspace_generation=workspace_generation,
            event_kind=event_kind,
            previous_status=previous_status,
            status=status,
            state_version=state_version,
            actor_ref=actor_ref,
            occurred_at=occurred_at,
            event_digest=canonical_capability_digest(payload),
            revocation_scope=revocation_scope,
            revocation_reason=revocation_reason,
        )

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "lease_id": self.lease_id,
            "session_id": self.session_id,
            "agent_member_id": self.agent_member_id,
            "agent_id": self.agent_id,
            "workspace_generation": self.workspace_generation,
            "event_kind": self.event_kind.value,
            "previous_status": _enum_value(self.previous_status),
            "status": self.status.value,
            "state_version": self.state_version,
            "actor_ref": self.actor_ref,
            "occurred_at": self.occurred_at,
            "revocation_scope": _enum_value(self.revocation_scope),
            "revocation_reason": _enum_value(self.revocation_reason),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_payload(), "event_digest": self.event_digest}


@dataclass(frozen=True, slots=True)
class AgentRetirementRequest:
    request_id: str
    session_id: str
    agent_member_id: str
    agent_id: str
    workspace_generation: int
    capability_lease_id: str
    shutdown_request_ref: str
    cleanup_provider_id: str
    actor_ref: str
    requested_at: str
    canonical_digest: str
    schema_version: str = AGENT_RETIREMENT_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_RETIREMENT_REQUEST_SCHEMA_VERSION:
            raise ValueError("unsupported agent retirement request schema_version")
        for field_name in (
            "request_id",
            "session_id",
            "agent_member_id",
            "agent_id",
            "capability_lease_id",
            "shutdown_request_ref",
            "cleanup_provider_id",
            "actor_ref",
            "requested_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        if self.workspace_generation <= 0:
            raise ValueError("workspace_generation must be positive")
        _require_digest(self.canonical_digest, "canonical_digest")
        if self.canonical_digest != canonical_capability_digest(
            self.canonical_payload()
        ):
            raise ValueError(
                "canonical_digest does not match retirement request payload"
            )

    @classmethod
    def create(
        cls,
        *,
        request_id: str,
        session_id: str,
        agent_member_id: str,
        agent_id: str,
        workspace_generation: int,
        capability_lease_id: str,
        shutdown_request_ref: str,
        cleanup_provider_id: str,
        actor_ref: str,
        requested_at: str,
    ) -> AgentRetirementRequest:
        payload = {
            "schema_version": AGENT_RETIREMENT_REQUEST_SCHEMA_VERSION,
            "request_id": request_id,
            "session_id": session_id,
            "agent_member_id": agent_member_id,
            "agent_id": agent_id,
            "workspace_generation": workspace_generation,
            "capability_lease_id": capability_lease_id,
            "shutdown_request_ref": shutdown_request_ref,
            "cleanup_provider_id": cleanup_provider_id,
            "actor_ref": actor_ref,
            "requested_at": requested_at,
        }
        return cls(
            request_id=request_id,
            session_id=session_id,
            agent_member_id=agent_member_id,
            agent_id=agent_id,
            workspace_generation=workspace_generation,
            capability_lease_id=capability_lease_id,
            shutdown_request_ref=shutdown_request_ref,
            cleanup_provider_id=cleanup_provider_id,
            actor_ref=actor_ref,
            requested_at=requested_at,
            canonical_digest=canonical_capability_digest(payload),
        )

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "agent_member_id": self.agent_member_id,
            "agent_id": self.agent_id,
            "workspace_generation": self.workspace_generation,
            "capability_lease_id": self.capability_lease_id,
            "shutdown_request_ref": self.shutdown_request_ref,
            "cleanup_provider_id": self.cleanup_provider_id,
            "actor_ref": self.actor_ref,
            "requested_at": self.requested_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_payload(), "canonical_digest": self.canonical_digest}


@dataclass(frozen=True, slots=True)
class AgentRetirementCleanupProofRecord:
    proof_id: str
    retirement_request_id: str
    retirement_request_digest: str
    session_id: str
    agent_member_id: str
    agent_id: str
    workspace_generation: int
    capability_lease_id: str
    shutdown_request_ref: str
    provider_id: str
    cleanup_proof_digest: str
    reason: AgentRetirementReason
    observed_at: str
    canonical_digest: str
    schema_version: str = AGENT_RETIREMENT_CLEANUP_PROOF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_RETIREMENT_CLEANUP_PROOF_SCHEMA_VERSION:
            raise ValueError(
                "unsupported agent retirement cleanup proof schema_version"
            )
        for field_name in (
            "proof_id",
            "retirement_request_id",
            "session_id",
            "agent_member_id",
            "agent_id",
            "capability_lease_id",
            "shutdown_request_ref",
            "provider_id",
            "observed_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        if self.workspace_generation <= 0:
            raise ValueError("workspace_generation must be positive")
        _require_digest(
            self.retirement_request_digest,
            "retirement_request_digest",
        )
        _require_digest(self.cleanup_proof_digest, "cleanup_proof_digest")
        if not isinstance(self.reason, AgentRetirementReason):
            raise TypeError("reason must be an AgentRetirementReason")
        _require_digest(self.canonical_digest, "canonical_digest")
        if self.canonical_digest != canonical_capability_digest(
            self.canonical_payload()
        ):
            raise ValueError(
                "canonical_digest does not match retirement cleanup proof payload"
            )

    @classmethod
    def create(
        cls,
        *,
        proof_id: str,
        retirement_request_id: str,
        retirement_request_digest: str,
        session_id: str,
        agent_member_id: str,
        agent_id: str,
        workspace_generation: int,
        capability_lease_id: str,
        shutdown_request_ref: str,
        provider_id: str,
        cleanup_proof_digest: str,
        reason: AgentRetirementReason,
        observed_at: str,
    ) -> AgentRetirementCleanupProofRecord:
        payload = {
            "schema_version": AGENT_RETIREMENT_CLEANUP_PROOF_SCHEMA_VERSION,
            "proof_id": proof_id,
            "retirement_request_id": retirement_request_id,
            "retirement_request_digest": retirement_request_digest,
            "session_id": session_id,
            "agent_member_id": agent_member_id,
            "agent_id": agent_id,
            "workspace_generation": workspace_generation,
            "capability_lease_id": capability_lease_id,
            "shutdown_request_ref": shutdown_request_ref,
            "provider_id": provider_id,
            "cleanup_proof_digest": cleanup_proof_digest,
            "reason": reason.value,
            "observed_at": observed_at,
        }
        return cls(
            proof_id=proof_id,
            retirement_request_id=retirement_request_id,
            retirement_request_digest=retirement_request_digest,
            session_id=session_id,
            agent_member_id=agent_member_id,
            agent_id=agent_id,
            workspace_generation=workspace_generation,
            capability_lease_id=capability_lease_id,
            shutdown_request_ref=shutdown_request_ref,
            provider_id=provider_id,
            cleanup_proof_digest=cleanup_proof_digest,
            reason=reason,
            observed_at=observed_at,
            canonical_digest=canonical_capability_digest(payload),
        )

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "proof_id": self.proof_id,
            "retirement_request_id": self.retirement_request_id,
            "retirement_request_digest": self.retirement_request_digest,
            "session_id": self.session_id,
            "agent_member_id": self.agent_member_id,
            "agent_id": self.agent_id,
            "workspace_generation": self.workspace_generation,
            "capability_lease_id": self.capability_lease_id,
            "shutdown_request_ref": self.shutdown_request_ref,
            "provider_id": self.provider_id,
            "cleanup_proof_digest": self.cleanup_proof_digest,
            "reason": self.reason.value,
            "observed_at": self.observed_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_payload(), "canonical_digest": self.canonical_digest}


@dataclass(frozen=True, slots=True)
class AgentRetirementRecord:
    retirement_id: str
    session_id: str
    agent_member_id: str
    agent_id: str
    retirement_request_id: str
    retirement_request_digest: str
    workspace_generation: int
    capability_lease_id: str
    shutdown_request_ref: str
    cleanup_proof_id: str
    cleanup_proof_digest: str
    cleanup_proof_record_digest: str
    actor_ref: str
    reason: AgentRetirementReason
    retired_at: str
    canonical_digest: str
    schema_version: str = AGENT_RETIREMENT_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_RETIREMENT_RECORD_SCHEMA_VERSION:
            raise ValueError("unsupported agent retirement record schema_version")
        for field_name in (
            "retirement_id",
            "session_id",
            "agent_member_id",
            "agent_id",
            "retirement_request_id",
            "capability_lease_id",
            "shutdown_request_ref",
            "cleanup_proof_id",
            "actor_ref",
            "retired_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        if self.workspace_generation <= 0:
            raise ValueError("workspace_generation must be positive")
        _require_digest(
            self.retirement_request_digest,
            "retirement_request_digest",
        )
        _require_digest(self.cleanup_proof_digest, "cleanup_proof_digest")
        _require_digest(
            self.cleanup_proof_record_digest,
            "cleanup_proof_record_digest",
        )
        if not isinstance(self.reason, AgentRetirementReason):
            raise TypeError("reason must be an AgentRetirementReason")
        _require_digest(self.canonical_digest, "canonical_digest")
        if self.canonical_digest != canonical_capability_digest(
            self.canonical_payload()
        ):
            raise ValueError("canonical_digest does not match retirement payload")

    @classmethod
    def create(
        cls,
        *,
        retirement_id: str,
        session_id: str,
        agent_member_id: str,
        agent_id: str,
        retirement_request_id: str,
        retirement_request_digest: str,
        workspace_generation: int,
        capability_lease_id: str,
        shutdown_request_ref: str,
        cleanup_proof_id: str,
        cleanup_proof_digest: str,
        cleanup_proof_record_digest: str,
        actor_ref: str,
        reason: AgentRetirementReason,
        retired_at: str,
    ) -> AgentRetirementRecord:
        payload = {
            "schema_version": AGENT_RETIREMENT_RECORD_SCHEMA_VERSION,
            "retirement_id": retirement_id,
            "session_id": session_id,
            "agent_member_id": agent_member_id,
            "agent_id": agent_id,
            "retirement_request_id": retirement_request_id,
            "retirement_request_digest": retirement_request_digest,
            "workspace_generation": workspace_generation,
            "capability_lease_id": capability_lease_id,
            "shutdown_request_ref": shutdown_request_ref,
            "cleanup_proof_id": cleanup_proof_id,
            "cleanup_proof_digest": cleanup_proof_digest,
            "cleanup_proof_record_digest": cleanup_proof_record_digest,
            "actor_ref": actor_ref,
            "reason": reason.value,
            "retired_at": retired_at,
        }
        return cls(
            retirement_id=retirement_id,
            session_id=session_id,
            agent_member_id=agent_member_id,
            agent_id=agent_id,
            retirement_request_id=retirement_request_id,
            retirement_request_digest=retirement_request_digest,
            workspace_generation=workspace_generation,
            capability_lease_id=capability_lease_id,
            shutdown_request_ref=shutdown_request_ref,
            cleanup_proof_id=cleanup_proof_id,
            cleanup_proof_digest=cleanup_proof_digest,
            cleanup_proof_record_digest=cleanup_proof_record_digest,
            actor_ref=actor_ref,
            reason=reason,
            retired_at=retired_at,
            canonical_digest=canonical_capability_digest(payload),
        )

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "retirement_id": self.retirement_id,
            "session_id": self.session_id,
            "agent_member_id": self.agent_member_id,
            "agent_id": self.agent_id,
            "retirement_request_id": self.retirement_request_id,
            "retirement_request_digest": self.retirement_request_digest,
            "workspace_generation": self.workspace_generation,
            "capability_lease_id": self.capability_lease_id,
            "shutdown_request_ref": self.shutdown_request_ref,
            "cleanup_proof_id": self.cleanup_proof_id,
            "cleanup_proof_digest": self.cleanup_proof_digest,
            "cleanup_proof_record_digest": self.cleanup_proof_record_digest,
            "actor_ref": self.actor_ref,
            "reason": self.reason.value,
            "retired_at": self.retired_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_payload(), "canonical_digest": self.canonical_digest}


__all__ = [
    "AGENT_CAPABILITY_LEASE_EVENT_SCHEMA_VERSION",
    "AGENT_CAPABILITY_LEASE_SCHEMA_VERSION",
    "AGENT_RETIREMENT_CLEANUP_PROOF_SCHEMA_VERSION",
    "AGENT_RETIREMENT_RECORD_SCHEMA_VERSION",
    "AGENT_RETIREMENT_REQUEST_SCHEMA_VERSION",
    "AGENT_WORKSPACE_GENERATION_RESERVATION_SCHEMA_VERSION",
    "AgentCapability",
    "AgentCapabilityLease",
    "AgentCapabilityLeaseEventKind",
    "AgentCapabilityLeaseLifecycleEvent",
    "AgentCapabilityLeaseStatus",
    "AgentCapabilityProfile",
    "AgentCapabilityRevocationReason",
    "AgentCapabilityRevocationScope",
    "AgentRetirementReason",
    "AgentRetirementCleanupProofRecord",
    "AgentRetirementRecord",
    "AgentRetirementRequest",
    "AgentWorkspaceGenerationReservation",
    "AgentWorkspaceGenerationStatus",
    "AgentWorkspaceReadinessOwnerKind",
    "EXECUTOR_AGENT_CAPABILITIES",
    "GENERAL_AGENT_CAPABILITIES",
    "canonical_capability_digest",
    "capabilities_for_profile",
    "capability_set_digest",
    "target_scope_digest",
]
