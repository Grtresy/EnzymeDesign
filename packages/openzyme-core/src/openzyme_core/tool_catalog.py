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


def artifact_tool_descriptors() -> tuple[ToolDescriptor, ...]:
    return (
        ToolDescriptor(
            tool_name="artifact.list",
            description=(
                "List safe session artifact records or artifacts scoped to a task/invocation. "
                "Results never include Host storage_uri or local paths."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "invocation_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="artifact.create_text",
            description=(
                "Create a new immutable Python pipeline source artifact in the current session. "
                "The artifact is stored as kind=code, format=python, semantic_type=pipeline_source, "
                "with SHA-256 content_digest and version metadata. Results never include Host paths."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Safe basename ending in .py, for example aox_hmm_pipeline.py.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Complete UTF-8 Python source text for the artifact.",
                    },
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["filename", "content"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="artifact.patch_text",
            description=(
                "Create a new immutable version of a Python pipeline source artifact from complete patched "
                "UTF-8 source text. Requires base_artifact_id and matching base_content_digest for concurrency "
                "control; the old artifact is not overwritten."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "base_artifact_id": {"type": "string"},
                    "base_content_digest": {"type": "string"},
                    "content": {
                        "type": "string",
                        "description": "Complete patched UTF-8 Python source text.",
                    },
                    "filename": {
                        "type": "string",
                        "description": "Optional safe .py basename; defaults to the base artifact filename.",
                    },
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["base_artifact_id", "base_content_digest", "content"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="artifact.diff_text",
            description=(
                "Return a bounded unified diff between two Python pipeline source artifacts or versions. "
                "Results include safe artifact metadata and content digests, never Host paths."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "base_artifact_id": {"type": "string"},
                    "target_artifact_id": {"type": "string"},
                    "context_lines": {"type": "integer", "minimum": 0, "maximum": 20},
                },
                "required": ["base_artifact_id", "target_artifact_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="artifact.get",
            description=(
                "Read one safe artifact catalog record and linked engine metadata by artifact_id. "
                "Large linked output fields are summarized by default; use path/offset/limit from read_hint "
                "to page fields such as output_payload.evidence_items. When path targets a large dict, "
                "the result returns pageable keys with child paths to inspect. Results never include Host paths."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "artifact_id": {"type": "string"},
                    "path": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 0, "maximum": 50},
                    "include_full": {"type": "boolean"},
                },
                "required": ["artifact_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="artifact.preview",
            description="Preview a UTF-8 text artifact by artifact_id without exposing the Host storage path.",
            input_schema={
                "type": "object",
                "properties": {
                    "artifact_id": {"type": "string"},
                    "lines": {"type": "integer", "minimum": 1, "maximum": 200},
                    "limit": {"type": "integer", "minimum": 0, "maximum": 50000},
                },
                "required": ["artifact_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="artifact.read_text",
            description="Read a UTF-8 text artifact by character offset and bounded limit.",
            input_schema={
                "type": "object",
                "properties": {
                    "artifact_id": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 0, "maximum": 50000},
                },
                "required": ["artifact_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="artifact.range",
            description="Read a UTF-8 text artifact by 1-based line range, suitable for logs, PDB, FASTA, JSON, and Markdown.",
            input_schema={
                "type": "object",
                "properties": {
                    "artifact_id": {"type": "string"},
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                },
                "required": ["artifact_id"],
                "additionalProperties": False,
            },
        ),
    )


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
            description=(
                "Inspect one internal team protocol thread by correlation id, including small structured payloads "
                "and latest status, summary, task, and failure observation fields."
            ),
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
        *artifact_tool_descriptors(),
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


__all__ = [
    "ToolDescriptor",
    "artifact_tool_descriptors",
    "builtin_tool_descriptors",
    "top_level_tool_descriptors",
]
