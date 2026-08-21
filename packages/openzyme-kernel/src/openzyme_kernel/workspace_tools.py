from __future__ import annotations

from collections.abc import Mapping
import base64
import binascii
from dataclasses import dataclass
from dataclasses import replace
import json
from typing import Protocol

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import ToolSpec
from openzyme_contracts import WorkspaceExecRequest
from openzyme_contracts import WorkspaceFilesystemMutation
from openzyme_contracts import WorkspaceFilesystemMutationKind
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import WorkspaceObservationKind
from openzyme_contracts import WorkspaceObservationRequest
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import WORKSPACE_STRUCTURED_OPERATION_MAX_BYTES
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts.identity import JsonValue
from openzyme_contracts.identity import json_compatible
from openzyme_extension_spi import KernelCommandContext

from .catalog import DeclaredToolEntry
from .errors import KernelContractError
from .workspace_operations import WorkspaceOperationCoordinationError
from .workspace_operations import WorkspaceOperationCoordinator
from .workspace_operations import WorkspaceOperationOutcome
from .workspace_operations import WorkspaceOperationSettlementState


_MAX_STRUCTURED_BYTES = WORKSPACE_STRUCTURED_OPERATION_MAX_BYTES
_DEFAULT_OUTPUT_BYTES = 65_536
_DEFAULT_TIMEOUT_SECONDS = 120


@dataclass(frozen=True, slots=True)
class ResolvedLocalWorkspaceToolContext:
    binding: WorkspaceRuntimeBinding
    command_context: KernelCommandContext
    process_epoch: int

    def __post_init__(self) -> None:
        if self.binding.workspace_kind is not WorkspaceKind.AGENT_LOCAL:
            raise ValueError("base workspace tools require one local workspace binding")
        if (
            self.command_context.session_id != self.binding.session_id
            or self.command_context.actor_id != self.binding.owner_member_id
            or self.command_context.workspace_generation != self.binding.generation
        ):
            raise ValueError("resolved workspace context identity drifted")
        if self.process_epoch < 1:
            raise ValueError("process_epoch must be positive")


class LocalWorkspaceToolContextResolver(Protocol):
    """Host-side resolver over current canonical member/authority/workspace facts."""

    def resolve(
        self,
        invocation: ToolInvocation,
        *,
        effectful: bool,
    ) -> ResolvedLocalWorkspaceToolContext: ...


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


def kernel_workspace_tool_specs() -> tuple[ToolSpec, ...]:
    path = {
        "type": "string",
        "minLength": 1,
        "maxLength": 4096,
    }
    byte_budget = {
        "type": "integer",
        "minimum": 256,
        "maximum": _MAX_STRUCTURED_BYTES,
    }
    return (
        ToolSpec(
            tool_name="workspace.status",
            description=(
                "观察当前 Agent 唯一 generation-owned 本地 workspace 的 Git/文件状态；"
                "不接受 workspace ID，也不产生 mutation。"
            ),
            input_schema=_object_schema({}),
            required_authorities=("workspace.fs.read",),
        ),
        ToolSpec(
            tool_name="workspace.fs.read",
            description=(
                "从当前 Agent 的本地 workspace 读取一个 root-relative 文件；"
                "返回 bounded、content-bound observation。"
            ),
            input_schema=_object_schema(
                {"path": path, "max_bytes": byte_budget},
                required=("path",),
            ),
            required_authorities=("workspace.fs.read",),
        ),
        ToolSpec(
            tool_name="workspace.fs.list",
            description=(
                "列出当前 Agent 本地 workspace 的一个 root-relative 目录；"
                "不展开 glob，不接受 Host path。"
            ),
            input_schema=_object_schema(
                {"path": path, "max_bytes": byte_budget},
            ),
            required_authorities=("workspace.fs.read",),
        ),
        ToolSpec(
            tool_name="workspace.fs.mutate",
            description=(
                "在当前 Agent 本地 workspace 中执行一个 closed、root-confined、"
                "CAS-aware 文件 mutation。成功不会自动 checkpoint、publish 或完成 Task。"
            ),
            input_schema=_object_schema(
                {
                    "operation": {
                        "type": "string",
                        "enum": [
                            item.value for item in WorkspaceFilesystemMutationKind
                        ],
                    },
                    "path": path,
                    "destination_path": path,
                    "content_base64": {
                        "type": "string",
                        "maxLength": 1_398_104,
                    },
                    "expected_content_digest": {
                        "type": "string",
                        "pattern": "^sha256:[0-9a-f]{64}$",
                    },
                    "recursive": {"type": "boolean"},
                },
                required=("operation", "path"),
            ),
            required_authorities=("workspace.fs.write",),
        ),
        ToolSpec(
            tool_name="workspace.exec",
            description=(
                "在当前 Agent 唯一 generation-owned 本地 workspace 中执行一个 bounded argv；"
                "需要 shell 时必须显式传入 shell argv。本工具不接受 credential、target、"
                "remote locator 或 workspace ID。"
            ),
            input_schema=_object_schema(
                {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 256,
                    },
                    "cwd": path,
                    "timeout_seconds": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 3600,
                    },
                    "max_output_bytes": {
                        "type": "integer",
                        "minimum": 256,
                        "maximum": 4_194_304,
                    },
                    "stdin_base64": {
                        "type": "string",
                        "maxLength": 1_398_104,
                    },
                },
                required=("argv",),
            ),
            required_authorities=("workspace.process.exec",),
        ),
    )


