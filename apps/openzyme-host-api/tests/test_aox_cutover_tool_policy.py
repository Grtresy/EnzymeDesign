from __future__ import annotations

from types import SimpleNamespace

from openzyme_host_api.aox_cutover_tool_policy import AOX_REPORT_TASK_ID
from openzyme_host_api.aox_cutover_tool_policy import AOX_RESEARCH_TASK_ID
from openzyme_host_api.aox_cutover_tool_policy import (
    AoxCutoverFormalToolPrecondition,
)
from openzyme_runtime import ToolInvocation


SESSION_ID = "sess_formal_policy"
EXECUTION_TASK_ID = "aox_execution_cutover_policy"


def _record(**values: object) -> SimpleNamespace:
    return SimpleNamespace(**values)


def _status(value: str) -> SimpleNamespace:
    return _record(value=value)


def _tasks(
    *,
    research_status: str = "completed",
    execution_status: str = "completed",
    report_status: str = "completed",
) -> tuple[SimpleNamespace, ...]:
    return (
        _record(
            task_id=AOX_RESEARCH_TASK_ID,
            kind="research",
            assigned_ref="agent_researcher",
            status=_status(research_status),
        ),
        _record(
            task_id=EXECUTION_TASK_ID,
            kind="execution",
            assigned_ref="agent_executor",
            status=_status(execution_status),
        ),
        _record(
            task_id=AOX_REPORT_TASK_ID,
            kind="reporting",
            assigned_ref="agent_reporter",
            status=_status(report_status),
        ),
    )


def _agents() -> tuple[SimpleNamespace, ...]:
    return (
        _record(agent_id="agent_researcher", role="researcher"),
        _record(agent_id="agent_executor", role="executor"),
        _record(agent_id="agent_reporter", role="reporter"),
    )


def _finish_documents(
    tasks: tuple[SimpleNamespace, ...],
) -> tuple[SimpleNamespace, ...]:
    return tuple(
        _record(
            document_kind="task_finish",
            payload={
                "task_id": task.task_id,
                "status": task.status.value,
                "finished_by": task.assigned_ref,
            },
        )
        for task in tasks
    )


def _repositories(
    *,
    tasks: tuple[SimpleNamespace, ...],
    reports: tuple[SimpleNamespace, ...] = (),
    drafts: tuple[SimpleNamespace, ...] = (),
    documents: tuple[SimpleNamespace, ...] | None = None,
) -> SimpleNamespace:
    by_id = {task.task_id: task for task in tasks}
    finish_documents = (
        _finish_documents(tasks) if documents is None else documents
    )
    return _record(
        tasks=_record(
            get=by_id.get,
            list_by_session=lambda _session_id: tasks,
        ),
        agents=_record(
            list_by_session=lambda _session_id: _agents(),
        ),
        engine_documents=_record(
            list_by_session=lambda _session_id: finish_documents,
        ),
        reports=_record(
            list_by_session=lambda _session_id: reports,
        ),
        report_drafts=_record(
            list_by_session=lambda _session_id: drafts,
        ),
    )


def _context(repositories: SimpleNamespace) -> SimpleNamespace:
    return _record(repositories=repositories)


def _step(
    *,
    session_id: str = SESSION_ID,
    actor_kind: str = "master",
) -> SimpleNamespace:
    return _record(
        session_id=session_id,
        actor_kind=actor_kind,
        agent_id="agent:master",
    )


def _close_invocation() -> ToolInvocation:
    return ToolInvocation(
        call_id="call_close",
        tool_name="scientific.attempt.close",
        arguments={
            "attempt_id": "attempt_001",
            "selection_id": "selection_001",
            "actor_ref": "agent:master",
            "idempotency_key": "close:001",
        },
    )


def _positive_policy() -> AoxCutoverFormalToolPrecondition:
    return AoxCutoverFormalToolPrecondition(
        session_id=SESSION_ID,
        execution_task_id=EXECUTION_TASK_ID,
        attempt_kind="positive",
    )


