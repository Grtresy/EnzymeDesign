from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from typing import Protocol
from uuid import uuid4

from openzyme_core import EngineDescriptor
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import ToolResult
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import Episode
from openzyme_domain import ArtifactKind
from openzyme_domain import MemoryEntry
from openzyme_domain import MemoryKind
from openzyme_domain import MemoryScopeKind
from openzyme_domain import Project
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SourceRefKind
from openzyme_domain import ResearchEvidence
from openzyme_domain import ResearchGap
from openzyme_domain import ResearchSourceRef
from openzyme_domain import ResearchSummary
from openzyme_domain import ResearchSummaryStatus
from openzyme_domain.control_plane import utc_now_iso

from .deep_research_contracts import ResearchDossier
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


@dataclass(slots=True)
class GraphBackedDeepResearchRunner:
    repositories: Any
    research_adapter: Any
    research_tool_provider: Any | None = None
    model_factory: Any | None = None
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
        from langgraph.checkpoint.memory import InMemorySaver
        from openzyme_runtime import DefaultResearchToolProvider
        from openzyme_runtime import GraphAssemblyInputs
        from openzyme_runtime import OpenZymeHostToolbox
        from openzyme_runtime import get_settings

        if self.research_adapter is None:
            raise ValueError("GraphBackedDeepResearchRunner requires a research_adapter")
        settings = self.settings or get_settings()
        effective_brief = research_brief
        if resolution:
            effective_brief = f"{research_brief}\n\nResolution:\n{resolution}"
        tool_provider = self.research_tool_provider or DefaultResearchToolProvider(
            self.research_adapter,
            mcp_enabled=settings.research.mcp_enabled,
            mcp_tool_allowlist=settings.research.mcp_tool_allowlist,
        )
        project = Project.create(project_id=f"proj_{invocation_id}", name="V3 deep research")
        episode = Episode.create(
            episode_id=invocation_id,
            project_id=project.project_id,
            objective=objective,
        )
        inputs = GraphAssemblyInputs(
            repositories=self.repositories,
            checkpointer=InMemorySaver(),
            execution_adapter=None,
            hpc_catalog_provider=None,
            hpc_execution_registry=None,
            research_adapter=self.research_adapter,
            research_tool_provider=tool_provider,
            projection_loader=None,
            model_factory=self.model_factory,
            host_toolbox=OpenZymeHostToolbox(self.repositories),
            settings=settings,
        )
        return run_deep_research(
            inputs,
            episode_id=episode.episode_id,
            project_id=project.project_id,
            objective=objective,
            design_brief=design_brief,
            research_brief=effective_brief,
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
            produces_artifact_types=("research_dossier",),
            capability_key="deep_research",
        )

    def register_tools(self, registry: ToolRegistry) -> None:
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
    ) -> ResearchStartResult:
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
        return self._execute(session=session, task=task, invocation=invocation)

    def resume_research(self, *, invocation_id: str, resolution: str) -> ResearchStartResult:
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
        return self._execute(session=session, task=task, invocation=running_invocation)

    def get_research_status(self, invocation_id: str) -> dict[str, Any]:
        invocation = self._require_invocation(invocation_id)
        payload = invocation.to_dict()
        summary = self.repositories.research_summaries.get_by_invocation(invocation.session_id, invocation_id)
        if summary is not None:
            payload["canonical_summary"] = summary.to_dict()
        return payload

    def get_research_dossier(self, invocation_id: str) -> NormalizedResearchDossier:
        invocation = self._require_invocation(invocation_id)
        if invocation.output_ref is None:
            raise ValueError(f"invocation {invocation_id!r} does not have an output dossier yet")
        document = self.repositories.engine_documents.get(invocation.output_ref)
        if document is None:
            raise ValueError(f"output document {invocation.output_ref!r} does not exist")
        return self._dossier_from_payload(document.payload)

    def _execute(
        self,
        *,
        session: Any,
        task: Any,
        invocation: EngineInvocation,
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
            return self._complete_success(
                session=session,
                task=task,
                invocation=invocation,
                dossier=dossier,
            )
        except Exception as exc:
            dossier = self._build_failure_dossier(research_brief=research_brief, error=str(exc))
            return self._complete_failure(
                session=session,
                task=task,
                invocation=invocation,
                dossier=dossier,
            )

    def _complete_success(
        self,
        *,
        session: Any,
        task: Any,
        invocation: EngineInvocation,
        dossier: NormalizedResearchDossier,
    ) -> ResearchStartResult:
        now = utc_now_iso()
        output_id = _new_document_id("eng_out")
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=output_id,
                session_id=session.session_id,
                invocation_id=invocation.invocation_id,
                document_kind="deep_research_dossier",
                payload=dossier.to_dict(),
                created_at=now,
                updated_at=now,
            )
        )
        self._rewrite_canonical_research(
            invocation=invocation,
            dossier=dossier,
            updated_at=now,
        )
        self._persist_artifacts(
            session_id=session.session_id,
            task_id=task.task_id,
            lane_id=invocation.lane_id,
            invocation_id=invocation.invocation_id,
            dossier=dossier,
            created_at=now,
        )
        updated_invocation = EngineInvocation(
            invocation_id=invocation.invocation_id,
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            engine_name=invocation.engine_name,
            status=EngineInvocationStatus.SUCCEEDED,
            input_ref=invocation.input_ref,
            output_ref=output_id,
            approval_id=invocation.approval_id,
            idempotency_key=invocation.idempotency_key,
            started_at=invocation.started_at,
            finished_at=now,
        )
        self.repositories.invocations.save(updated_invocation)
        self.repositories.memory.save(
            MemoryEntry(
                memory_id=f"mem_{uuid4().hex[:12]}",
                session_id=session.session_id,
                scope_kind=MemoryScopeKind.TASK,
                scope_ref=task.task_id,
                kind=MemoryKind.SUMMARY,
                summary=dossier.summary,
                source_range=f"engine:{invocation.invocation_id}",
                importance=7,
                created_at=now,
            )
        )
        self._emit(
            "engine.invocation.completed",
            {"invocation_id": invocation.invocation_id, "engine_name": invocation.engine_name, "status": "succeeded"},
        )
        return ResearchStartResult(invocation=updated_invocation, dossier=dossier)

    def _complete_failure(
        self,
        *,
        session: Any,
        task: Any,
        invocation: EngineInvocation,
        dossier: NormalizedResearchDossier,
    ) -> ResearchStartResult:
        now = utc_now_iso()
        output_id = _new_document_id("eng_out")
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=output_id,
                session_id=session.session_id,
                invocation_id=invocation.invocation_id,
                document_kind="deep_research_dossier",
                payload=dossier.to_dict(),
                created_at=now,
                updated_at=now,
            )
        )
        self._rewrite_canonical_research(
            invocation=invocation,
            dossier=dossier,
            updated_at=now,
        )
        failed_invocation = EngineInvocation(
            invocation_id=invocation.invocation_id,
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            engine_name=invocation.engine_name,
            status=EngineInvocationStatus.FAILED,
            input_ref=invocation.input_ref,
            output_ref=output_id,
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
        return ResearchStartResult(invocation=failed_invocation, dossier=dossier)

    def _rewrite_canonical_research(
        self,
        *,
        invocation: EngineInvocation,
        dossier: NormalizedResearchDossier,
        updated_at: str,
    ) -> None:
        session_id = invocation.session_id
        summary_id = f"{invocation.invocation_id}:summary"
        self.repositories.research_source_refs.delete_by_invocation(session_id, invocation.invocation_id)
        self.repositories.research_evidence.delete_by_invocation(session_id, invocation.invocation_id)
        self.repositories.research_gaps.delete_by_invocation(session_id, invocation.invocation_id)
        summary_status = {
            "completed": ResearchSummaryStatus.COMPLETED,
            "partial": ResearchSummaryStatus.PARTIAL,
            "needs_clarification": ResearchSummaryStatus.NEEDS_CLARIFICATION,
            "failed": ResearchSummaryStatus.FAILED,
        }[dossier.status]
        existing = self.repositories.research_summaries.get_by_invocation(session_id, invocation.invocation_id)
        created_at = updated_at if existing is None else existing.created_at
        self.repositories.research_summaries.save(
            ResearchSummary(
                summary_id=summary_id,
                session_id=session_id,
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
                invocation_id=invocation.invocation_id,
                status=summary_status,
                completion_reason=dossier.completion_reason,
                research_brief=dossier.research_brief,
                summary=dossier.summary,
                clarification_question=dossier.clarification_question,
                created_at=created_at,
                updated_at=updated_at,
            )
        )
        self._emit(
            "research.summary.updated",
            {"invocation_id": invocation.invocation_id, "summary_id": summary_id, "status": summary_status.value},
        )
        for evidence_index, evidence_item in enumerate(dossier.evidence_items, start=1):
            evidence_id = f"{invocation.invocation_id}:evidence:{evidence_index}"
            self.repositories.research_evidence.save(
                ResearchEvidence(
                    evidence_id=evidence_id,
                    session_id=session_id,
                    task_id=invocation.task_id,
                    lane_id=invocation.lane_id,
                    invocation_id=invocation.invocation_id,
                    summary_id=summary_id,
                    summary=evidence_item.summary,
                    query=evidence_item.query,
                    confidence_label=evidence_item.confidence_label,
                    created_at=updated_at,
                )
            )
            self._emit(
                "research.evidence.recorded",
                {"invocation_id": invocation.invocation_id, "evidence_id": evidence_id},
            )
            for source_index, source in enumerate(evidence_item.sources, start=1):
                self.repositories.research_source_refs.save(
                    ResearchSourceRef(
                        source_ref_id=f"{evidence_id}:source:{source_index}",
                        session_id=session_id,
                        task_id=invocation.task_id,
                        lane_id=invocation.lane_id,
                        invocation_id=invocation.invocation_id,
                        evidence_id=evidence_id,
                        title=str(source["title"]),
                        locator=str(source["locator"]),
                        kind=SourceRefKind(str(source["kind"])),
                        snippet=None if source.get("snippet") is None else str(source["snippet"]),
                        created_at=updated_at,
                    )
                )
        for gap_index, gap in enumerate(dossier.unresolved_gaps, start=1):
            self.repositories.research_gaps.save(
                ResearchGap(
                    gap_id=f"{invocation.invocation_id}:gap:{gap_index}",
                    session_id=session_id,
                    task_id=invocation.task_id,
                    lane_id=invocation.lane_id,
                    invocation_id=invocation.invocation_id,
                    summary_id=summary_id,
                    summary=gap,
                    created_at=updated_at,
                )
            )

    def _persist_artifacts(
        self,
        *,
        session_id: str,
        task_id: str | None,
        lane_id: str | None,
        invocation_id: str,
        dossier: NormalizedResearchDossier,
        created_at: str,
    ) -> None:
        from pathlib import PurePosixPath

        for index, item in enumerate(dossier.artifacts, start=1):
            filename = str(item.get("filename") or f"artifact_{index}")
            title = str(item.get("title") or PurePosixPath(filename).name)
            self.repositories.artifacts.save(
                SessionArtifactRecord(
                    artifact_id=f"{invocation_id}:artifact:{index}",
                    session_id=session_id,
                    task_id=task_id,
                    lane_id=lane_id,
                    invocation_id=invocation_id,
                    run_id=None,
                    kind=ArtifactKind(str(item.get("kind") or "other")),
                    storage_uri=str(item.get("storage_uri") or item.get("source_locator") or f"research://{filename}"),
                    relative_path=filename,
                    title=title,
                    description=None if item.get("description") is None else str(item.get("description")),
                    metadata={
                        "provider": item.get("provider"),
                        "external_id": item.get("external_id"),
                        "format": item.get("format"),
                        "source_locator": item.get("source_locator"),
                        "produced_by": "deep_research",
                        **({} if item.get("metadata") is None else dict(item.get("metadata"))),
                    },
                    created_at=created_at,
                )
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
        from openzyme_core import EngineDocumentRecord

        return EngineDocumentRecord(
            document_id=document_id,
            session_id=session_id,
            invocation_id=invocation_id,
            document_kind=document_kind,
            payload=payload,
            created_at=created_at,
            updated_at=updated_at,
        )

    def _build_failure_dossier(self, *, research_brief: str, error: str) -> NormalizedResearchDossier:
        return NormalizedResearchDossier(
            status="failed",
            completion_reason="research_failed",
            research_brief=research_brief,
            summary=error,
            evidence_items=(),
            source_refs=(),
            unresolved_gaps=(error,),
            raw_notes=(error,),
            clarification_question=None,
            recent_turns=(),
        )

    def _dossier_from_payload(self, payload: dict[str, Any]) -> NormalizedResearchDossier:
        return NormalizedResearchDossier(
            status=str(payload["status"]),
            completion_reason=str(payload["completion_reason"]),
            research_brief=str(payload["research_brief"]),
            summary=str(payload["summary"]),
            evidence_items=tuple(
                ResearchEvidenceItem(
                    summary=str(item["summary"]),
                    query=str(item["query"]),
                    confidence_label=None if item.get("confidence_label") is None else str(item["confidence_label"]),
                    sources=tuple(dict(source) for source in item.get("sources", [])),
                )
                for item in payload.get("evidence_items", [])
            ),
            source_refs=tuple(dict(source) for source in payload.get("source_refs", [])),
            unresolved_gaps=tuple(str(gap) for gap in payload.get("unresolved_gaps", [])),
            artifacts=tuple(dict(item) for item in payload.get("artifacts", [])),
            raw_notes=tuple(str(note) for note in payload.get("raw_notes", [])),
            clarification_question=payload.get("clarification_question"),
            recent_turns=tuple(dict(turn) for turn in payload.get("recent_turns", [])),
        )

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_emitter is not None:
            self.event_emitter(event_type, payload)


def register_deep_research_tools(registry: ToolRegistry, engine: DeepResearchEngine) -> None:
    def start_handler(context: Any, invocation: ToolInvocation) -> ToolResult:
        result = engine.start_research(
            session_id=context.snapshot.session.session_id,
            task_id=str(invocation.arguments["task_id"]),
            brief=str(invocation.arguments["brief"]),
            invocation_id=None if "invocation_id" not in invocation.arguments else str(invocation.arguments["invocation_id"]),
            lane_id=invocation.lane_id if "lane_id" not in invocation.arguments else invocation.arguments.get("lane_id"),
            idempotency_key=invocation.arguments.get("idempotency_key"),
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=result.invocation.status is EngineInvocationStatus.SUCCEEDED,
            content=json.dumps(result.dossier.to_dict(), sort_keys=True),
            task_id=result.invocation.task_id,
            lane_id=result.invocation.lane_id,
        )

    def resume_handler(_context: Any, invocation: ToolInvocation) -> ToolResult:
        result = engine.resume_research(
            invocation_id=str(invocation.arguments["invocation_id"]),
            resolution=str(invocation.arguments["resolution"]),
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=result.invocation.status is EngineInvocationStatus.SUCCEEDED,
            content=json.dumps(result.dossier.to_dict(), sort_keys=True),
            task_id=result.invocation.task_id,
            lane_id=result.invocation.lane_id,
        )

    def status_handler(_context: Any, invocation: ToolInvocation) -> ToolResult:
        status = engine.get_research_status(str(invocation.arguments["invocation_id"]))
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(status, sort_keys=True),
        )

    def dossier_handler(_context: Any, invocation: ToolInvocation) -> ToolResult:
        dossier = engine.get_research_dossier(str(invocation.arguments["invocation_id"]))
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(dossier.to_dict(), sort_keys=True),
        )

    registry.register("deep_research.start", start_handler)
    registry.register("deep_research.resume", resume_handler)
    registry.register("deep_research.status", status_handler)
    registry.register("deep_research.dossier", dossier_handler)


__all__ = [
    "DeepResearchEngine",
    "DeepResearchRunner",
    "GraphBackedDeepResearchRunner",
    "NormalizedResearchDossier",
    "ResearchEvidenceItem",
    "ResearchStartResult",
    "register_deep_research_tools",
]
