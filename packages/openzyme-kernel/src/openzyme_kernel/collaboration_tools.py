from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import replace
from typing import Protocol

from openzyme_contracts import EvidenceKind
from openzyme_contracts import EvidenceRef
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_contracts.identity import JsonValue
from openzyme_contracts.identity import json_compatible
from openzyme_extension_spi import ApprovalApplicationCommand
from openzyme_extension_spi import ApprovalCommandKind
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_extension_spi import ProtocolApplicationCommand
from openzyme_extension_spi import ProtocolCommandKind
from openzyme_extension_spi import TaskApplicationCommand
from openzyme_extension_spi import TaskCommandKind

from .catalog import DeclaredToolEntry
from .collaboration_application import CollaborationApplicationCommand
from .collaboration_application import CollaborationCommandKind
from .errors import KernelContractError


_OWNER_COMPONENT_ID = "openzyme.kernel"
_TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "cancelled"})
_NON_TERMINAL_TASK_STATUSES = frozenset({"todo", "in_progress", "blocked"})
_TASK_UPDATE_FIELDS = frozenset(
    {
        "subject",
        "description",
        "priority",
        "assigned_ref",
        "lane_id",
        "blocked_by",
        "failure_summary",
        "failure_ref",
        "status",
    }
)


def _object_schema(
    properties: Mapping[str, JsonValue],
    *,
    required: tuple[str, ...] = (),
) -> dict[str, JsonValue]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(required),
        "additionalProperties": False,
    }


_IDENTIFIER: dict[str, JsonValue] = {
    "type": "string",
    "minLength": 1,
    "maxLength": 512,
}
_TEXT: dict[str, JsonValue] = {
    "type": "string",
    "minLength": 1,
    "maxLength": 16_384,
}
_DIGEST: dict[str, JsonValue] = {
    "type": "string",
    "pattern": "^sha256:[0-9a-f]{64}$",
}


