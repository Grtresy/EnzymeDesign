from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

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
from openzyme_contracts.identity import json_compatible
from openzyme_extension_spi import ControlledOperationApplicationCommand
from openzyme_extension_spi import ControlledOperationCommandKind
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelMutationReceipt

from .authority_application import evaluate_authority_payload
from .errors import KernelContractError


_ENTITY_TYPE = "controlled_operation"
_RECEIPT_ENTITY_TYPE = "kernel_command_receipt"


def _effect_fact(payload: Mapping[str, JsonValue]) -> tuple[ExternalEffectCertainty, bool | None]:
    try:
        certainty = ExternalEffectCertainty(str(payload["effect_certainty"]))
    except (KeyError, ValueError) as exc:
        raise KernelContractError(
            "controlled_operation_effect_certainty_invalid",
            "settlement requires a closed effect_certainty",
        ) from exc
    mutation_applied = payload.get("mutation_applied")
    if certainty is ExternalEffectCertainty.NO_EFFECT:
        if mutation_applied is not False:
            raise KernelContractError(
                "controlled_operation_mutation_fact_invalid",
                "no_effect requires mutation_applied=false",
            )
    elif certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
        if mutation_applied is not None:
            raise KernelContractError(
                "controlled_operation_mutation_fact_invalid",
                "dispatch_in_doubt requires an unknown mutation fact",
            )
    elif not isinstance(mutation_applied, bool):
        raise KernelContractError(
            "controlled_operation_mutation_fact_invalid",
            "known effect certainty requires a boolean mutation fact",
        )
    return certainty, mutation_applied


