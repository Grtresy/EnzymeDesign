from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import replace
import sqlite3
from threading import Event
from threading import Thread
import time

import pytest

from openzyme_core import AgentRuntimeScheduler
from openzyme_core import AgentRuntimeService
from openzyme_core import CoreRepositories
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeLeaseRepository
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import ToolRegistry
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core.agent_identity import create_agent_member
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import Session
from openzyme_domain import Task
from openzyme_domain import TaskStatus
from openzyme_runtime import LangChainToolCallingInvoker


class FakeToolCallingInvoker:
    def __init__(self) -> None:
        self.calls = 0

    def invoke_with_tools(self, *, system_prompt: str, messages: list[object], tools: list[object]) -> object:
        del system_prompt, messages, tools
        self.calls += 1
        return {"content": "handled", "tool_calls": []}


class FakeModelFactory:
    def __init__(self) -> None:
        self.invoker = FakeToolCallingInvoker()

    def create_tool_calling_invoker(self, *, purpose: str) -> FakeToolCallingInvoker:
        del purpose
        return self.invoker


class BlockingHeartbeatInvoker:
    def __init__(self, started: Event, release: Event) -> None:
        self.started = started
        self.release = release

    def invoke_with_tools(
        self,
        *,
        system_prompt: str,
        messages: list[object],
        tools: list[object],
    ) -> object:
        del system_prompt, messages, tools
        self.started.set()
        assert self.release.wait(timeout=10)
        return {"content": "handled after heartbeat", "tool_calls": []}


class BlockingHeartbeatModelFactory:
    def __init__(self, started: Event, release: Event) -> None:
        self.invoker = BlockingHeartbeatInvoker(started, release)

    def create_tool_calling_invoker(self, *, purpose: str) -> BlockingHeartbeatInvoker:
        del purpose
        return self.invoker


class FinishingToolCallingInvoker:
    def __init__(self) -> None:
        self.calls = 0

    def invoke_with_tools(self, *, system_prompt: str, messages: list[object], tools: list[object]) -> object:
        del system_prompt, messages, tools
        self.calls += 1
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_finish",
                    "name": "task.finish",
                    "args": {
                        "task_id": "task_0",
                        "status": "completed",
                        "summary": "Finished via task.finish.",
                    },
                }
            ],
        }


class FinishingModelFactory:
    def __init__(self) -> None:
        self.invoker = FinishingToolCallingInvoker()

    def create_tool_calling_invoker(self, *, purpose: str) -> FinishingToolCallingInvoker:
        del purpose
        return self.invoker


class ReporterToolCallingInvoker:
    def __init__(self, *, agent_id: str) -> None:
        self.agent_id = agent_id
        self.calls = 0

    def invoke_with_tools(self, *, system_prompt: str, messages: list[object], tools: list[object]) -> object:
        del system_prompt, messages, tools
        self.calls += 1
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_draft",
                    "name": "report_draft.update",
                    "args": {
                        "task_id": "task_report",
                        "title": "Final report",
                        "summary": "Draft complete.",
                        "markdown": "# Final report\n\nReady.",
                        "status": "ready",
                        "owner_agent_id": self.agent_id,
                    },
                },
                {
                    "id": "call_publish",
                    "name": "report.publish",
                    "args": {
                        "task_id": "task_report",
                        "title": "Final report",
                        "summary": "Published report.",
                        "stage_summary": "Reporter published the final report.",
                        "status": "published",
                    },
                },
                {
                    "id": "call_finish_report",
                    "name": "task.finish",
                    "args": {
                        "task_id": "task_report",
                        "status": "completed",
                        "summary": "Report draft and publication completed.",
                    },
                },
            ],
        }


class ReporterModelFactory:
    def __init__(self, *, agent_id: str) -> None:
        self.invoker = ReporterToolCallingInvoker(agent_id=agent_id)

    def create_tool_calling_invoker(self, *, purpose: str) -> ReporterToolCallingInvoker:
        assert purpose == "v3_teammate_loop:reporter"
        return self.invoker


class LoopingToolCallingInvoker:
    def __init__(self) -> None:
        self.calls = 0

    def invoke_with_tools(self, *, system_prompt: str, messages: list[object], tools: list[object]) -> object:
        del system_prompt, messages, tools
        self.calls += 1
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": f"call_list_{self.calls}",
                    "name": "task.list",
                    "args": {},
                }
            ],
        }