_SPECS = {item.tool_name: item for item in kernel_workspace_tool_specs()}


def kernel_workspace_declared_tool_entries() -> tuple[DeclaredToolEntry, ...]:
    """Return the one canonical declared-catalog entry for each Kernel base tool."""

    return tuple(
        DeclaredToolEntry(
            owner_component_id="openzyme.kernel",
            runtime_id=f"openzyme.kernel.runtime.{spec.tool_name}",
            contract=spec,
            requirements=(),
            requires_workspace=True,
            requires_explicit_route=False,
        )
        for spec in kernel_workspace_tool_specs()
    )


@dataclass(slots=True)
class KernelWorkspaceToolRuntime:
    tool_name: str
    coordinator: WorkspaceOperationCoordinator
    context_resolver: LocalWorkspaceToolContextResolver

    def __post_init__(self) -> None:
        if self.tool_name not in _SPECS:
            raise ValueError("unknown Kernel workspace base tool")

    @property
    def owner_component_id(self) -> str:
        """Identify this runtime as a Kernel contribution, never as a Plugin."""

        return "openzyme.kernel"

    @property
    def runtime_id(self) -> str:
        return f"openzyme.kernel.runtime.{self.tool_name}"

    @property
    def contract(self) -> ToolSpec:
        return _SPECS[self.tool_name]

    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        if invocation.tool_name != self.tool_name:
            return _failure(
                invocation,
                "workspace_tool_contract_mismatch",
                "Tool invocation does not match this runtime contract.",
            )
        if "workspace_id" in invocation.arguments:
            return _failure(
                invocation,
                "workspace_id_forbidden",
                "Local workspace tools resolve the caller's current workspace; workspace_id is forbidden.",
            )
        try:
            if self.tool_name == "workspace.status":
                return self._observe(
                    invocation,
                    operation=WorkspaceObservationKind.STATUS,
                    default_path=".",
                )
            if self.tool_name == "workspace.fs.read":
                return self._observe(
                    invocation,
                    operation=WorkspaceObservationKind.READ,
                    default_path=None,
                )
            if self.tool_name == "workspace.fs.list":
                return self._observe(
                    invocation,
                    operation=WorkspaceObservationKind.LIST,
                    default_path=".",
                )
            if self.tool_name == "workspace.fs.mutate":
                return self._mutate(invocation)
            return self._execute(invocation)
        except (KernelContractError, WorkspaceOperationCoordinationError) as exc:
            return _coordination_failure(invocation, exc)
        except (KeyError, TypeError, ValueError, binascii.Error) as exc:
            return _failure(
                invocation,
                "invalid_tool_arguments",
                str(exc),
            )

    def _observe(
        self,
        invocation: ToolInvocation,
        *,
        operation: WorkspaceObservationKind,
        default_path: str | None,
    ) -> ToolResult:
        allowed = set() if operation is WorkspaceObservationKind.STATUS else {
            "path",
            "max_bytes",
        }
        _require_closed_arguments(invocation.arguments, allowed=allowed)
        context = self.context_resolver.resolve(invocation, effectful=False)
        path = _optional_string(invocation.arguments, "path", default=default_path)
        if path is None:
            raise ValueError("path is required")
        max_bytes = _optional_integer(
            invocation.arguments,
            "max_bytes",
            default=_DEFAULT_OUTPUT_BYTES,
        )
        observation = self.coordinator.observe(
            context=context.command_context,
            request=WorkspaceObservationRequest(
                binding=context.binding,
                operation=operation,
                path=path,
                max_bytes=max_bytes,
            ),
        )
        payload = _decode_result_payload(observation.bounded_payload)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            status=f"workspace_{operation.value}_observed",
            summary="Observed the exact current local workspace without mutation.",
            payload={
                "workspace_generation": observation.generation,
                "workspace_state_version": observation.state_version,
                "observation_digest": observation.result_digest,
                "result": payload,
                "mutation_applied": False,
                "fallback_performed": False,
            },
        )

    def _mutate(self, invocation: ToolInvocation) -> ToolResult:
        _require_closed_arguments(
            invocation.arguments,
            allowed={
                "operation",
                "path",
                "destination_path",
                "content_base64",
                "expected_content_digest",
                "recursive",
            },
            required={"operation", "path"},
        )
        resolved = self.context_resolver.resolve(invocation, effectful=True)
        context, operation_id, idempotency_key = _effect_context(
            resolved.command_context,
            invocation,
        )
        content = _optional_base64(invocation.arguments, "content_base64")
        request = WorkspaceFilesystemMutation(
            operation_id=operation_id,
            binding=resolved.binding,
            operation=WorkspaceFilesystemMutationKind(
                _required_string(invocation.arguments, "operation")
            ),
            path=_required_string(invocation.arguments, "path"),
            destination_path=_optional_string(
                invocation.arguments,
                "destination_path",
            ),
            content=content,
            expected_content_digest=_optional_string(
                invocation.arguments,
                "expected_content_digest",
            ),
            recursive=_optional_boolean(
                invocation.arguments,
                "recursive",
                default=False,
            ),
            idempotency_key=idempotency_key,
            authority_lease_id=context.authority_lease_id,
            authority_generation=context.authority_generation,
            authority_fence=context.authority_fence,
        )
        return _effect_result(
            invocation,
            self.coordinator.mutate_filesystem(
                context=context,
                request=request,
            ),
            success_status="workspace_filesystem_mutation_settled",
            success_summary="Applied the exact private workspace filesystem mutation.",
        )

    def _execute(self, invocation: ToolInvocation) -> ToolResult:
        _require_closed_arguments(
            invocation.arguments,
            allowed={
                "argv",
                "cwd",
                "timeout_seconds",
                "max_output_bytes",
                "stdin_base64",
            },
            required={"argv"},
        )
        raw_argv = invocation.arguments["argv"]
        if not isinstance(raw_argv, tuple) or any(
            not isinstance(item, str) for item in raw_argv
        ):
            raise ValueError("argv must be an array of strings")
        resolved = self.context_resolver.resolve(invocation, effectful=True)
        context, operation_id, idempotency_key = _effect_context(
            resolved.command_context,
            invocation,
        )
        request = WorkspaceExecRequest(
            operation_id=operation_id,
            binding=resolved.binding,
            argv=tuple(raw_argv),
            cwd=_optional_string(invocation.arguments, "cwd", default=".") or ".",
            timeout_seconds=_optional_integer(
                invocation.arguments,
                "timeout_seconds",
                default=_DEFAULT_TIMEOUT_SECONDS,
            ),
            max_output_bytes=_optional_integer(
                invocation.arguments,
                "max_output_bytes",
                default=_DEFAULT_OUTPUT_BYTES,
            ),
            idempotency_key=idempotency_key,
            authority_lease_id=context.authority_lease_id,
            authority_generation=context.authority_generation,
            authority_fence=context.authority_fence,
            process_epoch=resolved.process_epoch,
            stdin=_optional_base64(invocation.arguments, "stdin_base64") or b"",
        )
        result = _effect_result(
            invocation,
            self.coordinator.execute_process(context=context, request=request),
            success_status="workspace_process_settled",
            success_summary="The exact bounded local workspace process settled.",
        )
        if result.ok and isinstance(result.payload, Mapping):
            process = result.payload.get("result")
            if isinstance(process, Mapping):
                returncode = process.get("returncode")
                if isinstance(returncode, int) and returncode != 0:
                    return replace(
                        result,
                        ok=False,
                        status="workspace_process_nonzero_exit",
                        summary=f"Local workspace process exited with code {returncode}.",
                        error_code="workspace_process_nonzero_exit",
                    )
        return result


