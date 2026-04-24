from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any
import json
from uuid import uuid4

from openzyme_domain import TaskStatus
from openzyme_domain import EngineInvocationStatus

from .engines import EngineRegistry
from .harness import HarnessInput
from .harness import HarnessStep
from .harness import RestoreFocus
from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolResult
from .tool_catalog import ToolDescriptor
from .tool_catalog import top_level_tool_descriptors
from .teammate_roster import TEAMMATE_ROLE_NAMES
from .teammate_roster import teammate_role_for_task_kind
from .teammate_roster import teammate_roster_prompt_line


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
        "You are the top-level OpenZyme master agent.",
        "You talk to the user, understand goals, create and update tasks, and delegate concrete work to internal teammate agents.",
        teammate_roster_prompt_line(),
        f"If the user asks which teammates are available, answer only with {', '.join(TEAMMATE_ROLE_NAMES)} plus their role-level responsibilities.",
        "Do not describe provider tools or capability engines such as fpocket, AutoDock Vina, AlphaFold, PubMed, UniProt, or RCSB PDB as teammates.",
        "Use tools to create, inspect, update, and delegate tasks. Do not directly start capability engines.",
        "Prefer a small number of tool calls. Never request more than 3 tool calls in one response.",
        "If the user asks for new research, execution, or reporting work and no suitable task exists yet, create a task first.",
        "For research, execution, and reporting tasks, prefer task.delegate after task.create or task.update.",
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
    current_message_already_loaded = (
        bool(harness_input.message)
        and bool(restore.recent_conversation)
        and restore.recent_conversation[-1].role == "user"
        and restore.recent_conversation[-1].content == harness_input.message
    )
    if harness_input.message and not current_message_already_loaded:
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

    def _descriptor_by_name(self) -> dict[str, ToolDescriptor]:
        return {descriptor.tool_name: descriptor for descriptor in self._tool_catalog()}

    def _invocation_refs(self, tool_name: str, args: dict[str, Any]) -> tuple[str | None, str | None]:
        if tool_name in {"task.create", "lane.create"}:
            return None, None
        task_id = None if "task_id" not in args else str(args["task_id"])
        lane_id = None if "lane_id" not in args else str(args["lane_id"])
        return task_id, lane_id

    def _backfill_task_bound_args(self, tool_calls: list[dict[str, Any]]) -> None:
        created_tasks = [
            dict(tool_call.get("args") or {})
            for tool_call in tool_calls
            if str(tool_call.get("name")) == "task.create"
        ]
        created_task = created_tasks[0] if len(created_tasks) == 1 else None
        if created_task is None:
            return
        created_task_id = created_task.get("task_id")
        if not created_task_id:
            created_task_id = f"task_{uuid4().hex[:12]}"
            created_task["task_id"] = created_task_id
            for tool_call in tool_calls:
                if str(tool_call.get("name")) == "task.create":
                    tool_call["args"] = created_task
                    break
        created_subject = str(created_task.get("subject") or "")
        created_description = str(created_task.get("description") or "")
        for tool_call in tool_calls:
            tool_name = str(tool_call.get("name"))
            if tool_name not in {"task.delegate"}:
                continue
            arguments = dict(tool_call.get("args") or {})
            if not arguments.get("task_id") and created_task_id:
                arguments["task_id"] = str(created_task_id)
            if not arguments.get("instructions"):
                arguments["instructions"] = created_description or created_subject
            if not arguments.get("agent_role"):
                created_task_kind = str(created_task.get("kind") or "")
                inferred_role = teammate_role_for_task_kind(created_task_kind)
                if inferred_role is not None:
                    arguments["agent_role"] = inferred_role
            tool_call["args"] = arguments

    def _validate_tool_arguments(self, tool_name: str, arguments: dict[str, Any]) -> str | None:
        descriptor = self._descriptor_by_name().get(tool_name)
        if descriptor is None:
            return f"Tool {tool_name} is not available in the current harness."
        required = tuple(descriptor.input_schema.get("required") or ())
        missing = [field_name for field_name in required if field_name not in arguments or arguments[field_name] in (None, "")]
        if missing:
            if tool_name == "task.delegate" and "task_id" in missing:
                return (
                    "Cannot delegate a task without task_id. "
                    "Create or select a task first, then delegate it."
                )
            if tool_name == "task.delegate" and "agent_role" in missing:
                return (
                    "Cannot delegate a task without agent_role. "
                    f"Choose one of: {', '.join(TEAMMATE_ROLE_NAMES)}."
                )
            return f"Cannot call {tool_name}; missing required fields: {', '.join(missing)}."
        properties = descriptor.input_schema.get("properties") or {}
        for field_name, field_schema in properties.items():
            if field_name not in arguments or not isinstance(field_schema, dict):
                continue
            enum_values = field_schema.get("enum")
            if enum_values is not None and arguments[field_name] not in enum_values:
                return (
                    f"Cannot call {tool_name}; invalid {field_name}: {arguments[field_name]!r}. "
                    f"Choose one of: {', '.join(str(value) for value in enum_values)}."
                )
        return None

    def _resume_waiting_invocation(self, context: SessionRuntimeContext, harness_input: HarnessInput) -> HarnessStep | None:
        if harness_input.resume is None:
            return None
        waiting = [
            invocation
            for invocation in context.snapshot.active_invocations
            if invocation.status is EngineInvocationStatus.WAITING_APPROVAL
            and invocation.engine_name == "execution"
            and invocation.approval_id == harness_input.resume.approval_id
        ]
        if not waiting:
            return None
        invocation = waiting[0]
        task = None if invocation.task_id is None else context.repositories.tasks.get(invocation.task_id)
        agent_id = None if task is None else task.assigned_ref
        if agent_id is not None and agent_id.startswith("agent:"):
            return HarnessStep(
                tool_invocations=(
                    ToolInvocation(
                        call_id=f"call_teammate_resume_{invocation.invocation_id}",
                        tool_name="teammate.resume_execution",
                        arguments={
                            "invocation_id": invocation.invocation_id,
                            "approval_id": harness_input.resume.approval_id,
                            "decision": harness_input.resume.decision.value,
                            "actor_ref": harness_input.resume.actor_ref,
                            "correlation_id": invocation.approval_id or invocation.invocation_id,
                        },
                        task_id=invocation.task_id,
                        lane_id=invocation.lane_id,
                    ),
                ),
                next_focus=RestoreFocus(task_id=invocation.task_id, lane_id=invocation.lane_id),
            )
        return HarnessStep(
            tool_invocations=(
                ToolInvocation(
                    call_id=f"call_resume_{invocation.invocation_id}",
                    tool_name="execution.resume",
                    arguments={
                        "invocation_id": invocation.invocation_id,
                        "resolution": f"Approval {harness_input.resume.decision.value} by {harness_input.resume.actor_ref}.",
                    },
                    task_id=invocation.task_id,
                    lane_id=invocation.lane_id,
                ),
            ),
            next_focus=RestoreFocus(task_id=invocation.task_id, lane_id=invocation.lane_id),
        )

    def _resume_followup_step(
        self,
        context: SessionRuntimeContext,
        tool_results: tuple[ToolResult, ...],
    ) -> HarnessStep | None:
        if len(tool_results) != 1 or tool_results[0].tool_name not in {"execution.resume", "teammate.resume_execution"}:
            return None
        result = tool_results[0]
        task_updates = ()
        if result.task_id is not None:
            task = context.repositories.tasks.get(result.task_id)
            if task is not None:
                next_status = TaskStatus.COMPLETED if result.ok else TaskStatus.BLOCKED
                task_updates = (replace(task, status=next_status),)
        if result.ok:
            return HarnessStep(
                assistant_message="Approval resolved. The delegated execution task resumed under the executor teammate.",
                task_updates=task_updates,
            )
        return HarnessStep(
            assistant_message="Approval resolved, but the delegated execution task did not resume successfully.",
            task_updates=task_updates,
        )

    def plan(
        self,
        context: SessionRuntimeContext,
        harness_input: HarnessInput,
        tool_results: tuple[ToolResult, ...],
    ) -> HarnessStep:
        if harness_input.resume is not None and not tool_results:
            resumed = self._resume_waiting_invocation(context, harness_input)
            if resumed is not None:
                return resumed
        if harness_input.resume is not None and tool_results:
            resume_step = self._resume_followup_step(context, tool_results)
            if resume_step is not None:
                return resume_step
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
            self._backfill_task_bound_args(selected)
            invocations: list[ToolInvocation] = []
            for index, tool_call in enumerate(selected):
                tool_name = str(tool_call["name"])
                arguments = dict(tool_call.get("args") or {})
                validation_error = self._validate_tool_arguments(tool_name, arguments)
                if validation_error is not None:
                    return HarnessStep(assistant_message=validation_error)
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
