from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import ClockPort
from openzyme_contracts import ControlStorePort
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordReaderPort
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import AuthorityCheckRequest
from openzyme_extension_spi import AuthorityDecision
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelMutationReceipt

from .errors import KernelContractError


def _parse_instant(value: str) -> datetime | None:
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return instant if instant.tzinfo is not None else None


def evaluate_authority_payload(
    *,
    payload: Mapping[str, JsonValue],
    session_id: str,
    actor_id: str,
    authority_lease_id: str,
    operation: str,
    scope_id: str,
    expected_generation: int,
    expected_fence: int,
    now_iso: str,
) -> AuthorityDecision:
    denial_code = None
    if payload.get("session_id") != session_id:
        denial_code = "authority_session_mismatch"
    elif payload.get("agent_member_id") != actor_id:
        denial_code = "authority_actor_mismatch"
    elif payload.get("state") != "active":
        denial_code = "authority_lease_inactive"
    elif payload.get("generation") != expected_generation:
        denial_code = "authority_generation_stale"
    elif payload.get("fence") != expected_fence:
        denial_code = "authority_fence_stale"
    else:
        expires_at = payload.get("expires_at")
        if isinstance(expires_at, str):
            expiry = _parse_instant(expires_at)
            now = _parse_instant(now_iso)
            if expiry is None or now is None:
                denial_code = "authority_lease_time_invalid"
            elif expiry <= now:
                denial_code = "authority_lease_expired"

    if denial_code is None:
        grants = payload.get("grants")
        allowed = False
        if isinstance(grants, tuple | list):
            for grant in grants:
                if not isinstance(grant, Mapping):
                    continue
                operations = grant.get("operations")
                if (
                    grant.get("scope_id") in {scope_id, session_id}
                    and isinstance(operations, tuple | list)
                    and operation in operations
                ):
                    allowed = True
                    break
        if not allowed:
            denial_code = "authority_operation_denied"

    return AuthorityDecision(
        allowed=denial_code is None,
        operation=operation,
        scope_id=scope_id,
        authority_lease_id=authority_lease_id,
        generation=expected_generation,
        fence=expected_fence,
        denial_code=denial_code,
    )


class AuthorityKernelApplicationService:
    """Read-only AgentAuthorityLease decision service."""

    def __init__(self, *, reader: KernelRecordReaderPort, clock: ClockPort) -> None:
        self._reader = reader
        self._clock = clock

    def authorize(self, request: AuthorityCheckRequest) -> AuthorityDecision:
        lease = self._reader.read(
            entity_type="agent_authority_lease",
            entity_id=request.context.authority_lease_id,
        )
        if lease is None:
            return AuthorityDecision(
                allowed=False,
                operation=request.operation,
                scope_id=request.scope_id,
                authority_lease_id=request.context.authority_lease_id,
                generation=request.expected_generation,
                fence=request.expected_fence,
                denial_code="authority_lease_not_found",
            )
        return evaluate_authority_payload(
            payload=lease.payload,
            session_id=request.context.session_id,
            actor_id=request.context.actor_id,
            authority_lease_id=request.context.authority_lease_id,
            operation=request.operation,
            scope_id=request.scope_id,
            expected_generation=request.expected_generation,
            expected_fence=request.expected_fence,
            now_iso=self._clock.now_iso(),
        )


class AuthorityLeaseMutationKind(StrEnum):
    ISSUE = "issue"
    REVOKE = "revoke"


@dataclass(frozen=True, slots=True)
class AuthorityLeaseIssueCommand:
    context: KernelCommandContext
    lease: AgentAuthorityLease
    expected_parent_version: int | None = None

    def __post_init__(self) -> None:
        if self.expected_parent_version is not None and self.expected_parent_version < 1:
            raise ValueError("expected_parent_version must be positive")


@dataclass(frozen=True, slots=True)
class AuthorityLeaseRevokeCommand:
    context: KernelCommandContext
    lease_id: str
    expected_lease_version: int
    reason: str

    def __post_init__(self) -> None:
        if self.expected_lease_version < 1:
            raise ValueError("expected_lease_version must be positive")
        if not self.reason or self.reason != self.reason.strip():
            raise ValueError("reason must be non-empty without surrounding whitespace")