def build_kernel_workspace_tool_runtimes(
    *,
    coordinator: WorkspaceOperationCoordinator,
    context_resolver: LocalWorkspaceToolContextResolver,
) -> tuple[KernelWorkspaceToolRuntime, ...]:
    return tuple(
        KernelWorkspaceToolRuntime(
            tool_name=tool_name,
            coordinator=coordinator,
            context_resolver=context_resolver,
        )
        for tool_name in sorted(_SPECS)
    )


def _effect_context(
    context: KernelCommandContext,
    invocation: ToolInvocation,
) -> tuple[KernelCommandContext, str, str]:
    seed = canonical_sha256_digest(
        {
            "call_id": invocation.call_id,
            "tool_name": invocation.tool_name,
            "session_id": invocation.session_id,
            "agent_member_id": invocation.agent_member_id,
            "arguments": json_compatible(invocation.arguments),
        }
    ).removeprefix("sha256:")
    operation_id = f"workspace-operation-{seed[:32]}"
    idempotency_key = f"workspace-tool-call-{seed[:32]}"
    return (
        replace(
            context,
            command_id=f"workspace-command-{seed[:32]}",
            idempotency_key=idempotency_key,
        ),
        operation_id,
        idempotency_key,
    )


def _decode_result_payload(value: bytes) -> JsonValue:
    try:
        decoded = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KernelContractError(
            "workspace_adapter_payload_invalid",
            "Workspace Adapter returned a non-JSON public payload.",
        ) from exc
    return decoded


