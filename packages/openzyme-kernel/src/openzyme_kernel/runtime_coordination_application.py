from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from enum import StrEnum
from typing import Any

from openzyme_contracts import AgentRuntimeSignalReason
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
from openzyme_contracts import SessionRuntimeLeaseMode
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_identifier
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelMutationReceipt

from .authority_application import evaluate_authority_payload
from .errors import KernelContractError


_RETIRED_MEMBER_STATES = frozenset({"completed", "failed", "stopped", "shutdown"})


def build_runtime_signal_payload(
    *,
    signal_id: str,
    session_id: str,
    agent_id: str,
    agent_member_id: str,
    reason: AgentRuntimeSignalReason,
    target_authority_lease_id: str,
    target_authority_lease_digest: str,
    workspace_generation: int,
    process_epoch: int,
    correlation_id: str | None,
    source_ref: str | None,
    task_id: str | None,
    lane_id: str | None,
    created_at: str,
    enqueue_command_digest: str,
) -> dict[str, Any]:
    """Build the one closed signal payload used by every same-UoW Kernel writer."""

    if process_epoch < 1 or workspace_generation < 1:
        raise KernelContractError(
            "runtime_signal_target_invalid",
            "Runtime signal requires positive process/workspace generations",
        )
    return {
        "signal_id": signal_id,
        "session_id": session_id,
        "agent_id": agent_id,
        "agent_member_id": agent_member_id,
        "reason": reason.value,
        "status": "pending",
        "created_at": created_at,
        "task_id": task_id,
        "lane_id": lane_id,
        "correlation_id": correlation_id,
        "source_ref": source_ref,
        "claimed_at": None,
        "claimed_by": None,
        "claim_token": None,
        "claim_expires_at": None,
        "attempt_count": 0,
        "completed_at": None,
        "error_message": None,
        "last_error": None,
        "session_lease_token": None,
        "session_fencing_token": None,
        "runtime_lease_generation": None,
        "capability_lease_id": target_authority_lease_id,
        "capability_lease_digest": target_authority_lease_digest,
        "workspace_generation": workspace_generation,
        "process_epoch": process_epoch,
        "enqueue_command_digest": enqueue_command_digest,
        "claim_command_digest": None,
    }


