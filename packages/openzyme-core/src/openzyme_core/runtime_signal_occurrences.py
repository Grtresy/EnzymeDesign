from __future__ import annotations

from dataclasses import dataclass

from openzyme_domain import AgentCapabilityLeaseStatus
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus

from .agent_capability_service import AgentCapabilityAdmissionRejectedError
from .agent_capability_service import AgentCapabilityProvisioningRequiredError
from .agent_capability_service import AgentCapabilityRetiredError
from .agent_capability_service import AgentCapabilityRevokedError
from .agent_capability_service import AgentRetirementRequestedError
from .repositories import CoreRepositories


@dataclass(frozen=True, slots=True)
class AgentRuntimeSignalOccurrenceResult:
    signal: AgentRuntimeSignal
    created: bool


@dataclass(slots=True)
class AgentRuntimeSignalOccurrenceService:
    """Create one signal occurrence bound to the current capability generation."""

    repositories: CoreRepositories

    def enqueue(
        self,
        *,
        signal_id: str,
        session_id: str,
        agent_id: str,
        reason: AgentRuntimeSignalReason,
        created_at: str,
        task_id: str | None = None,
        lane_id: str | None = None,
        correlation_id: str | None = None,
        source_ref: str | None = None,
    ) -> AgentRuntimeSignalOccurrenceResult:
        with self.repositories.atomic(prefix="runtime_signal_occurrence"):
            return self.enqueue_locked(
                signal_id=signal_id,
                session_id=session_id,
                agent_id=agent_id,
                reason=reason,
                created_at=created_at,
                task_id=task_id,
                lane_id=lane_id,
                correlation_id=correlation_id,
                source_ref=source_ref,
            )

    def enqueue_locked(
        self,
        *,
        signal_id: str,
        session_id: str,
        agent_id: str,
        reason: AgentRuntimeSignalReason,
        created_at: str,
        task_id: str | None = None,
        lane_id: str | None = None,
        correlation_id: str | None = None,
        source_ref: str | None = None,
    ) -> AgentRuntimeSignalOccurrenceResult:
        if not self.repositories.in_managed_transaction:
            raise RuntimeError(
                "runtime signal occurrence resolution requires an owning transaction"
            )
        capability_lease_id, workspace_generation = self._resolve_current_binding(
            session_id=session_id,
            agent_id=agent_id,
        )
        existing_by_id = self.repositories.runtime_signals.get(signal_id)
        if existing_by_id is not None:
            self._require_same_occurrence(
                existing_by_id,
                session_id=session_id,
                agent_id=agent_id,
                reason=reason,
                created_at=created_at,
                task_id=task_id,
                lane_id=lane_id,
                correlation_id=correlation_id,
                source_ref=source_ref,
                capability_lease_id=capability_lease_id,
                workspace_generation=workspace_generation,
            )
            return AgentRuntimeSignalOccurrenceResult(
                signal=existing_by_id,
                created=False,
            )
        existing = self.repositories.runtime_signals.find_pending_duplicate(
            session_id=session_id,
            agent_id=agent_id,
            reason=reason,
            source_ref=source_ref,
            capability_lease_id=capability_lease_id,
            workspace_generation=workspace_generation,
        )
        if existing is not None:
            self._require_same_occurrence(
                existing,
                session_id=session_id,
                agent_id=agent_id,
                reason=reason,
                created_at=existing.created_at,
                task_id=task_id,
                lane_id=lane_id,
                correlation_id=correlation_id,
                source_ref=source_ref,
                capability_lease_id=capability_lease_id,
                workspace_generation=workspace_generation,
            )
            return AgentRuntimeSignalOccurrenceResult(signal=existing, created=False)
        signal = AgentRuntimeSignal(
            signal_id=signal_id,
            session_id=session_id,
            agent_id=agent_id,
            task_id=task_id,
            lane_id=lane_id,
            correlation_id=correlation_id,
            reason=reason,
            source_ref=source_ref,
            status=AgentRuntimeSignalStatus.PENDING,
            created_at=created_at,
            capability_lease_id=capability_lease_id,
            workspace_generation=workspace_generation,
        )
        saved = self.repositories.runtime_signals.insert_if_absent(signal)
        return AgentRuntimeSignalOccurrenceResult(signal=saved, created=True)

    def _resolve_current_binding(
        self,
        *,
        session_id: str,
        agent_id: str,
    ) -> tuple[str, int]:
        agent = self.repositories.agents.get(session_id, agent_id)
        if agent is None or agent.member_id is None:
            raise AgentCapabilityProvisioningRequiredError(
                f"agent {agent_id!r} has no canonical member identity"
            )
        retirement = self.repositories.agent_retirements.get_by_agent(
            session_id=session_id,
            agent_member_id=agent.member_id,
        )
        if retirement is not None:
            raise AgentCapabilityRetiredError(
                f"agent member {agent.member_id!r} is retired"
            )
        retirement_request = self.repositories.agent_retirement_requests.get_by_agent(
            session_id=session_id,
            agent_member_id=agent.member_id,
        )
        if retirement_request is not None:
            raise AgentRetirementRequestedError(
                f"agent member {agent.member_id!r} has a durable retirement request"
            )
        reservation = (
            self.repositories.agent_workspace_generation_reservations.get_current(
                session_id=session_id,
                agent_member_id=agent.member_id,
            )
        )
        if reservation is None:
            raise AgentCapabilityProvisioningRequiredError(
                f"agent {agent_id!r} has no current workspace generation"
            )
        if reservation.agent_id != agent_id:
            raise AgentCapabilityAdmissionRejectedError(
                "workspace generation reservation owner does not match the agent"
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
        if (
            lease.agent_id != agent_id
            or lease.workspace_generation != reservation.workspace_generation
        ):
            raise AgentCapabilityAdmissionRejectedError(
                "capability lease owner does not match the current generation"
            )
        if lease.status is AgentCapabilityLeaseStatus.REVOKED:
            raise AgentCapabilityRevokedError(
                f"capability lease {lease.lease_id!r} is revoked"
            )
        if lease.status not in {
            AgentCapabilityLeaseStatus.PENDING_WORKSPACE,
            AgentCapabilityLeaseStatus.ACTIVE,
        }:
            raise AgentCapabilityAdmissionRejectedError(
                "capability lease status cannot own a runtime occurrence"
            )
        return lease.lease_id, lease.workspace_generation

    @staticmethod
    def _require_same_occurrence(
        signal: AgentRuntimeSignal,
        *,
        session_id: str,
        agent_id: str,
        reason: AgentRuntimeSignalReason,
        created_at: str,
        task_id: str | None,
        lane_id: str | None,
        correlation_id: str | None,
        source_ref: str | None,
        capability_lease_id: str,
        workspace_generation: int,
    ) -> None:
        if (
            signal.session_id,
            signal.agent_id,
            signal.task_id,
            signal.lane_id,
            signal.correlation_id,
            signal.reason,
            signal.source_ref,
            signal.created_at,
            signal.capability_lease_id,
            signal.workspace_generation,
        ) != (
            session_id,
            agent_id,
            task_id,
            lane_id,
            correlation_id,
            reason,
            source_ref,
            created_at,
            capability_lease_id,
            workspace_generation,
        ):
            raise ValueError(
                "runtime signal identity is already bound to another occurrence"
            )


__all__ = [
    "AgentRuntimeSignalOccurrenceResult",
    "AgentRuntimeSignalOccurrenceService",
]
