from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import EvidenceKind
from openzyme_contracts import EvidenceRef
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import ApprovalApplicationCommand
from openzyme_extension_spi import ApprovalCommandKind
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_extension_spi import ProtocolApplicationCommand
from openzyme_extension_spi import ProtocolCommandKind
from openzyme_extension_spi import TaskApplicationCommand
from openzyme_extension_spi import TaskCommandKind
from openzyme_host_api import HostV2CommandError
from openzyme_host_api import HostV2MutationInvocation
from openzyme_kernel import AgentAuthorityLeaseKernelApplicationService
from openzyme_kernel import ApprovalKernelApplicationService
from openzyme_kernel import AuthorityLeaseIssueCommand
from openzyme_kernel import AuthorityLeaseRevokeCommand
from openzyme_kernel import CollaborationApplicationCommand
from openzyme_kernel import CollaborationCommandKind
from openzyme_kernel import CollaborationKernelApplicationService
from openzyme_kernel import MessageIngressCommand
from openzyme_kernel import MessageIngressKernelApplicationService
from openzyme_kernel import ProtocolKernelApplicationService
from openzyme_kernel import TaskKernelApplicationService


STANDARD_COORDINATION_ROUTE_IDS = (
    "openzyme.kernel.message.send@2",
    "openzyme.kernel.agent.register@2",
    "openzyme.kernel.agent.retire@2",
    "openzyme.kernel.approval.decide@2",
    "openzyme.kernel.approval.request@2",
    "openzyme.kernel.authority.issue@2",
    "openzyme.kernel.authority.revoke@2",
    "openzyme.kernel.lane.create@2",
    "openzyme.kernel.protocol.delegate@2",
    "openzyme.kernel.protocol.send@2",
    "openzyme.kernel.task.create@2",
    "openzyme.kernel.task.dependency.add@2",
    "openzyme.kernel.task.finish@2",
)


