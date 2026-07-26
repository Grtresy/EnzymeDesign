from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import sqlite3
from threading import Barrier
from threading import Event

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import HOST_MUTATION_COVERAGE_DIGEST
from openzyme_core import MutationResourceCategory
from openzyme_core import MutationScopeError
from openzyme_core import MutationScopeService
from openzyme_core import MutationWriteFencingError
from openzyme_core import MutationWriterAdmissionReason
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import verify_quiescence_evidence_envelope
from openzyme_domain import MutationScopeKind
from openzyme_domain import MutationScopeState
from openzyme_domain import MutationWriterKind
from openzyme_domain import Session
from openzyme_domain import Task
from openzyme_domain import TaskStatus


NOW = "2026-07-21T00:00:00+00:00"


def _repositories(
    *,
    session_id: str = "sess_quiescence",
) -> tuple[sqlite3.Connection, CoreRepositories, Session]:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    session = Session.create(
        session_id=session_id,
        project_id="proj_quiescence",
        title="Quiescence",
        objective="Prove generic Host mutation closure",
    )
    repositories.sessions.save(session)
    return connection, repositories, session


def _service(repositories: CoreRepositories) -> MutationScopeService:
    return MutationScopeService(repositories, now=lambda: NOW)


def test_scope_freeze_receipt_seal_and_new_generation_are_monotonic() -> None:
    connection, repositories, session = _repositories()
    service = _service(repositories)
    scope = service.open_scope(
        session_id=session.session_id,
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="attempt:r41",
    )
    assert scope.generation == 1
    assert scope.writer_coverage_manifest_digest == HOST_MUTATION_COVERAGE_DIGEST

    with pytest.raises(sqlite3.IntegrityError, match="authority rejected"):
        connection.execute(
            "UPDATE sessions SET title = ? WHERE session_id = ?",
            ("detached", session.session_id),
        )
    connection.rollback()

    root = service.register_writer(
        scope_id=scope.scope_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="attempt-driver",
        trusted_root=True,
    )
    child = service.register_writer(
        scope_id=scope.scope_id,
        owner_kind=MutationWriterKind.SANDBOX_PROCESS,
        owner_ref="sandbox:run-1",
        parent_writer_id=root.writer_id,
        process_epoch=7,
    )
    child_authority = service.authority_for_writer(child.writer_id)
    with repositories.mutation_write_authority(child_authority):
        repositories.sessions.save(replace(session, title="written-by-child"))

    freezing = service.begin_freeze(scope.scope_id)
    assert freezing.state is MutationScopeState.FREEZING
    assert freezing.mutation_fencing_token == scope.mutation_fencing_token + 1
    with pytest.raises(MutationScopeError, match="admission is closed"):
        service.register_writer(
            scope_id=scope.scope_id,
            owner_kind=MutationWriterKind.ENGINE_CALLBACK,
            owner_ref="late-callback",
            parent_writer_id=root.writer_id,
        )
    with pytest.raises(MutationWriteFencingError, match="lost its scope"):
        with repositories.mutation_write_authority(child_authority):
            repositories.sessions.save(replace(session, title="late-write"))
    assert repositories.sessions.get(session.session_id).title == "written-by-child"

    with pytest.raises(MutationScopeError, match="child"):
        service.retire_writer(root.writer_id, terminal_proof={"kind": "complete"})
    with pytest.raises(MutationScopeError, match="exact writer epoch"):
        service.retire_writer(
            child.writer_id,
            terminal_proof={"kind": "process_exit"},
            expected_process_epoch=8,
        )
    service.retire_writer(
        child.writer_id,
        terminal_proof={"kind": "process_exit", "exit_code": 0},
        expected_process_epoch=7,
    )
    service.retire_writer(root.writer_id, terminal_proof={"kind": "complete"})

    issued = service.issue_quiescence_receipt(scope.scope_id)
    replayed = service.issue_quiescence_receipt(scope.scope_id)
    assert replayed.receipt == issued.receipt
    assert replayed.snapshot == issued.snapshot
    verify_quiescence_evidence_envelope(issued.evidence_envelope())

    sealed = service.seal_scope(
        scope.scope_id,
        receipt_id=issued.receipt.receipt_id,
    )
    assert sealed.state is MutationScopeState.SEALED
    assert sealed.sealed_receipt_digest == issued.receipt.receipt_digest
    with pytest.raises(sqlite3.IntegrityError, match="authority rejected"):
        connection.execute(
            "UPDATE sessions SET title = ? WHERE session_id = ?",
            ("post-seal", session.session_id),
        )
    connection.rollback()

    with pytest.raises(MutationScopeError, match="link the exact previous scope"):
        service.open_scope(
            session_id=session.session_id,
            scope_kind=MutationScopeKind.ATTEMPT,
            scope_ref="attempt:r41",
        )
    follow_up = service.open_scope(
        session_id=session.session_id,
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="attempt:r41",
        parent_scope_id=scope.scope_id,
    )
    assert follow_up.generation == 2
    follow_up_writer = service.register_writer(
        scope_id=follow_up.scope_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="attempt-driver:follow-up",
        trusted_root=True,
    )
    with repositories.mutation_write_authority(
        service.authority_for_writer(follow_up_writer.writer_id)
    ):
        repositories.sessions.save(replace(session, title="follow-up-write"))
    assert (
        repositories.quiescence_snapshots.get(issued.snapshot.snapshot_id)
        == issued.snapshot
    )


