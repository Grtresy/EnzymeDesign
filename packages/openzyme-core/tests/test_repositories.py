from dataclasses import replace

from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import InboxMessage
from openzyme_domain import InboxParticipantKind
from openzyme_domain import InboxStatus
from openzyme_domain import Lane
from openzyme_domain import LaneStatus
from openzyme_domain import MemoryEntry
from openzyme_domain import MemoryKind
from openzyme_domain import MemoryScopeKind
from openzyme_domain import ResearchEvidence
from openzyme_domain import ResearchGap
from openzyme_domain import ResearchSourceRef
from openzyme_domain import ResearchSummary
from openzyme_domain import ResearchSummaryStatus
from openzyme_domain import RunRecord
from openzyme_domain import RunStatus
from openzyme_domain import Session
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SessionReportDraftRecord
from openzyme_domain import SessionReportDraftStatus
from openzyme_domain import SessionReportRecord
from openzyme_domain import SessionReportStatus
from openzyme_domain import SessionStatus
from openzyme_domain import SourceRefKind
from openzyme_domain import ArtifactKind
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_core import CoreRepositories
from openzyme_core import EngineDocumentRecord
from openzyme_core import LaneLifecycleEventRecord
from openzyme_core import OwnershipError
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite


def test_core_repositories_persist_v3_control_plane_records() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)

    session = Session(
        session_id="sess_001",
        project_id="proj_001",
        title="Thermostability redesign",
        objective="Move V3 control-plane work forward",
        status=SessionStatus.ACTIVE,
        created_at="2026-04-16T10:00:00+00:00",
        updated_at="2026-04-16T10:00:00+00:00",
    )
    root_task = Task(
        task_id="task_root",
        session_id=session.session_id,
        subject="Research scaffold",
        description="Collect the first scaffold shortlist.",
        status=TaskStatus.COMPLETED,
        priority=TaskPriority.HIGH,
        kind="research",
        assigned_ref="agent:host",
        created_at="2026-04-16T10:01:00+00:00",
        updated_at="2026-04-16T10:02:00+00:00",
    )
    child_task = Task(
        task_id="task_exec",
        session_id=session.session_id,
        subject="Prepare execution handoff",
        description="Turn the shortlist into an execution plan.",
        status=TaskStatus.TODO,
        priority=TaskPriority.NORMAL,
        kind="execution",
        assigned_ref="agent:planner",
        created_at="2026-04-16T10:03:00+00:00",
        updated_at="2026-04-16T10:03:00+00:00",
        lane_id="lane_001",
        blocked_by=(root_task.task_id,),
    )
    lane = Lane(
        lane_id="lane_001",
        session_id=session.session_id,
        name="analysis",
        status=LaneStatus.CLAIMED,
        cwd="/tmp/lane_001",
        branch_name="v3/session-02",
        claimed_ref="agent:planner",
        created_at="2026-04-16T10:04:00+00:00",
        updated_at="2026-04-16T10:04:00+00:00",
    )
    approval = ApprovalRequest(
        approval_id="appr_001",
        session_id=session.session_id,
        task_id=child_task.task_id,
        lane_id=lane.lane_id,
        kind="execution_launch",
        requested_action="Approve the first HPC launch",
        status=ApprovalRequestStatus.PENDING,
        request_ref="artifact://approval/appr_001/request.json",
        resolution_ref=None,
        created_at="2026-04-16T10:05:00+00:00",
    )
    inbox = InboxMessage(
        message_id="msg_001",
        session_id=session.session_id,
        sender="user:alice",
        sender_kind=InboxParticipantKind.USER,
        recipient="agent:planner",
        recipient_kind=InboxParticipantKind.AGENT,
        message_type="task_update",
        correlation_id="corr_001",
        payload_ref="artifact://messages/msg_001.json",
        status=InboxStatus.DELIVERED,
        created_at="2026-04-16T10:06:00+00:00",
    )
    memory = MemoryEntry(
        memory_id="mem_001",
        session_id=session.session_id,
        scope_kind=MemoryScopeKind.TASK,
        scope_ref=child_task.task_id,
        kind=MemoryKind.SUMMARY,
        summary="Execution should wait for scaffold evidence sign-off.",
        source_range="turns:1-3",
        importance=7,
        created_at="2026-04-16T10:07:00+00:00",
    )
    agent = AgentMember(
        agent_id="agent_001",
        session_id=session.session_id,
        lane_id=lane.lane_id,
        task_id=child_task.task_id,
        name="Planner",
        role="execution_planner",
        status=AgentMemberStatus.ACTIVE,
        parent_agent_id=None,
        created_at="2026-04-16T10:08:00+00:00",
        updated_at="2026-04-16T10:08:00+00:00",
    )
    invocation = EngineInvocation(
        invocation_id="inv_001",
        session_id=session.session_id,
        task_id=child_task.task_id,
        lane_id=lane.lane_id,
        engine_name="deep_research",
        status=EngineInvocationStatus.WAITING_APPROVAL,
        input_ref="artifact://engine/inv_001/input.json",
        output_ref=None,
        approval_id=approval.approval_id,
        idempotency_key="task_exec:deep_research:v1",
        started_at="2026-04-16T10:09:00+00:00",
    )
    run = RunRecord(
        run_id="run_001",
        session_id=session.session_id,
        task_id=child_task.task_id,
        lane_id=lane.lane_id,
        invocation_id="inv_001",
        approval_id=approval.approval_id,
        engine_name="execution",
        runner_run_id="job_123",
        status=RunStatus.QUEUED,
        execution_mode="sbatch",
        remote_run_dir="/remote/run_001",
        summary=None,
        created_at="2026-04-16T10:09:10+00:00",
        updated_at="2026-04-16T10:09:10+00:00",
    )
    artifact = SessionArtifactRecord(
        artifact_id="run_001:stdout.log",
        session_id=session.session_id,
        task_id=child_task.task_id,
        lane_id=lane.lane_id,
        invocation_id="inv_001",
        run_id="run_001",
        kind=ArtifactKind.LOG,
        storage_uri="/tmp/stdout.log",
        relative_path="stdout.log",
        title="stdout.log",
        description=None,
        metadata={"source": "execution_engine"},
        created_at="2026-04-16T10:09:11+00:00",
    )
    report = SessionReportRecord(
        report_id="report_001",
        session_id=session.session_id,
        task_id=child_task.task_id,
        lane_id=lane.lane_id,
        invocation_id=invocation.invocation_id,
        run_id=run.run_id,
        artifact_id=artifact.artifact_id,
        status=SessionReportStatus.READY,
        title="Execution report",
        summary="Execution summary",
        stage_summary="Research summary: done",
        created_at="2026-04-16T10:09:12+00:00",
        updated_at="2026-04-16T10:09:12+00:00",
    )
    draft = SessionReportDraftRecord(
        draft_id="draft_001",
        session_id=session.session_id,
        task_id=child_task.task_id,
        owner_agent_id=agent.agent_id,
        status=SessionReportDraftStatus.IN_REVIEW,
        title="Execution draft",
        summary="Draft summary",
        content_ref="doc_002",
        published_report_id=report.report_id,
        created_at="2026-04-16T10:09:12+00:00",
        updated_at="2026-04-16T10:09:13+00:00",
    )
    lane_event = LaneLifecycleEventRecord(
        event_id="lane_evt_001",
        session_id=session.session_id,
        lane_id=lane.lane_id,
        task_id=child_task.task_id,
        event_type="task.bound_to_lane",
        created_at="2026-04-16T10:09:30+00:00",
        payload={"task_id": child_task.task_id},
    )

    repositories.sessions.save(session)
    repositories.tasks.save(root_task)
    repositories.lanes.save(lane)
    repositories.tasks.save(child_task)
    repositories.approvals.save(approval)
    repositories.inbox.save(inbox)
    repositories.memory.save(memory)
    repositories.agents.save(agent)
    repositories.invocations.save(invocation)
    repositories.runs.save(run)
    repositories.artifacts.save(artifact)
    repositories.reports.save(report)
    repositories.report_drafts.save(draft)
    repositories.lane_events.save(lane_event)
    repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id="doc_001",
            session_id=session.session_id,
            invocation_id=invocation.invocation_id,
            document_kind="deep_research_dossier",
            payload={"summary": "Initial dossier"},
            created_at="2026-04-16T10:09:31+00:00",
            updated_at="2026-04-16T10:09:31+00:00",
        )
    )
    repositories.research_summaries.save(
        ResearchSummary(
            summary_id="inv_001:summary",
            session_id=session.session_id,
            task_id=child_task.task_id,
            lane_id=lane.lane_id,
            invocation_id=invocation.invocation_id,
            status=ResearchSummaryStatus.COMPLETED,
            completion_reason="research_completed",
            research_brief="Collect scaffold evidence",
            summary="Research finished with one evidence item.",
            clarification_question=None,
            created_at="2026-04-16T10:09:32+00:00",
            updated_at="2026-04-16T10:09:32+00:00",
        )
    )
    repositories.research_evidence.save(
        ResearchEvidence(
            evidence_id="inv_001:evidence:1",
            session_id=session.session_id,
            task_id=child_task.task_id,
            lane_id=lane.lane_id,
            invocation_id=invocation.invocation_id,
            summary_id="inv_001:summary",
            summary="Scaffold A is literature-backed.",
            query="scaffold A evidence",
            confidence_label="high",
            created_at="2026-04-16T10:09:33+00:00",
        )
    )
    repositories.research_source_refs.save(
        ResearchSourceRef(
            source_ref_id="inv_001:evidence:1:source:1",
            session_id=session.session_id,
            task_id=child_task.task_id,
            lane_id=lane.lane_id,
            invocation_id=invocation.invocation_id,
            evidence_id="inv_001:evidence:1",
            title="Paper A",
            locator="https://example.org/paper-a",
            kind=SourceRefKind.PAPER,
            snippet="Thermostability signal",
            created_at="2026-04-16T10:09:34+00:00",
        )
    )
    repositories.research_gaps.save(
        ResearchGap(
            gap_id="inv_001:gap:1",
            session_id=session.session_id,
            task_id=child_task.task_id,
            lane_id=lane.lane_id,
            invocation_id=invocation.invocation_id,
            summary_id="inv_001:summary",
            summary="Need wet-lab validation",
            created_at="2026-04-16T10:09:35+00:00",
        )
    )

    assert repositories.sessions.get(session.session_id) == session
    assert repositories.tasks.list_by_session(session.session_id) == [root_task, child_task]
    assert repositories.tasks.list_by_lane(session.session_id, lane.lane_id) == [child_task]
    assert repositories.tasks.get(child_task.task_id) == child_task
    assert repositories.lane_events.list_by_lane(session.session_id, lane.lane_id) == [lane_event]
    assert repositories.approvals.list_pending_by_session(session.session_id) == [approval]
    assert repositories.inbox.list_by_session(session.session_id) == [inbox]
    assert repositories.memory.list_by_scope(
        session.session_id, MemoryScopeKind.TASK, child_task.task_id
    ) == [memory]
    assert repositories.agents.list_by_session(session.session_id) == [agent]
    assert repositories.invocations.list_by_session(session.session_id) == [invocation]
    assert repositories.invocations.list_active_by_session(session.session_id) == [invocation]
    assert repositories.runs.get_by_invocation(session.session_id, invocation.invocation_id) == run
    assert repositories.artifacts.list_by_run(run.run_id) == [artifact]
    assert repositories.report_drafts.get(draft.draft_id) == draft
    assert repositories.report_drafts.get_by_task(session.session_id, child_task.task_id) == draft
    assert repositories.reports.get_by_invocation(session.session_id, invocation.invocation_id) == report
    assert repositories.engine_documents.list_by_invocation(session.session_id, invocation.invocation_id)[0].payload == {
        "summary": "Initial dossier"
    }
    assert repositories.research_summaries.get_by_invocation(session.session_id, invocation.invocation_id).summary == (
        "Research finished with one evidence item."
    )
    assert repositories.research_evidence.list_by_invocation(session.session_id, invocation.invocation_id)[0].query == (
        "scaffold A evidence"
    )
    assert repositories.research_source_refs.list_by_evidence("inv_001:evidence:1")[0].kind is SourceRefKind.PAPER
    assert repositories.research_gaps.list_by_invocation(session.session_id, invocation.invocation_id)[0].summary == (
        "Need wet-lab validation"
    )


