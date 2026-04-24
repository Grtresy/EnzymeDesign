from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from openzyme_domain import AgentMemberStatus
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import InboxParticipantKind

from .artifact_tools import register_artifact_tools
from .bio_research_tools import register_bio_research_tools
from .engines import EngineRegistry
from .harness import HarnessDriver
from .harness import HarnessInput
from .harness import HarnessResult
from .harness import HarnessStatus
from .harness import HarnessStep
from .harness import RestoreFocus
from .harness import ResumeEnvelope
from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .harness import run_agent_harness_loop
from .lane_manager import register_lane_tools
from .memory import register_memory_tools
from .protocol_tools import register_protocol_tools
from .protocols import ProtocolService
from .report_drafts import register_report_draft_tools
from .skills import register_skill_tools
from .task_board import register_task_board_tools
from .tool_catalog import ToolDescriptor


def teammate_tool_descriptors(*, role: str) -> tuple[ToolDescriptor, ...]:
    shared = (
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
            description="List current tasks to understand related work in the session.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        ToolDescriptor(
            tool_name="task.update",
            description="Update the assigned task status, details, or assignment.",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "subject": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {"type": "string", "enum": ["todo", "in_progress", "blocked", "completed", "cancelled"]},
                    "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
                    "kind": {"type": "string"},
                    "assigned_ref": {"type": ["string", "null"]},
                    "blocked_by": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["task_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="artifact.list",
            description="List available session artifacts or artifacts scoped to a task/invocation.",
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
            tool_name="artifact.get",
            description=(
                "Read one artifact record. Large linked output fields are summarized by default; "
                "use path/offset/limit from read_hint to page fields such as output_payload.evidence_items. "
                "When path targets a large dict, the result returns pageable keys with child paths to inspect."
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
            tool_name="protocol.thread",
            description="Read one team protocol thread by correlation id.",
            input_schema={
                "type": "object",
                "properties": {"correlation_id": {"type": "string"}},
                "required": ["correlation_id"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="protocol.send",
            description="Send a structured protocol message to another teammate or the harness.",
            input_schema={
                "type": "object",
                "properties": {
                    "correlation_id": {"type": "string"},
                    "recipient": {"type": "string"},
                    "recipient_kind": {"type": "string", "enum": ["agent", "harness", "system", "user"]},
                    "sender": {"type": "string"},
                    "sender_kind": {"type": "string", "enum": ["agent", "harness", "system", "user"]},
                    "message_type": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "required": ["correlation_id", "recipient"],
                "additionalProperties": False,
            },
        ),
        ToolDescriptor(
            tool_name="memory.compact",
            description="Write a compact summary for the teammate working context.",
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
    )
    role_specific: list[ToolDescriptor] = []
    if role == "researcher":
        role_specific.extend(
            (
                ToolDescriptor(
                    tool_name="deep_research.start",
                    description="Start deep research for the currently assigned task.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "task_id": {"type": "string"},
                            "brief": {"type": "string"},
                        },
                        "required": ["task_id", "brief"],
                        "additionalProperties": False,
                    },
                ),
                ToolDescriptor(
                    tool_name="deep_research.resume",
                    description="Resume a deep research invocation after clarification.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "invocation_id": {"type": "string"},
                            "resolution": {"type": "string"},
                        },
                        "required": ["invocation_id", "resolution"],
                        "additionalProperties": False,
                    },
                ),
                ToolDescriptor(
                    tool_name="deep_research.status",
                    description="Read the current status of a deep research invocation.",
                    input_schema={
                        "type": "object",
                        "properties": {"invocation_id": {"type": "string"}},
                        "required": ["invocation_id"],
                        "additionalProperties": False,
                    },
                ),
                ToolDescriptor(
                    tool_name="deep_research.dossier",
                    description="Read the current dossier output for a deep research invocation.",
                    input_schema={
                        "type": "object",
                        "properties": {"invocation_id": {"type": "string"}},
                        "required": ["invocation_id"],
                        "additionalProperties": False,
                    },
                ),
                ToolDescriptor(
                    tool_name="pubmed.search",
                    description="Search PubMed for focused biomedical literature queries.",
                    input_schema={
                        "type": "object",
                        "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                ),
                ToolDescriptor(
                    tool_name="semantic_scholar.search",
                    description="Search Semantic Scholar for papers and citation-backed literature hits.",
                    input_schema={
                        "type": "object",
                        "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                ),
                ToolDescriptor(
                    tool_name="uniprot.lookup",
                    description="Look up one UniProt accession and return normalized protein metadata.",
                    input_schema={
                        "type": "object",
                        "properties": {"accession": {"type": "string"}},
                        "required": ["accession"],
                        "additionalProperties": False,
                    },
                ),
                ToolDescriptor(
                    tool_name="uniprot.download_fasta",
                    description="Download a protein FASTA sequence from UniProt and persist it as a workspace artifact.",
                    input_schema={
                        "type": "object",
                        "properties": {"accession": {"type": "string"}},
                        "required": ["accession"],
                        "additionalProperties": False,
                    },
                ),
                ToolDescriptor(
                    tool_name="rcsb_pdb.search",
                    description="Search RCSB PDB for matching protein structures.",
                    input_schema={
                        "type": "object",
                        "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                ),
                ToolDescriptor(
                    tool_name="rcsb_pdb.download_structure",
                    description="Download a structure file from RCSB PDB and persist it as a workspace artifact.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "pdb_id": {"type": "string"},
                            "format": {"type": "string", "enum": ["pdb", "cif"]},
                        },
                        "required": ["pdb_id"],
                        "additionalProperties": False,
                    },
                ),
                ToolDescriptor(
                    tool_name="interpro.query",
                    description="Query InterPro annotations for a UniProt accession.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "accession": {"type": "string"},
                            "limit": {"type": "integer"},
                        },
                        "required": ["accession"],
                        "additionalProperties": False,
                    },
                ),
            )
        )
    if role == "executor":
        role_specific.extend(
            (
                ToolDescriptor(
                    tool_name="lane.create",
                    description="Create an isolated execution lane for the assigned task when needed.",
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
                    description="Bind the assigned task to a lane.",
                    input_schema={
                        "type": "object",
                        "properties": {"task_id": {"type": "string"}, "lane_id": {"type": "string"}},
                        "required": ["task_id", "lane_id"],
                        "additionalProperties": False,
                    },
                ),
                ToolDescriptor(
                    tool_name="lane.list",
                    description="List execution lanes in the session.",
                    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                ),
                ToolDescriptor(
                    tool_name="execution.start",
                    description="Start execution for the assigned task.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "task_id": {"type": "string"},
                            "handoff": {"type": "object"},
                        },
                        "required": ["task_id", "handoff"],
                        "additionalProperties": False,
                    },
                ),
                ToolDescriptor(
                    tool_name="execution.resume",
                    description="Resume an execution invocation after approval.",
                    input_schema={
                        "type": "object",
                        "properties": {"invocation_id": {"type": "string"}, "resolution": {"type": "string"}},
                        "required": ["invocation_id"],
                        "additionalProperties": False,
                    },
                ),
            )
        )
    if role == "reporter":
        role_specific.extend(
            (
                ToolDescriptor(
                    tool_name="report_draft.get",
                    description="Read the current report draft for the assigned task.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "draft_id": {"type": "string"},
                            "task_id": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                ),
                ToolDescriptor(
                    tool_name="report_draft.update",
                    description="Create or update the report draft for the assigned task.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "task_id": {"type": "string"},
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "markdown": {"type": "string"},
                            "status": {"type": "string", "enum": ["draft", "in_review", "ready", "published", "failed"]},
                            "owner_agent_id": {"type": "string"},
                        },
                        "required": ["task_id"],
                        "additionalProperties": False,
                    },
                ),
                ToolDescriptor(
                    tool_name="report.publish",
                    description="Publish the current report draft as a final report.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "draft_id": {"type": "string"},
                            "task_id": {"type": "string"},
                            "report_id": {"type": "string"},
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "stage_summary": {"type": "string"},
                            "status": {"type": "string", "enum": ["ready", "published", "failed"]},
                        },
                        "additionalProperties": False,
                    },
                ),
            )
        )
    return (*shared, *tuple(role_specific))


