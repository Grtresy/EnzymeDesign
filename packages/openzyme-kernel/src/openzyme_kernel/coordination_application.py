from __future__ import annotations

from collections.abc import Mapping

from openzyme_contracts import ClockPort
from openzyme_contracts import ControlStorePort
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import FailureObservation
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import PrivateDiagnosticRecord
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import validate_failure_diagnostic_pair
from openzyme_contracts.identity import JsonValue
from openzyme_contracts.identity import json_compatible
from openzyme_extension_spi import ContinuationApplicationCommand
from openzyme_extension_spi import ContinuationCommandKind
from openzyme_extension_spi import FailureRecordCommand
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelMutationReceipt

from .authority_application import evaluate_authority_payload
from .errors import KernelContractError


def _authorized(
    *,
    unit,
    context,
    clock: ClockPort,
    operation: str,
    scope_id: str,
) -> None:  # noqa: ANN001
    lease = unit.read(
        entity_type="agent_authority_lease",
        entity_id=context.authority_lease_id,
    )
    if lease is None:
        raise KernelContractError(
            "authority_lease_not_found",
            "coordination authority lease is absent",
        )
    decision = evaluate_authority_payload(
        payload=lease.payload,
        session_id=context.session_id,
        actor_id=context.actor_id,
        authority_lease_id=context.authority_lease_id,
        operation=operation,
        scope_id=scope_id,
        expected_generation=context.authority_generation,
        expected_fence=context.authority_fence,
        now_iso=clock.now_iso(),
    )
    if not decision.allowed:
        raise KernelContractError(
            decision.denial_code or "authority_operation_denied",
            "AgentAuthorityLease denies this coordination operation",
        )


def _require_session(unit, context):  # noqa: ANN001
    session = unit.read(entity_type="session", entity_id=context.session_id)
    if session is None:
        raise KernelContractError(
            "session_not_found",
            "coordination command requires a canonical Session",
        )
    if session.state_version != context.expected_session_version:
        raise KernelContractError(
            "session_state_version_stale",
            "Session changed before coordination mutation",
        )
    return session


