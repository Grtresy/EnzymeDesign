from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from typing import Any
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    task_id: str | None = None
    lane_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    tool_name: str
    ok: bool
    content: str
    task_id: str | None = None
    lane_id: str | None = None
    status: str | None = None
    summary: str | None = None
    error_code: str | None = None
    hint: str | None = None
    details: dict[str, Any] | None = None

    def envelope(self) -> dict[str, Any]:
        details = dict(self.details or {})
        envelope: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status or ("ok" if self.ok else "failed"),
            "summary": self.summary or self.content,
            "error_code": self.error_code,
            "hint": self.hint,
            "details": details,
            "content": self.content,
        }
        try:
            envelope["payload"] = json.loads(self.content)
        except (TypeError, json.JSONDecodeError):
            pass
        return envelope

    def to_tool_message_content(self) -> str:
        return json.dumps(self.envelope(), sort_keys=True)


ToolHandler = Callable[[Any, ToolInvocation], ToolResult | str]


@dataclass(frozen=True, slots=True)
class AgentStepContext:
    step_id: str
    session_id: str
    agent_id: str
    actor_kind: str
    role: str
    call_index: int
    task_id: str | None = None
    lane_id: str | None = None
    correlation_id: str | None = None
    signal_id: str | None = None
    wakeup_reason: str | None = None
    restore_context_digest: str | None = None
    tool_catalog_digest: str | None = None
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "actor_kind": self.actor_kind,
            "role": self.role,
            "call_index": self.call_index,
            "task_id": self.task_id,
            "lane_id": self.lane_id,
            "correlation_id": self.correlation_id,
            "signal_id": self.signal_id,
            "wakeup_reason": self.wakeup_reason,
            "restore_context_digest": self.restore_context_digest,
            "tool_catalog_digest": self.tool_catalog_digest,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class ToolSpec:
    tool_name: str
    description: str
    input_schema: dict[str, Any]

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.tool_name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


class ToolRuntime(Protocol):
    def spec(self, step_context: AgentStepContext) -> ToolSpec: ...

    def is_visible(self, step_context: AgentStepContext) -> bool: ...

    def dispatch(
        self,
        step_context: AgentStepContext,
        invocation: ToolInvocation,
        runtime_context: Any,
    ) -> ToolResult: ...


@dataclass(frozen=True, slots=True)
class LegacyFunctionToolRuntime:
    tool_name: str
    handler: ToolHandler
    tool_spec: ToolSpec

    def spec(self, step_context: AgentStepContext) -> ToolSpec:
        del step_context
        return self.tool_spec

    def is_visible(self, step_context: AgentStepContext) -> bool:
        del step_context
        return True

    def dispatch(
        self,
        step_context: AgentStepContext,
        invocation: ToolInvocation,
        runtime_context: Any,
    ) -> ToolResult:
        del step_context
        try:
            result = self.handler(runtime_context, invocation)
        except (KeyError, TypeError, ValueError) as exc:
            message = f"Tool {invocation.tool_name} failed: {str(exc).strip() or exc.__class__.__name__}"
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=message,
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
                status="invalid_tool_arguments",
                summary=message,
                error_code="invalid_tool_arguments",
                hint="Fix the tool arguments or referenced task/lane/session state before retrying.",
                details={"exception_type": exc.__class__.__name__},
            )
        if isinstance(result, ToolResult):
            return result
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=str(result),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            status="ok",
            summary=str(result),
        )


@dataclass(slots=True)
class ToolRouter:
    runtimes: dict[str, ToolRuntime]
    dispatch_context: Any

    def registered_tool_names(self) -> tuple[str, ...]:
        return tuple(sorted(self.runtimes))

    def model_visible_specs(
        self, step_context: AgentStepContext
    ) -> tuple[ToolSpec, ...]:
        return tuple(
            runtime.spec(step_context)
            for runtime in self.runtimes.values()
            if runtime.is_visible(step_context)
        )

    def dispatch(
        self, step_context: AgentStepContext, invocation: ToolInvocation
    ) -> ToolResult:
        runtime = self.runtimes.get(invocation.tool_name)
        if runtime is None:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=f"unknown tool: {invocation.tool_name}",
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
                status="unknown_tool",
                summary=f"Tool {invocation.tool_name!r} is not registered.",
                error_code="unknown_tool",
                hint="Use one of the tools exposed in the current V3 tool catalog.",
            )
        return runtime.dispatch(step_context, invocation, self.dispatch_context)


class ToolRegistryProtocol:
    def register(self, tool_name: str, handler: ToolHandler) -> None: ...


__all__ = [
    "AgentStepContext",
    "LegacyFunctionToolRuntime",
    "ToolHandler",
    "ToolInvocation",
    "ToolRegistryProtocol",
    "ToolRouter",
    "ToolRuntime",
    "ToolSpec",
    "ToolResult",
]
