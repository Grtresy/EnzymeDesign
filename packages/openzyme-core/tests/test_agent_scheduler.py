from __future__ import annotations

import asyncio
from dataclasses import replace

from openzyme_core import AgentRuntimeScheduler
from openzyme_core import CoreRepositories
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import ToolRegistry
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import Session
from openzyme_domain import Task


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


def _build_context(*, model_factory: object | None) -> tuple[CoreRepositories, SessionRuntimeContext]:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    session = Session.create("sess_scheduler", "proj_001", "Scheduler", "Scheduler")
    repositories.sessions.save(session)
    repositories.agents.save(
        AgentMember(
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
                agent_id="agent:researcher",
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
    repositories, context = _build_context(model_factory=FakeModelFactory())

    outcomes = AgentRuntimeScheduler(
        context,
        worker_id="test:scheduler",
        max_global_concurrency=3,
        max_session_concurrency=1,
    ).run_once_sync("sess_scheduler", max_signals=1)

    assert len(outcomes) == 1
    signals = repositories.runtime_signals.list_by_session("sess_scheduler")
    assert [signal.status for signal in signals].count(AgentRuntimeSignalStatus.COMPLETED) == 1
    assert [signal.status for signal in signals].count(AgentRuntimeSignalStatus.PENDING) == 2
    assert signals[0].claimed_by == "test:scheduler"


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


def test_scheduler_run_forever_stops_on_shutdown_request() -> None:
    _, context = _build_context(model_factory=None)
    scheduler = AgentRuntimeScheduler(context)
    scheduler.request_shutdown()

    outcomes = asyncio.run(
        scheduler.run_forever("sess_scheduler", poll_interval_seconds=0, max_ticks=10)
    )

    assert outcomes == ()