def test_cutover_policy_rejects_noncanonical_task_creation_without_effect() -> None:
    policy = _positive_policy()
    invocation = ToolInvocation(
        call_id="call_task",
        tool_name="task.create",
        arguments={
            "task_id": f"{AOX_REPORT_TASK_ID}_retry",
            "subject": "Replacement report",
            "kind": "reporting",
        },
    )

    result = policy(
        _context(_repositories(tasks=())),
        _step(),  # type: ignore[arg-type]
        invocation,
    )

    assert result is not None
    assert result.ok is False
    assert result.error_code == "aox_cutover_task_set_violation"
    assert result.details["effect_certainty"] == "no_effect"
    assert result.details["retry_eligibility"] == "same_phase_safe"
    assert result.details["expected_task_ids"] == sorted(
        {
            AOX_RESEARCH_TASK_ID,
            EXECUTION_TASK_ID,
            AOX_REPORT_TASK_ID,
        }
    )


def test_cutover_policy_rejects_wrong_kind_for_canonical_task() -> None:
    invocation = ToolInvocation(
        call_id="call_wrong_kind",
        tool_name="task.create",
        arguments={
            "task_id": AOX_RESEARCH_TASK_ID,
            "subject": "Research",
            "kind": "execution",
        },
    )

    result = _positive_policy()(
        _context(_repositories(tasks=())),
        _step(),  # type: ignore[arg-type]
        invocation,
    )

    assert result is not None
    assert result.error_code == "aox_cutover_task_kind_violation"
    assert result.details["expected_kind"] == "research"


def test_cutover_policy_rejects_duplicate_canonical_task() -> None:
    tasks = _tasks()
    invocation = ToolInvocation(
        call_id="call_duplicate",
        tool_name="task.create",
        arguments={
            "task_id": AOX_RESEARCH_TASK_ID,
            "subject": "Duplicate research",
            "kind": "research",
        },
    )

    result = _positive_policy()(
        _context(_repositories(tasks=tasks)),
        _step(),  # type: ignore[arg-type]
        invocation,
    )

    assert result is not None
    assert result.error_code == "aox_cutover_task_already_exists"


def test_cutover_policy_rejects_close_before_positive_task_exits() -> None:
    tasks = _tasks(execution_status="in_progress")

    result = _positive_policy()(
        _context(_repositories(tasks=tasks)),
        _step(),  # type: ignore[arg-type]
        _close_invocation(),
    )

    assert result is not None
    assert result.error_code == "aox_cutover_task_exits_not_ready"
    assert result.details["task_statuses"][EXECUTION_TASK_ID] == (
        "in_progress"
    )


def test_cutover_policy_rejects_close_from_teammate() -> None:
    result = _positive_policy()(
        _context(_repositories(tasks=_tasks())),
        _step(actor_kind="teammate"),  # type: ignore[arg-type]
        _close_invocation(),
    )

    assert result is not None
    assert result.error_code == "aox_cutover_close_actor_violation"


def test_cutover_policy_rejects_extra_task_and_wrong_assignment() -> None:
    extra_tasks = (
        *_tasks(),
        _record(
            task_id="aox_final_source_linked_report_retry",
            kind="reporting",
            assigned_ref="agent_reporter",
            status=_status("todo"),
        ),
    )
    extra_result = _positive_policy()(
        _context(_repositories(tasks=extra_tasks)),
        _step(),  # type: ignore[arg-type]
        _close_invocation(),
    )
    assert extra_result is not None
    assert extra_result.error_code == "aox_cutover_task_set_not_ready"
    assert extra_result.details["extra_task_ids"] == [
        "aox_final_source_linked_report_retry"
    ]

    wrong_assignment = list(_tasks())
    wrong_assignment[1] = _record(
        task_id=EXECUTION_TASK_ID,
        kind="execution",
        assigned_ref="agent_reporter",
        status=_status("completed"),
    )
    identity_result = _positive_policy()(
        _context(_repositories(tasks=tuple(wrong_assignment))),
        _step(),  # type: ignore[arg-type]
        _close_invocation(),
    )
    assert identity_result is not None
    assert identity_result.error_code == "aox_cutover_task_identity_not_ready"


