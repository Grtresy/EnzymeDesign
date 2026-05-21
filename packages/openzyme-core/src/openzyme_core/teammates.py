from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from openzyme_domain import AgentMemberStatus
from openzyme_domain import InboxParticipantKind
from openzyme_domain import ResearchSummaryStatus

from .artifact_tools import register_artifact_tools
from .bio_research_tools import register_bio_research_tools
from .bio_research_tools import register_web_research_tools
from .docs import register_docs_tools
from .engines import EngineRegistry
from .harness import HarnessDriver
from .harness import HarnessInput
from .harness import HarnessResult
from .harness import HarnessStatus
from .harness import HarnessStep
from .harness import LlmTraceStep
from .harness import LlmTraceToolCall
from .harness import RestoreFocus
from .harness import ResumeEnvelope
from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .harness import run_agent_harness_loop
from .lane_manager import register_lane_tools
from .llm_driver import _sanitize_public_args
from .memory import register_memory_tools
from .protocol_tools import register_protocol_tools
from .protocols import ProtocolService
from .report_drafts import register_report_draft_tools
from .task_board import register_task_board_tools
from .tool_catalog import ToolDescriptor


def _web_tool_enabled(adapter: object | None) -> bool:
    return (
        adapter is not None
        and callable(getattr(adapter, "web_search", None))
        and callable(getattr(adapter, "fetch_url", None))
    )


def teammate_tool_descriptors(
    *, role: str, research_adapter: object | None = None
) -> tuple[ToolDescriptor, ...]:
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
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
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
                    "status": {
                        "type": "string",
                        "enum": [
                            "todo",
                            "in_progress",
                            "blocked",
                            "completed",
                            "failed",
                            "cancelled",
                        ],
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "normal", "high", "urgent"],
                    },
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
                    "recipient_kind": {
                        "type": "string",
                        "enum": ["agent", "harness", "system", "user"],
                    },
                    "sender": {"type": "string"},
                    "sender_kind": {
                        "type": "string",
                        "enum": ["agent", "harness", "system", "user"],
                    },
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
                    "scope_kind": {
                        "type": "string",
                        "enum": ["session", "lane", "task"],
                    },
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
        web_tools: tuple[ToolDescriptor, ...] = ()
        if _web_tool_enabled(research_adapter):
            web_tools = (
                ToolDescriptor(
                    tool_name="web.search",
                    description="Search the web for a query and return normalized evidence sources.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "max_results": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 20,
                            },
                            "topic": {"type": "string"},
                            "include_raw_content": {"type": "boolean"},
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                ),
                ToolDescriptor(
                    tool_name="web.fetch",
                    description=(
                        "Fetch and extract readable content from one web page URL. "
                        "This does not persist structure artifacts; for RCSB structure pages use rcsb_pdb.download_structure."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "query": {"type": ["string", "null"]},
                            "extract_depth": {
                                "type": "string",
                                "enum": ["basic", "advanced"],
                            },
                            "format": {"type": "string", "enum": ["markdown", "text"]},
                            "include_images": {"type": "boolean"},
                        },
                        "required": ["url"],
                        "additionalProperties": False,
                    },
                ),
            )
        role_specific.extend(
            (
                *web_tools,
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
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {"type": "integer"},
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                ),
                ToolDescriptor(
                    tool_name="semantic_scholar.search",
                    description="Search Semantic Scholar for papers and citation-backed literature hits.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {"type": "integer"},
                        },
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
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {"type": "integer"},
                        },
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
                    description="List execution lanes in the session.",
                    input_schema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                ),
                ToolDescriptor(
                    tool_name="docs.search",
                    description="Search the controlled V3 execution pipeline documentation registry.",
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
                    description="Read one controlled V3 execution pipeline document by doc_id or registered path.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "doc_id": {"type": "string"},
                            "path": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                ),
                ToolDescriptor(
                    tool_name="execution.pipeline.start",
                    description=(
                        "Submit Python pipeline code for the assigned task to the controlled execution sandbox. "
                        "This runs the pipeline; dry-run previews are not exposed to teammate execution tasks."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "task_id": {"type": "string"},
                            "code": {"type": "string"},
                            "inputs": {"type": "object"},
                        },
                        "required": ["task_id", "code"],
                        "additionalProperties": False,
                    },
                ),
                ToolDescriptor(
                    tool_name="execution.pipeline.status",
                    description="Read the current status of an execution pipeline invocation.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "invocation_id": {"type": "string"},
                        },
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
                            "status": {
                                "type": "string",
                                "enum": [
                                    "draft",
                                    "in_review",
                                    "ready",
                                    "published",
                                    "failed",
                                ],
                            },
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
                            "status": {
                                "type": "string",
                                "enum": ["ready", "published", "failed"],
                            },
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
    research_adapter: Any | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    register_task_board_tools(registry)
    register_lane_tools(registry)
    register_memory_tools(registry)
    register_docs_tools(registry)
    if engine_registry is not None:
        for engine in engine_registry.list_engines():
            engine.register_tools(registry)
    register_web_research_tools(registry, adapter=research_adapter)
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


