from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import ToolSpec
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import WorkspacePortError
from openzyme_contracts.identity import JsonValue

from .workspace_lifecycle import ExecutorHpcWorkspaceError


HPC_PLUGIN_ID = "openzyme.hpc"


@dataclass(frozen=True, slots=True)
class HpcWorkspaceToolContext:
    call_id: str
    session_id: str
    agent_member_id: str
    task_id: str | None
    lane_id: str | None
    route_id: str | None
    affordance_snapshot_digest: str | None


class HpcWorkspaceToolApplication(Protocol):
    """Narrow Plugin API; every method must revalidate owner and route identity."""

    def request(
        self,
        context: HpcWorkspaceToolContext,
        arguments: Mapping[str, JsonValue],
    ) -> Mapping[str, JsonValue]: ...

    def inspect(
        self,
        context: HpcWorkspaceToolContext,
        arguments: Mapping[str, JsonValue],
    ) -> Mapping[str, JsonValue]: ...

    def verify(
        self,
        context: HpcWorkspaceToolContext,
        arguments: Mapping[str, JsonValue],
    ) -> Mapping[str, JsonValue]: ...

    def sync_source(
        self,
        context: HpcWorkspaceToolContext,
        arguments: Mapping[str, JsonValue],
    ) -> Mapping[str, JsonValue]: ...

    def fs_read(
        self,
        context: HpcWorkspaceToolContext,
        arguments: Mapping[str, JsonValue],
    ) -> Mapping[str, JsonValue]: ...

    def fs_list(
        self,
        context: HpcWorkspaceToolContext,
        arguments: Mapping[str, JsonValue],
    ) -> Mapping[str, JsonValue]: ...

    def fs_mutate(
        self,
        context: HpcWorkspaceToolContext,
        arguments: Mapping[str, JsonValue],
    ) -> Mapping[str, JsonValue]: ...

    def exec(
        self,
        context: HpcWorkspaceToolContext,
        arguments: Mapping[str, JsonValue],
    ) -> Mapping[str, JsonValue]: ...


_WORKSPACE_ID = {"type": "string", "minLength": 1, "maxLength": 256}
_RELATIVE_PATH = {
    "type": "string",
    "minLength": 1,
    "maxLength": 2048,
    "description": "Canonical remote-workspace-root-relative path; no absolute path, parent traversal or glob.",
}
_BASE_OUTPUT = {
    "type": "object",
    "required": [
        "workspace_id",
        "fallback_performed",
        "publication_created",
        "scientific_evidence_created",
        "task_finished",
    ],
}


def _workspace_schema(properties: dict[str, object], required: list[str]) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["workspace_id", *required],
        "properties": {"workspace_id": _WORKSPACE_ID, **properties},
    }