def test_writer_resource_category_is_closed_and_public_projection_is_redacted() -> None:
    _, repositories, session = _repositories()
    service = _service(repositories)
    scope = service.open_scope(
        session_id=session.session_id,
        scope_kind=MutationScopeKind.SESSION,
        scope_ref=session.session_id,
    )
    writer = service.register_writer(
        scope_id=scope.scope_id,
        owner_kind=MutationWriterKind.ARTIFACT_PUBLISHER,
        owner_ref="/private/host/path?token=secret",
        process_epoch=99,
        trusted_root=True,
    )
    authority = service.authority_for_writer(writer.writer_id)
    with repositories.mutation_write_authority(authority):
        repositories.assert_mutation_write_authority(
            session_id=session.session_id,
            resource_category=MutationResourceCategory.ARTIFACT_PUBLICATION,
        )
        with pytest.raises(MutationWriteFencingError, match="resource authority"):
            repositories.assert_mutation_write_authority(
                session_id=session.session_id,
                resource_category=MutationResourceCategory.REPORT_PUBLICATION,
            )
    projection = service.project_scope(scope.scope_id)
    rendered = repr(projection)
    assert "private" not in rendered
    assert "secret" not in rendered
    assert "process_epoch" not in rendered
    assert "fencing" not in rendered
    assert projection["active_writer_counts"] == {"artifact_publisher": 1}


def test_nested_retirement_and_scope_closure_never_change_task_truth() -> None:
    _, repositories, session = _repositories()
    task = Task.create(
        task_id="task_strategy",
        session_id=session.session_id,
        subject="Agent-owned decision",
        description="Closure must not finish this task",
    )
    with repositories.atomic(prefix="seed_task"):
        repositories.tasks.seed_fixture(task)
    service = _service(repositories)
    scope = service.open_scope(
        session_id=session.session_id,
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="attempt:strategy",
    )
    writer = service.register_writer(
        scope_id=scope.scope_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="driver",
        trusted_root=True,
    )
    service.begin_freeze(scope.scope_id)
    service.retire_writer(
        writer.writer_id,
        terminal_proof={"kind": "local_process_exit", "external_effect": "unknown"},
    )
    issued = service.issue_quiescence_receipt(scope.scope_id)
    service.seal_scope(scope.scope_id, receipt_id=issued.receipt.receipt_id)
    assert repositories.tasks.get(task.task_id).status is TaskStatus.TODO


