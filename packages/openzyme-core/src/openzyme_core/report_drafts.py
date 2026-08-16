from __future__ import annotations

import json
from uuid import uuid4

from openzyme_domain import RevisionPathRef
from openzyme_domain import SessionReportDraftRecord
from openzyme_domain import SessionReportDraftStatus
from openzyme_domain import SessionReportRecord
from openzyme_domain import SessionReportStatus
from openzyme_domain import TaskEvidenceKind
from openzyme_domain import TaskEvidenceRef
from openzyme_domain.control_plane import utc_now_iso

from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .revision_path_handoffs import RevisionPathHandoffError
from .revision_path_handoffs import RevisionPathReferenceService
from .revision_path_handoffs import report_evidence_ref


_FORBIDDEN_BODY_ARGUMENTS = frozenset(
    {"markdown", "content", "body", "bytes", "artifact_id", "path", "branch", "url"}
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _error(
    invocation: ToolInvocation,
    *,
    code: str,
    message: str,
) -> ToolResult:
    payload = {
        "error_code": code,
        "message": message,
        "retry_performed": False,
        "fallback_performed": False,
        "workspace_publish_performed": False,
    }
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=False,
        content=json.dumps(payload, sort_keys=True),
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        status=code,
        summary=message,
        error_code=code,
        details=payload,
    )


def _parse_content_ref(
    context: SessionRuntimeContext,
    value: object,
    *,
    owner_agent_id: str,
) -> RevisionPathRef:
    if not isinstance(value, dict):
        raise RevisionPathHandoffError(
            "content_ref must be a complete RevisionPathRef@1 object"
        )
    ref = RevisionPathRef.from_dict(value)
    service = RevisionPathReferenceService(context.repositories)
    service.require_report_file(
        ref,
        project_id=context.snapshot.session.project_id,
        session_id=context.snapshot.session.session_id,
        owner_agent_id=owner_agent_id,
    )
    return context.repositories.revision_path_handoffs.add_ref(ref)


def _project_draft(context: SessionRuntimeContext, draft: SessionReportDraftRecord) -> dict[str, object]:
    payload: dict[str, object] = {"draft": draft.to_dict()}
    if draft.content_ref is not None:
        ref = context.repositories.revision_path_handoffs.get_ref(draft.content_ref)
        if ref is None:
            raise RevisionPathHandoffError(
                "report draft content ref does not resolve to canonical storage"
            )
        payload["content_reference"] = ref.to_dict()
    payload["content_bytes_in_control_plane"] = False
    payload["workspace_publication_required_before_report_publication"] = True
    return payload


