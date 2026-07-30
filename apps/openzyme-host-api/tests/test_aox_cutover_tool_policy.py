from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import openzyme_core.agent_runtime as agent_runtime_module

from openzyme_core import CoreRepositories
from openzyme_core import HarnessInput
from openzyme_core import HarnessStatus
from openzyme_core import HarnessStep
from openzyme_core import ScientificAttemptService
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import TaskBoardService
from openzyme_core import TaskFinishCommand
from openzyme_core import ToolRegistry
from openzyme_core import apply_sqlite_migrations
from openzyme_core import build_conversation_projection
from openzyme_core import connect_sqlite
from openzyme_core import controlled_operation_artifact_set_digest
from openzyme_core import run_agent_harness_loop
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ControlledOperationResultHandle
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import Lane
from openzyme_domain import LaneStatus
from openzyme_domain import MutationWriterKind
from openzyme_domain import RetryEligibility
from openzyme_domain import SandboxImageCompatibility
from openzyme_domain import SandboxRunRecord
from openzyme_domain import SandboxRunStatus
from openzyme_domain import SandboxWorkspaceRecord
from openzyme_domain import SandboxWorkspaceStatus
from openzyme_domain import ScientificAttemptAuthorityStatus
from openzyme_domain import ScientificAttemptScope
from openzyme_domain import Session
from openzyme_domain import SessionReportDraftRecord
from openzyme_domain import SessionReportDraftStatus
from openzyme_domain import SessionReportRecord
from openzyme_domain import SessionReportStatus
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskStatus
from openzyme_host_api.aox_cutover_tool_policy import AOX_REPORT_TASK_ID
from openzyme_host_api.aox_cutover_tool_policy import AOX_RESEARCH_TASK_ID
from openzyme_host_api.aox_cutover_tool_policy import (
    AoxCutoverFormalToolPrecondition,
)
from openzyme_host_api.aox_scientific_contract import (
    AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY,
)
from openzyme_host_api.aox_scientific_contract import (
    AOX_SELECTED_CHAIN_CONTRACT_V2,
)
from openzyme_host_api.aox_scientific_contract import (
    AOX_SELECTED_CHAIN_WORKFLOW_ID,
)
from openzyme_host_api.aox_cutover_live import LiveAoxAttemptRunner
from openzyme_host_api.v3_service import V3EventStore
from openzyme_host_api.v3_service import V3HostApiService
from openzyme_runtime import ToolInvocation


SESSION_ID = "sess_formal_policy"
EXECUTION_TASK_ID = "aox_execution_cutover_policy"
FINAL_RESPONSE = "AOX formal workflow completed with a source-linked report."


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
    artifacts: tuple[SimpleNamespace, ...] = (),
    source_refs: tuple[SimpleNamespace, ...] = (),
    attempts: tuple[SimpleNamespace, ...] = (),
    resolved_head: SimpleNamespace | None = None,
) -> SimpleNamespace:
    by_id = {task.task_id: task for task in tasks}
    attempts_by_id = {attempt.attempt_id: attempt for attempt in attempts}
    finish_documents = _finish_documents(tasks) if documents is None else documents
    documents_by_id = {
        str(document.document_id): document
        for document in finish_documents
        if getattr(document, "document_id", None) is not None
    }
    artifacts_by_id = {str(artifact.artifact_id): artifact for artifact in artifacts}
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
            get=documents_by_id.get,
        ),
        artifacts=_record(
            get=artifacts_by_id.get,
        ),
        research_source_refs=_record(
            list_by_session=lambda _session_id: source_refs,
        ),
        reports=_record(
            list_by_session=lambda _session_id: reports,
        ),
        report_drafts=_record(
            list_by_session=lambda _session_id: drafts,
        ),
        scientific_attempts=_record(
            get=attempts_by_id.get,
            list_by_session=lambda _session_id: attempts,
        ),
        scientific_selections=_record(
            resolve_head=lambda _attempt_id: resolved_head,
        ),
    )


def _context(
    repositories: object,
    *,
    scientific_workflow_contract_registry: object | None = None,
) -> SimpleNamespace:
    return _record(
        repositories=repositories,
        scientific_workflow_contract_registry=(scientific_workflow_contract_registry),
    )