def test_task_ready_query_filters_out_blocked_work() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)

    session = Session.create(
        session_id="sess_001",
        project_id="proj_001",
        title="Ready query",
        objective="Check ready tasks",
    )
    repositories.sessions.save(session)
    repositories.tasks.save(
        Task.create(
            task_id="task_a",
            session_id=session.session_id,
            subject="A",
            description="done blocker",
            status=TaskStatus.COMPLETED,
        )
    )
    repositories.tasks.save(
        Task.create(
            task_id="task_b",
            session_id=session.session_id,
            subject="B",
            description="ready work",
        )
    )
    repositories.tasks.save(
        Task.create(
            task_id="task_c",
            session_id=session.session_id,
            subject="C",
            description="blocked work",
            blocked_by=("task_a",),
        )
    )
    repositories.tasks.save(
        Task.create(
            task_id="task_d",
            session_id=session.session_id,
            subject="D",
            description="still blocked",
        )
    )
    repositories.tasks.save(
        Task(
            task_id="task_e",
            session_id=session.session_id,
            subject="E",
            description="blocks another task",
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.NORMAL,
            kind="general",
            assigned_ref=None,
            created_at="2026-04-16T10:00:05+00:00",
            updated_at="2026-04-16T10:00:05+00:00",
        )
    )
    repositories.tasks.save(
        Task.create(
            task_id="task_f",
            session_id=session.session_id,
            subject="F",
            description="blocked on active task",
            blocked_by=("task_e",),
        )
    )

    ready_ids = [task.task_id for task in repositories.tasks.list_ready_by_session(session.session_id)]
    assert ready_ids == ["task_b", "task_c", "task_d"]


