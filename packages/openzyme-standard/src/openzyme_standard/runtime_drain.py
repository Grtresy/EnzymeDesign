from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from typing import Protocol

from openzyme_contracts import AgentRuntimeSignal
from openzyme_contracts import AgentRuntimeSignalReason
from openzyme_contracts import AgentRuntimeSignalStatus
from openzyme_contracts import ClockPort
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelRecordQueryPort
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import SessionRuntimeLease
from openzyme_contracts import SessionRuntimeLeaseMode
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_host_api import HostV2CommandError
from openzyme_host_api import HostV2MutationInvocation
from openzyme_kernel import ControlStoreRuntimeOutcomeRepository
from openzyme_kernel import RuntimeLeaseAction
from openzyme_kernel import RuntimeSignalClaimCommand
from openzyme_kernel import RuntimeTurnAdmission
from openzyme_kernel import RuntimeTurnBudget
from openzyme_kernel import RuntimeTurnCoordinator
from openzyme_kernel import SessionRuntimeLeaseCommand
from openzyme_kernel import RuntimeCoordinationKernelApplicationService
from openzyme_runtime_spi import RuntimeCapabilityGateway

from .coordination_routes import build_standard_command_context


class StandardRuntimeTurnAdmissionSource(Protocol):
    """Build exact target-Agent turn facts without exposing a repository to Adapter."""

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

    def discard(self, command_id: str) -> None:
        """Discard the non-canonical tool scope after one bounded command."""