def test_returned_parent_stays_retiring_until_exact_child_epoch_retires() -> None:
    _, repositories, session = _repositories()
    service = _service(repositories)
    scope = service.open_scope(
        session_id=session.session_id,
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="attempt:attached-child",
    )
    root = service.register_writer(
        scope_id=scope.scope_id,
        owner_kind=MutationWriterKind.RUNTIME_COMMAND,
        owner_ref="command",
        trusted_root=True,
    )
    child = service.register_writer(
        scope_id=scope.scope_id,
        owner_kind=MutationWriterKind.SANDBOX_PROCESS,
        owner_ref="sandbox-process",
        parent_writer_id=root.writer_id,
        process_epoch=11,
    )
    retiring = service.finish_writer_turn(
        root.writer_id,
        terminal_proof={"kind": "command_returned"},
    )
    assert retiring.state.value == "retiring"
    service.finish_writer_turn(
        child.writer_id,
        terminal_proof={"kind": "process_exited"},
        expected_process_epoch=11,
    )
    assert repositories.mutation_writers.get(root.writer_id).state.value == "retired"


def test_unstable_artifact_snapshot_and_incomplete_guard_withhold_receipt() -> None:
    connection, repositories, session = _repositories()
    counter = {"value": 0}

    def changing_artifacts(_: str) -> dict[str, int]:
        counter["value"] += 1
        return {"generation": counter["value"]}

    service = MutationScopeService(
        repositories,
        now=lambda: NOW,
        artifact_snapshot_provider=changing_artifacts,
    )
    scope = service.open_scope(
        session_id=session.session_id,
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="attempt:unstable",
    )
    writer = service.register_writer(
        scope_id=scope.scope_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="driver",
        trusted_root=True,
    )
    service.begin_freeze(scope.scope_id)
    service.retire_writer(writer.writer_id, terminal_proof={"kind": "complete"})
    with pytest.raises(MutationScopeError, match="changed during final verification"):
        service.issue_quiescence_receipt(scope.scope_id)
    assert (
        repositories.quiescence_receipts.get_by_scope(
            scope_id=scope.scope_id,
            seal_generation=scope.generation,
        )
        is None
    )

    connection.execute("DROP TRIGGER mutation_guard_tasks_insert")
    connection.commit()
    stable_service = _service(repositories)
    with pytest.raises(MutationScopeError, match="lacks a database guard"):
        stable_service.issue_quiescence_receipt(scope.scope_id)


def test_offline_verifier_detects_snapshot_receipt_and_high_watermark_tampering() -> (
    None
):
    _, repositories, session = _repositories()
    service = _service(repositories)
    scope = service.open_scope(
        session_id=session.session_id,
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="attempt:tamper",
    )
    writer = service.register_writer(
        scope_id=scope.scope_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="driver",
        trusted_root=True,
    )
    service.begin_freeze(scope.scope_id)
    service.retire_writer(writer.writer_id, terminal_proof={"kind": "complete"})
    issued = service.issue_quiescence_receipt(scope.scope_id)
    envelope = issued.evidence_envelope()

    snapshot_tamper = deepcopy(envelope)
    resources = snapshot_tamper["snapshot"]["evidence"]["resources"]
    session_resource = next(
        item for item in resources if item["table_name"] == "sessions"
    )
    session_resource["rows"][0]["title"] = "rewritten"
    with pytest.raises(MutationScopeError, match="snapshot bytes"):
        verify_quiescence_evidence_envelope(snapshot_tamper)

    receipt_tamper = deepcopy(envelope)
    receipt_tamper["receipt"]["event_high_watermark"] = "sha256:" + "0" * 64
    with pytest.raises(MutationScopeError, match="snapshot field"):
        verify_quiescence_evidence_envelope(receipt_tamper)


