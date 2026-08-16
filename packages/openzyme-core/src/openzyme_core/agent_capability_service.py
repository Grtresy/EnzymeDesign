from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from typing import Mapping
from typing import Protocol
from typing import runtime_checkable
from uuid import uuid4

from openzyme_domain import AgentCapability
from openzyme_domain import AgentCapabilityLease
from openzyme_domain import AgentCapabilityLeaseEventKind
from openzyme_domain import AgentCapabilityLeaseLifecycleEvent
from openzyme_domain import AgentCapabilityLeaseStatus
from openzyme_domain import AgentCapabilityProfile
from openzyme_domain import AgentCapabilityRevocationReason
from openzyme_domain import AgentCapabilityRevocationScope
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentGitWorkspace
from openzyme_domain import AgentGitWorkspaceStatus
from openzyme_domain import AgentRetirementCleanupProofRecord
from openzyme_domain import AgentRetirementReason
from openzyme_domain import AgentRetirementRecord
from openzyme_domain import AgentRetirementRequest
from openzyme_domain import AgentWorkspaceGenerationReservation
from openzyme_domain import AgentWorkspaceGenerationStatus
from openzyme_domain import AgentWorkspaceReadinessOwnerKind
from openzyme_domain import Session
from openzyme_domain import canonical_capability_digest
from openzyme_domain import capabilities_for_profile
from openzyme_domain.control_plane import utc_now_iso

from .mutation_authority import AgentCapabilityReadinessActivationAuthority
from .mutation_authority import AgentRetirementLifecycleAuthority
from .repositories import CoreRepositories


AGENT_CAPABILITY_POLICY_SCHEMA_VERSION = "agent_capability_policy@1"
AGENT_CAPABILITY_ADMISSION_SCHEMA_VERSION = "agent_capability_admission@1"


class AgentCapabilityError(RuntimeError):
    error_code = "agent_capability_error"


class AgentCapabilityConflictError(AgentCapabilityError):
    error_code = "agent_capability_conflict"


class AgentCapabilityProvisioningRequiredError(AgentCapabilityError):
    error_code = "provisioning_required"


class AgentCapabilityPolicyDriftError(AgentCapabilityError):
    error_code = "agent_capability_policy_drift"


class AgentCapabilityRevokedError(AgentCapabilityError):
    error_code = "agent_capability_revoked"


class AgentCapabilityRetiredError(AgentCapabilityError):
    error_code = "agent_retired"


class AgentRetirementRequestedError(AgentCapabilityError):
    error_code = "agent_retirement_requested"


class AgentRetirementActiveClaimError(AgentCapabilityError):
    error_code = "agent_retirement_active_claim"


class AgentCapabilityAdmissionRejectedError(AgentCapabilityError):
    error_code = "agent_capability_admission_rejected"


class AgentWorkspaceReadinessProviderUnavailableError(AgentCapabilityError):
    error_code = "workspace_readiness_provider_unavailable"


class AgentRetirementCleanupProviderUnavailableError(AgentCapabilityError):
    error_code = "retirement_cleanup_provider_unavailable"


class AgentCapabilityCredentialProviderUnavailableError(AgentCapabilityError):
    error_code = "agent_credential_provider_unavailable"


@dataclass(frozen=True, slots=True)
class AgentCapabilityPolicy:
    policy_version: str
    role_profiles: tuple[tuple[str, AgentCapabilityProfile], ...]
    allowed_child_profiles: tuple[
        tuple[str, tuple[AgentCapabilityProfile, ...]], ...
    ]
    profile_targets: tuple[tuple[AgentCapabilityProfile, tuple[str, ...]], ...]
    policy_digest: str
    schema_version: str = AGENT_CAPABILITY_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_CAPABILITY_POLICY_SCHEMA_VERSION:
            raise ValueError("unsupported agent capability policy schema version")
        if not self.policy_version:
            raise ValueError("agent capability policy version must not be empty")
        roles = tuple(role for role, _ in self.role_profiles)
        if roles != tuple(sorted(set(roles))):
            raise ValueError("agent capability policy roles must be unique and sorted")
        child_roles = tuple(role for role, _ in self.allowed_child_profiles)
        if child_roles != roles:
            raise ValueError("allowed child profile roles must match role profile roles")
        profiles = tuple(profile for profile, _ in self.profile_targets)
        if profiles != (
            AgentCapabilityProfile.GENERAL,
            AgentCapabilityProfile.EXECUTOR,
        ):
            raise ValueError("agent capability policy must define both closed profiles")
        for _, allowed in self.allowed_child_profiles:
            if len(set(allowed)) != len(allowed):
                raise ValueError("allowed child profiles must be unique")
        for _, targets in self.profile_targets:
            if not targets or targets != tuple(sorted(set(targets))):
                raise ValueError("profile targets must be non-empty, unique, and sorted")
        if self.policy_digest != canonical_capability_digest(self.payload()):
            raise ValueError("agent capability policy digest does not match policy")

    @classmethod
    def create_default(cls) -> AgentCapabilityPolicy:
        role_profiles = (
            ("executor", AgentCapabilityProfile.EXECUTOR),
            ("master", AgentCapabilityProfile.GENERAL),
            ("reporter", AgentCapabilityProfile.GENERAL),
            ("researcher", AgentCapabilityProfile.GENERAL),
        )
        allowed_child_profiles = (
            ("executor", ()),
            (
                "master",
                (
                    AgentCapabilityProfile.GENERAL,
                    AgentCapabilityProfile.EXECUTOR,
                ),
            ),
            ("reporter", ()),
            ("researcher", ()),
        )
        profile_targets = (
            (
                AgentCapabilityProfile.GENERAL,
                ("network:deployment", "repository:session-pinned"),
            ),
            (
                AgentCapabilityProfile.EXECUTOR,
                (
                    "hpc:primary",
                    "network:deployment",
                    "repository:session-pinned",
                ),
            ),
        )
        payload = {
            "schema_version": AGENT_CAPABILITY_POLICY_SCHEMA_VERSION,
            "policy_version": "agent-capability-policy-v1",
            "role_profiles": [
                {"role": role, "profile": profile.value}
                for role, profile in role_profiles
            ],
            "allowed_child_profiles": [
                {
                    "role": role,
                    "profiles": [profile.value for profile in profiles],
                }
                for role, profiles in allowed_child_profiles
            ],
            "profile_targets": [
                {
                    "profile": profile.value,
                    "target_ids": list(targets),
                }
                for profile, targets in profile_targets
            ],
        }
        return cls(
            policy_version="agent-capability-policy-v1",
            role_profiles=role_profiles,
            allowed_child_profiles=allowed_child_profiles,
            profile_targets=profile_targets,
            policy_digest=canonical_capability_digest(payload),
        )

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "role_profiles": [
                {"role": role, "profile": profile.value}
                for role, profile in self.role_profiles
            ],
            "allowed_child_profiles": [
                {
                    "role": role,
                    "profiles": [profile.value for profile in profiles],
                }
                for role, profiles in self.allowed_child_profiles
            ],
            "profile_targets": [
                {
                    "profile": profile.value,
                    "target_ids": list(targets),
                }
                for profile, targets in self.profile_targets
            ],
        }

    def profile_for_role(self, role: str) -> AgentCapabilityProfile:
        for candidate, profile in self.role_profiles:
            if candidate == role:
                return profile
        raise AgentCapabilityAdmissionRejectedError(
            f"agent role {role!r} has no capability profile"
        )

    def targets_for_profile(
        self,
        profile: AgentCapabilityProfile,
    ) -> tuple[str, ...]:
        for candidate, target_ids in self.profile_targets:
            if candidate is profile:
                return target_ids
        raise AgentCapabilityAdmissionRejectedError(
            f"agent capability profile {profile.value!r} has no target scope"
        )

    def assert_child_profile_allowed(
        self,
        *,
        parent_role: str,
        child_profile: AgentCapabilityProfile,
    ) -> None:
        for role, profiles in self.allowed_child_profiles:
            if role == parent_role:
                if child_profile not in profiles:
                    raise AgentCapabilityAdmissionRejectedError(
                        f"agent role {parent_role!r} cannot delegate profile "
                        f"{child_profile.value!r}"
                    )
                return
        raise AgentCapabilityAdmissionRejectedError(
            f"agent role {parent_role!r} has no delegation policy"
        )


DEFAULT_AGENT_CAPABILITY_POLICY = AgentCapabilityPolicy.create_default()