def _step(
    *,
    session_id: str = SESSION_ID,
    actor_kind: str = "master",
    agent_id: str = "agent:master",
) -> SimpleNamespace:
    return _record(
        session_id=session_id,
        actor_kind=actor_kind,
        agent_id=agent_id,
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


def test_cutover_policy_has_no_assistant_response_veto() -> None:
    policy = _positive_policy()

    assert not hasattr(policy, "check_assistant_response")


@pytest.mark.parametrize(
    "tool_name",
    (
        "artifact.create_text",
        "artifact.patch_text",
        "artifacts.materialize",
        "artifacts.register",
        "artifacts.snapshot_code",
        "attempt.create",
        "deep_research.resume",
        "deep_research.start",
        "execution.pipeline.start",
        "interpro.query",
        "pubmed.search",
        "rcsb_pdb.download_structure",
        "rcsb_pdb.search",
        "sandbox.exec",
        "sandbox.file.delete",
        "sandbox.file.patch",
        "sandbox.file.write",
        "scientific.artifact.materialize",
        "scientific.effect.adopt",
        "scientific.operation.adopt",
        "scientific.operation.disposition",
        "scientific.selection.begin",
        "scientific.selection.seal",
        "semantic_scholar.search",
        "uniprot.download_fasta",
        "uniprot.lookup",
        "web.fetch",
        "web.search",
        "future.external.effect",
    ),
)
def test_closure_stage_policy_seals_external_operation_universe(
    tool_name: str,
) -> None:
    policy = AoxCutoverFormalToolPrecondition(
        session_id=SESSION_ID,
        execution_task_id=EXECUTION_TASK_ID,
        attempt_kind="positive",
        sealed_operation_universe=True,
    )
    invocation = ToolInvocation(
        call_id="call_closure_stage_sealed",
        tool_name=tool_name,
        arguments={},
    )

    result = policy(
        _context(_repositories(tasks=())),
        _step(),  # type: ignore[arg-type]
        invocation,
    )

    assert result is not None
    assert result.ok is False
    assert result.error_code == ("aox_closure_stage_operation_universe_sealed")
    assert result.details == {
        "policy_id": "aox_cutover_formal_tool_precondition@5",
        "precondition_rejected": True,
        "dispatched": False,
        "effect_certainty": "no_effect",
        "retry_eligibility": "same_phase_safe",
        "tool_name": tool_name,
        "operation_universe_sealed": True,
    }


@pytest.mark.parametrize(
    "tool_name",
    (
        "artifact.list",
        "deep_research.status",
        "execution.pipeline.status",
        "protocol.send",
        "report.publish",
        "report_draft.update",
        "scientific.attempt.close",
        "task.finish",
        "world.inspect",
    ),
)
def test_closure_stage_policy_keeps_declared_handoff_tools_available(
    tool_name: str,
) -> None:
    policy = AoxCutoverFormalToolPrecondition(
        session_id=SESSION_ID,
        execution_task_id=EXECUTION_TASK_ID,
        attempt_kind="positive",
        sealed_operation_universe=True,
    )
    invocation = ToolInvocation(
        call_id="call_closure_stage_allowed",
        tool_name=tool_name,
        arguments={},
    )

    result = policy(
        _context(_repositories(tasks=())),
        _step(),  # type: ignore[arg-type]
        invocation,
    )
    assert result is None or result.error_code != (
        "aox_closure_stage_operation_universe_sealed"
    )


def test_closure_stage_report_finish_requires_durable_pubmed_source_link() -> None:
    tasks = _tasks(report_status="in_progress")
    primary_artifact_id = "art_primary_pubmed"
    report_id = "report_closure_stage"
    content_ref = "doc_report_content"
    documents = (
        _record(
            document_id="finish_research",
            document_kind="task_finish",
            payload={
                "task_id": AOX_RESEARCH_TASK_ID,
                "status": "completed",
                "finished_by": "agent_researcher",
                "evidence_refs": [f"artifact:{primary_artifact_id}"],
            },
        ),
        _record(
            document_id=content_ref,
            document_kind="report_draft_content",
            payload={"markdown": "# AOX/HMM diagnostic\n\nSource-linked."},
        ),
    )
    repositories = _repositories(
        tasks=tasks,
        reports=(
            _record(
                report_id=report_id,
                session_id=SESSION_ID,
                task_id=AOX_REPORT_TASK_ID,
                status=_status("ready"),
            ),
        ),
        drafts=(
            _record(
                draft_id="draft_closure_stage",
                session_id=SESSION_ID,
                task_id=AOX_REPORT_TASK_ID,
                status=_status("published"),
                content_ref=content_ref,
                published_report_id=report_id,
            ),
        ),
        documents=documents,
        artifacts=(
            _record(
                artifact_id=primary_artifact_id,
                session_id=SESSION_ID,
                task_id=AOX_RESEARCH_TASK_ID,
                metadata={
                    "provider": "pubmed",
                    "cutover_eligible": True,
                    "content_digest": "sha256:" + "a" * 64,
                    "diagnostic_source_copy": {
                        "source_artifact_id": primary_artifact_id,
                        "source_manifest_digest": ("sha256:" + "b" * 64),
                        "formal_adoption_eligible": False,
                        "new_effect": False,
                    },
                },
            ),
        ),
        source_refs=(
            _record(
                source_ref_id="source_ref_pubmed_001",
                evidence_artifact_id=primary_artifact_id,
                provider="pubmed",
                pmid="42278471",
                task_id=AOX_RESEARCH_TASK_ID,
            ),
        ),
    )
    policy = AoxCutoverFormalToolPrecondition(
        session_id=SESSION_ID,
        execution_task_id=EXECUTION_TASK_ID,
        attempt_kind="positive",
        sealed_operation_universe=True,
    )

    missing_source = policy(
        _context(repositories),
        _step(
            actor_kind="teammate",
            agent_id="agent_reporter",
        ),  # type: ignore[arg-type]
        ToolInvocation(
            call_id="call_report_finish_missing_source",
            tool_name="task.finish",
            arguments={
                "task_id": AOX_REPORT_TASK_ID,
                "status": "completed",
                "summary": "Published the report.",
                "evidence_refs": [f"report:{report_id}"],
            },
        ),
    )

    assert missing_source is not None
    assert missing_source.error_code == ("aox_closure_stage_report_source_link_invalid")
    assert missing_source.details["missing_evidence_refs"] == [
        f"artifact:{primary_artifact_id}"
    ]

    linked = policy(
        _context(repositories),
        _step(
            actor_kind="teammate",
            agent_id="agent_reporter",
        ),  # type: ignore[arg-type]
        ToolInvocation(
            call_id="call_report_finish_linked",
            tool_name="task.finish",
            arguments={
                "task_id": AOX_REPORT_TASK_ID,
                "status": "completed",
                "summary": "Published the source-linked report.",
                "evidence_refs": [
                    f"report:{report_id}",
                    f"artifact:{primary_artifact_id}",
                ],
            },
        ),
    )

    assert linked is None

    completed_documents = (
        documents[0],
        _record(
            document_id="finish_execution",
            document_kind="task_finish",
            payload={
                "task_id": EXECUTION_TASK_ID,
                "status": "completed",
                "finished_by": "agent_executor",
                "evidence_refs": ["artifact:art_execution_result"],
            },
        ),
        _record(
            document_id="finish_reporter",
            document_kind="task_finish",
            payload={
                "task_id": AOX_REPORT_TASK_ID,
                "status": "completed",
                "finished_by": "agent_reporter",
                "evidence_refs": [
                    f"report:{report_id}",
                    f"artifact:{primary_artifact_id}",
                ],
            },
        ),
        documents[1],
    )
    completed_repositories = _repositories(
        tasks=_tasks(),
        reports=repositories.reports.list_by_session(SESSION_ID),
        drafts=repositories.report_drafts.list_by_session(SESSION_ID),
        documents=completed_documents,
        artifacts=(repositories.artifacts.get(primary_artifact_id),),
        source_refs=repositories.research_source_refs.list_by_session(SESSION_ID),
    )

    assert (
        policy(
            _context(completed_repositories),
            _step(),  # type: ignore[arg-type]
            _close_invocation(),
        )
        is None
    )

    reporter_without_source = _record(
        document_id=completed_documents[2].document_id,
        document_kind=completed_documents[2].document_kind,
        payload={
            **completed_documents[2].payload,
            "evidence_refs": [f"report:{report_id}"],
        },
    )
    unlinked_repositories = _repositories(
        tasks=_tasks(),
        reports=repositories.reports.list_by_session(SESSION_ID),
        drafts=repositories.report_drafts.list_by_session(SESSION_ID),
        documents=(
            completed_documents[0],
            completed_documents[1],
            reporter_without_source,
            completed_documents[3],
        ),
        artifacts=(repositories.artifacts.get(primary_artifact_id),),
        source_refs=repositories.research_source_refs.list_by_session(SESSION_ID),
    )
    close_delegated = policy(
        _context(unlinked_repositories),
        _step(),  # type: ignore[arg-type]
        _close_invocation(),
    )
    assert close_delegated is None


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


def test_cutover_policy_delegates_close_before_positive_task_exits_to_core() -> None:
    tasks = _tasks(execution_status="in_progress")

    result = _positive_policy()(
        _context(_repositories(tasks=tasks)),
        _step(),  # type: ignore[arg-type]
        _close_invocation(),
    )

    assert result is None


def test_cutover_policy_delegates_teammate_close_to_core() -> None:
    result = _positive_policy()(
        _context(_repositories(tasks=_tasks())),
        _step(actor_kind="teammate"),  # type: ignore[arg-type]
        _close_invocation(),
    )

    assert result is None


def test_cutover_policy_leaves_sealed_attempt_lifecycle_to_core() -> None:
    tasks = _tasks(execution_status="in_progress")
    attempts = (
        _record(
            attempt_id="attempt_001",
            task_id=EXECUTION_TASK_ID,
            status=_status("active"),
        ),
    )
    resolved_head = _record(
        selection=_record(
            selection_id="selection_001",
            state=_status("sealed"),
        ),
    )
    repositories = _repositories(
        tasks=tasks,
        attempts=attempts,
        resolved_head=resolved_head,
    )
    teammate_step = _step(
        actor_kind="teammate",
        agent_id="agent_executor",
    )

    close_result = _positive_policy()(
        _context(repositories),
        teammate_step,  # type: ignore[arg-type]
        _close_invocation(),
    )
    assert close_result is None

    blocked_result = _positive_policy()(
        _context(repositories),
        teammate_step,  # type: ignore[arg-type]
        ToolInvocation(
            call_id="call_blocked_after_seal",
            tool_name="task.finish",
            arguments={
                "task_id": EXECUTION_TASK_ID,
                "status": "blocked",
                "blocked_reason": ("Only the master may close the scientific attempt."),
            },
            task_id=EXECUTION_TASK_ID,
        ),
    )
    assert blocked_result is None

    completed_result = _positive_policy()(
        _context(repositories),
        teammate_step,  # type: ignore[arg-type]
        ToolInvocation(
            call_id="call_completed_after_seal",
            tool_name="task.finish",
            arguments={
                "task_id": EXECUTION_TASK_ID,
                "status": "completed",
                "summary": "Sealed the positive scientific selection.",
            },
            task_id=EXECUTION_TASK_ID,
        ),
    )
    assert completed_result is None


def test_cutover_policy_leaves_preselection_execution_blockers_generic() -> None:
    tasks = _tasks(execution_status="in_progress")
    repositories = _repositories(
        tasks=tasks,
        attempts=(
            _record(
                attempt_id="attempt_001",
                task_id=EXECUTION_TASK_ID,
                status=_status("active"),
            ),
        ),
        resolved_head=_record(
            selection=_record(
                selection_id="selection_001",
                state=_status("draft"),
            ),
        ),
    )
    result = _positive_policy()(
        _context(repositories),
        _step(
            actor_kind="teammate",
            agent_id="agent_executor",
        ),  # type: ignore[arg-type]
        ToolInvocation(
            call_id="call_real_blocker_before_seal",
            tool_name="task.finish",
            arguments={
                "task_id": EXECUTION_TASK_ID,
                "status": "blocked",
                "blocked_reason": "Operator authority is genuinely missing.",
            },
            task_id=EXECUTION_TASK_ID,
        ),
    )

    assert result is None


def test_cutover_policy_leaves_fault_execution_exits_generic() -> None:
    policy = AoxCutoverFormalToolPrecondition(
        session_id=SESSION_ID,
        execution_task_id=EXECUTION_TASK_ID,
        attempt_kind="fault",
    )
    result = policy(
        _context(_repositories(tasks=_tasks(execution_status="in_progress"))),
        _step(
            actor_kind="teammate",
            agent_id="agent_executor",
        ),  # type: ignore[arg-type]
        ToolInvocation(
            call_id="call_fault_blocked",
            tool_name="task.finish",
            arguments={
                "task_id": EXECUTION_TASK_ID,
                "status": "blocked",
                "blocked_reason": "The injected required-artifact fault fired.",
            },
            task_id=EXECUTION_TASK_ID,
        ),
    )

    assert result is None


def test_cutover_policy_does_not_project_task_topology_into_close() -> None:
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
    assert extra_result is None

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
    assert identity_result is None


def test_cutover_policy_does_not_project_finish_receipts_into_close() -> None:
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

    assert result is None


def test_cutover_policy_does_not_project_finish_actor_into_close() -> None:
    tasks = _tasks()
    documents = list(_finish_documents(tasks))
    documents[1] = _record(
        document_kind="task_finish",
        payload={
            "task_id": EXECUTION_TASK_ID,
            "status": "completed",
            "finished_by": "agent:master",
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

    assert result is None


def test_cutover_policy_does_not_project_report_link_into_close() -> None:
    tasks = _tasks()

    result = _positive_policy()(
        _context(_repositories(tasks=tasks)),
        _step(),  # type: ignore[arg-type]
        _close_invocation(),
    )

    assert result is None


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


def test_cutover_policy_allows_r58_published_positive_close() -> None:
    tasks = _tasks()
    reports = (
        _record(
            report_id="report_r58",
            session_id=SESSION_ID,
            task_id=AOX_REPORT_TASK_ID,
            status=_status("published"),
        ),
    )
    drafts = (
        _record(
            draft_id="draft_r58",
            session_id=SESSION_ID,
            task_id=AOX_REPORT_TASK_ID,
            status=_status("published"),
            published_report_id="report_r58",
            content_ref="doc_report_r58",
        ),
    )

    result = _positive_policy()(
        _context(_repositories(tasks=tasks, reports=reports, drafts=drafts)),
        _step(),  # type: ignore[arg-type]
        _close_invocation(),
    )

    assert result is None


def test_cutover_policy_does_not_require_final_response_on_close() -> None:
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
    invocation = ToolInvocation(
        call_id="call_close_without_response",
        tool_name="scientific.attempt.close",
        arguments={
            "attempt_id": "attempt_001",
            "selection_id": "selection_001",
            "idempotency_key": "close:without-response",
        },
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
        invocation,
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


def test_cutover_policy_does_not_project_fault_report_state_into_close() -> None:
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

    assert result is None


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


class _OrdinaryTaskCreateDriver:
    def __init__(self) -> None:
        self.calls = 0

    def plan(
        self,
        context: object,
        harness_input: HarnessInput,
        tool_results: tuple[object, ...],
    ) -> HarnessStep:
        del context, harness_input
        self.calls += 1
        if not tool_results:
            return HarnessStep(
                tool_invocations=(
                    ToolInvocation(
                        call_id="call_ordinary_task_create",
                        tool_name="task.create",
                        arguments={
                            "subject": "Ordinary unpinned task",
                            "description": "Outside the AOX formal session.",
                        },
                    ),
                )
            )
        return HarnessStep(assistant_message="ordinary task created")


def test_repository_backed_policy_leaves_ordinary_session_task_creation_unchanged() -> (
    None
):
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    session = Session.create(
        session_id="sess_ordinary_policy",
        project_id="proj_ordinary_policy",
        title="Ordinary session",
        objective="Keep ordinary task semantics outside AOX formal authority",
    )
    repositories.sessions.save(session)
    driver = _OrdinaryTaskCreateDriver()

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(
            session_id=session.session_id,
            max_steps=2,
            agent_id="agent:master",
            actor_kind="master",
            actor_role="master",
        ),
        driver=driver,
        tool_registry=ToolRegistry(),
        tool_dispatch_precondition=_positive_policy(),
    )

    tasks = repositories.tasks.list_by_session(session.session_id)
    assert result.status is HarnessStatus.COMPLETED
    assert result.tool_results[0].ok is True
    assert driver.calls == 2
    assert len(tasks) == 1
    assert tasks[0].subject == "Ordinary unpinned task"


class _CloseThenMutationDriver:
    def __init__(self, *, attempt_id: str, selection_id: str) -> None:
        self.attempt_id = attempt_id
        self.selection_id = selection_id
        self.calls = 0

    def plan(
        self,
        context: object,
        harness_input: HarnessInput,
        tool_results: tuple[object, ...],
    ) -> HarnessStep:
        del context, harness_input, tool_results
        self.calls += 1
        if self.calls > 1:
            raise AssertionError(
                "successful scientific.attempt.close must retire the turn"
            )
        return HarnessStep(
            tool_invocations=(
                ToolInvocation(
                    call_id="call_repository_close",
                    tool_name="scientific.attempt.close",
                    arguments={
                        "attempt_id": self.attempt_id,
                        "selection_id": self.selection_id,
                        "idempotency_key": "close:repository-backed",
                    },
                    task_id=EXECUTION_TASK_ID,
                    lane_id="lane_execution",
                ),
                ToolInvocation(
                    call_id="call_mutation_after_close",
                    tool_name="task.update",
                    arguments={
                        "task_id": AOX_REPORT_TASK_ID,
                        "subject": "MUTATED AFTER CLOSE",
                    },
                    task_id=AOX_REPORT_TASK_ID,
                ),
            )
        )


def test_repository_backed_positive_close_retires_turn_and_host_observes_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = "2026-07-25T00:00:00+00:00"
    repositories = CoreRepositories.from_connection(connect_sqlite(":memory:"))
    apply_sqlite_migrations(repositories.tasks.connection)
    session = Session(
        session_id=SESSION_ID,
        project_id="proj_formal_policy",
        title="Repository-backed AOX close barrier",
        objective="Prove task, report, close, and turn settlement as one path",
        status=SessionStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    lane = Lane(
        lane_id="lane_execution",
        session_id=SESSION_ID,
        name="execution",
        status=LaneStatus.CLAIMED,
        cwd="/workspace",
        branch_name=None,
        claimed_ref="agent_executor",
        created_at=now,
        updated_at=now,
    )
    agents = (
        AgentMember(
            agent_id="agent:master",
            session_id=SESSION_ID,
            lane_id=None,
            task_id=None,
            name="Master",
            role="master",
            status=AgentMemberStatus.ACTIVE,
            parent_agent_id=None,
            created_at=now,
            updated_at=now,
            member_id="member_master",
        ),
        AgentMember(
            agent_id="agent_researcher",
            session_id=SESSION_ID,
            lane_id=None,
            task_id=AOX_RESEARCH_TASK_ID,
            name="Researcher",
            role="researcher",
            status=AgentMemberStatus.IDLE,
            parent_agent_id="agent:master",
            created_at=now,
            updated_at=now,
            member_id="member_researcher",
        ),
        AgentMember(
            agent_id="agent_executor",
            session_id=SESSION_ID,
            lane_id=lane.lane_id,
            task_id=EXECUTION_TASK_ID,
            name="Executor",
            role="executor",
            status=AgentMemberStatus.IDLE,
            parent_agent_id="agent:master",
            created_at=now,
            updated_at=now,
            member_id="member_executor",
        ),
        AgentMember(
            agent_id="agent_reporter",
            session_id=SESSION_ID,
            lane_id=None,
            task_id=AOX_REPORT_TASK_ID,
            name="Reporter",
            role="reporter",
            status=AgentMemberStatus.IDLE,
            parent_agent_id="agent:master",
            created_at=now,
            updated_at=now,
            member_id="member_reporter",
        ),
    )
    tasks = (
        Task.create(
            task_id=AOX_RESEARCH_TASK_ID,
            session_id=SESSION_ID,
            subject="Collect PubMed evidence",
            description="Canonical research task.",
            kind="research",
            status=TaskStatus.IN_PROGRESS,
            assigned_ref="agent_researcher",
        ),
        Task.create(
            task_id=EXECUTION_TASK_ID,
            session_id=SESSION_ID,
            subject="Execute AOX workflow",
            description="Authority-bound execution task.",
            kind="execution",
            status=TaskStatus.IN_PROGRESS,
            assigned_ref="agent_executor",
            lane_id=lane.lane_id,
        ),
        Task.create(
            task_id=AOX_REPORT_TASK_ID,
            session_id=SESSION_ID,
            subject="Publish source-linked report",
            description="Canonical reporting task.",
            kind="reporting",
            status=TaskStatus.IN_PROGRESS,
            assigned_ref="agent_reporter",
        ),
    )
    repositories.sessions.save(session)
    repositories.lanes.save(lane)
    for task in tasks:
        repositories.tasks.seed_fixture(task)
    for agent in agents:
        repositories.agents.save(agent)
    repositories.sandbox_workspaces.save(
        SandboxWorkspaceRecord(
            sandbox_workspace_id="workspace_execution",
            session_id=SESSION_ID,
            agent_member_id="member_executor",
            agent_id="agent_executor",
            status=SandboxWorkspaceStatus.ATTACHED,
            image_ref="image:aox-test",
            image_digest="sha256:image",
            image_version="1",
            sandbox_protocol_version="1",
            image_compatibility=SandboxImageCompatibility.COMPATIBLE,
            manifest_version="sandbox_workspace_manifest@1",
            focus_task_id=EXECUTION_TASK_ID,
            focus_lane_id=lane.lane_id,
            created_at=now,
            last_attached_at=now,
        )
    )

    scientific = ScientificAttemptService(
        repositories,
        now=lambda: now,
        workflow_contract_registry=(AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY),
    )
    authority = scientific.grant_authorization(
        session_id=SESSION_ID,
        task_id=EXECUTION_TASK_ID,
        campaign_id="campaign_repository_barrier",
        workflow_id=AOX_SELECTED_CHAIN_WORKFLOW_ID,
        root_ref="attempts/repository-barrier",
        grantor_kind="user",
        grantor_ref="user:owner",
        allowed_scopes=(ScientificAttemptScope.FORMAL,),
        allowed_effect_classes=("provider",),
        max_attempts=1,
        max_micu=100,
        max_cost_microunits=1_000,
        max_wall_time_seconds=600,
        expires_at="2026-08-01T00:00:00+00:00",
        idempotency_key="grant:repository-backed",
    )
    attempt = scientific.create_attempt(
        envelope_id=authority.envelope_id,
        session_id=SESSION_ID,
        task_id=EXECUTION_TASK_ID,
        lane_id=lane.lane_id,
        campaign_id="campaign_repository_barrier",
        workflow_id=AOX_SELECTED_CHAIN_WORKFLOW_ID,
        scope=ScientificAttemptScope.FORMAL,
        workflow_contract_digest=AOX_SELECTED_CHAIN_CONTRACT_V2.digest,
        requested_effect_classes=("provider",),
        reserved_micu=1,
        reserved_cost_microunits=10,
        reserved_wall_time_seconds=30,
        actor_ref="agent_executor",
        idempotency_key="attempt:repository-backed",
    )

    run = SandboxRunRecord(
        sandbox_run_id="run_repository_barrier",
        session_id=SESSION_ID,
        sandbox_workspace_id="workspace_execution",
        agent_id="agent_executor",
        task_id=EXECUTION_TASK_ID,
        lane_id=lane.lane_id,
        argv=("python", "aox.py"),
        argv_digest="sha256:argv",
        cwd="/workspace",
        env_digest="sha256:env",
        status=SandboxRunStatus.COMPLETED,
        exit_code=0,
        created_at=now,
        updated_at=now,
        ended_at=now,
    )
    operation = ControlledOperation(
        operation_id="operation_repository_barrier",
        session_id=SESSION_ID,
        sandbox_workspace_id="workspace_execution",
        sandbox_run_id=run.sandbox_run_id,
        task_id=EXECUTION_TASK_ID,
        lane_id=lane.lane_id,
        logical_operation_key="aox.ncbi_fetch",
        operation_digest="sha256:operation",
        params_digest="sha256:params",
        backend_category="fixture",
        selected_backend="fixture",
        route_policy_id="fixture_v1",
        sdk_module="bio",
        function_name="ncbi_fetch_proteins",
        owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
        status=ControlledOperationStatus.COMPLETED,
        created_at=now,
        updated_at=now,
    )
    artifact_set_digest = controlled_operation_artifact_set_digest(())
    execution = ControlledOperationExecution(
        execution_id="execution_repository_barrier",
        operation_id=operation.operation_id,
        session_id=SESSION_ID,
        task_id=EXECUTION_TASK_ID,
        lane_id=lane.lane_id,
        owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
        operation_digest=operation.operation_digest,
        approval_digest=None,
        route_policy_id="fixture_v1",
        selected_backend="fixture",
        adapter_policy_id="fixture_adapter_v1",
        input_identity_digest="sha256:input",
        expected_output_contract_digest="sha256:output",
        runtime_identity_digest="sha256:runtime",
        lifecycle_state=ControlledOperationExecutionLifecycle.TERMINAL,
        terminal_outcome=(ControlledOperationExecutionTerminalOutcome.SUCCEEDED),
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        retry_eligibility=RetryEligibility.TERMINAL,
        dispatch_generation=1,
        state_version=1,
        fencing_token=1,
        result_handle_ref="result_repository_barrier",
        result_digest="sha256:result",
        artifact_set_digest=artifact_set_digest,
        created_at=now,
        updated_at=now,
        terminal_at=now,
    )
    result_handle = ControlledOperationResultHandle(
        result_handle_id="result_repository_barrier",
        execution_id=execution.execution_id,
        operation_id=operation.operation_id,
        session_id=SESSION_ID,
        dispatch_generation=1,
        terminal_outcome=ControlledOperationExecutionTerminalOutcome.SUCCEEDED,
        bounded_result_envelope={"status": "ok"},
        result_digest="sha256:result",
        artifact_set_digest=artifact_set_digest,
        origin="host_supervisor",
        created_at=now,
    )
    with scientific.mutation_scopes.writer_turn(
        session_id=SESSION_ID,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="fixture:repository-barrier",
    ):
        repositories.sandbox_runs.save(run)
        repositories.controlled_operations.save(operation)
        repositories.controlled_operation_executions.add(execution)
        repositories.controlled_operation_results.save_once(result_handle)
        repositories.controlled_operation_result_artifacts.promote(
            result_handle,
            (),
        )
    scientific.bind_run(
        attempt_id=attempt.attempt_id,
        sandbox_run_id=run.sandbox_run_id,
        actor_ref="agent_executor",
    )
    scientific.bind_operation(
        attempt_id=attempt.attempt_id,
        operation_id=operation.operation_id,
        actor_ref="agent_executor",
    )
    selection = scientific.begin_selection(
        attempt_id=attempt.attempt_id,
        actor_ref="agent_executor",
        idempotency_key="selection:repository-backed",
    )
    scientific.adopt_operation(
        selection_id=selection.selection_id,
        operation_id=operation.operation_id,
        workflow_role="ncbi_fetch",
        reason_code="selected_repository_backed_result",
        actor_ref="agent_executor",
        idempotency_key="adopt:repository-backed",
    )
    universe = scientific.operation_universe(attempt.attempt_id)
    scientific.seal_selection(
        selection_id=selection.selection_id,
        actor_ref="agent_executor",
        idempotency_key="seal:repository-backed",
        expected_universe_digest=universe.universe_digest,
    )

    lifecycle_policy = AoxCutoverFormalToolPrecondition(
        session_id=SESSION_ID,
        execution_task_id=EXECUTION_TASK_ID,
        attempt_kind="positive",
    )
    executor_step = _step(
        actor_kind="teammate",
        agent_id="agent_executor",
    )
    blocked_invocation = ToolInvocation(
        call_id="call_repository_blocked_after_seal",
        tool_name="task.finish",
        arguments={
            "task_id": EXECUTION_TASK_ID,
            "status": "blocked",
            "blocked_reason": ("Only the master may close the scientific attempt."),
        },
        task_id=EXECUTION_TASK_ID,
    )
    with scientific.mutation_scopes.writer_turn(
        session_id=SESSION_ID,
        owner_kind=MutationWriterKind.AGENT_TURN,
        owner_ref="agent-turn:repository-backed-executor",
    ):
        ready_evaluation = scientific.evaluate_selection(
            attempt_id=attempt.attempt_id,
            selection_id=selection.selection_id,
        )
        ready_results = []
        for requested_status in ("blocked", "failed", "cancelled"):
            ready_results.append(
                lifecycle_policy(
                    _context(
                        repositories,
                        scientific_workflow_contract_registry=(
                            AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY
                        ),
                    ),
                    executor_step,  # type: ignore[arg-type]
                    ToolInvocation(
                        call_id=(f"call_repository_{requested_status}_after_seal"),
                        tool_name="task.finish",
                        arguments={
                            "task_id": EXECUTION_TASK_ID,
                            "status": requested_status,
                        },
                        task_id=EXECUTION_TASK_ID,
                    ),
                )
            )
    assert ready_evaluation.closure_request_ready is True
    assert ready_evaluation.closure_finalization_ready is False
    assert "selection_active_writers" in ready_evaluation.blocker_codes
    assert ready_results == [None, None, None]

    authority_connection = connect_sqlite(":memory:")
    repositories.tasks.connection.backup(authority_connection)
    authority_repositories = CoreRepositories.from_connection(authority_connection)
    authority_scientific = ScientificAttemptService(
        authority_repositories,
        now=lambda: now,
        workflow_contract_registry=(AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY),
    )
    authority_record = authority_repositories.scientific_attempt_authorizations.get(
        attempt.envelope_id
    )
    assert authority_record is not None
    with authority_scientific.mutation_scopes.writer_turn(
        session_id=SESSION_ID,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="fixture:repository-authority-drift",
    ):
        authority_repositories.scientific_attempt_authorizations.replace_consumption(
            replace(
                authority_record,
                status=ScientificAttemptAuthorityStatus.REVOKED,
                state_version=authority_record.state_version + 1,
                updated_at="2026-07-25T00:00:01+00:00",
            ),
            expected_state_version=authority_record.state_version,
        )
    authority_evaluation = authority_scientific.evaluate_selection(
        attempt_id=attempt.attempt_id,
        selection_id=selection.selection_id,
    )
    assert authority_evaluation.selection_state == "sealed"
    assert authority_evaluation.closure_request_ready is False
    assert "selection_attempt_authority_invalid" in (authority_evaluation.blocker_codes)
    assert (
        lifecycle_policy(
            _context(
                authority_repositories,
                scientific_workflow_contract_registry=(
                    AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY
                ),
            ),
            executor_step,  # type: ignore[arg-type]
            blocked_invocation,
        )
        is None
    )

    universe_connection = connect_sqlite(":memory:")
    repositories.tasks.connection.backup(universe_connection)
    universe_repositories = CoreRepositories.from_connection(universe_connection)
    universe_scientific = ScientificAttemptService(
        universe_repositories,
        now=lambda: now,
        workflow_contract_registry=(AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY),
    )
    drift_run = SandboxRunRecord(
        sandbox_run_id="run_repository_universe_drift",
        session_id=SESSION_ID,
        sandbox_workspace_id="workspace_execution",
        agent_id="agent_executor",
        task_id=EXECUTION_TASK_ID,
        lane_id=lane.lane_id,
        argv=("python", "late.py"),
        argv_digest="sha256:late-argv",
        cwd="/workspace",
        env_digest="sha256:late-env",
        status=SandboxRunStatus.FAILED,
        exit_code=1,
        created_at=now,
        updated_at=now,
        ended_at=now,
    )
    drift_operation = ControlledOperation(
        operation_id="operation_repository_universe_drift",
        session_id=SESSION_ID,
        sandbox_workspace_id="workspace_execution",
        sandbox_run_id=drift_run.sandbox_run_id,
        task_id=EXECUTION_TASK_ID,
        lane_id=lane.lane_id,
        logical_operation_key="aox.late_operation",
        operation_digest="sha256:late-operation",
        params_digest="sha256:late-params",
        backend_category="fixture",
        selected_backend="fixture",
        route_policy_id="fixture_v1",
        sdk_module="bio",
        function_name="ncbi_fetch_proteins",
        owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
        status=ControlledOperationStatus.FAILED,
        created_at=now,
        updated_at=now,
    )
    with universe_scientific.mutation_scopes.writer_turn(
        session_id=SESSION_ID,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="fixture:repository-universe-drift",
    ):
        universe_repositories.sandbox_runs.save(drift_run)
        universe_repositories.controlled_operations.save(drift_operation)
    universe_scientific.bind_operation(
        attempt_id=attempt.attempt_id,
        operation_id=drift_operation.operation_id,
        actor_ref="agent_executor",
    )
    universe_evaluation = universe_scientific.evaluate_selection(
        attempt_id=attempt.attempt_id,
        selection_id=selection.selection_id,
    )
    assert universe_evaluation.selection_state == "sealed"
    assert universe_evaluation.closure_request_ready is False
    assert "selection_universe_changed" in universe_evaluation.blocker_codes
    assert "selection_disposition_incomplete" in (universe_evaluation.blocker_codes)
    assert (
        lifecycle_policy(
            _context(
                universe_repositories,
                scientific_workflow_contract_registry=(
                    AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY
                ),
            ),
            executor_step,  # type: ignore[arg-type]
            blocked_invocation,
        )
        is None
    )

    with scientific.mutation_scopes.writer_turn(
        session_id=SESSION_ID,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="fixture:repository-backed-business-exits",
    ):
        repositories.reports.save(
            SessionReportRecord(
                report_id="report_repository_barrier",
                session_id=SESSION_ID,
                task_id=AOX_REPORT_TASK_ID,
                lane_id=None,
                invocation_id=None,
                run_id=None,
                artifact_id=None,
                status=SessionReportStatus.PUBLISHED,
                title="AOX report",
                summary="Source-linked final report.",
                stage_summary="Research, execution, and reporting complete.",
                created_at=now,
                updated_at=now,
            )
        )
        repositories.report_drafts.save(
            SessionReportDraftRecord(
                draft_id="draft_repository_barrier",
                session_id=SESSION_ID,
                task_id=AOX_REPORT_TASK_ID,
                owner_agent_id="agent_reporter",
                status=SessionReportDraftStatus.PUBLISHED,
                title="AOX report draft",
                summary="Published source-linked draft.",
                content_ref="document:report_repository_barrier",
                published_report_id="report_repository_barrier",
                created_at=now,
                updated_at=now,
            )
        )
        board = TaskBoardService(repositories)
        for task_id, finished_by in (
            (AOX_RESEARCH_TASK_ID, "agent_researcher"),
            (EXECUTION_TASK_ID, "agent_executor"),
            (AOX_REPORT_TASK_ID, "agent_reporter"),
        ):
            board.finish_task(
                task_id,
                TaskFinishCommand(
                    status=TaskStatus.COMPLETED,
                    finished_by=finished_by,
                    summary=f"{task_id} completed by its assigned owner.",
                ),
            )

    report_subject = repositories.tasks.get(AOX_REPORT_TASK_ID).subject

    driver = _CloseThenMutationDriver(
        attempt_id=attempt.attempt_id,
        selection_id=selection.selection_id,
    )
    with scientific.mutation_scopes.writer_turn(
        session_id=SESSION_ID,
        owner_kind=MutationWriterKind.AGENT_TURN,
        owner_ref="agent-turn:repository-backed-executor",
    ):
        result = run_agent_harness_loop(
            repositories,
            HarnessInput(
                session_id=SESSION_ID,
                max_steps=3,
                agent_id="agent_executor",
                actor_kind="teammate",
                actor_role="executor",
            ),
            driver=driver,
            tool_registry=ToolRegistry(),
            scientific_workflow_contract_registry=(
                AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY
            ),
            tool_dispatch_precondition=lifecycle_policy,
        )
        request = repositories.scientific_attempt_closure_requests.get_by_attempt(
            attempt.attempt_id
        )
        assert request is not None
        assert (
            repositories.scientific_attempt_closures.get_by_attempt(attempt.attempt_id)
            is None
        )

    assert result.status is HarnessStatus.COMPLETED
    assert driver.calls == 1
    assert len(result.tool_results) == 2
    close_result, interrupted = result.tool_results
    assert close_result.ok is True
    assert close_result.terminal_action == "scientific.attempt.close"
    assert close_result.terminates_turn is True
    assert "persists_assistant_response" not in close_result.envelope()
    assert result.outputs == ()
    assert interrupted.call_id == "call_mutation_after_close"
    assert interrupted.error_code == "tool_call_batch_interrupted"
    assert interrupted.details == {
        "dispatched": False,
        "effect_certainty": "no_effect",
        "interrupted_by_call_id": "call_repository_close",
        "interruption_reason": "scientific.attempt.close",
        "retry_eligibility": "verify_then_retry",
        "tool_call_position": 2,
    }
    assert repositories.tasks.get(AOX_REPORT_TASK_ID).subject == report_subject
    assert [
        event.payload["call_id"]
        for event in result.events
        if event.event_type == "tool.invoked"
    ] == ["call_repository_close"]
    conversation = build_conversation_projection(repositories, SESSION_ID)
    assert conversation == ()
    host_service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(repositories),
        model_factory=object(),
        scientific_workflow_contract_registry=(
            AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY
        ),
        mutation_writer_scope_factory=lambda **arguments: (
            scientific.mutation_scopes.writer_turn(**arguments)
        ),
    )
    finalized = host_service.finalize_scientific_attempt_closure(
        session_id=SESSION_ID,
        closure_request_id=request.closure_request_id,
    )
    closure = repositories.scientific_attempt_closures.get(
        finalized["record"]["closure_id"]
    )
    assert closure is not None
    assert closure.attempt_id == attempt.attempt_id
    assert closure.actor_ref == "agent_executor"
    closure_signals = [
        signal
        for signal in repositories.runtime_signals.list_by_session(SESSION_ID)
        if signal.source_ref == closure.closure_id
    ]
    assert len(closure_signals) == 1
    assert closure_signals[0].status is AgentRuntimeSignalStatus.PENDING

    def unexpected_model_path(*_args: object, **_kwargs: object) -> object:
        raise AssertionError(
            "terminal closure notification must settle without a model"
        )

    monkeypatch.setattr(
        agent_runtime_module,
        "run_agent_harness_loop",
        unexpected_model_path,
    )
    monkeypatch.setattr(
        agent_runtime_module,
        "run_teammate_loop",
        unexpected_model_path,
    )

    async def invoke_without_executor(
        function: object,
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        return function(*args, **kwargs)  # type: ignore[operator]

    monkeypatch.setattr(asyncio, "to_thread", invoke_without_executor)
    with scientific.mutation_scopes.writer_turn(
        session_id=SESSION_ID,
        owner_kind=MutationWriterKind.RUNTIME_COMMAND,
        owner_ref="runtime-command:scientific-terminal-settlement",
    ):
        drained = host_service.drain_runtime(
            session_id=SESSION_ID,
            max_signals=1,
            max_steps_per_agent=1,
            auto_enqueue_ready_tasks=False,
            worker_id="test:scientific-terminal-settlement",
        )
    settled_signal = repositories.runtime_signals.get(closure_signals[0].signal_id)
    assert drained.status == "completed"
    assert drained.processed_signal_count == 1
    assert settled_signal is not None
    assert settled_signal.status is AgentRuntimeSignalStatus.COMPLETED
    assert repositories.runtime_signals.list_pending_by_session(SESSION_ID) == []
    assert repositories.session_runtime_leases.get_active(SESSION_ID) is None
    assert build_conversation_projection(repositories, SESSION_ID) == conversation
    assert not any(
        event["event_type"] == "scientific.closure_notification.settled"
        for event in drained.events
    )
    historical_response_count = repositories.tasks.connection.execute(
        "SELECT COUNT(*) FROM scientific_attempt_closure_response_records"
    ).fetchone()
    assert historical_response_count is not None
    assert historical_response_count[0] == 0
    persisted_attempt = repositories.scientific_attempts.get(attempt.attempt_id)
    assert persisted_attempt is not None
    assert persisted_attempt.status.value == "active"

    database_path = tmp_path / "host-closed-attempt.sqlite3"
    file_connection = connect_sqlite(str(database_path))
    repositories.tasks.connection.backup(file_connection)
    file_connection.close()
    provider = SQLiteRepositoryProvider(str(database_path))
    observer_runner = object.__new__(LiveAoxAttemptRunner)
    with observer_runner._runtime_barrier_observer(
        provider,
        session_id=SESSION_ID,
        purpose="formal",
        attempt_authority={"attempt_id": attempt.attempt_id},
    ):
        pass
    closed = LiveAoxAttemptRunner._closed_formal_attempt_control(
        SimpleNamespace(),
        provider,
        session_id=SESSION_ID,
        authority={
            "attempt_id": "repository-barrier",
            "envelope_id": authority.envelope_id,
            "task_id": EXECUTION_TASK_ID,
            "lane_id": lane.lane_id,
        },
    )

    assert closed is not None
    control, scope_projection = closed
    assert control["attempt"]["status"] == "closed"
    assert control["closure"]["closure_id"] == closure.closure_id
    assert scope_projection["state"] == "sealed"
    with provider.read() as reader:
        scopes = reader.repositories.mutation_scopes.list_by_session(SESSION_ID)
        assert [
            writer
            for scope in scopes
            for writer in reader.repositories.mutation_writers.list_active(
                scope.scope_id
            )
        ] == []