def kernel_collaboration_tool_specs() -> tuple[ToolSpec, ...]:
    """Return the stable Kernel-owned resident collaboration vocabulary."""

    task_update_properties: dict[str, JsonValue] = {
        "subject": _TEXT,
        "description": _TEXT,
        "priority": {
            "type": "string",
            "enum": ["low", "normal", "high", "urgent"],
        },
        "assigned_ref": {"type": ["string", "null"], "maxLength": 512},
        "lane_id": {"type": ["string", "null"], "maxLength": 512},
        "blocked_by": {
            "type": "array",
            "items": _IDENTIFIER,
            "maxItems": 256,
        },
        "failure_summary": {"type": ["string", "null"], "maxLength": 16_384},
        "failure_ref": {"type": ["string", "null"], "maxLength": 512},
        "status": {
            "type": "string",
            "enum": sorted(_NON_TERMINAL_TASK_STATUSES),
        },
    }
    evidence_ref = _object_schema(
        {
            "evidence_id": _IDENTIFIER,
            "evidence_kind": {
                "type": "string",
                "enum": [item.value for item in EvidenceKind],
            },
            "contract_id": _IDENTIFIER,
            "owner_component_id": _IDENTIFIER,
            "project_id": _IDENTIFIER,
            "session_id": _IDENTIFIER,
            "task_id": _IDENTIFIER,
            "subject_ref": _IDENTIFIER,
            "subject_digest": _DIGEST,
            "attributes": {"type": "object"},
        },
        required=(
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
        ),
    )
    return (
        ToolSpec(
            tool_name="world.inspect",
            description=(
                "读取当前 runtime command 的 bounded canonical world facts；"
                "conversation 或 memory 中的相反文字不会覆盖这些事实。"
            ),
            input_schema=_object_schema(
                {
                    "sections": {
                        "type": "array",
                        "items": _IDENTIFIER,
                        "maxItems": 32,
                    },
                    "cursor": {"type": ["string", "null"], "maxLength": 2048},
                    "max_items": {"type": "integer", "minimum": 1, "maximum": 200},
                }
            ),
            required_authorities=("world.inspect",),
        ),
        ToolSpec(
            tool_name="capabilities.inspect",
            description=(
                "安全检查非 Hidden 能力，并可按 exact tool name 在当前 runtime command "
                "内扩展 currently callable Deferred tools；不会扩大 authority 或改变 route。"
            ),
            input_schema=_object_schema(
                {
                    "query": {"type": ["string", "null"], "maxLength": 1024},
                    "expand_tool_names": {
                        "type": "array",
                        "items": _IDENTIFIER,
                        "maxItems": 32,
                    },
                    "max_items": {"type": "integer", "minimum": 1, "maximum": 200},
                }
            ),
            required_authorities=("capabilities.inspect",),
        ),
        ToolSpec(
            tool_name="task.create",
            description="创建一个 canonical non-terminal Task；不会调度或运行 Agent。",
            input_schema=_object_schema(
                {
                    "task_id": _IDENTIFIER,
                    "subject": _TEXT,
                    "description": _TEXT,
                    "owner_actor_id": _IDENTIFIER,
                    "priority": {
                        "type": "string",
                        "enum": ["low", "normal", "high", "urgent"],
                    },
                    "kind": _IDENTIFIER,
                    "lane_id": {"type": ["string", "null"], "maxLength": 512},
                    "finish_validator_ids": {
                        "type": "array",
                        "items": _IDENTIFIER,
                        "maxItems": 32,
                    },
                },
                required=("task_id", "subject", "description"),
            ),
            required_authorities=("task.create",),
        ),
        ToolSpec(
            tool_name="task.update",
            description=(
                "更新 Task 的普通字段或 non-terminal status；completed/failed/cancelled "
                "必须使用 task.finish。"
            ),
            input_schema=_object_schema(
                {
                    "task_id": _IDENTIFIER,
                    "expected_task_version": {
                        "type": "integer",
                        "minimum": 1,
                    },
                    "updates": _object_schema(task_update_properties),
                },
                required=("task_id", "expected_task_version", "updates"),
            ),
            required_authorities=("task.update",),
        ),
        ToolSpec(
            tool_name="task.finish",
            description=(
                "显式请求 Task business terminal transition；要求 exact version、"
                "closed disposition 和已登记 EvidenceRef。"
            ),
            input_schema=_object_schema(
                {
                    "task_id": _IDENTIFIER,
                    "expected_task_version": {
                        "type": "integer",
                        "minimum": 1,
                    },
                    "terminal_status": {
                        "type": "string",
                        "enum": sorted(_TERMINAL_TASK_STATUSES),
                    },
                    "failure_summary": {"type": ["string", "null"], "maxLength": 16_384},
                    "failure_ref": {"type": ["string", "null"], "maxLength": 512},
                    "evidence_refs": {
                        "type": "array",
                        "items": evidence_ref,
                        "maxItems": 64,
                    },
                },
                required=("task_id", "expected_task_version", "terminal_status"),
            ),
            required_authorities=("task.finish",),
        ),
        ToolSpec(
            tool_name="task.delegate",
            description=(
                "通过 Protocol owner 把 Task 委派给一个 resident teammate，并只派生"
                "当前 workflow authority 的 causal subset；recipient 只被排队。"
            ),
            input_schema=_object_schema(
                {
                    "protocol_ref": _IDENTIFIER,
                    "task_id": _IDENTIFIER,
                    "recipient_actor_id": _IDENTIFIER,
                    "instruction": _TEXT,
                    "parent_agent_id": _IDENTIFIER,
                    "workflow_refs": {
                        "type": "array",
                        "items": _IDENTIFIER,
                        "maxItems": 64,
                    },
                },
                required=(
                    "protocol_ref",
                    "task_id",
                    "recipient_actor_id",
                    "instruction",
                    "workflow_refs",
                ),
            ),
            required_authorities=("protocol.delegate",),
        ),
        ToolSpec(
            tool_name="protocol.send",
            description=(
                "持久化一条 protocol inbox message 并排队 exact wakeup；"
                "绝不同步运行 recipient。"
            ),
            input_schema=_object_schema(
                {
                    "protocol_ref": _IDENTIFIER,
                    "recipient_actor_id": _IDENTIFIER,
                    "message_type": _IDENTIFIER,
                    "content": _TEXT,
                    "task_id": {"type": ["string", "null"], "maxLength": 512},
                },
                required=(
                    "protocol_ref",
                    "recipient_actor_id",
                    "message_type",
                    "content",
                ),
            ),
            required_authorities=("protocol.send",),
        ),
        ToolSpec(
            tool_name="approval.request",
            description=(
                "创建一个 pending approval intent；human resolution 与后续 Agent wakeup "
                "仍是独立 product command。"
            ),
            input_schema=_object_schema(
                {
                    "approval_id": _IDENTIFIER,
                    "requested_action": _IDENTIFIER,
                    "scope_id": _IDENTIFIER,
                    "task_id": {"type": ["string", "null"], "maxLength": 512},
                    "expires_at": {"type": "string", "minLength": 1, "maxLength": 128},
                    "reason": {"type": ["string", "null"], "maxLength": 4096},
                },
                required=(
                    "approval_id",
                    "requested_action",
                    "scope_id",
                    "expires_at",
                ),
            ),
            required_authorities=("approval.request",),
        ),
    )


