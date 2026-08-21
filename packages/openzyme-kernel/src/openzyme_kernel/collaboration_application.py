from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from openzyme_contracts import ClockPort
from openzyme_contracts import ControlStorePort
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_identifier
from openzyme_contracts.identity import JsonValue
from openzyme_contracts.identity import freeze_json
from openzyme_contracts.identity import json_compatible
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelMutationReceipt

from .authority_application import evaluate_authority_payload
from .errors import KernelContractError


class CollaborationCommandKind(StrEnum):
    CREATE_SESSION = "create_session"
    CREATE_TASK = "create_task"
    ADD_TASK_DEPENDENCY = "add_task_dependency"
    CREATE_LANE = "create_lane"
    REGISTER_AGENT = "register_agent"
    RECORD_CONVERSATION = "record_conversation"
    WRITE_MEMORY = "write_memory"
    RETIRE_AGENT = "retire_agent"


@dataclass(frozen=True, slots=True)
class CollaborationApplicationCommand:
    context: KernelCommandContext
    operation: CollaborationCommandKind
    entity_id: str
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        require_identifier(self.entity_id, field_name="entity_id")
        payload = freeze_json(self.payload, field_name="payload")
        if not isinstance(payload, Mapping):
            raise ValueError("payload must be a JSON object")
        object.__setattr__(self, "payload", payload)


_FIELDS = {
    CollaborationCommandKind.CREATE_SESSION: (
        frozenset({"project_id", "title", "objective"}),
        frozenset({"project_id", "title", "objective"}),
    ),
    CollaborationCommandKind.CREATE_TASK: (
        frozenset(
            {
                "subject",
                "description",
                "owner_actor_id",
                "priority",
                "kind",
                "lane_id",
                "finish_validator_ids",
            }
        ),
        frozenset({"subject", "description", "owner_actor_id"}),
    ),
    CollaborationCommandKind.ADD_TASK_DEPENDENCY: (
        frozenset({"dependency_task_id"}),
        frozenset({"dependency_task_id"}),
    ),
    CollaborationCommandKind.CREATE_LANE: (
        frozenset({"name", "workspace_binding_id"}),
        frozenset({"name"}),
    ),
    CollaborationCommandKind.REGISTER_AGENT: (
        frozenset({"name", "role", "parent_agent_id", "lane_id"}),
        frozenset({"name", "role"}),
    ),
    CollaborationCommandKind.RECORD_CONVERSATION: (
        frozenset({"sender_kind", "content", "message_type", "correlation_id"}),
        frozenset({"sender_kind", "content", "message_type"}),
    ),
    CollaborationCommandKind.WRITE_MEMORY: (
        frozenset({"scope_kind", "scope_ref", "kind", "summary", "source_range"}),
        frozenset({"scope_kind", "scope_ref", "kind", "summary"}),
    ),
    CollaborationCommandKind.RETIRE_AGENT: (
        frozenset({"reason", "terminal_proof_digest"}),
        frozenset({"reason", "terminal_proof_digest"}),
    ),
}


