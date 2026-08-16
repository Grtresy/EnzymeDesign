from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from typing import Protocol
from uuid import uuid4

from openzyme_runtime import AgentStepContext
from openzyme_runtime import classify_llm_provider_error
from openzyme_runtime import EngineDescriptor
from openzyme_runtime import EngineDocumentRecord
from openzyme_runtime import ToolGovernance
from openzyme_runtime import ToolInvocation
from openzyme_runtime import ToolRegistryProtocol
from openzyme_runtime import ToolResult
from openzyme_runtime import ToolSideEffect
from openzyme_runtime import ToolSpec
from openzyme_runtime import ToolValidationError
from openzyme_runtime import validate_arguments_against_schema
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import SourceRefKind
from openzyme_domain.control_plane import utc_now_iso

from .deep_research_contracts import EvidenceSynthesisItem
from .deep_research_contracts import ResearchDossier
from .deep_research_contracts import ResearchSourceItem
from .deep_research_contracts import ResearchTurnRecord
from .deep_research_graph import DeepResearchGraphInputs
from .deep_research_graph import resolve_research_graph_settings
from .deep_research_graph import run_deep_research


def _new_document_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


@dataclass(frozen=True, slots=True)
class ResearchEvidenceItem:
    summary: str
    query: str
    confidence_label: str | None
    sources: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "query": self.query,
            "confidence_label": self.confidence_label,
            "sources": [dict(source) for source in self.sources],
        }


@dataclass(frozen=True, slots=True)
class NormalizedResearchDossier:
    status: str
    completion_reason: str
    research_brief: str
    summary: str
    evidence_items: tuple[ResearchEvidenceItem, ...]
    source_refs: tuple[dict[str, Any], ...]
    unresolved_gaps: tuple[str, ...]
    artifacts: tuple[dict[str, Any], ...] = ()
    raw_notes: tuple[str, ...] = ()
    clarification_question: str | None = None
    recent_turns: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "completion_reason": self.completion_reason,
            "research_brief": self.research_brief,
            "summary": self.summary,
            "evidence_items": [item.to_dict() for item in self.evidence_items],
            "source_refs": [dict(source) for source in self.source_refs],
            "unresolved_gaps": list(self.unresolved_gaps),
            "artifacts": [dict(item) for item in self.artifacts],
            "raw_notes": list(self.raw_notes),
            "clarification_question": self.clarification_question,
            "recent_turns": [dict(turn) for turn in self.recent_turns],
        }

    @classmethod
    def from_runner_payload(cls, payload: Any) -> "NormalizedResearchDossier":
        evidence_items: list[ResearchEvidenceItem] = []
        flattened_sources: list[dict[str, Any]] = []
        for item in payload.evidence_items:
            sources = tuple(
                {
                    "title": source.title,
                    "locator": source.locator,
                    "kind": source.kind,
                    "snippet": source.snippet,
                }
                for source in item.sources
            )
            evidence_items.append(
                ResearchEvidenceItem(
                    summary=item.summary,
                    query=item.query,
                    confidence_label=item.confidence_label,
                    sources=sources,
                )
            )
            flattened_sources.extend(dict(source) for source in sources)
        return cls(
            status=payload.status,
            completion_reason=payload.completion_reason,
            research_brief=payload.research_brief,
            summary=payload.summary,
            evidence_items=tuple(evidence_items),
            source_refs=tuple(flattened_sources),
            unresolved_gaps=tuple(payload.unresolved_gaps),
            artifacts=tuple(dict(item) for item in getattr(payload, "artifacts", [])),
            raw_notes=tuple(payload.raw_notes),
            clarification_question=payload.clarification_question,
            recent_turns=tuple(turn.model_dump() for turn in payload.recent_turns),
        )


@dataclass(frozen=True, slots=True)
class ResearchStartResult:
    invocation: EngineInvocation
    dossier: NormalizedResearchDossier


def _tool_payload(
    invocation: EngineInvocation,
    dossier: NormalizedResearchDossier,
    *,
    workspace_files: tuple[dict[str, object], ...],
) -> dict[str, Any]:
    return {
        "schema_version": "deep_research_workspace_result@1",
        "invocation_id": invocation.invocation_id,
        "engine_status": invocation.status.value,
        "research_status": dossier.status,
        "completion_reason": dossier.completion_reason,
        "summary": dossier.summary[:2048],
        "evidence_count": len(dossier.evidence_items),
        "source_ref_count": len(dossier.source_refs),
        "gap_count": len(dossier.unresolved_gaps),
        "workspace_files": list(workspace_files),
        "publication_required_for_handoff": True,
        "artifact_alias_created": False,
        "engine_document_body_created": False,
    }