class LoopingModelFactory:
    def __init__(self) -> None:
        self.invoker = LoopingToolCallingInvoker()

    def create_tool_calling_invoker(self, *, purpose: str) -> LoopingToolCallingInvoker:
        del purpose
        return self.invoker


class FakeProviderStatusError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class RetryableProviderModelFactory:
    def __init__(
        self,
        *,
        status_code: int,
        fail_times: int,
        max_attempts: int,
    ) -> None:
        self.status_code = status_code
        self.fail_times = fail_times
        self.max_attempts = max_attempts
        self.provider_calls = 0

    def create_tool_calling_invoker(self, *, purpose: str):
        factory = self

        class FakeRunnable:
            def invoke(self, messages):
                del messages
                factory.provider_calls += 1
                if factory.provider_calls <= factory.fail_times:
                    raise FakeProviderStatusError(
                        factory.status_code,
                        f"provider status {factory.status_code}",
                    )
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_finish",
                            "name": "task.finish",
                            "args": {
                                "task_id": "task_0",
                                "status": "completed",
                                "summary": "Finished after provider retry.",
                            },
                        }
                    ],
                }

        class FakeModel:
            def bind_tools(self, tools):
                del tools
                return FakeRunnable()

        return LangChainToolCallingInvoker(
            model=FakeModel(),
            purpose=purpose,
            max_attempts=self.max_attempts,
            retry_backoff_seconds=0.0,
        )


class ExplodingMasterModelFactory:
    def __init__(self) -> None:
        self.calls = 0

    def create_tool_calling_invoker(self, *, purpose: str) -> object:
        del purpose
        self.calls += 1
        raise ValueError("task '' does not exist")


def _build_context(*, model_factory: object | None) -> tuple[CoreRepositories, SessionRuntimeContext]:
    connection = connect_sqlite(":memory:", check_same_thread=False)
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    session = Session.create("sess_scheduler", "proj_001", "Scheduler", "Scheduler")
    repositories.sessions.save(session)
    agent = create_agent_member(
        repositories,
        session_id=session.session_id,
        role="researcher",
    )
    for index in range(3):
        task_id = f"task_{index}"
        repositories.tasks.save(
            Task.create(
                task_id=task_id,
                session_id=session.session_id,
                subject=f"Task {index}",
                description=f"Do task {index}",
            )
        )
        repositories.runtime_signals.save(
            AgentRuntimeSignal(
                signal_id=f"sig_{index}",
                session_id=session.session_id,
                agent_id=agent.agent_id,
                task_id=task_id,
                reason=AgentRuntimeSignalReason.MANUAL_RESUME,
                status=AgentRuntimeSignalStatus.PENDING,
                created_at=f"2026-04-16T10:00:0{index + 1}+00:00",
            )
        )
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        model_factory=model_factory,
    )
    return repositories, context


def test_scheduler_does_not_claim_without_model_factory() -> None:
    repositories, context = _build_context(model_factory=None)

    outcomes = AgentRuntimeScheduler(context).run_once_sync("sess_scheduler")

    assert outcomes == ()
    assert all(
        signal.status is AgentRuntimeSignalStatus.PENDING
        and signal.attempt_count == 0
        for signal in repositories.runtime_signals.list_by_session("sess_scheduler")
    )


def test_scheduler_respects_max_signals_and_session_concurrency() -> None:
    repositories, context = _build_context(model_factory=FinishingModelFactory())

    outcomes = AgentRuntimeScheduler(
        context,
        worker_id="test:scheduler",
        max_global_concurrency=3,
        max_session_concurrency=1,
    ).run_once_sync("sess_scheduler", max_signals=1)

    assert len(outcomes) == 1
    signals = repositories.runtime_signals.list_by_session("sess_scheduler")
    assert [signal.status for signal in signals].count(AgentRuntimeSignalStatus.COMPLETED) == 1
    assert [signal.status for signal in signals].count(AgentRuntimeSignalStatus.PENDING) == 3
    assert any(
        signal.agent_id == "agent:master"
        and signal.reason is AgentRuntimeSignalReason.MANUAL_RESUME
        for signal in signals
    )
    assert signals[0].claimed_by == "test:scheduler"
    task = repositories.tasks.get("task_0")
    assert task is not None
    assert task.status is TaskStatus.COMPLETED