class AgentAuthorityLeaseKernelApplicationService:
    """Canonical issue/supersede/revoke reducer for AgentAuthorityLease."""

    service_id = "openzyme.kernel.agent-authority-lease"

    def __init__(
        self,
        *,
        store: ControlStorePort,
        reader: KernelRecordReaderPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._store = store
        self._reader = reader
        self._clock = clock
        self._ids = ids

    def issue(self, command: AuthorityLeaseIssueCommand) -> KernelMutationReceipt:
        proposed = command.lease
        if proposed.session_id != command.context.session_id:
            raise KernelContractError(
                "authority_issue_session_mismatch", "Issued lease differs from command Session"
            )
        if proposed.state is not AgentAuthorityLeaseState.ACTIVE:
            raise KernelContractError(
                "authority_issue_state_invalid", "New authority lease must be active"
            )
        if proposed.idempotency_key != command.context.idempotency_key:
            raise KernelContractError(
                "authority_issue_idempotency_mismatch",
                "Issued lease must bind the command idempotency key",
            )
        existing = self._reader.read(
            entity_type="agent_authority_lease", entity_id=proposed.lease_id
        )
        if existing is not None:
            if existing.payload.get("lease_digest") != proposed.lease_digest:
                raise KernelContractError(
                    "authority_lease_identity_conflict",
                    "Lease identity already names another authority contract",
                )
            return self._receipt(
                context=command.context,
                operation=AuthorityLeaseMutationKind.ISSUE.value,
                records=(existing,),
                mutation_applied=False,
            )
        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "operation": AuthorityLeaseMutationKind.ISSUE.value,
                "context": command.context.to_dict(),
                "lease": proposed.to_dict(),
                "expected_parent_version": command.expected_parent_version,
            }
        )
        unit = self._store.begin(self._uow(command.context, command_digest))
        try:
            self._require_session(unit, command.context)
            self._authorize(
                unit,
                command.context,
                operation="authority.lease.issue",
                scope_id=proposed.agent_member_id,
            )
            member = unit.read(
                entity_type="agent_member", entity_id=proposed.agent_member_id
            )
            if (
                member is None
                or member.payload.get("session_id") != proposed.session_id
                or member.payload.get("status") in {"completed", "failed", "stopped", "shutdown"}
            ):
                raise KernelContractError(
                    "authority_lease_member_inactive",
                    "Authority target member is absent or retired",
                )
            parent_record = None
            parent_replacement = None
            if proposed.parent_lease_id is None:
                if command.expected_parent_version is not None or proposed.generation != 1:
                    raise KernelContractError(
                        "authority_root_generation_invalid",
                        "Root authority lease must start at generation one",
                    )
                if member.payload.get("active_authority_lease_id") is not None:
                    raise KernelContractError(
                        "authority_member_already_bound",
                        "Authority target member already has an active lease",
                    )
            else:
                parent_record = unit.read(
                    entity_type="agent_authority_lease",
                    entity_id=proposed.parent_lease_id,
                )
                if (
                    parent_record is None
                    or parent_record.state_version != command.expected_parent_version
                ):
                    raise KernelContractError(
                        "authority_parent_state_stale", "Parent authority lease is stale"
                    )
                parent = AgentAuthorityLease.from_dict(parent_record.payload)
                if (
                    parent.session_id != proposed.session_id
                    or parent.state is not AgentAuthorityLeaseState.ACTIVE
                    or proposed.generation != parent.generation + 1
                    or proposed.fence != parent.fence + 1
                    or member.payload.get("active_authority_lease_id")
                    != parent.lease_id
                ):
                    raise KernelContractError(
                        "authority_parent_identity_invalid",
                        "Child lease must advance one active parent generation/fence",
                    )
                parent_replacement = self._terminal_lease(
                    parent,
                    state=AgentAuthorityLeaseState.SUPERSEDED,
                )
                unit.stage(
                    KernelStateMutation.create(
                        mutation_id=self._ids.new_id(namespace="mutation"),
                        kind=KernelMutationKind.REPLACE,
                        entity_type="agent_authority_lease",
                        entity_id=parent.lease_id,
                        expected_state_version=parent_record.state_version,
                        payload=parent_replacement,
                    )
                )
            member_payload = dict(member.payload)
            member_payload.update(
                {
                    "active_authority_lease_id": proposed.lease_id,
                    "workspace_generation": proposed.workspace_generation,
                    "updated_at": self._clock.now_iso(),
                }
            )
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.REPLACE,
                    entity_type="agent_member",
                    entity_id=proposed.agent_member_id,
                    expected_state_version=member.state_version,
                    payload=member_payload,
                )
            )
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.CREATE,
                    entity_type="agent_authority_lease",
                    entity_id=proposed.lease_id,
                    expected_state_version=None,
                    payload=proposed.to_dict(),
                )
            )
            event = self._event(
                unit,
                context=command.context,
                event_type="authority.lease.issued",
                entity_id=proposed.lease_id,
                state_version=1,
                payload={
                    "lease_id": proposed.lease_id,
                    "agent_member_id": proposed.agent_member_id,
                    "generation": proposed.generation,
                    "fence": proposed.fence,
                    "parent_lease_id": proposed.parent_lease_id,
                },
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        records = [
            KernelRecordSnapshot.create(
                entity_type="agent_authority_lease",
                entity_id=proposed.lease_id,
                state_version=1,
                payload=proposed.to_dict(),
            )
        ]
        if parent_record is not None and parent_replacement is not None:
            records.append(
                KernelRecordSnapshot.create(
                    entity_type="agent_authority_lease",
                    entity_id=parent_record.entity_id,
                    state_version=parent_record.state_version + 1,
                    payload=parent_replacement,
                )
            )
        return self._receipt(
            context=command.context,
            operation=AuthorityLeaseMutationKind.ISSUE.value,
            records=tuple(records),
            mutation_applied=committed.committed,
            event_id=event.event_id,
        )

    def revoke(self, command: AuthorityLeaseRevokeCommand) -> KernelMutationReceipt:
        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "operation": AuthorityLeaseMutationKind.REVOKE.value,
                "context": command.context.to_dict(),
                "lease_id": command.lease_id,
                "expected_lease_version": command.expected_lease_version,
                "reason": command.reason,
            }
        )
        unit = self._store.begin(self._uow(command.context, command_digest))
        try:
            self._require_session(unit, command.context)
            self._authorize(
                unit,
                command.context,
                operation="authority.lease.revoke",
                scope_id=command.lease_id,
            )
            current = unit.read(
                entity_type="agent_authority_lease", entity_id=command.lease_id
            )
            if current is None or current.state_version != command.expected_lease_version:
                raise KernelContractError(
                    "authority_lease_state_stale", "Authority lease version is stale"
                )
            lease = AgentAuthorityLease.from_dict(current.payload)
            if lease.state is not AgentAuthorityLeaseState.ACTIVE:
                raise KernelContractError(
                    "authority_lease_not_active", "Only an active lease can be revoked"
                )
            replacement = self._terminal_lease(
                lease,
                state=AgentAuthorityLeaseState.REVOKED,
            )
            member = unit.read(
                entity_type="agent_member", entity_id=lease.agent_member_id
            )
            if (
                member is None
                or member.payload.get("active_authority_lease_id") != lease.lease_id
            ):
                raise KernelContractError(
                    "authority_member_binding_stale",
                    "Authority target member binding differs from the active lease",
                )
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.REPLACE,
                    entity_type="agent_authority_lease",
                    entity_id=command.lease_id,
                    expected_state_version=current.state_version,
                    payload=replacement,
                )
            )
            member_payload = dict(member.payload)
            member_payload.update(
                {
                    "active_authority_lease_id": None,
                    "workspace_generation": None,
                    "updated_at": self._clock.now_iso(),
                }
            )
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.REPLACE,
                    entity_type="agent_member",
                    entity_id=lease.agent_member_id,
                    expected_state_version=member.state_version,
                    payload=member_payload,
                )
            )
            event = self._event(
                unit,
                context=command.context,
                event_type="authority.lease.revoked",
                entity_id=command.lease_id,
                state_version=current.state_version + 1,
                payload={
                    "lease_id": command.lease_id,
                    "generation": replacement["generation"],
                    "fence": replacement["fence"],
                    "reason": command.reason,
                },
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        record = KernelRecordSnapshot.create(
            entity_type="agent_authority_lease",
            entity_id=command.lease_id,
            state_version=current.state_version + 1,
            payload=replacement,
        )
        return self._receipt(
            context=command.context,
            operation=AuthorityLeaseMutationKind.REVOKE.value,
            records=(record,),
            mutation_applied=committed.committed,
            event_id=event.event_id,
        )

    def _terminal_lease(
        self,
        lease: AgentAuthorityLease,
        *,
        state: AgentAuthorityLeaseState,
    ) -> dict[str, JsonValue]:
        generation = lease.generation + 1
        fence = lease.fence + 1
        grants = tuple(
            AuthorityGrant.create(
                grant_id=grant.grant_id,
                scope_id=grant.scope_id,
                operations=grant.operations,
                generation=generation,
                fence=fence,
            )
            for grant in lease.grants
        )
        return AgentAuthorityLease.create(
            lease_id=lease.lease_id,
            session_id=lease.session_id,
            agent_member_id=lease.agent_member_id,
            grants=grants,
            generation=generation,
            fence=fence,
            state=state,
            issued_at=lease.issued_at,
            expires_at=lease.expires_at,
            agent_id=lease.agent_id,
            workspace_generation=lease.workspace_generation,
            parent_lease_id=lease.parent_lease_id,
            policy_digest=lease.policy_digest,
            idempotency_key=lease.idempotency_key,
            updated_at=self._clock.now_iso(),
        ).to_dict()

    def _uow(
        self, context: KernelCommandContext, command_digest: str
    ) -> UnitOfWorkRequest:
        return UnitOfWorkRequest(
            unit_of_work_id=self._ids.new_id(namespace="uow"),
            command_id=context.command_id,
            session_id=context.session_id,
            actor_id=context.actor_id,
            authority_lease_id=context.authority_lease_id,
            authority_generation=context.authority_generation,
            authority_fence=context.authority_fence,
            expected_session_version=context.expected_session_version,
            idempotency_key=context.idempotency_key,
            command_digest=command_digest,
        )

    @staticmethod
    def _require_session(unit, context: KernelCommandContext) -> None:  # noqa: ANN001
        session = unit.read(entity_type="session", entity_id=context.session_id)
        if session is None:
            raise KernelContractError("session_not_found", "Authority Session is absent")
        if session.state_version != context.expected_session_version:
            raise KernelContractError(
                "session_state_version_stale", "Authority command Session version is stale"
            )

    def _authorize(
        self,
        unit,  # noqa: ANN001
        context: KernelCommandContext,
        *,
        operation: str,
        scope_id: str,
    ) -> None:
        issuer = unit.read(
            entity_type="agent_authority_lease", entity_id=context.authority_lease_id
        )
        if issuer is None:
            raise KernelContractError(
                "authority_lease_not_found", "Issuing authority lease is absent"
            )
        decision = evaluate_authority_payload(
            payload=issuer.payload,
            session_id=context.session_id,
            actor_id=context.actor_id,
            authority_lease_id=context.authority_lease_id,
            operation=operation,
            scope_id=scope_id,
            expected_generation=context.authority_generation,
            expected_fence=context.authority_fence,
            now_iso=self._clock.now_iso(),
        )
        if not decision.allowed:
            raise KernelContractError(
                decision.denial_code or "authority_operation_denied",
                "AgentAuthorityLease denies authority mutation",
            )

    def _event(
        self,
        unit,  # noqa: ANN001
        *,
        context: KernelCommandContext,
        event_type: str,
        entity_id: str,
        state_version: int,
        payload: Mapping[str, JsonValue],
    ) -> DurableEventRecord:
        event = DurableEventRecord.create(
            event_id=self._ids.new_id(namespace="event"),
            session_id=context.session_id,
            event_type=event_type,
            source_entity_type="agent_authority_lease",
            source_entity_id=entity_id,
            source_state_version=state_version,
            command_id=context.command_id,
            payload=payload,
        )
        unit.append_event(event)
        outbox_payload = {
            "event_id": event.event_id,
            "event_digest": event.event_digest,
            "event_type": event_type,
            "lease_id": entity_id,
        }
        unit.append_outbox(
            OutboxRecord(
                outbox_id=self._ids.new_id(namespace="outbox"),
                session_id=context.session_id,
                topic="openzyme.kernel.authority-events",
                occurrence_id=event.event_id,
                payload=outbox_payload,
                payload_digest=canonical_sha256_digest(outbox_payload),
                created_at=self._clock.now_iso(),
            )
        )
        return event

    def _receipt(
        self,
        *,
        context: KernelCommandContext,
        operation: str,
        records: tuple[KernelRecordSnapshot, ...],
        mutation_applied: bool,
        event_id: str | None = None,
    ) -> KernelMutationReceipt:
        return KernelMutationReceipt.create(
            command_id=context.command_id,
            service_id=self.service_id,
            operation=operation,
            mutation_applied=mutation_applied,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            entity_refs=tuple(
                KernelEntityRef(
                    entity_kind=record.entity_type,
                    entity_id=record.entity_id,
                    state_version=record.state_version,
                    entity_digest=record.record_digest,
                )
                for record in records
            ),
            event_refs=() if event_id is None else (event_id,),
            result={"fallback_performed": False},
        )


__all__ = [
    "AgentAuthorityLeaseKernelApplicationService",
    "AuthorityLeaseIssueCommand",
    "AuthorityLeaseMutationKind",
    "AuthorityLeaseRevokeCommand",
    "AuthorityKernelApplicationService",
    "evaluate_authority_payload",
]