def _receipt_from_payload(payload: Mapping[str, JsonValue]) -> KernelMutationReceipt:
    receipt = payload.get("receipt")
    if not isinstance(receipt, Mapping):
        raise KernelContractError(
            "controlled_operation_idempotency_record_invalid",
            "stored command receipt is not a closed object",
        )
    try:
        return KernelMutationReceipt(
            command_id=str(receipt["command_id"]),
            service_id=str(receipt["service_id"]),
            operation=str(receipt["operation"]),
            mutation_applied=receipt["mutation_applied"] is True,
            effect_certainty=ExternalEffectCertainty(str(receipt["effect_certainty"])),
            fallback_performed=receipt["fallback_performed"] is True,
            entity_refs=tuple(
                KernelEntityRef(
                    entity_kind=str(item["entity_kind"]),
                    entity_id=str(item["entity_id"]),
                    state_version=int(item["state_version"]),
                    entity_digest=str(item["entity_digest"]),
                )
                for item in receipt["entity_refs"]
            ),
            event_refs=tuple(str(item) for item in receipt["event_refs"]),
            result=receipt["result"],
            receipt_digest=str(receipt["receipt_digest"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise KernelContractError(
            "controlled_operation_idempotency_record_invalid",
            "stored command receipt failed closed validation",
        ) from exc


class ControlledOperationKernelApplicationService:
    """Generic admission and effect-certainty state machine for every extension."""

    service_id = "controlled_operation"

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

    def execute(
        self,
        command: ControlledOperationApplicationCommand,
    ) -> KernelMutationReceipt:
        command_digest = canonical_sha256_digest(
            {
                "service_id": self.service_id,
                "context": command.context.to_dict(),
                "operation": command.operation.value,
                "operation_id": command.operation_id,
                "intent_digest": command.intent_digest,
                "payload": json_compatible(command.payload),
            }
        )
        idempotency = self._reader.read(
            entity_type=_RECEIPT_ENTITY_TYPE,
            entity_id=command.context.idempotency_key,
        )
        if idempotency is not None:
            if idempotency.payload.get("command_digest") != command_digest:
                raise KernelContractError(
                    "controlled_operation_idempotency_conflict",
                    "idempotency identity was reused for another controlled command",
                )
            return _receipt_from_payload(idempotency.payload)

        request = UnitOfWorkRequest(
            unit_of_work_id=self._ids.new_id(namespace="uow"),
            command_id=command.context.command_id,
            session_id=command.context.session_id,
            actor_id=command.context.actor_id,
            authority_lease_id=command.context.authority_lease_id,
            authority_generation=command.context.authority_generation,
            authority_fence=command.context.authority_fence,
            expected_session_version=command.context.expected_session_version,
            idempotency_key=command.context.idempotency_key,
            command_digest=command_digest,
        )
        unit = self._store.begin(request)
        try:
            session = unit.read(
                entity_type="session",
                entity_id=command.context.session_id,
            )
            if session is None:
                raise KernelContractError(
                    "session_not_found",
                    "ControlledOperation requires a canonical Session",
                )
            if session.state_version != command.context.expected_session_version:
                raise KernelContractError(
                    "session_state_version_stale",
                    "Session changed before ControlledOperation mutation",
                )
            current = unit.read(
                entity_type=_ENTITY_TYPE,
                entity_id=command.operation_id,
            )
            updated, certainty = self._reduce(command, current, unit)
            next_version = 1 if current is None else current.state_version + 1
            mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=(
                    KernelMutationKind.CREATE
                    if current is None
                    else KernelMutationKind.REPLACE
                ),
                entity_type=_ENTITY_TYPE,
                entity_id=command.operation_id,
                expected_state_version=(None if current is None else current.state_version),
                payload=updated,
            )
            unit.stage(mutation)
            event = DurableEventRecord.create(
                event_id=self._ids.new_id(namespace="event"),
                session_id=command.context.session_id,
                event_type=f"controlled_operation.{command.operation.value}",
                source_entity_type=_ENTITY_TYPE,
                source_entity_id=command.operation_id,
                source_state_version=next_version,
                command_id=command.context.command_id,
                payload={
                    "operation_id": command.operation_id,
                    "state": updated["state"],
                    "effect_certainty": certainty.value,
                    "fallback_performed": False,
                },
            )
            unit.append_event(event)
            outbox_payload: Mapping[str, JsonValue] = {
                "event_id": event.event_id,
                "event_digest": event.event_digest,
                "operation_id": command.operation_id,
                "state": updated["state"],
            }
            unit.append_outbox(
                OutboxRecord(
                    outbox_id=self._ids.new_id(namespace="outbox"),
                    session_id=command.context.session_id,
                    topic="openzyme.kernel.controlled-operation-events",
                    occurrence_id=event.event_id,
                    payload=outbox_payload,
                    payload_digest=canonical_sha256_digest(outbox_payload),
                    created_at=self._clock.now_iso(),
                )
            )
            updated_snapshot = KernelRecordSnapshot.create(
                entity_type=_ENTITY_TYPE,
                entity_id=command.operation_id,
                state_version=next_version,
                payload=updated,
            )
            receipt = KernelMutationReceipt.create(
                command_id=command.context.command_id,
                service_id=self.service_id,
                operation=command.operation.value,
                mutation_applied=True,
                effect_certainty=certainty,
                entity_refs=(
                    KernelEntityRef(
                        entity_kind=_ENTITY_TYPE,
                        entity_id=command.operation_id,
                        state_version=next_version,
                        entity_digest=updated_snapshot.record_digest,
                    ),
                ),
                event_refs=(event.event_id,),
                result={
                    "operation_id": command.operation_id,
                    "state": updated["state"],
                    "effect_certainty": certainty.value,
                    "mutation_applied": updated.get("mutation_applied"),
                    "dispatch_generation": updated["dispatch_generation"],
                    "redispatch_performed": False,
                    "fallback_performed": False,
                },
            )
            receipt_mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.CREATE,
                entity_type=_RECEIPT_ENTITY_TYPE,
                entity_id=command.context.idempotency_key,
                expected_state_version=None,
                payload={
                    "session_id": command.context.session_id,
                    "command_digest": command_digest,
                    "receipt": receipt.to_dict(),
                    "created_at": self._clock.now_iso(),
                },
            )
            unit.stage(receipt_mutation)
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        if not committed.committed:
            raise KernelContractError(
                "controlled_operation_commit_failed",
                "Control Store did not commit the controlled operation",
            )
        return receipt

    def _reduce(self, command, current, unit):  # noqa: ANN001
        if command.payload.get("fallback_performed") is True:
            raise KernelContractError(
                "controlled_operation_fallback_forbidden",
                "ControlledOperation command may not report hidden fallback",
            )
        if command.operation is ControlledOperationCommandKind.ADMIT:
            if current is not None:
                raise KernelContractError(
                    "controlled_operation_identity_conflict",
                    "ControlledOperation identity already exists",
                )
            authority_operation = command.payload.get("authority_operation")
            scope_id = command.payload.get(
                "scope_id", command.payload.get("workspace_id")
            )
            if not isinstance(authority_operation, str) or not isinstance(scope_id, str):
                raise KernelContractError(
                    "controlled_operation_authority_binding_missing",
                    "admission requires exact authority_operation and scope identity",
                )
            self._authorize(command, unit, authority_operation, scope_id)
            deadline = command.payload.get("deadline", command.payload.get("deadline_at"))
            if deadline is not None:
                try:
                    deadline_instant = datetime.fromisoformat(
                        str(deadline).replace("Z", "+00:00")
                    )
                    now_instant = datetime.fromisoformat(
                        self._clock.now_iso().replace("Z", "+00:00")
                    )
                except ValueError as exc:
                    raise KernelContractError(
                        "controlled_operation_deadline_invalid",
                        "ControlledOperation deadline is not an ISO-8601 instant",
                    ) from exc
                if (
                    deadline_instant.tzinfo is None
                    or now_instant.tzinfo is None
                    or deadline_instant <= now_instant
                ):
                    raise KernelContractError(
                        "controlled_operation_deadline_invalid",
                        "ControlledOperation deadline must be future and timezone-aware",
                    )
            approval_required = command.payload.get("approval_required", False)
            approval_id = command.payload.get("approval_id")
            if not isinstance(approval_required, bool):
                raise KernelContractError(
                    "controlled_operation_approval_binding_invalid",
                    "approval_required must be an exact boolean fact",
                )
            if approval_required is True:
                if not isinstance(approval_id, str):
                    raise KernelContractError(
                        "controlled_operation_approval_missing",
                        "ControlledOperation admission requires exact approval identity",
                    )
                approval = unit.read(entity_type="approval_request", entity_id=approval_id)
                approval_unexpired = False
                if approval is not None:
                    try:
                        approval_unexpired = _parse_instant(
                            str(approval.payload.get("expires_at"))
                        ) > _parse_instant(self._clock.now_iso())
                    except KernelContractError:
                        approval_unexpired = False
                if (
                    approval is None
                    or approval.payload.get("session_id") != command.context.session_id
                    or approval.payload.get("intent_digest") != command.intent_digest
                    or approval.payload.get("status") != "approved"
                    or not approval_unexpired
                ):
                    raise KernelContractError(
                        "controlled_operation_approval_invalid",
                        "Approval does not authorize the exact ControlledOperation intent",
                    )
            elif approval_id is not None:
                raise KernelContractError(
                    "controlled_operation_approval_binding_invalid",
                    "approval_id is forbidden when approval_required is false",
                )
            return (
                {
                    "session_id": command.context.session_id,
                    "actor_id": command.context.actor_id,
                    "owner_plugin_id": command.context.owner_plugin_id,
                    "operation_id": command.operation_id,
                    "intent_digest": command.intent_digest,
                    "route_id": command.context.route_id,
                    "authority_lease_id": command.context.authority_lease_id,
                    "authority_generation": command.context.authority_generation,
                    "authority_fence": command.context.authority_fence,
                    "authority_operation": authority_operation,
                    "scope_id": scope_id,
                    "dispatch_generation": 1,
                    "state": "admitted",
                    "effect_certainty": ExternalEffectCertainty.NO_EFFECT.value,
                    "mutation_applied": False,
                    "deadline": deadline,
                    "approval_required": approval_required is True,
                    "approval_id": approval_id,
                    "cancel_intent_digest": None,
                    "result_handle": None,
                    "terminal_receipt_digest": None,
                    "last_observation_digest": None,
                    "error_code": None,
                    "diagnostic_id": None,
                    "created_at": self._clock.now_iso(),
                    "updated_at": self._clock.now_iso(),
                    "safe_intent": dict(command.payload),
                    "fallback_performed": False,
                },
                ExternalEffectCertainty.NO_EFFECT,
            )

        if current is None:
            raise KernelContractError(
                "controlled_operation_not_found",
                "ControlledOperation settlement requires prior admission",
            )
        payload = dict(current.payload)
        intent_mismatch = payload.get("intent_digest") != command.intent_digest
        if command.operation is ControlledOperationCommandKind.CANCEL:
            intent_mismatch = False
        if (
            payload.get("session_id") != command.context.session_id
            or payload.get("actor_id") != command.context.actor_id
            or payload.get("owner_plugin_id") != command.context.owner_plugin_id
            or intent_mismatch
            or payload.get("route_id") != command.context.route_id
            or payload.get("authority_lease_id") != command.context.authority_lease_id
            or payload.get("authority_generation") != command.context.authority_generation
            or payload.get("authority_fence") != command.context.authority_fence
        ):
            raise KernelContractError(
                "controlled_operation_identity_stale",
                "settlement identity differs from durable admission",
            )
        authority_operation = payload.get("authority_operation")
        scope_id = payload.get("scope_id")
        if not isinstance(authority_operation, str) or not isinstance(scope_id, str):
            raise KernelContractError(
                "controlled_operation_state_invalid",
                "durable operation lacks authority binding",
            )
        current_state = payload.get("state")
        reconciliation_of_uncertain_effect = (
            command.operation is ControlledOperationCommandKind.RECONCILE
            and current_state == "reconcile_required"
        )
        if not reconciliation_of_uncertain_effect:
            self._authorize(command, unit, authority_operation, scope_id)
        if current_state in {"settled", "cancelled"}:
            raise KernelContractError(
                "controlled_operation_already_terminal",
                "terminal ControlledOperation cannot be rewritten",
            )
        if (
            command.operation is ControlledOperationCommandKind.CANCEL
            and "effect_certainty" not in command.payload
        ):
            certainty = ExternalEffectCertainty.NO_EFFECT
            mutation_applied = False
        else:
            certainty, mutation_applied = _effect_fact(command.payload)
        if command.operation is ControlledOperationCommandKind.RECONCILE:
            records_initial_uncertainty = (
                current_state == "admitted"
                and certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            )
            if current_state != "reconcile_required" and not records_initial_uncertainty:
                raise KernelContractError(
                    "controlled_operation_reconcile_not_required",
                    "reconcile is valid only for dispatch_in_doubt",
                )
        next_state = {
            ExternalEffectCertainty.NO_EFFECT: "settled",
            ExternalEffectCertainty.DISPATCH_IN_DOUBT: "reconcile_required",
            ExternalEffectCertainty.EFFECT_KNOWN: "active",
            ExternalEffectCertainty.TERMINAL_KNOWN: "settled",
        }[certainty]
        if command.operation is ControlledOperationCommandKind.CANCEL:
            payload["cancel_intent_digest"] = command.intent_digest
            next_state = (
                "reconcile_required"
                if certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
                else "cancel_requested"
            )
        elif command.operation not in {
            ControlledOperationCommandKind.OBSERVE,
            ControlledOperationCommandKind.RECONCILE,
        }:
            raise KernelContractError(
                "controlled_operation_transition_invalid",
                "ControlledOperation transition is not allowed",
            )
        payload.update(
            {
                "state": next_state,
                "effect_certainty": certainty.value,
                "mutation_applied": mutation_applied,
                "last_observation_digest": command.payload.get(
                    "adapter_receipt_digest"
                ),
                "result_handle": command.payload.get("result_handle"),
                "terminal_receipt_digest": command.payload.get(
                    "terminal_receipt_digest"
                ),
                "error_code": command.payload.get("error_code"),
                "diagnostic_id": command.payload.get("diagnostic_id"),
                "updated_at": self._clock.now_iso(),
                "fallback_performed": False,
            }
        )
        return payload, certainty

    def _authorize(self, command, unit, operation: str, scope_id: str) -> None:  # noqa: ANN001
        lease = unit.read(
            entity_type="agent_authority_lease",
            entity_id=command.context.authority_lease_id,
        )
        if lease is None:
            raise KernelContractError(
                "authority_lease_not_found",
                "ControlledOperation authority lease is absent",
            )
        decision = evaluate_authority_payload(
            payload=lease.payload,
            session_id=command.context.session_id,
            actor_id=command.context.actor_id,
            authority_lease_id=command.context.authority_lease_id,
            operation=operation,
            scope_id=scope_id,
            expected_generation=command.context.authority_generation,
            expected_fence=command.context.authority_fence,
            now_iso=self._clock.now_iso(),
        )
        if not decision.allowed:
            raise KernelContractError(
                decision.denial_code or "authority_operation_denied",
                "AgentAuthorityLease is stale or denies ControlledOperation",
                details={
                    "operation": operation,
                    "scope_id": scope_id,
                    "denial_code": decision.denial_code,
                },
            )


__all__ = ["ControlledOperationKernelApplicationService"]


def _parse_instant(value: str) -> datetime:
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise KernelContractError(
            "controlled_operation_time_invalid",
            "ControlledOperation time fact is not ISO-8601",
        ) from exc
    if instant.tzinfo is None:
        raise KernelContractError(
            "controlled_operation_time_invalid",
            "ControlledOperation time fact must be timezone-aware",
        )
    return instant