def test_scheduler_heartbeats_session_lease_during_blocking_provider_call(
    tmp_path,
    monkeypatch,
) -> None:
    provider = SQLiteRepositoryProvider(str(tmp_path / "heartbeat.sqlite3"))
    started = Event()
    release = Event()
    session = Session.create(
        "sess_heartbeat",
        "proj_001",
        "Heartbeat",
        "Keep lease active during provider wait",
    )
    with provider.write() as owner:
        repositories = owner.repositories
        repositories.sessions.save(session)
        agent = create_agent_member(
            repositories,
            session_id=session.session_id,
            role="researcher",
        )
        task = Task.create(
            "task_heartbeat",
            session.session_id,
            "Wait for provider",
            "The lease must be renewed while blocked.",
            assigned_ref=agent.agent_id,
        )
        repositories.tasks.save(task)
        repositories.runtime_signals.save(
            AgentRuntimeSignal(
                signal_id="sig_heartbeat",
                session_id=session.session_id,
                agent_id=agent.agent_id,
                task_id=task.task_id,
                reason=AgentRuntimeSignalReason.MANUAL_RESUME,
                status=AgentRuntimeSignalStatus.PENDING,
                created_at="2026-07-16T00:00:00+00:00",
            )
        )

    @contextmanager
    def repository_scope():
        with provider.connection_scope() as owner:
            yield owner.repositories

    heartbeat_connections = []
    busy_failures = 7
    original_heartbeat = SessionRuntimeLeaseRepository.heartbeat

    def heartbeat_busy_seven_times(self, **kwargs):
        heartbeat_connections.append(self.connection)
        if len(heartbeat_connections) <= busy_failures:
            raise sqlite3.OperationalError("database is locked")
        return original_heartbeat(self, **kwargs)

    monkeypatch.setattr(
        SessionRuntimeLeaseRepository,
        "heartbeat",
        heartbeat_busy_seven_times,
    )

    contender_result: dict[str, object] = {}

    def attempt_reclaim_after_original_expiry() -> None:
        assert started.wait(timeout=5)
        time.sleep(4.5)
        with provider.connection_scope() as owner:
            contender_result["result"] = (
                owner.repositories.session_runtime_leases.acquire(
                    session_id=session.session_id,
                    owner_id="test:contender",
                    mode="test",
                    lease_seconds=4,
                )
            )
        release.set()

    contender = Thread(target=attempt_reclaim_after_original_expiry)
    contender.start()
    with provider.connection_scope() as coordinator:
        coordinator_connection = (
            coordinator.repositories.session_runtime_leases.connection
        )
        context = SessionRuntimeContext(
            repositories=coordinator.repositories,
            event_sink=MemoryEventBus(),
            snapshot=SessionRuntimeSnapshot.load(
                coordinator.repositories,
                session.session_id,
            ),
            tool_registry=ToolRegistry(),
            restore_focus=RestoreFocus(),
            model_factory=BlockingHeartbeatModelFactory(started, release),
        )
        outcomes = AgentRuntimeScheduler(
            context,
            worker_id="test:heartbeat-owner",
            session_lease_seconds=4,
            repository_scope_factory=repository_scope,
        ).run_once_sync(session.session_id, max_signals=1)
    contender.join(timeout=7)

    assert not contender.is_alive()
    contender_attempt = contender_result["result"]
    assert getattr(contender_attempt, "acquired") is False
    assert len(outcomes) == 1
    assert outcomes[0].ok is True
    assert len(heartbeat_connections) >= busy_failures + 1
    assert all(
        connection is not coordinator_connection for connection in heartbeat_connections
    )
    assert len({id(connection) for connection in heartbeat_connections}) == len(
        heartbeat_connections
    )