def _write_research_workspace_files(
    runtime_context: Any,
    result: ResearchStartResult,
) -> tuple[dict[str, object], ...]:
    dossier = result.dossier
    root = f"research/{result.invocation.invocation_id}"
    file_payloads: tuple[tuple[str, dict[str, Any]], ...] = (
        (
            "source-snapshots.json",
            {
                "schema_version": "research_source_snapshots@1",
                "sources": [dict(item) for item in dossier.source_refs],
            },
        ),
        (
            "citations.json",
            {
                "schema_version": "research_citations@1",
                "citations": [
                    {
                        "source_index": index,
                        "title": item.get("title"),
                        "doi": item.get("doi"),
                        "pmid": item.get("pmid"),
                    }
                    for index, item in enumerate(dossier.source_refs)
                ],
            },
        ),
        (
            "notes.json",
            {
                "schema_version": "research_notes@1",
                "raw_notes": list(dossier.raw_notes),
                "recent_turns": [dict(item) for item in dossier.recent_turns],
            },
        ),
        (
            "analysis.json",
            {
                "schema_version": "research_analysis@1",
                "status": dossier.status,
                "completion_reason": dossier.completion_reason,
                "research_brief": dossier.research_brief,
                "summary": dossier.summary,
                "evidence_items": [item.to_dict() for item in dossier.evidence_items],
                "unresolved_gaps": list(dossier.unresolved_gaps),
                "clarification_question": dossier.clarification_question,
            },
        ),
        (
            "dossier.json",
            {
                "schema_version": "research_dossier_manifest@1",
                "invocation_id": result.invocation.invocation_id,
                "files": [
                    "source-snapshots.json",
                    "citations.json",
                    "notes.json",
                    "analysis.json",
                ],
                "source_count": len(dossier.source_refs),
                "evidence_count": len(dossier.evidence_items),
                "gap_count": len(dossier.unresolved_gaps),
            },
        ),
    )
    written = tuple(
        runtime_context.write_workspace_json(
            repository_path=f"{root}/{filename}",
            payload=payload,
        )
        for filename, payload in file_payloads
    )
    runtime_context.emit(
        "research.workspace_files_written",
        {
            "invocation_id": result.invocation.invocation_id,
            "files": list(written),
            "publication_required": True,
        },
    )
    return written


def _persist_research_workspace_files(
    engine: "DeepResearchEngine",
    runtime_context: Any,
    result: ResearchStartResult,
) -> tuple[ResearchStartResult, tuple[dict[str, object], ...]]:
    try:
        workspace_files = _write_research_workspace_files(runtime_context, result)
    except Exception as exc:
        if result.invocation.status is EngineInvocationStatus.RUNNING:
            engine.fail_workspace_persistence(result.invocation)
        raise DeepResearchRuntimeError(
            "deep research workspace file persistence failed"
        ) from exc
    if result.invocation.status is EngineInvocationStatus.RUNNING:
        result = ResearchStartResult(
            invocation=engine.complete_workspace_persistence(result.invocation),
            dossier=result.dossier,
        )
    return result, workspace_files


class DeepResearchRunner(Protocol):
    def run(
        self,
        *,
        invocation_id: str,
        objective: str,
        design_brief: str,
        research_brief: str,
        resolution: str | None,
    ) -> Any: ...


class DeepResearchRuntimeError(RuntimeError):
    """Raised when deep research infrastructure/model/provider execution fails."""

    error_code = "deep_research_workspace_integrity_error"


