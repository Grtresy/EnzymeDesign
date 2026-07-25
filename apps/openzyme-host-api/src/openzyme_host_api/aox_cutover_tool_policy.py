from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Literal

from openzyme_core import AssistantResponseRejection
from openzyme_core import is_published_report_link
from openzyme_core import is_published_report_status
from openzyme_runtime import AgentStepContext
from openzyme_runtime import ToolInvocation
from openzyme_runtime import ToolResult


AOX_CUTOVER_TOOL_PRECONDITION_ID = (
    "aox_cutover_formal_tool_precondition@2"
)
AOX_RESEARCH_TASK_ID = "aox_research_pubmed_evidence"
AOX_REPORT_TASK_ID = "aox_final_source_linked_report"

_TASK_CONTRACTS = {
    AOX_RESEARCH_TASK_ID: ("research", "researcher"),
    AOX_REPORT_TASK_ID: ("reporting", "reporter"),
}
_FAULT_EXECUTION_EXITS = frozenset({"failed", "blocked", "cancelled"})
_FAULT_REPORT_EXITS = frozenset({"failed", "blocked", "cancelled"})


def _status_value(record: object) -> str:
    status = getattr(record, "status", None)
    return str(getattr(status, "value", status) or "")


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
    before closure, and the requirement that a close-ready master submit its
    final response together with the explicit scientific-attempt close call.
    """

    session_id: str
    execution_task_id: str
    attempt_kind: Literal["positive", "fault"]

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("formal cutover session_id must be non-empty")
        if not self.execution_task_id.strip():
            raise ValueError(
                "formal cutover execution_task_id must be non-empty"
            )
        if self.execution_task_id in {
            AOX_RESEARCH_TASK_ID,
            AOX_REPORT_TASK_ID,
        }:
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
            AOX_RESEARCH_TASK_ID: _TASK_CONTRACTS[AOX_RESEARCH_TASK_ID],
            self.execution_task_id: ("execution", "executor"),
            AOX_REPORT_TASK_ID: _TASK_CONTRACTS[AOX_REPORT_TASK_ID],
        }

    def __call__(
        self,
        context: Any,
        step_context: AgentStepContext,
        invocation: ToolInvocation,
    ) -> ToolResult | None:
        if step_context.session_id != self.session_id:
            return None
        if invocation.tool_name == "task.create":
            return self._check_task_create(context, invocation)
        if invocation.tool_name == "scientific.attempt.close":
            return self._check_attempt_close(
                context,
                step_context,
                invocation,
            )
        return None

    def check_assistant_response(
        self,
        context: Any,
        step_context: AgentStepContext,
        assistant_response: str,
    ) -> AssistantResponseRejection | None:
        if (
            step_context.session_id != self.session_id
            or step_context.actor_kind != "master"
        ):
            return None
        repositories = context.repositories
        active_attempts = [
            attempt
            for attempt in repositories.scientific_attempts.list_by_session(
                self.session_id
            )
            if _status_value(attempt) == "active"
            and repositories.scientific_attempt_closure_requests.get_by_attempt(
                str(getattr(attempt, "attempt_id", ""))
            )
            is None
        ]
        if len(active_attempts) != 1:
            return None
        attempt = active_attempts[0]
        if str(getattr(attempt, "task_id", "")) != self.execution_task_id:
            return None

        readiness_probe = ToolInvocation(
            call_id="aox_cutover_assistant_response_readiness",
            tool_name="scientific.attempt.close",
            arguments={},
            task_id=self.execution_task_id,
            assistant_response_text=assistant_response,
        )
        if (
            self._check_attempt_close(
                context,
                step_context,
                readiness_probe,
            )
            is not None
        ):
            return None

        attempt_id = str(getattr(attempt, "attempt_id", ""))
        resolved_head = repositories.scientific_selections.resolve_head(
            attempt_id
        )
        selection_id = (
            None
            if resolved_head is None
            else resolved_head.head.selection_id
        )
        return AssistantResponseRejection(
            error_code="aox_cutover_close_required_before_final_response",
            summary=(
                "The AOX cutover final response was not persisted because the "
                "canonical task and report exits are ready but the active "
                "scientific attempt has not received an explicit closure request."
            ),
            hint=(
                "In one model response, include the complete user-facing final "
                "answer as response text and call scientific.attempt.close for "
                "the active attempt and exact sealed selection."
            ),
            details={
                "policy_id": AOX_CUTOVER_TOOL_PRECONDITION_ID,
                "assistant_response_persisted": False,
                "effect_certainty": "no_effect",
                "retry_eligibility": "same_phase_safe",
                "attempt_id": attempt_id,
                "selection_id": selection_id,
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
                    "Return the result to the master; the master must reconcile "
                    "the exact task board and report state before closing."
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
            observed_statuses[AOX_RESEARCH_TASK_ID] == "completed"
            and observed_statuses[self.execution_task_id]
            in _FAULT_EXECUTION_EXITS
            and observed_statuses[AOX_REPORT_TASK_ID]
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
                task_id=AOX_REPORT_TASK_ID,
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
                "report_task_id": AOX_REPORT_TASK_ID,
                "report_link_ready": linked,
            },
        )


__all__ = [
    "AOX_CUTOVER_TOOL_PRECONDITION_ID",
    "AOX_REPORT_TASK_ID",
    "AOX_RESEARCH_TASK_ID",
    "AoxCutoverFormalToolPrecondition",
]