def test_scheduler_releases_lease_and_preserves_heartbeat_error(monkeypatch) -> None:
    started = Event()
    release = Event()
    repositories, context = _build_context(
        model_factory=BlockingHeartbeatModelFactory(started, release)
    )

    def raise_programming_error(self, **kwargs):
        del self, kwargs
        raise ValueError("heartbeat programming error")

    original_emit = SessionRuntimeContext.emit

    def fail_heartbeat_event(self, event_type, payload):
        if event_type == "runtime.lease_heartbeat_failed":
            raise RuntimeError("heartbeat event sink failed")
        return original_emit(self, event_type, payload)

    monkeypatch.setattr(
        SessionRuntimeLeaseRepository,
        "heartbeat",
        raise_programming_error,
    )
    monkeypatch.setattr(SessionRuntimeContext, "emit", fail_heartbeat_event)

    def release_provider_call() -> None:
        started.wait(timeout=5)
        time.sleep(1.25)
        release.set()

    releaser = Thread(target=release_provider_call)
    releaser.start()

    scheduler = AgentRuntimeScheduler(
        context,
        worker_id="test:heartbeat-programming-error",
        session_lease_seconds=3,
    )
    with pytest.raises(ValueError, match="heartbeat programming error") as exc_info:
        scheduler.run_once_sync("sess_scheduler", max_signals=1)
    releaser.join(timeout=5)

    assert not releaser.is_alive()
    assert started.is_set()
    assert context.session_runtime_lease is None
    lease_row = repositories.session_runtime_leases.connection.execute(
        """
        SELECT released_at
        FROM session_runtime_leases
        WHERE session_id = ?
        ORDER BY fencing_token DESC
        LIMIT 1
        """,
        ("sess_scheduler",),
    ).fetchone()
    assert lease_row is not None
    assert lease_row["released_at"] is not None
    assert any(
        "heartbeat failure event emission also failed: RuntimeError" in note
        for note in getattr(exc_info.value, "__notes__", ())
    )


def test_reporter_can_publish_report_and_finish_delegated_task() -> None:
    connection = connect_sqlite(":memory:", check_same_thread=False)
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    session = Session.create("sess_reporter", "proj_001", "Reporter", "Write report")
    repositories.sessions.save(session)
    agent = create_agent_member(
        repositories,
        session_id=session.session_id,
        role="reporter",
    )
    repositories.tasks.save(
        Task.create(
            "task_report",
            session.session_id,
            "Write final report",
            "Draft and publish the final report.",
            kind="reporting",
            assigned_ref=agent.agent_id,
        )
    )
    signal = AgentRuntimeSignal(
        signal_id="sig_reporter",
        session_id=session.session_id,
        agent_id=agent.agent_id,
        task_id="task_report",
        reason=AgentRuntimeSignalReason.DELEGATION_ASSIGNED,
        status=AgentRuntimeSignalStatus.PENDING,
        created_at="2026-04-16T10:00:01+00:00",
    )
    repositories.runtime_signals.save(signal)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        model_factory=ReporterModelFactory(agent_id=agent.agent_id),
    )

    outcome = AgentRuntimeService(context).wake_agent(signal, max_steps=4)

    task = repositories.tasks.get("task_report")
    draft = repositories.report_drafts.get_by_task(session.session_id, "task_report")
    reports = repositories.reports.list_by_session(session.session_id)
    assert outcome.ok is True
    assert outcome.teammate_status == "completed"
    assert task is not None
    assert task.status is TaskStatus.COMPLETED
    assert task.assigned_ref == agent.agent_id
    assert draft is not None
    assert draft.owner_agent_id == agent.agent_id
    assert draft.status.value == "published"
    assert len(reports) == 1
    assert reports[0].status.value == "published"


def test_scheduler_runtime_failure_records_last_error() -> None:
    repositories, context = _build_context(model_factory=FakeModelFactory())
    signal = repositories.runtime_signals.get("sig_0")
    assert signal is not None
    repositories.runtime_signals.save(replace(signal, task_id=None))

    outcomes = AgentRuntimeScheduler(
        context,
        worker_id="test:scheduler",
    ).run_once_sync("sess_scheduler", max_signals=1)

    assert len(outcomes) == 1
    assert outcomes[0].ok is False
    failed = repositories.runtime_signals.get("sig_0")
    assert failed is not None
    assert failed.status is AgentRuntimeSignalStatus.FAILED
    assert failed.error_message == "Focused task required for wakeup."
    assert failed.last_error == "Focused task required for wakeup."


def test_terminal_task_stale_signal_is_consumed_without_runtime_failure() -> None:
    model_factory = FinishingModelFactory()
    repositories, context = _build_context(model_factory=model_factory)
    task = repositories.tasks.get("task_0")
    assert task is not None
    repositories.tasks.seed_fixture(replace(task, status=TaskStatus.COMPLETED))

    outcomes = AgentRuntimeScheduler(
        context,
        worker_id="test:scheduler",
    ).run_once_sync("sess_scheduler", max_signals=1)

    signal = repositories.runtime_signals.get("sig_0")
    assert len(outcomes) == 1
    assert outcomes[0].ok is True
    assert outcomes[0].teammate_status == "stale_signal_ignored"
    assert "already completed" in outcomes[0].summary
    assert signal is not None
    assert signal.status is AgentRuntimeSignalStatus.COMPLETED
    assert signal.error_message is None
    assert model_factory.invoker.calls == 0