@dataclass(slots=True)
class DirectDeepResearchRunner:
    repositories: Any
    research_adapter: Any
    research_tool_provider: Any | None = None
    model_factory: Any | None = None
    limiter_registry: Any | None = None
    settings: Any | None = None

    def run(
        self,
        *,
        invocation_id: str,
        objective: str,
        design_brief: str,
        research_brief: str,
        resolution: str | None,
    ) -> Any:
        if self.research_adapter is None:
            raise ValueError("DirectDeepResearchRunner requires a research_adapter")
        effective_brief = research_brief
        if resolution:
            effective_brief = f"{research_brief}\n\nResolution:\n{resolution}"
        query = " ".join(part for part in (objective, design_brief, effective_brief) if part)
        response = self.research_adapter.web_search(
            query=query,
            max_results=3,
            topic="enzyme design",
            include_raw_content=True,
        )
        results = list(response.get("results", []))
        evidence_items: list[EvidenceSynthesisItem] = []
        raw_notes: list[str] = []
        for index, raw_result in enumerate(results[:3], start=1):
            result = dict(raw_result)
            title = str(result.get("title") or f"Research source {index}")
            locator = str(result.get("url") or result.get("locator") or "")
            snippet = str(
                result.get("content") or result.get("raw_content") or title
            )
            raw_notes.append(snippet)
            evidence_items.append(
                EvidenceSynthesisItem(
                    summary=snippet,
                    query=query,
                    confidence_label="medium",
                    sources=[
                        ResearchSourceItem(
                            title=title,
                            locator=locator,
                            kind=SourceRefKind.WEB_PAGE.value,
                            snippet=snippet,
                        )
                    ],
                )
            )
        summary = (
            "Research completed with web evidence for the requested design brief."
            if evidence_items
            else "Research completed without source-backed findings."
        )
        return ResearchDossier(
            status="completed",
            completion_reason="research_completed",
            research_brief=effective_brief,
            summary=summary,
            evidence_items=evidence_items,
            unresolved_gaps=[] if evidence_items else ["No source-backed findings were returned."],
            raw_notes=raw_notes,
            recent_turns=[
                ResearchTurnRecord(
                    turn_index=1,
                    action_kind="web_search",
                    status="completed",
                    summary=summary,
                    rationale="Direct V3 research runner executed a bounded web search.",
                    tool_names=["web.search"],
                    observation_summary=summary,
                    created_at=utc_now_iso(),
                )
            ],
        )


@dataclass(slots=True)
class GraphBackedDeepResearchRunner:
    repositories: Any
    research_adapter: Any
    research_tool_provider: Any | None = None
    model_factory: Any | None = None
    limiter_registry: Any | None = None
    settings: Any | None = None

    def run(
        self,
        *,
        invocation_id: str,
        objective: str,
        design_brief: str,
        research_brief: str,
        resolution: str | None,
    ) -> Any:
        invocation = self.repositories.invocations.get(invocation_id)
        if invocation is None:
            raise ValueError(f"invocation {invocation_id!r} does not exist")
        session = self.repositories.sessions.get(invocation.session_id)
        if session is None:
            raise ValueError(f"session {invocation.session_id!r} does not exist")
        effective_research_brief = research_brief
        if resolution:
            effective_research_brief = f"{research_brief}\n\nResolution:\n{resolution}"
        return run_deep_research(
            DeepResearchGraphInputs(
                session_id=invocation.session_id,
                project_id=session.project_id,
                research_adapter=self.research_adapter,
                research_tool_provider=self.research_tool_provider,
                model_factory=self.model_factory,
                limiter_registry=self.limiter_registry,
                settings=resolve_research_graph_settings(self.settings),
            ),
            objective=objective,
            design_brief=design_brief,
            research_brief=effective_research_brief,
        )


NativeDeepResearchRunner = GraphBackedDeepResearchRunner