def test_registration_freeze_race_has_one_serialized_order(tmp_path) -> None:
    provider = SQLiteRepositoryProvider(
        str(tmp_path / "quiescence-race.sqlite3"),
        check_same_thread=False,
    )
    with provider.connection_scope() as scope_owner:
        session = Session.create(
            session_id="sess_race",
            project_id="proj_race",
            title="Race",
            objective="Serialize registration against freeze",
        )
        scope_owner.repositories.sessions.save(session)
        scope = MutationScopeService(scope_owner.repositories).open_scope(
            session_id=session.session_id,
            scope_kind=MutationScopeKind.ATTEMPT,
            scope_ref="attempt:race",
        )
    barrier = Barrier(2)

    def register() -> str:
        barrier.wait()
        with provider.connection_scope() as owner:
            try:
                MutationScopeService(owner.repositories).register_writer(
                    scope_id=scope.scope_id,
                    owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
                    owner_ref="racing-driver",
                    trusted_root=True,
                )
            except MutationScopeError:
                return "rejected"
            return "registered"

    def freeze() -> str:
        barrier.wait()
        with provider.connection_scope() as owner:
            MutationScopeService(owner.repositories).begin_freeze(scope.scope_id)
        return "frozen"

    with ThreadPoolExecutor(max_workers=2) as executor:
        register_result = executor.submit(register)
        freeze_result = executor.submit(freeze)
        outcomes = {register_result.result(), freeze_result.result()}
    assert "frozen" in outcomes
    assert outcomes <= {"frozen", "registered", "rejected"}
    with provider.read() as reader:
        stored_scope = reader.repositories.mutation_scopes.get(scope.scope_id)
        active = reader.repositories.mutation_writers.list_active(scope.scope_id)
    assert stored_scope is not None
    assert stored_scope.state is MutationScopeState.FREEZING
    assert len(active) == (1 if "registered" in outcomes else 0)


def test_session_writer_admission_reasons_and_no_scope_compatibility() -> None:
    _, repositories, session = _repositories()
    service = _service(repositories)

    assert (
        service.register_session_writer(
            session_id=session.session_id,
            owner_kind=MutationWriterKind.RUNTIME_COMMAND,
            owner_ref="untracked-command",
        )
        is None
    )

    scope = service.open_scope(
        session_id=session.session_id,
        scope_kind=MutationScopeKind.SESSION,
        scope_ref=session.session_id,
    )
    service.begin_freeze(scope.scope_id)

    with pytest.raises(MutationScopeError) as session_error:
        service.register_session_writer(
            session_id=session.session_id,
            owner_kind=MutationWriterKind.RUNTIME_COMMAND,
            owner_ref="late-command",
        )
    assert session_error.value.code == "mutation_writer_admission_closed"
    assert session_error.value.details["mutation_writer_admission_reason"] == (
        MutationWriterAdmissionReason.ZERO_OPEN_SCOPE.value
    )
    assert session_error.value.details["open_scope_count"] == 0

    with pytest.raises(MutationScopeError) as scope_error:
        service.register_writer(
            scope_id=scope.scope_id,
            owner_kind=MutationWriterKind.RUNTIME_COMMAND,
            owner_ref="late-scope-command",
            trusted_root=True,
        )
    assert scope_error.value.details["mutation_writer_admission_reason"] == (
        MutationWriterAdmissionReason.SCOPE_CLOSED_DURING_REGISTRATION.value
    )
    assert scope_error.value.details["scope_state"] == "freezing"


def test_session_writer_admission_rejects_ambiguous_open_scopes() -> None:
    connection, repositories, session = _repositories()
    service = _service(repositories)
    first = service.open_scope(
        session_id=session.session_id,
        scope_kind=MutationScopeKind.SESSION,
        scope_ref=session.session_id,
    )
    connection.execute("DROP INDEX idx_mutation_scopes_one_active_per_session")
    connection.commit()
    repositories.mutation_scopes.add(
        replace(
            first,
            scope_id="mutation_scope_corrupt_competitor",
            scope_ref="corrupt-competing-session-scope",
            generation=2,
        )
    )

    with pytest.raises(MutationScopeError) as caught:
        service.register_session_writer(
            session_id=session.session_id,
            owner_kind=MutationWriterKind.RUNTIME_COMMAND,
            owner_ref="ambiguous-command",
        )
    assert caught.value.code == "mutation_writer_admission_ambiguous"
    assert caught.value.details["mutation_writer_admission_reason"] == (
        MutationWriterAdmissionReason.AMBIGUOUS_OPEN_SCOPES.value
    )
    assert caught.value.details["open_scope_count"] == 2
    assert repositories.mutation_writers.list_active(first.scope_id) == []


