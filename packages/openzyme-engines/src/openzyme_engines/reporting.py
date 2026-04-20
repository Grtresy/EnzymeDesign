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
from openzyme_domain import ArtifactKind
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SessionReportRecord
from openzyme_domain import SessionReportStatus
from openzyme_domain.control_plane import utc_now_iso


def _new_document_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


@dataclass(frozen=True, slots=True)
class ReportDraft:
    title: str
    summary: str
    stage_summary: str
    markdown: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "stage_summary": self.stage_summary,
            "markdown": self.markdown,
        }


@dataclass(frozen=True, slots=True)
class ReportStartResult:
    invocation: EngineInvocation
    report: SessionReportRecord
    artifact: SessionArtifactRecord
    document: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation": self.invocation.to_dict(),
            "report": self.report.to_dict(),
            "artifact": self.artifact.to_dict(),
            "document": dict(self.document),
        }


class ReportingRunner(Protocol):
    def generate_report(
        self,
        *,
        session: Any,
        task: Any,
        report_brief: str,
        research_summaries: tuple[Any, ...],
        runs: tuple[Any, ...],
        artifacts: tuple[Any, ...],
        resolution: str | None = None,
    ) -> ReportDraft: ...


@dataclass(slots=True)
class DefaultReportingRunner:
    def generate_report(
        self,
        *,
        session: Any,
        task: Any,
        report_brief: str,
        research_summaries: tuple[Any, ...],
        runs: tuple[Any, ...],
        artifacts: tuple[Any, ...],
        resolution: str | None = None,
    ) -> ReportDraft:
        research_summary = "No research summary available."
        if research_summaries:
            research_summary = research_summaries[-1].summary
        run_summary = "No execution runs available."
        if runs:
            run_summary = runs[-1].summary or f"Latest execution status: {runs[-1].status.value}."
        artifact_summary = ", ".join(artifact.relative_path for artifact in artifacts) or "none"
        title = f"{task.subject} report"
        summary = f"{report_brief} Session objective: {session.objective}".strip()
        stage_summary = f"Research summary: {research_summary} Execution summary: {run_summary}".strip()
        resolution_block = "" if resolution is None else f"\n\nResolution:\n{resolution}"
        markdown = "\n".join(
            [
                f"# {title}",
                "",
                "## Objective",
                session.objective,
                "",
                "## Brief",
                report_brief,
                "",
                "## Research",
                research_summary,
                "",
                "## Execution",
                run_summary,
                "",
                "## Artifacts",
                artifact_summary,
            ]
        ) + resolution_block
        return ReportDraft(
            title=title,
            summary=summary,
            stage_summary=stage_summary,
            markdown=markdown,
        )