@dataclass(frozen=True, slots=True)
class AgentWorkspaceReadinessProof:
    provider_id: str
    reservation_id: str
    reservation_fingerprint: str
    session_id: str
    agent_member_id: str
    agent_id: str
    workspace_generation: int
    readiness_ref: str
    readiness_digest: str
    observed_at: str

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.provider_id, "provider_id"),
            (self.reservation_id, "reservation_id"),
            (self.session_id, "session_id"),
            (self.agent_member_id, "agent_member_id"),
            (self.agent_id, "agent_id"),
            (self.readiness_ref, "readiness_ref"),
            (self.observed_at, "observed_at"),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{field_name} must not be empty or padded")
        if self.workspace_generation <= 0:
            raise ValueError("workspace_generation must be positive")
        for digest, field_name in (
            (self.reservation_fingerprint, "reservation_fingerprint"),
            (self.readiness_digest, "readiness_digest"),
        ):
            if len(digest) != 71 or not digest.startswith("sha256:"):
                raise ValueError(f"{field_name} must be a sha256 digest")
            if any(
                character not in "0123456789abcdef"
                for character in digest.removeprefix("sha256:")
            ):
                raise ValueError(f"{field_name} must use lowercase hexadecimal")


class AgentWorkspaceReadinessProvider(Protocol):
    provider_id: str

    def verify_readiness(
        self,
        reservation: AgentWorkspaceGenerationReservation,
    ) -> AgentWorkspaceReadinessProof: ...


@runtime_checkable
class AtomicAgentWorkspaceReadinessProvider(Protocol):
    """Optional extension for providers that persist a concrete workspace."""

    def stage_atomic_readiness(
        self,
        *,
        repositories: CoreRepositories,
        proof: AgentWorkspaceReadinessProof,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class AgentRetirementCleanupProof:
    provider_id: str
    retirement_request_id: str
    retirement_request_digest: str
    session_id: str
    agent_member_id: str
    agent_id: str
    workspace_generation: int
    capability_lease_id: str
    shutdown_request_ref: str
    cleanup_proof_digest: str
    reason: AgentRetirementReason
    observed_at: str

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.provider_id, "provider_id"),
            (self.retirement_request_id, "retirement_request_id"),
            (self.session_id, "session_id"),
            (self.agent_member_id, "agent_member_id"),
            (self.agent_id, "agent_id"),
            (self.capability_lease_id, "capability_lease_id"),
            (self.shutdown_request_ref, "shutdown_request_ref"),
            (self.observed_at, "observed_at"),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{field_name} must not be empty or padded")
        if self.workspace_generation <= 0:
            raise ValueError("workspace_generation must be positive")
        if not isinstance(self.reason, AgentRetirementReason):
            raise TypeError("reason must be an AgentRetirementReason")
        for digest, field_name in (
            (self.retirement_request_digest, "retirement_request_digest"),
            (self.cleanup_proof_digest, "cleanup_proof_digest"),
        ):
            if len(digest) != 71 or not digest.startswith("sha256:"):
                raise ValueError(f"{field_name} must be a sha256 digest")
            if any(
                character not in "0123456789abcdef"
                for character in digest.removeprefix("sha256:")
            ):
                raise ValueError(f"{field_name} must use lowercase hexadecimal")


class AgentRetirementCleanupProvider(Protocol):
    provider_id: str

    def verify_cleanup(
        self,
        *,
        request: AgentRetirementRequest,
    ) -> AgentRetirementCleanupProof: ...


@dataclass(frozen=True, slots=True)
class AgentCapabilityIssuance:
    reservation: AgentWorkspaceGenerationReservation
    lease: AgentCapabilityLease