class ContinuationKernelApplicationService:
    service_id = "openzyme.kernel.continuation-application"

    def __init__(
        self, *, store: ControlStorePort, clock: ClockPort, ids: IdGeneratorPort
    ) -> None:
        self._store = store
        self._clock = clock
        self._ids = ids

    def execute(self, command: ContinuationApplicationCommand) -> KernelMutationReceipt:
        allowed = {
            ContinuationCommandKind.REGISTER: {
                "source_ref",
                "source_digest",
                "recipient_actor_id",
                "resume_strategy",
            },
            ContinuationCommandKind.DELIVER: {
                "delivery_receipt_digest",
                "process_epoch",
            },
            ContinuationCommandKind.FAIL: {"failure_id", "error_code", "process_epoch"},
        }[command.operation]
        required = allowed
        if set(command.payload) != required:
            raise KernelContractError(
                "continuation_payload_invalid",
                "Continuation payload differs from its closed operation contract",
                details={
                    "unknown": sorted(set(command.payload).difference(allowed)),
                    "missing": sorted(required.difference(command.payload)),
                },
            )
        digest_payload = {
            "context": command.context.to_dict(),
            "operation": command.operation.value,
            "continuation_id": command.continuation_id,
            "source_version": command.source_version,
            "payload": json_compatible(command.payload),
        }
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
            command_digest=canonical_sha256_digest(
                {"service_id": self.service_id, **digest_payload}
            ),
        )
        unit = self._store.begin(request)
        try:
            _require_session(unit, command.context)
            _authorized(
                unit=unit,
                context=command.context,
                clock=self._clock,
                operation=f"continuation.{command.operation.value}",
                scope_id=command.continuation_id,
            )
            current = unit.read(
                entity_type="continuation", entity_id=command.continuation_id
            )
            now = self._clock.now_iso()
            if command.operation is ContinuationCommandKind.REGISTER:
                if current is not None:
                    raise KernelContractError(
                        "continuation_identity_conflict",
                        "Continuation identity already exists",
                    )
                recipient = unit.read(
                    entity_type="agent_member",
                    entity_id=str(command.payload["recipient_actor_id"]),
                )
                if (
                    recipient is None
                    or recipient.payload.get("session_id") != command.context.session_id
                    or recipient.payload.get("status") != "active"
                ):
                    raise KernelContractError(
                        "continuation_recipient_unavailable",
                        "Continuation recipient is not an active Session member",
                    )
                process_epoch = recipient.payload.get("process_epoch")
                if (
                    not isinstance(process_epoch, int)
                    or isinstance(process_epoch, bool)
                    or process_epoch < 1
                ):
                    raise KernelContractError(
                        "continuation_process_epoch_invalid",
                        "Continuation recipient lacks a canonical process epoch",
                    )
                continuation_payload: dict[str, JsonValue] = {
                    "continuation_id": command.continuation_id,
                    "session_id": command.context.session_id,
                    "owner_actor_id": command.context.actor_id,
                    "source_version": command.source_version,
                    "source_ref": command.payload["source_ref"],
                    "source_digest": command.payload["source_digest"],
                    "recipient_actor_id": command.payload["recipient_actor_id"],
                    "resume_strategy": command.payload["resume_strategy"],
                    "process_epoch": process_epoch,
                    "state": "ready",
                    "delivery_attempt": 0,
                    "delivery_receipt_digest": None,
                    "failure_id": None,
                    "error_code": None,
                    "created_at": now,
                    "updated_at": now,
                    "task_transition_performed": False,
                }
                mutation_kind = KernelMutationKind.CREATE
                expected_version = None
                next_version = 1
            else:
                if current is None:
                    raise KernelContractError(
                        "continuation_not_found",
                        "Continuation transition requires prior registration",
                    )
                if current.payload.get("session_id") != command.context.session_id:
                    raise KernelContractError(
                        "continuation_session_mismatch",
                        "Continuation belongs to another Session",
                    )
                if current.payload.get("source_version") != command.source_version:
                    raise KernelContractError(
                        "continuation_source_version_stale",
                        "Continuation source version differs from registration",
                    )
                if current.payload.get("state") != "ready":
                    raise KernelContractError(
                        "continuation_already_terminal",
                        "Terminal Continuation cannot be delivered again",
                    )
                if (
                    current.payload.get("process_epoch")
                    != command.payload["process_epoch"]
                ):
                    raise KernelContractError(
                        "continuation_process_epoch_stale",
                        "Continuation process epoch is stale",
                    )
                continuation_payload = dict(current.payload)
                continuation_payload.update(
                    {
                        "state": (
                            "delivered"
                            if command.operation is ContinuationCommandKind.DELIVER
                            else "failed"
                        ),
                        "delivery_attempt": int(
                            current.payload.get("delivery_attempt", 0)
                        )
                        + 1,
                        "delivery_receipt_digest": command.payload.get(
                            "delivery_receipt_digest"
                        ),
                        "failure_id": command.payload.get("failure_id"),
                        "error_code": command.payload.get("error_code"),
                        "updated_at": now,
                        "task_transition_performed": False,
                    }
                )
                mutation_kind = KernelMutationKind.REPLACE
                expected_version = current.state_version
                next_version = current.state_version + 1
            mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=mutation_kind,
                entity_type="continuation",
                entity_id=command.continuation_id,
                expected_state_version=expected_version,
                payload=continuation_payload,
            )
            unit.stage(mutation)
            event = DurableEventRecord.create(
                event_id=self._ids.new_id(namespace="event"),
                session_id=command.context.session_id,
                event_type=f"continuation.{command.operation.value}",
                source_entity_type="continuation",
                source_entity_id=command.continuation_id,
                source_state_version=next_version,
                command_id=command.context.command_id,
                payload={
                    "continuation_id": command.continuation_id,
                    "state": continuation_payload["state"],
                    "source_version": command.source_version,
                    "process_epoch": continuation_payload["process_epoch"],
                    "task_transition_performed": False,
                },
            )
            unit.append_event(event)
            outbox_payload: Mapping[str, JsonValue] = {
                "event_id": event.event_id,
                "event_digest": event.event_digest,
                "continuation_id": command.continuation_id,
                "state": continuation_payload["state"],
            }
            unit.append_outbox(
                OutboxRecord(
                    outbox_id=self._ids.new_id(namespace="outbox"),
                    session_id=command.context.session_id,
                    topic="openzyme.kernel.continuation-events",
                    occurrence_id=event.event_id,
                    payload=outbox_payload,
                    payload_digest=canonical_sha256_digest(outbox_payload),
                    created_at=now,
                )
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        snapshot = KernelRecordSnapshot.create(
            entity_type="continuation",
            entity_id=command.continuation_id,
            state_version=next_version,
            payload=continuation_payload,
        )
        return KernelMutationReceipt.create(
            command_id=command.context.command_id,
            service_id=self.service_id,
            operation=command.operation.value,
            mutation_applied=committed.committed,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            entity_refs=(
                KernelEntityRef(
                    entity_kind="continuation",
                    entity_id=command.continuation_id,
                    state_version=next_version,
                    entity_digest=snapshot.record_digest,
                ),
            ),
            event_refs=(event.event_id,),
            result={
                "continuation_id": command.continuation_id,
                "state": continuation_payload["state"],
                "task_transition_performed": False,
            },
        )


class FailureKernelApplicationService:
    service_id = "openzyme.kernel.failure-application"

    def __init__(
        self, *, store: ControlStorePort, clock: ClockPort, ids: IdGeneratorPort
    ) -> None:
        self._store = store
        self._clock = clock
        self._ids = ids

    def record(
        self,
        command: FailureRecordCommand,
        *,
        private_diagnostic: PrivateDiagnosticRecord | None = None,
        authorization_operation: str = "failure.record",
    ) -> KernelMutationReceipt:
        observation = command.observation
        if not authorization_operation or any(
            character.isspace() for character in authorization_operation
        ):
            raise ValueError(
                "authorization_operation must be non-empty and whitespace-free"
            )
        if observation.session_id != command.context.session_id:
            raise KernelContractError(
                "failure_session_mismatch",
                "FailureObservation belongs to another Session",
            )
        if private_diagnostic is not None:
            try:
                validate_failure_diagnostic_pair(observation, private_diagnostic)
            except ValueError as exc:
                raise KernelContractError(
                    "failure_private_diagnostic_identity_mismatch",
                    "FailureObservation and private diagnostic differ",
                    details={
                        "failure_id": observation.failure_id,
                        "diagnostic_id": observation.diagnostic_id,
                        "mutation_applied": False,
                        "fallback_performed": False,
                    },
                ) from exc
        elif observation.private_diagnostic_digest is not None:
            raise KernelContractError(
                "failure_private_diagnostic_missing",
                "FailureObservation private diagnostic sidecar is missing",
                details={
                    "failure_id": observation.failure_id,
                    "diagnostic_id": observation.diagnostic_id,
                    "mutation_applied": False,
                    "fallback_performed": False,
                },
            )
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
            command_digest=canonical_sha256_digest(
                {
                    "service_id": self.service_id,
                    "context": command.context.to_dict(),
                    "observation": observation.to_internal_dict(),
                    "authorization_operation": authorization_operation,
                }
            ),
        )
        unit = self._store.begin(request)
        try:
            _require_session(unit, command.context)
            _authorized(
                unit=unit,
                context=command.context,
                clock=self._clock,
                operation=authorization_operation,
                scope_id=command.context.session_id,
            )
            existing_failure = unit.read(
                entity_type="failure_observation", entity_id=observation.failure_id
            )
            existing_private = unit.read(
                entity_type="private_diagnostic",
                entity_id=observation.diagnostic_id,
            )
            if existing_failure is not None:
                public_matches = (
                    json_compatible(existing_failure.payload)
                    == observation.to_internal_dict()
                )
                private_matches = (
                    private_diagnostic is None
                    and existing_private is None
                    or private_diagnostic is not None
                    and existing_private is not None
                    and json_compatible(existing_private.payload)
                    == private_diagnostic.to_dict()
                )
                if public_matches and private_matches:
                    unit.rollback()
                    return self._receipt(
                        command=command,
                        observation=observation,
                        private_diagnostic=private_diagnostic,
                        mutation_applied=False,
                        event_refs=(),
                        duplicate=True,
                    )
                raise KernelContractError(
                    "failure_identity_conflict",
                    "FailureObservation identity already names another public/private pair",
                    details={
                        "failure_id": observation.failure_id,
                        "diagnostic_id": observation.diagnostic_id,
                        "public_matches": public_matches,
                        "private_matches": private_matches,
                        "mutation_applied": False,
                        "fallback_performed": False,
                    },
                )
            if existing_private is not None:
                raise KernelContractError(
                    "failure_private_diagnostic_identity_conflict",
                    "Private diagnostic identity exists without the matching failure",
                    details={
                        "failure_id": observation.failure_id,
                        "diagnostic_id": observation.diagnostic_id,
                        "mutation_applied": False,
                        "fallback_performed": False,
                    },
                )
            mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.CREATE,
                entity_type="failure_observation",
                entity_id=observation.failure_id,
                expected_state_version=None,
                payload=observation.to_internal_dict(),
            )
            unit.stage(mutation)
            if private_diagnostic is not None:
                unit.stage(
                    KernelStateMutation.create(
                        mutation_id=self._ids.new_id(namespace="mutation"),
                        kind=KernelMutationKind.CREATE,
                        entity_type="private_diagnostic",
                        entity_id=private_diagnostic.diagnostic_id,
                        expected_state_version=None,
                        payload=private_diagnostic.to_dict(),
                    )
                )
            event = DurableEventRecord.create(
                event_id=self._ids.new_id(namespace="event"),
                session_id=command.context.session_id,
                event_type="failure.recorded",
                source_entity_type="failure_observation",
                source_entity_id=observation.failure_id,
                source_state_version=1,
                command_id=command.context.command_id,
                payload={
                    "failure_id": observation.failure_id,
                    "error_code": observation.error_code,
                    "effect_certainty": observation.effect_certainty.value,
                    "diagnostic_id": observation.diagnostic_id,
                    "task_transition_performed": False,
                },
            )
            unit.append_event(event)
            outbox_payload: Mapping[str, JsonValue] = {
                "event_id": event.event_id,
                "event_digest": event.event_digest,
                "failure_id": observation.failure_id,
                "diagnostic_id": observation.diagnostic_id,
            }
            unit.append_outbox(
                OutboxRecord(
                    outbox_id=self._ids.new_id(namespace="outbox"),
                    session_id=command.context.session_id,
                    topic="openzyme.kernel.failure-events",
                    occurrence_id=event.event_id,
                    payload=outbox_payload,
                    payload_digest=canonical_sha256_digest(outbox_payload),
                    created_at=self._clock.now_iso(),
                )
            )
            committed = unit.commit()
        except Exception:
            unit.rollback()
            raise
        return self._receipt(
            command=command,
            observation=observation,
            private_diagnostic=private_diagnostic,
            mutation_applied=committed.committed,
            event_refs=(event.event_id,),
            duplicate=False,
        )

    def _receipt(
        self,
        *,
        command: FailureRecordCommand,
        observation: FailureObservation,
        private_diagnostic: PrivateDiagnosticRecord | None,
        mutation_applied: bool,
        event_refs: tuple[str, ...],
        duplicate: bool,
    ) -> KernelMutationReceipt:
        snapshot = KernelRecordSnapshot.create(
            entity_type="failure_observation",
            entity_id=observation.failure_id,
            state_version=1,
            payload=observation.to_internal_dict(),
        )
        entity_refs = [
            KernelEntityRef(
                entity_kind="failure_observation",
                entity_id=observation.failure_id,
                state_version=1,
                entity_digest=snapshot.record_digest,
            )
        ]
        if private_diagnostic is not None:
            private_snapshot = KernelRecordSnapshot.create(
                entity_type="private_diagnostic",
                entity_id=private_diagnostic.diagnostic_id,
                state_version=1,
                payload=private_diagnostic.to_dict(),
            )
            entity_refs.append(
                KernelEntityRef(
                    entity_kind="private_diagnostic",
                    entity_id=private_diagnostic.diagnostic_id,
                    state_version=1,
                    entity_digest=private_snapshot.record_digest,
                )
            )
        return KernelMutationReceipt.create(
            command_id=command.context.command_id,
            service_id=self.service_id,
            operation="record",
            mutation_applied=mutation_applied,
            effect_certainty=observation.effect_certainty,
            entity_refs=tuple(entity_refs),
            event_refs=event_refs,
            result={
                "failure_id": observation.failure_id,
                "diagnostic_id": observation.diagnostic_id,
                "duplicate": duplicate,
                "task_transition_performed": False,
            },
        )


__all__ = [
    "ContinuationKernelApplicationService",
    "FailureKernelApplicationService",
]