@dataclass(slots=True)
class DeepResearchEngine:
    repositories: Any
    runner: DeepResearchRunner
    event_emitter: Any | None = None

    @property
    def descriptor(self) -> EngineDescriptor:
        return EngineDescriptor(
            engine_name="deep_research",
            tool_names=(
                "deep_research.start",
                "deep_research.resume",
                "deep_research.status",
                "deep_research.dossier",
            ),
            input_schema={"type": "object", "required": ["task_id", "brief"]},
            output_schema={
                "type": "object",
                "required": ["summary", "evidence_items", "source_refs", "unresolved_gaps"],
            },
            requires_approval=False,
            supports_background=True,
            idempotency_key_shape="{task_id}:deep_research:{nonce}",
            produces_artifact_types=(),
            capability_key="deep_research",
        )

    def register_tools(self, registry: ToolRegistryProtocol) -> None:
        register_deep_research_tools(registry, self)

    def start_research(
        self,
        *,
        session_id: str,
        task_id: str,
        brief: str,
        invocation_id: str | None = None,
        lane_id: str | None = None,
        idempotency_key: str | None = None,
        defer_success_until_workspace_persisted: bool = True,
    ) -> ResearchStartResult:
        if len(brief.encode("utf-8")) > 8_192:
            raise ValueError("deep research brief exceeds 8192 bytes")
        session = self._require_session(session_id)
        task = self._require_task(session_id, task_id)
        effective_lane_id = task.lane_id if lane_id is None else lane_id
        now = utc_now_iso()
        invocation_id = invocation_id or f"inv_{uuid4().hex[:12]}"
        input_id = _new_document_id("eng_in")
        invocation = EngineInvocation(
            invocation_id=invocation_id,
            session_id=session_id,
            task_id=task_id,
            lane_id=effective_lane_id,
            engine_name=self.descriptor.engine_name,
            status=EngineInvocationStatus.RUNNING,
            input_ref=input_id,
            output_ref=None,
            approval_id=None,
            idempotency_key=idempotency_key or f"{task_id}:deep_research:{uuid4().hex[:8]}",
            started_at=now,
        )
        self.repositories.invocations.save(invocation)
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=input_id,
                session_id=session_id,
                invocation_id=invocation_id,
                document_kind="deep_research_input",
                payload={"task_id": task_id, "lane_id": effective_lane_id, "brief": brief, "resolution": None},
                created_at=now,
                updated_at=now,
            )
        )
        self._emit(
            "engine.invocation.started",
            {"invocation_id": invocation_id, "engine_name": self.descriptor.engine_name, "task_id": task_id},
        )
        return self._execute(
            session=session,
            task=task,
            invocation=invocation,
            defer_success_until_workspace_persisted=(
                defer_success_until_workspace_persisted
            ),
        )

    def resume_research(
        self,
        *,
        invocation_id: str,
        resolution: str,
        defer_success_until_workspace_persisted: bool = True,
    ) -> ResearchStartResult:
        if len(resolution.encode("utf-8")) > 8_192:
            raise ValueError("deep research resolution exceeds 8192 bytes")
        invocation = self._require_invocation(invocation_id)
        session = self._require_session(invocation.session_id)
        task = self._require_task(invocation.session_id, str(invocation.task_id))
        input_payload = self._require_input_payload(invocation)
        now = utc_now_iso()
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=str(invocation.input_ref),
                session_id=invocation.session_id,
                invocation_id=invocation.invocation_id,
                document_kind="deep_research_input",
                payload={
                    **input_payload,
                    "resolution": resolution,
                },
                created_at=now,
                updated_at=now,
            )
        )
        running_invocation = EngineInvocation(
            invocation_id=invocation.invocation_id,
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            engine_name=invocation.engine_name,
            status=EngineInvocationStatus.RUNNING,
            input_ref=invocation.input_ref,
            output_ref=invocation.output_ref,
            approval_id=invocation.approval_id,
            idempotency_key=invocation.idempotency_key,
            started_at=invocation.started_at,
            finished_at=None,
        )
        self.repositories.invocations.save(running_invocation)
        self._emit(
            "engine.invocation.updated",
            {"invocation_id": invocation.invocation_id, "engine_name": invocation.engine_name, "status": "running"},
        )
        return self._execute(
            session=session,
            task=task,
            invocation=running_invocation,
            defer_success_until_workspace_persisted=(
                defer_success_until_workspace_persisted
            ),
        )

    def get_research_status(self, invocation_id: str) -> dict[str, Any]:
        invocation = self._require_invocation(invocation_id)
        payload = invocation.to_dict()
        payload["engine_status"] = invocation.status.value
        root = f"research/{invocation.invocation_id}"
        payload["workspace_layout"] = [
            f"{root}/source-snapshots.json",
            f"{root}/citations.json",
            f"{root}/notes.json",
            f"{root}/analysis.json",
            f"{root}/dossier.json",
        ]
        payload["artifact_alias_created"] = False
        payload["persistent_content_authority"] = "workspace_file_then_publication"
        payload["legacy_research_content_read"] = False
        return payload

    def get_research_dossier(self, invocation_id: str) -> NormalizedResearchDossier:
        self._require_invocation(invocation_id)
        raise ValueError(
            "research dossier bytes are not stored in EngineDocument; inspect the "
            "producer workspace file or an exact published RevisionPathRef@1"
        )

    def _execute(
        self,
        *,
        session: Any,
        task: Any,
        invocation: EngineInvocation,
        defer_success_until_workspace_persisted: bool,
    ) -> ResearchStartResult:
        input_payload = self._require_input_payload(invocation)
        research_brief = str(input_payload["brief"])
        resolution = None if input_payload.get("resolution") is None else str(input_payload["resolution"])
        try:
            runner_output = self.runner.run(
                invocation_id=invocation.invocation_id,
                objective=session.objective,
                design_brief=task.description,
                research_brief=research_brief,
                resolution=resolution,
            )
            dossier = NormalizedResearchDossier.from_runner_payload(runner_output)
            if dossier.artifacts:
                raise ValueError(
                    "deep research runner returned artifact-era file manifests; "
                    "provider files must be written directly into the researcher workspace"
                )
        except Exception as exc:
            failure_dossier = _runtime_failure_dossier(
                research_brief=research_brief,
                exc=exc,
            )
            self._complete_failure(
                session=session,
                task=task,
                invocation=invocation,
                dossier=failure_dossier,
            )
            raise DeepResearchRuntimeError(failure_dossier.summary) from exc
        if dossier.status == "failed":
            if not self._is_controlled_domain_failure(dossier):
                message = dossier.summary or "deep research runner returned failed without controlled domain failure metadata"
                self._complete_failure(
                    session=session,
                    task=task,
                    invocation=invocation,
                    dossier=dossier,
                )
                raise DeepResearchRuntimeError(message)
            return self._complete_failure(
                session=session,
                task=task,
                invocation=invocation,
                dossier=dossier,
            )
        return self._complete_success(
            session=session,
            task=task,
            invocation=invocation,
            dossier=dossier,
            defer_until_workspace_persisted=(
                defer_success_until_workspace_persisted
            ),
        )

    def _is_controlled_domain_failure(self, dossier: NormalizedResearchDossier) -> bool:
        markers = {
            dossier.completion_reason,
            *dossier.raw_notes,
        }
        return any(
            str(marker).startswith("controlled_domain_failure")
            or str(marker).startswith("domain_failure")
            for marker in markers
        )

    def _complete_success(
        self,
        *,
        session: Any,
        task: Any,
        invocation: EngineInvocation,
        dossier: NormalizedResearchDossier,
        defer_until_workspace_persisted: bool,
    ) -> ResearchStartResult:
        if defer_until_workspace_persisted:
            return ResearchStartResult(invocation=invocation, dossier=dossier)
        return ResearchStartResult(
            invocation=self.complete_workspace_persistence(invocation),
            dossier=dossier,
        )

    def complete_workspace_persistence(
        self,
        invocation: EngineInvocation,
    ) -> EngineInvocation:
        current = self._require_invocation(invocation.invocation_id)
        if current != invocation or current.status is not EngineInvocationStatus.RUNNING:
            raise DeepResearchRuntimeError(
                "deep research invocation changed before workspace persistence completed"
            )
        now = utc_now_iso()
        updated_invocation = EngineInvocation(
            invocation_id=current.invocation_id,
            session_id=current.session_id,
            task_id=current.task_id,
            lane_id=current.lane_id,
            engine_name=current.engine_name,
            status=EngineInvocationStatus.SUCCEEDED,
            input_ref=current.input_ref,
            output_ref=None,
            approval_id=current.approval_id,
            idempotency_key=current.idempotency_key,
            started_at=current.started_at,
            finished_at=now,
        )
        self.repositories.invocations.save(updated_invocation)
        self._emit(
            "engine.invocation.completed",
            {
                "invocation_id": current.invocation_id,
                "engine_name": current.engine_name,
                "status": "succeeded",
                "workspace_files_persisted": True,
            },
        )
        return updated_invocation

    def fail_workspace_persistence(
        self,
        invocation: EngineInvocation,
    ) -> EngineInvocation:
        current = self._require_invocation(invocation.invocation_id)
        if current != invocation or current.status is not EngineInvocationStatus.RUNNING:
            raise DeepResearchRuntimeError(
                "deep research invocation changed before workspace persistence failed"
            )
        now = utc_now_iso()
        failed_invocation = EngineInvocation(
            invocation_id=current.invocation_id,
            session_id=current.session_id,
            task_id=current.task_id,
            lane_id=current.lane_id,
            engine_name=current.engine_name,
            status=EngineInvocationStatus.FAILED,
            input_ref=current.input_ref,
            output_ref=None,
            approval_id=current.approval_id,
            idempotency_key=current.idempotency_key,
            started_at=current.started_at,
            finished_at=now,
        )
        self.repositories.invocations.save(failed_invocation)
        self._emit(
            "engine.invocation.completed",
            {
                "invocation_id": current.invocation_id,
                "engine_name": current.engine_name,
                "status": "failed",
                "error_code": "workspace_file_persistence_failed",
            },
        )
        return failed_invocation

    def _complete_failure(
        self,
        *,
        session: Any,
        task: Any,
        invocation: EngineInvocation,
        dossier: NormalizedResearchDossier,
    ) -> ResearchStartResult:
        now = utc_now_iso()
        failed_invocation = EngineInvocation(
            invocation_id=invocation.invocation_id,
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            engine_name=invocation.engine_name,
            status=EngineInvocationStatus.FAILED,
            input_ref=invocation.input_ref,
            output_ref=None,
            approval_id=invocation.approval_id,
            idempotency_key=invocation.idempotency_key,
            started_at=invocation.started_at,
            finished_at=now,
        )
        self.repositories.invocations.save(failed_invocation)
        self._emit(
            "engine.invocation.completed",
            {"invocation_id": invocation.invocation_id, "engine_name": invocation.engine_name, "status": "failed"},
        )
        return ResearchStartResult(
            invocation=failed_invocation,
            dossier=dossier,
        )

    def _require_session(self, session_id: str) -> Any:
        session = self.repositories.sessions.get(session_id)
        if session is None:
            raise ValueError(f"session {session_id!r} does not exist")
        return session

    def _require_task(self, session_id: str, task_id: str) -> Any:
        task = self.repositories.tasks.get(task_id)
        if task is None:
            raise ValueError(f"task {task_id!r} does not exist")
        if task.session_id != session_id:
            raise ValueError(f"task {task_id!r} belongs to session {task.session_id!r}, not {session_id!r}")
        return task

    def _require_invocation(self, invocation_id: str) -> EngineInvocation:
        invocation = self.repositories.invocations.get(invocation_id)
        if invocation is None:
            raise ValueError(f"invocation {invocation_id!r} does not exist")
        return invocation

    def _require_input_payload(self, invocation: EngineInvocation) -> dict[str, Any]:
        if invocation.input_ref is None:
            raise ValueError(f"invocation {invocation.invocation_id!r} does not have an input document")
        document = self.repositories.engine_documents.get(invocation.input_ref)
        if document is None:
            raise ValueError(f"input document {invocation.input_ref!r} does not exist")
        return document.payload

    def _document_record(
        self,
        *,
        document_id: str,
        session_id: str,
        invocation_id: str,
        document_kind: str,
        payload: dict[str, Any],
        created_at: str,
        updated_at: str,
    ) -> Any:
        return EngineDocumentRecord(
            document_id=document_id,
            session_id=session_id,
            invocation_id=invocation_id,
            document_kind=document_kind,
            payload=payload,
            created_at=created_at,
            updated_at=updated_at,
        )

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_emitter is not None:
            self.event_emitter(event_type, payload)


