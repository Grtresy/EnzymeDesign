from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import threading

import pytest

from openzyme_core import RuntimeCommandExecutionResult
from openzyme_core import RuntimeCommandWorker
from openzyme_core import RuntimeDrainCoreReceipt
from openzyme_core import RuntimeDrainProjectionOutcome
from openzyme_core import MutationScopeService
from openzyme_core import MutationWriterTurnFactory
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import connect_sqlite
from openzyme_core import current_mutation_write_authority
from openzyme_core import project_runtime_command
from openzyme_core import runtime_command_pre_core_failure_summary
from openzyme_core.runtime_drain_receipts import (
    validate_runtime_command_outcome_v2,
)
from openzyme_domain import RuntimeCommandRecord
from openzyme_domain import RuntimeCommandStatus
from openzyme_domain import RuntimeCommandType
from openzyme_domain import MutationScopeKind
from openzyme_domain import MutationWriterKind
from openzyme_domain import Session


NOW = "2026-07-21T00:00:00+00:00"


def _provider(tmp_path):  # type: ignore[no-untyped-def]
    provider = SQLiteRepositoryProvider(str(tmp_path / "runtime-commands.sqlite3"))
    with provider.write() as unit_of_work:
        unit_of_work.repositories.sessions.save(
            Session.create(
                session_id="sess_runtime_commands",
                project_id="proj_runtime_commands",
                title="Runtime commands",
                objective="Exercise durable command ownership",
            )
        )
    return provider


@contextmanager
def _repository_scope(provider):  # type: ignore[no-untyped-def]
    with provider.connection_scope() as scope:
        yield scope.repositories


@contextmanager
def _authority_aware_repository_scope(provider):  # type: ignore[no-untyped-def]
    with provider.connection_scope() as scope:
        authority = current_mutation_write_authority()
        if authority is None:
            yield scope.repositories
        else:
            with scope.repositories.mutation_write_authority(authority):
                yield scope.repositories


def _command(*, command_id: str = "command_001") -> RuntimeCommandRecord:
    return RuntimeCommandRecord(
        command_id=command_id,
        session_id="sess_runtime_commands",
        command_type=RuntimeCommandType.RUNTIME_DRAIN,
        request_digest="sha256:" + "a" * 64,
        idempotency_key=f"idempotency:{command_id}",
        status=RuntimeCommandStatus.ACCEPTED,
        max_signals=3,
        max_steps_per_agent=8,
        auto_enqueue_ready_tasks=False,
        state_version=1,
        fencing_token=0,
        accepted_at=NOW,
    )


def _completed_outcome_summary(
    *,
    processed_signal_count: int,
    suspended: bool,
) -> dict[str, object]:
    return RuntimeDrainCoreReceipt(
        scheduler_status=(
            "waiting_approval" if suspended else "completed"
        ),
        processed_signal_count=processed_signal_count,
        suspended=suspended,
    ).bounded_outcome_summary(RuntimeDrainProjectionOutcome.complete())


def test_runtime_drain_receipt_preserves_progress_and_bounds_identities() -> None:
    output_ids = tuple(f"sha256:output-{index}" for index in range(20))
    event_ids = tuple(f"evt_{index}" for index in range(70))
    receipt = RuntimeDrainCoreReceipt(
        scheduler_status="failed",
        processed_signal_count=1,
        suspended=False,
        output_ids=output_ids,
        event_ids=event_ids,
    )
    projection = RuntimeDrainProjectionOutcome.failed(
        safe_summary="Consistency projection failed.",
        failed_stage="runtime_consistency",
    )

    summary = receipt.bounded_outcome_summary(projection)

    assert receipt.to_dict() == {
        "schema_version": "runtime_drain_core_receipt@1",
        "scheduler_status": "failed",
        "processed_signal_count": 1,
        "suspended": False,
        "output_count": 20,
        "output_ids": list(output_ids),
        "event_count": 70,
        "event_ids": list(event_ids),
    }
    assert projection.to_dict() == {
        "schema_version": "runtime_drain_projection_outcome@1",
        "status": "failed",
        "error_code": "runtime_projection_failed",
        "safe_summary": "Consistency projection failed.",
        "failed_stage": "runtime_consistency",
    }
    assert summary["schema_version"] == "runtime_command_outcome@2"
    assert summary["core_receipt_formed"] is True
    assert summary["processed_signal_count"] == 1
    assert summary["projection_status"] == "failed"
    assert summary["projection_error_code"] == "runtime_projection_failed"
    assert summary["projection_failed_stage"] == "runtime_consistency"
    assert summary["replay_safe"] is False
    assert summary["output_count"] == 20
    assert summary["output_ids"] == list(output_ids[:16])
    assert summary["output_ids_truncated"] is True
    assert summary["event_count"] == 70
    assert summary["event_ids"] == list(event_ids[:64])
    assert summary["event_ids_truncated"] is True
    validate_runtime_command_outcome_v2(summary)