HPC_WORKSPACE_TOOL_SPECS = (
    ToolSpec(
        tool_name="hpc.workspace.request",
        description=(
            "Request one exact owner-scoped remote HPC workspace generation. This "
            "does not submit a scheduler job, publish files, create evidence or finish a Task."
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "target_id",
                "remote_workspace_generation",
                "idempotency_key",
                "absolute_deadline",
            ],
            "properties": {
                "target_id": {"type": "string", "minLength": 1},
                "remote_workspace_generation": {"type": "integer", "minimum": 1},
                "idempotency_key": {"type": "string", "minLength": 1},
                "absolute_deadline": {"type": "string", "minLength": 1},
            },
        },
        output_schema=_BASE_OUTPUT,
        required_authorities=("hpc.workspace.provision",),
    ),
    ToolSpec(
        tool_name="hpc.workspace.inspect",
        description="Inspect the redacted owner view of one opaque HPC workspace.",
        input_schema=_workspace_schema({}, []),
        output_schema=_BASE_OUTPUT,
        required_authorities=("hpc.workspace.inspect",),
    ),
    ToolSpec(
        tool_name="hpc.workspace.verify",
        description="Verify exact remote root, generation, target qualification and clone identity.",
        input_schema=_workspace_schema({}, []),
        output_schema=_BASE_OUTPUT,
        required_authorities=("hpc.workspace.inspect",),
    ),
    ToolSpec(
        tool_name="hpc.workspace.sync_source",
        description=(
            "Resolve one exact private checkpoint or immutable publication for an owner "
            "workspace. The receipt does not itself mutate, publish or adopt files."
        ),
        input_schema={
            **_workspace_schema(
                {
                    "checkpoint_id": {"type": "string", "minLength": 1},
                    "publication_id": {"type": "string", "minLength": 1},
                },
                [],
            ),
            "oneOf": [
                {"required": ["checkpoint_id"], "not": {"required": ["publication_id"]}},
                {"required": ["publication_id"], "not": {"required": ["checkpoint_id"]}},
            ],
        },
        output_schema=_BASE_OUTPUT,
        required_authorities=("hpc.workspace.transfer.write",),
    ),
    ToolSpec(
        tool_name="hpc.workspace.fs.read",
        description="Read one bounded root-relative file from an exact owner HPC workspace.",
        input_schema=_workspace_schema(
            {
                "path": _RELATIVE_PATH,
                "max_bytes": {"type": "integer", "minimum": 1, "maximum": 1048576},
            },
            ["path"],
        ),
        output_schema=_BASE_OUTPUT,
        required_authorities=("hpc.workspace.fs.read",),
    ),
    ToolSpec(
        tool_name="hpc.workspace.fs.list",
        description="List one bounded root-relative directory in an exact owner HPC workspace.",
        input_schema=_workspace_schema({"path": _RELATIVE_PATH}, ["path"]),
        output_schema=_BASE_OUTPUT,
        required_authorities=("hpc.workspace.fs.read",),
    ),
    ToolSpec(
        tool_name="hpc.workspace.fs.mutate",
        description=(
            "Apply one structured write, mkdir, move or remove operation under the exact "
            "owner root. Success is private mutation only, never publication or Task evidence."
        ),
        input_schema=_workspace_schema(
            {
                "operation": {
                    "type": "string",
                    "enum": ["write", "mkdir", "move", "remove"],
                },
                "path": _RELATIVE_PATH,
                "destination": _RELATIVE_PATH,
                "content": {"type": "string", "maxLength": 1048576},
                "expected_content_digest": {
                    "type": "string",
                    "pattern": "^sha256:[0-9a-f]{64}$",
                },
                "recursive": {"type": "boolean"},
                "idempotency_key": {"type": "string", "minLength": 1},
            },
            ["operation", "path", "idempotency_key"],
        ),
        output_schema=_BASE_OUTPUT,
        required_authorities=("hpc.workspace.fs.write",),
    ),
    ToolSpec(
        tool_name="hpc.workspace.exec",
        description=(
            "Execute one bounded foreground argv in an exact owner HPC workspace. Scheduler "
            "commands are excluded; response loss is reconciled without redispatch."
        ),
        input_schema=_workspace_schema(
            {
                "argv": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 256,
                    "items": {"type": "string", "minLength": 1, "maxLength": 4096},
                },
                "cwd": _RELATIVE_PATH,
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
                "stdin": {"type": "string", "maxLength": 1048576},
                "idempotency_key": {"type": "string", "minLength": 1},
            },
            ["argv", "cwd", "timeout_seconds", "idempotency_key"],
        ),
        output_schema=_BASE_OUTPUT,
        required_authorities=("hpc.workspace.process.exec",),
    ),
)


_SPEC_BY_NAME = {spec.tool_name: spec for spec in HPC_WORKSPACE_TOOL_SPECS}
_METHOD_BY_NAME = {
    "hpc.workspace.request": "request",
    "hpc.workspace.inspect": "inspect",
    "hpc.workspace.verify": "verify",
    "hpc.workspace.sync_source": "sync_source",
    "hpc.workspace.fs.read": "fs_read",
    "hpc.workspace.fs.list": "fs_list",
    "hpc.workspace.fs.mutate": "fs_mutate",
    "hpc.workspace.exec": "exec",
}