@dataclass(slots=True)
class ReportingEngine:
    repositories: Any
    runner: ReportingRunner | None = None
    event_emitter: Any | None = None

    @property
    def descriptor(self) -> EngineDescriptor:
        return EngineDescriptor(
            engine_name="reporting",
            tool_names=(
                "reporting.start",
                "reporting.resume",
                "reporting.status",
                "reporting.document",
            ),
            input_schema={"type": "object", "required": ["task_id", "report_brief"]},
            output_schema={"type": "object", "required": ["report", "artifact"]},
            requires_approval=False,
            supports_background=True,
            idempotency_key_shape="{task_id}:reporting:{nonce}",
            produces_artifact_types=("report",),
            capability_key="reporting",
        )

    def register_tools(self, registry: ToolRegistry) -> None:
        register_reporting_tools(registry, self)

    def start_report(
        self,
        *,
        session_id: str,
        task_id: str,
        report_brief: str,
        invocation_id: str | None = None,
        lane_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ReportStartResult:
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
            idempotency_key=idempotency_key or f"{task_id}:reporting:{uuid4().hex[:8]}",
            started_at=now,
        )
        self.repositories.invocations.save(invocation)
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=input_id,
                session_id=session_id,
                invocation_id=invocation_id,
                document_kind="reporting_input",
                payload={"task_id": task_id, "lane_id": effective_lane_id, "report_brief": report_brief},
                created_at=now,
                updated_at=now,
            )
        )
        self._emit(
            "engine.invocation.started",
            {"invocation_id": invocation_id, "engine_name": self.descriptor.engine_name, "task_id": task_id},
        )
        return self._generate(invocation=invocation, session=session, task=task, report_brief=report_brief, resolution=None)

    def resume_report(self, *, invocation_id: str, resolution: str | None = None) -> ReportStartResult:
        invocation = self._require_invocation(invocation_id)
        session = self._require_session(invocation.session_id)
        task = self._require_task(invocation.session_id, str(invocation.task_id))
        input_payload = self._require_input_payload(invocation)
        report_brief = str(input_payload["report_brief"])
        self._update_input_document(invocation, resolution=resolution)
        running = EngineInvocation(
            invocation_id=invocation.invocation_id,
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            engine_name=invocation.engine_name,
            status=EngineInvocationStatus.RUNNING,
            input_ref=invocation.input_ref,
            output_ref=invocation.output_ref,
            approval_id=None,
            idempotency_key=invocation.idempotency_key,
            started_at=invocation.started_at,
            finished_at=None,
        )
        self.repositories.invocations.save(running)
        self._emit(
            "engine.invocation.updated",
            {"invocation_id": running.invocation_id, "engine_name": running.engine_name, "status": "running"},
        )
        return self._generate(
            invocation=running,
            session=session,
            task=task,
            report_brief=report_brief,
            resolution=resolution,
        )

    def get_report_status(self, invocation_id: str) -> dict[str, Any]:
        invocation = self._require_invocation(invocation_id)
        payload = invocation.to_dict()
        report = self.repositories.reports.get_by_invocation(invocation.session_id, invocation.invocation_id)
        if report is not None:
            payload["report"] = report.to_dict()
        if invocation.output_ref is not None:
            document = self.repositories.engine_documents.get(invocation.output_ref)
            if document is not None:
                payload["output_document"] = document.to_dict()
        return payload

    def get_report_document(self, invocation_id: str) -> dict[str, Any]:
        invocation = self._require_invocation(invocation_id)
        if invocation.output_ref is None:
            raise ValueError(f"invocation {invocation_id!r} does not have an output document")
        document = self.repositories.engine_documents.get(invocation.output_ref)
        if document is None:
            raise ValueError(f"document {invocation.output_ref!r} does not exist")
        return document.to_dict()

    def _generate(
        self,
        *,
        invocation: EngineInvocation,
        session: Any,
        task: Any,
        report_brief: str,
        resolution: str | None,
    ) -> ReportStartResult:
        now = utc_now_iso()
        runner = self.runner or DefaultReportingRunner()
        research_summaries = tuple(self.repositories.research_summaries.list_by_session(invocation.session_id))
        runs = tuple(self.repositories.runs.list_by_task(invocation.session_id, task.task_id))
        artifacts = tuple(self.repositories.artifacts.list_by_task(invocation.session_id, task.task_id))
        draft = runner.generate_report(
            session=session,
            task=task,
            report_brief=report_brief,
            research_summaries=research_summaries,
            runs=runs,
            artifacts=artifacts,
            resolution=resolution,
        )
        output_id = _new_document_id("eng_out")
        document_payload = {
            "report_id": f"report_{invocation.invocation_id}",
            "task_id": task.task_id,
            "lane_id": invocation.lane_id,
            "report_brief": report_brief,
            "resolution": resolution,
            "draft": draft.to_dict(),
        }
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=output_id,
                session_id=invocation.session_id,
                invocation_id=invocation.invocation_id,
                document_kind="report_document",
                payload=document_payload,
                created_at=now,
                updated_at=now,
            )
        )
        artifact = SessionArtifactRecord(
            artifact_id=f"{invocation.invocation_id}:report",
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            invocation_id=invocation.invocation_id,
            run_id=None,
            kind=ArtifactKind.REPORT,
            storage_uri=f"engine://reports/{invocation.invocation_id}.md",
            relative_path=f"{invocation.invocation_id}.md",
            title=draft.title,
            description=draft.summary,
            metadata={"source": "reporting_engine", "document_id": output_id},
            created_at=now,
        )
        self.repositories.artifacts.save(artifact)
        report = SessionReportRecord(
            report_id=f"report_{invocation.invocation_id}",
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            invocation_id=invocation.invocation_id,
            run_id=runs[-1].run_id if runs else None,
            artifact_id=artifact.artifact_id,
            status=SessionReportStatus.READY,
            title=draft.title,
            summary=draft.summary,
            stage_summary=draft.stage_summary,
            created_at=now,
            updated_at=now,
        )
        self.repositories.reports.save(report)
        finalized = EngineInvocation(
            invocation_id=invocation.invocation_id,
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            engine_name=invocation.engine_name,
            status=EngineInvocationStatus.SUCCEEDED,
            input_ref=invocation.input_ref,
            output_ref=output_id,
            approval_id=None,
            idempotency_key=invocation.idempotency_key,
            started_at=invocation.started_at,
            finished_at=now,
        )
        self.repositories.invocations.save(finalized)
        self._emit(
            "report.generated",
            {
                "report_id": report.report_id,
                "task_id": report.task_id,
                "lane_id": report.lane_id,
                "artifact_id": report.artifact_id,
                "status": report.status.value,
            },
        )
        self._emit(
            "engine.invocation.completed",
            {
                "invocation_id": finalized.invocation_id,
                "engine_name": finalized.engine_name,
                "status": finalized.status.value,
            },
        )
        return ReportStartResult(
            invocation=finalized,
            report=report,
            artifact=artifact,
            document=document_payload,
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

    def _update_input_document(self, invocation: EngineInvocation, *, resolution: str | None) -> None:
        if invocation.input_ref is None:
            return
        document = self.repositories.engine_documents.get(invocation.input_ref)
        if document is None:
            return
        payload = dict(document.payload)
        payload["resolution"] = resolution
        self.repositories.engine_documents.save(
            self._document_record(
                document_id=document.document_id,
                session_id=document.session_id,
                invocation_id=str(document.invocation_id),
                document_kind=document.document_kind,
                payload=payload,
                created_at=document.created_at,
                updated_at=utc_now_iso(),
            )
        )

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

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_emitter is not None:
            self.event_emitter(event_type, payload)


def register_reporting_tools(registry: ToolRegistry, engine: ReportingEngine) -> None:
    def start_handler(context: Any, invocation: ToolInvocation) -> ToolResult:
        result = engine.start_report(
            session_id=context.snapshot.session.session_id,
            task_id=str(invocation.arguments["task_id"]),
            report_brief=str(invocation.arguments["report_brief"]),
            invocation_id=None if invocation.arguments.get("invocation_id") is None else str(invocation.arguments["invocation_id"]),
            lane_id=invocation.lane_id if invocation.arguments.get("lane_id") is None else str(invocation.arguments["lane_id"]),
            idempotency_key=None if invocation.arguments.get("idempotency_key") is None else str(invocation.arguments["idempotency_key"]),
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=result.invocation.status is EngineInvocationStatus.SUCCEEDED,
            content=json.dumps(result.to_dict(), sort_keys=True),
            task_id=result.invocation.task_id,
            lane_id=result.invocation.lane_id,
        )

    def resume_handler(_context: Any, invocation: ToolInvocation) -> ToolResult:
        result = engine.resume_report(
            invocation_id=str(invocation.arguments["invocation_id"]),
            resolution=None if invocation.arguments.get("resolution") is None else str(invocation.arguments["resolution"]),
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=result.invocation.status is EngineInvocationStatus.SUCCEEDED,
            content=json.dumps(result.to_dict(), sort_keys=True),
            task_id=result.invocation.task_id,
            lane_id=result.invocation.lane_id,
        )

    def status_handler(_context: Any, invocation: ToolInvocation) -> ToolResult:
        status = engine.get_report_status(str(invocation.arguments["invocation_id"]))
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(status, sort_keys=True),
        )

    def document_handler(_context: Any, invocation: ToolInvocation) -> ToolResult:
        document = engine.get_report_document(str(invocation.arguments["invocation_id"]))
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(document, sort_keys=True),
        )

    registry.register("reporting.start", start_handler)
    registry.register("reporting.resume", resume_handler)
    registry.register("reporting.status", status_handler)
    registry.register("reporting.document", document_handler)


__all__ = [
    "DefaultReportingRunner",
    "ReportDraft",
    "ReportStartResult",
    "ReportingEngine",
    "ReportingRunner",
    "register_reporting_tools",
]
