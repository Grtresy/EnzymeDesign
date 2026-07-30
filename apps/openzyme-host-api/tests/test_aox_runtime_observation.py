from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import MutationScopeService
from openzyme_core import RuntimeBarrierBlockerCode
from openzyme_core import RuntimeBarrierCounts
from openzyme_core import RuntimeBarrierProjection
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import MutationScopeKind
from openzyme_domain import MutationWriterKind
from openzyme_domain import Session
from openzyme_host_api import aox_cutover_live
from openzyme_host_api.aox_runtime_observation import AoxRuntimeObservationError
from openzyme_host_api.aox_runtime_observation import AoxRuntimeObservationService
from openzyme_host_api.evals import S15_AOX_HMM_FIXED_DELIVERABLES


SESSION_ID = "sess_aox_runtime_observation"


def _file_backed_repositories(tmp_path: Path):
    database_path = tmp_path / "aox-runtime-observation.sqlite3"
    connection = connect_sqlite(str(database_path))
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    repositories.sessions.save(
        Session.create(
            session_id=SESSION_ID,
            project_id="proj_aox_runtime_observation",
            title="AOX runtime observation",
            objective="Keep campaign policy outside the generic barrier",
        )
    )
    return (
        connection,
        repositories,
        SQLiteRepositoryProvider(str(database_path)),
    )


def test_aox_observer_excludes_exact_driver_and_tracks_attached_writer(
    tmp_path: Path,
) -> None:
    connection, repositories, provider = _file_backed_repositories(tmp_path)
    mutation_service = MutationScopeService(repositories)
    mutation_scope = mutation_service.open_scope(
        session_id=SESSION_ID,
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="aox-attempt:attempt_001:formal",
    )
    driver = mutation_service.register_writer(
        scope_id=mutation_scope.scope_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="aox-attempt-driver:attempt_001:formal",
        trusted_root=True,
    )
    observer = AoxRuntimeObservationService(provider)

    assert not observer.has_inflight_mutation_writers(session_id=SESSION_ID)
    incomplete = observer.observe_session(session_id=SESSION_ID, purpose="probe")
    assert incomplete.state == "incomplete"
    assert incomplete.barrier.ready
    assert incomplete.barrier.observer_writer_id == driver.writer_id

    child = mutation_service.register_writer(
        scope_id=mutation_scope.scope_id,
        owner_kind=MutationWriterKind.SANDBOX_PROCESS,
        owner_ref="sandbox:run_001",
        parent_writer_id=driver.writer_id,
        process_epoch=1,
    )
    assert observer.has_inflight_mutation_writers(session_id=SESSION_ID)
    active = observer.observe_session(session_id=SESSION_ID, purpose="formal")
    assert active.state == "incomplete"
    assert active.barrier.has_blocker(RuntimeBarrierBlockerCode.ACTIVE_MUTATION_WRITER)

    mutation_service.retire_writer(
        child.writer_id,
        terminal_proof={"kind": "process_exit", "exit_code": 0},
        expected_process_epoch=1,
    )
    assert not observer.has_inflight_mutation_writers(session_id=SESSION_ID)
    connection.close()


def test_aox_observer_rejects_open_scope_without_exact_driver(tmp_path: Path) -> None:
    connection, repositories, provider = _file_backed_repositories(tmp_path)
    MutationScopeService(repositories).open_scope(
        session_id=SESSION_ID,
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="aox-attempt:attempt_missing_driver:probe",
    )

    with pytest.raises(AoxRuntimeObservationError) as error:
        AoxRuntimeObservationService(provider).project_barrier(session_id=SESSION_ID)

    assert error.value.code == "mutation_driver_writer_identity_invalid"
    connection.close()


def test_aox_observer_rejects_missing_open_scope(tmp_path: Path) -> None:
    connection, _, provider = _file_backed_repositories(tmp_path)

    with pytest.raises(AoxRuntimeObservationError) as error:
        AoxRuntimeObservationService(provider).project_barrier(session_id=SESSION_ID)

    assert error.value.code == "mutation_scope_coordination_invalid"
    connection.close()