def build_teammate_registry(
    *,
    engine_registry: EngineRegistry | None = None,
    bio_research_service: Any | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    register_task_board_tools(registry)
    register_lane_tools(registry)
    register_memory_tools(registry)
    register_skill_tools(registry)
    if engine_registry is not None:
        for engine in engine_registry.list_engines():
            engine.register_tools(registry)
    register_bio_research_tools(registry, service=bio_research_service)
    register_artifact_tools(registry)
    register_protocol_tools(registry)
    register_report_draft_tools(registry)
    return registry


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
class TeammateConversationDriver(HarnessDriver):
    model_factory: Any
    role: str
    agent_id: str
    correlation_id: str
    task_id: str
    instructions: str
    max_parallel_tool_calls: int = 3
    _messages: list[Any] = field(default_factory=list)
    _initialized: bool = False

    def _system_prompt(self, context: SessionRuntimeContext) -> str:
        restore = context.restore_context
        assert restore is not None
        artifact_titles = ", ".join(artifact.title for artifact in restore.artifacts[:8]) or "none"
        draft_titles = ", ".join(draft.title for draft in restore.report_drafts[:8]) or "none"
        protocol_bits = ", ".join(thread["correlation_id"] for thread in restore.protocol_threads[:8]) or "none"
        report_titles = ", ".join(report.title for report in restore.reports[:8]) or "none"
        return "\n".join(
            [
                f"You are teammate agent {self.agent_id}.",
                f"Role: {self.role}. You are part of the internal OpenZyme agent team.",
                "You are not user-facing. Do not speak to the user directly.",
                "Work on your assigned task using the shared session workspace and your role-scoped tools.",
                "Prefer tools over narration. Complete or advance the assigned task, then send a structured protocol update if useful.",
                "You may read any session artifact through artifact tools. Stay focused on your assigned task and lane.",
                "Never request more than 3 tool calls in one response.",
                f"Assigned task: {self.task_id}",
                f"Correlation thread: {self.correlation_id}",
                f"Instructions: {self.instructions}",
                f"Session objective: {context.snapshot.session.objective}",
                f"Focused task: {restore.focused_task_id or 'none'}",
                f"Focused lane: {restore.focused_lane_id or 'none'}",
                "Artifact catalog: " + artifact_titles,
                "Report draft catalog: " + draft_titles,
                "Report catalog: " + report_titles,
                "Known protocol threads: " + protocol_bits,
                "Ready tasks: " + (", ".join(task.task_id for task in restore.ready_tasks) or "none"),
            ]
        )

    def _seed_messages(self, context: SessionRuntimeContext, harness_input: HarnessInput) -> list[Any]:
        del harness_input
        try:
            from langchain_core.messages import HumanMessage
        except ImportError:
            HumanMessage = None  # type: ignore[assignment]
        payload_lines = [f"Task {self.task_id}: {self.instructions}"]
        if context.restore_context is not None:
            for thread in context.restore_context.protocol_threads:
                if thread.get("correlation_id") == self.correlation_id:
                    payload_lines.append(f"Protocol thread: {json.dumps(thread, sort_keys=True)}")
                    break
        content = "\n".join(payload_lines)
        if HumanMessage is None:
            return [{"role": "user", "content": content}]
        return [HumanMessage(content=content)]

    def _allowed_tools(self) -> tuple[ToolDescriptor, ...]:
        return teammate_tool_descriptors(role=self.role)

    def plan(
        self,
        context: SessionRuntimeContext,
        harness_input: HarnessInput,
        tool_results: tuple[ToolResult, ...],
    ) -> HarnessStep:
        if harness_input.resume is not None and not tool_results and self.role == "executor":
            waiting = [
                invocation
                for invocation in context.snapshot.active_invocations
                if invocation.status is EngineInvocationStatus.WAITING_APPROVAL
                and invocation.engine_name == "execution"
                and invocation.approval_id == harness_input.resume.approval_id
                and invocation.task_id == self.task_id
            ]
            if waiting:
                invocation = waiting[0]
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
                    )
                )
        if harness_input.resume is not None and tool_results:
            if len(tool_results) == 1 and tool_results[0].tool_name == "execution.resume":
                if tool_results[0].ok:
                    return HarnessStep(assistant_message="Approval resolved. Execution resumed under the executor teammate.")
                return HarnessStep(assistant_message="Approval resolved, but execution did not resume successfully.")
        if not self._initialized:
            self._messages = self._seed_messages(context, harness_input)
            self._initialized = True
        elif tool_results:
            self._messages.extend(_tool_messages(tool_results))
        invoker = self.model_factory.create_tool_calling_invoker(purpose=f"v3_teammate_loop:{self.role}")
        tools = [descriptor.to_openai_tool() for descriptor in self._allowed_tools()]
        response = invoker.invoke_with_tools(
            system_prompt=self._system_prompt(context),
            messages=list(self._messages),
            tools=tools,
        )
        self._messages.append(response)
        tool_calls = _extract_tool_calls(response)
        if tool_calls:
            invocations: list[ToolInvocation] = []
            for index, tool_call in enumerate(tool_calls[: self.max_parallel_tool_calls]):
                args = dict(tool_call.get("args") or {})
                if "task_id" not in args and tool_call["name"].startswith(("deep_research.", "execution.", "report_draft.", "report.")):
                    args["task_id"] = self.task_id
                invocations.append(
                    ToolInvocation(
                        call_id=str(tool_call.get("id") or f"call_{index + 1}"),
                        tool_name=str(tool_call["name"]),
                        arguments=args,
                        task_id=str(args.get("task_id") or self.task_id),
                        lane_id=None if "lane_id" not in args else str(args["lane_id"]),
                    )
                )
            return HarnessStep(tool_invocations=tuple(invocations))
        assistant_message = _stringify_content(
            getattr(response, "content", None) if not isinstance(response, dict) else response.get("content")
        ) or f"{self.agent_id} completed delegated work."
        return HarnessStep(assistant_message=assistant_message)


