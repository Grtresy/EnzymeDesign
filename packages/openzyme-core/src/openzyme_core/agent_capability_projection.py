from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any
from typing import TYPE_CHECKING

from openzyme_domain import AgentCapabilityLease
from openzyme_domain import AgentCapabilityLeaseStatus
from openzyme_domain import AgentMember
from openzyme_domain import AgentRetirementRecord
from openzyme_domain import AgentRetirementRequest
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentWorkspaceGenerationReservation
from openzyme_domain import AgentWorkspaceGenerationStatus
from openzyme_domain import capabilities_for_profile

from .agent_capability_service import AgentCapabilityPolicy
from .agent_capability_service import DEFAULT_AGENT_CAPABILITY_POLICY
from .repositories import CoreRepositories

if TYPE_CHECKING:
    from .agent_runtime import AgentRuntimeOutcome


AGENT_CAPABILITY_PUBLIC_PROJECTION_SCHEMA_VERSION = (
    "agent_capability_public_projection@1"
)

_SAFE_TARGET_ID_PATTERN = re.compile(
    r"[A-Za-z][A-Za-z0-9_-]{0,63}:[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
)
_PUBLIC_SAFE_TARGET_ID_REGISTRY = frozenset(
    {
        "hpc:primary",
        "network:deployment",
        "repository:session-pinned",
    }
)


class AgentCapabilityPublicProjectionError(RuntimeError):
    error_code = "agent_capability_projection_rejected"


class AgentCapabilityPublicBlockerCode(StrEnum):
    PROVISIONING_REQUIRED = "provisioning_required"
    REVOKED = "agent_capability_revoked"
    RETIRED = "agent_retired"
    RETIREMENT_REQUESTED = "agent_retirement_requested"
    ADMISSION_REJECTED = "agent_capability_admission_rejected"
    CREDENTIAL_REJECTED = "repository_credential_rejected"
    POLICY_DRIFT = "agent_capability_policy_drift"


def _safe_target_ids(
    lease: AgentCapabilityLease | None,
    *,
    policy_drifted: bool,
) -> list[str]:
    if lease is None:
        return []
    target_ids = list(lease.target_ids)
    if any(
        _SAFE_TARGET_ID_PATTERN.fullmatch(target_id) is None for target_id in target_ids
    ):
        raise AgentCapabilityPublicProjectionError(
            "capability target identity is not safe for public projection"
        )
    if policy_drifted:
        return []
    if any(
        target_id not in _PUBLIC_SAFE_TARGET_ID_REGISTRY for target_id in target_ids
    ):
        raise AgentCapabilityPublicProjectionError(
            "capability target identity is not safe for public projection"
        )
    return target_ids


def _reservation_status(
    reservation: AgentWorkspaceGenerationReservation | None,
) -> tuple[str, str]:
    if reservation is None:
        return "missing", "missing"
    if reservation.status is AgentWorkspaceGenerationStatus.RESERVED:
        return reservation.status.value, "pending"
    if reservation.status is AgentWorkspaceGenerationStatus.READY:
        return reservation.status.value, "verified"
    return reservation.status.value, "replaced"


def _identity_mismatched(
    *,
    agent: AgentMember,
    reservation: AgentWorkspaceGenerationReservation | None,
    lease: AgentCapabilityLease | None,
    parent_lease: AgentCapabilityLease | None,
    retirement_request: AgentRetirementRequest | None,
    retirement: AgentRetirementRecord | None,
    policy: AgentCapabilityPolicy,
) -> bool:
    member_id = agent.member_id
    if reservation is not None and (
        member_id is None
        or reservation.session_id != agent.session_id
        or reservation.agent_member_id != member_id
        or reservation.agent_id != agent.agent_id
    ):
        return True
    if lease is not None and (
        member_id is None
        or lease.session_id != agent.session_id
        or lease.agent_member_id != member_id
        or lease.agent_id != agent.agent_id
        or reservation is None
        or lease.workspace_generation != reservation.workspace_generation
    ):
        return True
    if retirement is not None and (
        member_id is None
        or retirement.session_id != agent.session_id
        or retirement.agent_member_id != member_id
        or retirement.agent_id != agent.agent_id
    ):
        return True
    if retirement_request is not None and (
        member_id is None
        or retirement_request.session_id != agent.session_id
        or retirement_request.agent_member_id != member_id
        or retirement_request.agent_id != agent.agent_id
        or lease is None
        or retirement_request.capability_lease_id != lease.lease_id
        or retirement_request.workspace_generation != lease.workspace_generation
    ):
        return True
    if lease is None:
        return False

    if lease.parent_lease_id is None:
        return agent.parent_agent_id is not None
    return (
        parent_lease is None
        or parent_lease.session_id != agent.session_id
        or parent_lease.agent_id != agent.parent_agent_id
    )


