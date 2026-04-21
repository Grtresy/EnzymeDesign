from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import json

from .engines import EngineRegistry
from .harness import HarnessInput
from .harness import HarnessStep
from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolResult
from .tool_catalog import ToolDescriptor
from .tool_catalog import top_level_tool_descriptors


def _extract_tool_calls(message: Any) -> list[dict[str, Any]]:
    if hasattr(message, "tool_calls") and getattr(message, "tool_calls") is not None:
        return list(getattr(message, "tool_calls"))
    if isinstance(message, dict):
        return list(message.get("tool_calls") or [])
    return []


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()
    if content is None:
        return ""
    return str(content)


def _build_system_prompt(context: SessionRuntimeContext) -> str:
    restore = context.restore_context
    assert restore is not None
    sections = [
        "You are the top-level OpenZyme harness planner.",
        "Use tools to create and update tasks, bind lanes, start capability engines, and compact memory when useful.",
        "Prefer a small number of tool calls. Never request more than 3 tool calls in one response.",
        "When no tool is needed, reply with a concise assistant message for the user.",
        f"Session objective: {context.snapshot.session.objective}",
        f"Focused task: {restore.focused_task_id or 'none'}",
        f"Focused lane: {restore.focused_lane_id or 'none'}",
        "Ready tasks: " + (", ".join(task.task_id for task in restore.ready_tasks) or "none"),
        "Pending approvals: " + (", ".join(approval.approval_id for approval in restore.pending_approvals) or "none"),
        "Active invocations: " + (", ".join(inv.invocation_id for inv in restore.active_invocations) or "none"),
    ]
    if restore.session_memory.compaction is not None:
        sections.append(f"Session compaction: {restore.session_memory.compaction.summary}")
    elif restore.session_memory.continuity is not None:
        sections.append(f"Session continuity: {restore.session_memory.continuity.summary}")
    if restore.lane_memory and restore.lane_memory.compaction is not None:
        sections.append(f"Lane compaction: {restore.lane_memory.compaction.summary}")
    elif restore.lane_memory and restore.lane_memory.continuity is not None:
        sections.append(f"Lane continuity: {restore.lane_memory.continuity.summary}")
    if restore.task_memory and restore.task_memory.compaction is not None:
        sections.append(f"Task compaction: {restore.task_memory.compaction.summary}")
    return "\n".join(sections)


def _build_seed_messages(context: SessionRuntimeContext, harness_input: HarnessInput) -> list[Any]:
    restore = context.restore_context
    assert restore is not None
    try:
        from langchain_core.messages import AIMessage
        from langchain_core.messages import HumanMessage
    except ImportError:
        AIMessage = None  # type: ignore[assignment]
        HumanMessage = None  # type: ignore[assignment]

    messages: list[Any] = []
    for entry in restore.recent_conversation:
        if HumanMessage is None or AIMessage is None:
            messages.append({"role": entry.role, "content": entry.content})
            continue
        if entry.role == "assistant":
            messages.append(AIMessage(content=entry.content))
        else:
            messages.append(HumanMessage(content=entry.content))
    if harness_input.message:
        if HumanMessage is None:
            messages.append({"role": "user", "content": harness_input.message})
        else:
            messages.append(HumanMessage(content=harness_input.message))
    return messages


def _tool_messages(tool_results: tuple[ToolResult, ...]) -> list[Any]:
    try:
        from langchain_core.messages import ToolMessage
    except ImportError:
        ToolMessage = None  # type: ignore[assignment]
    messages: list[Any] = []
    for result in tool_results:
        if ToolMessage is None:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": result.call_id,
                    "content": result.content,
                    "name": result.tool_name,
                }
            )
        else:
            messages.append(ToolMessage(content=result.content, tool_call_id=result.call_id, name=result.tool_name))
    return messages


@dataclass(slots=True)
class LlmConversationDriver:
    model_factory: Any
    engine_registry: EngineRegistry | None = None
    max_parallel_tool_calls: int = 3
    _messages: list[Any] = field(default_factory=list)
    _initialized: bool = False

    def _tool_catalog(self) -> tuple[ToolDescriptor, ...]:
        return top_level_tool_descriptors(self.engine_registry)

    def _invocation_refs(self, tool_name: str, args: dict[str, Any]) -> tuple[str | None, str | None]:
        if tool_name in {"task.create", "lane.create"}:
            return None, None
        task_id = None if "task_id" not in args else str(args["task_id"])
        lane_id = None if "lane_id" not in args else str(args["lane_id"])
        return task_id, lane_id

    def plan(
        self,
        context: SessionRuntimeContext,
        harness_input: HarnessInput,
        tool_results: tuple[ToolResult, ...],
    ) -> HarnessStep:
        if not self._initialized:
            self._messages = _build_seed_messages(context, harness_input)
            self._initialized = True
        elif tool_results:
            self._messages.extend(_tool_messages(tool_results))

        invoker = self.model_factory.create_tool_calling_invoker(purpose="v3_harness_loop")
        tools = [descriptor.to_openai_tool() for descriptor in self._tool_catalog()]
        response = invoker.invoke_with_tools(
            system_prompt=_build_system_prompt(context),
            messages=list(self._messages),
            tools=tools,
        )
        self._messages.append(response)
        tool_calls = _extract_tool_calls(response)
        if tool_calls:
            selected = tool_calls[: self.max_parallel_tool_calls]
            invocations: list[ToolInvocation] = []
            for index, tool_call in enumerate(selected):
                tool_name = str(tool_call["name"])
                arguments = dict(tool_call.get("args") or {})
                task_id, lane_id = self._invocation_refs(tool_name, arguments)
                invocations.append(
                    ToolInvocation(
                        call_id=str(tool_call.get("id") or f"call_{index + 1}"),
                        tool_name=tool_name,
                        arguments=arguments,
                        task_id=task_id,
                        lane_id=lane_id,
                    )
                )
            return HarnessStep(tool_invocations=tuple(invocations))
        assistant_message = _stringify_content(getattr(response, "content", None) if not isinstance(response, dict) else response.get("content"))
        if not assistant_message:
            assistant_message = "No user-facing response was generated."
        return HarnessStep(assistant_message=assistant_message)


__all__ = ["LlmConversationDriver"]