@dataclass(slots=True)
class EnzymeDesignKernelCoordinationRouteApplication:
    """Closed HTTP-to-Kernel translation for state-only coordination routes."""

    collaboration: CollaborationKernelApplicationService
    tasks: TaskKernelApplicationService
    protocols: ProtocolKernelApplicationService
    approvals: ApprovalKernelApplicationService
    authority_leases: AgentAuthorityLeaseKernelApplicationService
    message_ingress: MessageIngressKernelApplicationService
    ids: IdGeneratorPort

    def invoke(self, invocation: HostV2MutationInvocation) -> KernelMutationReceipt:
        route = invocation.route_id
        payload = dict(invocation.payload)
        if route == "openzyme.kernel.message.send@2":
            context = _message_ingress_context(invocation, ids=self.ids)
            message_id = _pop_identifier(payload, "message_id", self.ids, "message")
            content = _pop_text(payload, "content")
            task_id = _pop_optional_text(payload, "task_id")
            lane_id = _pop_optional_text(payload, "lane_id")
            raw_skill_keys = payload.pop("skill_keys", [])
            if payload or not isinstance(raw_skill_keys, tuple | list) or any(
                not isinstance(item, str) or not item for item in raw_skill_keys
            ):
                raise _payload_error(route)
            skill_keys = tuple(raw_skill_keys)
            if skill_keys != tuple(sorted(set(skill_keys))):
                raise _payload_error(route)
            return self.message_ingress.execute(
                MessageIngressCommand(
                    context=context,
                    message_id=message_id,
                    source_actor_id=invocation.actor_id,
                    content=content,
                    task_id=task_id,
                    lane_id=lane_id,
                    skill_keys=skill_keys,
                )
            )
        context = build_enzymedesign_command_context(invocation, ids=self.ids)
        if route == "openzyme.kernel.task.create@2":
            entity_id = _pop_identifier(payload, "task_id", self.ids, "task")
            payload.setdefault("owner_actor_id", context.actor_id)
            return self.collaboration.execute(
                CollaborationApplicationCommand(
                    context=context,
                    operation=CollaborationCommandKind.CREATE_TASK,
                    entity_id=entity_id,
                    payload=payload,
                )
            )
        if route == "openzyme.kernel.task.dependency.add@2":
            return self.collaboration.execute(
                CollaborationApplicationCommand(
                    context=context,
                    operation=CollaborationCommandKind.ADD_TASK_DEPENDENCY,
                    entity_id=_path_identifier(invocation.path, "tasks"),
                    payload=payload,
                )
            )
        if route == "openzyme.kernel.task.finish@2":
            task_id = _path_identifier(invocation.path, "tasks")
            task = _projected_record(invocation, "tasks", "task_id", task_id)
            raw_evidence = payload.pop("evidence_refs", [])
            if payload or not isinstance(raw_evidence, tuple | list):
                raise _payload_error(route)
            return self.tasks.execute(
                TaskApplicationCommand(
                    context=context,
                    operation=TaskCommandKind.FINISH,
                    task_id=task_id,
                    expected_task_version=_state_version(task),
                    payload={},
                    evidence_refs=tuple(
                        _evidence_ref(item) for item in raw_evidence
                    ),
                )
            )
        if route == "openzyme.kernel.lane.create@2":
            entity_id = _pop_identifier(payload, "lane_id", self.ids, "lane")
            return self.collaboration.execute(
                CollaborationApplicationCommand(
                    context=context,
                    operation=CollaborationCommandKind.CREATE_LANE,
                    entity_id=entity_id,
                    payload=payload,
                )
            )
        if route == "openzyme.kernel.agent.register@2":
            entity_id = _pop_identifier(
                payload,
                "agent_member_id",
                self.ids,
                "agent-member",
            )
            return self.collaboration.execute(
                CollaborationApplicationCommand(
                    context=context,
                    operation=CollaborationCommandKind.REGISTER_AGENT,
                    entity_id=entity_id,
                    payload=payload,
                )
            )
        if route == "openzyme.kernel.agent.retire@2":
            return self.collaboration.execute(
                CollaborationApplicationCommand(
                    context=context,
                    operation=CollaborationCommandKind.RETIRE_AGENT,
                    entity_id=_path_identifier(invocation.path, "agents"),
                    payload=payload,
                )
            )
        if route in {
            "openzyme.kernel.protocol.delegate@2",
            "openzyme.kernel.protocol.send@2",
        }:
            protocol_ref = _pop_identifier(
                payload,
                "protocol_ref",
                self.ids,
                "protocol",
            )
            operation = (
                ProtocolCommandKind.DELEGATE
                if route.endswith("delegate@2")
                else ProtocolCommandKind.SEND
            )
            return self.protocols.execute(
                ProtocolApplicationCommand(
                    context=context,
                    operation=operation,
                    protocol_ref=protocol_ref,
                    payload=payload,
                )
            )
        if route in {
            "openzyme.kernel.approval.request@2",
            "openzyme.kernel.approval.decide@2",
        }:
            requesting = route.endswith("request@2")
            approval_id = (
                _pop_identifier(payload, "approval_id", self.ids, "approval")
                if requesting
                else _path_identifier(invocation.path, "approvals")
            )
            intent_digest = _pop_text(payload, "intent_digest")
            return self.approvals.execute(
                ApprovalApplicationCommand(
                    context=context,
                    operation=(
                        ApprovalCommandKind.REQUEST
                        if requesting
                        else ApprovalCommandKind.CONSUME
                    ),
                    approval_id=approval_id,
                    intent_digest=intent_digest,
                    payload=payload,
                )
            )
        if route == "openzyme.kernel.authority.issue@2":
            raw_lease = payload.pop("lease", None)
            expected_parent_version = payload.pop("expected_parent_version", None)
            if payload or not isinstance(raw_lease, Mapping):
                raise _payload_error(route)
            return self.authority_leases.issue(
                AuthorityLeaseIssueCommand(
                    context=context,
                    lease=AgentAuthorityLease.from_dict(raw_lease),
                    expected_parent_version=(
                        None
                        if expected_parent_version is None
                        else int(expected_parent_version)
                    ),
                )
            )
        if route == "openzyme.kernel.authority.revoke@2":
            lease_id = _path_identifier(invocation.path, "authority-leases")
            lease = _projected_record(
                invocation,
                "authority_leases",
                "lease_id",
                lease_id,
            )
            reason = _pop_text(payload, "reason")
            if payload:
                raise _payload_error(route)
            return self.authority_leases.revoke(
                AuthorityLeaseRevokeCommand(
                    context=context,
                    lease_id=lease_id,
                    expected_lease_version=_state_version(lease),
                    reason=reason,
                )
            )
        raise HostV2CommandError(
            "enzymedesign_coordination_route_unknown",
            "The coordination application does not own this Kernel route",
            status_code=503,
            mutation_applied=False,
            effect_certainty="no_effect",
            details={"route_id": route},
        )