def _effect_result(
    invocation: ToolInvocation,
    outcome: WorkspaceOperationOutcome,
    *,
    success_status: str,
    success_summary: str,
) -> ToolResult:
    result_payload: JsonValue = None
    if outcome.adapter_receipt is not None:
        result_payload = _decode_result_payload(
            outcome.adapter_receipt.result_payload
        )
    payload: dict[str, JsonValue] = {
        "operation": outcome.to_safe_dict(),
        "result": result_payload,
        "checkpoint_performed": False,
        "publication_performed": False,
        "workspace_cleanup_performed": False,
        "task_transition_performed": False,
        "fallback_performed": False,
    }
    if outcome.error_code is not None:
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=False,
            status=(
                "workspace_operation_reconcile_required"
                if outcome.settlement_state
                is WorkspaceOperationSettlementState.RECONCILE_REQUIRED
                else "workspace_operation_rejected"
            ),
            summary=(
                "Workspace effect is uncertain; reconcile the same operation identity."
                if outcome.effect_certainty
                is ExternalEffectCertainty.DISPATCH_IN_DOUBT
                else "Workspace operation was rejected without fallback."
            ),
            payload=payload,
            error_code=outcome.error_code,
            hint=(
                "Observe or reconcile this exact operation; do not retry or change route."
                if outcome.settlement_state
                is WorkspaceOperationSettlementState.RECONCILE_REQUIRED
                else None
            ),
        )
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=True,
        status=success_status,
        summary=success_summary,
        payload=payload,
    )


def _coordination_failure(
    invocation: ToolInvocation,
    error: KernelContractError | WorkspaceOperationCoordinationError,
) -> ToolResult:
    code = error.code
    certainty = getattr(error, "effect_certainty", "no_effect")
    mutation = getattr(error, "mutation_applied", False)
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=False,
        status=(
            "workspace_operation_reconcile_required"
            if certainty in {
                ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                ExternalEffectCertainty.DISPATCH_IN_DOUBT.value,
            }
            else "workspace_operation_rejected"
        ),
        summary=str(error),
        payload={
            "effect_certainty": (
                certainty.value
                if isinstance(certainty, ExternalEffectCertainty)
                else certainty
            ),
            "mutation_applied": mutation,
            "fallback_performed": False,
            "diagnostic_id": getattr(error, "diagnostic_id", None),
        },
        error_code=code,
        hint=(
            "Reconcile the same operation identity; do not issue a replacement."
            if certainty in {
                ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                ExternalEffectCertainty.DISPATCH_IN_DOUBT.value,
            }
            else None
        ),
    )


def _failure(
    invocation: ToolInvocation,
    error_code: str,
    summary: str,
) -> ToolResult:
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=False,
        status="workspace_tool_rejected",
        summary=summary,
        payload={
            "effect_certainty": "no_effect",
            "mutation_applied": False,
            "fallback_performed": False,
        },
        error_code=error_code,
    )


def _require_closed_arguments(
    arguments: Mapping[str, JsonValue],
    *,
    allowed: set[str],
    required: set[str] | None = None,
) -> None:
    keys = set(arguments)
    required_keys = required or set()
    missing = required_keys - keys
    unexpected = keys - allowed
    if missing or unexpected:
        raise ValueError(
            f"tool arguments are not closed: missing={sorted(missing)}, "
            f"unexpected={sorted(unexpected)}"
        )


def _required_string(arguments: Mapping[str, JsonValue], key: str) -> str:
    value = arguments[key]
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _optional_string(
    arguments: Mapping[str, JsonValue],
    key: str,
    *,
    default: str | None = None,
) -> str | None:
    value = arguments.get(key, default)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _optional_integer(
    arguments: Mapping[str, JsonValue],
    key: str,
    *,
    default: int,
) -> int:
    value = arguments.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    return value


def _optional_boolean(
    arguments: Mapping[str, JsonValue],
    key: str,
    *,
    default: bool,
) -> bool:
    value = arguments.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _optional_base64(
    arguments: Mapping[str, JsonValue],
    key: str,
) -> bytes | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a base64 string")
    decoded = base64.b64decode(value, validate=True)
    if len(decoded) > _MAX_STRUCTURED_BYTES:
        raise ValueError(f"{key} exceeds the 1 MiB structured-input limit")
    return decoded


__all__ = [
    "KernelWorkspaceToolRuntime",
    "LocalWorkspaceToolContextResolver",
    "ResolvedLocalWorkspaceToolContext",
    "build_kernel_workspace_tool_runtimes",
    "kernel_workspace_tool_specs",
    "kernel_workspace_declared_tool_entries",
]