_SPECS = {spec.tool_name: spec for spec in kernel_collaboration_tool_specs()}


def kernel_collaboration_declared_tool_entries() -> tuple[DeclaredToolEntry, ...]:
    return tuple(
        DeclaredToolEntry(
            owner_component_id=_OWNER_COMPONENT_ID,
            runtime_id=f"openzyme.kernel.runtime.{spec.tool_name}",
            contract=spec,
            requirements=(),
            requires_workspace=False,
            requires_explicit_route=False,
        )
        for spec in kernel_collaboration_tool_specs()
    )


@dataclass(frozen=True, slots=True)
class ResolvedCollaborationToolContext:
    """Current fenced application scope, loaded again for every invocation."""

    command_context: KernelCommandContext
    runtime_command_id: str
    workflow_authority_id: str
    workflow_authority_epoch: int
    workflow_authority_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.runtime_command_id, field_name="runtime_command_id")
        require_identifier(
            self.workflow_authority_id,
            field_name="workflow_authority_id",
        )
        if self.workflow_authority_epoch < 1:
            raise ValueError("workflow_authority_epoch must be positive")
        require_digest(
            self.workflow_authority_digest,
            field_name="workflow_authority_digest",
        )


class CollaborationToolContextResolver(Protocol):
    """Revalidate command, workflow, authority, workspace and release fences."""

    def resolve(
        self,
        invocation: ToolInvocation,
        *,
        effectful: bool,
    ) -> ResolvedCollaborationToolContext: ...


class WorldInspectionApplicationPort(Protocol):
    def inspect(
        self,
        *,
        context: ResolvedCollaborationToolContext,
        arguments: Mapping[str, JsonValue],
    ) -> Mapping[str, JsonValue]: ...


class CollaborationApplicationPort(Protocol):
    def execute(
        self,
        command: CollaborationApplicationCommand,
    ) -> KernelMutationReceipt: ...


class TaskApplicationPort(Protocol):
    def execute(self, command: TaskApplicationCommand) -> KernelMutationReceipt: ...


class ProtocolToolApplicationPort(Protocol):
    def delegate(
        self,
        command: ProtocolApplicationCommand,
    ) -> KernelMutationReceipt: ...

    def send(self, command: ProtocolApplicationCommand) -> KernelMutationReceipt: ...


class ApprovalApplicationPort(Protocol):
    def execute(self, command: ApprovalApplicationCommand) -> KernelMutationReceipt: ...


@dataclass(frozen=True, slots=True)
class CollaborationToolApplications:
    world: WorldInspectionApplicationPort
    collaboration: CollaborationApplicationPort
    tasks: TaskApplicationPort
    protocol: ProtocolToolApplicationPort
    approvals: ApprovalApplicationPort