def test_runtime_command_v2_rejects_replay_safe_after_scheduler_progress() -> None:
    summary = _completed_outcome_summary(
        processed_signal_count=1,
        suspended=False,
    )
    summary["replay_safe"] = True

    with pytest.raises(
        ValueError,
        match="replay cannot be safe after progress",
    ):
        validate_runtime_command_outcome_v2(summary)


def test_runtime_command_worker_claims_executes_and_sanitizes_result(tmp_path) -> None:  # type: ignore[no-untyped-def]
    provider = _provider(tmp_path)
    command = _command()
    with provider.write() as unit_of_work:
        unit_of_work.repositories.runtime_commands.add(command)
    calls: list[str] = []

    def execute(claimed: RuntimeCommandRecord) -> RuntimeCommandExecutionResult:
        calls.append(claimed.command_id)
        summary = _completed_outcome_summary(
            processed_signal_count=1,
            suspended=True,
        )
        summary.update(
            {
                "claim_owner": "secret-worker",
                "host_path": "/tmp/private-result",
            }
        )
        return RuntimeCommandExecutionResult(
            status=RuntimeCommandStatus.COMPLETED,
            bounded_outcome_summary=summary,
        )

    outcome = RuntimeCommandWorker(
        repository_scope_factory=lambda: _repository_scope(provider),
        executor=execute,
        worker_id="runtime-worker:test",
        clock=lambda: "2026-07-21T00:00:01+00:00",
    ).run_once()

    assert calls == [command.command_id]
    assert outcome.action == "completed"
    assert outcome.semantic_progress is True
    assert outcome.status == RuntimeCommandStatus.COMPLETED.value
    with provider.read() as unit_of_work:
        stored = unit_of_work.repositories.runtime_commands.get(command.command_id)
        events = unit_of_work.repositories.durable_events.list_by_session(
            command.session_id
        )
    assert stored is not None
    assert stored.status is RuntimeCommandStatus.COMPLETED
    assert stored.state_version == 3
    assert stored.fencing_token == 1
    assert stored.bounded_outcome_summary == _completed_outcome_summary(
        processed_signal_count=1,
        suspended=True,
    )
    assert [event.event_type for event in events] == ["runtime.command.finished"]
    assert "secret-worker" not in str(events[0].payload)


