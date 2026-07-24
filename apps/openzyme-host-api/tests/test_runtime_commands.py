from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import replace
import threading
import time

from fastapi.testclient import TestClient
import pytest

from openzyme_core import AgentRuntimeOutcome
from openzyme_core import AgentRuntimeService
from openzyme_core import MutationScopeService
from openzyme_core import RuntimeDrainCoreReceipt
from openzyme_core import RuntimeDrainProjectionOutcome
from openzyme_core import RuntimeCommandWorker
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import project_runtime_command
from openzyme_core.agent_identity import create_agent_member
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import Session
from openzyme_domain import MutationScopeKind
from openzyme_domain import MutationWriterKind
from openzyme_domain import SessionRuntimeLeaseMode
from openzyme_domain import Task
from openzyme_domain import TaskStatus
from openzyme_host_api import HostApiDependencies
from openzyme_host_api import build_local_eval_foundation
from openzyme_host_api import create_app
from openzyme_host_api.runtime_commands import HostRuntimeCommandExecutor
from openzyme_host_api.v3_service import V3HostApiService
from openzyme_host_api.v3_service import V3EventStore
from openzyme_host_api.v3_service import V3RuntimeDrainResult
from openzyme_runtime import ReliabilityRefactorSettings
from openzyme_runtime import RuntimeDrainContract


def _dependencies(
    *,
    repository_provider: SQLiteRepositoryProvider | None = None,
    model_factory: object | None = None,
) -> HostApiDependencies:
    foundation = build_local_eval_foundation()
    if model_factory is not None:
        foundation = replace(foundation, model_factory=model_factory)
    return HostApiDependencies(
        foundation=replace(
            foundation,
            settings=replace(
                foundation.settings,
                reliability=ReliabilityRefactorSettings(
                    runtime_drain_contract=RuntimeDrainContract.COMMAND_V1,
                ),
            ),
        ),
        v3_repository_provider=repository_provider,
        v3_background_runtime_enabled=False,
    )


def _create_session(client: TestClient, session_id: str) -> None:
    response = client.post(
        "/v3/sessions",
        json={
            "session_id": session_id,
            "project_id": "proj_runtime_commands",
            "title": "Runtime command test",
            "objective": "Exercise asynchronous command ownership",
        },
    )
    assert response.status_code == 200, response.text


def _drain_result(
    session_id: str,
    *,
    processed_signal_count: int = 0,
    suspended: bool = False,
) -> V3RuntimeDrainResult:
    return V3RuntimeDrainResult(
        session_id=session_id,
        core_receipt=RuntimeDrainCoreReceipt(
            scheduler_status=(
                "waiting_approval" if suspended else "completed"
            ),
            processed_signal_count=processed_signal_count,
            suspended=suspended,
        ),
        projection_outcome=RuntimeDrainProjectionOutcome.complete(),
        outputs=(),
        events=[],
        workspace={},
    )


class _LoopingToolCallingInvoker:
    def __init__(self) -> None:
        self.calls = 0

    def invoke_with_tools(
        self,
        *,
        system_prompt: str,
        messages: list[object],
        tools: list[object],
    ) -> object:
        del system_prompt, messages, tools
        self.calls += 1
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": f"call_budget_task_list_{self.calls}",
                    "name": "task.list",
                    "args": {},
                }
            ],
        }


class _LoopingModelFactory:
    def __init__(self) -> None:
        self.invoker = _LoopingToolCallingInvoker()

    def create_tool_calling_invoker(
        self,
        *,
        purpose: str,
    ) -> _LoopingToolCallingInvoker:
        del purpose
        return self.invoker


class _FailingTaskToolCallingInvoker:
    def __init__(self, *, task_id: str) -> None:
        self.task_id = task_id
        self.calls = 0

    def invoke_with_tools(
        self,
        *,
        system_prompt: str,
        messages: list[object],
        tools: list[object],
    ) -> object:
        del system_prompt, messages, tools
        self.calls += 1
        if self.calls > 1:
            return {
                "content": (
                    "The business task was explicitly closed as failed."
                ),
                "tool_calls": [],
            }
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": f"call_fail_task_{self.calls}",
                    "name": "task.finish",
                    "args": {
                        "task_id": self.task_id,
                        "status": "failed",
                        "summary": "Master explicitly closed the business task.",
                        "failure_summary": (
                            "The bounded objective is not achievable."
                        ),
                    },
                }
            ],
        }


class _BudgetThenFailModelFactory:
    def __init__(self, *, task_id: str) -> None:
        self.teammate_invoker = _LoopingToolCallingInvoker()
        self.master_invoker = _FailingTaskToolCallingInvoker(task_id=task_id)

    def create_tool_calling_invoker(self, *, purpose: str) -> object:
        if purpose.startswith("v3_teammate_loop:"):
            return self.teammate_invoker
        assert purpose == "v3_harness_loop"
        return self.master_invoker


async def _invoke_without_executor(func, /, *args, **kwargs):
    return func(*args, **kwargs)


