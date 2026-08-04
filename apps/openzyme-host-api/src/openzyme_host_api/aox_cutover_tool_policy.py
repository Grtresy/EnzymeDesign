from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Literal

from openzyme_core import is_published_report_link
from openzyme_core import is_published_report_status
from openzyme_runtime import AgentStepContext
from openzyme_runtime import ToolInvocation
from openzyme_runtime import ToolResult

from .aox_bundle_finalizer import AoxBundleFinalizationError
from .aox_bundle_finalizer import (
    validate_persisted_aox_finalization_receipt,
)

AOX_CUTOVER_TOOL_PRECONDITION_ID = "aox_finalization_tool_precondition@1"

def _status_value(record: object) -> str:
    status = getattr(record, "status", None)
    return str(getattr(status, "value", status) or "")


def evaluate_aox_source_linked_report(
    repositories: Any,
    *,
    session_id: str,
    research_task_id: str,
    report_task_id: str,
    reporter_evidence_refs: tuple[str, ...],
) -> dict[str, object]:
    """Resolve the durable report -> task finish -> PubMed evidence chain.

    Report prose remains agent-authored. This evaluator constrains only the
    product facts that make ``source-linked`` auditable without parsing prose:
    one published report/draft/content triple, one canonical PubMed artifact
    adopted by the research task, and reporter finish refs that bind both.
    """

    blocker_codes: list[str] = []
    published_reports = [
        report
        for report in repositories.reports.list_by_session(session_id)
        if is_published_report_status(report)
    ]
    published_drafts = [
        draft
        for draft in repositories.report_drafts.list_by_session(session_id)
        if _status_value(draft) == "published"
    ]
    report = published_reports[0] if len(published_reports) == 1 else None
    draft = published_drafts[0] if len(published_drafts) == 1 else None
    if report is None:
        blocker_codes.append("published_report_cardinality_invalid")
    if draft is None:
        blocker_codes.append("published_draft_cardinality_invalid")

    if not (
        report is not None
        and draft is not None
        and is_published_report_link(
            report,
            draft,
            task_id=report_task_id,
        )
    ):
        blocker_codes.append("published_report_link_invalid")
    content_ref = "" if draft is None else str(getattr(draft, "content_ref", "") or "")
    content_document = (
        None if not content_ref else repositories.engine_documents.get(content_ref)
    )
    content_payload = (
        {}
        if content_document is None
        else dict(getattr(content_document, "payload", None) or {})
    )
    if (
        content_document is None
        or getattr(content_document, "document_kind", None) != "report_draft_content"
        or getattr(content_document, "session_id", session_id) != session_id
        or not str(content_payload.get("markdown") or "").strip()
    ):
        blocker_codes.append("published_report_content_invalid")
    if report is not None and getattr(report, "artifact_id", None) is not None:
        blocker_codes.append("published_report_artifact_invalid")

    research_finish_documents = []
    for document in repositories.engine_documents.list_by_session(session_id):
        if getattr(document, "document_kind", None) != "task_finish":
            continue
        payload = dict(getattr(document, "payload", None) or {})
        if (
            payload.get("task_id") == research_task_id
            and payload.get("status") == "completed"
        ):
            research_finish_documents.append(document)
    research_finish = (
        research_finish_documents[0] if len(research_finish_documents) == 1 else None
    )
    if research_finish is None:
        blocker_codes.append("research_finish_cardinality_invalid")
    research_evidence_refs = tuple(
        str(item)
        for item in (
            []
            if research_finish is None
            else dict(getattr(research_finish, "payload", None) or {}).get(
                "evidence_refs"
            )
            or []
        )
    )
    primary_artifact_refs = tuple(
        item
        for item in research_evidence_refs
        if item.startswith("artifact:") and len(item) > len("artifact:")
    )
    primary_artifact_ref = (
        primary_artifact_refs[0] if len(primary_artifact_refs) == 1 else ""
    )
    if len(primary_artifact_refs) != 1 or len(research_evidence_refs) != 1:
        blocker_codes.append("primary_pubmed_receipt_invalid")
    primary_artifact_id = primary_artifact_ref.removeprefix("artifact:")
    primary_artifact = (
        None
        if not primary_artifact_id
        else repositories.artifacts.get(primary_artifact_id)
    )
    metadata = (
        {}
        if primary_artifact is None
        else dict(getattr(primary_artifact, "metadata", None) or {})
    )
    primary_artifact_digest = str(
        metadata.get("content_digest") or metadata.get("sealed_digest") or ""
    )
    if (
        primary_artifact is None
        or getattr(primary_artifact, "session_id", None) != session_id
        or getattr(primary_artifact, "task_id", None) != research_task_id
        or metadata.get("provider") != "pubmed"
        or metadata.get("cutover_eligible") is not True
        or not primary_artifact_digest.startswith("sha256:")
        or len(primary_artifact_digest) != 71
        or any(
            character not in "0123456789abcdef"
            for character in primary_artifact_digest[7:]
        )
    ):
        blocker_codes.append("primary_pubmed_artifact_invalid")

    source_refs = [
        source_ref
        for source_ref in repositories.research_source_refs.list_by_session(session_id)
        if getattr(source_ref, "evidence_artifact_id", None) == primary_artifact_id
    ]
    if not source_refs or any(
        getattr(source_ref, "provider", None) != "pubmed"
        or not str(getattr(source_ref, "pmid", "") or "").isdigit()
        or getattr(source_ref, "task_id", None) != research_task_id
        or not str(getattr(source_ref, "source_ref_id", "") or "").strip()
        for source_ref in source_refs
    ):
        blocker_codes.append("primary_pubmed_source_refs_invalid")
    source_ref_ids = tuple(
        sorted(str(getattr(source_ref, "source_ref_id")) for source_ref in source_refs)
    )

    report_id = "" if report is None else str(getattr(report, "report_id", "") or "")
    report_ref = f"report:{report_id}" if report_id else ""
    required_evidence_refs = tuple(
        item for item in (report_ref, primary_artifact_ref) if item
    )
    missing_evidence_refs = tuple(
        item for item in required_evidence_refs if item not in reporter_evidence_refs
    )
    if len(required_evidence_refs) != 2 or missing_evidence_refs:
        blocker_codes.append("report_finish_source_refs_missing")

    unique_blockers = tuple(dict.fromkeys(blocker_codes))
    return {
        "ready": not unique_blockers,
        "blocker_codes": unique_blockers,
        "report_id": report_id or None,
        "draft_id": (
            None if draft is None else str(getattr(draft, "draft_id", "") or "") or None
        ),
        "content_ref": content_ref or None,
        "primary_artifact_id": primary_artifact_id or None,
        "primary_artifact_digest": (primary_artifact_digest or None),
        "source_ref_ids": source_ref_ids,
        "required_evidence_refs": required_evidence_refs,
        "observed_evidence_refs": reporter_evidence_refs,
        "missing_evidence_refs": missing_evidence_refs,
    }