def run_teammate_loop(
    parent_context: SessionRuntimeContext,
    *,
    agent_id: str,
    role: str,
    task_id: str,
    lane_id: str | None,
    correlation_id: str,
    instructions: str,
    resume: ResumeEnvelope | None = None,
) -> HarnessResult:
    if parent_context.model_factory is None:
        raise ValueError("teammate loop requires model_factory")
    registry = build_teammate_registry(
        engine_registry=parent_context.engine_registry,
        bio_research_service=parent_context.bio_research_service,
    )
    driver = TeammateConversationDriver(
        model_factory=parent_context.model_factory,
        role=role,
        agent_id=agent_id,
        correlation_id=correlation_id,
        task_id=task_id,
        instructions=instructions,
    )
    return run_agent_harness_loop(
        parent_context.repositories,
        HarnessInput(
            session_id=parent_context.snapshot.session.session_id,
            resume=resume,
            sender=agent_id,
            sender_kind=InboxParticipantKind.AGENT,
            restore_focus=RestoreFocus(task_id=task_id, lane_id=lane_id),
            persist_conversation=False,
            skip_resume_resolution=resume is not None,
        ),
        driver=driver,
        tool_registry=registry,
        engine_registry=parent_context.engine_registry,
        event_sink=parent_context.event_sink,
        model_factory=parent_context.model_factory,
        bio_research_service=parent_context.bio_research_service,
    )