def _execution_resume_summary(tool_results: tuple[ToolResult, ...]) -> str | None:
    if len(tool_results) != 1:
        return None
    result = tool_results[0]
    if result.tool_name != "execution.pipeline.start" or not result.ok:
        return None
    try:
        payload = json.loads(result.content)
    except json.JSONDecodeError:
        return result.summary or result.content or None
    run = payload.get("run")
    if isinstance(run, dict):
        summary = run.get("summary")
        if isinstance(summary, str) and summary.strip():
            return summary.strip()
    parsed_result = payload.get("parsed_result")
    if isinstance(parsed_result, dict):
        summary = parsed_result.get("result_summary")
        if isinstance(summary, str) and summary.strip():
            return summary.strip()
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, list) and artifacts:
        return f"Execution completed with {len(artifacts)} artifact(s)."
    return result.summary or result.content or None


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
class TeammateConversationDriver(HarnessDriver):
    model_factory: Any
    role: str
    agent_id: str
    correlation_id: str
    task_id: str
    instructions: str
    max_parallel_tool_calls: int = 3
    research_adapter: Any | None = None
    _messages: list[Any] = field(default_factory=list)
    _initialized: bool = False
    _call_index: int = 0

    def _system_prompt(self, context: SessionRuntimeContext) -> str:
        restore = context.restore_context
        assert restore is not None
        artifact_bits = (
            ", ".join(
                f"{artifact.artifact_id} kind={artifact.kind.value} title={artifact.title or 'untitled'}"
                for artifact in restore.artifacts[:8]
            )
            or "none"
        )
        draft_titles = (
            ", ".join(draft.title for draft in restore.report_drafts[:8]) or "none"
        )
        protocol_bits = (
            ", ".join(
                thread["correlation_id"] for thread in restore.protocol_threads[:8]
            )
            or "none"
        )
        report_titles = (
            ", ".join(report.title for report in restore.reports[:8]) or "none"
        )
        return "\n".join(
            [
                f"You are teammate agent {self.agent_id}.",
                f"Role: {self.role}. You are part of the internal OpenZyme agent team.",
                "You are not user-facing. Do not speak to the user directly.",
                "Work on your assigned task using the shared session workspace and your role-scoped tools.",
                "Prefer tools over narration. Complete or advance the assigned task, then send a structured protocol update if useful.",
                "You may read any session artifact through artifact tools. Stay focused on your assigned task and lane.",
                "Never request more than 3 tool calls in one response.",
                "After every tool call, read ok, status, summary, error_code, hint, and details first. If ok is false, do not assume the requested action completed.",
                "Researcher contract: for open-ended literature/evidence gathering, start with deep_research.start for this assigned task. Use direct web/provider tools only for deterministic follow-up lookup, fetch, or downloads.",
                "Researcher contract: when the assigned objective requires execution against a real structure, use RCSB/UniProt tools to persist a workspace artifact such as rcsb_pdb.download_structure; fetching a web page is not a structure artifact.",
                "Executor contract: when the assigned task asks for fpocket and Artifact catalog contains a structure artifact id, submit execution.pipeline.start with Python code that reads that artifact via artifacts.get('<artifact_id>') and calls hpc.fpocket(structure_artifact_id=structure['artifact_id']). Include that artifact id in inputs.artifact_ids. Do not use dry_run for assigned execution work unless the user explicitly asked only for a plan preview; dry_run does not run HPC and does not satisfy execution or reporting gates.",
                f"Assigned task: {self.task_id}",
                f"Correlation thread: {self.correlation_id}",
                f"Instructions: {self.instructions}",
                f"Session objective: {context.snapshot.session.objective}",
                f"Focused task: {restore.focused_task_id or 'none'}",
                f"Focused lane: {restore.focused_lane_id or 'none'}",
                "Artifact catalog: " + artifact_bits,
                "Report draft catalog: " + draft_titles,
                "Report catalog: " + report_titles,
                "Known protocol threads: " + protocol_bits,
                "Ready tasks: "
                + (", ".join(task.task_id for task in restore.ready_tasks) or "none"),
            ]
        )

    def _seed_messages(
        self, context: SessionRuntimeContext, harness_input: HarnessInput
    ) -> list[Any]:
        del harness_input
        try:
            from langchain_core.messages import HumanMessage
        except ImportError:
            HumanMessage = None  # type: ignore[assignment]
        payload_lines = [f"Task {self.task_id}: {self.instructions}"]
        if context.restore_context is not None:
            for thread in context.restore_context.protocol_threads:
                if thread.get("correlation_id") == self.correlation_id:
                    payload_lines.append(
                        f"Protocol thread: {json.dumps(thread, sort_keys=True)}"
                    )
                    break
        content = "\n".join(payload_lines)
        if HumanMessage is None:
            return [{"role": "user", "content": content}]
        return [HumanMessage(content=content)]

    def _allowed_tools(
        self, context: SessionRuntimeContext
    ) -> tuple[ToolDescriptor, ...]:
        descriptors = teammate_tool_descriptors(
            role=self.role, research_adapter=self.research_adapter
        )
        if self.role != "researcher":
            return descriptors
        task = context.repositories.tasks.get(self.task_id)
        task_text = "" if task is None else f"{task.subject}\n{task.description}"
        session_text = context.snapshot.session.objective
        open_ended_needles = (
            "research",
            "evidence",
            "literature",
            "paper",
            "papers",
            "web",
            "identify",
            "search",
        )
        combined = f"{task_text}\n{self.instructions}\n{session_text}".lower()
        requires_deep_research_first = any(
            needle in combined for needle in open_ended_needles
        )
        if not requires_deep_research_first:
            return descriptors
        has_deep_research_invocation = any(
            invocation.engine_name == "deep_research"
            for invocation in context.repositories.invocations.list_by_task(
                context.snapshot.session.session_id, self.task_id
            )
        )
        if has_deep_research_invocation:
            return descriptors
        return tuple(
            descriptor
            for descriptor in descriptors
            if not descriptor.tool_name.startswith(
                (
                    "web.",
                    "pubmed.",
                    "semantic_scholar.",
                    "uniprot.",
                    "rcsb_pdb.",
                    "interpro.",
                )
            )
        )

    def _initial_prompt_projection(
        self, context: SessionRuntimeContext, seed_messages: list[Any]
    ) -> dict[str, Any]:
        restore = context.restore_context
        return {
            "identity": self.agent_id,
            "role": self.role,
            "task_id": self.task_id,
            "lane_id": None if restore is None else restore.focused_lane_id,
            "correlation_id": self.correlation_id,
            "instructions": self.instructions,
            "seed_message": "\n".join(
                _stringify_content(
                    message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
                )
                for message in seed_messages
            ).strip(),
        }

    def _trace_step(
        self,
        *,
        response_text: str,
        tool_invocations: tuple[ToolInvocation, ...] = (),
        initial_prompt: dict[str, Any] | None = None,
    ) -> LlmTraceStep:
        self._call_index += 1
        return LlmTraceStep(
            actor_ref=self.agent_id,
            actor_kind="teammate",
            display_name=self.agent_id.removeprefix("agent:") or self.agent_id,
            role=self.role,
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
            initial_prompt=initial_prompt,
        )

    def plan(
        self,
        context: SessionRuntimeContext,
        harness_input: HarnessInput,
        tool_results: tuple[ToolResult, ...],
    ) -> HarnessStep:
        initial_prompt = None
        if not self._initialized:
            self._messages = self._seed_messages(context, harness_input)
            initial_prompt = self._initial_prompt_projection(context, self._messages)
            self._initialized = True
        if tool_results:
            self._messages.extend(_tool_messages(tool_results))
        invoker = self.model_factory.create_tool_calling_invoker(
            purpose=f"v3_teammate_loop:{self.role}"
        )
        tools = [
            descriptor.to_openai_tool()
            for descriptor in self._allowed_tools(context)
        ]
        response = invoker.invoke_with_tools(
            system_prompt=self._system_prompt(context),
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
            invocations: list[ToolInvocation] = []
            for index, tool_call in enumerate(
                tool_calls[: self.max_parallel_tool_calls]
            ):
                args = dict(tool_call.get("args") or {})
                if "task_id" not in args and tool_call["name"].startswith(
                    ("deep_research.", "execution.pipeline.", "report_draft.", "report.")
                ):
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
            tool_invocations = tuple(invocations)
            return HarnessStep(
                tool_invocations=tool_invocations,
                llm_trace=self._trace_step(
                    response_text=response_text,
                    tool_invocations=tool_invocations,
                    initial_prompt=initial_prompt,
                ),
            )
        assistant_message = (
            response_text
            or (
                _execution_resume_summary(tool_results)
                if harness_input.resume is not None
                else None
            )
            or f"{self.agent_id} completed delegated work."
        )
        return HarnessStep(
            assistant_message=assistant_message,
            llm_trace=self._trace_step(
                response_text=assistant_message,
                initial_prompt=initial_prompt,
            ),
        )


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
    max_steps: int = 8,
) -> HarnessResult:
    if parent_context.model_factory is None:
        raise ValueError("teammate loop requires model_factory")
    registry = build_teammate_registry(
        engine_registry=parent_context.engine_registry,
        bio_research_service=parent_context.bio_research_service,
        research_adapter=parent_context.research_adapter,
    )
    driver = TeammateConversationDriver(
        model_factory=parent_context.model_factory,
        role=role,
        agent_id=agent_id,
        correlation_id=correlation_id,
        task_id=task_id,
        instructions=instructions,
        research_adapter=parent_context.research_adapter,
    )
    return run_agent_harness_loop(
        parent_context.repositories,
        HarnessInput(
            session_id=parent_context.snapshot.session.session_id,
            resume=resume,
            max_steps=max_steps,
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
        research_adapter=parent_context.research_adapter,
        signal_notifier=parent_context.signal_notifier,
    )


def finalize_teammate_result(
    context: SessionRuntimeContext,
    *,
    agent_id: str,
    task_id: str,
    correlation_id: str,
    result: HarnessResult,
) -> tuple[str, AgentMemberStatus]:
    protocol = ProtocolService(
        context.repositories,
        event_emitter=lambda event_type, payload: context.emit(event_type, payload),
        signal_notifier=context.signal_notifier,
    )
    if result.status is HarnessStatus.WAITING_APPROVAL:
        message = (
            result.outputs[-1]
            if result.outputs
            else f"{agent_id} is waiting for approval."
        )
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
                payload={
                    "task_id": task_id,
                    "status": "waiting_approval",
                    "summary": message,
                },
            ),
        )
        return message, AgentMemberStatus.BLOCKED
    recovered_completion = _recover_completion_from_workspace(
        context,
        task_id=task_id,
        correlation_id=correlation_id,
    )
    if (
        result.status is HarnessStatus.MAX_STEPS_EXCEEDED
        and recovered_completion is None
    ):
        message = (
            result.outputs[-1]
            if result.outputs
            else f"{agent_id} exceeded the delegated work step budget."
        )
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
                    "status": result.status.value,
                    "summary": message,
                    "outputs": list(result.outputs),
                },
            ),
        )
        return message, AgentMemberStatus.FAILED
    message = recovered_completion or (
        result.outputs[-1]
        if result.outputs
        else f"{agent_id} completed delegated work."
    )
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
                "status": "completed"
                if result.status
                in {HarnessStatus.COMPLETED, HarnessStatus.MAX_STEPS_EXCEEDED}
                and recovered_completion
                else result.status.value,
                "summary": message,
                "outputs": list(result.outputs),
            },
        ),
    )
    if result.status is HarnessStatus.COMPLETED or recovered_completion is not None:
        return message, AgentMemberStatus.IDLE
    return message, AgentMemberStatus.FAILED


def _recover_completion_from_workspace(
    context: SessionRuntimeContext,
    *,
    task_id: str,
    correlation_id: str,
) -> str | None:
    thread = ProtocolService(context.repositories).build_thread(
        context.snapshot.session.session_id, correlation_id
    )
    for message in reversed(thread.responses):
        if message.message_type not in {
            "research_completion",
            "delegation_result",
            "background_completion",
        }:
            continue
        if message.payload_ref is None:
            continue
        document = context.repositories.engine_documents.get(message.payload_ref)
        if document is None:
            continue
        payload = document.payload
        if str(payload.get("status") or "").lower() in {
            "completed",
            "succeeded",
            "success",
        }:
            return str(
                payload.get("summary")
                or payload.get("canonical_summary")
                or f"{message.sender} completed delegated work."
            )
    for summary in reversed(
        context.repositories.research_summaries.list_by_session(
            context.snapshot.session.session_id
        )
    ):
        if (
            summary.task_id == task_id
            and summary.status is ResearchSummaryStatus.COMPLETED
        ):
            return summary.summary
    return None


__all__ = [
    "TeammateConversationDriver",
    "build_teammate_registry",
    "finalize_teammate_result",
    "run_teammate_loop",
    "teammate_tool_descriptors",
]