def _policy_drifted(
    *,
    agent: AgentMember,
    lease: AgentCapabilityLease | None,
    policy: AgentCapabilityPolicy,
) -> bool:
    if lease is None:
        return False
    role_profiles = dict(policy.role_profiles)
    expected_profile = role_profiles.get(agent.role)
    if expected_profile is None:
        return True
    expected_targets = dict(policy.profile_targets)[expected_profile]
    return (
        lease.profile is not expected_profile
        or lease.capabilities != capabilities_for_profile(expected_profile)
        or lease.target_ids != expected_targets
        or any(
            target_id not in _PUBLIC_SAFE_TARGET_ID_REGISTRY
            for target_id in expected_targets
        )
        or lease.policy_version != policy.policy_version
        or lease.policy_digest != policy.policy_digest
    )


def project_agent_capability_for_public(
    *,
    agent: AgentMember,
    reservation: AgentWorkspaceGenerationReservation | None,
    lease: AgentCapabilityLease | None,
    parent_lease: AgentCapabilityLease | None,
    retirement_request: AgentRetirementRequest | None = None,
    retirement: AgentRetirementRecord | None,
    policy: AgentCapabilityPolicy = DEFAULT_AGENT_CAPABILITY_POLICY,
) -> dict[str, Any]:
    """Build the closed public capability view without projecting raw records."""

    reservation_status, readiness_status = _reservation_status(reservation)
    policy_drifted = _policy_drifted(agent=agent, lease=lease, policy=policy)
    target_ids = _safe_target_ids(lease, policy_drifted=policy_drifted)
    parent_agent_id = (
        parent_lease.agent_id if parent_lease is not None else agent.parent_agent_id
    )
    identity_mismatched = _identity_mismatched(
        agent=agent,
        reservation=reservation,
        lease=lease,
        parent_lease=parent_lease,
        retirement_request=retirement_request,
        retirement=retirement,
        policy=policy,
    )

    blocker: AgentCapabilityPublicBlockerCode | None
    if identity_mismatched:
        blocker = AgentCapabilityPublicBlockerCode.ADMISSION_REJECTED
    elif retirement is not None:
        blocker = AgentCapabilityPublicBlockerCode.RETIRED
    elif retirement_request is not None:
        blocker = AgentCapabilityPublicBlockerCode.RETIREMENT_REQUESTED
    elif lease is not None and lease.status is AgentCapabilityLeaseStatus.REVOKED:
        blocker = AgentCapabilityPublicBlockerCode.REVOKED
    elif policy_drifted:
        blocker = AgentCapabilityPublicBlockerCode.POLICY_DRIFT
    elif (
        reservation is None
        or lease is None
        or reservation.status is not AgentWorkspaceGenerationStatus.READY
        or lease.status is not AgentCapabilityLeaseStatus.ACTIVE
    ):
        blocker = AgentCapabilityPublicBlockerCode.PROVISIONING_REQUIRED
    else:
        blocker = None

    return {
        "schema_version": AGENT_CAPABILITY_PUBLIC_PROJECTION_SCHEMA_VERSION,
        "lease_id": None if lease is None else lease.lease_id,
        "agent_id": agent.agent_id,
        "workspace_generation": (
            reservation.workspace_generation
            if reservation is not None
            else (None if lease is None else lease.workspace_generation)
        ),
        "reservation_status": reservation_status,
        "readiness_status": readiness_status,
        "capabilities": (
            []
            if lease is None
            else [capability.value for capability in lease.capabilities]
        ),
        "target_scope": {
            "target_ids": target_ids,
            "digest": None if lease is None else lease.target_scope_digest,
        },
        "policy_digest": None if lease is None else lease.policy_digest,
        "parent_provenance": {
            "parent_lease_id": None if lease is None else lease.parent_lease_id,
            "parent_agent_id": parent_agent_id,
        },
        "lifecycle": {
            "status": "missing" if lease is None else lease.status.value,
            "activated_at": None if lease is None else lease.activated_at,
            "revoked_at": None if lease is None else lease.revoked_at,
            "revocation_scope": (
                None
                if lease is None or lease.revocation_scope is None
                else lease.revocation_scope.value
            ),
            "revocation_reason": (
                None
                if lease is None or lease.revocation_reason is None
                else lease.revocation_reason.value
            ),
        },
        "retirement": {
            "requested": retirement_request is not None,
            "retired": retirement is not None,
            "reason": None if retirement is None else retirement.reason.value,
            "retired_at": None if retirement is None else retirement.retired_at,
        },
        "runnable": blocker is None,
        "blocker_code": None if blocker is None else blocker.value,
    }


