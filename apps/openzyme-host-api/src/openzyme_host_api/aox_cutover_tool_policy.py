from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Literal

from openzyme_core import ScientificAttemptError
from openzyme_core import ScientificAttemptService
from openzyme_core import is_published_report_link
from openzyme_core import is_published_report_status
from openzyme_runtime import AgentStepContext
from openzyme_runtime import ToolInvocation
from openzyme_runtime import ToolResult


AOX_CUTOVER_TOOL_PRECONDITION_ID = (
    "aox_cutover_formal_tool_precondition@4"
)
AOX_RESEARCH_TASK_ID = "aox_research_pubmed_evidence"
AOX_REPORT_TASK_ID = "aox_final_source_linked_report"

_FAULT_EXECUTION_EXITS = frozenset({"failed", "blocked", "cancelled"})
_FAULT_REPORT_EXITS = frozenset({"failed", "blocked", "cancelled"})
_NONCOMPLETED_TASK_EXITS = frozenset({"failed", "blocked", "cancelled"})
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
    content_ref = (
        ""
        if draft is None
        else str(getattr(draft, "content_ref", "") or "")
    )
    content_document = (
        None
        if not content_ref
        else repositories.engine_documents.get(content_ref)
    )
    content_payload = (
        {}
        if content_document is None
        else dict(getattr(content_document, "payload", None) or {})
    )
    if (
        content_document is None
        or getattr(content_document, "document_kind", None)
        != "report_draft_content"
        or getattr(content_document, "session_id", session_id)
        != session_id
        or not str(content_payload.get("markdown") or "").strip()
    ):
        blocker_codes.append("published_report_content_invalid")
    if (
        report is not None
        and getattr(report, "artifact_id", None) is not None
    ):
        blocker_codes.append("published_report_artifact_invalid")

    research_finish_documents = []
    for document in repositories.engine_documents.list_by_session(
        session_id
    ):
        if getattr(document, "document_kind", None) != "task_finish":
            continue
        payload = dict(getattr(document, "payload", None) or {})
        if (
            payload.get("task_id") == research_task_id
            and payload.get("status") == "completed"
        ):
            research_finish_documents.append(document)
    research_finish = (
        research_finish_documents[0]
        if len(research_finish_documents) == 1
        else None
    )
    if research_finish is None:
        blocker_codes.append("research_finish_cardinality_invalid")
    research_evidence_refs = tuple(
        str(item)
        for item in (
            []
            if research_finish is None
            else dict(
                getattr(research_finish, "payload", None) or {}
            ).get("evidence_refs")
            or []
        )
    )
    primary_artifact_refs = tuple(
        item
        for item in research_evidence_refs
        if item.startswith("artifact:") and len(item) > len("artifact:")
    )
    primary_artifact_ref = (
        primary_artifact_refs[0]
        if len(primary_artifact_refs) == 1
        else ""
    )
    if (
        len(primary_artifact_refs) != 1
        or len(research_evidence_refs) != 1
    ):
        blocker_codes.append("primary_pubmed_receipt_invalid")
    primary_artifact_id = primary_artifact_ref.removeprefix(
        "artifact:"
    )
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
        metadata.get("content_digest")
        or metadata.get("sealed_digest")
        or ""
    )
    source_copy = metadata.get("diagnostic_source_copy")
    source_copy_valid = (
        isinstance(source_copy, dict)
        and source_copy.get("source_artifact_id")
        == primary_artifact_id
        and str(
            source_copy.get("source_manifest_digest") or ""
        ).startswith("sha256:")
        and source_copy.get("formal_adoption_eligible") is False
        and source_copy.get("new_effect") is False
    )
    if (
        primary_artifact is None
        or getattr(primary_artifact, "session_id", None) != session_id
        or getattr(primary_artifact, "task_id", None)
        != research_task_id
        or metadata.get("provider") != "pubmed"
        or metadata.get("cutover_eligible") is not True
        or not primary_artifact_digest.startswith("sha256:")
        or len(primary_artifact_digest) != 71
        or any(
            character not in "0123456789abcdef"
            for character in primary_artifact_digest[7:]
        )
        or (
            require_diagnostic_source_copy
            and not source_copy_valid
        )
    ):
        blocker_codes.append("primary_pubmed_artifact_invalid")

    source_refs = [
        source_ref
        for source_ref in repositories.research_source_refs.list_by_session(
            session_id
        )
        if getattr(source_ref, "evidence_artifact_id", None)
        == primary_artifact_id
    ]
    if (
        not source_refs
        or any(
            getattr(source_ref, "provider", None) != "pubmed"
            or not str(
                getattr(source_ref, "pmid", "") or ""
            ).isdigit()
            or getattr(source_ref, "task_id", None) != research_task_id
            or not str(
                getattr(source_ref, "source_ref_id", "") or ""
            ).strip()
            for source_ref in source_refs
        )
    ):
        blocker_codes.append("primary_pubmed_source_refs_invalid")
    source_ref_ids = tuple(
        sorted(
            str(getattr(source_ref, "source_ref_id"))
            for source_ref in source_refs
        )
    )

    report_id = (
        ""
        if report is None
        else str(getattr(report, "report_id", "") or "")
    )
    report_ref = f"report:{report_id}" if report_id else ""
    required_evidence_refs = tuple(
        item
        for item in (report_ref, primary_artifact_ref)
        if item
    )
    missing_evidence_refs = tuple(
        item
        for item in required_evidence_refs
        if item not in reporter_evidence_refs
    )
    if (
        len(required_evidence_refs) != 2
        or missing_evidence_refs
    ):
        blocker_codes.append("report_finish_source_refs_missing")

    unique_blockers = tuple(dict.fromkeys(blocker_codes))
    return {
        "ready": not unique_blockers,
        "blocker_codes": unique_blockers,
        "report_id": report_id or None,
        "draft_id": (
            None
            if draft is None
            else str(getattr(draft, "draft_id", "") or "") or None
        ),
        "content_ref": content_ref or None,
        "primary_artifact_id": primary_artifact_id or None,
        "primary_artifact_digest": (
            primary_artifact_digest or None
        ),
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
    presents already-pinned cutover constraints at the mutation/conversation
    boundary: the exact three-task topology, the business/report state required
    before closure, the completed execution handoff proved by a canonically
    closure-request-ready positive selection, and the requirement that a
    close-ready master submit its final response together with the explicit
    scientific-attempt close call.
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
            raise ValueError(
                "formal cutover task ids must be non-empty"
            )
        if len(
            {
                self.research_task_id,
                self.execution_task_id,
                self.report_task_id,
            }
        ) != 3:
            raise ValueError(
                "formal cutover execution task id must be role-distinct"
            )
        if self.attempt_kind not in {"positive", "fault"}:
            raise ValueError(
                "formal cutover attempt_kind must be positive or fault"
            )

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
                    "the execution handoff, publish the report, and let the "
                    "resident master request closure without starting new "
                    "science."
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
        if invocation.tool_name == "scientific.attempt.close":
            return self._check_attempt_close(
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
        """Reject a false negative exit after positive execution is ready.

        This is intentionally narrower than generic task lifecycle policy. A
        positive executor remains free to report a genuine blocker whenever its
        current selected chain is not canonically closure-request-ready. Once
        that same evaluator proves the current sealed selection ready, however,
        the durable scientific execution handoff is successful; master-only
        closure is a later lifecycle responsibility.
        """

        requested_task_id = str(
            invocation.arguments.get("task_id")
            or invocation.task_id
            or ""
        )
        requested_status = str(
            invocation.arguments.get("status") or ""
        )
        if (
            self.sealed_operation_universe
            and self.attempt_kind == "positive"
            and requested_task_id == self.report_task_id
            and requested_status == "completed"
        ):
            report_task = context.repositories.tasks.get(
                self.report_task_id
            )
            assigned_ref = str(
                getattr(report_task, "assigned_ref", "") or ""
            )
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
                    for item in (
                        invocation.arguments.get("evidence_refs") or []
                    )
                ),
                require_diagnostic_source_copy=True,
            )
            if evaluation["ready"] is not True:
                return _rejection(
                    invocation,
                    code=(
                        "aox_closure_stage_report_source_link_invalid"
                    ),
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
                        "blocker_codes": list(
                            evaluation["blocker_codes"]
                        ),
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
        if self.attempt_kind != "positive":
            return None
        if (
            requested_task_id != self.execution_task_id
            or requested_status not in _NONCOMPLETED_TASK_EXITS
            or step_context.actor_kind != "teammate"
        ):
            return None

        repositories = context.repositories
        task = repositories.tasks.get(self.execution_task_id)
        if (
            task is None
            or str(getattr(task, "assigned_ref", "") or "")
            != step_context.agent_id
        ):
            return None
        active_attempts = [
            attempt
            for attempt in repositories.scientific_attempts.list_by_session(
                self.session_id
            )
            if _status_value(attempt) == "active"
            and str(getattr(attempt, "task_id", ""))
            == self.execution_task_id
        ]
        if len(active_attempts) != 1:
            return None
        attempt = active_attempts[0]
        attempt_id = str(getattr(attempt, "attempt_id", ""))
        resolved_head = repositories.scientific_selections.resolve_head(
            attempt_id
        )
        if resolved_head is None:
            return None
        selection = getattr(resolved_head, "selection", None)
        raw_selection_state = getattr(selection, "state", "")
        if (
            str(getattr(raw_selection_state, "value", raw_selection_state))
            != "sealed"
        ):
            return None
        try:
            evaluation = ScientificAttemptService(
                repositories,
                workflow_contract_registry=getattr(
                    context,
                    "scientific_workflow_contract_registry",
                    None,
                ),
            ).evaluate_selection(attempt_id=attempt_id)
        except ScientificAttemptError:
            # A policy guard may prevent an exit only when canonical readiness
            # is positively proved. Missing/drifted evaluation facts remain a
            # genuine blocker under the ordinary task lifecycle.
            return None
        if not evaluation.closure_request_ready:
            return None
        return _rejection(
            invocation,
            code="aox_cutover_positive_execution_exit_mismatch",
            summary=(
                "AOX cutover rejected a non-completed positive execution exit "
                "because the executor's current scientific selection is "
                "canonically ready for a closure request."
            ),
            hint=(
                "Treat a teammate scientific.attempt.close actor rejection as "
                "the intended no-effect handoff, not as an unavailable "
                "capability. Finish this execution task completed with the "
                "actual result evidence; the reporter publishes and the resident "
                "master requests closure."
            ),
            details={
                "attempt_id": attempt_id,
                "selection_id": evaluation.selection_id,
                "selection_state": evaluation.selection_state,
                "closure_request_ready": (
                    evaluation.closure_request_ready
                ),
                "closure_finalization_ready": (
                    evaluation.closure_finalization_ready
                ),
                "selection_blocker_codes": list(
                    evaluation.blocker_codes
                ),
                "operation_universe_digest": (
                    evaluation.operation_universe_digest
                ),
                "operation_count": evaluation.operation_count,
                "task_id": self.execution_task_id,
                "requested_status": requested_status,
                "required_status": "completed",
                "closure_actor_kind": "master",
                "close_actor_rejection_effect_certainty": "no_effect",
            },
        )

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
        requested_kind = str(
            invocation.arguments.get("kind") or "general"
        )
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

    def _check_attempt_close(
        self,
        context: Any,
        step_context: AgentStepContext,
        invocation: ToolInvocation,
    ) -> ToolResult | None:
        if step_context.actor_kind != "master":
            return _rejection(
                invocation,
                code="aox_cutover_close_actor_violation",
                summary=(
                    "AOX cutover attempt closure may be requested only by the "
                    "resident master after teammate business exits settle."
                ),
                hint=(
                    "Return the result to the master. This no-effect actor "
                    "boundary is the intended handoff and must not make a "
                    "sealed positive execution task blocked; finish that task "
                    "completed, then let the master reconcile the exact task "
                    "board and report state before closing."
                ),
                details={
                    "actor_kind": step_context.actor_kind,
                    "agent_id": step_context.agent_id,
                },
            )

        repositories = context.repositories
        tasks = tuple(
            repositories.tasks.list_by_session(self.session_id)
        )
        expected = self.expected_task_contracts
        tasks_by_id = {
            str(getattr(task, "task_id", "")): task for task in tasks
        }
        observed_ids = set(tasks_by_id)
        if observed_ids != set(expected):
            return _rejection(
                invocation,
                code="aox_cutover_task_set_not_ready",
                summary=(
                    "AOX cutover attempt closure was rejected because the "
                    "durable task board is not the exact canonical three-task set."
                ),
                hint=(
                    "Create only missing canonical members, reconcile existing "
                    "members, and do not close while any extra task exists."
                ),
                details={
                    "expected_task_ids": sorted(expected),
                    "observed_task_ids": sorted(observed_ids),
                    "missing_task_ids": sorted(set(expected) - observed_ids),
                    "extra_task_ids": sorted(observed_ids - set(expected)),
                },
            )

        agents_by_id = {
            str(getattr(agent, "agent_id", "")): str(
                getattr(agent, "role", "")
            )
            for agent in repositories.agents.list_by_session(
                self.session_id
            )
        }
        identity_issues: list[dict[str, object]] = []
        for task_id, (expected_kind, expected_role) in expected.items():
            task = tasks_by_id[task_id]
            assigned_ref = str(
                getattr(task, "assigned_ref", "") or ""
            )
            observed_kind = str(getattr(task, "kind", "") or "")
            observed_role = agents_by_id.get(assigned_ref)
            if (
                observed_kind != expected_kind
                or observed_role != expected_role
            ):
                identity_issues.append(
                    {
                        "task_id": task_id,
                        "expected_kind": expected_kind,
                        "observed_kind": observed_kind,
                        "expected_role": expected_role,
                        "observed_role": observed_role,
                    }
                )
        if identity_issues:
            return _rejection(
                invocation,
                code="aox_cutover_task_identity_not_ready",
                summary=(
                    "AOX cutover attempt closure was rejected because canonical "
                    "task kind or teammate assignment is incomplete."
                ),
                hint=(
                    "Bind each canonical research/execution/reporting task to "
                    "exactly its researcher/executor/reporter teammate."
                ),
                details={"identity_issues": identity_issues},
            )

        observed_statuses = {
            task_id: _status_value(task)
            for task_id, task in tasks_by_id.items()
        }
        status_issue = self._task_status_issue(observed_statuses)
        if status_issue is not None:
            return _rejection(
                invocation,
                code="aox_cutover_task_exits_not_ready",
                summary=(
                    "AOX cutover attempt closure was rejected because teammate "
                    "business exits have not reached the required state."
                ),
                hint=status_issue,
                details={
                    "attempt_kind": self.attempt_kind,
                    "task_statuses": observed_statuses,
                },
            )

        finish_issues = self._task_finish_issues(
            repositories,
            tasks_by_id=tasks_by_id,
            observed_statuses=observed_statuses,
        )
        if finish_issues:
            return _rejection(
                invocation,
                code="aox_cutover_task_finish_receipts_not_ready",
                summary=(
                    "AOX cutover attempt closure was rejected because task state "
                    "does not resolve to one matching explicit task.finish receipt."
                ),
                hint=(
                    "Have each assigned teammate issue exactly one task.finish "
                    "matching its required business exit before retrying closure."
                ),
                details={"finish_issues": finish_issues},
            )

        reports = tuple(
            repositories.reports.list_by_session(self.session_id)
        )
        drafts = tuple(
            repositories.report_drafts.list_by_session(
                self.session_id
            )
        )
        report_issue = self._report_state_issue(reports, drafts)
        if report_issue is not None:
            code, summary, hint, details = report_issue
            return _rejection(
                invocation,
                code=code,
                summary=summary,
                hint=hint,
                details=details,
            )
        if self.sealed_operation_universe and self.attempt_kind == "positive":
            reporter_finish_documents = []
            for document in repositories.engine_documents.list_by_session(
                self.session_id
            ):
                if (
                    getattr(document, "document_kind", None)
                    != "task_finish"
                ):
                    continue
                payload = dict(
                    getattr(document, "payload", None) or {}
                )
                if (
                    payload.get("task_id") == self.report_task_id
                    and payload.get("status") == "completed"
                ):
                    reporter_finish_documents.append(document)
            reporter_evidence_refs = (
                ()
                if len(reporter_finish_documents) != 1
                else tuple(
                    str(item)
                    for item in (
                        dict(
                            getattr(
                                reporter_finish_documents[0],
                                "payload",
                                None,
                            )
                            or {}
                        ).get("evidence_refs")
                        or []
                    )
                )
            )
            source_link = evaluate_aox_source_linked_report(
                repositories,
                session_id=self.session_id,
                research_task_id=self.research_task_id,
                report_task_id=self.report_task_id,
                reporter_evidence_refs=reporter_evidence_refs,
                require_diagnostic_source_copy=True,
            )
            if source_link["ready"] is not True:
                return _rejection(
                    invocation,
                    code=(
                        "aox_closure_stage_report_source_link_not_ready"
                    ),
                    summary=(
                        "Closure was rejected because the reporting exit does "
                        "not prove the durable report-to-PubMed source chain."
                    ),
                    hint=(
                        "The assigned reporter must publish one non-empty report "
                        "and finish with both the report and canonical PubMed "
                        "artifact refs before the resident master retries close."
                    ),
                    details={
                        "blocker_codes": list(
                            source_link["blocker_codes"]
                        ),
                        "required_evidence_refs": list(
                            source_link["required_evidence_refs"]
                        ),
                        "observed_evidence_refs": list(
                            source_link["observed_evidence_refs"]
                        ),
                        "missing_evidence_refs": list(
                            source_link["missing_evidence_refs"]
                        ),
                    },
                )
        if (
            invocation.assistant_response_text is None
            or not invocation.assistant_response_text.strip()
        ):
            return _rejection(
                invocation,
                code="aox_cutover_final_response_missing",
                summary=(
                    "AOX cutover attempt closure was rejected because the same "
                    "model response did not include a non-empty final user-facing "
                    "answer."
                ),
                hint=(
                    "Include the complete final answer as response text and call "
                    "scientific.attempt.close in that same response; do not emit "
                    "the answer in an earlier assistant-only turn."
                ),
                details={"assistant_response_present": False},
            )
        return None

    def _task_status_issue(
        self,
        observed_statuses: dict[str, str],
    ) -> str | None:
        if self.attempt_kind == "positive":
            if set(observed_statuses.values()) == {"completed"}:
                return None
            return (
                "A positive attempt requires research, execution, and reporting "
                "tasks all explicitly completed."
            )
        if (
            observed_statuses[self.research_task_id] == "completed"
            and observed_statuses[self.execution_task_id]
            in _FAULT_EXECUTION_EXITS
            and observed_statuses[self.report_task_id]
            in _FAULT_REPORT_EXITS
        ):
            return None
        return (
            "A fault attempt requires completed research, a failed/blocked/"
            "cancelled execution exit, and a failed/blocked/cancelled reporting "
            "exit without a success report."
        )

    def _task_finish_issues(
        self,
        repositories: Any,
        *,
        tasks_by_id: dict[str, object],
        observed_statuses: dict[str, str],
    ) -> list[dict[str, object]]:
        finish_payloads: dict[str, list[dict[str, object]]] = {}
        for document in repositories.engine_documents.list_by_session(
            self.session_id
        ):
            if getattr(document, "document_kind", None) != "task_finish":
                continue
            payload = dict(getattr(document, "payload", None) or {})
            task_id = str(payload.get("task_id") or "")
            if task_id:
                finish_payloads.setdefault(task_id, []).append(payload)
        issues: list[dict[str, object]] = []
        for task_id, status in observed_statuses.items():
            matches = finish_payloads.get(task_id, [])
            expected_finished_by = str(
                getattr(tasks_by_id[task_id], "assigned_ref", "") or ""
            )
            observed_finished_by = [
                str(payload.get("finished_by") or "").strip() for payload in matches
            ]
            if (
                len(matches) != 1
                or matches[0].get("status") != status
                or observed_finished_by[0] != expected_finished_by
            ):
                issues.append(
                    {
                        "task_id": task_id,
                        "task_status": status,
                        "finish_receipt_count": len(matches),
                        "finish_statuses": [
                            str(payload.get("status") or "")
                            for payload in matches
                        ],
                        "expected_finished_by": expected_finished_by,
                        "observed_finished_by": observed_finished_by,
                    }
                )
        return issues

    def _report_state_issue(
        self,
        reports: tuple[object, ...],
        drafts: tuple[object, ...],
    ) -> (
        tuple[str, str, str, dict[str, object]]
        | None
    ):
        if self.attempt_kind == "fault":
            success_reports = [
                str(getattr(report, "report_id", ""))
                for report in reports
                if is_published_report_status(report)
            ]
            success_drafts = [
                str(getattr(draft, "draft_id", ""))
                for draft in drafts
                if _status_value(draft) in {"ready", "published"}
                or bool(getattr(draft, "published_report_id", None))
            ]
            if not success_reports and not success_drafts:
                return None
            return (
                "aox_cutover_fault_report_state_invalid",
                (
                    "AOX cutover fault closure was rejected because a "
                    "ready/published success report state exists."
                ),
                (
                    "Keep the required-chain fault explicit; fail or abandon "
                    "drafts and do not publish a success report."
                ),
                {
                    "success_report_ids": success_reports,
                    "success_draft_ids": success_drafts,
                },
            )

        published_reports = [
            report for report in reports if is_published_report_status(report)
        ]
        published_drafts = [
            draft for draft in drafts if _status_value(draft) == "published"
        ]
        linked = False
        if len(published_reports) == 1 and len(published_drafts) == 1:
            report = published_reports[0]
            draft = published_drafts[0]
            linked = is_published_report_link(
                report,
                draft,
                task_id=self.report_task_id,
            )
        if linked:
            return None
        return (
            "aox_cutover_positive_report_not_ready",
            (
                "AOX cutover positive closure was rejected because the exact "
                "ready/published report and published durable draft are not linked to "
                "the canonical reporting task."
            ),
            (
                "Complete the canonical reporting task only after publishing "
                "one non-empty draft to exactly one ready/published report, then retry "
                "scientific.attempt.close as the final mutation."
            ),
            {
                "published_report_ids": [
                    str(getattr(report, "report_id", ""))
                    for report in published_reports
                ],
                "published_draft_ids": [
                    str(getattr(draft, "draft_id", ""))
                    for draft in published_drafts
                ],
                "report_task_id": self.report_task_id,
                "report_link_ready": linked,
            },
        )


__all__ = [
    "AOX_CUTOVER_TOOL_PRECONDITION_ID",
    "AOX_REPORT_TASK_ID",
    "AOX_RESEARCH_TASK_ID",
    "AoxCutoverFormalToolPrecondition",
    "evaluate_aox_source_linked_report",
]