class CollaborationKernelApplicationService:
    """Canonical owner for domain-neutral collaboration facts."""

    service_id = "openzyme.kernel.collaboration-application"

    def __init__(self, *, store: ControlStorePort, clock: ClockPort, ids: IdGeneratorPort) -> None:
        self._store = store
        self._clock = clock
        self._ids = ids

    def execute(
        self,
        command: CollaborationApplicationCommand,
    ) -> KernelMutationReceipt:
        if command.operation is CollaborationCommandKind.CREATE_SESSION:
            raise KernelContractError(
                "session_bootstrap_command_required",
                "The first Session, master member and root authority lease must be "
                "created by the explicit operator-authorized bootstrap service",
            )
        allowed, required = _FIELDS[command.operation]
        unknown = set(command.payload).difference(allowed)
        missing = required.difference(command.payload)
        if unknown or missing:
            raise KernelContractError(
                "collaboration_payload_invalid",
                "Collaboration payload differs from its closed operation contract",
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
                    "entity_id": command.entity_id,
                    "payload": json_compatible(command.payload),
                }
            ),
        )
        unit = self._store.begin(request)
        try:
            session = unit.read(
                entity_type="session", entity_id=command.context.session_id
            )
            if command.operation is CollaborationCommandKind.CREATE_SESSION:
                if session is not None or command.entity_id != command.context.session_id:
                    raise KernelContractError(
                        "session_identity_conflict",
                        "Session create requires one absent exact Session identity",
                    )
            else:
                if session is None:
                    raise KernelContractError(
                        "session_not_found",
                        "Collaboration command requires a canonical Session",
                    )
                if session.state_version != command.context.expected_session_version:
                    raise KernelContractError(
                        "session_state_version_stale",
                        "Session changed before collaboration mutation",
                    )
            self._authorize(command, unit)
            now = self._clock.now_iso()
            mutations, primary = self._reduce(command, unit, now=now)
            if command.operation is not CollaborationCommandKind.CREATE_SESSION:
                session_payload = dict(session.payload)
                session_payload["updated_at"] = now
                mutations.append(
                    KernelStateMutation.create(
                        mutation_id=self._ids.new_id(namespace="mutation"),
                        kind=KernelMutationKind.REPLACE,
                        entity_type="session",
                        entity_id=command.context.session_id,
                        expected_state_version=session.state_version,
                        payload=session_payload,
                    )
                )
            for mutation in mutations:
                unit.stage(mutation)
            event = DurableEventRecord.create(
                event_id=self._ids.new_id(namespace="event"),
                session_id=command.context.session_id,
                event_type=f"collaboration.{command.operation.value}",
                source_entity_type=primary.entity_type,
                source_entity_id=primary.entity_id,
                source_state_version=primary.state_version,
                command_id=command.context.command_id,
                payload={
                    "entity_id": command.entity_id,
                    "operation": command.operation.value,
                    "task_transition_performed": False,
                    "runtime_executed": False,
                },
            )
            unit.append_event(event)
            outbox_payload: Mapping[str, JsonValue] = {
                "event_id": event.event_id,
                "event_digest": event.event_digest,
                "operation": command.operation.value,
                "entity_id": command.entity_id,
            }
            unit.append_outbox(
                OutboxRecord(
                    outbox_id=self._ids.new_id(namespace="outbox"),
                    session_id=command.context.session_id,
                    topic="openzyme.kernel.collaboration-events",
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
        return KernelMutationReceipt.create(
            command_id=command.context.command_id,
            service_id=self.service_id,
            operation=command.operation.value,
            mutation_applied=committed.committed,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            entity_refs=(
                KernelEntityRef(
                    entity_kind=primary.entity_type,
                    entity_id=primary.entity_id,
                    state_version=primary.state_version,
                    entity_digest=primary.record_digest,
                ),
            ),
            event_refs=(event.event_id,),
            result={
                "entity_id": command.entity_id,
                "task_transition_performed": False,
                "runtime_executed": False,
            },
        )

    def _authorize(self, command, unit) -> None:  # noqa: ANN001
        lease = unit.read(
            entity_type="agent_authority_lease",
            entity_id=command.context.authority_lease_id,
        )
        if lease is None:
            raise KernelContractError(
                "authority_lease_not_found",
                "Collaboration authority lease is absent",
            )
        operation = f"collaboration.{command.operation.value}"
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
                "AgentAuthorityLease denies this collaboration operation",
            )

    def _reduce(self, command, unit, *, now: str):  # noqa: ANN001
        operation = command.operation
        payload = dict(command.payload)
        if operation is CollaborationCommandKind.CREATE_SESSION:
            record_payload = {
                **payload,
                "session_id": command.entity_id,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }
            return self._single_create("session", command.entity_id, record_payload)

        if operation is CollaborationCommandKind.REGISTER_AGENT:
            parent_id = payload.get("parent_agent_id")
            if parent_id is not None:
                parent = unit.read(entity_type="agent_member", entity_id=str(parent_id))
                if (
                    parent is None
                    or parent.payload.get("session_id") != command.context.session_id
                    or parent.payload.get("status")
                    in {"completed", "failed", "stopped", "shutdown"}
                ):
                    raise KernelContractError(
                        "agent_parent_unavailable",
                        "parent Agent is absent, retired or belongs elsewhere",
                    )
            record_payload = {
                **payload,
                "session_id": command.context.session_id,
                "agent_member_id": command.entity_id,
                "agent_id": command.entity_id,
                "parent_agent_id": parent_id,
                "lane_id": payload.get("lane_id"),
                "status": "active",
                "process_epoch": 1,
                "active_authority_lease_id": None,
                "workspace_generation": None,
                "owned_task_ids": [],
                "retirement_reason": None,
                "terminal_proof_digest": None,
                "retirement_settled": False,
                "retired_at": None,
                "created_at": now,
                "updated_at": now,
            }
            return self._single_create("agent_member", command.entity_id, record_payload)

        if operation is CollaborationCommandKind.CREATE_TASK:
            owner_id = str(payload["owner_actor_id"])
            owner = unit.read(entity_type="agent_member", entity_id=owner_id)
            if (
                owner is None
                or owner.payload.get("session_id") != command.context.session_id
                or owner.payload.get("status")
                in {"completed", "failed", "stopped", "shutdown"}
            ):
                raise KernelContractError(
                    "task_owner_unavailable",
                    "Task owner Agent is absent, retired or belongs elsewhere",
                )
            task_payload = {
                **payload,
                "session_id": command.context.session_id,
                "task_id": command.entity_id,
                "status": "todo",
                "priority": payload.get("priority", "normal"),
                "kind": payload.get("kind", "general"),
                "lane_id": payload.get("lane_id"),
                "blocked_by": [],
                "finish_validator_ids": payload.get("finish_validator_ids", []),
                "assigned_ref": None,
                "failure_summary": None,
                "failure_ref": None,
                "evidence_refs": [],
                "finish_evidence_refs": [],
                "finish_validation_digest": None,
                "finished_by_actor_id": None,
                "created_at": now,
                "updated_at": now,
            }
            task_mutation, task_snapshot = self._create(
                "task", command.entity_id, task_payload
            )
            owned = owner.payload.get("owned_task_ids", ())
            if not isinstance(owned, tuple | list):
                raise KernelContractError(
                    "agent_owned_task_state_invalid",
                    "Agent owned Task index is invalid",
                )
            owner_payload = dict(owner.payload)
            owner_payload["owned_task_ids"] = sorted({*owned, command.entity_id})
            owner_payload["updated_at"] = now
            owner_mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.REPLACE,
                entity_type="agent_member",
                entity_id=owner_id,
                expected_state_version=owner.state_version,
                payload=owner_payload,
            )
            return [task_mutation, owner_mutation], task_snapshot

        if operation is CollaborationCommandKind.ADD_TASK_DEPENDENCY:
            task = self._session_record(unit, "task", command.entity_id, command)
            dependency_id = str(payload["dependency_task_id"])
            self._session_record(unit, "task", dependency_id, command)
            if dependency_id == command.entity_id or self._depends_on(
                unit, dependency_id, command.entity_id, seen=set()
            ):
                raise KernelContractError(
                    "task_dependency_cycle",
                    "Task dependency would create a directed cycle",
                )
            blocked_by = task.payload.get("blocked_by", ())
            if not isinstance(blocked_by, tuple | list):
                raise KernelContractError(
                    "task_dependency_state_invalid",
                    "Task dependency state is invalid",
                )
            updated = dict(task.payload)
            updated["blocked_by"] = sorted({*blocked_by, dependency_id})
            updated["updated_at"] = now
            mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.REPLACE,
                entity_type="task",
                entity_id=command.entity_id,
                expected_state_version=task.state_version,
                payload=updated,
            )
            snapshot = KernelRecordSnapshot.create(
                entity_type="task",
                entity_id=command.entity_id,
                state_version=task.state_version + 1,
                payload=updated,
            )
            return [mutation], snapshot

        if operation is CollaborationCommandKind.CREATE_LANE:
            record_payload = {
                **payload,
                "session_id": command.context.session_id,
                "lane_id": command.entity_id,
                "workspace_binding_id": payload.get("workspace_binding_id"),
                "status": "idle",
                "created_at": now,
                "updated_at": now,
            }
            return self._single_create("lane", command.entity_id, record_payload)

        if operation is CollaborationCommandKind.RECORD_CONVERSATION:
            record_payload = {
                **payload,
                "session_id": command.context.session_id,
                "message_id": command.entity_id,
                "sender_actor_id": command.context.actor_id,
                "admitted_by_actor_id": command.context.actor_id,
                "correlation_id": payload.get("correlation_id"),
                "task_id": payload.get("task_id"),
                "lane_id": payload.get("lane_id"),
                "skill_keys": payload.get("skill_keys", []),
                "created_at": now,
            }
            return self._single_create(
                "conversation_message", command.entity_id, record_payload
            )

        if operation is CollaborationCommandKind.WRITE_MEMORY:
            record_payload = {
                **payload,
                "session_id": command.context.session_id,
                "memory_id": command.entity_id,
                "author_actor_id": command.context.actor_id,
                "source_range": payload.get("source_range"),
                "created_at": now,
            }
            return self._single_create("memory", command.entity_id, record_payload)

        if operation is CollaborationCommandKind.RETIRE_AGENT:
            member = self._session_record(
                unit, "agent_member", command.entity_id, command
            )
            if command.entity_id != command.context.actor_id:
                raise KernelContractError(
                    "agent_retirement_owner_required",
                    "This reducer permits only explicit self-retirement",
                )
            owned_task_ids = member.payload.get("owned_task_ids", ())
            if not isinstance(owned_task_ids, tuple | list):
                raise KernelContractError(
                    "agent_owned_task_state_invalid",
                    "Agent owned Task index is invalid",
                )
            unsettled = []
            for task_id in owned_task_ids:
                task = unit.read(entity_type="task", entity_id=str(task_id))
                if task is not None and task.payload.get("status") not in {
                    "completed",
                    "failed",
                    "cancelled",
                }:
                    unsettled.append(str(task_id))
            if unsettled:
                raise KernelContractError(
                    "agent_retirement_ownership_unsettled",
                    "Agent retirement requires all owned Tasks to be terminal or transferred",
                    details={"task_ids": sorted(unsettled)},
                )
            member_payload = dict(member.payload)
            member_payload.update(
                {
                    "status": "shutdown",
                    "process_epoch": int(member.payload.get("process_epoch", 1)) + 1,
                    "retirement_reason": payload["reason"],
                    "terminal_proof_digest": payload["terminal_proof_digest"],
                    "retirement_settled": True,
                    "retired_at": now,
                    "updated_at": now,
                }
            )
            member_mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.REPLACE,
                entity_type="agent_member",
                entity_id=command.entity_id,
                expected_state_version=member.state_version,
                payload=member_payload,
            )
            lease = unit.read(
                entity_type="agent_authority_lease",
                entity_id=command.context.authority_lease_id,
            )
            lease_payload = dict(lease.payload)
            lease_payload.update(
                {
                    "state": "revoked",
                    "fence": command.context.authority_fence + 1,
                    "updated_at": now,
                }
            )
            lease_mutation = KernelStateMutation.create(
                mutation_id=self._ids.new_id(namespace="mutation"),
                kind=KernelMutationKind.REPLACE,
                entity_type="agent_authority_lease",
                entity_id=command.context.authority_lease_id,
                expected_state_version=lease.state_version,
                payload=lease_payload,
            )
            snapshot = KernelRecordSnapshot.create(
                entity_type="agent_member",
                entity_id=command.entity_id,
                state_version=member.state_version + 1,
                payload=member_payload,
            )
            return [member_mutation, lease_mutation], snapshot

        raise AssertionError("closed CollaborationCommandKind is exhaustive")

    def _single_create(self, entity_type: str, entity_id: str, payload):  # noqa: ANN001
        mutation, snapshot = self._create(entity_type, entity_id, payload)
        return [mutation], snapshot

    def _create(self, entity_type: str, entity_id: str, payload):  # noqa: ANN001
        mutation = KernelStateMutation.create(
            mutation_id=self._ids.new_id(namespace="mutation"),
            kind=KernelMutationKind.CREATE,
            entity_type=entity_type,
            entity_id=entity_id,
            expected_state_version=None,
            payload=payload,
        )
        snapshot = KernelRecordSnapshot.create(
            entity_type=entity_type,
            entity_id=entity_id,
            state_version=1,
            payload=payload,
        )
        return mutation, snapshot

    @staticmethod
    def _session_record(unit, entity_type, entity_id, command):  # noqa: ANN001
        record = unit.read(entity_type=entity_type, entity_id=entity_id)
        if record is None or record.payload.get("session_id") != command.context.session_id:
            raise KernelContractError(
                "collaboration_entity_not_found",
                "Collaboration entity is absent from the command Session",
            )
        return record

    def _depends_on(self, unit, task_id: str, target_id: str, *, seen: set[str]):  # noqa: ANN001
        if task_id in seen:
            return False
        seen.add(task_id)
        task = unit.read(entity_type="task", entity_id=task_id)
        if task is None:
            return False
        dependencies = task.payload.get("blocked_by", ())
        if not isinstance(dependencies, tuple | list):
            raise KernelContractError(
                "task_dependency_state_invalid",
                "Task dependency state is invalid",
            )
        return target_id in dependencies or any(
            self._depends_on(unit, str(item), target_id, seen=seen)
            for item in dependencies
        )


__all__ = [
    "CollaborationApplicationCommand",
    "CollaborationCommandKind",
    "CollaborationKernelApplicationService",
]
