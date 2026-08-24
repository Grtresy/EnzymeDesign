"""Independent bounded worker for durable Standard runtime commands."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from typing import Any

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AgentRuntimeSignal
from openzyme_contracts import AgentRuntimeSignalReason
from openzyme_contracts import AgentRuntimeSignalStatus
from openzyme_contracts import ClockPort
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelRecordQueryPort
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import RuntimeCommandRecord
from openzyme_contracts import RuntimeCommandStatus
from openzyme_contracts import RuntimeCommandType
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import SessionRuntimeLease
from openzyme_contracts import SessionRuntimeLeaseMode
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_kernel import ControlStoreRuntimeOutcomeRepository
from openzyme_kernel import KernelContractError
from openzyme_kernel import RuntimeCoordinationKernelApplicationService
from openzyme_kernel import RuntimeContinuationDeliveryWorker
from openzyme_kernel import RuntimeLeaseAction
from openzyme_kernel import RuntimeSignalClaimCommand
from openzyme_kernel import RuntimeTurnAdmission
from openzyme_kernel import RuntimeTurnBudget
from openzyme_kernel import RuntimeTurnCoordinator
from openzyme_kernel import SessionRuntimeLeaseCommand
from openzyme_kernel.runtime_command_application import RuntimeCommandClaimCommand
from openzyme_kernel.runtime_command_application import (
    RuntimeCommandKernelApplicationService,
)
from openzyme_kernel.runtime_command_application import RuntimeCommandSettlementCommand
from openzyme_kernel.runtime_command_application import observe_runtime_command_failure
from openzyme_runtime_spi import RuntimeCapabilityGateway


class StandardRuntimeTurnAdmissionSource:
    """Structural type kept local to avoid exposing worker mechanisms publicly."""

    def pending_signals(
        self,
        *,
        session_id: str,
        maximum: int,
    ) -> tuple[KernelRecordSnapshot, ...]: ...

    def build_admission(
        self,
        *,
        signal: AgentRuntimeSignal,
        signal_claim_token: str,
        session_lease: SessionRuntimeLease,
        runtime_lease_generation: int,
        command_id: str,
        turn_id: str,
        budget: RuntimeTurnBudget,
        observed_at: str,
    ) -> RuntimeTurnAdmission: ...

    def discard(self, command_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class StandardRuntimeCommandContextFactory:
    """Resolve the current ready root authority for one worker mutation."""

    records: KernelRecordQueryPort
    ids: IdGeneratorPort

    def build(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> KernelCommandContext:
        session = self.records.read(entity_type="session", entity_id=session_id)
        if session is None:
            raise KernelContractError(
                "session_not_found",
                "Runtime command worker requires a canonical Session",
            )
        members = self.records.list_for_session(
            entity_type="agent_member",
            session_id=session_id,
            max_items=64,
        )
        roots = tuple(
            item
            for item in members
            if item.payload.get("role") == "master"
            and item.payload.get("parent_agent_id") is None
            and item.payload.get("status") == "active"
        )
        if len(roots) != 1:
            raise KernelContractError(
                "runtime_command_root_member_ambiguous",
                "Runtime command worker requires one active root Agent",
            )
        member = roots[0]
        lease_id = member.payload.get("active_authority_lease_id")
        lease_record = (
            None
            if not isinstance(lease_id, str)
            else self.records.read(
                entity_type="agent_authority_lease",
                entity_id=lease_id,
            )
        )
        try:
            if lease_record is None:
                raise ValueError("missing")
            authority = AgentAuthorityLease.from_dict(lease_record.payload)
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "runtime_command_root_authority_invalid",
                "Runtime command root Agent lacks closed authority",
            ) from exc
        workspace_generation = member.payload.get("workspace_generation")
        if (
            authority.state is not AgentAuthorityLeaseState.ACTIVE
            or authority.session_id != session_id
            or authority.agent_member_id != member.entity_id
            or authority.workspace_generation != workspace_generation
            or not isinstance(workspace_generation, int)
            or isinstance(workspace_generation, bool)
            or workspace_generation < 1
        ):
            raise KernelContractError(
                "runtime_command_root_authority_stale",
                "Runtime command root authority is pending, stale or not ready",
            )
        binding = _latest_capability_binding(self.records, session_id=session_id)
        return KernelCommandContext(
            command_id=self.ids.new_id(namespace="command"),
            session_id=session_id,
            actor_id=member.entity_id,
            owner_plugin_id="openzyme.kernel",
            authority_lease_id=authority.lease_id,
            authority_generation=authority.generation,
            authority_fence=authority.fence,
            expected_session_version=session.state_version,
            extension_bundle_digest=binding.extension_bundle_digest,
            capability_binding_digest=binding.binding_digest,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            workspace_generation=workspace_generation,
        )

    def derive_settlement(
        self,
        context: KernelCommandContext,
        *,
        idempotency_key: str,
    ) -> KernelCommandContext:
        """Reuse the exact claimed authority without re-running a failed resolver."""

        return replace(
            context,
            command_id=self.ids.new_id(namespace="command"),
            idempotency_key=idempotency_key,
        )


@dataclass(slots=True)
class StandardRuntimeCommandExecutor:
    """Advance one already-claimed runtime command within its admitted bounds."""

    coordination: RuntimeCoordinationKernelApplicationService
    continuations: RuntimeContinuationDeliveryWorker
    turns: RuntimeTurnCoordinator
    outcomes: ControlStoreRuntimeOutcomeRepository
    records: KernelRecordQueryPort
    admissions: StandardRuntimeTurnAdmissionSource
    capability_gateway: RuntimeCapabilityGateway
    contexts: StandardRuntimeCommandContextFactory
    clock: ClockPort
    ids: IdGeneratorPort
    lease_seconds: int = 300
    signal_claim_seconds: int = 120
    max_duration_seconds: int = 300
    max_input_units: int = 64_000
    max_output_units: int = 16_000

    def __post_init__(self) -> None:
        for value in (
            self.lease_seconds,
            self.signal_claim_seconds,
            self.max_duration_seconds,
            self.max_input_units,
            self.max_output_units,
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError("Standard runtime worker budgets must be positive")

    def execute(self, record: RuntimeCommandRecord) -> dict[str, Any]:
        if record.status is not RuntimeCommandStatus.CLAIMED:
            raise KernelContractError(
                "runtime_command_claim_missing",
                "Runtime executor requires a claimed durable command",
            )
        if record.auto_enqueue_ready_tasks:
            raise KernelContractError(
                "runtime_command_auto_enqueue_unsupported",
                "Standard runtime worker does not implement automatic task enqueue",
            )
        pending = self.admissions.pending_signals(
            session_id=record.session_id,
            maximum=record.max_signals,
        )
        if len(pending) > record.max_signals:
            raise KernelContractError(
                "runtime_drain_source_unbounded",
                "Runtime admission source exceeded the admitted signal bound",
            )
        base = self.contexts.build(
            session_id=record.session_id,
            idempotency_key=f"{record.command_id}.continuation-delivery",
            correlation_id=record.command_id,
        )
        continuation_receipts = list(
            self.continuations.tick(
                context=base,
                maximum=record.max_signals,
            )
        )
        if not pending:
            return {
                "processed_signals": 0,
                "turns": [],
                "continuations_queued": len(continuation_receipts),
                "runtime_executed": False,
                "task_transition_performed": False,
                "fallback_performed": False,
            }

        base = self.contexts.build(
            session_id=record.session_id,
            idempotency_key=f"{record.command_id}.runtime-lease.acquire",
            correlation_id=record.command_id,
        )
        runtime_owner_id = f"runtime-owner-{record.command_id}"
        self.coordination.mutate_session_lease(
            SessionRuntimeLeaseCommand(
                context=base,
                action=RuntimeLeaseAction.ACQUIRE,
                owner_id=runtime_owner_id,
                mode=SessionRuntimeLeaseMode.MANUAL_DRAIN,
                lease_seconds=self.lease_seconds,
            )
        )
        lease, lease_generation = self._runtime_lease(record.session_id)
        processed: list[dict[str, object]] = []
        primary_error: BaseException | None = None
        try:
            for index, snapshot in enumerate(pending, start=1):
                signal = _pending_signal(snapshot, session_id=record.session_id)
                claim_context = self.contexts.build(
                    session_id=record.session_id,
                    idempotency_key=(
                        f"{record.command_id}.signal.{signal.signal_id}.claim"
                    ),
                    correlation_id=record.command_id,
                )
                self.coordination.claim_signal(
                    RuntimeSignalClaimCommand(
                        context=claim_context,
                        signal_id=signal.signal_id,
                        runtime_owner_id=runtime_owner_id,
                        runtime_lease_token=lease.lease_token,
                        runtime_lease_generation=lease_generation,
                        runtime_fence=lease.fencing_token,
                        expected_signal_version=snapshot.state_version,
                        claim_seconds=self.signal_claim_seconds,
                    )
                )
                claimed, claim_token = self._claimed_signal(signal.signal_id)
                turn_command_id = self.ids.new_id(namespace="runtime-turn-command")
                admission = self.admissions.build_admission(
                    signal=claimed,
                    signal_claim_token=claim_token,
                    session_lease=lease,
                    runtime_lease_generation=lease_generation,
                    command_id=turn_command_id,
                    turn_id=self.ids.new_id(namespace="runtime-turn"),
                    budget=RuntimeTurnBudget(
                        max_steps=record.max_steps_per_agent,
                        max_duration_seconds=self.max_duration_seconds,
                        max_input_units=self.max_input_units,
                        max_output_units=self.max_output_units,
                    ),
                    observed_at=self.clock.now_iso(),
                )
                turn = self.turns.build_command(admission)
                try:
                    self.outcomes.register_command(
                        turn,
                        tool_exposure_snapshot=admission.tool_exposure_snapshot,
                    )
                    outcome = self.turns.adapter.run_turn(
                        turn,
                        self.capability_gateway,
                    )
                    consumption = self.turns.consume_outcome(
                        turn,
                        outcome,
                        consumed_at=self.clock.now_iso(),
                    )
                finally:
                    self.admissions.discard(turn_command_id)
                processed.append(
                    {
                        "sequence": index,
                        "signal_id": claimed.signal_id,
                        "command_id": turn.command_id,
                        "command_digest": turn.command_digest,
                        "outcome_id": outcome.outcome_id,
                        "outcome_digest": outcome.outcome_digest,
                        "outcome_disposition": outcome.disposition.value,
                        "consumption_digest": consumption.consumption_digest,
                    }
                )
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            try:
                release_context = self.contexts.build(
                    session_id=record.session_id,
                    idempotency_key=f"{record.command_id}.runtime-lease.release",
                    correlation_id=record.command_id,
                )
                self.coordination.mutate_session_lease(
                    SessionRuntimeLeaseCommand(
                        context=release_context,
                        action=RuntimeLeaseAction.RELEASE,
                        owner_id=runtime_owner_id,
                        mode=SessionRuntimeLeaseMode.MANUAL_DRAIN,
                        lease_seconds=self.lease_seconds,
                        expected_lease_token=lease.lease_token,
                        expected_generation=lease_generation,
                        expected_fence=lease.fencing_token,
                    )
                )
            except Exception as release_error:
                if primary_error is None:
                    raise
                primary_error.add_note(
                    f"runtime lease release also failed: {type(release_error).__name__}"
                )
        remaining_continuations = record.max_signals - len(continuation_receipts)
        if remaining_continuations:
            continuation_receipts.extend(
                self.continuations.tick(
                    context=base,
                    maximum=remaining_continuations,
                )
            )
        return {
            "processed_signals": len(processed),
            "turns": processed,
            "continuations_queued": len(continuation_receipts),
            "runtime_executed": bool(processed),
            "task_transition_performed": False,
            "fallback_performed": False,
        }

    def _runtime_lease(self, session_id: str) -> tuple[SessionRuntimeLease, int]:
        snapshot = self.records.read(
            entity_type="session_runtime_lease",
            entity_id=session_id,
        )
        if snapshot is None:
            raise KernelContractError(
                "runtime_lease_missing",
                "Runtime lease mutation produced no canonical lease",
            )
        try:
            generation = _positive(snapshot.payload.get("generation"), "generation")
            return _runtime_lease(snapshot.payload), generation
        except (KeyError, TypeError, ValueError) as exc:
            raise KernelContractError(
                "runtime_lease_invalid",
                "Canonical runtime lease is invalid",
            ) from exc

    def _claimed_signal(self, signal_id: str) -> tuple[AgentRuntimeSignal, str]:
        snapshot = self.records.read(
            entity_type="agent_runtime_signal",
            entity_id=signal_id,
        )
        if snapshot is None:
            raise KernelContractError(
                "runtime_signal_missing",
                "Claimed runtime signal is absent",
            )
        try:
            signal = _runtime_signal(snapshot.payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise KernelContractError(
                "runtime_signal_invalid",
                "Claimed runtime signal is invalid",
            ) from exc
        claim_token = snapshot.payload.get("claim_token")
        if (
            signal.status is not AgentRuntimeSignalStatus.CLAIMED
            or not isinstance(claim_token, str)
            or not claim_token
        ):
            raise KernelContractError(
                "runtime_signal_claim_missing",
                "Runtime signal claim did not become canonical",
            )
        return signal, claim_token


@dataclass(slots=True)
class StandardRuntimeCommandWorker:
    """Claim, execute and settle one caller-selected durable occurrence."""

    application: RuntimeCommandKernelApplicationService
    records: KernelRecordQueryPort
    executor: StandardRuntimeCommandExecutor
    contexts: StandardRuntimeCommandContextFactory
    clock: ClockPort
    worker_id: str = "openzyme-standard-runtime-worker"
    claim_seconds: int = 600

    def __post_init__(self) -> None:
        if not self.worker_id:
            raise ValueError("runtime command worker_id must be non-empty")
        if (
            not isinstance(self.claim_seconds, int)
            or isinstance(self.claim_seconds, bool)
            or self.claim_seconds < 1
        ):
            raise ValueError("runtime command claim_seconds must be positive")

    def tick(
        self,
        *,
        session_id: str,
        maximum: int = 1,
    ) -> tuple[KernelMutationReceipt, ...]:
        if (
            not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or not 1 <= maximum <= 64
        ):
            raise ValueError("runtime command tick maximum must be between 1 and 64")
        candidates = tuple(
            item
            for item in sorted(
                self.records.list_for_session(
                    entity_type="runtime_command",
                    session_id=session_id,
                    max_items=512,
                ),
                key=lambda item: (
                    str(item.payload.get("accepted_at", "")),
                    item.entity_id,
                ),
            )
            if _claimable(item, now=self.clock.now_iso())
        )[:maximum]
        return tuple(self.run(runtime_command_id=item.entity_id) for item in candidates)

    def run(self, *, runtime_command_id: str) -> KernelMutationReceipt:
        snapshot = self.records.read(
            entity_type="runtime_command",
            entity_id=runtime_command_id,
        )
        if snapshot is None:
            raise KernelContractError(
                "runtime_command_not_found",
                "Runtime worker requires an exact durable command",
            )
        current = _runtime_command(snapshot)
        claim_context = self.contexts.build(
            session_id=current.session_id,
            idempotency_key=(f"{current.command_id}.claim.{current.fencing_token + 1}"),
            correlation_id=current.command_id,
        )
        self.application.claim(
            RuntimeCommandClaimCommand(
                context=claim_context,
                runtime_command_id=current.command_id,
                claim_owner=self.worker_id,
                expected_state_version=current.state_version,
                claim_seconds=self.claim_seconds,
            )
        )
        claimed_snapshot = self.records.read(
            entity_type="runtime_command",
            entity_id=current.command_id,
        )
        if claimed_snapshot is None:
            raise KernelContractError(
                "runtime_command_not_found",
                "Claimed runtime command disappeared",
            )
        claimed = _runtime_command(claimed_snapshot)
        assert claimed.claim_owner is not None
        assert claimed.lease_token is not None
        try:
            summary = self.executor.execute(claimed)
        except Exception as exc:
            return self._settle_failure(
                claimed,
                exc,
                claim_context=claim_context,
            )
        return self.application.settle(
            RuntimeCommandSettlementCommand(
                context=self.contexts.derive_settlement(
                    claim_context,
                    idempotency_key=f"{claimed.command_id}.settle.completed",
                ),
                runtime_command_id=claimed.command_id,
                claim_owner=claimed.claim_owner,
                lease_token=claimed.lease_token,
                fencing_token=claimed.fencing_token,
                expected_state_version=claimed.state_version,
                status=RuntimeCommandStatus.COMPLETED,
                bounded_outcome_summary=summary,
            )
        )

    def _settle_failure(
        self,
        claimed: RuntimeCommandRecord,
        error: Exception,
        *,
        claim_context: KernelCommandContext,
    ) -> KernelMutationReceipt:
        assert claimed.claim_owner is not None
        assert claimed.lease_token is not None
        code = (
            error.code
            if isinstance(error, KernelContractError)
            else "standard_runtime_command_execution_failed"
        )
        phase = _failure_phase(code)
        effect_certainty = (
            ExternalEffectCertainty.NO_EFFECT
            if phase == "runtime_context_projection"
            else ExternalEffectCertainty.DISPATCH_IN_DOUBT
        )
        safe_summary = (
            "The Standard runtime context failed before provider invocation"
            if phase == "runtime_context_projection"
            else (
                "The bounded Standard runtime command failed without a terminal "
                "effect observation"
            )
        )
        safe_hint = (
            "Inspect the canonical diagnostic; no provider, tool or fallback ran"
            if phase == "runtime_context_projection"
            else (
                "Reconcile the exact command occurrence before any successor; no "
                "automatic retry or fallback occurred"
            )
        )
        failure_records = observe_runtime_command_failure(
            error,
            record=claimed,
            component="openzyme.standard.runtime_worker",
            phase=phase,
            created_at=self.clock.now_iso(),
            error_code=code,
            safe_summary=safe_summary,
            safe_hint=safe_hint,
            effect_certainty=effect_certainty,
            correlation_id=claimed.command_id,
        )
        try:
            return self.application.settle(
                RuntimeCommandSettlementCommand(
                    context=self.contexts.derive_settlement(
                        claim_context,
                        idempotency_key=f"{claimed.command_id}.settle.failed",
                    ),
                    runtime_command_id=claimed.command_id,
                    claim_owner=claimed.claim_owner,
                    lease_token=claimed.lease_token,
                    fencing_token=claimed.fencing_token,
                    expected_state_version=claimed.state_version,
                    status=RuntimeCommandStatus.FAILED,
                    bounded_outcome_summary={
                        "processed_signals": 0,
                        "turns": [],
                        "runtime_executed": False,
                        "task_transition_performed": False,
                        "fallback_performed": False,
                    },
                    error_code=code,
                    safe_error_summary=safe_summary,
                    safe_retry_hint=safe_hint,
                    failure_records=failure_records,
                )
            )
        except Exception as settlement_error:
            error.add_note(
                "runtime command failure settlement also failed: "
                f"{type(settlement_error).__name__}"
            )
            raise error from settlement_error


def _failure_phase(error_code: str) -> str:
    if error_code.startswith(
        (
            "runtime_context_",
            "runtime_turn_command_",
            "workflow_authority_",
            "tool_exposure_",
        )
    ):
        return "runtime_context_projection"
    return "runtime_command_execution"


def _latest_capability_binding(
    records: KernelRecordQueryPort,
    *,
    session_id: str,
) -> SessionCapabilityBindingRevision:
    snapshots = records.list_for_session(
        entity_type="session_capability_binding_revision",
        session_id=session_id,
        max_items=64,
    )
    try:
        bindings = tuple(
            SessionCapabilityBindingRevision.from_dict(item.payload)
            for item in snapshots
        )
    except (TypeError, ValueError) as exc:
        raise KernelContractError(
            "runtime_command_capability_binding_invalid",
            "Runtime command Session capability binding is invalid",
        ) from exc
    if not bindings:
        raise KernelContractError(
            "runtime_command_capability_binding_missing",
            "Runtime command Session capability binding is absent",
        )
    revision = max(item.revision for item in bindings)
    latest = tuple(item for item in bindings if item.revision == revision)
    if len(latest) != 1:
        raise KernelContractError(
            "runtime_command_capability_binding_ambiguous",
            "Latest runtime command capability binding is ambiguous",
        )
    return latest[0]


def _claimable(snapshot: KernelRecordSnapshot, *, now: str) -> bool:
    record = _runtime_command(snapshot)
    if record.status is RuntimeCommandStatus.ACCEPTED:
        return True
    return bool(
        record.status is RuntimeCommandStatus.CLAIMED
        and record.lease_expires_at is not None
        and _instant(record.lease_expires_at) <= _instant(now)
    )


def _runtime_command(snapshot: KernelRecordSnapshot) -> RuntimeCommandRecord:
    payload = snapshot.payload
    try:
        summary = payload.get("bounded_outcome_summary")
        return RuntimeCommandRecord(
            command_id=_required_text(payload, "command_id"),
            session_id=_required_text(payload, "session_id"),
            command_type=RuntimeCommandType(_required_text(payload, "command_type")),
            request_digest=_required_text(payload, "request_digest"),
            idempotency_key=_required_text(payload, "idempotency_key"),
            status=RuntimeCommandStatus(_required_text(payload, "status")),
            max_signals=_positive(payload.get("max_signals"), "max_signals"),
            max_steps_per_agent=_positive(
                payload.get("max_steps_per_agent"),
                "max_steps_per_agent",
            ),
            auto_enqueue_ready_tasks=_required_boolean(
                payload,
                "auto_enqueue_ready_tasks",
            ),
            state_version=_positive(payload.get("state_version"), "state_version"),
            fencing_token=_non_negative(payload, "fencing_token"),
            accepted_at=_required_text(payload, "accepted_at"),
            claim_owner=_optional_text(payload.get("claim_owner")),
            lease_token=_optional_text(payload.get("lease_token")),
            lease_expires_at=_optional_text(payload.get("lease_expires_at")),
            bounded_outcome_summary=(
                None if summary is None else dict(summary)  # type: ignore[arg-type]
            ),
            failure_id=_optional_text(payload.get("failure_id")),
            diagnostic_id=_optional_text(payload.get("diagnostic_id")),
            error_code=_optional_text(payload.get("error_code")),
            safe_error_summary=_optional_text(payload.get("safe_error_summary")),
            safe_retry_hint=_optional_text(payload.get("safe_retry_hint")),
            started_at=_optional_text(payload.get("started_at")),
            completed_at=_optional_text(payload.get("completed_at")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise KernelContractError(
            "runtime_command_record_invalid",
            "Canonical runtime command is invalid",
        ) from exc


def _required_text(payload: Any, field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be exact non-empty text")
    return value


def _required_boolean(payload: Any, field_name: str) -> bool:
    value = payload.get(field_name)
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be boolean")
    return value


def _non_negative(payload: Any, field_name: str) -> int:
    value = payload.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _pending_signal(
    snapshot: KernelRecordSnapshot,
    *,
    session_id: str,
) -> AgentRuntimeSignal:
    if snapshot.entity_type != "agent_runtime_signal":
        raise KernelContractError(
            "runtime_signal_source_invalid",
            "Runtime admission source returned another entity type",
        )
    try:
        signal = _runtime_signal(snapshot.payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise KernelContractError(
            "runtime_signal_invalid",
            "Pending runtime signal is invalid",
        ) from exc
    if (
        signal.session_id != session_id
        or signal.status is not AgentRuntimeSignalStatus.PENDING
    ):
        raise KernelContractError(
            "runtime_signal_source_stale",
            "Runtime admission source returned a stale signal",
        )
    return signal


def _runtime_lease(payload: Any) -> SessionRuntimeLease:
    return SessionRuntimeLease(
        session_id=str(payload["session_id"]),
        owner_id=str(payload["owner_id"]),
        lease_token=str(payload["lease_token"]),
        mode=SessionRuntimeLeaseMode(str(payload["mode"])),
        acquired_at=str(payload["acquired_at"]),
        heartbeat_at=str(payload["heartbeat_at"]),
        expires_at=str(payload["expires_at"]),
        fencing_token=int(payload["fencing_token"]),
        released_at=(
            None if payload.get("released_at") is None else str(payload["released_at"])
        ),
        last_error=(
            None if payload.get("last_error") is None else str(payload["last_error"])
        ),
    )


def _runtime_signal(payload: Any) -> AgentRuntimeSignal:
    return AgentRuntimeSignal(
        signal_id=str(payload["signal_id"]),
        session_id=str(payload["session_id"]),
        agent_id=str(payload["agent_id"]),
        reason=AgentRuntimeSignalReason(str(payload["reason"])),
        status=AgentRuntimeSignalStatus(str(payload["status"])),
        created_at=str(payload["created_at"]),
        task_id=None if payload.get("task_id") is None else str(payload["task_id"]),
        lane_id=None if payload.get("lane_id") is None else str(payload["lane_id"]),
        correlation_id=(
            None
            if payload.get("correlation_id") is None
            else str(payload["correlation_id"])
        ),
        source_ref=(
            None if payload.get("source_ref") is None else str(payload["source_ref"])
        ),
        claimed_at=(
            None if payload.get("claimed_at") is None else str(payload["claimed_at"])
        ),
        claimed_by=(
            None if payload.get("claimed_by") is None else str(payload["claimed_by"])
        ),
        claim_expires_at=(
            None
            if payload.get("claim_expires_at") is None
            else str(payload["claim_expires_at"])
        ),
        attempt_count=int(payload.get("attempt_count", 0)),
        completed_at=(
            None
            if payload.get("completed_at") is None
            else str(payload["completed_at"])
        ),
        error_message=(
            None
            if payload.get("error_message") is None
            else str(payload["error_message"])
        ),
        last_error=(
            None if payload.get("last_error") is None else str(payload["last_error"])
        ),
        session_lease_token=(
            None
            if payload.get("session_lease_token") is None
            else str(payload["session_lease_token"])
        ),
        session_fencing_token=(
            None
            if payload.get("session_fencing_token") is None
            else int(payload["session_fencing_token"])
        ),
        capability_lease_id=(
            None
            if payload.get("capability_lease_id") is None
            else str(payload["capability_lease_id"])
        ),
        workspace_generation=(
            None
            if payload.get("workspace_generation") is None
            else int(payload["workspace_generation"])
        ),
    )


def _positive(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("optional runtime command field must be text")
    return value


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("runtime command time must include a timezone")
    return parsed


__all__ = [
    "StandardRuntimeCommandContextFactory",
    "StandardRuntimeCommandExecutor",
    "StandardRuntimeCommandWorker",
]