@dataclass(slots=True)
class KernelCollaborationToolRuntime:
    tool_name: str
    applications: CollaborationToolApplications
    context_resolver: CollaborationToolContextResolver

    def __post_init__(self) -> None:
        if self.tool_name not in _SPECS or self.tool_name == "capabilities.inspect":
            raise ValueError("unknown or gateway-owned Kernel collaboration tool")

    @property
    def owner_component_id(self) -> str:
        return _OWNER_COMPONENT_ID

    @property
    def runtime_id(self) -> str:
        return f"openzyme.kernel.runtime.{self.tool_name}"

    @property
    def contract(self) -> ToolSpec:
        return _SPECS[self.tool_name]

    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        if invocation.tool_name != self.tool_name:
            return _rejected(
                invocation,
                code="collaboration_tool_contract_mismatch",
                summary="Tool invocation does not match this runtime contract.",
            )
        try:
            if self.tool_name == "world.inspect":
                return self._inspect_world(invocation)
            context = self.context_resolver.resolve(invocation, effectful=True)
            if self.tool_name == "task.create":
                receipt = self._create_task(invocation, context)
            elif self.tool_name == "task.update":
                receipt = self._update_task(invocation, context)
            elif self.tool_name == "task.finish":
                receipt = self._finish_task(invocation, context)
            elif self.tool_name == "task.delegate":
                receipt = self._delegate_task(invocation, context)
            elif self.tool_name == "protocol.send":
                receipt = self._send_protocol(invocation, context)
            else:
                receipt = self._request_approval(invocation, context)
            return _receipt_result(invocation, receipt)
        except KernelContractError as exc:
            return _rejected(invocation, code=exc.code, summary=str(exc))
        except (KeyError, TypeError, ValueError) as exc:
            return _rejected(
                invocation,
                code="invalid_tool_arguments",
                summary=str(exc),
            )
        except Exception:
            diagnostic_id = _stable_identity(
                "diagnostic",
                invocation.session_id,
                invocation.call_id,
                invocation.tool_name,
            )
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                status="runtime_contract_failure",
                summary=(
                    "The Kernel collaboration application failed without a terminal receipt."
                ),
                payload={
                    "effect_certainty": "dispatch_in_doubt",
                    "mutation_applied": None,
                    "fallback_performed": False,
                    "retry_performed": False,
                    "reconcile_required": True,
                    "diagnostic_id": diagnostic_id,
                },
                error_code="collaboration_application_failed",
                hint=(
                    "Reconcile the exact command/call identity; do not retry or switch route."
                ),
            )

    def _inspect_world(self, invocation: ToolInvocation) -> ToolResult:
        _require_closed_arguments(
            invocation.arguments,
            allowed={"sections", "cursor", "max_items"},
        )
        context = self.context_resolver.resolve(invocation, effectful=False)
        facts = self.applications.world.inspect(
            context=context,
            arguments=invocation.arguments,
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            status="world_inspected",
            summary="Read bounded canonical world facts without mutation.",
            payload={
                "facts": json_compatible(facts),
                "mutation_applied": False,
                "task_transition_performed": False,
                "runtime_executed": False,
                "fallback_performed": False,
            },
        )

    def _create_task(
        self,
        invocation: ToolInvocation,
        resolved: ResolvedCollaborationToolContext,
    ) -> KernelMutationReceipt:
        _require_closed_arguments(
            invocation.arguments,
            allowed={
                "task_id",
                "subject",
                "description",
                "owner_actor_id",
                "priority",
                "kind",
                "lane_id",
                "finish_validator_ids",
            },
            required={"task_id", "subject", "description"},
        )
        payload: dict[str, JsonValue] = {
            "subject": _required_string(invocation.arguments, "subject"),
            "description": _required_string(invocation.arguments, "description"),
            "owner_actor_id": _optional_string(
                invocation.arguments,
                "owner_actor_id",
                default=resolved.command_context.actor_id,
            )
            or resolved.command_context.actor_id,
        }
        for key in ("priority", "kind", "lane_id", "finish_validator_ids"):
            if key in invocation.arguments:
                payload[key] = invocation.arguments[key]
        command = CollaborationApplicationCommand(
            context=_call_context(resolved.command_context, invocation),
            operation=CollaborationCommandKind.CREATE_TASK,
            entity_id=_required_string(invocation.arguments, "task_id"),
            payload=payload,
        )
        return self.applications.collaboration.execute(command)

    def _update_task(
        self,
        invocation: ToolInvocation,
        resolved: ResolvedCollaborationToolContext,
    ) -> KernelMutationReceipt:
        _require_closed_arguments(
            invocation.arguments,
            allowed={"task_id", "expected_task_version", "updates"},
            required={"task_id", "expected_task_version", "updates"},
        )
        updates = _required_object(invocation.arguments, "updates")
        unexpected = set(updates).difference(_TASK_UPDATE_FIELDS)
        if unexpected:
            raise ValueError(f"task.update fields are closed: {sorted(unexpected)}")
        status = updates.get("status")
        if status in _TERMINAL_TASK_STATUSES:
            raise KernelContractError(
                "task_terminal_transition_requires_finish",
                "Task terminal state requires an explicit task.finish command.",
            )
        if status is not None and status not in _NON_TERMINAL_TASK_STATUSES:
            raise ValueError("task.update status must be non-terminal")
        return self.applications.tasks.execute(
            TaskApplicationCommand(
                context=_call_context(resolved.command_context, invocation),
                operation=TaskCommandKind.UPDATE_NON_TERMINAL,
                task_id=_required_string(invocation.arguments, "task_id"),
                expected_task_version=_required_integer(
                    invocation.arguments,
                    "expected_task_version",
                ),
                payload=updates,
            )
        )

    def _finish_task(
        self,
        invocation: ToolInvocation,
        resolved: ResolvedCollaborationToolContext,
    ) -> KernelMutationReceipt:
        _require_closed_arguments(
            invocation.arguments,
            allowed={
                "task_id",
                "expected_task_version",
                "terminal_status",
                "failure_summary",
                "failure_ref",
                "evidence_refs",
            },
            required={"task_id", "expected_task_version", "terminal_status"},
        )
        terminal_status = _required_string(invocation.arguments, "terminal_status")
        if terminal_status not in _TERMINAL_TASK_STATUSES:
            raise ValueError("task.finish terminal_status is invalid")
        payload: dict[str, JsonValue] = {"terminal_status": terminal_status}
        for key in ("failure_summary", "failure_ref"):
            if key in invocation.arguments and invocation.arguments[key] is not None:
                payload[key] = invocation.arguments[key]
        raw_evidence = invocation.arguments.get("evidence_refs", ())
        if not isinstance(raw_evidence, tuple | list):
            raise ValueError("evidence_refs must be an array")
        evidence_refs = tuple(_evidence_ref(item) for item in raw_evidence)
        return self.applications.tasks.execute(
            TaskApplicationCommand(
                context=_call_context(resolved.command_context, invocation),
                operation=TaskCommandKind.FINISH,
                task_id=_required_string(invocation.arguments, "task_id"),
                expected_task_version=_required_integer(
                    invocation.arguments,
                    "expected_task_version",
                ),
                payload=payload,
                evidence_refs=evidence_refs,
            )
        )

    def _delegate_task(
        self,
        invocation: ToolInvocation,
        resolved: ResolvedCollaborationToolContext,
    ) -> KernelMutationReceipt:
        _require_closed_arguments(
            invocation.arguments,
            allowed={
                "protocol_ref",
                "task_id",
                "recipient_actor_id",
                "instruction",
                "parent_agent_id",
                "workflow_refs",
            },
            required={
                "protocol_ref",
                "task_id",
                "recipient_actor_id",
                "instruction",
                "workflow_refs",
            },
        )
        raw_workflow_refs = invocation.arguments["workflow_refs"]
        if not isinstance(raw_workflow_refs, tuple | list) or any(
            not isinstance(item, str) or not item
            for item in raw_workflow_refs
        ):
            raise ValueError("workflow_refs must be an array of exact identifiers")
        payload: dict[str, JsonValue] = {
            "task_id": _required_string(invocation.arguments, "task_id"),
            "recipient_actor_id": _required_string(
                invocation.arguments,
                "recipient_actor_id",
            ),
            "instruction": _required_string(invocation.arguments, "instruction"),
            "workflow_authority_id": resolved.workflow_authority_id,
            "workflow_authority_epoch": resolved.workflow_authority_epoch,
            "workflow_authority_digest": resolved.workflow_authority_digest,
            "workflow_refs": tuple(sorted(set(raw_workflow_refs))),
        }
        if "parent_agent_id" in invocation.arguments:
            payload["parent_agent_id"] = invocation.arguments["parent_agent_id"]
        return self.applications.protocol.delegate(
            ProtocolApplicationCommand(
                context=_call_context(resolved.command_context, invocation),
                operation=ProtocolCommandKind.DELEGATE,
                protocol_ref=_required_string(invocation.arguments, "protocol_ref"),
                payload=payload,
            )
        )

    def _send_protocol(
        self,
        invocation: ToolInvocation,
        resolved: ResolvedCollaborationToolContext,
    ) -> KernelMutationReceipt:
        _require_closed_arguments(
            invocation.arguments,
            allowed={
                "protocol_ref",
                "recipient_actor_id",
                "message_type",
                "content",
                "task_id",
            },
            required={
                "protocol_ref",
                "recipient_actor_id",
                "message_type",
                "content",
            },
        )
        payload: dict[str, JsonValue] = {
            "recipient_actor_id": _required_string(
                invocation.arguments,
                "recipient_actor_id",
            ),
            "message_type": _required_string(invocation.arguments, "message_type"),
            "content": _required_string(invocation.arguments, "content"),
            "workflow_authority_id": resolved.workflow_authority_id,
            "workflow_authority_epoch": resolved.workflow_authority_epoch,
            "workflow_authority_digest": resolved.workflow_authority_digest,
        }
        if "task_id" in invocation.arguments:
            payload["task_id"] = invocation.arguments["task_id"]
        return self.applications.protocol.send(
            ProtocolApplicationCommand(
                context=_call_context(resolved.command_context, invocation),
                operation=ProtocolCommandKind.SEND,
                protocol_ref=_required_string(invocation.arguments, "protocol_ref"),
                payload=payload,
            )
        )

    def _request_approval(
        self,
        invocation: ToolInvocation,
        resolved: ResolvedCollaborationToolContext,
    ) -> KernelMutationReceipt:
        _require_closed_arguments(
            invocation.arguments,
            allowed={
                "approval_id",
                "requested_action",
                "scope_id",
                "task_id",
                "expires_at",
                "reason",
            },
            required={"approval_id", "requested_action", "scope_id", "expires_at"},
        )
        payload: dict[str, JsonValue] = {
            "requested_action": _required_string(
                invocation.arguments,
                "requested_action",
            ),
            "scope_id": _required_string(invocation.arguments, "scope_id"),
            "expires_at": _required_string(invocation.arguments, "expires_at"),
        }
        for key in ("task_id", "reason"):
            if key in invocation.arguments:
                payload[key] = invocation.arguments[key]
        intent_digest = canonical_sha256_digest(
            {
                "session_id": invocation.session_id,
                "agent_member_id": invocation.agent_member_id,
                "workflow_authority_id": resolved.workflow_authority_id,
                "workflow_authority_epoch": resolved.workflow_authority_epoch,
                "workflow_authority_digest": resolved.workflow_authority_digest,
                "payload": json_compatible(payload),
            }
        )
        return self.applications.approvals.execute(
            ApprovalApplicationCommand(
                context=_call_context(resolved.command_context, invocation),
                operation=ApprovalCommandKind.REQUEST,
                approval_id=_required_string(invocation.arguments, "approval_id"),
                intent_digest=intent_digest,
                payload=payload,
            )
        )


