from openzyme_domain import CONTROL_PLANE_ENTITY_NAMES
from openzyme_domain import ArtifactKind
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import InboxMessage
from openzyme_domain import InboxParticipantKind
from openzyme_domain import InboxStatus
from openzyme_domain import MemoryEntry
from openzyme_domain import MemoryKind
from openzyme_domain import MemoryScopeKind
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
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus


def test_control_plane_entity_names_are_stable() -> None:
    assert CONTROL_PLANE_ENTITY_NAMES == (
        "Session",
        "Task",
        "Lane",
        "ApprovalRequest",
        "InboxMessage",
        "MemoryEntry",
        "AgentMember",
        "AgentRuntimeSignal",
        "EngineInvocation",
        "RunRecord",
        "SessionArtifactRecord",
        "SessionReportDraftRecord",
        "SessionReportRecord",
        "ResearchSummary",
        "ResearchEvidence",
        "ResearchSourceRef",
        "ResearchGap",
        "SandboxImageRecord",
        "SandboxWorkspaceRecord",
        "SandboxRunRecord",
        "ControlledOperation",
        "ContinuationState",
        "FileAuditEntry",
        "CommandLogArtifactRecord",
    )


def test_session_create_uses_v3_status_defaults() -> None:
    session = Session.create(
        session_id="sess_001",
        project_id="proj_001",
        title="V3 bootstrap",
        objective="Stand up control-plane schema",
    )

    assert session.status is SessionStatus.ACTIVE
    assert session.to_dict()["status"] == "active"
    assert session.title == "V3 bootstrap"


def test_task_to_dict_serializes_priority_and_blockers() -> None:
    task = Task.create(
        task_id="task_001",
        session_id="sess_001",
        subject="Build repositories",
        description="Implement CRUD for V3 tables.",
        priority=TaskPriority.HIGH,
        lane_id="lane_001",
        blocked_by=("task_000",),
    )

    payload = task.to_dict()
    assert payload["priority"] == "high"
    assert payload["status"] == "todo"
    assert payload["lane_id"] == "lane_001"
    assert payload["blocked_by"] == ["task_000"]


def test_terminal_sets_are_explicit_for_v3_statuses() -> None:
    assert TaskStatus.BLOCKED.is_terminal is False
    assert TaskStatus.COMPLETED.is_terminal is True
    assert TaskStatus.FAILED.is_terminal is True
    assert InboxStatus.DELIVERED.is_terminal is False
    assert InboxStatus.ACKNOWLEDGED.is_terminal is True
    assert EngineInvocationStatus.RUNNING.is_terminal is False
    assert EngineInvocationStatus.SUCCEEDED.is_terminal is True


def test_memory_and_inbox_records_use_typed_scope_and_participant_kinds() -> None:
    memory = MemoryEntry(
        memory_id="mem_001",
        session_id="sess_001",
        scope_kind=MemoryScopeKind.SESSION,
        scope_ref="sess_001",
        kind=MemoryKind.CONTINUITY,
        summary="The session was paused after approval wait.",
        source_range="turns:4-8",
        importance=5,
        created_at="2026-04-16T10:00:00+00:00",
    )
    message = InboxMessage(
        message_id="msg_001",
        session_id="sess_001",
        sender="user:alice",
        sender_kind=InboxParticipantKind.USER,
        recipient="harness:host",
        recipient_kind=InboxParticipantKind.HARNESS,
        message_type="resume",
        correlation_id="corr_001",
        payload_ref="artifact://messages/msg_001.json",
        status=InboxStatus.PENDING,
        created_at="2026-04-16T10:01:00+00:00",
    )

    assert memory.to_dict()["scope_kind"] == "session"
    assert memory.to_dict()["kind"] == "continuity"
    assert message.to_dict()["sender_kind"] == "user"
    assert message.to_dict()["recipient_kind"] == "harness"


def test_research_summary_records_use_v3_control_plane_fields() -> None:
    summary = ResearchSummary(
        summary_id="inv_001:summary",
        session_id="sess_001",
        task_id="task_001",
        lane_id="lane_001",
        invocation_id="inv_001",
        status=ResearchSummaryStatus.NEEDS_CLARIFICATION,
        completion_reason="clarification_requested",
        research_brief="Collect catalytic literature",
        summary="Research needs clarification before continuing.",
        clarification_question="Which enzyme family should the search focus on?",
        created_at="2026-04-20T10:00:00+00:00",
        updated_at="2026-04-20T10:01:00+00:00",
    )

    payload = summary.to_dict()
    assert payload["status"] == "needs_clarification"
    assert payload["invocation_id"] == "inv_001"
    assert SourceRefKind.WEB_PAGE.value == "web_page"


def test_execution_records_serialize_with_v3_session_scope() -> None:
    run = RunRecord(
        run_id="run_001",
        session_id="sess_001",
        task_id="task_001",
        lane_id="lane_001",
        invocation_id="inv_001",
        approval_id="appr_001",
        engine_name="execution",
        runner_run_id="job_123",
        status=RunStatus.RUNNING,
        execution_mode="sbatch",
        remote_run_dir="/remote/run_001",
        summary=None,
        created_at="2026-04-20T10:00:00+00:00",
        updated_at="2026-04-20T10:00:00+00:00",
    )
    artifact = SessionArtifactRecord(
        artifact_id="run_001:stdout.log",
        session_id="sess_001",
        task_id="task_001",
        lane_id="lane_001",
        invocation_id="inv_001",
        run_id="run_001",
        kind=ArtifactKind.LOG,
        storage_uri="/tmp/stdout.log",
        relative_path="stdout.log",
        title="stdout.log",
        description=None,
        metadata={"source": "execution_engine"},
        created_at="2026-04-20T10:01:00+00:00",
    )

    assert run.to_dict()["status"] == "running"
    assert artifact.to_dict()["kind"] == "log"
    assert artifact.to_dict()["session_id"] == "sess_001"


def test_session_report_records_serialize_with_v3_scope() -> None:
    report = SessionReportRecord(
        report_id="report_001",
        session_id="sess_001",
        task_id="task_001",
        lane_id="lane_001",
        invocation_id="inv_001",
        run_id="run_001",
        artifact_id="inv_001:report",
        status=SessionReportStatus.READY,
        title="Final report",
        summary="Report summary",
        stage_summary="Research summary: ok",
        created_at="2026-04-20T10:02:00+00:00",
        updated_at="2026-04-20T10:03:00+00:00",
    )

    assert report.to_dict()["status"] == "ready"
    assert report.to_dict()["session_id"] == "sess_001"


def test_session_report_draft_records_serialize_with_v3_scope() -> None:
    draft = SessionReportDraftRecord(
        draft_id="draft_001",
        session_id="sess_001",
        task_id="task_001",
        owner_agent_id="agent:reporter",
        status=SessionReportDraftStatus.IN_REVIEW,
        title="Draft report",
        summary="Draft summary",
        content_ref="doc_001",
        published_report_id=None,
        created_at="2026-04-20T10:02:00+00:00",
        updated_at="2026-04-20T10:03:00+00:00",
    )

    assert draft.to_dict()["status"] == "in_review"
    assert draft.to_dict()["owner_agent_id"] == "agent:reporter"