def test_runtime_command_late_binds_terminal_writer_when_execution_opens_scope(
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    provider = _provider(tmp_path)
    command = _command(command_id="command_opens_mutation_scope")
    with provider.write() as unit_of_work:
        unit_of_work.repositories.runtime_commands.add(command)

    def execute(claimed: RuntimeCommandRecord) -> RuntimeCommandExecutionResult:
        with _authority_aware_repository_scope(provider) as repositories:
            MutationScopeService(repositories).open_scope(
                session_id=claimed.session_id,
                scope_kind=MutationScopeKind.SESSION,
                scope_ref="runtime-command-created-scope",
            )
        return RuntimeCommandExecutionResult(
            status=RuntimeCommandStatus.COMPLETED,
            bounded_outcome_summary=_completed_outcome_summary(
                processed_signal_count=1,
                suspended=False,
            ),
        )

    writer_turns = MutationWriterTurnFactory(
        repository_scope_factory=lambda: _authority_aware_repository_scope(provider)
    )
    outcome = RuntimeCommandWorker(
        repository_scope_factory=lambda: _authority_aware_repository_scope(provider),
        executor=execute,
        worker_id="runtime-worker:late-terminal-writer",
        clock=lambda: "2026-07-21T00:00:01+00:00",
        mutation_writer_scope_factory=writer_turns.open,
    ).run_once()

    assert outcome.status == RuntimeCommandStatus.COMPLETED.value
    with provider.read() as unit_of_work:
        repositories = unit_of_work.repositories
        stored = repositories.runtime_commands.get(command.command_id)
        scopes = repositories.mutation_scopes.list_by_session(command.session_id)
        writers = repositories.mutation_writers.list_all(scopes[0].scope_id)
        events = repositories.durable_events.list_by_session(command.session_id)
    assert stored is not None
    assert stored.status is RuntimeCommandStatus.COMPLETED
    assert [event.event_type for event in events] == ["runtime.command.finished"]
    assert len(writers) == 1
    assert writers[0].owner_kind is MutationWriterKind.RUNTIME_COMMAND
    assert writers[0].owner_ref == (
        f"runtime-command:{command.command_id}:terminal-settlement"
    )
    assert writers[0].state.is_terminal


def test_runtime_command_worker_pre_core_exception_uses_v2_zero_receipt(
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    provider = _provider(tmp_path)
    command = _command(command_id="command_pre_core_failure")
    with provider.write() as unit_of_work:
        unit_of_work.repositories.runtime_commands.add(command)

    def fail_before_receipt(
        claimed: RuntimeCommandRecord,
    ) -> RuntimeCommandExecutionResult:
        del claimed
        raise RuntimeError("provider failed at /home/private/runtime.sock")

    outcome = RuntimeCommandWorker(
        repository_scope_factory=lambda: _repository_scope(provider),
        executor=fail_before_receipt,
        worker_id="runtime-worker:pre-core-failure",
        clock=lambda: "2026-07-21T00:00:01+00:00",
    ).run_once()

    assert outcome.action == "failed"
    assert outcome.semantic_progress is True
    with provider.read() as unit_of_work:
        stored = unit_of_work.repositories.runtime_commands.get(
            command.command_id
        )
    assert stored is not None
    assert stored.status is RuntimeCommandStatus.FAILED
    assert stored.error_code == "runtime_command_execution_failed"
    assert stored.bounded_outcome_summary == (
        runtime_command_pre_core_failure_summary()
    )
    assert stored.safe_error_summary == "provider failed at [redacted-host-path]"


def test_runtime_command_worker_never_overwrites_returned_core_receipt(
    tmp_path,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(tmp_path)
    command = _command(command_id="command_post_core_finish_failure")
    with provider.write() as unit_of_work:
        unit_of_work.repositories.runtime_commands.add(command)
    returned_summary = _completed_outcome_summary(
        processed_signal_count=1,
        suspended=False,
    )
    finish_results: list[RuntimeCommandExecutionResult] = []

    def fail_finish(
        self: RuntimeCommandWorker,
        claimed: RuntimeCommandRecord,
        result: RuntimeCommandExecutionResult,
        *,
        action: str | None = None,
    ) -> None:
        del self, claimed, action
        finish_results.append(result)
        raise RuntimeError("runtime command finish persistence failed")

    monkeypatch.setattr(RuntimeCommandWorker, "_finish", fail_finish)
    worker = RuntimeCommandWorker(
        repository_scope_factory=lambda: _repository_scope(provider),
        executor=lambda claimed: RuntimeCommandExecutionResult(
            status=RuntimeCommandStatus.COMPLETED,
            bounded_outcome_summary=returned_summary,
        ),
        worker_id="runtime-worker:post-core-failure",
        clock=lambda: "2026-07-21T00:00:01+00:00",
    )

    with pytest.raises(
        RuntimeError,
        match="runtime command finish persistence failed",
    ):
        worker.run_once()

    assert len(finish_results) == 1
    assert finish_results[0].bounded_outcome_summary == returned_summary
    assert finish_results[0].bounded_outcome_summary[
        "processed_signal_count"
    ] == 1
    assert finish_results[0].bounded_outcome_summary[
        "core_receipt_formed"
    ] is True
    with provider.read() as unit_of_work:
        stored = unit_of_work.repositories.runtime_commands.get(
            command.command_id
        )
    assert stored is not None
    assert stored.status is RuntimeCommandStatus.CLAIMED
    assert stored.bounded_outcome_summary is None


def test_runtime_command_worker_fails_expired_claim_without_scheduler_replay(
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    provider = _provider(tmp_path)
    command = _command(command_id="command_expired")
    with provider.write() as unit_of_work:
        repositories = unit_of_work.repositories
        repositories.runtime_commands.add(command)
        expired = repositories.runtime_commands.claim(
            command.command_id,
            expected_state_version=1,
            claim_owner="runtime-worker:dead",
            lease_token="runtime-command-lease:dead",
            lease_expires_at="2026-07-21T00:00:01+00:00",
            now_iso=NOW,
            started_at=NOW,
        )
    assert expired.fencing_token == 1
    calls: list[str] = []

    outcome = RuntimeCommandWorker(
        repository_scope_factory=lambda: _repository_scope(provider),
        executor=lambda claimed: calls.append(claimed.command_id),  # type: ignore[arg-type,return-value]
        worker_id="runtime-worker:recovery",
        clock=lambda: "2026-07-21T00:00:02+00:00",
    ).run_once()

    assert calls == []
    assert outcome.action == "recovered_without_replay"
    assert outcome.semantic_progress is True
    with provider.read() as unit_of_work:
        stored = unit_of_work.repositories.runtime_commands.get(command.command_id)
    assert stored is not None
    assert stored.status is RuntimeCommandStatus.FAILED
    assert stored.fencing_token == 2
    assert stored.state_version == 4
    assert stored.error_code == "runtime_command_claim_expired"
    assert stored.bounded_outcome_summary == (
        runtime_command_pre_core_failure_summary(
            recovery_required=True
        )
    )


def test_runtime_command_repository_renews_without_advancing_state_version(
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    provider = _provider(tmp_path)
    command = _command(command_id="command_heartbeat")
    with provider.write() as unit_of_work:
        repositories = unit_of_work.repositories
        repositories.runtime_commands.add(command)
        claimed = repositories.runtime_commands.claim(
            command.command_id,
            expected_state_version=1,
            claim_owner="runtime-worker:a",
            lease_token="runtime-command-lease:a",
            lease_expires_at="2026-07-21T00:00:10+00:00",
            now_iso=NOW,
            started_at=NOW,
        )
        renewed = repositories.runtime_commands.renew_lease(
            replace(
                claimed,
                lease_expires_at="2026-07-21T00:00:20+00:00",
            ),
            expected_state_version=claimed.state_version,
            expected_lease_token=str(claimed.lease_token),
            expected_fencing_token=claimed.fencing_token,
        )

    assert renewed.state_version == claimed.state_version
    assert renewed.fencing_token == claimed.fencing_token
    assert renewed.lease_expires_at == "2026-07-21T00:00:20+00:00"
    with provider.read() as unit_of_work:
        assert unit_of_work.repositories.runtime_commands.count_active() == 1
        assert unit_of_work.repositories.runtime_commands.list_active() == [renewed]


def test_runtime_command_projection_recursively_redacts_private_authority() -> None:
    projected = project_runtime_command(
        replace(
            _command(command_id="command_projection"),
            bounded_outcome_summary={
                "facts": {
                    "processed_signal_count": 1,
                    "claim_owner": "private-worker",
                    "fencing-token": 42,
                    "control_socket": "/tmp/private.sock",
                },
                "lease_token": "private-lease",
                "host_path": "/tmp/private-result",
            },
            safe_error_summary="failed under /home/private/runtime",
        )
    )

    serialized = str(projected)
    assert projected["bounded_outcome_summary"] == {
        "facts": {"processed_signal_count": 1}
    }
    for secret in (
        "private-worker",
        "private-lease",
        "private.sock",
        "private-result",
        "/home/private/runtime",
    ):
        assert secret not in serialized


def test_runtime_command_projection_preserves_historical_v1_without_v2_invention() -> (
    None
):
    historical_summary = {
        "schema_version": "runtime_command_outcome@1",
        "processed_signal_count": 1,
        "suspended": True,
        "recovery_required": True,
    }

    projected = project_runtime_command(
        replace(
            _command(command_id="command_historical_v1"),
            status=RuntimeCommandStatus.FAILED,
            bounded_outcome_summary=historical_summary,
            error_code="historical_runtime_failure",
        )
    )

    assert projected["bounded_outcome_summary"] == historical_summary
    assert "scheduler_status" not in projected["bounded_outcome_summary"]
    assert "projection_status" not in projected["bounded_outcome_summary"]
    assert "replay_safe" not in projected["bounded_outcome_summary"]


def test_runtime_command_projection_rejects_corrupt_v2_without_leaking_private_data() -> (
    None
):
    corrupt = _completed_outcome_summary(
        processed_signal_count=1,
        suspended=False,
    )
    corrupt.update(
        {
            "replay_safe": True,
            "claim_owner": "private-worker",
            "host_path": "/home/private/runtime.sqlite3",
        }
    )

    projected = project_runtime_command(
        replace(
            _command(command_id="command_corrupt_v2"),
            status=RuntimeCommandStatus.COMPLETED,
            bounded_outcome_summary=corrupt,
        )
    )

    assert projected["bounded_outcome_summary"] is None
    assert "private-worker" not in str(projected)
    assert "/home/private/runtime.sqlite3" not in str(projected)


def test_two_runtime_command_workers_never_execute_one_claim_twice(tmp_path) -> None:  # type: ignore[no-untyped-def]
    provider = _provider(tmp_path)
    command = _command(command_id="command_two_workers")
    with provider.write() as unit_of_work:
        unit_of_work.repositories.runtime_commands.add(command)
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    first_outcome: list[object] = []

    def execute(claimed: RuntimeCommandRecord) -> RuntimeCommandExecutionResult:
        calls.append(claimed.command_id)
        entered.set()
        assert release.wait(timeout=2)
        return RuntimeCommandExecutionResult(
            status=RuntimeCommandStatus.COMPLETED,
            bounded_outcome_summary=_completed_outcome_summary(
                processed_signal_count=0,
                suspended=False,
            ),
        )

    first = RuntimeCommandWorker(
        repository_scope_factory=lambda: _repository_scope(provider),
        executor=execute,
        worker_id="runtime-worker:first",
        clock=lambda: "2026-07-21T00:00:01+00:00",
    )
    second = RuntimeCommandWorker(
        repository_scope_factory=lambda: _repository_scope(provider),
        executor=execute,
        worker_id="runtime-worker:second",
        clock=lambda: "2026-07-21T00:00:01+00:00",
    )
    thread = threading.Thread(target=lambda: first_outcome.append(first.run_once()))
    thread.start()
    assert entered.wait(timeout=1)

    raced = second.run_once()
    release.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert raced.action in {"idle", "claim_raced"}
    assert raced.semantic_progress is False
    assert calls == [command.command_id]
    assert getattr(first_outcome[0], "status") == "completed"
    assert getattr(first_outcome[0], "semantic_progress") is True


def test_runtime_command_database_busy_is_deferred_without_state_relabel(
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    database_path = str(tmp_path / "runtime-command-busy.sqlite3")
    provider = SQLiteRepositoryProvider(database_path, busy_timeout_ms=25)
    with provider.write() as unit_of_work:
        repositories = unit_of_work.repositories
        repositories.sessions.save(
            Session.create(
                session_id="sess_runtime_commands",
                project_id="proj_runtime_commands",
                title="Runtime commands",
                objective="Exercise durable command ownership",
            )
        )
        repositories.runtime_commands.add(_command(command_id="command_database_busy"))
    calls: list[str] = []

    def execute(claimed: RuntimeCommandRecord) -> RuntimeCommandExecutionResult:
        calls.append(claimed.command_id)
        return RuntimeCommandExecutionResult(
            status=RuntimeCommandStatus.COMPLETED,
            bounded_outcome_summary=_completed_outcome_summary(
                processed_signal_count=0,
                suspended=False,
            ),
        )

    worker = RuntimeCommandWorker(
        repository_scope_factory=lambda: _repository_scope(provider),
        executor=execute,
        worker_id="runtime-worker:database-busy",
        clock=lambda: "2026-07-21T00:00:01+00:00",
    )
    blocker = connect_sqlite(database_path, busy_timeout_ms=25, enable_wal=True)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        busy = worker.run_once()
    finally:
        blocker.rollback()
        blocker.close()

    assert busy.action == "database_busy"
    assert busy.semantic_progress is False
    assert calls == []
    with provider.read() as unit_of_work:
        persisted = unit_of_work.repositories.runtime_commands.get(
            "command_database_busy"
        )
    assert persisted is not None
    assert persisted.status is RuntimeCommandStatus.ACCEPTED
    assert persisted.state_version == 1

    progressed = worker.run_once()
    assert progressed.status == "completed"
    assert progressed.semantic_progress is True
    assert calls == ["command_database_busy"]