def _runtime_failure_dossier(
    *,
    research_brief: str,
    exc: Exception,
) -> NormalizedResearchDossier:
    classification = classify_llm_provider_error(exc)
    summary = f"Deep research runtime failed: {type(exc).__name__}: {exc}"
    return NormalizedResearchDossier(
        status="failed",
        completion_reason=f"runtime_failure:{classification.category}",
        research_brief=research_brief,
        summary=summary,
        evidence_items=(),
        source_refs=(),
        unresolved_gaps=(summary,),
        raw_notes=(
            "domain_failure:runtime_exception",
            "provider_taxonomy="
            + json.dumps(
                classification.to_dict(),
                ensure_ascii=True,
                sort_keys=True,
            ),
        ),
    )


def _deep_research_start_spec() -> ToolSpec:
    return ToolSpec(
        tool_name="deep_research.start",
        description="Start deep research for the currently assigned task.",
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "brief": {"type": "string", "maxLength": 8192},
            },
            "required": ["task_id", "brief"],
            "additionalProperties": False,
        },
    )


def _deep_research_resume_spec() -> ToolSpec:
    return ToolSpec(
        tool_name="deep_research.resume",
        description="Resume a deep research invocation after clarification.",
        input_schema={
            "type": "object",
            "properties": {
                "invocation_id": {"type": "string"},
                "resolution": {"type": "string", "maxLength": 8192},
            },
            "required": ["invocation_id", "resolution"],
            "additionalProperties": False,
        },
    )