def _project_agent_member_for_public(
    agent: AgentMember,
    *,
    capability: dict[str, Any],
) -> dict[str, Any]:
    """Project the public agent fields from an explicit allowlist."""

    return {
        "agent_id": agent.agent_id,
        "lane_id": agent.lane_id,
        "task_id": agent.task_id,
        "name": agent.name,
        "role": agent.role,
        "status": agent.status.value,
        "parent_agent_id": agent.parent_agent_id,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
        "runtime_state": agent.runtime_state,
        "current_correlation_id": agent.current_correlation_id,
        "wakeup_reason": agent.wakeup_reason,
        "last_active_at": agent.last_active_at,
        "idle_since": agent.idle_since,
        "shutdown_requested_at": agent.shutdown_requested_at,
        "nickname": agent.nickname,
        "display_name": agent.display_name,
        "handle": agent.handle,
        "runnable": capability["runnable"],
        "blocker_code": capability["blocker_code"],
        "capability": capability,
    }


def project_agent_runtime_signal_for_public(
    signal: AgentRuntimeSignal,
) -> dict[str, Any]:
    """Project runtime-signal facts without lease tokens, fences, or worker refs."""

    return {
        "signal_id": signal.signal_id,
        "agent_id": signal.agent_id,
        "task_id": signal.task_id,
        "lane_id": signal.lane_id,
        "correlation_id": signal.correlation_id,
        "reason": signal.reason.value,
        "status": signal.status.value,
        "created_at": signal.created_at,
        "attempt_count": signal.attempt_count,
        "completed_at": signal.completed_at,
        "capability_lease_id": signal.capability_lease_id,
        "workspace_generation": signal.workspace_generation,
    }


@dataclass(slots=True)
class AgentCapabilityPublicProjector:
    repositories: CoreRepositories
    policy: AgentCapabilityPolicy = DEFAULT_AGENT_CAPABILITY_POLICY

    def project_capability(self, agent: AgentMember) -> dict[str, Any]:
        reservation: AgentWorkspaceGenerationReservation | None = None
        lease: AgentCapabilityLease | None = None
        retirement: AgentRetirementRecord | None = None
        retirement_request: AgentRetirementRequest | None = None
        if agent.member_id is not None:
            reservations = (
                self.repositories.agent_workspace_generation_reservations.list_by_agent(
                    session_id=agent.session_id,
                    agent_member_id=agent.member_id,
                )
            )
            leases = self.repositories.agent_capability_leases.list_by_agent(
                session_id=agent.session_id,
                agent_member_id=agent.member_id,
            )
            reservation = None if not reservations else reservations[-1]
            if reservation is not None:
                lease = self.repositories.agent_capability_leases.get_by_generation(
                    session_id=agent.session_id,
                    agent_member_id=agent.member_id,
                    workspace_generation=reservation.workspace_generation,
                )
            elif leases:
                lease = leases[-1]
            retirement = self.repositories.agent_retirements.get_by_agent(
                session_id=agent.session_id,
                agent_member_id=agent.member_id,
            )
            retirement_request = (
                self.repositories.agent_retirement_requests.get_by_agent(
                    session_id=agent.session_id,
                    agent_member_id=agent.member_id,
                )
            )
        parent_lease = (
            None
            if lease is None or lease.parent_lease_id is None
            else self.repositories.agent_capability_leases.get(lease.parent_lease_id)
        )
        return project_agent_capability_for_public(
            agent=agent,
            reservation=reservation,
            lease=lease,
            parent_lease=parent_lease,
            retirement_request=retirement_request,
            retirement=retirement,
            policy=self.policy,
        )

    def project_agent(self, agent: AgentMember) -> dict[str, Any]:
        capability = self.project_capability(agent)
        return _project_agent_member_for_public(agent, capability=capability)

    def project_runtime_outcome(
        self,
        outcome: AgentRuntimeOutcome,
    ) -> dict[str, Any]:
        """Project a Host-visible runtime result without raw agent or signal state."""

        assert outcome.settlement is not None
        return {
            "signal": project_agent_runtime_signal_for_public(outcome.signal),
            "task": None if outcome.task is None else outcome.task.to_dict(),
            "agent": (
                None if outcome.agent is None else self.project_agent(outcome.agent)
            ),
            "ok": outcome.ok,
            "summary": outcome.summary,
            "teammate_status": outcome.teammate_status,
            "outputs": list(outcome.outputs),
            "waiting_approval_id": outcome.waiting_approval_id,
            "settlement": outcome.settlement.to_dict(),
        }


__all__ = [
    "AGENT_CAPABILITY_PUBLIC_PROJECTION_SCHEMA_VERSION",
    "AgentCapabilityPublicBlockerCode",
    "AgentCapabilityPublicProjectionError",
    "AgentCapabilityPublicProjector",
    "project_agent_capability_for_public",
    "project_agent_runtime_signal_for_public",
]