@dataclass(frozen=True, slots=True)
class AgentCapabilityAdmissionRequest:
    lease_id: str
    session_id: str
    agent_member_id: str
    agent_id: str
    workspace_generation: int
    service_id: str
    protocol: str
    operation_class: str
    required_capabilities: tuple[AgentCapability, ...] = ()
    target_id: str | None = None
    schema_version: str = AGENT_CAPABILITY_ADMISSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_CAPABILITY_ADMISSION_SCHEMA_VERSION:
            raise ValueError("unsupported agent capability admission schema version")
        for value, field_name in (
            (self.lease_id, "lease_id"),
            (self.session_id, "session_id"),
            (self.agent_member_id, "agent_member_id"),
            (self.agent_id, "agent_id"),
            (self.service_id, "service_id"),
            (self.protocol, "protocol"),
            (self.operation_class, "operation_class"),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{field_name} must not be empty or padded")
        if self.workspace_generation <= 0:
            raise ValueError("workspace_generation must be positive")
        if self.target_id is not None and not self.target_id:
            raise ValueError("target_id must be non-empty when provided")
        if len(set(self.required_capabilities)) != len(self.required_capabilities):
            raise ValueError("required capabilities must be unique")
        if not all(
            isinstance(capability, AgentCapability)
            for capability in self.required_capabilities
        ):
            raise TypeError("required_capabilities must contain AgentCapability values")

    @property
    def request_digest(self) -> str:
        return canonical_capability_digest(
            {
                "schema_version": self.schema_version,
                "lease_id": self.lease_id,
                "session_id": self.session_id,
                "agent_member_id": self.agent_member_id,
                "agent_id": self.agent_id,
                "workspace_generation": self.workspace_generation,
                "service_id": self.service_id,
                "protocol": self.protocol,
                "operation_class": self.operation_class,
                "required_capabilities": [
                    capability.value for capability in self.required_capabilities
                ],
                "target_id": self.target_id,
            }
        )


@dataclass(frozen=True, slots=True)
class ActiveAgentCapabilityLeaseClaims:
    lease: AgentCapabilityLease
    reservation: AgentWorkspaceGenerationReservation
    workspace: AgentGitWorkspace | None
    request_digest: str

    def require_workspace(self) -> AgentGitWorkspace:
        if self.workspace is None:
            raise AgentCapabilityProvisioningRequiredError(
                "operation requires an exact ready generation-owned Git workspace"
            )
        return self.workspace


@dataclass(slots=True)
class ActiveAgentCapabilityLeaseValidator:
    repositories: CoreRepositories
    policy: AgentCapabilityPolicy = DEFAULT_AGENT_CAPABILITY_POLICY

    def validate(
        self,
        request: AgentCapabilityAdmissionRequest,
    ) -> ActiveAgentCapabilityLeaseClaims:
        lease = self.repositories.agent_capability_leases.get(request.lease_id)
        if lease is None:
            raise AgentCapabilityProvisioningRequiredError(
                f"capability lease {request.lease_id!r} does not exist"
            )
        expected_identity = (
            request.session_id,
            request.agent_member_id,
            request.agent_id,
            request.workspace_generation,
        )
        actual_identity = (
            lease.session_id,
            lease.agent_member_id,
            lease.agent_id,
            lease.workspace_generation,
        )
        if actual_identity != expected_identity:
            raise AgentCapabilityAdmissionRejectedError(
                "capability lease identity does not match the admission request"
            )
        agent = self.repositories.agents.get_by_member_id(request.agent_member_id)
        if agent is None or (agent.session_id, agent.agent_id) != (
            request.session_id,
            request.agent_id,
        ):
            raise AgentCapabilityAdmissionRejectedError(
                "capability lease agent owner does not match canonical membership"
            )
        retirement = self.repositories.agent_retirements.get_by_agent(
            session_id=request.session_id,
            agent_member_id=request.agent_member_id,
        )
        if retirement is not None:
            raise AgentCapabilityRetiredError(
                f"agent member {request.agent_member_id!r} is retired"
            )
        retirement_request = self.repositories.agent_retirement_requests.get_by_agent(
            session_id=request.session_id,
            agent_member_id=request.agent_member_id,
        )
        if retirement_request is not None:
            raise AgentRetirementRequestedError(
                f"agent member {request.agent_member_id!r} has a durable "
                "retirement request"
            )
        if lease.status is AgentCapabilityLeaseStatus.REVOKED:
            raise AgentCapabilityRevokedError(
                f"capability lease {request.lease_id!r} is revoked"
            )
        reservation = self.repositories.agent_workspace_generation_reservations.get_current(
            session_id=request.session_id,
            agent_member_id=request.agent_member_id,
        )
        if reservation is None:
            raise AgentCapabilityProvisioningRequiredError(
                "agent has no current workspace generation reservation"
            )
        if (
            reservation.agent_id != request.agent_id
            or reservation.workspace_generation != request.workspace_generation
            or reservation.status is not AgentWorkspaceGenerationStatus.READY
        ):
            raise AgentCapabilityProvisioningRequiredError(
                "agent current workspace generation is not the exact ready generation"
            )
        if lease.status is not AgentCapabilityLeaseStatus.ACTIVE:
            raise AgentCapabilityProvisioningRequiredError(
                "agent capability lease is pending workspace readiness"
            )
        workspace: AgentGitWorkspace | None = None
        if (reservation.readiness_ref or "").startswith("agent_git_workspace:"):
            workspace = self.repositories.agent_git_workspaces.get_current(
                session_id=request.session_id,
                agent_member_id=request.agent_member_id,
            )
            if (
                workspace is None
                or workspace.status is not AgentGitWorkspaceStatus.READY
                or workspace.agent_id != request.agent_id
                or workspace.workspace_generation != request.workspace_generation
                or workspace.reservation_id != reservation.reservation_id
                or workspace.capability_lease_id != lease.lease_id
                or workspace.capability_policy_version != lease.policy_version
                or workspace.capability_policy_digest != lease.policy_digest
            ):
                raise AgentCapabilityProvisioningRequiredError(
                    "agent has no exact ready generation-owned Git workspace"
                )
        expected_profile = self.policy.profile_for_role(agent.role)
        if (
            lease.profile is not expected_profile
            or lease.capabilities != capabilities_for_profile(expected_profile)
            or lease.policy_version != self.policy.policy_version
            or lease.policy_digest != self.policy.policy_digest
            or lease.target_ids != self.policy.targets_for_profile(expected_profile)
        ):
            raise AgentCapabilityPolicyDriftError(
                "canonical capability lease no longer matches current policy"
            )
        missing = tuple(
            capability
            for capability in request.required_capabilities
            if capability not in lease.capabilities
        )
        if missing:
            raise AgentCapabilityAdmissionRejectedError(
                "capability lease does not authorize required capabilities: "
                + ", ".join(capability.value for capability in missing)
            )
        if request.target_id is not None and request.target_id not in lease.target_ids:
            raise AgentCapabilityAdmissionRejectedError(
                f"capability lease does not authorize target {request.target_id!r}"
            )
        self._validate_parent_provenance(agent, lease)
        return ActiveAgentCapabilityLeaseClaims(
            lease=lease,
            reservation=reservation,
            workspace=workspace,
            request_digest=request.request_digest,
        )

    def require_current_agent(
        self,
        *,
        session_id: str,
        agent_id: str,
        expected_lease_id: str | None = None,
        expected_workspace_generation: int | None = None,
        service_id: str = "agent_runtime",
        protocol: str = "bounded_turn",
        operation_class: str = "agent_runtime",
        required_capabilities: tuple[AgentCapability, ...] = (),
        target_id: str | None = None,
    ) -> ActiveAgentCapabilityLeaseClaims:
        agent = self.repositories.agents.get(session_id, agent_id)
        if agent is None or agent.member_id is None:
            raise AgentCapabilityProvisioningRequiredError(
                f"agent {agent_id!r} has no canonical member identity"
            )
        reservation = self.repositories.agent_workspace_generation_reservations.get_current(
            session_id=session_id,
            agent_member_id=agent.member_id,
        )
        if reservation is None:
            raise AgentCapabilityProvisioningRequiredError(
                f"agent {agent_id!r} has no current workspace generation"
            )
        if (
            expected_workspace_generation is not None
            and reservation.workspace_generation != expected_workspace_generation
        ):
            raise AgentCapabilityAdmissionRejectedError(
                "runtime occurrence workspace generation is stale"
            )
        lease = self.repositories.agent_capability_leases.get_by_generation(
            session_id=session_id,
            agent_member_id=agent.member_id,
            workspace_generation=reservation.workspace_generation,
        )
        if lease is None:
            raise AgentCapabilityProvisioningRequiredError(
                f"agent {agent_id!r} has no lease for its current generation"
            )
        if expected_lease_id is not None and lease.lease_id != expected_lease_id:
            raise AgentCapabilityAdmissionRejectedError(
                "runtime occurrence capability lease identity is stale"
            )
        return self.validate(
            AgentCapabilityAdmissionRequest(
                lease_id=lease.lease_id,
                session_id=session_id,
                agent_member_id=agent.member_id,
                agent_id=agent_id,
                workspace_generation=reservation.workspace_generation,
                service_id=service_id,
                protocol=protocol,
                operation_class=operation_class,
                required_capabilities=required_capabilities,
                target_id=target_id,
            )
        )

    def _validate_parent_provenance(
        self,
        agent: AgentMember,
        lease: AgentCapabilityLease,
    ) -> None:
        if agent.parent_agent_id is None:
            if lease.parent_lease_id is not None:
                raise AgentCapabilityAdmissionRejectedError(
                    "root agent lease unexpectedly names parent provenance"
                )
            return
        if lease.parent_lease_id is None:
            raise AgentCapabilityAdmissionRejectedError(
                "child agent lease is missing parent provenance"
            )
        parent = self.repositories.agent_capability_leases.get(lease.parent_lease_id)
        if (
            parent is None
            or parent.session_id != agent.session_id
            or parent.agent_id != agent.parent_agent_id
        ):
            raise AgentCapabilityAdmissionRejectedError(
                "child agent lease parent provenance is invalid"
            )
        parent_agent = self.repositories.agents.get(
            agent.session_id,
            agent.parent_agent_id,
        )
        if parent_agent is None:
            raise AgentCapabilityAdmissionRejectedError(
                "child agent canonical parent is missing"
            )
        self.policy.assert_child_profile_allowed(
            parent_role=parent_agent.role,
            child_profile=lease.profile,
        )


class AgentScopedCredentialIssuer(Protocol):
    def issue_for_active_lease(
        self,
        request: AgentCapabilityAdmissionRequest,
    ) -> object: ...


@dataclass(slots=True)
class UnavailableRemoteAgentCredentialIssuer:
    validator: ActiveAgentCapabilityLeaseValidator

    def issue_for_active_lease(
        self,
        request: AgentCapabilityAdmissionRequest,
    ) -> object:
        self.validator.validate(request)
        raise AgentCapabilityCredentialProviderUnavailableError(
            "remote agent credential provider is not implemented by C2"
        )


@dataclass(slots=True)
class AgentCapabilityLeaseService:
    repositories: CoreRepositories
    policy: AgentCapabilityPolicy = DEFAULT_AGENT_CAPABILITY_POLICY
    readiness_providers: Mapping[str, AgentWorkspaceReadinessProvider] = field(
        default_factory=dict
    )
    retirement_cleanup_providers: Mapping[
        str, AgentRetirementCleanupProvider
    ] = field(default_factory=dict)

    @property
    def validator(self) -> ActiveAgentCapabilityLeaseValidator:
        return ActiveAgentCapabilityLeaseValidator(self.repositories, self.policy)

    def reserve_and_issue(
        self,
        *,
        session_id: str,
        agent_id: str,
        idempotency_key: str,
        actor_ref: str,
        parent_lease_id: str | None = None,
        workspace_generation: int | None = None,
        requested_profile: AgentCapabilityProfile | None = None,
        requested_capabilities: tuple[AgentCapability, ...] | None = None,
        requested_target_ids: tuple[str, ...] | None = None,
        requested_policy_version: str | None = None,
        requested_policy_digest: str | None = None,
    ) -> AgentCapabilityIssuance:
        if not idempotency_key or not actor_ref:
            raise ValueError("idempotency_key and actor_ref must not be empty")
        with self.repositories.atomic(prefix="agent_capability_issue"):
            session = self.repositories.sessions.get(session_id)
            if session is None:
                raise AgentCapabilityAdmissionRejectedError(
                    f"session {session_id!r} does not exist"
                )
            if session.status.is_terminal:
                raise AgentCapabilityAdmissionRejectedError(
                    "terminal session cannot issue an agent capability lease"
                )
            agent = self._require_agent(session_id=session_id, agent_id=agent_id)
            member_id = self._require_member_id(agent)
            if self.repositories.agent_retirements.get_by_agent(
                session_id=session_id,
                agent_member_id=member_id,
            ) is not None:
                raise AgentCapabilityRetiredError(
                    f"agent member {member_id!r} is retired"
                )
            if self.repositories.agent_retirement_requests.get_by_agent(
                session_id=session_id,
                agent_member_id=member_id,
            ) is not None:
                raise AgentRetirementRequestedError(
                    f"agent member {member_id!r} has a durable retirement request"
                )
            profile = self.policy.profile_for_role(agent.role)
            capabilities = capabilities_for_profile(profile)
            target_ids = self.policy.targets_for_profile(profile)
            self._assert_requested_policy(
                profile=profile,
                capabilities=capabilities,
                target_ids=target_ids,
                requested_profile=requested_profile,
                requested_capabilities=requested_capabilities,
                requested_target_ids=requested_target_ids,
                requested_policy_version=requested_policy_version,
                requested_policy_digest=requested_policy_digest,
            )
            existing = self.repositories.agent_capability_leases.get_by_idempotency_key(
                session_id=session_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                if existing.status is AgentCapabilityLeaseStatus.REVOKED:
                    raise AgentCapabilityRevokedError(
                        "revoked capability issuance cannot be replayed as live"
                    )
                reservation = self.repositories.agent_workspace_generation_reservations.get_by_generation(
                    session_id=session_id,
                    agent_member_id=member_id,
                    workspace_generation=existing.workspace_generation,
                )
                if reservation is None:
                    raise AgentCapabilityConflictError(
                        "existing capability lease has no generation reservation"
                    )
                self._assert_replayed_issuance(
                    lease=existing,
                    reservation=reservation,
                    agent=agent,
                    workspace_generation=workspace_generation,
                    profile=profile,
                    capabilities=capabilities,
                    target_ids=target_ids,
                    parent_lease_id=parent_lease_id,
                )
                return AgentCapabilityIssuance(reservation, existing)

            self._assert_parent_authority(
                agent=agent,
                parent_lease_id=parent_lease_id,
                child_profile=profile,
            )

            reservation = self.repositories.agent_workspace_generation_reservations.get_current(
                session_id=session_id,
                agent_member_id=member_id,
            )
            if reservation is None:
                generation = 1 if workspace_generation is None else workspace_generation
                now = utc_now_iso()
                reservation = AgentWorkspaceGenerationReservation.create(
                    reservation_id=f"agent_workspace_generation_{uuid4().hex}",
                    session_id=session_id,
                    agent_member_id=member_id,
                    agent_id=agent.agent_id,
                    workspace_generation=generation,
                    status=AgentWorkspaceGenerationStatus.RESERVED,
                    state_version=1,
                    reserved_at=now,
                    updated_at=now,
                )
                self.repositories.agent_workspace_generation_reservations.add(
                    reservation
                )
            elif (
                workspace_generation is not None
                and reservation.workspace_generation != workspace_generation
            ):
                raise AgentCapabilityConflictError(
                    "workspace generation conflicts with the current reservation"
                )
            existing_generation_lease = self.repositories.agent_capability_leases.get_by_generation(
                session_id=session_id,
                agent_member_id=member_id,
                workspace_generation=reservation.workspace_generation,
            )
            if existing_generation_lease is not None:
                raise AgentCapabilityConflictError(
                    "workspace generation already has a different capability lease"
                )
            now = utc_now_iso()
            lease = AgentCapabilityLease.create(
                lease_id=f"agent_capability_lease_{uuid4().hex}",
                session_id=session_id,
                agent_member_id=member_id,
                agent_id=agent.agent_id,
                workspace_generation=reservation.workspace_generation,
                profile=profile,
                capabilities=capabilities,
                target_ids=target_ids,
                policy_version=self.policy.policy_version,
                policy_digest=self.policy.policy_digest,
                parent_lease_id=parent_lease_id,
                idempotency_key=idempotency_key,
                status=AgentCapabilityLeaseStatus.PENDING_WORKSPACE,
                state_version=1,
                issued_at=now,
                updated_at=now,
            )
            self.repositories.agent_capability_leases.add(lease)
            self.repositories.agent_capability_lease_events.append(
                self._event(
                    lease=lease,
                    event_kind=AgentCapabilityLeaseEventKind.ISSUED,
                    previous_status=None,
                    actor_ref=actor_ref,
                )
            )
            self._mark_provisioning_required(agent)
            return AgentCapabilityIssuance(reservation, lease)

    def activate_with_provider(
        self,
        *,
        lease_id: str,
        provider_id: str,
        actor_ref: str,
    ) -> AgentCapabilityIssuance:
        provider = self.readiness_providers.get(provider_id)
        if provider is None or provider.provider_id != provider_id:
            raise AgentWorkspaceReadinessProviderUnavailableError(
                f"workspace readiness provider {provider_id!r} is not registered"
            )
        lease = self.repositories.agent_capability_leases.get(lease_id)
        if lease is None:
            raise AgentCapabilityProvisioningRequiredError(
                f"capability lease {lease_id!r} does not exist"
            )
        if self.repositories.agent_retirement_requests.get_by_agent(
            session_id=lease.session_id,
            agent_member_id=lease.agent_member_id,
        ) is not None:
            raise AgentRetirementRequestedError(
                f"agent member {lease.agent_member_id!r} has a durable "
                "retirement request"
            )
        reservation = self.repositories.agent_workspace_generation_reservations.get_by_generation(
            session_id=lease.session_id,
            agent_member_id=lease.agent_member_id,
            workspace_generation=lease.workspace_generation,
        )
        if reservation is None:
            raise AgentCapabilityProvisioningRequiredError(
                "capability lease has no workspace generation reservation"
            )
        proof = provider.verify_readiness(reservation)
        if proof.provider_id != provider_id:
            raise AgentCapabilityAdmissionRejectedError(
                "workspace readiness proof provider identity changed"
            )
        return self._activate_with_proof(
            lease_id=lease_id,
            proof=proof,
            actor_ref=actor_ref,
        )

    def _activate_with_proof(
        self,
        *,
        lease_id: str,
        proof: AgentWorkspaceReadinessProof,
        actor_ref: str,
    ) -> AgentCapabilityIssuance:
        registered = self.readiness_providers.get(proof.provider_id)
        if registered is None or registered.provider_id != proof.provider_id:
            raise AgentWorkspaceReadinessProviderUnavailableError(
                f"workspace readiness provider {proof.provider_id!r} is not registered"
            )
        with self.repositories.atomic(prefix="agent_capability_activate"):
            lease = self.repositories.agent_capability_leases.get(lease_id)
            if lease is None:
                raise AgentCapabilityProvisioningRequiredError(
                    f"capability lease {lease_id!r} does not exist"
                )
            if lease.status is AgentCapabilityLeaseStatus.REVOKED:
                raise AgentCapabilityRevokedError(
                    f"capability lease {lease_id!r} is revoked"
                )
            if self.repositories.agent_retirement_requests.get_by_agent(
                session_id=lease.session_id,
                agent_member_id=lease.agent_member_id,
            ) is not None:
                raise AgentRetirementRequestedError(
                    f"agent member {lease.agent_member_id!r} has a durable "
                    "retirement request"
                )
            reservation = self.repositories.agent_workspace_generation_reservations.get_by_generation(
                session_id=lease.session_id,
                agent_member_id=lease.agent_member_id,
                workspace_generation=lease.workspace_generation,
            )
            if reservation is None:
                raise AgentCapabilityProvisioningRequiredError(
                    "capability lease has no workspace generation reservation"
                )
            self._assert_readiness_proof(reservation, proof)
            agent = self._require_agent(
                session_id=lease.session_id,
                agent_id=lease.agent_id,
            )
            self._assert_lease_matches_current_policy(lease=lease, agent=agent)
            if lease.status is AgentCapabilityLeaseStatus.ACTIVE:
                if (
                    reservation.status is not AgentWorkspaceGenerationStatus.READY
                    or reservation.readiness_owner_ref != proof.provider_id
                    or reservation.readiness_ref != proof.readiness_ref
                    or reservation.readiness_digest != proof.readiness_digest
                ):
                    raise AgentCapabilityConflictError(
                        "active lease readiness facts conflict with replayed proof"
                    )
                return AgentCapabilityIssuance(reservation, lease)
            if reservation.status is not AgentWorkspaceGenerationStatus.RESERVED:
                raise AgentCapabilityConflictError(
                    "only a reserved workspace generation can become ready"
                )
            if not (
                agent.status is AgentMemberStatus.BLOCKED
                and agent.runtime_state == "provisioning_required"
            ):
                raise AgentCapabilityConflictError(
                    "workspace readiness requires the exact provisioning blocker"
                )
            if isinstance(registered, AtomicAgentWorkspaceReadinessProvider):
                registered.stage_atomic_readiness(
                    repositories=self.repositories,
                    proof=proof,
                )
            ready = AgentWorkspaceGenerationReservation.create(
                reservation_id=reservation.reservation_id,
                session_id=reservation.session_id,
                agent_member_id=reservation.agent_member_id,
                agent_id=reservation.agent_id,
                workspace_generation=reservation.workspace_generation,
                status=AgentWorkspaceGenerationStatus.READY,
                state_version=reservation.state_version + 1,
                reserved_at=reservation.reserved_at,
                updated_at=proof.observed_at,
                readiness_owner_kind=(
                    AgentWorkspaceReadinessOwnerKind.WORKSPACE_PROVISIONER
                ),
                readiness_owner_ref=proof.provider_id,
                readiness_ref=proof.readiness_ref,
                readiness_digest=proof.readiness_digest,
                ready_at=proof.observed_at,
            )
            active = AgentCapabilityLease.create(
                lease_id=lease.lease_id,
                session_id=lease.session_id,
                agent_member_id=lease.agent_member_id,
                agent_id=lease.agent_id,
                workspace_generation=lease.workspace_generation,
                profile=lease.profile,
                capabilities=lease.capabilities,
                target_ids=lease.target_ids,
                policy_version=lease.policy_version,
                policy_digest=lease.policy_digest,
                parent_lease_id=lease.parent_lease_id,
                idempotency_key=lease.idempotency_key,
                status=AgentCapabilityLeaseStatus.ACTIVE,
                state_version=lease.state_version + 1,
                issued_at=lease.issued_at,
                updated_at=proof.observed_at,
                activated_at=proof.observed_at,
            )
            activated_event = self._event(
                lease=active,
                event_kind=AgentCapabilityLeaseEventKind.ACTIVATED,
                previous_status=AgentCapabilityLeaseStatus.PENDING_WORKSPACE,
                actor_ref=actor_ref,
            )
            activation_authority = AgentCapabilityReadinessActivationAuthority(
                reservation_id=reservation.reservation_id,
                lease_id=lease.lease_id,
                session_id=lease.session_id,
                agent_member_id=lease.agent_member_id,
                agent_id=lease.agent_id,
                workspace_generation=lease.workspace_generation,
                provider_id=proof.provider_id,
                readiness_ref=proof.readiness_ref,
                readiness_digest=proof.readiness_digest,
                activated_at=proof.observed_at,
                reservation_previous_state_version=reservation.state_version,
                lease_previous_state_version=lease.state_version,
                reservation_canonical_digest=ready.canonical_digest,
                lease_canonical_digest=active.canonical_digest,
                event_id=activated_event.event_id,
                event_digest=activated_event.event_digest,
                actor_ref=activated_event.actor_ref,
            )
            with self.repositories._agent_capability_readiness_activation(
                activation_authority
            ):
                self.repositories.agent_workspace_generation_reservations.update(
                    ready,
                    expected_state_version=reservation.state_version,
                )
                self.repositories.agent_capability_leases.update(
                    active,
                    expected_state_version=lease.state_version,
                )
                self.repositories.agent_capability_lease_events.append(
                    activated_event
                )
                now = utc_now_iso()
                self.repositories.agents.save(
                    replace(
                        agent,
                        status=AgentMemberStatus.IDLE,
                        runtime_state="idle",
                        updated_at=now,
                        idle_since=now,
                    )
                )
            return AgentCapabilityIssuance(ready, active)

    def revoke_exact(
        self,
        lease_id: str,
        *,
        actor_ref: str,
    ) -> tuple[AgentCapabilityLease, ...]:
        return self._revoke_selected(
            self._require_lease(lease_id),
            scope=AgentCapabilityRevocationScope.EXACT,
            reason=AgentCapabilityRevocationReason.EXPLICIT,
            actor_ref=actor_ref,
        )

    def revoke_session(
        self,
        session_id: str,
        *,
        actor_ref: str,
    ) -> tuple[AgentCapabilityLease, ...]:
        with self.repositories.atomic(prefix="agent_capability_revoke_session"):
            return self._revoke_selected(
                *self.repositories.agent_capability_leases.list_by_session(session_id),
                scope=AgentCapabilityRevocationScope.SESSION,
                reason=AgentCapabilityRevocationReason.SESSION_ENDED,
                actor_ref=actor_ref,
                mark_provisioning_required=False,
            )

    def transition_session_terminal(
        self,
        updated_session: Session,
        *,
        actor_ref: str,
    ) -> Session:
        if not updated_session.status.is_terminal:
            raise ValueError("updated_session must have a terminal status")
        with self.repositories.atomic(prefix="agent_capability_session_terminal"):
            current = self.repositories.sessions.get(updated_session.session_id)
            if current is None:
                raise AgentCapabilityAdmissionRejectedError(
                    f"session {updated_session.session_id!r} does not exist"
                )
            if current.status.is_terminal:
                if current == updated_session:
                    return current
                raise AgentCapabilityConflictError(
                    "terminal session transition replay changes canonical facts"
                )
            if (
                current.project_id != updated_session.project_id
                or current.title != updated_session.title
                or current.objective != updated_session.objective
                or current.created_at != updated_session.created_at
                or current.repository_binding_status
                is not updated_session.repository_binding_status
            ):
                raise AgentCapabilityConflictError(
                    "terminal session transition changes immutable session facts"
                )
            self._revoke_selected(
                *self.repositories.agent_capability_leases.list_by_session(
                    updated_session.session_id
                ),
                scope=AgentCapabilityRevocationScope.SESSION,
                reason=AgentCapabilityRevocationReason.SESSION_ENDED,
                actor_ref=actor_ref,
                mark_provisioning_required=False,
            )
            self.repositories.sessions.save(updated_session)
            return updated_session

    def revoke_policy(
        self,
        *,
        policy_version: str,
        policy_digest: str,
        actor_ref: str,
        session_id: str | None = None,
    ) -> tuple[AgentCapabilityLease, ...]:
        with self.repositories.atomic(prefix="agent_capability_revoke_policy"):
            connection = self.repositories.tasks.connection
            if session_id is None:
                rows = connection.execute(
                    """
                    SELECT lease_id
                    FROM agent_capability_lease_records
                    WHERE policy_version = ? AND policy_digest = ?
                    ORDER BY issued_at, lease_id
                    """,
                    (policy_version, policy_digest),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT lease_id
                    FROM agent_capability_lease_records
                    WHERE session_id = ?
                      AND policy_version = ?
                      AND policy_digest = ?
                    ORDER BY issued_at, lease_id
                    """,
                    (session_id, policy_version, policy_digest),
                ).fetchall()
            leases = tuple(
                self._require_lease(str(row["lease_id"])) for row in rows
            )
            return self._revoke_selected(
                *leases,
                scope=AgentCapabilityRevocationScope.POLICY,
                reason=AgentCapabilityRevocationReason.POLICY_INVALIDATED,
                actor_ref=actor_ref,
            )

    def revoke_derived_subtree(
        self,
        root_lease_id: str,
        *,
        actor_ref: str,
    ) -> tuple[AgentCapabilityLease, ...]:
        with self.repositories.atomic(prefix="agent_capability_revoke_subtree"):
            ordered: list[AgentCapabilityLease] = []
            queue = [self._require_lease(root_lease_id)]
            seen: set[str] = set()
            while queue:
                lease = queue.pop(0)
                if lease.lease_id in seen:
                    continue
                seen.add(lease.lease_id)
                ordered.append(lease)
                queue.extend(
                    self.repositories.agent_capability_leases.list_direct_children(
                        lease.lease_id
                    )
                )
            return self._revoke_selected(
                *ordered,
                scope=AgentCapabilityRevocationScope.DERIVED_SUBTREE,
                reason=AgentCapabilityRevocationReason.OPERATOR_SUBTREE,
                actor_ref=actor_ref,
            )

    def replace_workspace_generation(
        self,
        lease_id: str,
        *,
        idempotency_key: str,
        actor_ref: str,
    ) -> AgentCapabilityIssuance:
        with self.repositories.atomic(prefix="agent_workspace_replace"):
            lease = self._require_lease(lease_id)
            if lease.status is AgentCapabilityLeaseStatus.REVOKED:
                raise AgentCapabilityRevokedError(
                    "revoked generation cannot be replaced again"
                )
            reservation = self.repositories.agent_workspace_generation_reservations.get_by_generation(
                session_id=lease.session_id,
                agent_member_id=lease.agent_member_id,
                workspace_generation=lease.workspace_generation,
            )
            if reservation is None or reservation.status is AgentWorkspaceGenerationStatus.REPLACED:
                raise AgentCapabilityConflictError(
                    "capability lease does not own a current generation"
                )
            self._revoke_selected(
                lease,
                scope=AgentCapabilityRevocationScope.WORKSPACE_GENERATION,
                reason=AgentCapabilityRevocationReason.WORKSPACE_REPLACED,
                actor_ref=actor_ref,
            )
            next_generation = lease.workspace_generation + 1
            replacement_time = utc_now_iso()
            replaced_reservation = AgentWorkspaceGenerationReservation.create(
                reservation_id=reservation.reservation_id,
                session_id=reservation.session_id,
                agent_member_id=reservation.agent_member_id,
                agent_id=reservation.agent_id,
                workspace_generation=reservation.workspace_generation,
                status=AgentWorkspaceGenerationStatus.REPLACED,
                state_version=reservation.state_version + 1,
                reserved_at=reservation.reserved_at,
                updated_at=replacement_time,
                readiness_owner_kind=reservation.readiness_owner_kind,
                readiness_owner_ref=reservation.readiness_owner_ref,
                readiness_ref=reservation.readiness_ref,
                readiness_digest=reservation.readiness_digest,
                ready_at=reservation.ready_at,
                replaced_by_generation=next_generation,
                replaced_at=replacement_time,
            )
            self.repositories.agent_workspace_generation_reservations.update(
                replaced_reservation,
                expected_state_version=reservation.state_version,
            )
            return self.reserve_and_issue(
                session_id=lease.session_id,
                agent_id=lease.agent_id,
                idempotency_key=idempotency_key,
                actor_ref=actor_ref,
                parent_lease_id=lease.parent_lease_id,
                workspace_generation=next_generation,
            )

    def retire_agent(
        self,
        *,
        session_id: str,
        agent_id: str,
        shutdown_request_ref: str,
        provider_id: str,
        actor_ref: str,
    ) -> AgentRetirementRecord:
        provider = self.retirement_cleanup_providers.get(provider_id)
        if provider is None or provider.provider_id != provider_id:
            raise AgentRetirementCleanupProviderUnavailableError(
                f"retirement cleanup provider {provider_id!r} is not registered"
            )
        request = self.request_agent_retirement(
            session_id=session_id,
            agent_id=agent_id,
            shutdown_request_ref=shutdown_request_ref,
            provider_id=provider_id,
            actor_ref=actor_ref,
        )
        proof_record = self.repositories.agent_retirement_cleanup_proofs.get_by_request(
            request.request_id
        )
        if proof_record is None:
            proof_record = self.record_retirement_cleanup_proof(
                request_id=request.request_id,
            )
        return self.complete_agent_retirement(
            request_id=request.request_id,
            cleanup_proof_id=proof_record.proof_id,
        )

    def request_agent_retirement(
        self,
        *,
        session_id: str,
        agent_id: str,
        shutdown_request_ref: str,
        provider_id: str,
        actor_ref: str,
    ) -> AgentRetirementRequest:
        provider = self.retirement_cleanup_providers.get(provider_id)
        if provider is None or provider.provider_id != provider_id:
            raise AgentRetirementCleanupProviderUnavailableError(
                f"retirement cleanup provider {provider_id!r} is not registered"
            )
        with self.repositories.atomic(prefix="agent_retirement_request"):
            agent = self._require_agent(session_id=session_id, agent_id=agent_id)
            member_id = self._require_member_id(agent)
            existing = self.repositories.agent_retirement_requests.get_by_agent(
                session_id=session_id,
                agent_member_id=member_id,
            )
            if existing is not None:
                if (
                    existing.agent_id,
                    existing.shutdown_request_ref,
                    existing.cleanup_provider_id,
                    existing.actor_ref,
                ) != (
                    agent_id,
                    shutdown_request_ref,
                    provider_id,
                    actor_ref,
                ):
                    raise AgentCapabilityConflictError(
                        "agent retirement request replay changes immutable facts"
                    )
                return existing
            retirement = self.repositories.agent_retirements.get_by_agent(
                session_id=session_id,
                agent_member_id=member_id,
            )
            if retirement is not None:
                raise AgentCapabilityRetiredError(
                    f"agent member {member_id!r} is already retired"
                )
            reservation = (
                self.repositories.agent_workspace_generation_reservations.get_current(
                    session_id=session_id,
                    agent_member_id=member_id,
                )
            )
            if reservation is None or reservation.agent_id != agent_id:
                raise AgentCapabilityProvisioningRequiredError(
                    "agent retirement request requires a current workspace generation"
                )
            lease = self.repositories.agent_capability_leases.get_by_generation(
                session_id=session_id,
                agent_member_id=member_id,
                workspace_generation=reservation.workspace_generation,
            )
            if lease is None or lease.agent_id != agent_id:
                raise AgentCapabilityProvisioningRequiredError(
                    "agent retirement request requires the exact current capability lease"
                )
            if lease.status is AgentCapabilityLeaseStatus.REVOKED:
                raise AgentCapabilityRevokedError(
                    "revoked capability lease cannot open a retirement request"
                )
            request = AgentRetirementRequest.create(
                request_id=f"agent_retirement_request_{uuid4().hex}",
                session_id=session_id,
                agent_member_id=member_id,
                agent_id=agent_id,
                workspace_generation=reservation.workspace_generation,
                capability_lease_id=lease.lease_id,
                shutdown_request_ref=shutdown_request_ref,
                cleanup_provider_id=provider_id,
                actor_ref=actor_ref,
                requested_at=utc_now_iso(),
            )
            authority = AgentRetirementLifecycleAuthority(
                phase="request",
                record_id=request.request_id,
                record_digest=request.canonical_digest,
                request_id=request.request_id,
                request_digest=request.canonical_digest,
                session_id=request.session_id,
                agent_member_id=request.agent_member_id,
                agent_id=request.agent_id,
                workspace_generation=request.workspace_generation,
                capability_lease_id=request.capability_lease_id,
            )
            with self.repositories._agent_retirement_lifecycle(authority):
                return self.repositories.agent_retirement_requests.add(request)

    def record_retirement_cleanup_proof(
        self,
        *,
        request_id: str,
    ) -> AgentRetirementCleanupProofRecord:
        with self.repositories.atomic(prefix="agent_retirement_cleanup_preflight"):
            request = self.repositories.agent_retirement_requests.get(request_id)
            if request is None:
                raise AgentCapabilityAdmissionRejectedError(
                    f"retirement request {request_id!r} does not exist"
                )
            existing = (
                self.repositories.agent_retirement_cleanup_proofs.get_by_request(
                    request.request_id
                )
            )
            if existing is not None:
                return existing
            agent = self._require_agent(
                session_id=request.session_id,
                agent_id=request.agent_id,
            )
            self._assert_retirement_request_owner(request=request, agent=agent)
            self._assert_no_claimed_runtime_signal(
                request=request,
                phase="cleanup provider admission",
            )
            provider = self.retirement_cleanup_providers.get(
                request.cleanup_provider_id
            )
            if provider is None or provider.provider_id != request.cleanup_provider_id:
                raise AgentRetirementCleanupProviderUnavailableError(
                    "retirement cleanup provider from the durable request is not "
                    "registered"
                )
        proof = provider.verify_cleanup(request=request)
        with self.repositories.atomic(prefix="agent_retirement_cleanup_proof"):
            request = self.repositories.agent_retirement_requests.get(request_id)
            if request is None:
                raise AgentCapabilityAdmissionRejectedError(
                    f"retirement request {request_id!r} does not exist"
                )
            agent = self._require_agent(
                session_id=request.session_id,
                agent_id=request.agent_id,
            )
            self._assert_retirement_request_owner(request=request, agent=agent)
            self._assert_retirement_cleanup_proof(request=request, proof=proof)
            self._assert_no_claimed_runtime_signal(
                request=request,
                phase="cleanup proof persistence",
            )
            existing = (
                self.repositories.agent_retirement_cleanup_proofs.get_by_request(
                    request.request_id
                )
            )
            candidate = AgentRetirementCleanupProofRecord.create(
                proof_id=(
                    existing.proof_id
                    if existing is not None
                    else f"agent_retirement_cleanup_proof_{uuid4().hex}"
                ),
                retirement_request_id=request.request_id,
                retirement_request_digest=request.canonical_digest,
                session_id=request.session_id,
                agent_member_id=request.agent_member_id,
                agent_id=request.agent_id,
                workspace_generation=request.workspace_generation,
                capability_lease_id=request.capability_lease_id,
                shutdown_request_ref=request.shutdown_request_ref,
                provider_id=proof.provider_id,
                cleanup_proof_digest=proof.cleanup_proof_digest,
                reason=proof.reason,
                observed_at=proof.observed_at,
            )
            if existing is not None:
                if existing.canonical_digest != candidate.canonical_digest:
                    raise AgentCapabilityConflictError(
                        "agent retirement cleanup proof replay changes immutable facts"
                    )
                return existing
            authority = AgentRetirementLifecycleAuthority(
                phase="cleanup_proof",
                record_id=candidate.proof_id,
                record_digest=candidate.canonical_digest,
                request_id=request.request_id,
                request_digest=request.canonical_digest,
                session_id=request.session_id,
                agent_member_id=request.agent_member_id,
                agent_id=request.agent_id,
                workspace_generation=request.workspace_generation,
                capability_lease_id=request.capability_lease_id,
            )
            with self.repositories._agent_retirement_lifecycle(authority):
                return self.repositories.agent_retirement_cleanup_proofs.add(
                    candidate
                )

    def complete_agent_retirement(
        self,
        *,
        request_id: str,
        cleanup_proof_id: str,
    ) -> AgentRetirementRecord:
        with self.repositories.atomic(prefix="agent_retirement_finalize"):
            request = self.repositories.agent_retirement_requests.get(request_id)
            if request is None:
                raise AgentCapabilityAdmissionRejectedError(
                    f"retirement request {request_id!r} does not exist"
                )
            proof = self.repositories.agent_retirement_cleanup_proofs.get(
                cleanup_proof_id
            )
            if proof is None:
                raise AgentCapabilityAdmissionRejectedError(
                    f"retirement cleanup proof {cleanup_proof_id!r} does not exist"
                )
            agent = self._require_agent(
                session_id=request.session_id,
                agent_id=request.agent_id,
            )
            self._assert_retirement_request_owner(request=request, agent=agent)
            self._assert_persisted_retirement_cleanup_proof(
                request=request,
                proof=proof,
            )
            existing = self.repositories.agent_retirements.get_by_agent(
                session_id=request.session_id,
                agent_member_id=request.agent_member_id,
            )
            timestamp = existing.retired_at if existing is not None else utc_now_iso()
            candidate = AgentRetirementRecord.create(
                retirement_id=(
                    existing.retirement_id
                    if existing is not None
                    else f"agent_retirement_{uuid4().hex}"
                ),
                session_id=request.session_id,
                agent_member_id=request.agent_member_id,
                agent_id=request.agent_id,
                retirement_request_id=request.request_id,
                retirement_request_digest=request.canonical_digest,
                workspace_generation=request.workspace_generation,
                capability_lease_id=request.capability_lease_id,
                shutdown_request_ref=request.shutdown_request_ref,
                cleanup_proof_id=proof.proof_id,
                cleanup_proof_digest=proof.cleanup_proof_digest,
                cleanup_proof_record_digest=proof.canonical_digest,
                actor_ref=request.actor_ref,
                reason=proof.reason,
                retired_at=timestamp,
            )
            if existing is not None:
                if existing.canonical_digest != candidate.canonical_digest:
                    raise AgentCapabilityConflictError(
                        "agent retirement replay changes immutable facts"
                    )
                return existing
            current_reservation = (
                self.repositories.agent_workspace_generation_reservations.get_current(
                    session_id=request.session_id,
                    agent_member_id=request.agent_member_id,
                )
            )
            lease = self.repositories.agent_capability_leases.get(
                request.capability_lease_id
            )
            if (
                current_reservation is None
                or current_reservation.agent_id != request.agent_id
                or current_reservation.workspace_generation
                != request.workspace_generation
                or lease is None
                or lease.session_id != request.session_id
                or lease.agent_member_id != request.agent_member_id
                or lease.agent_id != request.agent_id
                or lease.workspace_generation != request.workspace_generation
            ):
                raise AgentCapabilityConflictError(
                    "retirement request owner generation or lease drifted"
                )
            self._assert_no_claimed_runtime_signal(
                request=request,
                phase="retirement finalization",
            )
            authority = AgentRetirementLifecycleAuthority(
                phase="final",
                record_id=candidate.retirement_id,
                record_digest=candidate.canonical_digest,
                request_id=request.request_id,
                request_digest=request.canonical_digest,
                session_id=request.session_id,
                agent_member_id=request.agent_member_id,
                agent_id=request.agent_id,
                workspace_generation=request.workspace_generation,
                capability_lease_id=request.capability_lease_id,
            )
            with self.repositories._agent_retirement_lifecycle(authority):
                self._revoke_selected(
                    *self.repositories.agent_capability_leases.list_by_agent(
                        session_id=request.session_id,
                        agent_member_id=request.agent_member_id,
                    ),
                    scope=AgentCapabilityRevocationScope.AGENT,
                    reason=AgentCapabilityRevocationReason.AGENT_RETIRED,
                    actor_ref=request.actor_ref,
                    revoked_at=timestamp,
                    mark_provisioning_required=False,
                )
                self.repositories.agent_retirements.add(candidate)
                self.repositories.agents.save(
                    replace(
                        agent,
                        status=AgentMemberStatus.SHUTDOWN,
                        runtime_state="retired",
                        shutdown_requested_at=(
                            agent.shutdown_requested_at or request.requested_at
                        ),
                        updated_at=timestamp,
                    )
                )
            return candidate

    @staticmethod
    def _assert_retirement_request_owner(
        *,
        request: AgentRetirementRequest,
        agent: AgentMember,
    ) -> None:
        if (
            agent.member_id is None
            or request.session_id != agent.session_id
            or request.agent_member_id != agent.member_id
            or request.agent_id != agent.agent_id
        ):
            raise AgentCapabilityAdmissionRejectedError(
                "retirement request does not match the exact canonical agent owner"
            )

    def _assert_no_claimed_runtime_signal(
        self,
        *,
        request: AgentRetirementRequest,
        phase: str,
    ) -> None:
        claimed_signal = self.repositories.tasks.connection.execute(
            """
            SELECT signal_id
            FROM agent_runtime_signals
            WHERE session_id = ? AND agent_id = ? AND status = 'claimed'
            ORDER BY created_at, rowid
            LIMIT 1
            """,
            (request.session_id, request.agent_id),
        ).fetchone()
        if claimed_signal is not None:
            raise AgentRetirementActiveClaimError(
                f"{phase} requires explicit settlement of claimed runtime "
                f"signal {claimed_signal['signal_id']!r}"
            )

    @staticmethod
    def _assert_retirement_cleanup_proof(
        *,
        request: AgentRetirementRequest,
        proof: AgentRetirementCleanupProof,
    ) -> None:
        if (
            proof.provider_id != request.cleanup_provider_id
            or proof.retirement_request_id != request.request_id
            or proof.retirement_request_digest != request.canonical_digest
            or proof.session_id != request.session_id
            or proof.agent_member_id != request.agent_member_id
            or proof.agent_id != request.agent_id
            or proof.workspace_generation != request.workspace_generation
            or proof.capability_lease_id != request.capability_lease_id
            or proof.shutdown_request_ref != request.shutdown_request_ref
        ):
            raise AgentCapabilityAdmissionRejectedError(
                "retirement cleanup proof does not match the exact agent request"
            )

    @staticmethod
    def _assert_persisted_retirement_cleanup_proof(
        *,
        request: AgentRetirementRequest,
        proof: AgentRetirementCleanupProofRecord,
    ) -> None:
        if (
            proof.retirement_request_id != request.request_id
            or proof.retirement_request_digest != request.canonical_digest
            or proof.session_id != request.session_id
            or proof.agent_member_id != request.agent_member_id
            or proof.agent_id != request.agent_id
            or proof.workspace_generation != request.workspace_generation
            or proof.capability_lease_id != request.capability_lease_id
            or proof.shutdown_request_ref != request.shutdown_request_ref
            or proof.provider_id != request.cleanup_provider_id
        ):
            raise AgentCapabilityAdmissionRejectedError(
                "persisted retirement cleanup proof does not match exact request"
            )

    def _revoke_selected(
        self,
        *leases: AgentCapabilityLease,
        scope: AgentCapabilityRevocationScope,
        reason: AgentCapabilityRevocationReason,
        actor_ref: str,
        revoked_at: str | None = None,
        mark_provisioning_required: bool = True,
    ) -> tuple[AgentCapabilityLease, ...]:
        if not actor_ref:
            raise ValueError("actor_ref must not be empty")
        with self.repositories.atomic(prefix="agent_capability_revoke"):
            timestamp = utc_now_iso() if revoked_at is None else revoked_at
            revoked: list[AgentCapabilityLease] = []
            affected_agents: set[tuple[str, str]] = set()
            for candidate in leases:
                lease = self._require_lease(candidate.lease_id)
                if lease.status is AgentCapabilityLeaseStatus.REVOKED:
                    continue
                connection = self.repositories.tasks.connection
                connection.execute(
                    """
                    UPDATE repository_credential_issuance_records
                    SET revoked_at = ?
                    WHERE capability_lease_id = ? AND revoked_at IS NULL
                    """,
                    (timestamp, lease.lease_id),
                )
                connection.execute(
                    """
                    UPDATE repository_private_namespace_holds
                    SET released_at = ?
                    WHERE hold_kind = 'active_capability_lease'
                      AND owner_ref = ?
                      AND released_at IS NULL
                    """,
                    (timestamp, lease.lease_id),
                )
                updated = AgentCapabilityLease.create(
                    lease_id=lease.lease_id,
                    session_id=lease.session_id,
                    agent_member_id=lease.agent_member_id,
                    agent_id=lease.agent_id,
                    workspace_generation=lease.workspace_generation,
                    profile=lease.profile,
                    capabilities=lease.capabilities,
                    target_ids=lease.target_ids,
                    policy_version=lease.policy_version,
                    policy_digest=lease.policy_digest,
                    parent_lease_id=lease.parent_lease_id,
                    idempotency_key=lease.idempotency_key,
                    status=AgentCapabilityLeaseStatus.REVOKED,
                    state_version=lease.state_version + 1,
                    issued_at=lease.issued_at,
                    updated_at=timestamp,
                    activated_at=lease.activated_at,
                    revoked_at=timestamp,
                    revocation_scope=scope,
                    revocation_reason=reason,
                )
                self.repositories.agent_capability_leases.update(
                    updated,
                    expected_state_version=lease.state_version,
                )
                self.repositories.agent_capability_lease_events.append(
                    self._event(
                        lease=updated,
                        event_kind=AgentCapabilityLeaseEventKind.REVOKED,
                        previous_status=lease.status,
                        actor_ref=actor_ref,
                    )
                )
                revoked.append(updated)
                affected_agents.add((lease.session_id, lease.agent_id))
            if mark_provisioning_required:
                for session_id, agent_id in affected_agents:
                    agent = self.repositories.agents.get(session_id, agent_id)
                    if agent is not None and agent.member_id is not None:
                        active = self.repositories.agent_capability_leases.get_active(
                            session_id=session_id,
                            agent_member_id=agent.member_id,
                        )
                        if active is None:
                            self._mark_provisioning_required(agent)
            return tuple(revoked)

    def _assert_parent_authority(
        self,
        *,
        agent: AgentMember,
        parent_lease_id: str | None,
        child_profile: AgentCapabilityProfile,
    ) -> None:
        if agent.parent_agent_id is None:
            if parent_lease_id is not None:
                raise AgentCapabilityConflictError(
                    "root agent issuance cannot name parent provenance"
                )
            return
        if parent_lease_id is None:
            raise AgentCapabilityAdmissionRejectedError(
                "child agent issuance requires exact parent lease provenance"
            )
        parent_claims = self.validator.require_current_agent(
            session_id=agent.session_id,
            agent_id=agent.parent_agent_id,
            expected_lease_id=parent_lease_id,
            service_id="agent_delegation",
            protocol="derive_child_lease",
            operation_class="delegation",
        )
        parent_agent = self._require_agent(
            session_id=agent.session_id,
            agent_id=agent.parent_agent_id,
        )
        if parent_claims.lease.lease_id != parent_lease_id:
            raise AgentCapabilityAdmissionRejectedError(
                "child parent capability lease identity changed"
            )
        self.policy.assert_child_profile_allowed(
            parent_role=parent_agent.role,
            child_profile=child_profile,
        )

    def _assert_requested_policy(
        self,
        *,
        profile: AgentCapabilityProfile,
        capabilities: tuple[AgentCapability, ...],
        target_ids: tuple[str, ...],
        requested_profile: AgentCapabilityProfile | None,
        requested_capabilities: tuple[AgentCapability, ...] | None,
        requested_target_ids: tuple[str, ...] | None,
        requested_policy_version: str | None,
        requested_policy_digest: str | None,
    ) -> None:
        if requested_profile is not None and requested_profile is not profile:
            raise AgentCapabilityAdmissionRejectedError(
                "requested capability profile does not match agent role"
            )
        if requested_capabilities is not None and requested_capabilities != capabilities:
            raise AgentCapabilityAdmissionRejectedError(
                "requested capabilities do not equal the closed profile"
            )
        if requested_target_ids is not None and requested_target_ids != target_ids:
            raise AgentCapabilityAdmissionRejectedError(
                "requested target scope does not equal the closed profile"
            )
        if (
            requested_policy_version is not None
            and requested_policy_version != self.policy.policy_version
        ) or (
            requested_policy_digest is not None
            and requested_policy_digest != self.policy.policy_digest
        ):
            raise AgentCapabilityPolicyDriftError(
                "requested capability policy does not match current policy"
            )

    def _assert_lease_matches_current_policy(
        self,
        *,
        lease: AgentCapabilityLease,
        agent: AgentMember,
    ) -> None:
        expected_profile = self.policy.profile_for_role(agent.role)
        if (
            lease.profile is not expected_profile
            or lease.capabilities != capabilities_for_profile(expected_profile)
            or lease.target_ids != self.policy.targets_for_profile(expected_profile)
            or lease.policy_version != self.policy.policy_version
            or lease.policy_digest != self.policy.policy_digest
        ):
            raise AgentCapabilityPolicyDriftError(
                "pending capability lease no longer matches current policy"
            )
        self.validator._validate_parent_provenance(agent, lease)

    def _assert_replayed_issuance(
        self,
        *,
        lease: AgentCapabilityLease,
        reservation: AgentWorkspaceGenerationReservation,
        agent: AgentMember,
        workspace_generation: int | None,
        profile: AgentCapabilityProfile,
        capabilities: tuple[AgentCapability, ...],
        target_ids: tuple[str, ...],
        parent_lease_id: str | None,
    ) -> None:
        expected_generation = (
            lease.workspace_generation
            if workspace_generation is None
            else workspace_generation
        )
        if (
            lease.session_id != agent.session_id
            or lease.agent_member_id != self._require_member_id(agent)
            or lease.agent_id != agent.agent_id
            or lease.workspace_generation != expected_generation
            or reservation.workspace_generation != expected_generation
            or lease.profile is not profile
            or lease.capabilities != capabilities
            or lease.target_ids != target_ids
            or lease.policy_version != self.policy.policy_version
            or lease.policy_digest != self.policy.policy_digest
            or lease.parent_lease_id != parent_lease_id
        ):
            raise AgentCapabilityConflictError(
                "capability issuance idempotency identity drifted"
            )

    def _assert_readiness_proof(
        self,
        reservation: AgentWorkspaceGenerationReservation,
        proof: AgentWorkspaceReadinessProof,
    ) -> None:
        if (
            proof.reservation_id != reservation.reservation_id
            or proof.reservation_fingerprint != reservation.immutable_fingerprint
            or proof.session_id != reservation.session_id
            or proof.agent_member_id != reservation.agent_member_id
            or proof.agent_id != reservation.agent_id
            or proof.workspace_generation != reservation.workspace_generation
        ):
            raise AgentCapabilityAdmissionRejectedError(
                "workspace readiness proof does not match the exact reservation"
            )

    def _event(
        self,
        *,
        lease: AgentCapabilityLease,
        event_kind: AgentCapabilityLeaseEventKind,
        previous_status: AgentCapabilityLeaseStatus | None,
        actor_ref: str,
    ) -> AgentCapabilityLeaseLifecycleEvent:
        return AgentCapabilityLeaseLifecycleEvent.create(
            event_id=f"agent_capability_event_{uuid4().hex}",
            lease_id=lease.lease_id,
            session_id=lease.session_id,
            agent_member_id=lease.agent_member_id,
            agent_id=lease.agent_id,
            workspace_generation=lease.workspace_generation,
            event_kind=event_kind,
            previous_status=previous_status,
            status=lease.status,
            state_version=lease.state_version,
            actor_ref=actor_ref,
            occurred_at=lease.updated_at,
            revocation_scope=lease.revocation_scope,
            revocation_reason=lease.revocation_reason,
        )

    def _mark_provisioning_required(self, agent: AgentMember) -> AgentMember:
        if agent.status in {
            AgentMemberStatus.COMPLETED,
            AgentMemberStatus.FAILED,
            AgentMemberStatus.STOPPED,
            AgentMemberStatus.SHUTDOWN,
        }:
            return agent
        if (
            agent.status is AgentMemberStatus.BLOCKED
            and agent.runtime_state == "provisioning_required"
        ):
            return agent
        updated = replace(
            agent,
            status=AgentMemberStatus.BLOCKED,
            runtime_state="provisioning_required",
            updated_at=utc_now_iso(),
            idle_since=None,
        )
        self.repositories.agents.save(updated)
        return updated

    def _require_agent(self, *, session_id: str, agent_id: str) -> AgentMember:
        agent = self.repositories.agents.get(session_id, agent_id)
        if agent is None:
            raise AgentCapabilityAdmissionRejectedError(
                f"agent {agent_id!r} does not exist in session {session_id!r}"
            )
        return agent

    @staticmethod
    def _require_member_id(agent: AgentMember) -> str:
        if agent.member_id is None:
            raise AgentCapabilityAdmissionRejectedError(
                f"agent {agent.agent_id!r} has no internal member identity"
            )
        return agent.member_id

    def _require_lease(self, lease_id: str) -> AgentCapabilityLease:
        lease = self.repositories.agent_capability_leases.get(lease_id)
        if lease is None:
            raise AgentCapabilityProvisioningRequiredError(
                f"capability lease {lease_id!r} does not exist"
            )
        return lease


__all__ = [
    "AGENT_CAPABILITY_ADMISSION_SCHEMA_VERSION",
    "AGENT_CAPABILITY_POLICY_SCHEMA_VERSION",
    "ActiveAgentCapabilityLeaseClaims",
    "ActiveAgentCapabilityLeaseValidator",
    "AgentCapabilityAdmissionRejectedError",
    "AgentCapabilityAdmissionRequest",
    "AgentCapabilityConflictError",
    "AgentCapabilityCredentialProviderUnavailableError",
    "AgentCapabilityError",
    "AgentCapabilityIssuance",
    "AgentCapabilityLeaseService",
    "AgentCapabilityPolicy",
    "AgentCapabilityPolicyDriftError",
    "AgentCapabilityProvisioningRequiredError",
    "AgentCapabilityRetiredError",
    "AgentCapabilityRevokedError",
    "AgentRetirementActiveClaimError",
    "AgentRetirementCleanupProof",
    "AgentRetirementCleanupProvider",
    "AgentRetirementCleanupProviderUnavailableError",
    "AgentRetirementRequestedError",
    "AgentScopedCredentialIssuer",
    "AgentWorkspaceReadinessProof",
    "AgentWorkspaceReadinessProvider",
    "AgentWorkspaceReadinessProviderUnavailableError",
    "DEFAULT_AGENT_CAPABILITY_POLICY",
    "UnavailableRemoteAgentCredentialIssuer",
]