def test_file_backed_session_admission_observes_freeze_commit_atomically(
    tmp_path,
) -> None:
    provider = SQLiteRepositoryProvider(
        str(tmp_path / "session-admission-freeze.sqlite3"),
        check_same_thread=False,
        busy_timeout_ms=10_000,
    )
    with provider.connection_scope() as owner:
        session = Session.create(
            session_id="sess_session_admission_freeze",
            project_id="proj_session_admission_freeze",
            title="Atomic session admission",
            objective="Freeze wins before writer selection commits",
        )
        owner.repositories.sessions.save(session)
        scope = MutationScopeService(owner.repositories).open_scope(
            session_id=session.session_id,
            scope_kind=MutationScopeKind.ATTEMPT,
            scope_ref="attempt:atomic-session-admission",
        )

    freeze_commit_reached = Event()
    release_freeze_commit = Event()
    registration_started = Event()

    def freeze() -> None:
        with provider.connection_scope() as owner:
            blocked = False

            def trace(statement: str) -> None:
                nonlocal blocked
                if statement.strip().upper() == "COMMIT" and not blocked:
                    blocked = True
                    freeze_commit_reached.set()
                    assert release_freeze_commit.wait(timeout=5)

            owner.connection.set_trace_callback(trace)
            MutationScopeService(owner.repositories).begin_freeze(scope.scope_id)

    def register() -> MutationScopeError:
        with provider.connection_scope() as owner:
            registration_started.set()
            with pytest.raises(MutationScopeError) as caught:
                MutationScopeService(owner.repositories).register_session_writer(
                    session_id=session.session_id,
                    owner_kind=MutationWriterKind.RUNTIME_COMMAND,
                    owner_ref="observer-after-freeze",
                )
            return caught.value

    with ThreadPoolExecutor(max_workers=2) as executor:
        freeze_future = executor.submit(freeze)
        assert freeze_commit_reached.wait(timeout=5)
        register_future = executor.submit(register)
        assert registration_started.wait(timeout=5)
        release_freeze_commit.set()
        freeze_future.result()
        registration_error = register_future.result()

    assert registration_error.code == "mutation_writer_admission_closed"
    assert registration_error.details["mutation_writer_admission_reason"] == (
        MutationWriterAdmissionReason.ZERO_OPEN_SCOPE.value
    )
    with provider.read() as reader:
        stored_scope = reader.repositories.mutation_scopes.get(scope.scope_id)
        active = reader.repositories.mutation_writers.list_active(scope.scope_id)
    assert stored_scope is not None
    assert stored_scope.state is MutationScopeState.FREEZING
    assert active == []


def test_unknown_policy_coverage_and_detached_writer_fail_before_authority() -> None:
    _, repositories, session = _repositories()
    service = _service(repositories)
    with pytest.raises(MutationScopeError, match="policy is not supported"):
        service.open_scope(
            session_id=session.session_id,
            scope_kind=MutationScopeKind.SESSION,
            scope_ref=session.session_id,
            policy_id="unknown",
        )
    with pytest.raises(MutationScopeError, match="incomplete or unknown"):
        service.open_scope(
            session_id=session.session_id,
            scope_kind=MutationScopeKind.SESSION,
            scope_ref=session.session_id,
            coverage_digest="sha256:unknown",
        )
    scope = service.open_scope(
        session_id=session.session_id,
        scope_kind=MutationScopeKind.SESSION,
        scope_ref=session.session_id,
    )
    with pytest.raises(MutationScopeError, match="trusted-root"):
        service.register_writer(
            scope_id=scope.scope_id,
            owner_kind=MutationWriterKind.RUNTIME_COMMAND,
            owner_ref="command",
        )
