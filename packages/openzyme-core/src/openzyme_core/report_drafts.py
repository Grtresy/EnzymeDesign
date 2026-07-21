from __future__ import annotations

import json
from uuid import uuid4

from openzyme_domain import SessionReportDraftRecord
from openzyme_domain import SessionReportDraftStatus
from openzyme_domain import SessionReportRecord
from openzyme_domain import SessionReportStatus
from openzyme_domain.control_plane import utc_now_iso

from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .repositories import EngineDocumentRecord


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _persist_draft_content(context: SessionRuntimeContext, *, session_id: str, markdown: str) -> str:
    document_id = _new_id("doc")
    now = utc_now_iso()
    context.repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id=document_id,
            session_id=session_id,
            invocation_id=None,
            document_kind="report_draft_content",
            payload={"markdown": markdown},
            created_at=now,
            updated_at=now,
        )
    )
    return document_id


def register_report_draft_tools(registry: ToolRegistry) -> None:
    def get_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        session_id = context.snapshot.session.session_id
        draft_id = invocation.arguments.get("draft_id")
        task_id = invocation.arguments.get("task_id")
        draft = None
        if draft_id is not None:
            draft = context.repositories.report_drafts.get(str(draft_id))
        elif task_id is not None:
            draft = context.repositories.report_drafts.get_by_task(session_id, str(task_id))
        if draft is None:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content="report draft does not exist",
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
            )
        payload = {"draft": draft.to_dict()}
        if draft.content_ref is not None:
            document = context.repositories.engine_documents.get(draft.content_ref)
            if document is not None:
                payload["content"] = document.payload
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            task_id=draft.task_id,
            lane_id=invocation.lane_id,
        )

    def update_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        session_id = context.snapshot.session.session_id
        context.repositories.assert_report_publication_authority(
            session_id=session_id
        )
        task_id = str(invocation.arguments.get("task_id") or invocation.task_id or "")
        if not task_id:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content="report_draft.update requires task_id",
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
            )
        existing = context.repositories.report_drafts.get_by_task(session_id, task_id)
        now = utc_now_iso()
        markdown = str(invocation.arguments.get("markdown") or "")
        content_ref = existing.content_ref if existing is not None else None
        if markdown:
            content_ref = _persist_draft_content(context, session_id=session_id, markdown=markdown)
        draft = SessionReportDraftRecord(
            draft_id=existing.draft_id if existing is not None else _new_id("draft"),
            session_id=session_id,
            task_id=task_id,
            owner_agent_id=str(
                invocation.arguments.get("owner_agent_id")
                or invocation.arguments.get("agent_id")
                or (None if existing is None else existing.owner_agent_id)
                or ""
            ),
            status=SessionReportDraftStatus(str(invocation.arguments.get("status") or (existing.status.value if existing is not None else SessionReportDraftStatus.DRAFT.value))),
            title=str(invocation.arguments.get("title") or (existing.title if existing is not None else "Report draft")),
            summary=str(invocation.arguments.get("summary") or (existing.summary if existing is not None else "")),
            content_ref=content_ref,
            published_report_id=existing.published_report_id if existing is not None else None,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        owner_agent_id = draft.owner_agent_id or None
        draft = SessionReportDraftRecord(
            draft_id=draft.draft_id,
            session_id=draft.session_id,
            task_id=draft.task_id,
            owner_agent_id=owner_agent_id,
            status=draft.status,
            title=draft.title,
            summary=draft.summary,
            content_ref=draft.content_ref,
            published_report_id=draft.published_report_id,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
        )
        context.repositories.report_drafts.save(draft)
        context.emit("report_draft.updated", draft.to_dict())
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(draft.to_dict(), sort_keys=True),
            task_id=draft.task_id,
            lane_id=invocation.lane_id,
        )

    def publish_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        session_id = context.snapshot.session.session_id
        context.repositories.assert_report_publication_authority(
            session_id=session_id
        )
        draft_id = invocation.arguments.get("draft_id")
        task_id = invocation.arguments.get("task_id")
        draft = None
        if draft_id is not None:
            draft = context.repositories.report_drafts.get(str(draft_id))
        elif task_id is not None:
            draft = context.repositories.report_drafts.get_by_task(session_id, str(task_id))
        if draft is None:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content="report draft does not exist",
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
            )
        task = None if draft.task_id is None else context.repositories.tasks.get(draft.task_id)
        report_id = str(invocation.arguments.get("report_id") or draft.published_report_id or _new_id("report"))
        now = utc_now_iso()
        report = SessionReportRecord(
            report_id=report_id,
            session_id=session_id,
            task_id=draft.task_id,
            lane_id=None if task is None else task.lane_id,
            invocation_id=None,
            run_id=None,
            artifact_id=None,
            status=SessionReportStatus(str(invocation.arguments.get("status") or SessionReportStatus.READY.value)),
            title=str(invocation.arguments.get("title") or draft.title),
            summary=str(invocation.arguments.get("summary") or draft.summary),
            stage_summary=str(invocation.arguments.get("stage_summary") or draft.summary),
            created_at=(
                now
                if draft.published_report_id is None or context.repositories.reports.get(report_id) is None
                else context.repositories.reports.get(report_id).created_at
            ),
            updated_at=now,
        )
        context.repositories.reports.save(report)
        updated_draft = SessionReportDraftRecord(
            draft_id=draft.draft_id,
            session_id=draft.session_id,
            task_id=draft.task_id,
            owner_agent_id=draft.owner_agent_id,
            status=SessionReportDraftStatus.PUBLISHED,
            title=draft.title,
            summary=draft.summary,
            content_ref=draft.content_ref,
            published_report_id=report.report_id,
            created_at=draft.created_at,
            updated_at=now,
        )
        context.repositories.report_drafts.save(updated_draft)
        context.emit("report_draft.updated", updated_draft.to_dict())
        context.emit("report.generated", report.to_dict())
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps({"draft": updated_draft.to_dict(), "report": report.to_dict()}, sort_keys=True),
            task_id=report.task_id,
            lane_id=report.lane_id,
        )

    registry.register("report_draft.get", get_handler)
    registry.register("report_draft.update", update_handler)
    registry.register("report.publish", publish_handler)


__all__ = ["register_report_draft_tools"]
