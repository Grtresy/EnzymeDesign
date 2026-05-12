from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .engines import EngineRegistry
from .teammate_roster import TEAMMATE_ROLE_NAMES


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
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


def builtin_tool_descriptors() -> tuple[ToolDescriptor, ...]:
    return (
        ToolDescriptor(
            tool_name="task.create",
            description="Create a new task in the current session when the user asks for new work to be tracked.",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "subject": {"type": "string"},
                    "description": {"type": "string"},
                    "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
                    "kind": {"type": "string"},
                    "status": {"type": "string", "enum": ["todo", "in_progress", "blocked", "completed", "failed", "cancelled"]},
                    "assigned_ref": {"type": ["string", "null"]},
                    "blocked_by": {"type": "array", "items": {"type": "string"}},
                    "failure_summary": {"type": ["string", "null"]},
                    "failure_ref": {"type": ["string", "null"]},
                },
                "required": ["subject"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="task.update",
            description="Update an existing task status, wording, priority, or assignment.",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "subject": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {"type": "string", "enum": ["todo", "in_progress", "blocked", "completed", "failed", "cancelled"]},
                    "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
                    "kind": {"type": "string"},
                    "assigned_ref": {"type": ["string", "null"]},
                    "blocked_by": {"type": "array", "items": {"type": "string"}},
                    "failure_summary": {"type": ["string", "null"]},
                    "failure_ref": {"type": ["string", "null"]},
                },
                "required": ["task_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="task.get",
            description="Fetch one task by id before updating or reasoning about it.",
            input_schema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="task.list",
            description="List the current task board to inspect ready, blocked, and in-progress work.",
            input_schema={
                "type": "object",
                "properties": {"lane_id": {"type": "string"}},
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="task.next",
            description="Get the next ready task when selecting what to do next.",
            input_schema={
                "type": "object",
                "properties": {"lane_id": {"type": "string"}},
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="task.delegate",
            description=(
                "Delegate a concrete task to one internal teammate agent by queuing a runtime wakeup. "
                f"Valid teammate roles are {', '.join(TEAMMATE_ROLE_NAMES)}."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "agent_role": {"type": "string", "enum": list(TEAMMATE_ROLE_NAMES)},
                    "agent_id": {"type": "string"},
                    "instructions": {"type": "string"},
                    "correlation_id": {"type": "string"},
                },
                "required": ["task_id", "agent_role"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="protocol.thread",
            description="Inspect one internal team protocol thread by correlation id, including small structured payloads.",
            input_schema={
                "type": "object",
                "properties": {"correlation_id": {"type": "string"}},
                "required": ["correlation_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="protocol.send",
            description=(
                "Send a structured internal team protocol message to a teammate or the harness. "
                "This only persists the message and queues a wakeup signal; it does not run the recipient."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "recipient": {"type": "string"},
                    "recipient_kind": {"type": "string", "enum": ["agent", "harness", "user", "system"]},
                    "sender": {"type": "string"},
                    "sender_kind": {"type": "string", "enum": ["agent", "harness", "user", "system"]},
                    "message_type": {"type": "string"},
                    "correlation_id": {"type": "string"},
                    "task_id": {"type": "string"},
                    "lane_id": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "required": ["recipient", "correlation_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="lane.create",
            description="Create a lane when work needs an isolated execution context.",
            input_schema={
                "type": "object",
                "properties": {
                    "lane_id": {"type": "string"},
                    "name": {"type": "string"},
                    "cwd": {"type": "string"},
                    "branch_name": {"type": "string"},
                },
                "required": ["lane_id", "name", "cwd"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="lane.bind_task",
            description="Bind a task to an existing lane.",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "lane_id": {"type": "string"},
                },
                "required": ["task_id", "lane_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="lane.list",
            description="List lanes and their assigned work.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        ToolDescriptor(
            tool_name="memory.compact",
            description="Write a compact summary for session, lane, or task context.",
            input_schema={
                "type": "object",
                "properties": {
                    "scope_kind": {"type": "string", "enum": ["session", "lane", "task"]},
                    "scope_ref": {"type": "string"},
                    "task_id": {"type": "string"},
                    "lane_id": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="docs.search",
            description="Search the controlled V3 documentation registry for pipeline SDK and sandbox docs.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="docs.read",
            description="Read one document from the controlled V3 documentation registry by doc_id or registered path.",
            input_schema={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "path": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
    )


def top_level_tool_descriptors(engine_registry: EngineRegistry | None = None) -> tuple[ToolDescriptor, ...]:
    del engine_registry
    return builtin_tool_descriptors()


__all__ = ["ToolDescriptor", "builtin_tool_descriptors", "top_level_tool_descriptors"]