def _rejection(
    invocation: ToolInvocation,
    *,
    code: str,
    summary: str,
    hint: str,
    details: dict[str, Any],
) -> ToolResult:
    public_details = {
        "policy_id": AOX_CUTOVER_TOOL_PRECONDITION_ID,
        "precondition_rejected": True,
        "dispatched": False,
        "effect_certainty": "no_effect",
        "retry_eligibility": "same_phase_safe",
        **details,
    }
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=False,
        content=json.dumps(
            {
                "error_code": code,
                "summary": summary,
                "hint": hint,
                "details": public_details,
            },
            sort_keys=True,
        ),
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        status="precondition_failed",
        summary=summary,
        error_code=code,
        hint=hint,
        details=public_details,
    )


@dataclass(frozen=True, slots=True)
class AoxFinalizationToolPrecondition:
    """Guard only receipt-bound terminal handoff for one formal session.

    Task identities remain agent-owned and canonical.  This precondition never
    observes or constrains ``task.create``; it derives the exact three-task set
    from Host state only when a positive run attempts scientific/report closure.
    """

    session_id: str
    attempt_kind: Literal["positive", "fault"]

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("formal cutover session_id must be non-empty")
        if self.attempt_kind not in {"positive", "fault"}:
            raise ValueError("formal cutover attempt_kind must be positive or fault")

    def __call__(
        self,
        context: Any,
        step_context: AgentStepContext,
        invocation: ToolInvocation,
    ) -> ToolResult | None:
        if step_context.session_id != self.session_id or self.attempt_kind != "positive":
            return None
        return self._check_finalization_gate(context, invocation)

    def _check_finalization_gate(
        self,
        context: Any,
        invocation: ToolInvocation,
    ) -> ToolResult | None:
        requested_task_id = str(
            invocation.arguments.get("task_id") or invocation.task_id or ""
        )
        requested_status = str(invocation.arguments.get("status") or "")
        requested_task = context.repositories.tasks.get(requested_task_id)
        requested_kind = getattr(requested_task, "kind", None)
        potentially_terminal = invocation.tool_name in {
            "scientific.attempt.close",
            "report.publish",
        } or (
            invocation.tool_name == "task.finish"
            and requested_status == "completed"
            and requested_kind in {"execution", "reporting"}
        ) or (
            invocation.tool_name == "task.delegate" and requested_kind == "reporting"
        )
        if not potentially_terminal:
            return None
        tasks = context.repositories.tasks.list_by_session(self.session_id)
        by_kind = {
            kind: [task.task_id for task in tasks if task.kind == kind]
            for kind in ("research", "execution", "reporting")
        }
        if len(tasks) != 3 or any(len(values) != 1 for values in by_kind.values()):
            return _rejection(
                invocation,
                code="aox_finalization_task_set_invalid",
                summary="AOX finalization requires exactly one task of each role.",
                hint="Repair the agent-owned public task graph before terminal handoff.",
                details={"task_count": len(tasks), "task_ids_by_kind": by_kind},
            )
        execution_task_id, report_task_id = (
            by_kind[kind][0] for kind in ("execution", "reporting")
        )
        requires_receipt = False
        receipt_id: str | None = None
        attempt_id: str | None = None
        selection_id: str | None = None
        evidence_refs: tuple[str, ...] = ()

        if invocation.tool_name == "scientific.attempt.close":
            requires_receipt = True
            receipt_id = str(invocation.arguments.get("finalization_receipt_id") or "")
            attempt_id = str(invocation.arguments.get("attempt_id") or "")
            selection_id = str(invocation.arguments.get("selection_id") or "")
        elif (
            invocation.tool_name == "task.finish"
            and requested_status == "completed"
            and requested_task_id in {execution_task_id, report_task_id}
        ):
            requires_receipt = True
            evidence_refs = tuple(
                str(item) for item in (invocation.arguments.get("evidence_refs") or [])
            )
            finalization_refs = sorted(
                {
                    ref.removeprefix("document:")
                    for ref in evidence_refs
                    if ref.startswith("document:aox_finalization_")
                }
            )
            if len(finalization_refs) > 1:
                return _rejection(
                    invocation,
                    code="aox_finalization_receipt_evidence_ambiguous",
                    summary=(
                        "AOX execution/report completion must cite exactly one "
                        "finalization receipt document."
                    ),
                    hint=(
                        "Include the exact document:<receipt_id> returned by "
                        "the atomic 17-deliverable finalizer."
                    ),
                    details={
                        "task_id": requested_task_id,
                        "observed_finalization_receipt_ids": finalization_refs,
                    },
                )
            if finalization_refs:
                receipt_id = finalization_refs[0]
        elif invocation.tool_name == "task.delegate" and requested_task_id == report_task_id:
            requires_receipt = True
        elif invocation.tool_name == "report.publish":
            requires_receipt = True

        if not requires_receipt:
            return None
        if invocation.tool_name == "scientific.attempt.close" and not all(
            (receipt_id, attempt_id, selection_id)
        ):
            return _rejection(
                invocation,
                code="aox_finalization_receipt_required",
                summary=(
                    "AOX attempt closure requires the exact passed finalization "
                    "receipt id."
                ),
                hint=(
                    "Run the installed atomic 17-deliverable finalizer, then "
                    "retry closure with finalization_receipt_id from its result."
                ),
                details={
                    "execution_task_id": execution_task_id,
                    "requested_attempt_id": attempt_id or None,
                    "requested_selection_id": selection_id or None,
                },
            )
        try:
            payload = validate_persisted_aox_finalization_receipt(
                context.repositories,
                session_id=self.session_id,
                execution_task_id=execution_task_id,
                receipt_id=receipt_id,
                attempt_id=attempt_id,
                selection_id=selection_id,
            )
        except AoxBundleFinalizationError as exc:
            return _rejection(
                invocation,
                code=exc.error_code,
                summary=str(exc),
                hint=exc.hint,
                details={"execution_task_id": execution_task_id, **dict(exc.details)},
            )
        persisted_receipt_id = str(payload["receipt_id"])
        if invocation.tool_name == "task.finish" and (
            f"document:{persisted_receipt_id}" not in evidence_refs
        ):
            return _rejection(
                invocation,
                code="aox_finalization_receipt_evidence_missing",
                summary=(
                    "AOX execution/report completion must cite the exact "
                    "validation receipt document."
                ),
                hint=(
                    "Include document:<receipt_id> in task.finish.evidence_refs "
                    "alongside the task's other exact evidence."
                ),
                details={
                    "task_id": requested_task_id,
                    "required_evidence_ref": f"document:{persisted_receipt_id}",
                    "observed_evidence_refs": list(evidence_refs),
                },
            )
        report_progress = (
            invocation.tool_name == "task.delegate" and requested_task_id == report_task_id
        ) or invocation.tool_name == "report.publish" or (
            invocation.tool_name == "task.finish"
            and requested_task_id == report_task_id
            and requested_status == "completed"
        )
        execution_task = context.repositories.tasks.get(execution_task_id)
        if report_progress and _status_value(execution_task) != "completed":
            return _rejection(
                invocation,
                code="aox_finalization_execution_not_completed",
                summary=(
                    "AOX report handoff requires the receipt-bound execution "
                    "task to be completed first."
                ),
                hint=(
                    "Close the receipt-bound attempt and let the assigned "
                    "executor complete its task with document:<receipt_id>, "
                    "then retry report handoff."
                ),
                details={
                    "execution_task_id": execution_task_id,
                    "execution_task_status": _status_value(execution_task) or None,
                    "receipt_id": persisted_receipt_id,
                },
            )
        return None
