from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from openzyme_contracts import ClockPort
from openzyme_contracts import AgentRuntimeSignalReason
from openzyme_contracts import ControlStorePort
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import WorkflowAuthoritySignalSourceKind
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_contracts.identity import JsonValue
from openzyme_contracts.identity import json_compatible
from openzyme_extension_spi import ApprovalApplicationCommand
from openzyme_extension_spi import ApprovalCommandKind
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelMutationReceipt

from .authority_application import evaluate_authority_payload
from .errors import KernelContractError
from .runtime_coordination_application import build_runtime_signal_payload
from .workflow_authority_application import ExistingWorkflowAuthoritySignalRequest
from .workflow_authority_application import WorkflowAuthorityUnitOfWorkOwner


def _instant(value: str) -> datetime:
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise KernelContractError(
            "approval_expiry_invalid",
            "Approval expiry must be a timezone-aware ISO-8601 instant",
        ) from exc
    if instant.tzinfo is None:
        raise KernelContractError(
            "approval_expiry_invalid",
            "Approval expiry must include a timezone",
        )
    return instant


class ApprovalKernelApplicationService:
    """Approval truth is separate from the operation it may authorize."""

    service_id = "openzyme.kernel.approval-application"

    def __init__(self, *, store: ControlStorePort, clock: ClockPort, ids: IdGeneratorPort) -> None:
        self._store = store
        self._clock = clock
        self._ids = ids
        self._workflow_authority = WorkflowAuthorityUnitOfWorkOwner(
            clock=clock,
            ids=ids,
        )

    def execute(self, command: ApprovalApplicationCommand) -> KernelMutationReceipt:
        allowed = (
            {
                "requested_action",
                "scope_id",
                "task_id",
                "expires_at",
                "reason",
                "workflow_authority_id",
                "workflow_authority_epoch",
                "workflow_authority_digest",
            }
            if command.operation is ApprovalCommandKind.REQUEST
            else {"decision", "resolution_ref", "reason"}
        )
        required = (
            {
                "requested_action",
                "scope_id",
                "expires_at",
                "workflow_authority_id",
                "workflow_authority_epoch",
                "workflow_authority_digest",
            }
            if command.operation is ApprovalCommandKind.REQUEST
            else {"decision", "resolution_ref"}
        )
        unknown = set(command.payload).difference(allowed)
        missing = required.difference(command.payload)
        if unknown or missing:
            raise KernelContractError(
                "approval_payload_invalid",
                "Approval payload differs from its closed operation contract",
                details={"unknown": sorted(unknown), "missing": sorted(missing)},
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
                    "operation": command.operation.value,
                    "approval_id": command.approval_id,
                    "intent_digest": command.intent_digest,
                    "payload": json_compatible(command.payload),
                }
            ),
        )
        unit = self._store.begin(request)
        try:
            session = unit.read(
                entity_type="session", entity_id=command.context.session_id
            )
            if session is None:
                raise KernelContractError(
                    "session_not_found",
                    "Approval command requires a canonical Session",
                )
            if session.state_version != command.context.expected_session_version:
                raise KernelContractError(
                    "session_state_version_stale",
                    "Session changed before Approval mutation",
                )
            self._authorize(command, unit)
            current = unit.read(
                entity_type="approval_request", entity_id=command.approval_id
            )
            now = self._clock.now_iso()
            signal_mutation: KernelStateMutation | None = None
            signal_id: str | None = None
            signal_link = None
            if command.operation is ApprovalCommandKind.REQUEST:
                if current is not None:
                    raise KernelContractError(
                        "approval_identity_conflict",
                        "ApprovalRequest identity already exists",
                    )
                expires_at = str(command.payload["expires_at"])
                if _instant(expires_at) <= _instant(now):
                    raise KernelContractError(
                        "approval_expiry_invalid",
                        "ApprovalRequest must expire in the future",
                    )
                authority_id, authority_epoch, authority_digest = (
                    self._authority_identity(command.payload)
                )
                workflow_binding = self._workflow_authority.require_current(
                    unit,
                    authority_id=authority_id,
                    expected_epoch=authority_epoch,
                    expected_binding_digest=authority_digest,
                    expected_actor_id=command.context.actor_id,
                )
                if workflow_binding.session_id != command.context.session_id:
                    raise KernelContractError(
                        "workflow_authority_session_mismatch",
                        "Approval workflow authority belongs to another Session",
                    )
                approval_payload: dict[str, JsonValue] = {
                    "approval_id": command.approval_id,
                    "session_id": command.context.session_id,
                    "requester_actor_id": command.context.actor_id,
                    "intent_digest": command.intent_digest,
                    "requested_action": command.payload["requested_action"],
                    "scope_id": command.payload["scope_id"],
                    "task_id": command.payload.get("task_id"),
                    "reason": command.payload.get("reason"),
                    "status": "pending",
                    "created_at": now,
                    "expires_at": expires_at,
                    "resolved_at": None,
                    "resolver_actor_id": None,
                    "resolution_ref": None,
                    "operation_dispatched": False,
                    "workflow_authority_id": authority_id,
                    "workflow_authority_epoch": authority_epoch,
                    "workflow_authority_digest": authority_digest,
                }
                mutation_kind = KernelMutationKind.CREATE
                expected_version = None
                next_version = 1
            else:
                if current is None:
                    raise KernelContractError(
                        "approval_not_found",
                        "Approval resolution requires an existing request",
                    )
                if (
                    current.payload.get("session_id") != command.context.session_id
                    or current.payload.get("intent_digest") != command.intent_digest
                ):
                    raise KernelContractError(
                        "approval_intent_mismatch",
                        "Approval resolution differs from the exact request intent",
                    )
                if current.payload.get("status") != "pending":
                    raise KernelContractError(
                        "approval_already_terminal",
                        "Terminal ApprovalRequest cannot be resolved again",
                    )
                if _instant(str(current.payload["expires_at"])) <= _instant(now):
                    raise KernelContractError(
                        "approval_expired",
                        "Expired ApprovalRequest cannot be consumed",
                    )
                decision = command.payload["decision"]
                if decision not in {"approved", "rejected"}:
                    raise KernelContractError(
                        "approval_decision_invalid",
                        "Approval decision must be approved or rejected",
                    )
                approval_payload = dict(current.payload)
                approval_payload.update(
                    {
                        "status": decision,
                        "reason": command.payload.get("reason"),
                        "resolution_ref": command.payload["resolution_ref"],
                        "resolver_actor_id": command.context.actor_id,
                        "resolved_at": now,
                        "operation_dispatched": False,
                    }
                )
                mutation_kind = KernelMutationKind.REPLACE
                expected_version = current.state_version
                next_version = current.state_version + 1
                requester_id = str(current.payload["requester_actor_id"])
                requester = unit.read(
                    entity_type="agent_member", entity_id=requester_id
                )
                if (
                    requester is None
                    or requester.payload.get("session_id")
                    != command.context.session_id
                    or requester.payload.get("status") != "active"
                ):
                    raise KernelContractError(
                        "approval_requester_runtime_unavailable",
                        "Approval requester is not an active Session member",
                    )
                target_lease_id = requester.payload.get(
                    "active_authority_lease_id"
                )
                workspace_generation = requester.payload.get(
                    "workspace_generation"
                )
                process_epoch = requester.payload.get("process_epoch")
                agent_id = requester.payload.get("agent_id")
                if (
                    not isinstance(target_lease_id, str)
                    or not isinstance(workspace_generation, int)
                    or isinstance(workspace_generation, bool)
                    or not isinstance(process_epoch, int)
                    or isinstance(process_epoch, bool)
                    or not isinstance(agent_id, str)
                ):
                    raise KernelContractError(
                        "approval_requester_runtime_binding_missing",
                        "Approval requester lacks an active authority/workspace binding",
                    )
                target_lease = unit.read(
                    entity_type="agent_authority_lease",
                    entity_id=target_lease_id,
                )
                if (
                    target_lease is None
                    or target_lease.payload.get("session_id")
                    != command.context.session_id
                    or target_lease.payload.get("agent_member_id") != requester_id
                    or target_lease.payload.get("agent_id") != agent_id
                    or target_lease.payload.get("workspace_generation")
                    != workspace_generation
                    or target_lease.payload.get("state") != "active"
                    or not isinstance(target_lease.payload.get("lease_digest"), str)
                ):
                    raise KernelContractError(
                        "approval_requester_authority_stale",
                        "Approval requester authority binding is stale",
                    )
                signal_id = self._ids.new_id(namespace="runtime-signal")
                signal_command_digest = canonical_sha256_digest(
                    {
                        "service_id": self.service_id,
                        "operation": "enqueue-requester-signal",
                        "approval_id": command.approval_id,
                        "approval_command_digest": request.command_digest,
                        "signal_id": signal_id,
                    }
                )
                signal_mutation = KernelStateMutation.create(
                        mutation_id=self._ids.new_id(namespace="mutation"),
                        kind=KernelMutationKind.CREATE,
                        entity_type="agent_runtime_signal",
                        entity_id=signal_id,
                        expected_state_version=None,
                        payload=build_runtime_signal_payload(
                            signal_id=signal_id,
                            session_id=command.context.session_id,
                            agent_id=agent_id,
                            agent_member_id=requester_id,
                            reason=AgentRuntimeSignalReason.APPROVAL_RESOLVED,
                            target_authority_lease_id=target_lease_id,
                            target_authority_lease_digest=str(
                                target_lease.payload["lease_digest"]
                            ),
                            workspace_generation=workspace_generation,
                            process_epoch=process_epoch,
                            correlation_id=command.context.correlation_id,
                            source_ref=command.approval_id,
                            task_id=(
                                str(current.payload["task_id"])
                                if current.payload.get("task_id") is not None
                                else None
                            ),
                            lane_id=(
                                str(requester.payload["lane_id"])
                                if requester.payload.get("lane_id") is not None
                                else None
                            ),
                            created_at=now,
                            enqueue_command_digest=signal_command_digest,
                        ),
                    )
                authority_id, authority_epoch, authority_digest = (
                    self._authority_identity(current.payload)
                )
                signal_link = self._workflow_authority.link_existing(
                    unit,
                    ExistingWorkflowAuthoritySignalRequest(
                        session_id=command.context.session_id,
                        authority_id=authority_id,
                        authority_epoch=authority_epoch,
                        authority_binding_digest=authority_digest,
                        authorized_actor_id=requester_id,
                        signal_id=signal_id,
                        causation_ref=command.approval_id,
                        source_kind=(
                            WorkflowAuthoritySignalSourceKind.APPROVAL_RESOLUTION
                        ),
                    ),
                )
            mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=mutation_kind,
                entity_type="approval_request",
                entity_id=command.approval_id,
                expected_state_version=expected_version,
                payload=approval_payload,
            )
            session_payload = dict(session.payload)
            session_payload["updated_at"] = now
            session_mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.REPLACE,
                entity_type="session",
                entity_id=command.context.session_id,
                expected_state_version=session.state_version,
                payload=session_payload,
            )
            unit.stage(mutation)
            if signal_mutation is not None:
                assert signal_link is not None
                self._workflow_authority.stage_runtime_signal_with_link(
                    unit,
                    signal_mutation=signal_mutation,
                    link=signal_link,
                )
            unit.stage(session_mutation)
            event = DurableEventRecord.create(
                event_id=self._ids.new_id(namespace="event"),
                session_id=command.context.session_id,
                event_type=f"approval.{command.operation.value}",
                source_entity_type="approval_request",
                source_entity_id=command.approval_id,
                source_state_version=next_version,
                command_id=command.context.command_id,
                payload={
                    "approval_id": command.approval_id,
                    "intent_digest": command.intent_digest,
                    "status": approval_payload["status"],
                    "workflow_authority_id": authority_id,
                    "workflow_authority_epoch": authority_epoch,
                    "workflow_authority_digest": authority_digest,
                    "runtime_signal_id": signal_id,
                    "runtime_signal_authority_link_digest": (
                        signal_link.link_digest if signal_link is not None else None
                    ),
                    "operation_dispatched": False,
                },
            )
            unit.append_event(event)
            outbox_payload: Mapping[str, JsonValue] = {
                "event_id": event.event_id,
                "event_digest": event.event_digest,
                "approval_id": command.approval_id,
                "status": approval_payload["status"],
                "workflow_authority_id": authority_id,
            }
            unit.append_outbox(
                OutboxRecord(
                    outbox_id=self._ids.new_id(namespace="outbox"),
                    session_id=command.context.session_id,
                    topic="openzyme.kernel.approval-events",
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
            entity_type="approval_request",
            entity_id=command.approval_id,
            state_version=next_version,
            payload=approval_payload,
        )
        entity_refs = [
            KernelEntityRef(
                entity_kind="approval_request",
                entity_id=command.approval_id,
                state_version=next_version,
                entity_digest=snapshot.record_digest,
            )
        ]
        if signal_link is not None:
            link_snapshot = KernelRecordSnapshot.create(
                entity_type="runtime_signal_authority_link",
                entity_id=signal_link.signal_id,
                state_version=1,
                payload=signal_link.to_dict(),
            )
            entity_refs.append(
                KernelEntityRef(
                    entity_kind=link_snapshot.entity_type,
                    entity_id=link_snapshot.entity_id,
                    state_version=link_snapshot.state_version,
                    entity_digest=link_snapshot.record_digest,
                )
            )
        return KernelMutationReceipt.create(
            command_id=command.context.command_id,
            service_id=self.service_id,
            operation=command.operation.value,
            mutation_applied=committed.committed,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            entity_refs=tuple(entity_refs),
            event_refs=(event.event_id,),
            result={
                "approval_id": command.approval_id,
                "status": approval_payload["status"],
                "workflow_authority_id": authority_id,
                "workflow_authority_epoch": authority_epoch,
                "workflow_authority_digest": authority_digest,
                "runtime_signal_id": signal_id,
                "runtime_signal_authority_link_digest": (
                    signal_link.link_digest if signal_link is not None else None
                ),
                "operation_dispatched": False,
            },
        )

    @staticmethod
    def _authority_identity(payload: Mapping[str, object]) -> tuple[str, int, str]:
        authority_id = payload.get("workflow_authority_id")
        authority_epoch = payload.get("workflow_authority_epoch")
        authority_digest = payload.get("workflow_authority_digest")
        try:
            if not isinstance(authority_id, str):
                raise ValueError("workflow authority ID must be a string")
            require_identifier(authority_id, field_name="workflow_authority_id")
            if (
                not isinstance(authority_epoch, int)
                or isinstance(authority_epoch, bool)
                or authority_epoch < 1
            ):
                raise ValueError("workflow authority epoch must be positive")
            if not isinstance(authority_digest, str):
                raise ValueError("workflow authority digest must be a string")
            require_digest(
                authority_digest,
                field_name="workflow_authority_digest",
            )
        except ValueError as exc:
            raise KernelContractError(
                "workflow_authority_identity_invalid",
                "Approval lacks an exact workflow authority identity",
            ) from exc
        return authority_id, authority_epoch, authority_digest

    def _authorize(self, command, unit) -> None:  # noqa: ANN001
        lease = unit.read(
            entity_type="agent_authority_lease",
            entity_id=command.context.authority_lease_id,
        )
        if lease is None:
            raise KernelContractError(
                "authority_lease_not_found",
                "Approval authority lease is absent",
            )
        operation = f"approval.{command.operation.value}"
        decision = evaluate_authority_payload(
            payload=lease.payload,
            session_id=command.context.session_id,
            actor_id=command.context.actor_id,
            authority_lease_id=command.context.authority_lease_id,
            operation=operation,
            scope_id=command.context.session_id,
            expected_generation=command.context.authority_generation,
            expected_fence=command.context.authority_fence,
            now_iso=self._clock.now_iso(),
        )
        if not decision.allowed:
            raise KernelContractError(
                decision.denial_code or "authority_operation_denied",
                "AgentAuthorityLease denies this Approval operation",
            )


__all__ = ["ApprovalKernelApplicationService"]