def test_cutover_policy_rejects_mismatched_task_finish_receipt() -> None:
    tasks = _tasks()
    documents = list(_finish_documents(tasks))
    documents[1] = _record(
        document_kind="task_finish",
        payload={
            "task_id": EXECUTION_TASK_ID,
            "status": "failed",
            "finished_by": "agent_executor",
        },
    )

    result = _positive_policy()(
        _context(
            _repositories(
                tasks=tasks,
                documents=tuple(documents),
            )
        ),
        _step(),  # type: ignore[arg-type]
        _close_invocation(),
    )

    assert result is not None
    assert (
        result.error_code
        == "aox_cutover_task_finish_receipts_not_ready"
    )
    assert result.details["finish_issues"][0]["task_id"] == (
        EXECUTION_TASK_ID
    )


def test_cutover_policy_requires_exact_positive_report_link() -> None:
    tasks = _tasks()

    result = _positive_policy()(
        _context(_repositories(tasks=tasks)),
        _step(),  # type: ignore[arg-type]
        _close_invocation(),
    )

    assert result is not None
    assert result.error_code == "aox_cutover_positive_report_not_ready"
    assert result.details["report_link_ready"] is False


def test_cutover_policy_allows_ready_positive_close() -> None:
    tasks = _tasks()
    reports = (
        _record(
            report_id="report_001",
            task_id=AOX_REPORT_TASK_ID,
            status=_status("ready"),
        ),
    )
    drafts = (
        _record(
            draft_id="draft_001",
            task_id=AOX_REPORT_TASK_ID,
            status=_status("published"),
            published_report_id="report_001",
            content_ref="doc_report_001",
        ),
    )

    result = _positive_policy()(
        _context(
            _repositories(
                tasks=tasks,
                reports=reports,
                drafts=drafts,
            )
        ),
        _step(),  # type: ignore[arg-type]
        _close_invocation(),
    )

    assert result is None


def test_cutover_policy_allows_closed_fault_without_success_report() -> None:
    policy = AoxCutoverFormalToolPrecondition(
        session_id=SESSION_ID,
        execution_task_id=EXECUTION_TASK_ID,
        attempt_kind="fault",
    )
    tasks = _tasks(
        execution_status="failed",
        report_status="blocked",
    )
    drafts = (
        _record(
            draft_id="draft_failure",
            task_id=AOX_REPORT_TASK_ID,
            status=_status("failed"),
            published_report_id=None,
            content_ref="doc_failure",
        ),
    )

    result = policy(
        _context(_repositories(tasks=tasks, drafts=drafts)),
        _step(),  # type: ignore[arg-type]
        _close_invocation(),
    )

    assert result is None


def test_cutover_policy_rejects_fault_success_report_state() -> None:
    policy = AoxCutoverFormalToolPrecondition(
        session_id=SESSION_ID,
        execution_task_id=EXECUTION_TASK_ID,
        attempt_kind="fault",
    )
    tasks = _tasks(
        execution_status="failed",
        report_status="blocked",
    )
    reports = (
        _record(
            report_id="report_unexpected",
            task_id=AOX_REPORT_TASK_ID,
            status=_status("ready"),
        ),
    )

    result = policy(
        _context(_repositories(tasks=tasks, reports=reports)),
        _step(),  # type: ignore[arg-type]
        _close_invocation(),
    )

    assert result is not None
    assert result.error_code == "aox_cutover_fault_report_state_invalid"
    assert result.details["success_report_ids"] == ["report_unexpected"]


def test_cutover_policy_does_not_affect_probe_or_other_sessions() -> None:
    invocation = ToolInvocation(
        call_id="call_probe_task",
        tool_name="task.create",
        arguments={"subject": "Probe execution"},
    )

    result = _positive_policy()(
        _context(_repositories(tasks=())),
        _step(session_id="sess_probe"),  # type: ignore[arg-type]
        invocation,
    )

    assert result is None
