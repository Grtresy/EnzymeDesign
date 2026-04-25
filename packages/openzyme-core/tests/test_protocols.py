from __future__ import annotations

import json

from openzyme_domain import AgentMemberStatus
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import InboxParticipantKind
from openzyme_domain import InboxStatus
from openzyme_domain import Lane
from openzyme_domain import LaneStatus
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_core import CoreRepositories
from openzyme_core import CorrelationStatus
from openzyme_core import ProtocolService
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import register_protocol_tools


class FakeToolCallingInvoker:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def invoke_with_tools(self, *, system_prompt: str, messages: list[object], tools: list[object]) -> object:
        self.calls.append({"system_prompt": system_prompt, "messages": list(messages), "tools": list(tools)})
        if isinstance(self.response, list):
            index = min(len(self.calls) - 1, len(self.response) - 1)
            return self.response[index]
        return self.response


class FakeModelFactory:
    def __init__(self, response: object | dict[str, object]) -> None:
        self.response = response
        self.invokers: dict[str, FakeToolCallingInvoker] = {}

    def create_tool_calling_invoker(self, *, purpose: str) -> FakeToolCallingInvoker:
        if purpose not in self.invokers:
            if isinstance(self.response, dict) and purpose in self.response:
                response = self.response[purpose]
            else:
                response = self.response
            self.invokers[purpose] = FakeToolCallingInvoker(response)
        return self.invokers[purpose]


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _seed_session(repositories: CoreRepositories) -> Session:
    session = Session(
        session_id="sess_001",
        project_id="proj_001",
        title="Protocols",
        objective="Exercise Session 06 protocol behavior",
        status=SessionStatus.ACTIVE,
        created_at="2026-04-17T12:00:00+00:00",
        updated_at="2026-04-17T12:00:00+00:00",
    )
    repositories.sessions.save(session)
    repositories.lanes.save(
        Lane(
            lane_id="lane_001",
            session_id=session.session_id,
            name="analysis",
            status=LaneStatus.CLAIMED,
            cwd="/tmp/analysis",
            branch_name=None,
            claimed_ref="agent:planner",
            created_at="2026-04-17T12:00:01+00:00",
            updated_at="2026-04-17T12:00:01+00:00",
        )
    )
    repositories.tasks.save(
        Task(
            task_id="task_001",
            session_id=session.session_id,
            subject="Analyze",
            description="Primary delegated task",
            status=TaskStatus.TODO,
            priority=TaskPriority.HIGH,
            kind="research",
            assigned_ref="agent:planner",
            created_at="2026-04-17T12:00:02+00:00",
            updated_at="2026-04-17T12:00:02+00:00",
            lane_id="lane_001",
        )
    )
    return session


def test_protocol_service_builds_correlation_threads_for_delegation() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = ProtocolService(repositories)

    envelope = service.delegate(
        session_id=session.session_id,
        agent_id="agent:researcher",
        name="Researcher",
        role="delegate",
        payload_ref="artifact://delegations/deleg_001.json",
        task_id="task_001",
        correlation_id="corr_001",
    )
    response = service.reply(
        session_id=session.session_id,
        sender="agent:researcher",
        sender_kind=InboxParticipantKind.AGENT,
        recipient="harness",
        recipient_kind=InboxParticipantKind.HARNESS,
        message_type="delegation_result",
        correlation_id="corr_001",
        payload_ref="artifact://delegations/deleg_001-result.json",
    )
    thread = service.build_thread(session.session_id, "corr_001")

    assert envelope.agent.agent_id == "agent:researcher"
    assert envelope.request_message.message_type == "delegation_request"
    assert response.message_type == "delegation_result"
    assert thread.request is not None
    assert thread.request.message_type == "delegation_request"
    assert [message.message_type for message in thread.responses] == ["delegation_result"]
    assert thread.status is CorrelationStatus.RESPONDED
    assert envelope.request_message.status is InboxStatus.UNREAD
    assert any(
        signal.reason.value == "delegation_assigned"
        for signal in repositories.runtime_signals.list_by_session(session.session_id)
    )


def test_protocol_send_to_agent_creates_unread_wakeup_signal() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = ProtocolService(repositories)
    service.delegate(
        session_id=session.session_id,
        agent_id="agent:researcher",
        name="Researcher",
        role="delegate",
        payload_ref="artifact://delegations/deleg_001.json",
        task_id="task_001",
        correlation_id="corr_001",
    )

    message = service.send_message(
        session_id=session.session_id,
        sender="agent:planner",
        sender_kind=InboxParticipantKind.AGENT,
        recipient="agent:researcher",
        recipient_kind=InboxParticipantKind.AGENT,
        message_type="status_update",
        correlation_id="corr_peer",
    )

    signals = repositories.runtime_signals.list_by_session(session.session_id)
    assert message.status is InboxStatus.UNREAD
    assert any(signal.source_ref == message.message_id and signal.reason.value == "inbox_unread" for signal in signals)


def test_protocol_thread_expands_small_payloads() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = ProtocolService(repositories)
    payload_ref = service.persist_payload(
        session_id=session.session_id,
        document_kind="protocol_payload",
        payload={
            "task_id": "task_001",
            "question": "What failed?",
            "instructions": "Reply with the root cause.",
            "failed_summary": "max steps exceeded",
            "expected_response": "diagnostic_response",
        },
    )

    service.send_message(
        session_id=session.session_id,
        sender="harness",
        sender_kind=InboxParticipantKind.HARNESS,
        recipient="agent:researcher",
        recipient_kind=InboxParticipantKind.AGENT,
        message_type="diagnostic_request",
        correlation_id="corr_diag_payload",
        payload_ref=payload_ref,
        task_id="task_001",
        lane_id="lane_001",
    )

    thread = service.build_thread(session.session_id, "corr_diag_payload").to_dict()
    assert thread["request"]["payload"]["question"] == "What failed?"
    assert thread["request"]["payload"]["task_id"] == "task_001"