@dataclass(slots=True)
class StandardBoundedRuntimeDrainApplication:
    """Execute an explicit bounded drain through Kernel lease/claim/turn owners."""

    coordination: RuntimeCoordinationKernelApplicationService
    turns: RuntimeTurnCoordinator
    outcomes: ControlStoreRuntimeOutcomeRepository
    records: KernelRecordQueryPort
    admissions: StandardRuntimeTurnAdmissionSource
    capability_gateway: RuntimeCapabilityGateway
    clock: ClockPort
    ids: IdGeneratorPort
    lease_seconds: int = 300
    claim_seconds: int = 120
    max_duration_seconds: int = 300
    max_input_units: int = 64_000
    max_output_units: int = 16_000

    def __post_init__(self) -> None:
        for value in (
            self.lease_seconds,
            self.claim_seconds,
            self.max_duration_seconds,
            self.max_input_units,
            self.max_output_units,
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError("Standard runtime drain budgets must be positive")

    def invoke(self, invocation: HostV2MutationInvocation) -> KernelMutationReceipt:
        payload = dict(invocation.payload)
        max_signals = _positive(payload.pop("max_signals", None), "max_signals")
        max_steps = _positive(
            payload.pop("max_steps_per_agent", None),
            "max_steps_per_agent",
        )
        if payload or max_signals > 64 or max_steps > 128:
            raise _drain_error(
                "runtime_drain_payload_invalid",
                "Runtime drain payload exceeds its closed bounds",
                status_code=422,
            )
        pending = self.admissions.pending_signals(
            session_id=invocation.session_id,
            maximum=max_signals,
        )
        if len(pending) > max_signals:
            raise _drain_error(
                "runtime_drain_source_unbounded",
                "Runtime admission source exceeded the requested signal bound",
            )
        if not pending:
            return KernelMutationReceipt.create(
                command_id=self.ids.new_id(namespace="runtime-drain"),
                service_id="openzyme.standard.runtime-drain",
                operation="runtime.drain",
                mutation_applied=False,
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                result={
                    "processed_signals": 0,
                    "task_transition_performed": False,
                    "fallback_performed": False,
                },
            )

        base = build_standard_command_context(invocation, ids=self.ids)
        runtime_owner_id = self.ids.new_id(namespace="runtime-owner")
        acquire_context = replace(
            base,
            command_id=self.ids.new_id(namespace="command"),
            idempotency_key=f"{invocation.idempotency_key}.lease.acquire",
        )
        self.coordination.mutate_session_lease(
            SessionRuntimeLeaseCommand(
                context=acquire_context,
                action=RuntimeLeaseAction.ACQUIRE,
                owner_id=runtime_owner_id,
                mode=SessionRuntimeLeaseMode.MANUAL_DRAIN,
                lease_seconds=self.lease_seconds,
            )
        )
        lease, lease_generation = self._runtime_lease(invocation.session_id)
        processed: list[dict[str, object]] = []
        primary_error: BaseException | None = None
        try:
            for index, snapshot in enumerate(pending, start=1):
                if snapshot.entity_type != "agent_runtime_signal":
                    raise _drain_error(
                        "runtime_signal_source_invalid",
                        "Runtime admission source returned another entity type",
                    )
                signal = _runtime_signal(snapshot.payload)
                if (
                    signal.session_id != invocation.session_id
                    or signal.status is not AgentRuntimeSignalStatus.PENDING
                ):
                    raise _drain_error(
                        "runtime_signal_source_stale",
                        "Runtime admission source returned a stale signal",
                    )
                claim_context = replace(
                    base,
                    command_id=self.ids.new_id(namespace="command"),
                    idempotency_key=(
                        f"{invocation.idempotency_key}.signal.{signal.signal_id}.claim"
                    ),
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
                        claim_seconds=self.claim_seconds,
                    )
                )
                claimed, claim_token = self._claimed_signal(signal.signal_id)
                admission = self.admissions.build_admission(
                    signal=claimed,
                    signal_claim_token=claim_token,
                    session_lease=lease,
                    runtime_lease_generation=lease_generation,
                    command_id=self.ids.new_id(namespace="runtime-command"),
                    turn_id=self.ids.new_id(namespace="runtime-turn"),
                    budget=RuntimeTurnBudget(
                        max_steps=max_steps,
                        max_duration_seconds=self.max_duration_seconds,
                        max_input_units=self.max_input_units,
                        max_output_units=self.max_output_units,
                    ),
                    observed_at=self.clock.now_iso(),
                )
                command = self.turns.build_command(admission)
                try:
                    self.outcomes.register_command(command)
                    outcome = self.turns.adapter.run_turn(
                        command,
                        self.capability_gateway,
                    )
                    consumption = self.turns.consume_outcome(
                        command,
                        outcome,
                        consumed_at=self.clock.now_iso(),
                    )
                finally:
                    self.admissions.discard(command.command_id)
                processed.append(
                    {
                        "sequence": index,
                        "signal_id": claimed.signal_id,
                        "command_id": command.command_id,
                        "command_digest": command.command_digest,
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
            release_context = replace(
                base,
                command_id=self.ids.new_id(namespace="command"),
                idempotency_key=f"{invocation.idempotency_key}.lease.release",
            )
            try:
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

        return KernelMutationReceipt.create(
            command_id=base.command_id,
            service_id="openzyme.standard.runtime-drain",
            operation="runtime.drain",
            mutation_applied=True,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            result={
                "processed_signals": len(processed),
                "turns": processed,
                "task_transition_performed": False,
                "fallback_performed": False,
            },
        )

    def _runtime_lease(self, session_id: str) -> tuple[SessionRuntimeLease, int]:
        record = self.records.read(
            entity_type="session_runtime_lease",
            entity_id=session_id,
        )
        if record is None:
            raise _drain_error(
                "runtime_lease_missing",
                "Runtime lease mutation produced no canonical lease",
            )
        try:
            generation = _positive(record.payload.get("generation"), "generation")
            return _runtime_lease(record.payload), generation
        except (KeyError, TypeError, ValueError, HostV2CommandError) as exc:
            raise _drain_error(
                "runtime_lease_invalid",
                "Canonical runtime lease is invalid",
            ) from exc

    def _claimed_signal(self, signal_id: str) -> tuple[AgentRuntimeSignal, str]:
        record = self.records.read(
            entity_type="agent_runtime_signal",
            entity_id=signal_id,
        )
        if record is None:
            raise _drain_error(
                "runtime_signal_missing",
                "Claimed runtime signal is absent",
            )
        try:
            signal = _runtime_signal(record.payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise _drain_error(
                "runtime_signal_invalid",
                "Claimed runtime signal is invalid",
            ) from exc
        claim_token = record.payload.get("claim_token")
        if (
            signal.status is not AgentRuntimeSignalStatus.CLAIMED
            or not isinstance(claim_token, str)
            or not claim_token
        ):
            raise _drain_error(
                "runtime_signal_claim_missing",
                "Runtime signal claim did not become canonical",
            )
        return signal, claim_token


def _runtime_lease(payload) -> SessionRuntimeLease:  # noqa: ANN001
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


def _runtime_signal(payload) -> AgentRuntimeSignal:  # noqa: ANN001
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
        raise _drain_error(
            "runtime_drain_payload_invalid",
            f"{field_name} must be a positive integer",
            status_code=422,
        )
    return value


def _drain_error(
    code: str,
    message: str,
    *,
    status_code: int = 409,
) -> HostV2CommandError:
    return HostV2CommandError(
        code,
        message,
        status_code=status_code,
        mutation_applied=False,
        effect_certainty="no_effect",
    )


__all__ = [
    "StandardBoundedRuntimeDrainApplication",
    "StandardRuntimeTurnAdmissionSource",
]