def _deep_research_status_spec() -> ToolSpec:
    return ToolSpec(
        tool_name="deep_research.status",
        description="Read the current status of a deep research invocation.",
        input_schema={
            "type": "object",
            "properties": {"invocation_id": {"type": "string"}},
            "required": ["invocation_id"],
            "additionalProperties": False,
        },
    )


def _deep_research_dossier_spec() -> ToolSpec:
    return ToolSpec(
        tool_name="deep_research.dossier",
        description=(
            "Locate the dossier in the current private Git workspace without "
            "returning dossier bytes; publish an exact revision before handoff."
        ),
        input_schema={
            "type": "object",
            "properties": {"invocation_id": {"type": "string"}},
            "required": ["invocation_id"],
            "additionalProperties": False,
        },
    )


@dataclass(frozen=True, slots=True)
class DeepResearchStartRuntime:
    engine: DeepResearchEngine
    tool_name: str = "deep_research.start"

    def spec(self, step_context: AgentStepContext) -> ToolSpec:
        del step_context
        return _deep_research_start_spec()

    def is_visible(self, step_context: AgentStepContext) -> bool:
        del step_context
        return True

    def governance(self, step_context: AgentStepContext) -> ToolGovernance:
        del step_context
        return ToolGovernance(
            role_scope=("researcher",),
            supports_parallel=False,
            side_effect=ToolSideEffect.EXTERNAL,
            approval_required=False,
            result_budget_policy="default",
        )

    def validate(
        self, step_context: AgentStepContext, invocation: ToolInvocation
    ) -> ToolValidationError | None:
        del step_context
        return validate_arguments_against_schema(
            tool_name=invocation.tool_name,
            input_schema=_deep_research_start_spec().input_schema,
            arguments=invocation.arguments,
        )

    def dispatch(
        self,
        step_context: AgentStepContext,
        invocation: ToolInvocation,
        runtime_context: Any,
    ) -> ToolResult:
        del step_context
        result = self.engine.start_research(
            session_id=runtime_context.snapshot.session.session_id,
            task_id=str(invocation.arguments["task_id"]),
            brief=str(invocation.arguments["brief"]),
            invocation_id=None,
            lane_id=invocation.lane_id,
            idempotency_key=None,
            defer_success_until_workspace_persisted=True,
        )
        result, workspace_files = _persist_research_workspace_files(
            self.engine,
            runtime_context,
            result,
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=result.invocation.status is EngineInvocationStatus.SUCCEEDED,
            content=json.dumps(
                _tool_payload(
                    result.invocation,
                    result.dossier,
                    workspace_files=workspace_files,
                ),
                sort_keys=True,
            ),
            task_id=result.invocation.task_id,
            lane_id=result.invocation.lane_id,
        )