def _build_master_failure_context(
    *, reason: AgentRuntimeSignalReason
) -> tuple[CoreRepositories, SessionRuntimeContext, ExplodingMasterModelFactory]:
    connection = connect_sqlite(":memory:", check_same_thread=False)
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    session = Session.create("sess_master_failure", "proj_001", "Master", "Fail once")
    repositories.sessions.save(session)
    repositories.agents.save(
        AgentMember(
            agent_id="agent:master",
            session_id=session.session_id,
            lane_id=None,
            task_id=None,
            name="OpenZyme",
            role="master",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at="2026-04-16T10:00:00+00:00",
            updated_at="2026-04-16T10:00:00+00:00",
            runtime_state="idle",
            idle_since="2026-04-16T10:00:00+00:00",
        )
    )
    repositories.runtime_signals.save(
        AgentRuntimeSignal(
            signal_id="sig_master_failure",
            session_id=session.session_id,
            agent_id="agent:master",
            reason=reason,
            status=AgentRuntimeSignalStatus.PENDING,
            created_at="2026-04-16T10:00:01+00:00",
        )
    )
    model_factory = ExplodingMasterModelFactory()
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        model_factory=model_factory,
    )
    return repositories, context, model_factory


def test_scheduler_releases_master_agent_after_uncaught_runtime_exception() -> None:
    repositories, context, model_factory = _build_master_failure_context(
        reason=AgentRuntimeSignalReason.MANUAL_RESUME
    )

    outcomes = AgentRuntimeScheduler(
        context,
        worker_id="test:scheduler",
    ).run_once_sync("sess_master_failure", max_signals=1)

    failed = repositories.runtime_signals.get("sig_master_failure")
    master = repositories.agents.get("sess_master_failure", "agent:master")
    assert len(outcomes) == 1
    assert outcomes[0].ok is False
    assert failed is not None
    assert failed.status is AgentRuntimeSignalStatus.FAILED
    assert "task '' does not exist" in (failed.last_error or "")
    assert model_factory.calls == 1
    assert master is not None
    assert master.status is AgentMemberStatus.IDLE
    assert master.runtime_state == "idle"
    assert master.idle_since is not None
    assert outcomes[0].agent == master


def test_scheduler_fails_missing_master_inbox_source_before_provider() -> None:
    repositories, context, model_factory = _build_master_failure_context(
        reason=AgentRuntimeSignalReason.INBOX_UNREAD
    )

    outcomes = AgentRuntimeScheduler(
        context,
        worker_id="test:scheduler",
    ).run_once_sync("sess_master_failure", max_signals=1)

    failed = repositories.runtime_signals.get("sig_master_failure")
    master = repositories.agents.get("sess_master_failure", "agent:master")
    assert len(outcomes) == 1
    assert outcomes[0].ok is False
    assert failed is not None
    assert failed.status is AgentRuntimeSignalStatus.FAILED
    assert "master inbox_unread signal source message is missing" in (
        failed.last_error or ""
    )
    assert model_factory.calls == 0
    assert master is not None
    assert master.status is AgentMemberStatus.IDLE
    assert master.runtime_state == "idle"
    assert master.idle_since is not None
    assert outcomes[0].agent == master


def test_teammate_max_steps_does_not_mark_business_task_failed() -> None:
    model_factory = LoopingModelFactory()
    repositories, context = _build_context(model_factory=model_factory)

    outcomes = AgentRuntimeScheduler(
        context,
        worker_id="test:scheduler",
    ).run_once_sync("sess_scheduler", max_signals=1, max_steps_per_agent=1)

    task = repositories.tasks.get("task_0")
    signal = repositories.runtime_signals.get("sig_0")
    assert len(outcomes) == 1
    assert outcomes[0].ok is False
    assert outcomes[0].teammate_status == "max_steps_exceeded"
    assert signal is not None
    assert signal.status is AgentRuntimeSignalStatus.FAILED
    assert task is not None
    assert task.status is TaskStatus.IN_PROGRESS
    assert task.failure_summary is None
    assert task.failure_ref is None