@dataclass(slots=True)
class HpcWorkspaceToolRuntime:
    tool_name: str
    application: HpcWorkspaceToolApplication
    owner_plugin_id: str = HPC_PLUGIN_ID

    def __post_init__(self) -> None:
        if self.tool_name not in _SPEC_BY_NAME:
            raise ValueError("unknown HPC workspace tool runtime")

    @property
    def runtime_id(self) -> str:
        return f"openzyme.hpc.{self.tool_name.removeprefix('hpc.').replace('.', '-')}@1"

    @property
    def contract(self) -> ToolSpec:
        return _SPEC_BY_NAME[self.tool_name]

    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        if invocation.tool_name != self.tool_name:
            return self._error(
                invocation,
                "hpc_workspace_tool_contract_mismatch",
                "HPC runtime received a different tool contract.",
            )
        context = HpcWorkspaceToolContext(
            call_id=invocation.call_id,
            session_id=invocation.session_id,
            agent_member_id=invocation.agent_member_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            route_id=invocation.route_id,
            affordance_snapshot_digest=invocation.affordance_snapshot_digest,
        )
        try:
            method = getattr(self.application, _METHOD_BY_NAME[self.tool_name])
            result = dict(method(context, invocation.arguments))
        except WorkspacePortError as exc:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                status=exc.effect_certainty.value,
                summary=str(exc),
                payload={
                    "mutation_applied": exc.mutation_applied,
                    "effect_certainty": exc.effect_certainty.value,
                    "diagnostic_id": exc.diagnostic_id,
                    "fallback_performed": False,
                    "publication_created": False,
                    "scientific_evidence_created": False,
                    "task_finished": False,
                },
                error_code=exc.error_code,
            )
        except (ExecutorHpcWorkspaceError, KeyError, TypeError, ValueError) as exc:
            return self._error(
                invocation,
                getattr(exc, "error_code", "hpc_workspace_request_invalid"),
                str(exc),
            )
        payload: dict[str, JsonValue] = {
            **result,
            "fallback_performed": False,
            "publication_created": False,
            "scientific_evidence_created": False,
            "task_finished": False,
        }
        if result.get("effect_certainty") == ExternalEffectCertainty.DISPATCH_IN_DOUBT.value:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                status=ExternalEffectCertainty.DISPATCH_IN_DOUBT.value,
                summary=(
                    "Remote workspace dispatch outcome is uncertain; observe or reconcile "
                    "the same occurrence without redispatch."
                ),
                payload=payload,
                error_code="remote_workspace_dispatch_in_doubt",
            )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            status="accepted",
            summary="HPC workspace operation accepted with exact owner and route identity.",
            payload=payload,
        )

    @staticmethod
    def _error(
        invocation: ToolInvocation,
        error_code: str,
        summary: str,
    ) -> ToolResult:
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=False,
            status="rejected",
            summary=summary,
            payload={
                "mutation_applied": False,
                "fallback_performed": False,
                "publication_created": False,
                "scientific_evidence_created": False,
                "task_finished": False,
            },
            error_code=error_code,
        )


def build_hpc_workspace_tool_runtimes(
    application: HpcWorkspaceToolApplication,
) -> tuple[HpcWorkspaceToolRuntime, ...]:
    return tuple(
        HpcWorkspaceToolRuntime(tool_name=spec.tool_name, application=application)
        for spec in HPC_WORKSPACE_TOOL_SPECS
    )


__all__ = [
    "HPC_PLUGIN_ID",
    "HPC_WORKSPACE_TOOL_SPECS",
    "HpcWorkspaceToolApplication",
    "HpcWorkspaceToolContext",
    "HpcWorkspaceToolRuntime",
    "build_hpc_workspace_tool_runtimes",
]
