from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Literal

from openzyme_core import is_published_report_link
from openzyme_core import is_published_report_status
from openzyme_runtime import AgentStepContext
from openzyme_runtime import ToolInvocation
from openzyme_runtime import ToolResult


AOX_CUTOVER_TOOL_PRECONDITION_ID = "aox_cutover_formal_tool_precondition@5"
AOX_RESEARCH_TASK_ID = "aox_research_pubmed_evidence"
AOX_REPORT_TASK_ID = "aox_final_source_linked_report"

_CLOSURE_STAGE_ALLOWED_TOOLS = frozenset(
    {
        "artifact.diff_text",
        "artifact.get",
        "artifact.list",
        "artifact.preview",
        "artifact.range",
        "artifact.read_text",
        "deep_research.dossier",
        "deep_research.status",
        "docs.read",
        "docs.search",
        "execution.pipeline.status",
        "failure.get",
        "lane.bind_task",
        "lane.create",
        "lane.list",
        "memory.compact",
        "protocol.send",
        "protocol.thread",
        "report.publish",
        "report_draft.get",
        "report_draft.update",
        "sandbox.file.list",
        "sandbox.file.read",
        "sandbox.workspace.status",
        "scientific.attempt.close",
        "scientific.attempt.inspect",
        "skill.load",
        "task.create",
        "task.delegate",
        "task.finish",
        "task.get",
        "task.list",
        "task.next",
        "task.update",
        "world.inspect",
    }
)


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
    require_diagnostic_source_copy: bool = False,
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
    source_copy = metadata.get("diagnostic_source_copy")
    source_copy_valid = (
        isinstance(source_copy, dict)
        and source_copy.get("source_artifact_id") == primary_artifact_id
        and str(source_copy.get("source_manifest_digest") or "").startswith("sha256:")
        and source_copy.get("formal_adoption_eligible") is False
        and source_copy.get("new_effect") is False
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
        or (require_diagnostic_source_copy and not source_copy_valid)
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
class AoxCutoverFormalToolPrecondition:
    """Fail-closed runtime guard for one authority-bound formal session.

    This guard does not choose task strategy or scientific operations. It
    presents the pinned task identity, sealed-operation-universe, and durable
    source-linked reporting constraints. Canonical scientific closure ownership
    and lifecycle ordering are enforced by Core rather than duplicated here.
    """

    session_id: str
    execution_task_id: str
    attempt_kind: Literal["positive", "fault"]
    research_task_id: str = AOX_RESEARCH_TASK_ID
    report_task_id: str = AOX_REPORT_TASK_ID
    sealed_operation_universe: bool = False

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("formal cutover session_id must be non-empty")
        if not all(
            task_id.strip()
            for task_id in (
                self.research_task_id,
                self.execution_task_id,
                self.report_task_id,
            )
        ):
            raise ValueError("formal cutover task ids must be non-empty")
        if (
            len(
                {
                    self.research_task_id,
                    self.execution_task_id,
                    self.report_task_id,
                }
            )
            != 3
        ):
            raise ValueError("formal cutover execution task id must be role-distinct")
        if self.attempt_kind not in {"positive", "fault"}:
            raise ValueError("formal cutover attempt_kind must be positive or fault")

    @property
    def expected_task_contracts(
        self,
    ) -> dict[str, tuple[str, str]]:
        return {
            self.research_task_id: ("research", "researcher"),
            self.execution_task_id: ("execution", "executor"),
            self.report_task_id: ("reporting", "reporter"),
        }

    def __call__(
        self,
        context: Any,
        step_context: AgentStepContext,
        invocation: ToolInvocation,
    ) -> ToolResult | None:
        if step_context.session_id != self.session_id:
            return None
        if (
            self.sealed_operation_universe
            and invocation.tool_name not in _CLOSURE_STAGE_ALLOWED_TOOLS
        ):
            return _rejection(
                invocation,
                code="aox_closure_stage_operation_universe_sealed",
                summary=(
                    "The closure-stage diagnostic rejected a new scientific "
                    "or sandbox mutation because the restored operation "
                    "universe is sealed."
                ),
                hint=(
                    "Use the existing sealed artifacts and selection. Complete "
                    "the scientific lifecycle and task handoff, then publish "
                    "the report without starting new science."
                ),
                details={
                    "tool_name": invocation.tool_name,
                    "operation_universe_sealed": True,
                },
            )
        if invocation.tool_name == "task.create":
            return self._check_task_create(context, invocation)
        if invocation.tool_name == "task.finish":
            return self._check_task_finish(
                context,
                step_context,
                invocation,
            )
        return None

    def _check_task_finish(
        self,
        context: Any,
        step_context: AgentStepContext,
        invocation: ToolInvocation,
    ) -> ToolResult | None:
        """Require the closure-stage reporting exit to bind canonical sources."""

        requested_task_id = str(
            invocation.arguments.get("task_id") or invocation.task_id or ""
        )
        requested_status = str(invocation.arguments.get("status") or "")
        if (
            self.sealed_operation_universe
            and self.attempt_kind == "positive"
            and requested_task_id == self.report_task_id
            and requested_status == "completed"
        ):
            report_task = context.repositories.tasks.get(self.report_task_id)
            assigned_ref = str(getattr(report_task, "assigned_ref", "") or "")
            if (
                step_context.actor_kind != "teammate"
                or not assigned_ref
                or assigned_ref != step_context.agent_id
            ):
                return _rejection(
                    invocation,
                    code="aox_closure_stage_report_finish_actor_invalid",
                    summary=(
                        "The closure-stage reporting task may be completed only "
                        "by its assigned reporter."
                    ),
                    hint=(
                        "Let the assigned reporter publish the source-linked "
                        "report and issue its own task.finish receipt."
                    ),
                    details={
                        "task_id": self.report_task_id,
                        "expected_finished_by": assigned_ref or None,
                        "observed_finished_by": step_context.agent_id,
                    },
                )
            evaluation = evaluate_aox_source_linked_report(
                context.repositories,
                session_id=self.session_id,
                research_task_id=self.research_task_id,
                report_task_id=self.report_task_id,
                reporter_evidence_refs=tuple(
                    str(item)
                    for item in (invocation.arguments.get("evidence_refs") or [])
                ),
                require_diagnostic_source_copy=True,
            )
            if evaluation["ready"] is not True:
                return _rejection(
                    invocation,
                    code=("aox_closure_stage_report_source_link_invalid"),
                    summary=(
                        "The closure-stage reporter cannot finish because the "
                        "published report is not durably linked to the canonical "
                        "PubMed source artifact."
                    ),
                    hint=(
                        "Publish one non-empty report draft, then finish with "
                        "both exact refs from required_evidence_refs. These refs "
                        "bind the published report and restored PubMed source "
                        "without creating new science."
                    ),
                    details={
                        "task_id": self.report_task_id,
                        "blocker_codes": list(evaluation["blocker_codes"]),
                        "required_evidence_refs": list(
                            evaluation["required_evidence_refs"]
                        ),
                        "observed_evidence_refs": list(
                            evaluation["observed_evidence_refs"]
                        ),
                        "missing_evidence_refs": list(
                            evaluation["missing_evidence_refs"]
                        ),
                    },
                )
        return None

    def _check_task_create(
        self,
        context: Any,
        invocation: ToolInvocation,
    ) -> ToolResult | None:
        expected = self.expected_task_contracts
        raw_task_id = invocation.arguments.get("task_id")
        task_id = raw_task_id if isinstance(raw_task_id, str) else ""
        if task_id not in expected:
            return _rejection(
                invocation,
                code="aox_cutover_task_set_violation",
                summary=(
                    "AOX cutover task creation was rejected because the task "
                    "id is outside the exact authority-bound task set."
                ),
                hint=(
                    "Call task.list, then create only a missing task using one "
                    "of expected_task_ids; advance an existing member instead "
                    "of creating a suffixed or replacement task."
                ),
                details={
                    "requested_task_id": task_id or None,
                    "expected_task_ids": sorted(expected),
                },
            )
        expected_kind, _ = expected[task_id]
        requested_kind = str(invocation.arguments.get("kind") or "general")
        if requested_kind != expected_kind:
            return _rejection(
                invocation,
                code="aox_cutover_task_kind_violation",
                summary=(
                    "AOX cutover task creation was rejected because the "
                    "canonical task id has the wrong task kind."
                ),
                hint=(
                    f"Create {task_id!r} with kind={expected_kind!r}; do not "
                    "change its role identity."
                ),
                details={
                    "task_id": task_id,
                    "requested_kind": requested_kind,
                    "expected_kind": expected_kind,
                },
            )
        if context.repositories.tasks.get(task_id) is not None:
            return _rejection(
                invocation,
                code="aox_cutover_task_already_exists",
                summary=(
                    "AOX cutover task creation was rejected because that "
                    "canonical task already exists."
                ),
                hint=(
                    "Use task.get/task.update/task.delegate for the existing "
                    "canonical task; do not create a replacement."
                ),
                details={"task_id": task_id},
            )
        return None


__all__ = [
    "AOX_CUTOVER_TOOL_PRECONDITION_ID",
    "AOX_REPORT_TASK_ID",
    "AOX_RESEARCH_TASK_ID",
    "AoxCutoverFormalToolPrecondition",
    "evaluate_aox_source_linked_report",
]