def test_task_repository_rejects_cross_session_lane_binding() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)

    repositories.sessions.save(Session.create("sess_a", "proj_001", "A", "A"))
    repositories.sessions.save(Session.create("sess_b", "proj_001", "B", "B"))
    repositories.lanes.save(
        Lane(
            lane_id="lane_a",
            session_id="sess_a",
            name="lane a",
            status=LaneStatus.IDLE,
            cwd="/tmp/lane_a",
            branch_name=None,
            claimed_ref=None,
            created_at="2026-04-16T10:00:00+00:00",
            updated_at="2026-04-16T10:00:00+00:00",
        )
    )

    try:
        repositories.tasks.save(Task.create("task_b", "sess_b", "B", "B", lane_id="lane_a"))
    except OwnershipError as exc:
        assert "belongs to session 'sess_a'" in str(exc)
    else:
        raise AssertionError("expected OwnershipError")


def test_repository_ownership_checks_reject_cross_session_links() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)

    repositories.sessions.save(Session.create("sess_a", "proj_001", "A", "A"))
    repositories.sessions.save(Session.create("sess_b", "proj_001", "B", "B"))
    repositories.tasks.save(
        Task.create("task_a", "sess_a", "A", "A")
    )

    try:
        repositories.tasks.save(
            Task.create(
                "task_b",
                "sess_b",
                "B",
                "B",
                blocked_by=("task_a",),
            )
        )
    except OwnershipError as exc:
        assert "belongs to session 'sess_a'" in str(exc)
    else:
        raise AssertionError("expected OwnershipError")