def build_enzymedesign_coordination_route_applications(
    application: EnzymeDesignKernelCoordinationRouteApplication,
) -> dict[str, EnzymeDesignKernelCoordinationRouteApplication]:
    return {route_id: application for route_id in STANDARD_COORDINATION_ROUTE_IDS}


def build_enzymedesign_command_context(
    invocation: HostV2MutationInvocation,
    *,
    ids: IdGeneratorPort,
) -> KernelCommandContext:
    core = invocation.precondition.projection.core.payload
    session = core.get("session")
    leases = core.get("authority_leases")
    agents = core.get("agents")
    if (
        not isinstance(session, Mapping)
        or not isinstance(leases, tuple | list)
        or not isinstance(agents, tuple | list)
    ):
        raise _projection_error("Core coordination identity is incomplete")
    lease_payload = next(
        (
            item
            for item in leases
            if isinstance(item, Mapping)
            and item.get("lease_id")
            == invocation.precondition.query_context.authority_lease_id
        ),
        None,
    )
    if not isinstance(lease_payload, Mapping):
        raise _projection_error("Projection authority lease is absent")
    closed_lease = dict(lease_payload)
    closed_lease.pop("state_version", None)
    try:
        lease = AgentAuthorityLease.from_dict(closed_lease)
    except (TypeError, ValueError) as exc:
        raise _projection_error("Projection authority lease is invalid") from exc
    if invocation.actor_id.startswith("agent-member:"):
        actor_id = invocation.actor_id.removeprefix("agent-member:")
        if actor_id != lease.agent_member_id:
            raise _projection_error("Authenticated Agent differs from projection lease")
    elif invocation.actor_id == "user:local-dev":
        actor_id = lease.agent_member_id
    else:
        raise HostV2CommandError(
            "enzymedesign_operator_agent_authority_required",
            "Shared user principals cannot impersonate an Agent authority lease",
            status_code=403,
            mutation_applied=False,
            effect_certainty="no_effect",
        )
    member = next(
        (
            item
            for item in agents
            if isinstance(item, Mapping)
            and item.get("agent_member_id") == actor_id
        ),
        None,
    )
    if not isinstance(member, Mapping):
        raise _projection_error("Projection authority member is absent")
    workspace_generation = member.get("workspace_generation")
    if workspace_generation is not None and (
        not isinstance(workspace_generation, int)
        or isinstance(workspace_generation, bool)
        or workspace_generation < 1
    ):
        raise _projection_error("Projection workspace generation is invalid")
    return KernelCommandContext(
        command_id=ids.new_id(namespace="command"),
        session_id=invocation.session_id,
        actor_id=actor_id,
        owner_plugin_id="openzyme.kernel",
        authority_lease_id=lease.lease_id,
        authority_generation=lease.generation,
        authority_fence=lease.fence,
        expected_session_version=_state_version(session),
        extension_bundle_digest=(
            invocation.precondition.query_context.extension_bundle_digest
        ),
        capability_binding_digest=(
            invocation.precondition.capability_binding_digest
        ),
        idempotency_key=invocation.idempotency_key,
        correlation_id=invocation.correlation_id,
        workspace_generation=workspace_generation,
    )


def _message_ingress_context(
    invocation: HostV2MutationInvocation,
    *,
    ids: IdGeneratorPort,
) -> KernelCommandContext:
    if not invocation.actor_id.startswith("user:"):
        return build_enzymedesign_command_context(invocation, ids=ids)
    core = invocation.precondition.projection.core.payload
    agents = core.get("agents")
    if not isinstance(agents, tuple | list):
        raise _projection_error("Core Agent section is invalid")
    masters = tuple(
        item
        for item in agents
        if isinstance(item, Mapping)
        and item.get("role") == "master"
        and item.get("parent_agent_id") is None
        and item.get("status") == "active"
    )
    if len(masters) != 1:
        raise _projection_error("Session has no unique active root Agent")
    master_id = masters[0].get("agent_member_id")
    if not isinstance(master_id, str) or not master_id:
        raise _projection_error("Root Agent identity is invalid")
    projected = HostV2MutationInvocation(
        route_id=invocation.route_id,
        method=invocation.method,
        path=invocation.path,
        session_id=invocation.session_id,
        actor_id=f"agent-member:{master_id}",
        idempotency_key=invocation.idempotency_key,
        correlation_id=invocation.correlation_id,
        payload=invocation.payload,
        precondition=invocation.precondition,
    )
    return build_enzymedesign_command_context(projected, ids=ids)


