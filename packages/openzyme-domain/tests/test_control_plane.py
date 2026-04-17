from openzyme_domain import CONTROL_PLANE_ENTITY_NAMES
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import InboxMessage
from openzyme_domain import InboxParticipantKind
from openzyme_domain import InboxStatus
from openzyme_domain import MemoryEntry
from openzyme_domain import MemoryKind
from openzyme_domain import MemoryScopeKind
from openzyme_domain import Session
from openzyme_domain import SessionStatus
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
        "EngineInvocation",
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
        blocked_by=("task_000",),
    )

    payload = task.to_dict()
    assert payload["priority"] == "high"
    assert payload["status"] == "todo"
    assert payload["blocked_by"] == ["task_000"]


def test_terminal_sets_are_explicit_for_v3_statuses() -> None:
    assert TaskStatus.BLOCKED.is_terminal is False
    assert TaskStatus.COMPLETED.is_terminal is True
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