@dataclass(frozen=True, slots=True)
class DeepResearchResumeRuntime:
    engine: DeepResearchEngine
    tool_name: str = "deep_research.resume"

    def spec(self, step_context: AgentStepContext) -> ToolSpec:
        del step_context
        return _deep_research_resume_spec()

    def is_visible(self, step_context: AgentStepContext) -> bool:
        del step_context
        return True

    def governance(self, step_context: AgentStepContext) -> ToolGovernance:
        del step_context
        return ToolGovernance(
            role_scope=("researcher",),
            supports_parallel=False,
            side_effect=ToolSideEffect.EXTERNAL,
            approval_required=False,
            result_budget_policy="default",
        )

    def validate(
        self, step_context: AgentStepContext, invocation: ToolInvocation
    ) -> ToolValidationError | None:
        del step_context
        return validate_arguments_against_schema(
            tool_name=invocation.tool_name,
            input_schema=_deep_research_resume_spec().input_schema,
            arguments=invocation.arguments,
        )

    def dispatch(
        self,
        step_context: AgentStepContext,
        invocation: ToolInvocation,
        runtime_context: Any,
    ) -> ToolResult:
        del step_context
        result = self.engine.resume_research(
            invocation_id=str(invocation.arguments["invocation_id"]),
            resolution=str(invocation.arguments["resolution"]),
            defer_success_until_workspace_persisted=True,
        )
        result, workspace_files = _persist_research_workspace_files(
            self.engine,
            runtime_context,
            result,
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=result.invocation.status is EngineInvocationStatus.SUCCEEDED,
            content=json.dumps(
                _tool_payload(
                    result.invocation,
                    result.dossier,
                    workspace_files=workspace_files,
                ),
                sort_keys=True,
            ),
            task_id=result.invocation.task_id,
            lane_id=result.invocation.lane_id,
        )