def test_protocol_send_await_response_drains_signal_and_returns_runtime_outcome() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = ProtocolService(repositories)
    service.delegate(
        session_id=session.session_id,
        agent_id="agent:researcher",
        name="Researcher",
        role="researcher",
        payload_ref=None,
        task_id="task_001",
        lane_id="lane_001",
        correlation_id="corr_original",
    )
    registry = ToolRegistry()
    register_protocol_tools(registry)
    model_factory = FakeModelFactory(
        {
            "v3_teammate_loop:researcher": [
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_reply",
                            "name": "protocol.send",
                            "args": {
                                "recipient": "harness",
                                "recipient_kind": "harness",
                                "message_type": "diagnostic_response",
                                "correlation_id": "corr_diag_await",
                                "payload": {
                                    "task_id": "task_001",
                                    "status": "diagnosed",
                                    "summary": "The previous turn ran out of steps before using the research tool.",
                                },
                            },
                        }
                    ],
                },
                {"content": "diagnostic response sent", "tool_calls": []},
            ]
        }
    )
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id="task_001", lane_id="lane_001"),
        model_factory=model_factory,
    )
    context.refresh_restore_context()

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_diag",
            tool_name="protocol.send",
            arguments={
                "recipient": "agent:researcher",
                "message_type": "diagnostic_request",
                "correlation_id": "corr_diag_await",
                "task_id": "task_001",
                "lane_id": "lane_001",
                "await_response": True,
                "max_steps": 4,
                "payload": {
                    "task_id": "task_001",
                    "lane_id": "lane_001",
                    "question": "Why did you fail?",
                    "instructions": "Answer with a concise root cause.",
                    "failed_summary": "max_steps_exceeded",
                    "expected_response": "diagnostic_response",
                },
            },
            task_id="task_001",
            lane_id="lane_001",
        ),
    )

    content = json.loads(result.content)
    message = repositories.inbox.get(content["message"]["message_id"])
    thread = content["thread"]
    prompt = model_factory.invokers["v3_teammate_loop:researcher"].calls[0]["system_prompt"]
    seed_message = model_factory.invokers["v3_teammate_loop:researcher"].calls[0]["messages"][0]
    seed = seed_message.get("content") if isinstance(seed_message, dict) else seed_message.content
    task = repositories.tasks.get("task_001")
    assert result.ok is True
    assert message.status is InboxStatus.ACKNOWLEDGED
    assert content["runtime_outcomes"][0]["ok"] is True
    assert thread["status"] == CorrelationStatus.RESPONDED.value
    assert [response["message_type"] for response in thread["responses"]] == ["diagnostic_response", "delegation_result"]
    assert "Diagnostic question: Why did you fail?" in prompt
    assert "max_steps_exceeded" in prompt
    assert "corr_diag_await" in seed
    assert task.status is TaskStatus.IN_PROGRESS


def test_background_completion_updates_agent_and_invocation_state() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = ProtocolService(repositories)
    service.delegate(
        session_id=session.session_id,
        agent_id="agent:executor",
        name="Executor",
        role="delegate",
        payload_ref="artifact://delegations/deleg_002.json",
        task_id="task_001",
        correlation_id="corr_bg_001",
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_001",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            engine_name="execution",
            status=EngineInvocationStatus.RUNNING,
            input_ref="artifact://engine/inv_001/input.json",
            output_ref=None,
            approval_id=None,
            idempotency_key="task_001:execution:1",
            started_at="2026-04-17T12:00:03+00:00",
        )
    )

    completion = service.complete_background_task(
        session_id=session.session_id,
        correlation_id="corr_bg_001",
        recipient="harness",
        payload_ref="artifact://engine/inv_001/output.json",
        invocation_id="inv_001",
        agent_id="agent:executor",
        success=True,
    )

    assert completion.notification.message_type == "background_completion"
    assert repositories.agents.get("agent:executor").status is AgentMemberStatus.IDLE
    assert repositories.invocations.get("inv_001").status is EngineInvocationStatus.SUCCEEDED
    assert service.build_thread(session.session_id, "corr_bg_001").status is CorrelationStatus.COMPLETED
    assert any(
        signal.reason.value == "engine_completed"
        for signal in repositories.runtime_signals.list_by_session(session.session_id)
    )


def test_background_completion_preserves_existing_invocation_output_ref() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = ProtocolService(repositories)
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_002",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            engine_name="execution",
            status=EngineInvocationStatus.RUNNING,
            input_ref="artifact://engine/inv_002/input.json",
            output_ref="artifact://engine/inv_002/existing-output.json",
            approval_id=None,
            idempotency_key="task_001:execution:2",
            started_at="2026-04-17T12:00:03+00:00",
        )
    )

    service.complete_background_task(
        session_id=session.session_id,
        correlation_id="corr_bg_002",
        recipient="harness",
        payload_ref="artifact://engine/inv_002/background-notification.json",
        invocation_id="inv_002",
        success=True,
    )

    assert repositories.invocations.get("inv_002").output_ref == "artifact://engine/inv_002/existing-output.json"