def build_kernel_collaboration_tool_runtimes(
    *,
    applications: CollaborationToolApplications,
    context_resolver: CollaborationToolContextResolver,
) -> tuple[KernelCollaborationToolRuntime, ...]:
    return tuple(
        KernelCollaborationToolRuntime(
            tool_name=tool_name,
            applications=applications,
            context_resolver=context_resolver,
        )
        for tool_name in sorted(set(_SPECS).difference({"capabilities.inspect"}))
    )


def _call_context(
    context: KernelCommandContext,
    invocation: ToolInvocation,
) -> KernelCommandContext:
    identity = _stable_identity(
        "collaboration",
        invocation.session_id,
        invocation.agent_member_id,
        invocation.call_id,
        invocation.tool_name,
        canonical_sha256_digest(json_compatible(invocation.arguments)),
    )
    return replace(
        context,
        command_id=f"command-{identity}",
        idempotency_key=f"tool-call-{identity}",
    )


def _receipt_result(
    invocation: ToolInvocation,
    receipt: KernelMutationReceipt,
) -> ToolResult:
    result = dict(receipt.result)
    if invocation.tool_name in {"task.delegate", "protocol.send"}:
        if result.get("recipient_runtime_executed") is True:
            raise KernelContractError(
                "protocol_enqueue_contract_violated",
                "Protocol application receipt claims synchronous recipient execution.",
            )
        result["recipient_runtime_executed"] = False
        result["runtime_executed"] = False
    if invocation.tool_name != "task.finish":
        if result.get("task_transition_performed") is True:
            raise KernelContractError(
                "task_transition_contract_violated",
                "Only task.finish may report a Task business terminal transition.",
            )
        result["task_transition_performed"] = False
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=True,
        status=f"{invocation.tool_name.replace('.', '_')}_settled",
        summary="Kernel application service settled the exact collaboration command.",
        payload={
            "application_receipt": receipt.to_dict(),
            "result": json_compatible(result),
            "mutation_applied": receipt.mutation_applied,
            "effect_certainty": receipt.effect_certainty.value,
            "fallback_performed": False,
            "retry_performed": False,
        },
        terminal_action=("task.finish" if invocation.tool_name == "task.finish" else None),
    )