def finalize_teammate_result(
    context: SessionRuntimeContext,
    *,
    agent_id: str,
    task_id: str,
    correlation_id: str,
    result: HarnessResult,
) -> tuple[str, AgentMemberStatus]:
    protocol = ProtocolService(context.repositories, event_emitter=lambda event_type, payload: context.emit(event_type, payload))
    if result.status is HarnessStatus.WAITING_APPROVAL:
        message = result.outputs[-1] if result.outputs else f"{agent_id} is waiting for approval."
        protocol.reply(
            session_id=context.snapshot.session.session_id,
            sender=agent_id,
            sender_kind=InboxParticipantKind.AGENT,
            recipient="harness",
            recipient_kind=InboxParticipantKind.HARNESS,
            message_type="status_update",
            correlation_id=correlation_id,
            payload_ref=protocol.persist_payload(
                session_id=context.snapshot.session.session_id,
                document_kind="protocol_payload",
                payload={"task_id": task_id, "status": "waiting_approval", "summary": message},
            ),
        )
        return message, AgentMemberStatus.BLOCKED
    message = result.outputs[-1] if result.outputs else f"{agent_id} completed delegated work."
    protocol.reply(
        session_id=context.snapshot.session.session_id,
        sender=agent_id,
        sender_kind=InboxParticipantKind.AGENT,
        recipient="harness",
        recipient_kind=InboxParticipantKind.HARNESS,
        message_type="delegation_result",
        correlation_id=correlation_id,
        payload_ref=protocol.persist_payload(
            session_id=context.snapshot.session.session_id,
            document_kind="protocol_payload",
            payload={
                "task_id": task_id,
                "status": "completed" if result.status is HarnessStatus.COMPLETED else result.status.value,
                "summary": message,
                "outputs": list(result.outputs),
            },
        ),
    )
    return message, AgentMemberStatus.COMPLETED if result.status is HarnessStatus.COMPLETED else AgentMemberStatus.ACTIVE


__all__ = [
    "TeammateConversationDriver",
    "build_teammate_registry",
    "finalize_teammate_result",
    "run_teammate_loop",
    "teammate_tool_descriptors",
]