@dataclass(frozen=True, slots=True)
class DeepResearchStatusRuntime:
    engine: DeepResearchEngine
    tool_name: str = "deep_research.status"

    def spec(self, step_context: AgentStepContext) -> ToolSpec:
        del step_context
        return _deep_research_status_spec()

    def is_visible(self, step_context: AgentStepContext) -> bool:
        del step_context
        return True

    def governance(self, step_context: AgentStepContext) -> ToolGovernance:
        del step_context
        return ToolGovernance(
            role_scope=("researcher",),
            supports_parallel=True,
            side_effect=ToolSideEffect.READ,
            approval_required=False,
            result_budget_policy="default",
        )

    def validate(
        self, step_context: AgentStepContext, invocation: ToolInvocation
    ) -> ToolValidationError | None:
        del step_context
        return validate_arguments_against_schema(
            tool_name=invocation.tool_name,
            input_schema=_deep_research_status_spec().input_schema,
            arguments=invocation.arguments,
        )

    def dispatch(
        self,
        step_context: AgentStepContext,
        invocation: ToolInvocation,
        runtime_context: Any,
    ) -> ToolResult:
        del step_context, runtime_context
        status = self.engine.get_research_status(str(invocation.arguments["invocation_id"]))
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(status, sort_keys=True),
        )


@dataclass(frozen=True, slots=True)
class DeepResearchDossierRuntime:
    engine: DeepResearchEngine
    tool_name: str = "deep_research.dossier"

    def spec(self, step_context: AgentStepContext) -> ToolSpec:
        del step_context
        return _deep_research_dossier_spec()

    def is_visible(self, step_context: AgentStepContext) -> bool:
        del step_context
        return True

    def governance(self, step_context: AgentStepContext) -> ToolGovernance:
        del step_context
        return ToolGovernance(
            role_scope=("researcher",),
            supports_parallel=True,
            side_effect=ToolSideEffect.READ,
            approval_required=False,
            result_budget_policy="default",
        )

    def validate(
        self, step_context: AgentStepContext, invocation: ToolInvocation
    ) -> ToolValidationError | None:
        del step_context
        return validate_arguments_against_schema(
            tool_name=invocation.tool_name,
            input_schema=_deep_research_dossier_spec().input_schema,
            arguments=invocation.arguments,
        )

    def dispatch(
        self,
        step_context: AgentStepContext,
        invocation: ToolInvocation,
        runtime_context: Any,
    ) -> ToolResult:
        del step_context
        invocation_id = str(invocation.arguments["invocation_id"])
        engine_invocation = self.engine._require_invocation(invocation_id)
        status = self.engine.get_research_status(invocation_id)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(
                {
                    "schema_version": "deep_research_workspace_lookup@1",
                    "invocation_id": engine_invocation.invocation_id,
                    "engine_status": engine_invocation.status.value,
                    "workspace_layout": status["workspace_layout"],
                    "content_bytes_in_control_plane": False,
                    "publication_required_for_handoff": True,
                },
                sort_keys=True,
            ),
        )


def register_deep_research_tools(registry: ToolRegistryProtocol, engine: DeepResearchEngine) -> None:
    registry.register_runtime(DeepResearchStartRuntime(engine))
    registry.register_runtime(DeepResearchResumeRuntime(engine))
    registry.register_runtime(DeepResearchStatusRuntime(engine))
    registry.register_runtime(DeepResearchDossierRuntime(engine))


__all__ = [
    "DeepResearchEngine",
    "DeepResearchRunner",
    "DirectDeepResearchRunner",
    "NativeDeepResearchRunner",
    "NormalizedResearchDossier",
    "ResearchEvidenceItem",
    "ResearchStartResult",
    "register_deep_research_tools",
]