def _evidence_ref(value: JsonValue) -> EvidenceRef:
    if not isinstance(value, Mapping):
        raise ValueError("evidence_refs entries must be objects")
    required = {
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
    if set(value) != required:
        raise ValueError("EvidenceRef differs from its closed contract")
    attributes = value["attributes"]
    if not isinstance(attributes, Mapping):
        raise ValueError("EvidenceRef attributes must be an object")
    return EvidenceRef(
        evidence_id=_mapping_string(value, "evidence_id"),
        evidence_kind=EvidenceKind(_mapping_string(value, "evidence_kind")),
        contract_id=_mapping_string(value, "contract_id"),
        owner_component_id=_mapping_string(value, "owner_component_id"),
        project_id=_mapping_string(value, "project_id"),
        session_id=_mapping_string(value, "session_id"),
        task_id=_mapping_string(value, "task_id"),
        subject_ref=_mapping_string(value, "subject_ref"),
        subject_digest=_mapping_string(value, "subject_digest"),
        attributes=attributes,
    )


def _require_closed_arguments(
    arguments: Mapping[str, JsonValue],
    *,
    allowed: set[str],
    required: set[str] | None = None,
) -> None:
    missing = (required or set()).difference(arguments)
    unexpected = set(arguments).difference(allowed)
    if missing or unexpected:
        raise ValueError(
            f"tool arguments are not closed: missing={sorted(missing)}, "
            f"unexpected={sorted(unexpected)}"
        )


def _required_string(arguments: Mapping[str, JsonValue], key: str) -> str:
    value = arguments[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _mapping_string(arguments: Mapping[str, JsonValue], key: str) -> str:
    return _required_string(arguments, key)


def _optional_string(
    arguments: Mapping[str, JsonValue],
    key: str,
    *,
    default: str | None = None,
) -> str | None:
    value = arguments.get(key, default)
    if value is not None and (not isinstance(value, str) or not value):
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _required_integer(arguments: Mapping[str, JsonValue], key: str) -> int:
    value = arguments[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{key} must be a positive integer")
    return value


def _required_object(
    arguments: Mapping[str, JsonValue],
    key: str,
) -> Mapping[str, JsonValue]:
    value = arguments[key]
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be an object")
    return value


def _rejected(
    invocation: ToolInvocation,
    *,
    code: str,
    summary: str,
) -> ToolResult:
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=False,
        status="collaboration_tool_rejected",
        summary=summary,
        payload={
            "effect_certainty": "no_effect",
            "mutation_applied": False,
            "fallback_performed": False,
            "retry_performed": False,
            "reconcile_required": False,
        },
        error_code=code,
    )


def _stable_identity(*parts: object) -> str:
    return canonical_sha256_digest({"parts": [str(part) for part in parts]}).removeprefix(
        "sha256:"
    )[:32]


__all__ = [
    "ApprovalApplicationPort",
    "CollaborationApplicationPort",
    "CollaborationToolApplications",
    "CollaborationToolContextResolver",
    "KernelCollaborationToolRuntime",
    "ProtocolToolApplicationPort",
    "ResolvedCollaborationToolContext",
    "TaskApplicationPort",
    "WorldInspectionApplicationPort",
    "build_kernel_collaboration_tool_runtimes",
    "kernel_collaboration_declared_tool_entries",
    "kernel_collaboration_tool_specs",
]