def _instant(value: str, *, field_name: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise KernelContractError(
            "runtime_time_invalid", f"{field_name} must be an ISO-8601 instant"
        ) from exc
    if result.tzinfo is None:
        raise KernelContractError(
            "runtime_time_invalid", f"{field_name} must include a timezone"
        )
    return result


def _after(value: str, seconds: int) -> str:
    return (_instant(value, field_name="now") + timedelta(seconds=seconds)).isoformat()


def _positive_seconds(value: int, *, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")


class RuntimeLeaseAction(StrEnum):
    ACQUIRE = "acquire"
    HEARTBEAT = "heartbeat"
    RELEASE = "release"


@dataclass(frozen=True, slots=True)
class RuntimeSignalEnqueueCommand:
    context: KernelCommandContext
    signal_id: str
    agent_id: str
    agent_member_id: str
    reason: AgentRuntimeSignalReason
    target_authority_lease_id: str
    workspace_generation: int
    task_id: str | None = None
    lane_id: str | None = None
    source_ref: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "signal_id",
            "agent_id",
            "agent_member_id",
            "target_authority_lease_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in ("task_id", "lane_id", "source_ref"):
            value = getattr(self, field_name)
            if value is not None:
                require_identifier(value, field_name=field_name)
        _positive_seconds(self.workspace_generation, field_name="workspace_generation")


@dataclass(frozen=True, slots=True)
class SessionRuntimeLeaseCommand:
    context: KernelCommandContext
    action: RuntimeLeaseAction
    owner_id: str
    mode: SessionRuntimeLeaseMode
    lease_seconds: int
    expected_lease_token: str | None = None
    expected_generation: int | None = None
    expected_fence: int | None = None

    def __post_init__(self) -> None:
        require_identifier(self.owner_id, field_name="owner_id")
        _positive_seconds(self.lease_seconds, field_name="lease_seconds")
        if self.action is RuntimeLeaseAction.ACQUIRE:
            if any(
                value is not None
                for value in (
                    self.expected_lease_token,
                    self.expected_generation,
                    self.expected_fence,
                )
            ):
                raise ValueError("lease acquire must not carry an old lease identity")
        else:
            if self.expected_lease_token is None:
                raise ValueError("lease heartbeat/release requires lease token")
            require_identifier(self.expected_lease_token, field_name="expected_lease_token")
            if self.expected_generation is None or self.expected_fence is None:
                raise ValueError("lease heartbeat/release requires generation and fence")
            _positive_seconds(self.expected_generation, field_name="expected_generation")
            _positive_seconds(self.expected_fence, field_name="expected_fence")


@dataclass(frozen=True, slots=True)
class RuntimeSignalClaimCommand:
    context: KernelCommandContext
    signal_id: str
    runtime_owner_id: str
    runtime_lease_token: str
    runtime_lease_generation: int
    runtime_fence: int
    expected_signal_version: int
    claim_seconds: int

    def __post_init__(self) -> None:
        for field_name in ("signal_id", "runtime_owner_id", "runtime_lease_token"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "runtime_lease_generation",
            "runtime_fence",
            "expected_signal_version",
            "claim_seconds",
        ):
            _positive_seconds(getattr(self, field_name), field_name=field_name)


class RuntimeCoordinationKernelApplicationService:
    """Canonical Session lease and Agent runtime-signal owner.

    This reducer only coordinates durable work.  It neither invokes a Runtime Adapter
    nor reads or mutates Task state.  A signal claim binds the current Session lease,
    target member process epoch, target Agent authority lease, and workspace generation.
    """

    service_id = "openzyme.kernel.runtime-coordination"

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

    def enqueue_signal(
        self, command: RuntimeSignalEnqueueCommand
    ) -> KernelMutationReceipt:
        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "operation": "signal.enqueue",
                "context": command.context.to_dict(),
                "signal_id": command.signal_id,
                "agent_id": command.agent_id,
                "agent_member_id": command.agent_member_id,
                "reason": command.reason.value,
                "target_authority_lease_id": command.target_authority_lease_id,
                "workspace_generation": command.workspace_generation,
                "task_id": command.task_id,
                "lane_id": command.lane_id,
                "source_ref": command.source_ref,
            }
        )
        existing = self._reader.read(
            entity_type="agent_runtime_signal", entity_id=command.signal_id
        )
        if existing is not None:
            if existing.payload.get("enqueue_command_digest") != command_digest:
                raise KernelContractError(
                    "runtime_signal_identity_conflict",
                    "Signal identity already names another occurrence",
                )
            return self._receipt(
                context=command.context,
                operation="signal.enqueue",
                record=existing,
                mutation_applied=False,
            )

        request = self._uow_request(command.context, command_digest)
        unit = self._store.begin(request)
        try:
            self._require_session(unit, command.context)
            self._authorize(
                unit,
                command.context,
                operation="runtime.signal.enqueue",
                scope_id=command.signal_id,
            )
            member = self._require_member(
                unit,
                session_id=command.context.session_id,
                agent_id=command.agent_id,
                agent_member_id=command.agent_member_id,
            )
            target_lease = self._require_target_lease(
                unit,
                session_id=command.context.session_id,
                agent_member_id=command.agent_member_id,
                lease_id=command.target_authority_lease_id,
                workspace_generation=command.workspace_generation,
            )
            now = self._clock.now_iso()
            payload = build_runtime_signal_payload(
                signal_id=command.signal_id,
                session_id=command.context.session_id,
                agent_id=command.agent_id,
                agent_member_id=command.agent_member_id,
                reason=command.reason,
                target_authority_lease_id=command.target_authority_lease_id,
                target_authority_lease_digest=str(target_lease.payload["lease_digest"]),
                workspace_generation=command.workspace_generation,
                process_epoch=int(member.payload["process_epoch"]),
                correlation_id=command.context.correlation_id,
                source_ref=command.source_ref,
                task_id=command.task_id,
                lane_id=command.lane_id,
                created_at=now,
                enqueue_command_digest=command_digest,
            )
            mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.CREATE,
                entity_type="agent_runtime_signal",
                entity_id=command.signal_id,
                expected_state_version=None,
                payload=payload,
            )
            unit.stage(mutation)
            event = self._event_and_outbox(
                unit,
                context=command.context,
                event_type="runtime.signal.enqueued",
                entity_type="agent_runtime_signal",
                entity_id=command.signal_id,
                state_version=1,
                payload={"signal_id": command.signal_id, "task_transition_performed": False},
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        record = KernelRecordSnapshot.create(
            entity_type="agent_runtime_signal",
            entity_id=command.signal_id,
            state_version=1,
            payload=payload,
        )
        return self._receipt(
            context=command.context,
            operation="signal.enqueue",
            record=record,
            mutation_applied=committed.committed,
            event_id=event.event_id,
        )

    def mutate_session_lease(
        self, command: SessionRuntimeLeaseCommand
    ) -> KernelMutationReceipt:
        now = self._clock.now_iso()
        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "operation": f"lease.{command.action.value}",
                "context": command.context.to_dict(),
                "owner_id": command.owner_id,
                "mode": command.mode.value,
                "lease_seconds": command.lease_seconds,
                "expected_lease_token": command.expected_lease_token,
                "expected_generation": command.expected_generation,
                "expected_fence": command.expected_fence,
            }
        )
        request = self._uow_request(command.context, command_digest)
        unit = self._store.begin(request)
        try:
            self._require_session(unit, command.context)
            self._authorize(
                unit,
                command.context,
                operation=f"runtime.lease.{command.action.value}",
                scope_id=command.context.session_id,
            )
            current = unit.read(
                entity_type="session_runtime_lease",
                entity_id=command.context.session_id,
            )
            if command.action is RuntimeLeaseAction.ACQUIRE:
                if (
                    current is not None
                    and current.payload.get("released_at") is None
                    and _instant(str(current.payload["expires_at"]), field_name="expires_at")
                    > _instant(now, field_name="now")
                ):
                    raise KernelContractError(
                        "session_runtime_lease_active",
                        "Session already has an active runtime owner",
                        details={"owner_id": current.payload.get("owner_id")},
                    )
                generation = 1 if current is None else int(current.payload["generation"]) + 1
                fence = 1 if current is None else int(current.payload["fencing_token"]) + 1
                payload = {
                    "session_id": command.context.session_id,
                    "owner_id": command.owner_id,
                    "lease_token": self._ids.new_id(namespace="runtime-lease"),
                    "mode": command.mode.value,
                    "generation": generation,
                    "fencing_token": fence,
                    "acquired_at": now,
                    "heartbeat_at": now,
                    "expires_at": _after(now, command.lease_seconds),
                    "released_at": None,
                    "last_error": None,
                    "acquire_command_digest": command_digest,
                }
            else:
                if current is None or not self._lease_identity_matches(current, command):
                    raise KernelContractError(
                        "session_runtime_lease_stale",
                        "Runtime lease token, generation, fence or owner is stale",
                    )
                if current.payload.get("released_at") is not None:
                    raise KernelContractError(
                        "session_runtime_lease_released", "Runtime lease is already released"
                    )
                if command.action is RuntimeLeaseAction.HEARTBEAT and _instant(
                    str(current.payload["expires_at"]), field_name="expires_at"
                ) <= _instant(now, field_name="now"):
                    raise KernelContractError(
                        "session_runtime_lease_expired", "Expired lease cannot heartbeat"
                    )
                payload = dict(current.payload)
                payload["heartbeat_at"] = now
                if command.action is RuntimeLeaseAction.HEARTBEAT:
                    payload["expires_at"] = _after(now, command.lease_seconds)
                else:
                    payload["released_at"] = now
            mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=(
                    KernelMutationKind.CREATE
                    if current is None
                    else KernelMutationKind.REPLACE
                ),
                entity_type="session_runtime_lease",
                entity_id=command.context.session_id,
                expected_state_version=None if current is None else current.state_version,
                payload=payload,
            )
            unit.stage(mutation)
            next_version = 1 if current is None else current.state_version + 1
            event = self._lease_event(
                unit,
                command=command,
                state_version=next_version,
                generation=int(payload["generation"]),
                fence=int(payload["fencing_token"]),
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        record = KernelRecordSnapshot.create(
            entity_type="session_runtime_lease",
            entity_id=command.context.session_id,
            state_version=next_version,
            payload=payload,
        )
        return self._receipt(
            context=command.context,
            operation=f"lease.{command.action.value}",
            record=record,
            mutation_applied=committed.committed,
            event_id=event.event_id,
        )

    def claim_signal(self, command: RuntimeSignalClaimCommand) -> KernelMutationReceipt:
        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "operation": "signal.claim",
                "context": command.context.to_dict(),
                "signal_id": command.signal_id,
                "runtime_owner_id": command.runtime_owner_id,
                "runtime_lease_token": command.runtime_lease_token,
                "runtime_lease_generation": command.runtime_lease_generation,
                "runtime_fence": command.runtime_fence,
                "expected_signal_version": command.expected_signal_version,
                "claim_seconds": command.claim_seconds,
            }
        )
        request = self._uow_request(command.context, command_digest)
        unit = self._store.begin(request)
        try:
            self._require_session(unit, command.context)
            self._authorize(
                unit,
                command.context,
                operation="runtime.signal.claim",
                scope_id=command.signal_id,
            )
            signal = unit.read(
                entity_type="agent_runtime_signal", entity_id=command.signal_id
            )
            lease = unit.read(
                entity_type="session_runtime_lease",
                entity_id=command.context.session_id,
            )
            if signal is None or signal.payload.get("session_id") != command.context.session_id:
                raise KernelContractError("runtime_signal_not_found", "Signal is absent")
            if signal.state_version != command.expected_signal_version:
                raise KernelContractError("runtime_signal_state_stale", "Signal version is stale")
            self._require_active_runtime_lease(lease, command)
            member = self._require_member(
                unit,
                session_id=command.context.session_id,
                agent_id=str(signal.payload["agent_id"]),
                agent_member_id=str(signal.payload["agent_member_id"]),
            )
            target_lease = self._require_target_lease(
                unit,
                session_id=command.context.session_id,
                agent_member_id=str(signal.payload["agent_member_id"]),
                lease_id=str(signal.payload["capability_lease_id"]),
                workspace_generation=int(signal.payload["workspace_generation"]),
            )
            if member.payload.get("process_epoch") != signal.payload.get("process_epoch"):
                raise KernelContractError(
                    "runtime_signal_process_epoch_stale",
                    "Signal was enqueued for an older Agent process epoch",
                )
            if target_lease.payload.get("lease_digest") != signal.payload.get(
                "capability_lease_digest"
            ):
                raise KernelContractError(
                    "runtime_signal_authority_stale",
                    "Signal target authority lease changed after enqueue",
                )
            now = self._clock.now_iso()
            status = signal.payload.get("status")
            expired_claim = (
                status == "claimed"
                and isinstance(signal.payload.get("claim_expires_at"), str)
                and _instant(
                    str(signal.payload["claim_expires_at"]), field_name="claim_expires_at"
                )
                <= _instant(now, field_name="now")
            )
            if status != "pending" and not expired_claim:
                raise KernelContractError(
                    "runtime_signal_not_claimable", "Signal is not pending or expired-claimed"
                )
            payload = dict(signal.payload)
            payload.update(
                {
                    "status": "claimed",
                    "claimed_at": now,
                    "claimed_by": command.runtime_owner_id,
                    "claim_token": self._ids.new_id(namespace="signal-claim"),
                    "claim_expires_at": _after(now, command.claim_seconds),
                    "attempt_count": int(signal.payload.get("attempt_count", 0)) + 1,
                    "session_lease_token": command.runtime_lease_token,
                    "session_fencing_token": command.runtime_fence,
                    "runtime_lease_generation": command.runtime_lease_generation,
                    "last_error": (
                        "previous claim expired before reclaim" if expired_claim else None
                    ),
                    "claim_command_digest": command_digest,
                }
            )
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.REPLACE,
                    entity_type="agent_runtime_signal",
                    entity_id=command.signal_id,
                    expected_state_version=signal.state_version,
                    payload=payload,
                )
            )
            next_version = signal.state_version + 1
            event = self._event_and_outbox(
                unit,
                context=command.context,
                event_type="runtime.signal.claimed",
                entity_type="agent_runtime_signal",
                entity_id=command.signal_id,
                state_version=next_version,
                payload={
                    "signal_id": command.signal_id,
                    "attempt_count": payload["attempt_count"],
                    "runtime_lease_generation": command.runtime_lease_generation,
                    "runtime_fence": command.runtime_fence,
                    "task_transition_performed": False,
                },
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        record = KernelRecordSnapshot.create(
            entity_type="agent_runtime_signal",
            entity_id=command.signal_id,
            state_version=next_version,
            payload=payload,
        )
        return self._receipt(
            context=command.context,
            operation="signal.claim",
            record=record,
            mutation_applied=committed.committed,
            event_id=event.event_id,
        )

    def _uow_request(
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
    def _require_session(unit: Any, context: KernelCommandContext) -> KernelRecordSnapshot:
        session = unit.read(entity_type="session", entity_id=context.session_id)
        if session is None:
            raise KernelContractError("session_not_found", "Runtime Session is absent")
        if session.state_version != context.expected_session_version:
            raise KernelContractError(
                "session_state_version_stale", "Runtime command Session version is stale"
            )
        return session

    def _authorize(
        self,
        unit: Any,
        context: KernelCommandContext,
        *,
        operation: str,
        scope_id: str,
    ) -> None:
        lease = unit.read(
            entity_type="agent_authority_lease", entity_id=context.authority_lease_id
        )
        if lease is None:
            raise KernelContractError("authority_lease_not_found", "Authority lease is absent")
        decision = evaluate_authority_payload(
            payload=lease.payload,
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
                "AgentAuthorityLease denies runtime coordination",
            )

    def _require_member(
        self,
        unit: Any,
        *,
        session_id: str,
        agent_id: str,
        agent_member_id: str,
    ) -> KernelRecordSnapshot:
        member = unit.read(entity_type="agent_member", entity_id=agent_member_id)
        if (
            member is None
            or member.payload.get("session_id") != session_id
            or member.payload.get("agent_id") != agent_id
            or member.payload.get("status") in _RETIRED_MEMBER_STATES
        ):
            raise KernelContractError(
                "runtime_agent_member_inactive", "Runtime target member is absent or retired"
            )
        process_epoch = member.payload.get("process_epoch")
        if not isinstance(process_epoch, int) or isinstance(process_epoch, bool) or process_epoch < 1:
            raise KernelContractError(
                "runtime_process_epoch_invalid", "Runtime target process epoch is invalid"
            )
        return member

    def _require_target_lease(
        self,
        unit: Any,
        *,
        session_id: str,
        agent_member_id: str,
        lease_id: str,
        workspace_generation: int,
    ) -> KernelRecordSnapshot:
        lease = unit.read(entity_type="agent_authority_lease", entity_id=lease_id)
        now = _instant(self._clock.now_iso(), field_name="now")
        if (
            lease is None
            or lease.payload.get("session_id") != session_id
            or lease.payload.get("agent_member_id") != agent_member_id
            or lease.payload.get("workspace_generation") != workspace_generation
            or lease.payload.get("state") != "active"
        ):
            raise KernelContractError(
                "runtime_target_authority_invalid",
                "Signal target authority/workspace binding is invalid",
            )
        expires_at = lease.payload.get("expires_at")
        if isinstance(expires_at, str) and _instant(expires_at, field_name="expires_at") <= now:
            raise KernelContractError(
                "runtime_target_authority_expired", "Signal target authority lease expired"
            )
        return lease

    def _require_active_runtime_lease(
        self,
        lease: KernelRecordSnapshot | None,
        command: RuntimeSignalClaimCommand,
    ) -> None:
        if (
            lease is None
            or lease.payload.get("owner_id") != command.runtime_owner_id
            or lease.payload.get("lease_token") != command.runtime_lease_token
            or lease.payload.get("generation") != command.runtime_lease_generation
            or lease.payload.get("fencing_token") != command.runtime_fence
            or lease.payload.get("released_at") is not None
        ):
            raise KernelContractError(
                "session_runtime_lease_stale", "Signal claim runtime lease is stale"
            )
        if _instant(str(lease.payload["expires_at"]), field_name="expires_at") <= _instant(
            self._clock.now_iso(), field_name="now"
        ):
            raise KernelContractError(
                "session_runtime_lease_expired", "Signal claim runtime lease expired"
            )

    @staticmethod
    def _lease_identity_matches(
        current: KernelRecordSnapshot, command: SessionRuntimeLeaseCommand
    ) -> bool:
        return (
            current.payload.get("owner_id") == command.owner_id
            and current.payload.get("lease_token") == command.expected_lease_token
            and current.payload.get("generation") == command.expected_generation
            and current.payload.get("fencing_token") == command.expected_fence
        )

    def _event_and_outbox(
        self,
        unit: Any,
        *,
        context: KernelCommandContext,
        event_type: str,
        entity_type: str,
        entity_id: str,
        state_version: int,
        payload: Mapping[str, Any],
    ) -> DurableEventRecord:
        event = DurableEventRecord.create(
            event_id=self._ids.new_id(namespace="event"),
            session_id=context.session_id,
            event_type=event_type,
            source_entity_type=entity_type,
            source_entity_id=entity_id,
            source_state_version=state_version,
            command_id=context.command_id,
            payload=payload,
        )
        unit.append_event(event)
        outbox_payload = {
            "event_id": event.event_id,
            "event_digest": event.event_digest,
            "event_type": event.event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
        }
        unit.append_outbox(
            OutboxRecord(
                outbox_id=self._ids.new_id(namespace="outbox"),
                session_id=context.session_id,
                topic="openzyme.kernel.runtime-coordination-events",
                occurrence_id=event.event_id,
                payload=outbox_payload,
                payload_digest=canonical_sha256_digest(outbox_payload),
                created_at=self._clock.now_iso(),
            )
        )
        return event

    def _lease_event(
        self,
        unit: Any,
        *,
        command: SessionRuntimeLeaseCommand,
        state_version: int,
        generation: int,
        fence: int,
    ) -> DurableEventRecord:
        common = {
            "owner_id": command.owner_id,
            "generation": generation,
            "fence": fence,
            "task_transition_performed": False,
        }
        if command.action is RuntimeLeaseAction.ACQUIRE:
            return self._event_and_outbox(
                unit,
                context=command.context,
                event_type="runtime.lease.acquired",
                entity_type="session_runtime_lease",
                entity_id=command.context.session_id,
                state_version=state_version,
                payload=common,
            )
        if command.action is RuntimeLeaseAction.HEARTBEAT:
            return self._event_and_outbox(
                unit,
                context=command.context,
                event_type="runtime.lease.renewed",
                entity_type="session_runtime_lease",
                entity_id=command.context.session_id,
                state_version=state_version,
                payload=common,
            )
        return self._event_and_outbox(
            unit,
            context=command.context,
            event_type="runtime.lease.released",
            entity_type="session_runtime_lease",
            entity_id=command.context.session_id,
            state_version=state_version,
            payload=common,
        )

    def _receipt(
        self,
        *,
        context: KernelCommandContext,
        operation: str,
        record: KernelRecordSnapshot,
        mutation_applied: bool,
        event_id: str | None = None,
    ) -> KernelMutationReceipt:
        return KernelMutationReceipt.create(
            command_id=context.command_id,
            service_id=self.service_id,
            operation=operation,
            mutation_applied=mutation_applied,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            entity_refs=(
                KernelEntityRef(
                    entity_kind=record.entity_type,
                    entity_id=record.entity_id,
                    state_version=record.state_version,
                    entity_digest=record.record_digest,
                ),
            ),
            event_refs=() if event_id is None else (event_id,),
            result={
                "task_transition_performed": False,
                "record_digest": record.record_digest,
            },
        )


__all__ = [
    "RuntimeCoordinationKernelApplicationService",
    "RuntimeLeaseAction",
    "RuntimeSignalClaimCommand",
    "RuntimeSignalEnqueueCommand",
    "SessionRuntimeLeaseCommand",
    "build_runtime_signal_payload",
]
