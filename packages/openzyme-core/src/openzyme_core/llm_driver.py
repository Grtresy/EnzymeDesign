from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from openzyme_domain import EngineInvocationStatus

from .engines import EngineRegistry
from .harness import HarnessInput
from .harness import HarnessStep
from .harness import LlmTraceStep
from .harness import LlmTraceToolCall
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


_REDACTED = "[redacted]"
_SENSITIVE_KEY_FRAGMENTS = (
    "secret",
    "token",
    "password",
    "credential",
    "private_key",
    "api_key",
)
_PRIVATE_KEY_FRAGMENTS = (
    "storage_uri",
    "source_storage_uri",
    "intermediate_storage_uri",
    "local_path",
    "remote_path",
    "host_path",
    "runner_config",
    "ssh",
    "config",
    "pipeline_code",
    "source_code",
    "code",
)


def _sanitize_public_args(value: Any, *, key: str = "") -> Any:
    key_lower = key.lower()
    if any(fragment in key_lower for fragment in _SENSITIVE_KEY_FRAGMENTS):
        return _REDACTED
    if any(fragment in key_lower for fragment in _PRIVATE_KEY_FRAGMENTS):
        return _REDACTED
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize_public_args(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_public_args(item) for item in value[:20]]
    if isinstance(value, str):
        if value.startswith(("artifact://", "storage://", "s3://", "file://")):
            return _REDACTED
        if value.startswith(("/home/", "/tmp/", "/var/", "/mnt/", "/data/", "~")):
            return _REDACTED
        if len(value) > 1200:
            return value[:1200] + "... [truncated]"
    return value


def _resume_result_summary(tool_results: tuple[ToolResult, ...]) -> str | None:
    del tool_results
    return None


def _build_system_prompt(context: SessionRuntimeContext) -> str:
    restore = context.restore_context
    assert restore is not None
    terminal_tasks = [
        task
        for task in restore.tasks
        if task.status.value in {"completed", "failed", "blocked"}
        and task.assigned_ref
        and task.assigned_ref.startswith("agent:")
    ]
    terminal_task_bits = [
        (
            f"{task.status.value} task_id={task.task_id} kind={task.kind} "
            f"assigned_agent={task.assigned_ref}"
        )
        for task in terminal_tasks[:8]
    ]
    protocol_thread_bits: list[str] = []
    for thread in restore.protocol_threads[:8]:
        responses = list(thread.get("responses") or [])
        latest_type = "none"
        if responses:
            latest = responses[-1]
            if isinstance(latest, dict):
                latest_type = str(latest.get("message_type") or "unknown")
        protocol_thread_bits.append(
            "correlation_id={correlation_id} status={status} "
            "response_count={response_count} latest_response_type={latest_type}".format(
                correlation_id=thread.get("correlation_id"),
                status=thread.get("status"),
                response_count=len(responses),
                latest_type=latest_type,
            )
        )
    sections = [
        "You are the top-level OpenZyme master agent.",
        "You talk to the user, understand goals, create and update tasks, and delegate concrete work to internal teammate agents.",
        "The conversation is only user <-> master. Teammate agents are internal workers; do not expose raw teammate outputs as chat transcript entries.",
        teammate_roster_prompt_line(),
        f"If the user asks which teammates are available, answer only with {', '.join(TEAMMATE_ROLE_NAMES)} plus their role-level responsibilities.",
        "Do not describe provider tools or capability engines such as fpocket, AutoDock Vina, AlphaFold, PubMed, UniProt, or RCSB PDB as teammates.",
        "Use tools to create, inspect, update, and delegate tasks. Do not directly start capability engines.",
        "Prefer a small number of tool calls. Never request more than 3 tool calls in one response.",
        "If the user asks for new research, execution, or reporting work and no suitable task exists yet, create a task first.",
        "For research, execution, and reporting tasks, prefer task.delegate after task.create or task.update.",
        "If task.delegate returns wakeup_queued, delegation has been queued but not completed; teammate execution requires an explicit scheduler/runtime drain.",
        "If a later explicit drain or protocol thread shows max_steps_exceeded, failure, or an unclear summary, inspect protocol.thread for that correlation and use protocol.send with message_type=diagnostic_request to queue a focused diagnostic question for the same teammate.",
        "When a delegated task is completed or failed, inspect protocol.thread(correlation_id) for the relevant protocol thread if the restore summary is not enough, then report the task result to the user in your own words.",
        "Diagnostic protocol payloads should include question, instructions, task_id, failed_summary, and expected_response. Protocol sends only deliver messages and queue wakeups; runtime execution is a separate scheduler action.",
        "After every tool call, read ok, status, summary, error_code, hint, and details first. If ok is false, do not assume the requested action completed.",
        "When no tool is needed, reply with a concise assistant message for the user.",
        f"Session objective: {context.snapshot.session.objective}",
        f"Focused task: {restore.focused_task_id or 'none'}",
        f"Focused lane: {restore.focused_lane_id or 'none'}",
        "Ready tasks: "
        + (", ".join(task.task_id for task in restore.ready_tasks) or "none"),
        "Completed/failed/blocked delegated tasks: "
        + ("; ".join(terminal_task_bits) or "none"),
        "Protocol threads available via protocol.thread: "
        + ("; ".join(protocol_thread_bits) or "none"),
        "Pending approvals: "
        + (
            ", ".join(approval.approval_id for approval in restore.pending_approvals)
            or "none"
        ),
        "Active invocations: "
        + (
            ", ".join(inv.invocation_id for inv in restore.active_invocations) or "none"
        ),
    ]
    if restore.session_memory.compaction is not None:
        sections.append(
            f"Session compaction: {restore.session_memory.compaction.summary}"
        )
    elif restore.session_memory.continuity is not None:
        sections.append(
            f"Session continuity: {restore.session_memory.continuity.summary}"
        )
    if restore.lane_memory and restore.lane_memory.compaction is not None:
        sections.append(f"Lane compaction: {restore.lane_memory.compaction.summary}")
    elif restore.lane_memory and restore.lane_memory.continuity is not None:
        sections.append(f"Lane continuity: {restore.lane_memory.continuity.summary}")
    if restore.task_memory and restore.task_memory.compaction is not None:
        sections.append(f"Task compaction: {restore.task_memory.compaction.summary}")
    return "\n".join(sections)


