from __future__ import annotations

from pathlib import Path

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import MutationScopeService
from openzyme_core import RuntimeBarrierBlockerCode
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import MutationScopeKind
from openzyme_domain import MutationWriterKind
from openzyme_domain import Session
from openzyme_host_api import aox_cutover_live
from openzyme_host_api.aox_runtime_observation import AoxRuntimeObservationError
from openzyme_host_api.aox_runtime_observation import AoxRuntimeObservationService


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
    assert active.barrier.has_blocker(
        RuntimeBarrierBlockerCode.ACTIVE_MUTATION_WRITER
    )

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


def test_campaign_driver_does_not_reintroduce_direct_runtime_database_helpers() -> None:
    source = Path(aox_cutover_live.__file__).read_text(encoding="utf-8")

    assert "def _task_has_active_durable_suspension" not in source
    assert "def _session_has_inflight_mutation_writers" not in source
    assert "def _session_state" not in source
