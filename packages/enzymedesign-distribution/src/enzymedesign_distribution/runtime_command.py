"""Durable EnzymeDesign runtime-drain admission and bounded worker."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from typing import Mapping

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import ClockPort
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelRecordQueryPort
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import RuntimeCommandRecord
from openzyme_contracts import RuntimeCommandStatus
from openzyme_contracts import RuntimeCommandType
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import json_compatible
from openzyme_contracts import require_identifier
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_host_api import HostV2CommandError
from openzyme_host_api import HostV2MutationInvocation
from openzyme_kernel import KernelContractError
from openzyme_kernel.runtime_command_application import RuntimeCommandAdmissionCommand
from openzyme_kernel.runtime_command_application import RuntimeCommandClaimCommand
from openzyme_kernel.runtime_command_application import (
    RuntimeCommandKernelApplicationService,
)
from openzyme_kernel.runtime_command_application import RuntimeCommandSettlementCommand
from openzyme_kernel.runtime_command_application import observe_runtime_command_failure

from .coordination_routes import build_enzymedesign_command_context
from .runtime_drain import EnzymeDesignBoundedRuntimeDrainApplication


@dataclass(slots=True)
class EnzymeDesignRuntimeDrainAdmissionApplication:
    """Admit an explicit durable command; never execute runtime work in HTTP."""

    commands: RuntimeCommandKernelApplicationService
    ids: IdGeneratorPort

    def invoke(self, invocation: HostV2MutationInvocation) -> KernelMutationReceipt:
        payload = dict(invocation.payload)
        max_signals = _positive(payload.pop("max_signals", None), "max_signals")
        max_steps = _positive(
            payload.pop("max_steps_per_agent", None),
            "max_steps_per_agent",
        )
        auto_enqueue = payload.pop("auto_enqueue_ready_tasks", False)
        if (
            payload
            or max_signals > 64
            or max_steps > 128
            or not isinstance(auto_enqueue, bool)
            or auto_enqueue
        ):
            raise _payload_error(
                "Runtime drain payload exceeds its closed bounds or requests "
                "unsupported automatic task enqueue"
            )
        return self.commands.admit(
            RuntimeCommandAdmissionCommand(
                context=build_enzymedesign_command_context(invocation, ids=self.ids),
                max_signals=max_signals,
                max_steps_per_agent=max_steps,
                auto_enqueue_ready_tasks=auto_enqueue,
            )
        )


@dataclass(frozen=True, slots=True)
class EnzymeDesignRuntimeCommandContextResolver:
    """Resolve the current exact resident master authority for worker mutations."""

    records: KernelRecordQueryPort
    extension_bundle_digest: str
    ids: IdGeneratorPort

    def resolve(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> KernelCommandContext:
        session = self.records.read(entity_type="session", entity_id=session_id)
        if session is None:
            raise KernelContractError(
                "runtime_command_session_missing",
                "Runtime command Session is absent",
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
                "runtime_command_master_ambiguous",
                "Runtime command requires one exact active resident master",
            )
        member = roots[0]
        member_id = member.payload.get("agent_member_id")
        workspace_generation = member.payload.get("workspace_generation")
        if not isinstance(member_id, str) or not member_id:
            raise KernelContractError(
                "runtime_command_master_invalid",
                "Resident master identity is invalid",
            )
        if workspace_generation is not None and (
            not isinstance(workspace_generation, int)
            or isinstance(workspace_generation, bool)
            or workspace_generation < 1
        ):
            raise KernelContractError(
                "runtime_command_workspace_generation_invalid",
                "Resident master workspace generation is invalid",
            )
        active_lease_id = member.payload.get("active_authority_lease_id")
        lease_snapshot = (
            None
            if not isinstance(active_lease_id, str) or not active_lease_id
            else self.records.read(
                entity_type="agent_authority_lease",
                entity_id=active_lease_id,
            )
        )
        try:
            if lease_snapshot is None:
                raise ValueError("missing")
            lease = AgentAuthorityLease.from_dict(lease_snapshot.payload)
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "runtime_command_authority_invalid",
                "Resident master authority violates its closed contract",
            ) from exc
        if (
            lease.lease_id != active_lease_id
            or lease.session_id != session_id
            or lease.agent_member_id != member_id
            or lease.state is not AgentAuthorityLeaseState.ACTIVE
            or lease.workspace_generation != workspace_generation
        ):
            raise KernelContractError(
                "runtime_command_authority_stale",
                "Resident master points to a pending or stale authority lease",
            )
        matching = tuple(
            snapshot.entity_id
            for snapshot in self.records.list_for_session(
                entity_type="agent_authority_lease",
                session_id=session_id,
                max_items=128,
            )
            if snapshot.entity_id == active_lease_id
        )
        if matching != (active_lease_id,):
            raise KernelContractError(
                "runtime_command_authority_ambiguous",
                "Runtime command requires one exact resident authority record",
            )
        binding = self._latest_binding(session_id)
        if binding.extension_bundle_digest != self.extension_bundle_digest:
            raise KernelContractError(
                "runtime_command_composition_stale",
                "Runtime command Session is pinned to another extension bundle",
            )
        return KernelCommandContext(
            command_id=self.ids.new_id(namespace="command"),
            session_id=session_id,
            actor_id=member_id,
            owner_plugin_id="openzyme.kernel",
            authority_lease_id=lease.lease_id,
            authority_generation=lease.generation,
            authority_fence=lease.fence,
            expected_session_version=session.state_version,
            extension_bundle_digest=self.extension_bundle_digest,
            capability_binding_digest=binding.binding_digest,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            workspace_generation=workspace_generation,
            route_id="openzyme.kernel.runtime.drain@2",
        )

    def _latest_binding(self, session_id: str) -> SessionCapabilityBindingRevision:
        snapshots = self.records.list_for_session(
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
                "Runtime command capability binding is invalid",
            ) from exc
        if not bindings:
            raise KernelContractError(
                "runtime_command_capability_binding_missing",
                "Runtime command capability binding is absent",
            )
        revision = max(item.revision for item in bindings)
        selected = tuple(item for item in bindings if item.revision == revision)
        if len(selected) != 1:
            raise KernelContractError(
                "runtime_command_capability_binding_ambiguous",
                "Runtime command capability binding is ambiguous",
            )
        return selected[0]

    def derive_settlement(
        self,
        context: KernelCommandContext,
        *,
        idempotency_key: str,
    ) -> KernelCommandContext:
        """Reuse the exact claimed authority when later context projection failed."""

        return replace(
            context,
            command_id=self.ids.new_id(namespace="command"),
            idempotency_key=idempotency_key,
        )


@dataclass(slots=True)
class EnzymeDesignRuntimeCommandWorker:
    """Claim, execute and terminally settle one exact durable command."""

    commands: RuntimeCommandKernelApplicationService
    records: KernelRecordQueryPort
    contexts: EnzymeDesignRuntimeCommandContextResolver
    executor: EnzymeDesignBoundedRuntimeDrainApplication
    clock: ClockPort
    claim_owner: str
    claim_seconds: int = 900

    def __post_init__(self) -> None:
        require_identifier(self.claim_owner, field_name="claim_owner")
        if (
            not isinstance(self.claim_seconds, int)
            or isinstance(self.claim_seconds, bool)
            or not 1 <= self.claim_seconds <= 86_400
        ):
            raise ValueError("claim_seconds must be between 1 and 86400")

    def tick(
        self,
        *,
        session_id: str,
        maximum: int = 1,
    ) -> tuple[KernelMutationReceipt, ...]:
        """Claim bounded accepted/expired occurrences after a process restart."""

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
        return tuple(self.run(item.entity_id) for item in candidates)

    def run(self, runtime_command_id: str) -> KernelMutationReceipt:
        initial = self._record(runtime_command_id)
        current = _runtime_command(initial)
        session_id = current.session_id
        request_key = current.idempotency_key
        if current.status.is_terminal:
            raise KernelContractError(
                "runtime_command_terminal",
                "Terminal runtime command cannot be executed again",
            )
        claim_context = self.contexts.resolve(
            session_id=session_id,
            idempotency_key=f"{request_key}.worker.claim",
            correlation_id=runtime_command_id,
        )
        self.commands.claim(
            RuntimeCommandClaimCommand(
                context=claim_context,
                runtime_command_id=runtime_command_id,
                claim_owner=self.claim_owner,
                expected_state_version=current.state_version,
                claim_seconds=self.claim_seconds,
            )
        )
        claimed = self._record(runtime_command_id)
        claimed_record = _runtime_command(claimed)
        lease_token = claimed_record.lease_token
        if lease_token is None:
            raise KernelContractError(
                "runtime_command_claim_missing",
                "Claimed runtime command lacks a lease token",
            )
        fencing_token = claimed_record.fencing_token
        claimed_version = claimed_record.state_version
        try:
            execute_context = self.contexts.resolve(
                session_id=session_id,
                idempotency_key=f"{request_key}.worker.execute.{fencing_token}",
                correlation_id=runtime_command_id,
            )
            if claimed_record.auto_enqueue_ready_tasks:
                raise KernelContractError(
                    "runtime_command_auto_enqueue_unsupported",
                    "EnzymeDesign runtime worker does not implement automatic task enqueue",
                )
            execution = self.executor.execute(
                context=execute_context,
                max_signals=claimed_record.max_signals,
                max_steps_per_agent=claimed_record.max_steps_per_agent,
            )
            summary = json_compatible(execution.result)
            if not isinstance(summary, dict):
                raise KernelContractError(
                    "runtime_command_outcome_summary_invalid",
                    "Runtime drain returned a non-object outcome summary",
                )
        except Exception as exc:
            error_code = (
                exc.code
                if isinstance(exc, KernelContractError)
                else "runtime_command_execution_failed"
            )
            phase = _failure_phase(error_code)
            effect_certainty = (
                ExternalEffectCertainty.NO_EFFECT
                if phase == "runtime_context_projection"
                else ExternalEffectCertainty.DISPATCH_IN_DOUBT
            )
            safe_summary = (
                "The EnzymeDesign runtime context failed before provider invocation"
                if phase == "runtime_context_projection"
                else (
                    "The bounded EnzymeDesign runtime command failed without a "
                    "terminal effect observation"
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
                exc,
                record=claimed_record,
                component="enzymedesign.distribution.runtime_worker",
                phase=phase,
                created_at=self.clock.now_iso(),
                error_code=error_code,
                safe_summary=safe_summary,
                safe_hint=safe_hint,
                effect_certainty=effect_certainty,
                correlation_id=runtime_command_id,
            )
            try:
                return self.commands.settle(
                    RuntimeCommandSettlementCommand(
                        context=self.contexts.derive_settlement(
                            claim_context,
                            idempotency_key=(
                                f"{request_key}.worker.settle.{fencing_token}"
                            ),
                        ),
                        runtime_command_id=runtime_command_id,
                        claim_owner=self.claim_owner,
                        lease_token=lease_token,
                        fencing_token=fencing_token,
                        expected_state_version=claimed_version,
                        status=RuntimeCommandStatus.FAILED,
                        bounded_outcome_summary={
                            "processed_signals": 0,
                            "turns": [],
                            "runtime_executed": False,
                            "runtime_completed": False,
                            "task_transition_performed": False,
                            "fallback_performed": False,
                        },
                        error_code=error_code,
                        safe_error_summary=safe_summary,
                        safe_retry_hint=safe_hint,
                        failure_records=failure_records,
                    )
                )
            except Exception as settlement_error:
                exc.add_note(
                    "runtime command failure settlement also failed: "
                    f"{type(settlement_error).__name__}"
                )
                raise exc from settlement_error
        settle_context = self.contexts.derive_settlement(
            claim_context,
            idempotency_key=f"{request_key}.worker.settle.{fencing_token}",
        )
        return self.commands.settle(
            RuntimeCommandSettlementCommand(
                context=settle_context,
                runtime_command_id=runtime_command_id,
                claim_owner=self.claim_owner,
                lease_token=lease_token,
                fencing_token=fencing_token,
                expected_state_version=claimed_version,
                status=RuntimeCommandStatus.COMPLETED,
                bounded_outcome_summary=summary,
            )
        )

    def _record(self, runtime_command_id: str) -> Mapping[str, object]:
        snapshot = self.records.read(
            entity_type="runtime_command",
            entity_id=runtime_command_id,
        )
        if snapshot is None:
            raise KernelContractError(
                "runtime_command_not_found",
                "Runtime command worker requires one exact durable occurrence",
            )
        return snapshot.payload


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


def _positive(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _payload_error(f"{field_name} must be a positive integer")
    return value


def _positive_version(payload: Mapping[str, object], field_name: str) -> int:
    value = payload.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise KernelContractError(
            "runtime_command_record_invalid",
            f"Runtime command {field_name} is invalid",
        )
    return value


def _runtime_command(payload: Mapping[str, object]) -> RuntimeCommandRecord:
    summary = payload.get("bounded_outcome_summary")
    try:
        return RuntimeCommandRecord(
            command_id=_text(payload, "command_id"),
            session_id=_text(payload, "session_id"),
            command_type=RuntimeCommandType(_text(payload, "command_type")),
            request_digest=_text(payload, "request_digest"),
            idempotency_key=_text(payload, "idempotency_key"),
            status=RuntimeCommandStatus(_text(payload, "status")),
            max_signals=_positive_version(payload, "max_signals"),
            max_steps_per_agent=_positive_version(
                payload,
                "max_steps_per_agent",
            ),
            auto_enqueue_ready_tasks=_boolean(
                payload,
                "auto_enqueue_ready_tasks",
            ),
            state_version=_positive_version(payload, "state_version"),
            fencing_token=_non_negative(payload, "fencing_token"),
            accepted_at=_text(payload, "accepted_at"),
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
    except (TypeError, ValueError) as exc:
        raise KernelContractError(
            "runtime_command_record_invalid",
            "Canonical runtime command violates its closed contract",
        ) from exc


def _claimable(snapshot: KernelRecordSnapshot, *, now: str) -> bool:
    record = _runtime_command(snapshot.payload)
    if record.status is RuntimeCommandStatus.ACCEPTED:
        return True
    return bool(
        record.status is RuntimeCommandStatus.CLAIMED
        and record.lease_expires_at is not None
        and _instant(record.lease_expires_at) <= _instant(now)
    )


def _instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise KernelContractError(
            "runtime_command_record_invalid",
            "Runtime command time must be ISO-8601",
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise KernelContractError(
            "runtime_command_record_invalid",
            "Runtime command time must include a timezone",
        )
    return parsed


def _boolean(payload: Mapping[str, object], field_name: str) -> bool:
    value = payload.get(field_name)
    if not isinstance(value, bool):
        raise KernelContractError(
            "runtime_command_record_invalid",
            f"Runtime command {field_name} is invalid",
        )
    return value


def _non_negative(payload: Mapping[str, object], field_name: str) -> int:
    value = payload.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise KernelContractError(
            "runtime_command_record_invalid",
            f"Runtime command {field_name} is invalid",
        )
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise KernelContractError(
            "runtime_command_record_invalid",
            "Runtime command optional text is invalid",
        )
    return value


def _text(payload: Mapping[str, object], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value or value != value.strip():
        raise KernelContractError(
            "runtime_command_record_invalid",
            f"Runtime command {field_name} is invalid",
        )
    return value


def _payload_error(message: str) -> HostV2CommandError:
    return HostV2CommandError(
        "runtime_drain_payload_invalid",
        message,
        status_code=422,
        mutation_applied=False,
        effect_certainty="no_effect",
    )


__all__ = [
    "EnzymeDesignRuntimeCommandContextResolver",
    "EnzymeDesignRuntimeCommandWorker",
    "EnzymeDesignRuntimeDrainAdmissionApplication",
]