def test_teammate_without_task_finish_records_followup_not_business_completion() -> None:
    repositories, context = _build_context(model_factory=FakeModelFactory())
    agent = next(
        candidate
        for candidate in repositories.agents.list_by_session("sess_scheduler")
        if candidate.role == "researcher"
    )

    outcomes = AgentRuntimeScheduler(
        context,
        worker_id="test:scheduler",
    ).run_once_sync("sess_scheduler", max_signals=1)

    task = repositories.tasks.get("task_0")
    signal = repositories.runtime_signals.get("sig_0")
    updated_agent = repositories.agents.get("sess_scheduler", agent.agent_id)
    messages = repositories.inbox.list_by_session("sess_scheduler")
    status_update = next(
        message
        for message in messages
        if message.sender == agent.agent_id
        and message.message_type == "status_update"
    )
    payload = repositories.engine_documents.get(status_update.payload_ref)

    assert len(outcomes) == 1
    assert outcomes[0].ok is True
    assert outcomes[0].teammate_status == "completed"
    assert "task.finish" in outcomes[0].summary
    assert signal is not None
    assert signal.status is AgentRuntimeSignalStatus.COMPLETED
    assert task is not None
    assert task.status is TaskStatus.IN_PROGRESS
    assert task.failure_summary is None
    assert updated_agent is not None
    assert updated_agent.status is AgentMemberStatus.IDLE
    assert all(message.message_type != "delegation_result" for message in messages)
    assert any(
        runtime_signal.agent_id == "agent:master"
        and runtime_signal.status is AgentRuntimeSignalStatus.PENDING
        for runtime_signal in repositories.runtime_signals.list_by_session(
            "sess_scheduler"
        )
    )
    assert payload is not None
    assert payload.payload["status"] == "task_finish_required"
    assert payload.payload["runtime_status"] == "completed"
    assert payload.payload["business_status"] == "unchanged"
    assert payload.payload["task_status"] == "in_progress"
    assert payload.payload["required_action"] == "task.finish"


def test_scheduler_completes_signal_when_tool_calling_retry_succeeds() -> None:
    model_factory = RetryableProviderModelFactory(
        status_code=502,
        fail_times=1,
        max_attempts=2,
    )
    repositories, context = _build_context(model_factory=model_factory)

    outcomes = AgentRuntimeScheduler(
        context,
        worker_id="test:scheduler",
    ).run_once_sync("sess_scheduler", max_signals=1)

    completed = repositories.runtime_signals.get("sig_0")
    assert completed is not None
    assert len(outcomes) == 1
    assert outcomes[0].ok is True
    assert completed.status is AgentRuntimeSignalStatus.COMPLETED
    assert model_factory.provider_calls == 2


def test_scheduler_releases_retryable_provider_failure_back_to_pending() -> None:
    model_factory = RetryableProviderModelFactory(
        status_code=502,
        fail_times=10,
        max_attempts=1,
    )
    repositories, context = _build_context(model_factory=model_factory)

    outcomes = AgentRuntimeScheduler(
        context,
        worker_id="test:scheduler",
    ).run_once_sync("sess_scheduler", max_signals=1)

    pending = repositories.runtime_signals.get("sig_0")
    agent = next(
        candidate
        for candidate in repositories.agents.list_by_session("sess_scheduler")
        if candidate.role == "researcher"
    )
    assert pending is not None
    assert agent is not None
    assert len(outcomes) == 1
    assert outcomes[0].ok is False
    assert pending.status is AgentRuntimeSignalStatus.PENDING
    assert pending.attempt_count == 1
    assert pending.last_error is not None
    assert "provider status 502" in pending.last_error
    assert agent.status is AgentMemberStatus.IDLE


def test_scheduler_fails_non_retryable_provider_failure() -> None:
    model_factory = RetryableProviderModelFactory(
        status_code=400,
        fail_times=10,
        max_attempts=2,
    )
    repositories, context = _build_context(model_factory=model_factory)

    outcomes = AgentRuntimeScheduler(
        context,
        worker_id="test:scheduler",
    ).run_once_sync("sess_scheduler", max_signals=1)

    failed = repositories.runtime_signals.get("sig_0")
    assert failed is not None
    assert len(outcomes) == 1
    assert outcomes[0].ok is False
    assert failed.status is AgentRuntimeSignalStatus.FAILED
    assert "provider status 400" in (failed.last_error or "")


def test_scheduler_run_forever_stops_on_shutdown_request() -> None:
    _, context = _build_context(model_factory=None)
    scheduler = AgentRuntimeScheduler(context)
    scheduler.request_shutdown()

    outcomes = asyncio.run(
        scheduler.run_forever("sess_scheduler", poll_interval_seconds=0, max_ticks=10)
    )

    assert outcomes == ()