def _evidence_ref(value: object) -> EvidenceRef:
    if not isinstance(value, Mapping):
        raise _payload_error("openzyme.kernel.task.finish@2")
    expected = {
        "schema_version",
        "evidence_id",
        "evidence_kind",
        "contract_id",
        "owner_component_id",
        "project_id",
        "session_id",
        "task_id",
        "subject_ref",
        "subject_digest",
        "attributes",
    }
    if set(value) != expected or value.get("schema_version") != "evidence_ref@1":
        raise _payload_error("openzyme.kernel.task.finish@2")
    attributes = value["attributes"]
    if not isinstance(attributes, Mapping):
        raise _payload_error("openzyme.kernel.task.finish@2")
    return EvidenceRef(
        evidence_id=str(value["evidence_id"]),
        evidence_kind=EvidenceKind(str(value["evidence_kind"])),
        contract_id=str(value["contract_id"]),
        owner_component_id=str(value["owner_component_id"]),
        project_id=str(value["project_id"]),
        session_id=str(value["session_id"]),
        task_id=str(value["task_id"]),
        subject_ref=str(value["subject_ref"]),
        subject_digest=str(value["subject_digest"]),
        attributes=attributes,
    )


def _projected_record(
    invocation: HostV2MutationInvocation,
    section: str,
    identity_field: str,
    identity: str,
) -> Mapping[str, JsonValue]:
    records = invocation.precondition.projection.core.payload.get(section)
    if not isinstance(records, tuple | list):
        raise _projection_error(f"Core {section} section is invalid")
    matches = tuple(
        item
        for item in records
        if isinstance(item, Mapping) and item.get(identity_field) == identity
    )
    if len(matches) != 1:
        raise _projection_error(f"Core {section} identity is absent or ambiguous")
    return matches[0]


def _state_version(payload: Mapping[str, object]) -> int:
    value = payload.get("state_version")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _projection_error("Core record lacks a canonical state_version")
    return value


def _path_identifier(path: str, collection: str) -> str:
    parts = tuple(part for part in path.split("/") if part)
    try:
        index = parts.index(collection)
        value = parts[index + 1]
    except (ValueError, IndexError) as exc:
        raise _payload_error("path") from exc
    if not value or "{" in value or "}" in value:
        raise _payload_error("path")
    return value


def _pop_identifier(
    payload: dict[str, JsonValue],
    field_name: str,
    ids: IdGeneratorPort,
    namespace: str,
) -> str:
    value = payload.pop(field_name, None)
    if value is None:
        return ids.new_id(namespace=namespace)
    if not isinstance(value, str) or not value:
        raise _payload_error(field_name)
    return value


def _pop_text(payload: dict[str, JsonValue], field_name: str) -> str:
    value = payload.pop(field_name, None)
    if not isinstance(value, str) or not value or value != value.strip():
        raise _payload_error(field_name)
    return value


def _pop_optional_text(
    payload: dict[str, JsonValue], field_name: str
) -> str | None:
    value = payload.pop(field_name, None)
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise _payload_error(field_name)
    return value


def _payload_error(route_id: str) -> HostV2CommandError:
    return HostV2CommandError(
        "enzymedesign_kernel_route_payload_invalid",
        "Kernel route payload differs from its closed application contract",
        status_code=422,
        mutation_applied=False,
        effect_certainty="no_effect",
        details={"route_id": route_id},
    )


def _projection_error(message: str) -> HostV2CommandError:
    return HostV2CommandError(
        "enzymedesign_kernel_route_projection_stale",
        message,
        status_code=409,
        mutation_applied=False,
        effect_certainty="no_effect",
    )


__all__ = [
    "STANDARD_COORDINATION_ROUTE_IDS",
    "EnzymeDesignKernelCoordinationRouteApplication",
    "build_enzymedesign_command_context",
    "build_enzymedesign_coordination_route_applications",
]
