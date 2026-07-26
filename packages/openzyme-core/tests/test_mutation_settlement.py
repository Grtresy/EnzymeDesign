from __future__ import annotations

import sqlite3

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import MutationLocalSettlementError
from openzyme_core import MutationScopeService
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import project_mutation_local_settlement
from openzyme_domain import MutationScopeKind
from openzyme_domain import MutationWriterKind
from openzyme_domain import Session


def _repositories() -> tuple[sqlite3.Connection, CoreRepositories, Session]:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    session = Session.create(
        session_id="sess_local_settlement",
        project_id="proj_local_settlement",
        title="Local settlement",
        objective="Prove process-local writer retirement",
    )
    repositories.sessions.save(session)
    return connection, repositories, session


def test_projection_without_mutation_tables_is_stable() -> None:
    connection = sqlite3.connect(":memory:")

    first = project_mutation_local_settlement(connection)
    second = project_mutation_local_settlement(connection)

    assert first == second
    assert first.tables_present is False
    assert first.nonterminal_scope_count == 0
    assert first.active_writer_count == 0
    assert first.observed_row_count == 0


def test_projection_accepts_terminal_scopes_and_writer_free_open_scope() -> None:
    connection, repositories, session = _repositories()
    service = MutationScopeService(repositories)
    first = service.open_scope(
        session_id=session.session_id,
        scope_kind=MutationScopeKind.SESSION,
        scope_ref="pre-attempt",
    )
    service.begin_freeze(first.scope_id)
    issued = service.issue_quiescence_receipt(first.scope_id)
    service.seal_scope(first.scope_id, receipt_id=issued.receipt.receipt_id)
    service.open_scope(
        session_id=session.session_id,
        scope_kind=MutationScopeKind.SESSION,
        scope_ref="post-attempt",
        parent_scope_id=first.scope_id,
    )

    first_projection = project_mutation_local_settlement(connection)
    second_projection = project_mutation_local_settlement(connection)

    assert first_projection == second_projection
    assert first_projection.tables_present is True
    assert first_projection.nonterminal_scope_count == 1
    assert first_projection.active_writer_count == 0
    assert first_projection.scope_state_counts == {"open": 1, "sealed": 1}


def test_projection_rejects_active_writer_without_rejecting_open_scope() -> None:
    connection, repositories, session = _repositories()
    service = MutationScopeService(repositories)
    scope = service.open_scope(
        session_id=session.session_id,
        scope_kind=MutationScopeKind.SESSION,
        scope_ref="active",
    )
    service.register_writer(
        scope_id=scope.scope_id,
        owner_kind=MutationWriterKind.ATTEMPT_DRIVER,
        owner_ref="driver",
        trusted_root=True,
    )

    with pytest.raises(
        MutationLocalSettlementError,
        match="active writers",
    ) as exc_info:
        project_mutation_local_settlement(connection)

    assert exc_info.value.code == "mutation_writers_active"
    assert exc_info.value.details["active_writer_count"] == 1


def test_projection_rejects_incomplete_authority_schema() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE mutation_scope_records (scope_id TEXT)")

    with pytest.raises(MutationLocalSettlementError) as exc_info:
        project_mutation_local_settlement(connection)

    assert exc_info.value.code == "mutation_settlement_schema_incomplete"


def test_projection_enforces_bounded_rows_and_bytes() -> None:
    connection, repositories, session = _repositories()
    MutationScopeService(repositories).open_scope(
        session_id=session.session_id,
        scope_kind=MutationScopeKind.SESSION,
        scope_ref="bounded",
    )

    with pytest.raises(MutationLocalSettlementError) as row_error:
        project_mutation_local_settlement(connection, max_rows=0)
    assert row_error.value.code == "mutation_settlement_bounds_invalid"

    with pytest.raises(MutationLocalSettlementError) as byte_error:
        project_mutation_local_settlement(connection, max_bytes=1)
    assert byte_error.value.code == "mutation_settlement_byte_limit_exceeded"
