from __future__ import annotations

from openzyme_core import CoreRepositories
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import ArtifactKind
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import Lane
from openzyme_domain import LaneStatus
from openzyme_domain import ResearchSummary
from openzyme_domain import ResearchSummaryStatus
from openzyme_domain import RunRecord
from openzyme_domain import RunStatus
from openzyme_domain import Session
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_engines import ReportingEngine
from openzyme_engines import register_reporting_tools


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _seed_session(repositories: CoreRepositories) -> Session:
    session = Session(
        session_id="sess_001",
        project_id="proj_001",
        title="Reporting",
        objective="Create a workspace report",
        status=SessionStatus.ACTIVE,
        created_at="2026-04-20T12:00:00+00:00",
        updated_at="2026-04-20T12:00:00+00:00",
    )
    repositories.sessions.save(session)
    repositories.lanes.save(
        Lane(
            lane_id="lane_001",
            session_id=session.session_id,
            name="analysis",
            status=LaneStatus.CLAIMED,
            cwd="/tmp/analysis",
            branch_name="wt/analysis",
            claimed_ref="agent:planner",
            created_at="2026-04-20T12:00:01+00:00",
            updated_at="2026-04-20T12:00:01+00:00",
        )
    )
    repositories.tasks.save(
        Task(
            task_id="task_001",
            session_id=session.session_id,
            subject="Summarize the run",
            description="Turn research and execution into a concise report.",
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.HIGH,
            kind="reporting",
            assigned_ref="agent:planner",
            created_at="2026-04-20T12:00:02+00:00",
            updated_at="2026-04-20T12:00:02+00:00",
            lane_id="lane_001",
        )
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_research_001",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            engine_name="deep_research",
            status=EngineInvocationStatus.SUCCEEDED,
            input_ref="eng_in_research_001",
            output_ref="eng_out_research_001",
            approval_id=None,
            idempotency_key="task_001:deep_research:1",
            started_at="2026-04-20T12:00:03+00:00",
            finished_at="2026-04-20T12:00:04+00:00",
        )
    )
    repositories.research_summaries.save(
        ResearchSummary(
            summary_id="inv_research_001:summary",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            invocation_id="inv_research_001",
            status=ResearchSummaryStatus.COMPLETED,
            completion_reason="research_completed",
            research_brief="Summarize the evidence",
            summary="Research indicates the candidate remains promising.",
            clarification_question=None,
            created_at="2026-04-20T12:00:04+00:00",
            updated_at="2026-04-20T12:00:04+00:00",
        )
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_exec_001",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            engine_name="execution",
            status=EngineInvocationStatus.SUCCEEDED,
            input_ref="eng_in_exec_001",
            output_ref="eng_out_exec_001",
            approval_id=None,
            idempotency_key="task_001:execution:1",
            started_at="2026-04-20T12:00:05+00:00",
            finished_at="2026-04-20T12:00:06+00:00",
        )
    )
    repositories.runs.save(
        RunRecord(
            run_id="run_exec_001",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            invocation_id="inv_exec_001",
            approval_id=None,
            engine_name="execution",
            runner_run_id="job_123",
            status=RunStatus.SUCCEEDED,
            execution_mode="sbatch",
            remote_run_dir="/remote/run_001",
            summary="Execution found one promising pocket.",
            created_at="2026-04-20T12:00:05+00:00",
            updated_at="2026-04-20T12:00:06+00:00",
            finished_at="2026-04-20T12:00:06+00:00",
        )
    )
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="run_exec_001:stdout.log",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            invocation_id="inv_exec_001",
            run_id="run_exec_001",
            kind=ArtifactKind.LOG,
            storage_uri="/tmp/stdout.log",
            relative_path="stdout.log",
            title="stdout.log",
            description=None,
            metadata={"source": "execution_engine"},
            created_at="2026-04-20T12:00:06+00:00",
        )
    )
    return session


def test_reporting_engine_persists_row_document_and_artifact() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = ReportingEngine(repositories)

    result = engine.start_report(
        session_id=session.session_id,
        task_id="task_001",
        report_brief="Produce a concise final report.",
        invocation_id="inv_report_001",
    )

    assert result.invocation.status is EngineInvocationStatus.SUCCEEDED
    assert result.report.status.value == "ready"
    assert result.artifact.kind is ArtifactKind.REPORT
    assert repositories.reports.get_by_invocation(session.session_id, "inv_report_001") == result.report
    assert repositories.engine_documents.get(result.invocation.output_ref).document_kind == "report_document"  # type: ignore[arg-type]


def test_reporting_tools_return_report_payload() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = ReportingEngine(repositories)
    registry = ToolRegistry()
    register_reporting_tools(registry, engine)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id="task_001", lane_id="lane_001"),
    )

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_001",
            tool_name="reporting.start",
            arguments={"task_id": "task_001", "report_brief": "Create a report"},
            task_id="task_001",
            lane_id="lane_001",
        ),
    )

    assert result.ok is True
    assert "report" in result.content