def _build_seed_messages(
    context: SessionRuntimeContext, harness_input: HarnessInput
) -> list[Any]:
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
        content = result.to_tool_message_content()
        if ToolMessage is None:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": result.call_id,
                    "content": content,
                    "name": result.tool_name,
                }
            )
        else:
            messages.append(
                ToolMessage(
                    content=content, tool_call_id=result.call_id, name=result.tool_name
                )
            )
    return messages


@dataclass(slots=True)
class LlmConversationDriver:
    model_factory: Any
    engine_registry: EngineRegistry | None = None
    max_parallel_tool_calls: int = 3
    _messages: list[Any] = field(default_factory=list)
    _initialized: bool = False
    _call_index: int = 0

    def _tool_catalog(self) -> tuple[ToolDescriptor, ...]:
        return top_level_tool_descriptors(self.engine_registry)

    def _descriptor_by_name(self) -> dict[str, ToolDescriptor]:
        return {descriptor.tool_name: descriptor for descriptor in self._tool_catalog()}

    def _invocation_refs(
        self, tool_name: str, args: dict[str, Any]
    ) -> tuple[str | None, str | None]:
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

    def _validate_tool_arguments(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> str | None:
        descriptor = self._descriptor_by_name().get(tool_name)
        if descriptor is None:
            return f"Tool {tool_name} is not available in the current harness."
        required = tuple(descriptor.input_schema.get("required") or ())
        missing = [
            field_name
            for field_name in required
            if field_name not in arguments or arguments[field_name] in (None, "")
        ]
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

    def _resume_waiting_invocation(
        self, context: SessionRuntimeContext, harness_input: HarnessInput
    ) -> HarnessStep | None:
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
        return HarnessStep(
            assistant_message="Approval was resolved. The execution supervisor will continue the pipeline internally.",
            next_focus=RestoreFocus(
                task_id=invocation.task_id, lane_id=invocation.lane_id
            ),
        )

    def _trace_step(
        self,
        *,
        response_text: str,
        tool_invocations: tuple[ToolInvocation, ...] = (),
    ) -> LlmTraceStep:
        self._call_index += 1
        return LlmTraceStep(
            actor_ref="harness",
            actor_kind="master",
            display_name="OpenZyme",
            role="master",
            call_index=self._call_index,
            response_text=response_text,
            tool_calls=tuple(
                LlmTraceToolCall(
                    call_id=invocation.call_id,
                    tool_name=invocation.tool_name,
                    task_id=invocation.task_id,
                    lane_id=invocation.lane_id,
                    args_public=_sanitize_public_args(invocation.arguments),
                )
                for invocation in tool_invocations
            ),
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
        if not self._initialized:
            self._messages = _build_seed_messages(context, harness_input)
            self._initialized = True
        if tool_results:
            self._messages.extend(_tool_messages(tool_results))

        invoker = self.model_factory.create_tool_calling_invoker(
            purpose="v3_harness_loop"
        )
        tools = [descriptor.to_openai_tool() for descriptor in self._tool_catalog()]
        response = invoker.invoke_with_tools(
            system_prompt=_build_system_prompt(context),
            messages=list(self._messages),
            tools=tools,
        )
        self._messages.append(response)
        response_text = _stringify_content(
            getattr(response, "content", None)
            if not isinstance(response, dict)
            else response.get("content")
        )
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
                    return HarnessStep(
                        assistant_message=validation_error,
                        llm_trace=self._trace_step(response_text=response_text),
                    )
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
            tool_invocations = tuple(invocations)
            return HarnessStep(
                tool_invocations=tool_invocations,
                llm_trace=self._trace_step(
                    response_text=response_text, tool_invocations=tool_invocations
                ),
            )
        assistant_message = response_text
        if not assistant_message:
            assistant_message = (
                _resume_result_summary(tool_results)
                if harness_input.resume is not None
                else None
            )
        if not assistant_message:
            assistant_message = "No user-facing response was generated."
        return HarnessStep(
            assistant_message=assistant_message,
            llm_trace=self._trace_step(response_text=assistant_message),
        )


__all__ = ["LlmConversationDriver"]