def register_report_draft_tools(registry: ToolRegistry) -> None:
    def get_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        session_id = context.snapshot.session.session_id
        draft_id = invocation.arguments.get("draft_id")
        task_id = invocation.arguments.get("task_id")
        draft = None
        if draft_id is not None:
            draft = context.repositories.report_drafts.get(str(draft_id))
        elif task_id is not None:
            draft = context.repositories.report_drafts.get_by_task(
                session_id,
                str(task_id),
            )
        if draft is None or draft.session_id != session_id:
            return _error(
                invocation,
                code="report_draft_not_found",
                message="report draft does not exist in this session",
            )
        try:
            payload = _project_draft(context, draft)
        except RevisionPathHandoffError as exc:
            return _error(
                invocation,
                code=exc.error_code,
                message=str(exc),
            )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            task_id=draft.task_id,
            lane_id=invocation.lane_id,
        )

    def update_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        forbidden = sorted(_FORBIDDEN_BODY_ARGUMENTS.intersection(invocation.arguments))
        if forbidden:
            return _error(
                invocation,
                code="report_body_inline_forbidden",
                message=(
                    "report draft body must be edited in the reporter Git workspace; "
                    f"forbidden control-plane fields: {', '.join(forbidden)}"
                ),
            )
        session_id = context.snapshot.session.session_id
        context.repositories.assert_report_publication_authority(session_id=session_id)
        task_id = str(
            invocation.arguments.get("task_id") or invocation.task_id or ""
        )
        if not task_id:
            return _error(
                invocation,
                code="report_task_required",
                message="report_draft.update requires task_id",
            )
        task = context.repositories.tasks.get(task_id)
        if task is None or task.session_id != session_id:
            return _error(
                invocation,
                code="report_task_invalid",
                message="report draft task does not belong to this session",
            )
        existing = context.repositories.report_drafts.get_by_task(session_id, task_id)
        owner_agent_id = str(
            invocation.arguments.get("owner_agent_id")
            or (None if existing is None else existing.owner_agent_id)
            or context.agent_id
            or ""
        )
        if context.agent_id is None or context.agent_id != owner_agent_id:
            return _error(
                invocation,
                code="report_owner_invalid",
                message="report draft owner must be the current canonical reporter agent",
            )
        content_ref_id = None if existing is None else existing.content_ref
        raw_content_ref = invocation.arguments.get("content_ref")
        if raw_content_ref is not None:
            try:
                content_ref_id = _parse_content_ref(
                    context,
                    raw_content_ref,
                    owner_agent_id=owner_agent_id,
                ).ref_id
            except (RevisionPathHandoffError, TypeError, ValueError) as exc:
                return _error(
                    invocation,
                    code="report_content_ref_invalid",
                    message=str(exc),
                )
        requested_status = str(
            invocation.arguments.get("status")
            or (
                existing.status.value
                if existing is not None
                else SessionReportDraftStatus.DRAFT.value
            )
        )
        if requested_status == SessionReportDraftStatus.PUBLISHED.value:
            return _error(
                invocation,
                code="report_publish_action_required",
                message="only report.publish may place a report draft in published state",
            )
        published_report_id = (
            existing.published_report_id if existing is not None else None
        )
        if existing is not None and existing.status is SessionReportDraftStatus.PUBLISHED:
            if (
                requested_status != SessionReportDraftStatus.DRAFT.value
                or raw_content_ref is None
                or content_ref_id == existing.content_ref
            ):
                return _error(
                    invocation,
                    code="report_revision_requires_new_draft_file",
                    message=(
                        "revising a published report requires explicit draft status "
                        "and a different published RevisionPathRef"
                    ),
                )
            published_report_id = None
        now = utc_now_iso()
        draft = SessionReportDraftRecord(
            draft_id=(existing.draft_id if existing is not None else _new_id("draft")),
            session_id=session_id,
            task_id=task_id,
            owner_agent_id=owner_agent_id,
            status=SessionReportDraftStatus(requested_status),
            title=str(
                invocation.arguments.get("title")
                or (existing.title if existing is not None else "Report draft")
            ),
            summary=str(
                invocation.arguments.get("summary")
                or (existing.summary if existing is not None else "")
            ),
            content_ref=content_ref_id,
            published_report_id=published_report_id,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        context.repositories.report_drafts.save(draft)
        projection = _project_draft(context, draft)
        context.emit("report_draft.updated", projection)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(projection, sort_keys=True),
            task_id=draft.task_id,
            lane_id=invocation.lane_id,
        )

    def publish_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        if _FORBIDDEN_BODY_ARGUMENTS.intersection(invocation.arguments):
            return _error(
                invocation,
                code="report_body_inline_forbidden",
                message="report.publish accepts only an exact published RevisionPathRef body",
            )
        session_id = context.snapshot.session.session_id
        context.repositories.assert_report_publication_authority(session_id=session_id)
        draft_id = invocation.arguments.get("draft_id")
        task_id = invocation.arguments.get("task_id")
        draft = None
        if draft_id is not None:
            draft = context.repositories.report_drafts.get(str(draft_id))
        elif task_id is not None:
            draft = context.repositories.report_drafts.get_by_task(
                session_id,
                str(task_id),
            )
        if draft is None or draft.session_id != session_id:
            return _error(
                invocation,
                code="report_draft_not_found",
                message="report draft does not exist in this session",
            )
        owner_agent_id = draft.owner_agent_id or ""
        if context.agent_id is None or context.agent_id != owner_agent_id:
            return _error(
                invocation,
                code="report_owner_invalid",
                message="only the canonical reporter owner can publish this report",
            )
        raw_content_ref = invocation.arguments.get("content_ref")
        if raw_content_ref is None:
            return _error(
                invocation,
                code="report_content_ref_required",
                message="report.publish requires a complete published RevisionPathRef@1",
            )
        try:
            content_ref = _parse_content_ref(
                context,
                raw_content_ref,
                owner_agent_id=owner_agent_id,
            )
        except (RevisionPathHandoffError, TypeError, ValueError) as exc:
            return _error(
                invocation,
                code="report_content_ref_invalid",
                message=str(exc),
            )
        if draft.content_ref is not None and draft.content_ref != content_ref.ref_id:
            return _error(
                invocation,
                code="report_content_ref_drift",
                message="report.publish content ref differs from the draft's exact published ref",
            )
        predecessor_id = invocation.arguments.get("supersedes_report_id")
        predecessor = (
            None
            if predecessor_id is None
            else context.repositories.reports.get(str(predecessor_id))
        )
        if predecessor_id is not None and (
            predecessor is None
            or predecessor.session_id != session_id
            or predecessor.task_id != draft.task_id
        ):
            return _error(
                invocation,
                code="report_supersession_invalid",
                message="superseded report does not belong to this report task",
            )
        prior_reports = [
            item
            for item in context.repositories.reports.list_by_session(session_id)
            if item.task_id == draft.task_id
        ]
        latest_report = (
            None
            if not prior_reports
            else max(
                prior_reports,
                key=lambda item: (item.report_version, item.created_at, item.report_id),
            )
        )
        if latest_report is not None and predecessor is None:
            return _error(
                invocation,
                code="report_supersession_required",
                message="a report correction must explicitly supersede the latest report",
            )
        if predecessor is not None and (
            latest_report is None or predecessor.report_id != latest_report.report_id
        ):
            return _error(
                invocation,
                code="report_supersession_stale",
                message="a report correction must supersede the latest report version",
            )
        report_id = str(invocation.arguments.get("report_id") or _new_id("report"))
        if predecessor is not None and report_id == predecessor.report_id:
            return _error(
                invocation,
                code="report_supersession_invalid",
                message="report correction must create a new report identity",
            )
        if context.repositories.reports.get(report_id) is not None:
            return _error(
                invocation,
                code="report_id_already_exists",
                message="report publication is immutable; use a new report_id for correction",
            )
        task = (
            None
            if draft.task_id is None
            else context.repositories.tasks.get(draft.task_id)
        )
        requested_report_status = str(
            invocation.arguments.get("status") or SessionReportStatus.READY.value
        )
        if requested_report_status not in {
            SessionReportStatus.READY.value,
            SessionReportStatus.PUBLISHED.value,
        }:
            return _error(
                invocation,
                code="report_publish_status_invalid",
                message="report.publish accepts only ready or published business status",
            )
        now = utc_now_iso()
        report = SessionReportRecord(
            report_id=report_id,
            session_id=session_id,
            task_id=draft.task_id,
            lane_id=None if task is None else task.lane_id,
            invocation_id=None,
            run_id=None,
            artifact_id=None,
            status=SessionReportStatus(requested_report_status),
            title=str(invocation.arguments.get("title") or draft.title),
            summary=str(invocation.arguments.get("summary") or draft.summary),
            stage_summary=str(
                invocation.arguments.get("stage_summary") or draft.summary
            ),
            created_at=now,
            updated_at=now,
            content_ref_id=content_ref.ref_id,
            report_version=(1 if predecessor is None else predecessor.report_version + 1),
            supersedes_report_id=(
                None if predecessor is None else predecessor.report_id
            ),
        )
        updated_draft = SessionReportDraftRecord(
            draft_id=draft.draft_id,
            session_id=draft.session_id,
            task_id=draft.task_id,
            owner_agent_id=draft.owner_agent_id,
            status=SessionReportDraftStatus.PUBLISHED,
            title=draft.title,
            summary=draft.summary,
            content_ref=content_ref.ref_id,
            published_report_id=report.report_id,
            created_at=draft.created_at,
            updated_at=now,
        )
        with context.repositories.atomic(prefix="report_file_publication"):
            RevisionPathReferenceService(context.repositories).require_report_file(
                content_ref,
                project_id=context.snapshot.session.project_id,
                session_id=session_id,
                owner_agent_id=owner_agent_id,
            )
            context.repositories.reports.save(report)
            context.repositories.report_drafts.save(updated_draft)
        report_projection = report.to_dict()
        report_projection["content_reference"] = content_ref.to_dict()
        report_projection["workspace_publication_performed"] = False
        report_ref = report_evidence_ref(
            report,
            project_id=context.snapshot.session.project_id,
        )
        task_evidence_ref = (
            None
            if report.task_id is None
            else TaskEvidenceRef(
                kind=TaskEvidenceKind.REPORT,
                project_id=context.snapshot.session.project_id,
                session_id=session_id,
                task_id=report.task_id,
                owner_id=report.report_id,
                owner_digest=report_ref.report_digest,
                report_ref=report_ref,
            ).to_dict()
        )
        report_projection["task_evidence_ref"] = task_evidence_ref
        context.emit("report_draft.updated", _project_draft(context, updated_draft))
        context.emit("report.generated", report_projection)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(
                {
                    "draft": updated_draft.to_dict(),
                    "report": report_projection,
                    "task_evidence_ref": task_evidence_ref,
                },
                sort_keys=True,
            ),
            task_id=report.task_id,
            lane_id=report.lane_id,
        )

    registry.register("report_draft.get", get_handler)
    registry.register("report_draft.update", update_handler)
    registry.register("report.publish", publish_handler)


__all__ = ["register_report_draft_tools"]