def test_memory_scope_checks_require_existing_scope_records() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)

    session = Session.create("sess_001", "proj_001", "Memory", "Memory")
    repositories.sessions.save(session)

    try:
        repositories.memory.save(
            MemoryEntry(
                memory_id="mem_missing",
                session_id=session.session_id,
                scope_kind=MemoryScopeKind.LANE,
                scope_ref="lane_missing",
                kind=MemoryKind.COMPACTION,
                summary="Missing lane",
                source_range=None,
                importance=3,
                created_at="2026-04-16T10:00:00+00:00",
            )
        )
    except OwnershipError as exc:
        assert "lanes.lane_id='lane_missing' does not exist" in str(exc)
    else:
        raise AssertionError("expected OwnershipError")


def test_runtime_signal_repository_claims_leases_and_recovers_stale_claims() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)

    session = Session.create("sess_lease", "proj_001", "Lease", "Lease")
    repositories.sessions.save(session)
    agent = AgentMember(
        agent_id="agent:researcher",
        session_id=session.session_id,
        lane_id=None,
        task_id=None,
        name="Researcher",
        role="researcher",
        status=AgentMemberStatus.IDLE,
        parent_agent_id=None,
        created_at="2026-04-16T10:00:00+00:00",
        updated_at="2026-04-16T10:00:00+00:00",
    )
    repositories.agents.save(agent)
    signal = AgentRuntimeSignal(
        signal_id="sig_lease",
        session_id=session.session_id,
        agent_id=agent.agent_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        status=AgentRuntimeSignalStatus.PENDING,
        created_at="2026-04-16T10:00:01+00:00",
        source_ref="manual:1",
    )
    repositories.runtime_signals.save(signal)

    claimed = repositories.runtime_signals.claim_next(
        session_id=session.session_id,
        claimed_by="worker:a",
        lease_seconds=60,
    )
    assert claimed is not None
    assert claimed.status is AgentRuntimeSignalStatus.CLAIMED
    assert claimed.claimed_by == "worker:a"
    assert claimed.claim_expires_at is not None
    assert claimed.attempt_count == 1
    assert repositories.runtime_signals.claim_next(
        session_id=session.session_id,
        claimed_by="worker:b",
    ) is None
    assert repositories.runtime_signals.find_pending_duplicate(
        session_id=session.session_id,
        agent_id=agent.agent_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        source_ref="manual:1",
    ) == claimed

    repositories.runtime_signals.save(
        replace(claimed, claim_expires_at="2020-01-01T00:00:00+00:00")
    )
    reclaimed = repositories.runtime_signals.claim_next(
        session_id=session.session_id,
        claimed_by="worker:b",
    )
    assert reclaimed is not None
    assert reclaimed.claimed_by == "worker:b"
    assert reclaimed.attempt_count == 2