def _seed_teammate_budget_signal(
    service: V3HostApiService,
    *,
    session_id: str,
) -> tuple[str, str]:
    service.create_session(
        project_id="proj_runtime_commands",
        session_id=session_id,
        title="Budget handoff",
        objective="Replan from a new source-bound master turn.",
    )
    task_id = f"task_{session_id}"
    task = Task.create(
        task_id=task_id,
        session_id=session_id,
        subject="Use one bounded turn",
        description="Exhaust the turn and preserve the business task.",
        status=TaskStatus.IN_PROGRESS,
    )
    service.repositories.tasks.save(task)
    agent = create_agent_member(
        service.repositories,
        session_id=session_id,
        role="executor",
        task_id=task_id,
    )
    service.repositories.tasks.save(
        replace(
            task,
            assigned_ref=agent.agent_id,
        )
    )
    signal_id = f"signal_{session_id}"
    service.repositories.runtime_signals.save(
        AgentRuntimeSignal(
            signal_id=signal_id,
            session_id=session_id,
            agent_id=agent.agent_id,
            task_id=task_id,
            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
            status=AgentRuntimeSignalStatus.PENDING,
            created_at="2026-07-24T12:00:00+00:00",
        )
    )
    return task_id, signal_id


def _wait_for_terminal(
    client: TestClient,
    *,
    session_id: str,
    command_id: str,
    timeout_seconds: float = 3.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        response = client.get(
            f"/v3/sessions/{session_id}/runtime/commands/{command_id}"
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] in {"completed", "failed", "locked", "cancelled"}:
            return payload
        if time.monotonic() >= deadline:
            raise AssertionError(f"runtime command remained {payload['status']!r}")
        time.sleep(0.02)


def _completed_outcome_with_failed_business_task() -> AgentRuntimeOutcome:
    task = replace(
        Task.create(
            task_id="task_explicitly_failed",
            session_id="sess_scheduler_settlement",
            subject="Explicit business failure",
            description="Keep scheduler and business state independent.",
            status=TaskStatus.IN_PROGRESS,
        ),
        status=TaskStatus.FAILED,
        failure_summary="The objective is not achievable.",
    )
    signal = AgentRuntimeSignal(
        signal_id="signal_completed_for_failed_task",
        session_id=task.session_id,
        agent_id="agent:master",
        task_id=task.task_id,
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        status=AgentRuntimeSignalStatus.COMPLETED,
        created_at="2026-07-24T10:00:00+00:00",
        attempt_count=1,
        completed_at="2026-07-24T10:00:01+00:00",
    )
    return AgentRuntimeOutcome(
        signal=signal,
        task=task,
        agent=None,
        ok=True,
        summary="The signal completed after an explicit task.finish.",
        teammate_status="completed",
    )


def test_host_scheduler_settlement_ignores_explicit_business_task_failure() -> None:
    outcome = _completed_outcome_with_failed_business_task()

    assert (
        V3HostApiService._outcomes_include_scheduler_failure([outcome])
        is False
    )
    assert outcome.settlement is not None
    assert outcome.settlement.task_status is TaskStatus.FAILED


def test_host_scheduler_settlement_rejects_untyped_outcome_payload() -> None:
    outcome = _completed_outcome_with_failed_business_task()

    assert (
        V3HostApiService._outcomes_include_scheduler_failure(  # type: ignore[list-item]
            [outcome.to_dict()]
        )
        is True
    )


def test_host_scheduler_settlement_keeps_ordinary_signal_failure_failed() -> None:
    signal = AgentRuntimeSignal(
        signal_id="signal_ordinary_failure",
        session_id="sess_scheduler_settlement",
        agent_id="agent:master",
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        status=AgentRuntimeSignalStatus.FAILED,
        created_at="2026-07-24T10:00:00+00:00",
        attempt_count=1,
        completed_at="2026-07-24T10:00:01+00:00",
        error_message="ordinary_runtime_failure",
    )
    outcome = AgentRuntimeOutcome(
        signal=signal,
        task=None,
        agent=None,
        ok=False,
        summary="An ordinary runtime failure remains a scheduler failure.",
        teammate_status="runtime_exception",
    )

    assert (
        V3HostApiService._outcomes_include_scheduler_failure([outcome])
        is True
    )


def test_r55_shaped_runtime_drain_settles_closed_teammate_budget_replan_handoff(
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    provider = SQLiteRepositoryProvider(
        str(tmp_path / "closed-budget-replan.sqlite3"),
        check_same_thread=False,
    )
    with provider.connection_scope() as scope:
        service = V3HostApiService(
            repositories=scope.repositories,
            event_store=V3EventStore(scope.repositories),
            model_factory=_LoopingModelFactory(),
        )
        task_id, signal_id = _seed_teammate_budget_signal(
            service,
            session_id="sess_closed_budget_replan",
        )
        command, created = service.admit_runtime_command(
            session_id="sess_closed_budget_replan",
            idempotency_key="drain:r55-shaped-budget-replan",
            max_signals=1,
            max_steps_per_agent=16,
            auto_enqueue_ready_tasks=False,
        )
        assert created is True

        result = service.drain_runtime(
            session_id="sess_closed_budget_replan",
            max_signals=1,
            max_steps_per_agent=16,
        )

        signal = scope.repositories.runtime_signals.get(signal_id)
        task = scope.repositories.tasks.get(task_id)
        failures = scope.repositories.failure_observations.list_by_source(
            session_id="sess_closed_budget_replan",
            source_kind="runtime_signal",
            source_ref=signal_id,
        )
        wakeups = [
            candidate
            for candidate in scope.repositories.runtime_signals.list_by_session(
                "sess_closed_budget_replan"
            )
            if candidate.agent_id == "agent:master"
            and candidate.source_ref == signal_id
        ]

    class CapturedDrainService:
        def drain_runtime(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return result

    @contextmanager
    def captured_service_scope():  # type: ignore[no-untyped-def]
        yield CapturedDrainService()

    execution_result = HostRuntimeCommandExecutor(
        service_scope=captured_service_scope,
        worker_id="test:r55-runtime-command",
    )(command)

    assert signal is not None
    assert signal.status is AgentRuntimeSignalStatus.FAILED
    assert task is not None
    assert task.status is TaskStatus.IN_PROGRESS
    assert len(failures) == 1
    assert failures[0].facts["max_steps"] == 16
    assert len(wakeups) == 1
    assert wakeups[0].status is AgentRuntimeSignalStatus.PENDING
    assert result.core_receipt.scheduler_status == "completed"
    assert result.core_receipt.processed_signal_count == 1
    assert result.projection_outcome.status == "complete"
    assert result.bounded_outcome_summary["replay_safe"] is False
    assert execution_result.status.value == "completed"
    assert execution_result.error_code is None


def test_file_backed_worker_consumes_budget_successor_only_on_next_command(
    monkeypatch,  # type: ignore[no-untyped-def]
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setattr(asyncio, "to_thread", _invoke_without_executor)
    session_id = "sess_two_command_budget_handoff"
    task_id = f"task_{session_id}"
    provider = SQLiteRepositoryProvider(
        str(tmp_path / "two-command-budget-handoff.sqlite3"),
        check_same_thread=False,
    )
    dependencies = _dependencies(
        repository_provider=provider,
        model_factory=_BudgetThenFailModelFactory(task_id=task_id),
    )
    with dependencies.v3_service_scope(mode="write") as service:
        seeded_task_id, source_signal_id = _seed_teammate_budget_signal(
            service,
            session_id=session_id,
        )
        assert seeded_task_id == task_id
        first_command, created = service.admit_runtime_command(
            session_id=session_id,
            idempotency_key="drain:first-budget-turn",
            max_signals=3,
            max_steps_per_agent=1,
            auto_enqueue_ready_tasks=False,
        )
    assert created is True

    worker = RuntimeCommandWorker(
        repository_scope_factory=lambda: dependencies.v3_repository_scope(
            mode="connection"
        ),
        executor=HostRuntimeCommandExecutor(
            service_scope=lambda: dependencies.v3_service_scope(
                mode="connection"
            ),
            worker_id="test:two-command-budget-handoff",
        ),
        worker_id="test:two-command-budget-handoff",
        mutation_writer_scope_factory=dependencies.v3_mutation_writer_scope,
        post_writer_finalizer=(
            dependencies.finalize_pending_v3_scientific_transitions
        ),
    )

    first_outcome = worker.run_once()
    assert first_outcome.status == "completed"
    with dependencies.v3_repository_scope(mode="read") as repositories:
        source_after_first = repositories.runtime_signals.get(source_signal_id)
        task_after_first = repositories.tasks.get(task_id)
        successors = [
            signal
            for signal in repositories.runtime_signals.list_by_session(
                session_id
            )
            if signal.agent_id == "agent:master"
            and signal.source_ref == source_signal_id
        ]
        first_stored = repositories.runtime_commands.get(
            first_command.command_id
        )
    assert source_after_first is not None
    assert source_after_first.status is AgentRuntimeSignalStatus.FAILED
    assert source_after_first.attempt_count == 1
    assert task_after_first is not None
    assert task_after_first.status is TaskStatus.IN_PROGRESS
    assert len(successors) == 1
    successor = successors[0]
    assert successor.status is AgentRuntimeSignalStatus.PENDING
    assert successor.attempt_count == 0
    assert first_stored is not None
    assert first_stored.status.value == "completed"
    first_summary = dict(first_stored.bounded_outcome_summary or {})
    assert first_summary["scheduler_status"] == "completed"
    assert first_summary["processed_signal_count"] == 1

    with dependencies.v3_service_scope(mode="write") as service:
        second_command, created = service.admit_runtime_command(
            session_id=session_id,
            idempotency_key="drain:second-master-replan",
            max_signals=3,
            max_steps_per_agent=2,
            auto_enqueue_ready_tasks=False,
        )
    assert created is True

    second_outcome = worker.run_once()
    assert second_outcome.status == "completed"
    with dependencies.v3_repository_scope(mode="read") as repositories:
        source_after_second = repositories.runtime_signals.get(
            source_signal_id
        )
        successor_after_second = repositories.runtime_signals.get(
            successor.signal_id
        )
        task_after_second = repositories.tasks.get(task_id)
        first_after_second = repositories.runtime_commands.get(
            first_command.command_id
        )
        second_stored = repositories.runtime_commands.get(
            second_command.command_id
        )
    assert source_after_second is not None
    assert source_after_second.status is AgentRuntimeSignalStatus.FAILED
    assert source_after_second.attempt_count == 1
    assert successor_after_second is not None
    assert successor_after_second.status is AgentRuntimeSignalStatus.COMPLETED
    assert successor_after_second.attempt_count == 1
    assert task_after_second is not None
    assert task_after_second.status is TaskStatus.FAILED
    assert first_after_second is not None
    assert first_after_second.status.value == "completed"
    assert first_after_second.bounded_outcome_summary == first_summary
    assert second_stored is not None
    assert second_stored.status.value == "completed"
    assert second_stored.bounded_outcome_summary is not None
    assert second_stored.bounded_outcome_summary["scheduler_status"] == (
        "completed"
    )
    assert second_stored.bounded_outcome_summary[
        "processed_signal_count"
    ] == 1


def test_runtime_drain_fails_when_budget_replan_wakeup_is_missing(
    monkeypatch,  # type: ignore[no-untyped-def]
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    provider = SQLiteRepositoryProvider(
        str(tmp_path / "missing-budget-replan.sqlite3"),
        check_same_thread=False,
    )
    monkeypatch.setattr(
        AgentRuntimeService,
        "_enqueue_master_wakeup_after_teammate",
        lambda *args, **kwargs: None,
    )
    with provider.connection_scope() as scope:
        service = V3HostApiService(
            repositories=scope.repositories,
            event_store=V3EventStore(scope.repositories),
            model_factory=_LoopingModelFactory(),
        )
        _seed_teammate_budget_signal(
            service,
            session_id="sess_missing_budget_replan",
        )

        result = service.drain_runtime(
            session_id="sess_missing_budget_replan",
            max_signals=1,
            max_steps_per_agent=1,
        )

    assert result.core_receipt.scheduler_status == "failed"
    assert result.core_receipt.processed_signal_count == 1
    assert result.projection_outcome.status == "complete"


def test_runtime_drain_keeps_master_budget_exhaustion_failed(
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    provider = SQLiteRepositoryProvider(
        str(tmp_path / "master-budget-exhaustion.sqlite3"),
        check_same_thread=False,
    )
    with provider.connection_scope() as scope:
        service = V3HostApiService(
            repositories=scope.repositories,
            event_store=V3EventStore(scope.repositories),
            model_factory=_LoopingModelFactory(),
        )
        service.create_session(
            project_id="proj_runtime_commands",
            session_id="sess_master_budget_exhaustion",
            title="Master budget",
            objective="Do not invent a successor turn for master.",
        )
        service.post_message(
            session_id="sess_master_budget_exhaustion",
            message="Inspect the current task board.",
        )

        result = service.drain_runtime(
            session_id="sess_master_budget_exhaustion",
            max_signals=1,
            max_steps_per_agent=1,
        )

    assert result.core_receipt.scheduler_status == "failed"
    assert result.core_receipt.processed_signal_count == 1
    assert result.projection_outcome.status == "complete"


@pytest.mark.parametrize(
    "failed_stage",
    ("runtime_consistency", "event_append", "workspace"),
)
def test_runtime_drain_preserves_core_receipt_across_projection_failures(
    monkeypatch,  # type: ignore[no-untyped-def]
    tmp_path,  # type: ignore[no-untyped-def]
    failed_stage: str,
) -> None:
    provider = SQLiteRepositoryProvider(
        str(tmp_path / f"projection-{failed_stage}.sqlite3")
    )
    with provider.connection_scope() as scope:
        service = V3HostApiService(
            repositories=scope.repositories,
            event_store=V3EventStore(scope.repositories),
            model_factory=object(),
        )
        service.create_session(
            project_id="proj_runtime_commands",
            session_id=f"sess_projection_{failed_stage}",
            title="Projection failure",
            objective="Preserve scheduler progress across settlement failure.",
        )

        def one_processed_signal(
            self,  # type: ignore[no-untyped-def]
            session_id,
            events,
            **kwargs,
        ):
            del kwargs
            agent = self.repositories.agents.get(session_id, "agent:master")
            assert agent is not None
            events.append(
                {
                    "event_id": f"evt_scheduler_{failed_stage}",
                    "session_id": session_id,
                    "event_type": "agent.runtime_signal.updated",
                    "created_at": "2026-07-24T00:00:00+00:00",
                    "payload": {"status": "completed"},
                }
            )
            signal = AgentRuntimeSignal(
                signal_id=f"signal_projection_{failed_stage}",
                session_id=session_id,
                agent_id="agent:master",
                reason=AgentRuntimeSignalReason.MANUAL_RESUME,
                status=AgentRuntimeSignalStatus.COMPLETED,
                created_at="2026-07-24T00:00:00+00:00",
                attempt_count=1,
                completed_at="2026-07-24T00:00:01+00:00",
            )
            return [
                AgentRuntimeOutcome(
                    signal=signal,
                    task=None,
                    agent=agent,
                    ok=True,
                    summary="Synthetic completed scheduler outcome.",
                    outputs=("scheduler output",),
                    teammate_status="completed",
                )
            ]

        monkeypatch.setattr(
            V3HostApiService,
            "_drain_pending_agent_signals",
            one_processed_signal,
        )

        def injected_failure(*args, **kwargs):  # type: ignore[no-untyped-def]
            del args, kwargs
            raise RuntimeError(
                f"{failed_stage} failed at /home/private/control.sqlite3"
            )

        if failed_stage == "runtime_consistency":
            monkeypatch.setattr(
                V3HostApiService,
                "_extend_with_runtime_consistency_events",
                injected_failure,
            )
        elif failed_stage == "event_append":
            monkeypatch.setattr(V3EventStore, "append", injected_failure)
        else:
            monkeypatch.setattr(
                V3HostApiService,
                "_extend_with_trace_events",
                lambda *args, **kwargs: None,
            )
            monkeypatch.setattr(
                V3HostApiService,
                "_extend_with_activity_events",
                lambda *args, **kwargs: None,
            )
            monkeypatch.setattr(
                V3HostApiService,
                "_extend_with_runtime_consistency_events",
                lambda *args, **kwargs: None,
            )
            monkeypatch.setattr(
                V3HostApiService,
                "workspace",
                injected_failure,
            )

        result = service.drain_runtime(
            session_id=f"sess_projection_{failed_stage}",
            max_signals=1,
            max_steps_per_agent=1,
        )

    summary = result.bounded_outcome_summary
    assert result.status == "failed"
    assert result.core_receipt.scheduler_status == "completed"
    assert result.core_receipt.processed_signal_count == 1
    assert result.projection_outcome.status == "failed"
    assert result.projection_outcome.error_code == "runtime_projection_failed"
    assert result.projection_outcome.failed_stage == failed_stage
    assert "[redacted-host-path]" in str(
        result.projection_outcome.safe_summary
    )
    assert "/home/private" not in str(result.projection_outcome.safe_summary)
    assert summary["schema_version"] == "runtime_command_outcome@2"
    assert summary["core_receipt_formed"] is True
    assert summary["scheduler_status"] == "completed"
    assert summary["processed_signal_count"] == 1
    assert summary["projection_status"] == "failed"
    assert summary["projection_failed_stage"] == failed_stage
    assert summary["replay_safe"] is False
    assert summary["output_count"] == 1
    assert summary["event_count"] == 1
    assert result.workspace == {}
    assert "blindly replay" in str(result.safe_retry_hint)


def test_file_backed_runtime_command_reports_durable_progress_after_projection_failure(
    monkeypatch,  # type: ignore[no-untyped-def]
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    provider = SQLiteRepositoryProvider(
        str(tmp_path / "r54-runtime-receipt.sqlite3")
    )
    dependencies = _dependencies(repository_provider=provider)
    session_id = "sess_r54_runtime_receipt"
    signal_id = "signal_r54_runtime_receipt"

    def process_signal_then_return(
        self,  # type: ignore[no-untyped-def]
        observed_session_id,
        events,
        **kwargs,
    ):
        del kwargs
        assert observed_session_id == session_id
        completed = self.repositories.runtime_signals.complete(signal_id)
        assert completed is not None
        assert completed.status is AgentRuntimeSignalStatus.COMPLETED
        events.append(
            {
                "event_id": "evt_r54_signal_completed",
                "session_id": session_id,
                "event_type": "agent.runtime_signal.updated",
                "created_at": "2026-07-24T00:00:00+00:00",
                "payload": {
                    "signal_id": signal_id,
                    "status": "completed",
                },
            }
        )
        agent = self.repositories.agents.get(session_id, "agent:master")
        assert agent is not None
        return [
            AgentRuntimeOutcome(
                signal=completed,
                task=None,
                agent=agent,
                ok=True,
                summary="Synthetic completed scheduler outcome.",
                teammate_status="completed",
            )
        ]

    def fail_consistency_projection(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise RuntimeError(
            "selection head projection failed at "
            "/home/private/r54-control.sqlite3"
        )

    monkeypatch.setattr(
        V3HostApiService,
        "_drain_pending_agent_signals",
        process_signal_then_return,
    )
    monkeypatch.setattr(
        V3HostApiService,
        "_extend_with_runtime_consistency_events",
        fail_consistency_projection,
    )

    with dependencies.v3_service_scope(mode="write") as service:
        service.create_session(
            project_id="proj_runtime_commands",
            session_id=session_id,
            title="r54 runtime receipt",
            objective="Preserve durable progress after projection failure.",
        )
        command, created = service.admit_runtime_command(
            session_id=session_id,
            idempotency_key="drain:r54-receipt",
            max_signals=1,
            max_steps_per_agent=1,
            auto_enqueue_ready_tasks=False,
        )
    assert created is True
    with dependencies.v3_repository_scope(mode="write") as repositories:
        repositories.runtime_signals.save(
            AgentRuntimeSignal(
                signal_id=signal_id,
                session_id=session_id,
                agent_id="agent:master",
                reason=AgentRuntimeSignalReason.MANUAL_RESUME,
                status=AgentRuntimeSignalStatus.PENDING,
                created_at="2026-07-24T00:00:00+00:00",
            )
        )
    with dependencies.v3_service_scope(mode="connection") as service:
        drain_result = service.drain_runtime(
            session_id=session_id,
            max_signals=1,
            max_steps_per_agent=1,
            auto_enqueue_ready_tasks=False,
            worker_id="test:r54-scheduler",
        )

    class CapturedDrainService:
        def drain_runtime(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return drain_result

    @contextmanager
    def captured_service_scope():  # type: ignore[no-untyped-def]
        yield CapturedDrainService()

    execution_result = HostRuntimeCommandExecutor(
        service_scope=captured_service_scope,
        worker_id="test:r54-runtime-command",
    )(command)

    def replay_captured_result(claimed):  # type: ignore[no-untyped-def]
        del claimed
        return execution_result

    worker_outcome = RuntimeCommandWorker(
        repository_scope_factory=lambda: dependencies.v3_repository_scope(
            mode="connection"
        ),
        executor=replay_captured_result,
        worker_id="test:r54-runtime-command",
    ).run_once()
    assert worker_outcome.status == "failed"

    with provider.read() as unit_of_work:
        stored_signal = unit_of_work.repositories.runtime_signals.get(signal_id)
        stored_command = unit_of_work.repositories.runtime_commands.get(
            command.command_id
        )
        finished_events = [
            event
            for event in unit_of_work.repositories.durable_events.list_by_session(
                session_id
            )
            if event.event_type == "runtime.command.finished"
        ]
    assert stored_command is not None
    terminal = project_runtime_command(stored_command)
    summary = terminal["bounded_outcome_summary"]
    assert terminal["status"] == "failed"
    assert terminal["error_code"] == "runtime_projection_failed"
    assert summary["schema_version"] == "runtime_command_outcome@2"
    assert summary["core_receipt_formed"] is True
    assert summary["scheduler_status"] == "completed"
    assert summary["processed_signal_count"] == 1
    assert summary["projection_status"] == "failed"
    assert summary["projection_error_code"] == "runtime_projection_failed"
    assert summary["projection_failed_stage"] == "runtime_consistency"
    assert summary["replay_safe"] is False
    assert "blindly replay" in str(terminal["safe_retry_hint"])
    assert "/home/private" not in str(terminal)
    assert stored_signal is not None
    assert stored_signal.status is AgentRuntimeSignalStatus.COMPLETED
    assert stored_command.bounded_outcome_summary == summary
    assert len(finished_events) == 1
    assert finished_events[0].payload["bounded_outcome_summary"] == summary
    assert "/home/private" not in str(finished_events[0].payload)


def test_session_command_routes_use_registered_mutation_writers_and_seal(
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    provider = SQLiteRepositoryProvider(str(tmp_path / "mutation-scope.sqlite3"))
    dependencies = _dependencies(repository_provider=provider)
    with TestClient(create_app(dependencies)) as client:
        _create_session(client, "sess_command_mutation_scope")
        with dependencies.v3_repository_scope(mode="connection") as repositories:
            scope = MutationScopeService(repositories).open_scope(
                session_id="sess_command_mutation_scope",
                scope_kind=MutationScopeKind.SESSION,
                scope_ref="session-command-route-test",
            )

        response = client.post(
            "/v3/sessions/sess_command_mutation_scope/messages",
            headers={"Idempotency-Key": "message:mutation-scope"},
            json={"message": "Persist under a registered Host command writer."},
        )
        assert response.status_code == 200, response.text

        with dependencies.v3_repository_scope(mode="connection") as repositories:
            service = MutationScopeService(repositories)
            writers = repositories.mutation_writers.list_all(scope.scope_id)
            assert {writer.owner_kind for writer in writers} == {
                MutationWriterKind.ATTEMPT_DRIVER,
                MutationWriterKind.EVENT_OUTBOX_PUBLISHER,
            }
            event_writer = next(
                writer
                for writer in writers
                if writer.owner_kind is MutationWriterKind.EVENT_OUTBOX_PUBLISHER
            )
            command_writer = next(
                writer
                for writer in writers
                if writer.owner_kind is MutationWriterKind.ATTEMPT_DRIVER
            )
            assert event_writer.parent_writer_id == command_writer.writer_id
            assert all(writer.state.is_terminal for writer in writers)
            service.begin_freeze(scope.scope_id)
            issued = service.issue_quiescence_receipt(scope.scope_id)
            service.seal_scope(
                scope.scope_id,
                receipt_id=issued.receipt.receipt_id,
            )
            projection = service.project_scope(scope.scope_id)

        assert projection["state"] == "sealed"
        assert projection["active_writer_counts"] == {}
        assert projection["receipt"]["snapshot_id"] == issued.snapshot.snapshot_id

        rejected = client.post(
            "/v3/sessions/sess_command_mutation_scope/messages",
            headers={"Idempotency-Key": "message:after-seal"},
            json={"message": "This write must not reopen sealed authority."},
        )
        assert rejected.status_code >= 400

        with dependencies.v3_repository_scope(mode="read") as repositories:
            messages = repositories.inbox.list_by_session(
                "sess_command_mutation_scope"
            )
        assert len(messages) == 1


def test_runtime_drain_returns_202_before_blocked_scheduler_finishes(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def blocked_drain(self, *, session_id: str, **kwargs):  # type: ignore[no-untyped-def]
        del self, kwargs
        calls.append(session_id)
        entered.set()
        assert release.wait(timeout=3)
        return _drain_result(
            session_id,
            processed_signal_count=0,
            suspended=False,
        )

    monkeypatch.setattr(V3HostApiService, "drain_runtime", blocked_drain)
    dependencies = _dependencies()
    with TestClient(create_app(dependencies)) as client:
        _create_session(client, "sess_async_admission")
        started_at = time.monotonic()
        response = client.post(
            "/v3/sessions/sess_async_admission/runtime/drain",
            headers={"Idempotency-Key": "drain:async-admission"},
            json={"max_signals": 2, "max_steps_per_agent": 3},
        )
        elapsed = time.monotonic() - started_at

        assert response.status_code == 202, response.text
        assert elapsed < 1.0
        payload = response.json()
        assert payload["session_id"] == "sess_async_admission"
        assert payload["status"] in {"accepted", "claimed"}
        assert payload["status_url"].endswith(payload["command_id"])
        assert not {
            "workspace",
            "events",
            "outputs",
            "claim_owner",
            "lease_token",
            "fencing_token",
        }.intersection(payload)
        assert entered.wait(timeout=1)
        release.set()
        terminal = _wait_for_terminal(
            client,
            session_id="sess_async_admission",
            command_id=payload["command_id"],
        )
        assert terminal["status"] == "completed"
        assert calls == ["sess_async_admission"]


def test_runtime_command_idempotency_conflict_and_strict_request_surface() -> None:
    dependencies = _dependencies()
    with TestClient(create_app(dependencies)) as client:
        _create_session(client, "sess_command_identity")
        request = {"max_signals": 2, "max_steps_per_agent": 3}
        headers = {"Idempotency-Key": "drain:identity"}
        first = client.post(
            "/v3/sessions/sess_command_identity/runtime/drain",
            headers=headers,
            json=request,
        )
        replay = client.post(
            "/v3/sessions/sess_command_identity/runtime/drain",
            headers=headers,
            json=request,
        )
        conflict = client.post(
            "/v3/sessions/sess_command_identity/runtime/drain",
            headers=headers,
            json={**request, "max_signals": 4},
        )
        missing_key = client.post(
            "/v3/sessions/sess_command_identity/runtime/drain",
            json=request,
        )
        extra_authority = client.post(
            "/v3/sessions/sess_command_identity/runtime/drain",
            headers={"Idempotency-Key": "drain:forbidden"},
            json={**request, "skill_keys": ["choose-a-workflow"]},
        )

        assert first.status_code == 202
        assert replay.status_code == 202
        assert replay.json()["command_id"] == first.json()["command_id"]
        assert conflict.status_code == 409
        assert missing_key.status_code == 422
        assert extra_authority.status_code == 422
        with dependencies.v3_repository_scope(mode="read") as repositories:
            commands = repositories.runtime_commands.list_active()
            all_commands = repositories.runtime_commands.get(first.json()["command_id"])
        assert all_commands is not None
        assert len(commands) <= 1


def test_runtime_command_prefer_wait_is_strict_and_post_remains_202(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    def immediate_drain(self, *, session_id: str, **kwargs):  # type: ignore[no-untyped-def]
        del self, kwargs
        return _drain_result(
            session_id,
            processed_signal_count=1,
            suspended=True,
        )

    monkeypatch.setattr(V3HostApiService, "drain_runtime", immediate_drain)
    dependencies = _dependencies()
    with TestClient(create_app(dependencies)) as client:
        _create_session(client, "sess_prefer_wait")
        completed = client.post(
            "/v3/sessions/sess_prefer_wait/runtime/drain",
            headers={
                "Idempotency-Key": "drain:prefer-complete",
                "Prefer": "wait=2",
            },
            json={},
        )
        assert completed.status_code == 202
        assert completed.json()["status"] == "completed"
        assert completed.json()["bounded_outcome_summary"]["suspended"] is True

        for index, invalid in enumerate(("wait=-1", "wait=2.1", "respond-async")):
            rejected = client.post(
                "/v3/sessions/sess_prefer_wait/runtime/drain",
                headers={
                    "Idempotency-Key": f"drain:invalid-prefer:{index}",
                    "Prefer": invalid,
                },
                json={},
            )
            assert rejected.status_code == 400


def test_runtime_command_lock_is_terminal_and_cross_session_lookup_is_hidden() -> None:
    dependencies = _dependencies()
    with TestClient(create_app(dependencies)) as client:
        _create_session(client, "sess_locked_command")
        _create_session(client, "sess_other_command")
        with dependencies.v3_repository_scope(mode="write") as repositories:
            acquired = repositories.session_runtime_leases.acquire(
                session_id="sess_locked_command",
                owner_id="fixture:other-runtime-owner",
                mode=SessionRuntimeLeaseMode.TEST,
                lease_seconds=60,
            )
        assert acquired.acquired is True

        admitted = client.post(
            "/v3/sessions/sess_locked_command/runtime/drain",
            headers={"Idempotency-Key": "drain:locked"},
            json={},
        )
        assert admitted.status_code == 202
        terminal = _wait_for_terminal(
            client,
            session_id="sess_locked_command",
            command_id=admitted.json()["command_id"],
        )
        assert terminal["status"] == "locked"
        assert terminal["error_code"] == "session_runtime_locked"
        hidden = client.get(
            "/v3/sessions/sess_other_command/runtime/commands/"
            f"{admitted.json()['command_id']}"
        )
        assert hidden.status_code == 404
        with dependencies.v3_repository_scope(mode="read") as repositories:
            assert repositories.runtime_commands.count_active() == 0
            locked_events = [
                event
                for event in repositories.durable_events.list_by_session(
                    "sess_locked_command"
                )
                if event.event_type == "runtime.session_locked"
            ]
        assert len(locked_events) == 1
        assert set(locked_events[0].payload) == {
            "status",
            "retry_after_seconds",
            "safe_retry_hint",
        }
        assert "fixture:other-runtime-owner" not in str(locked_events[0].payload)


def test_runtime_command_admission_rolls_back_if_its_durable_event_fails(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    dependencies = _dependencies()
    try:
        with dependencies.v3_repository_scope(mode="write") as repositories:
            repositories.sessions.save(
                Session.create(
                    session_id="sess_atomic_admission",
                    project_id="proj_runtime_commands",
                    title="Atomic command admission",
                    objective="Rollback every admission record together",
                )
            )

        def fail_event_append(self, session_id, events):  # type: ignore[no-untyped-def]
            del self, session_id, events
            raise RuntimeError("injected durable event failure")

        monkeypatch.setattr(V3EventStore, "append", fail_event_append)
        with pytest.raises(RuntimeError, match="injected durable event failure"):
            with dependencies.v3_service_scope(mode="write") as service:
                service.admit_runtime_command(
                    session_id="sess_atomic_admission",
                    idempotency_key="drain:atomic-failure",
                    max_signals=3,
                    max_steps_per_agent=8,
                    auto_enqueue_ready_tasks=False,
                )

        with dependencies.v3_repository_scope(mode="read") as repositories:
            assert repositories.runtime_commands.count_active() == 0
            assert (
                repositories.durable_events.list_by_session("sess_atomic_admission")
                == []
            )
    finally:
        dependencies.close_owned_v3_storage()


def test_host_restart_claims_an_existing_accepted_runtime_command(
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    provider = SQLiteRepositoryProvider(str(tmp_path / "host-restart.sqlite3"))
    admission_dependencies = _dependencies(repository_provider=provider)
    with admission_dependencies.v3_repository_scope(mode="write") as repositories:
        repositories.sessions.save(
            Session.create(
                session_id="sess_command_restart",
                project_id="proj_runtime_commands",
                title="Restart command",
                objective="Recover an accepted runtime command",
            )
        )
    with admission_dependencies.v3_service_scope(mode="write") as service:
        command, created = service.admit_runtime_command(
            session_id="sess_command_restart",
            idempotency_key="drain:restart",
            max_signals=1,
            max_steps_per_agent=1,
            auto_enqueue_ready_tasks=False,
        )
    assert created is True

    recovered_dependencies = _dependencies(repository_provider=provider)
    with TestClient(create_app(recovered_dependencies)) as client:
        terminal = _wait_for_terminal(
            client,
            session_id="sess_command_restart",
            command_id=command.command_id,
        )

    assert terminal["status"] == "completed"
    with provider.read() as unit_of_work:
        stored = unit_of_work.repositories.runtime_commands.get(command.command_id)
        events = unit_of_work.repositories.durable_events.list_by_session(
            "sess_command_restart"
        )
    assert stored is not None
    assert stored.fencing_token == 1
    assert [event.event_type for event in events] == [
        "runtime.command.accepted",
        "runtime.command.finished",
    ]


def test_runtime_api_downgrade_is_rejected_while_a_command_is_active(
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    provider = SQLiteRepositoryProvider(str(tmp_path / "api-downgrade.sqlite3"))
    command_dependencies = _dependencies(repository_provider=provider)
    with command_dependencies.v3_repository_scope(mode="write") as repositories:
        repositories.sessions.save(
            Session.create(
                session_id="sess_command_downgrade",
                project_id="proj_runtime_commands",
                title="Command downgrade",
                objective="Keep active commands on their durable owner",
            )
        )
    with command_dependencies.v3_service_scope(mode="write") as service:
        service.admit_runtime_command(
            session_id="sess_command_downgrade",
            idempotency_key="drain:downgrade",
            max_signals=1,
            max_steps_per_agent=1,
            auto_enqueue_ready_tasks=False,
        )

    foundation = build_local_eval_foundation()
    sync_dependencies = HostApiDependencies(
        foundation=replace(
            foundation,
            settings=replace(
                foundation.settings,
                reliability=ReliabilityRefactorSettings(
                    runtime_drain_contract=RuntimeDrainContract.SYNC_V1,
                ),
            ),
        ),
        v3_repository_provider=provider,
        v3_background_runtime_enabled=False,
    )
    with pytest.raises(
        RuntimeError,
        match=(
            "cannot downgrade while active durable commands or continuations exist"
        ),
    ):
        create_app(sync_dependencies)


def test_retired_sync_runtime_api_has_no_fallback_without_active_rows() -> None:
    foundation = build_local_eval_foundation()
    sync_dependencies = HostApiDependencies(
        foundation=replace(
            foundation,
            settings=replace(
                foundation.settings,
                reliability=ReliabilityRefactorSettings(
                    runtime_drain_contract=RuntimeDrainContract.SYNC_V1,
                ),
            ),
        ),
        v3_background_runtime_enabled=False,
    )

    with pytest.raises(
        RuntimeError,
        match="sync_v1 runtime drain contract is retired",
    ):
        create_app(sync_dependencies)