def test_aox_observer_rejects_ambiguous_open_scopes(tmp_path: Path) -> None:
    connection, repositories, provider = _file_backed_repositories(tmp_path)
    mutation_scope = MutationScopeService(repositories).open_scope(
        session_id=SESSION_ID,
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="aox-attempt:attempt_ambiguous:formal",
    )
    # Corrupt the persisted invariant deliberately to prove the read boundary
    # still fails closed if an older or externally damaged database contains
    # more than one active scope.
    connection.execute("DROP INDEX idx_mutation_scopes_one_active_per_session")
    connection.execute(
        """
        INSERT INTO mutation_scope_records (
            scope_id, schema_version, scope_kind, scope_ref, parent_scope_id,
            state, generation, mutation_fencing_token, state_version, policy_id,
            writer_coverage_manifest_digest, opened_at, freeze_requested_at,
            quiescent_at, sealed_at, failed_at, safe_error_summary, session_id,
            sealed_receipt_digest
        )
        SELECT
            ?, schema_version, scope_kind, ?, parent_scope_id,
            state, generation, mutation_fencing_token, state_version, policy_id,
            writer_coverage_manifest_digest, opened_at, freeze_requested_at,
            quiescent_at, sealed_at, failed_at, safe_error_summary, session_id,
            sealed_receipt_digest
        FROM mutation_scope_records
        WHERE scope_id = ?
        """,
        (
            "mutation_scope_ambiguous_second",
            "aox-attempt:attempt_ambiguous_second:formal",
            mutation_scope.scope_id,
        ),
    )
    connection.commit()

    with pytest.raises(AoxRuntimeObservationError) as error:
        AoxRuntimeObservationService(provider).project_barrier(session_id=SESSION_ID)

    assert error.value.code == "mutation_scope_coordination_invalid"
    connection.close()


def test_formal_product_readiness_waits_for_closed_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def records(items: tuple[object, ...] = ()):
        return SimpleNamespace(list_by_session=lambda _session_id: items)

    repositories = SimpleNamespace(
        controlled_operations=records(),
        tasks=records(
            tuple(
                SimpleNamespace(
                    kind=kind,
                    status=SimpleNamespace(value="completed"),
                )
                for kind in ("research", "execution", "reporting")
            )
        ),
        sandbox_runs=records(),
        artifacts=records(
            tuple(
                SimpleNamespace(relative_path=path)
                for path in S15_AOX_HMM_FIXED_DELIVERABLES
            )
        ),
        reports=records(
            (
                SimpleNamespace(
                    status=SimpleNamespace(value="published"),
                ),
            )
        ),
        report_drafts=records(
            (
                SimpleNamespace(
                    status=SimpleNamespace(value="published"),
                ),
            )
        ),
        agents=records(
            tuple(
                SimpleNamespace(role=role)
                for role in ("researcher", "executor", "reporter")
            )
        ),
    )

    @contextmanager
    def read_scope():
        yield SimpleNamespace(repositories=repositories)

    barrier = RuntimeBarrierProjection(
        session_id=SESSION_ID,
        task_id=None,
        ready=True,
        blocker_codes=(),
        counts=RuntimeBarrierCounts(),
        active_durable_suspension_task_ids=(),
        observer_writer_id="writer_formal_observer",
        record_limit=10_000,
        observed_record_count=0,
        records_truncated=False,
        latest_runtime_command_status=None,
    )
    monkeypatch.setattr(
        "openzyme_host_api.aox_runtime_observation."
        "RuntimeBarrierProjectionService.project",
        lambda *_args, **_kwargs: barrier,
    )
    monkeypatch.setattr(
        "openzyme_host_api.aox_runtime_observation.build_conversation_projection",
        lambda *_args, **_kwargs: (SimpleNamespace(role="assistant"),),
    )
    observer = AoxRuntimeObservationService(
        SimpleNamespace(read=read_scope)  # type: ignore[arg-type]
    )

    open_attempt = observer.observe_session(
        session_id=SESSION_ID,
        purpose="formal",
    )
    closed_attempt = observer.observe_session(
        session_id=SESSION_ID,
        purpose="formal",
        formal_attempt_closed=True,
    )

    assert open_attempt.state == "incomplete"
    assert open_attempt.blocker_code == "scientific_attempt_open"
    assert closed_attempt.state == "completed"
    assert closed_attempt.blocker_code is None


def test_campaign_driver_does_not_reintroduce_direct_runtime_database_helpers() -> None:
    source = Path(aox_cutover_live.__file__).read_text(encoding="utf-8")

    assert "def _task_has_active_durable_suspension" not in source
    assert "def _session_has_inflight_mutation_writers" not in source
    assert "def _session_state" not in source