def test_runtime_signal_repository_completion_and_retry_failure_are_idempotent() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)

    session = Session.create("sess_retry", "proj_001", "Retry", "Retry")
    repositories.sessions.save(session)
    repositories.agents.save(
        AgentMember(
            agent_id="agent:executor",
            session_id=session.session_id,
            lane_id=None,
            task_id=None,
            name="Executor",
            role="executor",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at="2026-04-16T10:00:00+00:00",
            updated_at="2026-04-16T10:00:00+00:00",
        )
    )
    completed_signal = AgentRuntimeSignal(
        signal_id="sig_complete",
        session_id=session.session_id,
        agent_id="agent:executor",
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        status=AgentRuntimeSignalStatus.PENDING,
        created_at="2026-04-16T10:00:01+00:00",
    )
    retry_signal = replace(completed_signal, signal_id="sig_retry")
    repositories.runtime_signals.save(completed_signal)
    repositories.runtime_signals.save(retry_signal)

    first_complete = repositories.runtime_signals.complete("sig_complete")
    second_complete = repositories.runtime_signals.complete("sig_complete")
    assert first_complete is not None
    assert second_complete == first_complete
    assert second_complete.status is AgentRuntimeSignalStatus.COMPLETED

    claimed = repositories.runtime_signals.claim_next(
        session_id=session.session_id,
        claimed_by="worker:a",
        signal_ids={"sig_retry"},
    )
    assert claimed is not None
    retryable = repositories.runtime_signals.fail(
        "sig_retry",
        error_message="transient provider error",
        retryable=True,
        max_attempts=2,
    )
    assert retryable is not None
    assert retryable.status is AgentRuntimeSignalStatus.PENDING
    assert retryable.last_error == "transient provider error"

    claimed_again = repositories.runtime_signals.claim_next(
        session_id=session.session_id,
        claimed_by="worker:b",
        signal_ids={"sig_retry"},
    )
    assert claimed_again is not None
    final = repositories.runtime_signals.fail(
        "sig_retry",
        error_message="still failing",
        retryable=True,
        max_attempts=2,
    )
    assert final is not None
    assert final.status is AgentRuntimeSignalStatus.FAILED
    assert final.completed_at is not None
    assert final.last_error == "still failing"
