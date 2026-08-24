"""Durable admission, claim and settlement for explicit runtime commands.

The public runtime-drain request only admits one bounded occurrence.  A separate
Distribution-owned worker claims that occurrence and invokes the runtime.  This
module owns the canonical command lifecycle and deliberately has no dependency on
an Agent runtime Adapter or scheduler implementation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from typing import Any

from openzyme_contracts import ClockPort
from openzyme_contracts import ControlStorePort
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import FailureActorKind
from openzyme_contracts import FailureClass
from openzyme_contracts import FailureRecoverability
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordReaderPort
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import RuntimeCommandRecord
from openzyme_contracts import RuntimeCommandStatus
from openzyme_contracts import RuntimeCommandType
from openzyme_contracts import RetryEligibility
from openzyme_contracts import StructuredFailureContext
from openzyme_contracts import StructuredFailureRecords
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_json_bytes
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import observe_structured_failure
from openzyme_contracts import require_identifier
from openzyme_contracts import validate_failure_diagnostic_pair
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelMutationReceipt

from .errors import KernelContractError


_ENTITY_TYPE = "runtime_command"
_MAX_SIGNALS = 64
_MAX_STEPS_PER_AGENT = 128
_MAX_OUTCOME_SUMMARY_BYTES = 64 * 1024
_MAX_SAFE_TEXT_LENGTH = 8_192


def _positive_bounded(value: int, *, field_name: str, maximum: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= maximum
    ):
        raise ValueError(f"{field_name} must be between 1 and {maximum}")


def _instant(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise KernelContractError(
            "runtime_command_time_invalid",
            f"{field_name} must be a timezone-aware ISO-8601 instant",
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise KernelContractError(
            "runtime_command_time_invalid",
            f"{field_name} must include a timezone",
        )
    return parsed


def _after(value: str, seconds: int) -> str:
    return (_instant(value, field_name="now") + timedelta(seconds=seconds)).isoformat()


def runtime_command_id(*, session_id: str, idempotency_key: str) -> str:
    """Derive a restart-stable command identity from the idempotency scope."""

    require_identifier(session_id, field_name="session_id")
    require_identifier(idempotency_key, field_name="idempotency_key")
    digest = canonical_sha256_digest(
        {
            "schema_version": "runtime_command_identity@1",
            "session_id": session_id,
            "command_type": RuntimeCommandType.RUNTIME_DRAIN.value,
            "idempotency_key": idempotency_key,
        }
    )
    return "runtime-command-" + digest.removeprefix("sha256:")[:32]


def observe_runtime_command_failure(
    error: BaseException,
    *,
    record: RuntimeCommandRecord,
    component: str,
    phase: str,
    created_at: str,
    error_code: str,
    safe_summary: str,
    safe_hint: str,
    effect_certainty: ExternalEffectCertainty,
    correlation_id: str | None = None,
) -> StructuredFailureRecords:
    """Build one restart-stable outer-command diagnostic occurrence.

    The identity is derived from the exact command claim fence so a worker that
    loses the settlement response cannot mint a second diagnostic occurrence.
    """

    require_identifier(component, field_name="component")
    require_identifier(phase, field_name="phase")
    require_identifier(error_code, field_name="error_code")
    identity_digest = canonical_sha256_digest(
        {
            "schema_version": "runtime_command_failure_identity@1",
            "runtime_command_id": record.command_id,
            "session_id": record.session_id,
            "fencing_token": record.fencing_token,
            "source_version": canonical_sha256_digest(record.to_dict()),
        }
    ).removeprefix("sha256:")[:32]
    reconcile_required = effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
    return observe_structured_failure(
        error,
        context=StructuredFailureContext(
            failure_id=f"failure-runtime-command-{identity_digest}",
            diagnostic_id=f"diagnostic-runtime-command-{identity_digest}",
            session_id=record.session_id,
            component=component,
            operation="runtime_command_execute",
            phase=phase,
            source_kind=_ENTITY_TYPE,
            source_ref=record.command_id,
            source_version=canonical_sha256_digest(record.to_dict()),
            created_at=created_at,
            correlation_id=correlation_id,
        ),
        failure_class=(
            FailureClass.HARNESS
            if phase == "runtime_context_projection"
            else FailureClass.RUNTIME
        ),
        recoverability=(
            FailureRecoverability.RECONCILIATION_REQUIRED
            if reconcile_required
            else FailureRecoverability.TERMINAL
        ),
        effect_certainty=effect_certainty,
        retry_eligibility=(
            RetryEligibility.RECONCILE_REQUIRED
            if reconcile_required
            else RetryEligibility.TERMINAL
        ),
        actor_kind=FailureActorKind.SYSTEM,
        error_code=error_code,
        safe_summary=safe_summary,
        safe_hint=safe_hint,
        next_action=(
            "reconcile_runtime_command"
            if reconcile_required
            else "inspect_runtime_command_diagnostic"
        ),
        mutation_applied=None if reconcile_required else False,
        fallback_performed=False,
        reconcile_required=reconcile_required,
        retry_performed=False,
        identities={
            "command_id": record.command_id,
            "session_id": record.session_id,
        },
        private_context={
            "runtime_command_id": record.command_id,
            "fencing_token": record.fencing_token,
            "claim_owner": record.claim_owner,
        },
    )


@dataclass(frozen=True, slots=True)
class RuntimeCommandAdmissionCommand:
    context: KernelCommandContext
    max_signals: int
    max_steps_per_agent: int
    auto_enqueue_ready_tasks: bool = False

    def __post_init__(self) -> None:
        _positive_bounded(
            self.max_signals,
            field_name="max_signals",
            maximum=_MAX_SIGNALS,
        )
        _positive_bounded(
            self.max_steps_per_agent,
            field_name="max_steps_per_agent",
            maximum=_MAX_STEPS_PER_AGENT,
        )
        if not isinstance(self.auto_enqueue_ready_tasks, bool):
            raise ValueError("auto_enqueue_ready_tasks must be boolean")


@dataclass(frozen=True, slots=True)
class RuntimeCommandClaimCommand:
    context: KernelCommandContext
    runtime_command_id: str
    claim_owner: str
    expected_state_version: int
    claim_seconds: int

    def __post_init__(self) -> None:
        require_identifier(self.runtime_command_id, field_name="runtime_command_id")
        require_identifier(self.claim_owner, field_name="claim_owner")
        _positive_bounded(
            self.expected_state_version,
            field_name="expected_state_version",
            maximum=2**63 - 1,
        )
        _positive_bounded(
            self.claim_seconds,
            field_name="claim_seconds",
            maximum=86_400,
        )


@dataclass(frozen=True, slots=True)
class RuntimeCommandSettlementCommand:
    context: KernelCommandContext
    runtime_command_id: str
    claim_owner: str
    lease_token: str
    fencing_token: int
    expected_state_version: int
    status: RuntimeCommandStatus
    bounded_outcome_summary: Mapping[str, Any]
    error_code: str | None = None
    safe_error_summary: str | None = None
    safe_retry_hint: str | None = None
    failure_records: StructuredFailureRecords | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "runtime_command_id",
            "claim_owner",
            "lease_token",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        _positive_bounded(
            self.fencing_token,
            field_name="fencing_token",
            maximum=2**63 - 1,
        )
        _positive_bounded(
            self.expected_state_version,
            field_name="expected_state_version",
            maximum=2**63 - 1,
        )
        if self.status not in {
            RuntimeCommandStatus.COMPLETED,
            RuntimeCommandStatus.FAILED,
            RuntimeCommandStatus.LOCKED,
            RuntimeCommandStatus.CANCELLED,
        }:
            raise ValueError("runtime command settlement status must be terminal")
        if not isinstance(self.bounded_outcome_summary, Mapping):
            raise ValueError("bounded_outcome_summary must be an object")
        if len(canonical_json_bytes(self.bounded_outcome_summary)) > (
            _MAX_OUTCOME_SUMMARY_BYTES
        ):
            raise ValueError("bounded_outcome_summary exceeds its closed byte bound")
        for field_name in (
            "safe_error_summary",
            "safe_retry_hint",
        ):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value) > _MAX_SAFE_TEXT_LENGTH
            ):
                raise ValueError(f"{field_name} must be bounded non-empty text or null")
        if self.error_code is not None:
            require_identifier(self.error_code, field_name="error_code")
        if self.status is RuntimeCommandStatus.COMPLETED:
            if any(
                value is not None
                for value in (
                    self.error_code,
                    self.safe_error_summary,
                    self.safe_retry_hint,
                )
            ):
                raise ValueError("completed runtime command cannot carry an error")
            if self.failure_records is not None:
                raise ValueError(
                    "completed runtime command cannot carry failure records"
                )
        elif self.error_code is None or self.safe_error_summary is None:
            raise ValueError(
                "non-success terminal runtime command requires a safe error"
            )
        if self.status is RuntimeCommandStatus.FAILED:
            if self.failure_records is None:
                raise ValueError(
                    "failed runtime command requires public/private failure records"
                )
            validate_failure_diagnostic_pair(
                self.failure_records.public,
                self.failure_records.private,
            )
            failure = self.failure_records.public
            if (
                failure.failure_id != self.failure_records.private.failure_id
                or failure.session_id != self.context.session_id
                or failure.source_kind != _ENTITY_TYPE
                or failure.source_ref != self.runtime_command_id
                or failure.error_code != self.error_code
                or failure.safe_summary != self.safe_error_summary
                or failure.safe_hint != self.safe_retry_hint
                or failure.fallback_performed
            ):
                raise ValueError(
                    "runtime command failure records differ from the settlement"
                )
        elif self.failure_records is not None:
            raise ValueError(
                "only failed runtime command settlement may carry failure records"
            )


class RuntimeCommandKernelApplicationService:
    """Own the durable explicit runtime-command state machine."""

    service_id = "openzyme.kernel.runtime-command"

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

    def admit(
        self,
        command: RuntimeCommandAdmissionCommand,
    ) -> KernelMutationReceipt:
        context = command.context
        identity = runtime_command_id(
            session_id=context.session_id,
            idempotency_key=context.idempotency_key,
        )
        request_digest = canonical_sha256_digest(
            {
                "schema_version": "runtime_command_request@1",
                "session_id": context.session_id,
                "command_type": RuntimeCommandType.RUNTIME_DRAIN.value,
                "max_signals": command.max_signals,
                "max_steps_per_agent": command.max_steps_per_agent,
                "auto_enqueue_ready_tasks": command.auto_enqueue_ready_tasks,
            }
        )
        now = self._clock.now_iso()
        record = RuntimeCommandRecord(
            command_id=identity,
            session_id=context.session_id,
            command_type=RuntimeCommandType.RUNTIME_DRAIN,
            request_digest=request_digest,
            idempotency_key=context.idempotency_key,
            status=RuntimeCommandStatus.ACCEPTED,
            max_signals=command.max_signals,
            max_steps_per_agent=command.max_steps_per_agent,
            auto_enqueue_ready_tasks=command.auto_enqueue_ready_tasks,
            state_version=1,
            fencing_token=0,
            accepted_at=now,
        )
        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "operation": "admit",
                "context": context.to_dict(),
                "record": record.to_dict(),
            }
        )
        unit = self._store.begin(self._uow(context, command_digest))
        try:
            self._require_session(unit, context)
            existing = unit.read(entity_type=_ENTITY_TYPE, entity_id=identity)
            if existing is not None:
                current = _record(existing)
                if (
                    current.session_id != context.session_id
                    or current.idempotency_key != context.idempotency_key
                    or current.request_digest != request_digest
                ):
                    raise KernelContractError(
                        "runtime_command_idempotency_collision",
                        "Runtime command idempotency identity was reused for another request",
                    )
                unit.rollback()
                return self._receipt(
                    context=context,
                    operation="admit",
                    record=existing,
                    mutation_applied=False,
                    effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                    result=_admission_result(current),
                )
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.CREATE,
                    entity_type=_ENTITY_TYPE,
                    entity_id=identity,
                    expected_state_version=None,
                    payload=record.to_dict(),
                )
            )
            event = self._event(
                unit,
                context=context,
                event_type="runtime.command.accepted",
                record=record,
                payload={
                    "runtime_command_id": identity,
                    "request_digest": request_digest,
                    "max_signals": command.max_signals,
                    "max_steps_per_agent": command.max_steps_per_agent,
                    "auto_enqueue_ready_tasks": command.auto_enqueue_ready_tasks,
                    "runtime_executed": False,
                    "task_transition_performed": False,
                    "fallback_performed": False,
                },
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        snapshot = _snapshot(record)
        return self._receipt(
            context=context,
            operation="admit",
            record=snapshot,
            mutation_applied=committed.committed,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            result=_admission_result(record),
            event_id=event.event_id,
        )

    def claim(self, command: RuntimeCommandClaimCommand) -> KernelMutationReceipt:
        context = command.context
        unit = self._store.begin(
            self._uow(
                context,
                canonical_sha256_digest(
                    {
                        "service_id": self.service_id,
                        "operation": "claim",
                        "context": context.to_dict(),
                        "runtime_command_id": command.runtime_command_id,
                        "claim_owner": command.claim_owner,
                        "expected_state_version": command.expected_state_version,
                        "claim_seconds": command.claim_seconds,
                    }
                ),
            )
        )
        try:
            self._require_session(unit, context)
            current_snapshot = unit.read(
                entity_type=_ENTITY_TYPE,
                entity_id=command.runtime_command_id,
            )
            if current_snapshot is None:
                raise KernelContractError(
                    "runtime_command_not_found",
                    "Runtime command claim requires an exact durable occurrence",
                )
            current = _record(current_snapshot)
            self._require_same_session(current, context)
            now = self._clock.now_iso()
            if current.status.is_terminal:
                raise KernelContractError(
                    "runtime_command_terminal",
                    "Terminal runtime command cannot be claimed",
                )
            if current_snapshot.state_version != command.expected_state_version:
                if _claim_is_current(current, command, now=now):
                    unit.rollback()
                    return self._receipt(
                        context=context,
                        operation="claim",
                        record=current_snapshot,
                        mutation_applied=False,
                        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                        result=_claim_result(current),
                    )
                raise KernelContractError(
                    "runtime_command_stale",
                    "Runtime command changed before claim",
                )
            if current.status is RuntimeCommandStatus.CLAIMED:
                assert current.lease_expires_at is not None
                if _instant(current.lease_expires_at, field_name="lease_expires_at") > (
                    _instant(now, field_name="now")
                ):
                    if current.claim_owner == command.claim_owner:
                        unit.rollback()
                        return self._receipt(
                            context=context,
                            operation="claim",
                            record=current_snapshot,
                            mutation_applied=False,
                            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                            result=_claim_result(current),
                        )
                    raise KernelContractError(
                        "runtime_command_claim_busy",
                        "Another worker owns the unexpired runtime command claim",
                    )
            next_fence = current.fencing_token + 1
            lease_token = _lease_token(
                runtime_command_id=current.command_id,
                claim_owner=command.claim_owner,
                fencing_token=next_fence,
            )
            claimed = RuntimeCommandRecord(
                command_id=current.command_id,
                session_id=current.session_id,
                command_type=current.command_type,
                request_digest=current.request_digest,
                idempotency_key=current.idempotency_key,
                status=RuntimeCommandStatus.CLAIMED,
                max_signals=current.max_signals,
                max_steps_per_agent=current.max_steps_per_agent,
                auto_enqueue_ready_tasks=current.auto_enqueue_ready_tasks,
                state_version=current.state_version + 1,
                fencing_token=next_fence,
                accepted_at=current.accepted_at,
                claim_owner=command.claim_owner,
                lease_token=lease_token,
                lease_expires_at=_after(now, command.claim_seconds),
                failure_id=current.failure_id,
                diagnostic_id=current.diagnostic_id,
                started_at=current.started_at or now,
            )
            self._stage_replace(unit, current_snapshot, claimed)
            event = self._event(
                unit,
                context=context,
                event_type="runtime.command.claimed",
                record=claimed,
                payload={
                    "runtime_command_id": claimed.command_id,
                    "claim_owner": claimed.claim_owner,
                    "fencing_token": claimed.fencing_token,
                    "lease_expires_at": claimed.lease_expires_at,
                    "runtime_executed": False,
                    "task_transition_performed": False,
                    "fallback_performed": False,
                },
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        snapshot = _snapshot(claimed)
        return self._receipt(
            context=context,
            operation="claim",
            record=snapshot,
            mutation_applied=committed.committed,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            result=_claim_result(claimed),
            event_id=event.event_id,
        )

    def settle(
        self,
        command: RuntimeCommandSettlementCommand,
    ) -> KernelMutationReceipt:
        context = command.context
        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "operation": "settle",
                "context": context.to_dict(),
                "runtime_command_id": command.runtime_command_id,
                "claim_owner": command.claim_owner,
                "lease_token": command.lease_token,
                "fencing_token": command.fencing_token,
                "expected_state_version": command.expected_state_version,
                "status": command.status.value,
                "bounded_outcome_summary": command.bounded_outcome_summary,
                "error_code": command.error_code,
                "safe_error_summary": command.safe_error_summary,
                "safe_retry_hint": command.safe_retry_hint,
                "failure_records": (
                    None
                    if command.failure_records is None
                    else {
                        "public": command.failure_records.public.to_internal_dict(),
                        "private": command.failure_records.private.to_dict(),
                    }
                ),
            }
        )
        unit = self._store.begin(self._uow(context, command_digest))
        try:
            self._require_session(unit, context)
            current_snapshot = unit.read(
                entity_type=_ENTITY_TYPE,
                entity_id=command.runtime_command_id,
            )
            if current_snapshot is None:
                raise KernelContractError(
                    "runtime_command_not_found",
                    "Runtime command settlement requires an exact durable occurrence",
                )
            current = _record(current_snapshot)
            self._require_same_session(current, context)
            if current.status.is_terminal:
                if _settlement_is_duplicate(current, command):
                    unit.rollback()
                    return self._receipt(
                        context=context,
                        operation="settle",
                        record=current_snapshot,
                        mutation_applied=False,
                        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                        result=_settlement_result(current),
                    )
                raise KernelContractError(
                    "runtime_command_terminal_collision",
                    "Terminal runtime command differs from this settlement",
                )
            if (
                current_snapshot.state_version != command.expected_state_version
                or current.status is not RuntimeCommandStatus.CLAIMED
                or current.claim_owner != command.claim_owner
                or current.lease_token != command.lease_token
                or current.fencing_token != command.fencing_token
            ):
                raise KernelContractError(
                    "runtime_command_fence_stale",
                    "Runtime command settlement has a stale claim or fence",
                )
            assert current.lease_expires_at is not None
            now = self._clock.now_iso()
            if _instant(now, field_name="now") >= _instant(
                current.lease_expires_at,
                field_name="lease_expires_at",
            ):
                raise KernelContractError(
                    "runtime_command_claim_expired",
                    "Runtime command claim expired before settlement",
                )
            if command.failure_records is not None:
                self._stage_failure_records(
                    unit,
                    current=current,
                    records=command.failure_records,
                )
            terminal = RuntimeCommandRecord(
                command_id=current.command_id,
                session_id=current.session_id,
                command_type=current.command_type,
                request_digest=current.request_digest,
                idempotency_key=current.idempotency_key,
                status=command.status,
                max_signals=current.max_signals,
                max_steps_per_agent=current.max_steps_per_agent,
                auto_enqueue_ready_tasks=current.auto_enqueue_ready_tasks,
                state_version=current.state_version + 1,
                fencing_token=current.fencing_token,
                accepted_at=current.accepted_at,
                claim_owner=current.claim_owner,
                lease_token=current.lease_token,
                lease_expires_at=current.lease_expires_at,
                bounded_outcome_summary=dict(command.bounded_outcome_summary),
                failure_id=(
                    None
                    if command.failure_records is None
                    else command.failure_records.public.failure_id
                ),
                diagnostic_id=(
                    None
                    if command.failure_records is None
                    else command.failure_records.public.diagnostic_id
                ),
                error_code=command.error_code,
                safe_error_summary=command.safe_error_summary,
                safe_retry_hint=command.safe_retry_hint,
                started_at=current.started_at,
                completed_at=now,
            )
            self._stage_replace(unit, current_snapshot, terminal)
            event = self._event(
                unit,
                context=context,
                event_type=f"runtime.command.{terminal.status.value}",
                record=terminal,
                payload={
                    "runtime_command_id": terminal.command_id,
                    "status": terminal.status.value,
                    "outcome_summary_digest": canonical_sha256_digest(
                        terminal.bounded_outcome_summary
                    ),
                    "runtime_executed": bool(
                        terminal.bounded_outcome_summary.get("runtime_executed", False)
                    ),
                    "task_transition_performed": bool(
                        terminal.bounded_outcome_summary.get(
                            "task_transition_performed",
                            False,
                        )
                    ),
                    "fallback_performed": False,
                    "failure_id": terminal.failure_id,
                    "diagnostic_id": terminal.diagnostic_id,
                },
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        snapshot = _snapshot(terminal)
        return self._receipt(
            context=context,
            operation="settle",
            record=snapshot,
            mutation_applied=committed.committed,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            result=_settlement_result(terminal),
            event_id=event.event_id,
        )

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
    def _require_session(unit: Any, context: KernelCommandContext) -> None:
        session = unit.read(entity_type="session", entity_id=context.session_id)
        if session is None:
            raise KernelContractError(
                "session_not_found",
                "Runtime command requires a canonical Session",
            )
        if session.state_version != context.expected_session_version:
            raise KernelContractError(
                "session_state_version_stale",
                "Session changed before runtime command mutation",
            )

    @staticmethod
    def _require_same_session(
        record: RuntimeCommandRecord,
        context: KernelCommandContext,
    ) -> None:
        if record.session_id != context.session_id:
            raise KernelContractError(
                "runtime_command_session_mismatch",
                "Runtime command belongs to another Session",
            )

    def _stage_replace(
        self,
        unit: Any,
        current: KernelRecordSnapshot,
        next_record: RuntimeCommandRecord,
    ) -> None:
        unit.stage(
            KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.REPLACE,
                entity_type=_ENTITY_TYPE,
                entity_id=current.entity_id,
                expected_state_version=current.state_version,
                payload=next_record.to_dict(),
            )
        )

    def _stage_failure_records(
        self,
        unit: Any,
        *,
        current: RuntimeCommandRecord,
        records: StructuredFailureRecords,
    ) -> None:
        observation = records.public
        diagnostic = records.private
        validate_failure_diagnostic_pair(observation, diagnostic)
        if (
            observation.session_id != current.session_id
            or observation.source_kind != _ENTITY_TYPE
            or observation.source_ref != current.command_id
            or observation.source_version != canonical_sha256_digest(current.to_dict())
            or observation.identities
            != {
                "command_id": current.command_id,
                "session_id": current.session_id,
            }
        ):
            raise KernelContractError(
                "runtime_command_failure_identity_drift",
                "Runtime command failure differs from the claimed occurrence",
            )
        if (
            unit.read(
                entity_type="failure_observation",
                entity_id=observation.failure_id,
            )
            is not None
            or unit.read(
                entity_type="private_diagnostic",
                entity_id=diagnostic.diagnostic_id,
            )
            is not None
        ):
            raise KernelContractError(
                "runtime_command_failure_identity_collision",
                "Runtime command failure identity is already in use",
            )
        unit.stage(
            KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.CREATE,
                entity_type="failure_observation",
                entity_id=observation.failure_id,
                expected_state_version=None,
                payload=observation.to_internal_dict(),
            )
        )
        unit.stage(
            KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.CREATE,
                entity_type="private_diagnostic",
                entity_id=diagnostic.diagnostic_id,
                expected_state_version=None,
                payload=diagnostic.to_dict(),
            )
        )

    def _event(
        self,
        unit: Any,
        *,
        context: KernelCommandContext,
        event_type: str,
        record: RuntimeCommandRecord,
        payload: Mapping[str, Any],
    ) -> DurableEventRecord:
        event = DurableEventRecord.create(
            event_id=self._ids.new_id(namespace="event"),
            session_id=context.session_id,
            event_type=event_type,
            source_entity_type=_ENTITY_TYPE,
            source_entity_id=record.command_id,
            source_state_version=record.state_version,
            command_id=context.command_id,
            payload=payload,
        )
        unit.append_event(event)
        outbox_payload = {
            "event_id": event.event_id,
            "event_digest": event.event_digest,
            "source_entity_type": _ENTITY_TYPE,
            "source_entity_id": record.command_id,
        }
        unit.append_outbox(
            OutboxRecord(
                outbox_id=self._ids.new_id(namespace="outbox"),
                session_id=context.session_id,
                topic="openzyme.kernel.runtime-command-events",
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
        record: KernelRecordSnapshot,
        mutation_applied: bool,
        effect_certainty: ExternalEffectCertainty,
        result: Mapping[str, Any],
        event_id: str | None = None,
    ) -> KernelMutationReceipt:
        return KernelMutationReceipt.create(
            command_id=context.command_id,
            service_id=self.service_id,
            operation=operation,
            mutation_applied=mutation_applied,
            effect_certainty=effect_certainty,
            entity_refs=(
                KernelEntityRef(
                    entity_kind=record.entity_type,
                    entity_id=record.entity_id,
                    state_version=record.state_version,
                    entity_digest=record.record_digest,
                ),
            ),
            event_refs=() if event_id is None else (event_id,),
            result=result,
        )


def _snapshot(record: RuntimeCommandRecord) -> KernelRecordSnapshot:
    return KernelRecordSnapshot.create(
        entity_type=_ENTITY_TYPE,
        entity_id=record.command_id,
        state_version=record.state_version,
        payload=record.to_dict(),
    )


def _record(snapshot: KernelRecordSnapshot) -> RuntimeCommandRecord:
    payload = dict(snapshot.payload)
    expected = {
        "schema_version",
        "command_id",
        "session_id",
        "command_type",
        "request_digest",
        "idempotency_key",
        "status",
        "max_signals",
        "max_steps_per_agent",
        "auto_enqueue_ready_tasks",
        "state_version",
        "fencing_token",
        "accepted_at",
        "claim_owner",
        "lease_token",
        "lease_expires_at",
        "bounded_outcome_summary",
        "failure_id",
        "diagnostic_id",
        "error_code",
        "safe_error_summary",
        "safe_retry_hint",
        "started_at",
        "completed_at",
    }
    if (
        snapshot.entity_type != _ENTITY_TYPE
        or set(payload) != expected
        or payload.get("schema_version") != RuntimeCommandRecord.SCHEMA_VERSION
        or payload.get("command_id") != snapshot.entity_id
        or payload.get("state_version") != snapshot.state_version
    ):
        raise KernelContractError(
            "runtime_command_record_invalid",
            "Canonical runtime command violates its closed contract",
        )
    try:
        summary = payload["bounded_outcome_summary"]
        return RuntimeCommandRecord(
            command_id=str(payload["command_id"]),
            session_id=str(payload["session_id"]),
            command_type=RuntimeCommandType(str(payload["command_type"])),
            request_digest=str(payload["request_digest"]),
            idempotency_key=str(payload["idempotency_key"]),
            status=RuntimeCommandStatus(str(payload["status"])),
            max_signals=int(payload["max_signals"]),
            max_steps_per_agent=int(payload["max_steps_per_agent"]),
            auto_enqueue_ready_tasks=bool(payload["auto_enqueue_ready_tasks"]),
            state_version=int(payload["state_version"]),
            fencing_token=int(payload["fencing_token"]),
            accepted_at=str(payload["accepted_at"]),
            claim_owner=_optional_text(payload["claim_owner"]),
            lease_token=_optional_text(payload["lease_token"]),
            lease_expires_at=_optional_text(payload["lease_expires_at"]),
            bounded_outcome_summary=(
                None if summary is None else dict(summary)  # type: ignore[arg-type]
            ),
            failure_id=_optional_text(payload["failure_id"]),
            diagnostic_id=_optional_text(payload["diagnostic_id"]),
            error_code=_optional_text(payload["error_code"]),
            safe_error_summary=_optional_text(payload["safe_error_summary"]),
            safe_retry_hint=_optional_text(payload["safe_retry_hint"]),
            started_at=_optional_text(payload["started_at"]),
            completed_at=_optional_text(payload["completed_at"]),
        )
    except (TypeError, ValueError) as exc:
        raise KernelContractError(
            "runtime_command_record_invalid",
            "Canonical runtime command contains invalid values",
        ) from exc


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("optional runtime command text must be a string")
    return value


def _lease_token(
    *,
    runtime_command_id: str,
    claim_owner: str,
    fencing_token: int,
) -> str:
    digest = canonical_sha256_digest(
        {
            "schema_version": "runtime_command_claim_identity@1",
            "runtime_command_id": runtime_command_id,
            "claim_owner": claim_owner,
            "fencing_token": fencing_token,
        }
    )
    return "runtime-command-lease-" + digest.removeprefix("sha256:")[:32]


def _claim_is_current(
    current: RuntimeCommandRecord,
    command: RuntimeCommandClaimCommand,
    *,
    now: str,
) -> bool:
    return bool(
        current.status is RuntimeCommandStatus.CLAIMED
        and current.claim_owner == command.claim_owner
        and current.lease_token
        == _lease_token(
            runtime_command_id=current.command_id,
            claim_owner=command.claim_owner,
            fencing_token=current.fencing_token,
        )
        and current.lease_expires_at is not None
        and _instant(current.lease_expires_at, field_name="lease_expires_at")
        > _instant(now, field_name="now")
    )


def _settlement_is_duplicate(
    current: RuntimeCommandRecord,
    command: RuntimeCommandSettlementCommand,
) -> bool:
    return bool(
        current.status is command.status
        and current.claim_owner == command.claim_owner
        and current.lease_token == command.lease_token
        and current.fencing_token == command.fencing_token
        and canonical_sha256_digest(current.bounded_outcome_summary)
        == canonical_sha256_digest(command.bounded_outcome_summary)
        and current.failure_id
        == (
            None
            if command.failure_records is None
            else command.failure_records.public.failure_id
        )
        and current.diagnostic_id
        == (
            None
            if command.failure_records is None
            else command.failure_records.public.diagnostic_id
        )
        and current.error_code == command.error_code
        and current.safe_error_summary == command.safe_error_summary
        and current.safe_retry_hint == command.safe_retry_hint
    )


def _admission_result(record: RuntimeCommandRecord) -> dict[str, Any]:
    return {
        "runtime_command_id": record.command_id,
        "runtime_command_status": record.status.value,
        "request_digest": record.request_digest,
        "max_signals": record.max_signals,
        "max_steps_per_agent": record.max_steps_per_agent,
        "auto_enqueue_ready_tasks": record.auto_enqueue_ready_tasks,
        "runtime_executed": False,
        "task_transition_performed": False,
        "fallback_performed": False,
    }


def _claim_result(record: RuntimeCommandRecord) -> dict[str, Any]:
    return {
        "runtime_command_id": record.command_id,
        "runtime_command_status": record.status.value,
        "claim_owner": record.claim_owner,
        "lease_token": record.lease_token,
        "lease_expires_at": record.lease_expires_at,
        "fencing_token": record.fencing_token,
        "runtime_executed": False,
        "task_transition_performed": False,
        "fallback_performed": False,
    }


def _settlement_result(record: RuntimeCommandRecord) -> dict[str, Any]:
    summary = record.bounded_outcome_summary or {}
    return {
        "runtime_command_id": record.command_id,
        "runtime_command_status": record.status.value,
        "bounded_outcome_summary": dict(summary),
        "failure_id": record.failure_id,
        "diagnostic_id": record.diagnostic_id,
        "error_code": record.error_code,
        "safe_error_summary": record.safe_error_summary,
        "safe_retry_hint": record.safe_retry_hint,
        "runtime_executed": bool(summary.get("runtime_executed", False)),
        "task_transition_performed": bool(
            summary.get("task_transition_performed", False)
        ),
        "fallback_performed": False,
    }


__all__ = [
    "RuntimeCommandAdmissionCommand",
    "RuntimeCommandClaimCommand",
    "RuntimeCommandKernelApplicationService",
    "RuntimeCommandSettlementCommand",
    "observe_runtime_command_failure",
    "runtime_command_id",
]
