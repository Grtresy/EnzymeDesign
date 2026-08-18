from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import connect_sqlite
from openzyme_core.migration_assets import apply_sqlite_migrations
from openzyme_core.migration_assets import CURRENT_SQLITE_SCHEMA_VERSION
from openzyme_core.migration_assets import FINAL_SCHEMA_GENERATION
from openzyme_core.migration_assets import FINAL_SCHEMA_MANIFEST_DIGEST
from openzyme_core.migration_assets import FRESH_INSTALL_BOOTSTRAP_RECEIPT_DIGEST
from openzyme_core.migration_assets import SQLiteSchemaMismatchError
from openzyme_core.migration_assets import _schema_manifest_digest
from openzyme_core.deployment_schema_proofs import build_fresh_install_bootstrap_receipt
from openzyme_core.deployment_schema_proofs import canonical_digest


DIGEST = "sha256:" + "1" * 64


def _assert_rejected_without_mutation(
    connection: sqlite3.Connection,
    *,
    match: str,
) -> SQLiteSchemaMismatchError:
    before_total_changes = connection.total_changes
    before_transaction = connection.in_transaction
    before_bytes = connection.serialize()

    with pytest.raises(SQLiteSchemaMismatchError, match=match) as caught:
        apply_sqlite_migrations(connection)

    assert connection.total_changes == before_total_changes
    assert connection.in_transaction is before_transaction
    assert connection.serialize() == before_bytes
    assert caught.value.mutation_applied is False
    assert caught.value.fallback_performed is False
    assert caught.value.__cause__ is not None or caught.value.diagnostic_context
    return caught.value


def _fresh_connection() -> sqlite3.Connection:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return connection


def _seed_complete_offline_ledger(
    connection: sqlite3.Connection,
    *,
    dispositions: tuple[str, ...] = ("removed", "already_absent"),
) -> str:
    receipt_id = "legacy_removal_fixture"
    identities = [f"legacy-object-{index}" for index in range(len(dispositions))]
    removed = [
        identity
        for identity, disposition in zip(identities, dispositions, strict=True)
        if disposition == "removed"
    ]
    already_absent = [
        identity
        for identity, disposition in zip(identities, dispositions, strict=True)
        if disposition == "already_absent"
    ]
    sizes = [index + 1 for index in range(len(dispositions))]
    root_set_digest = canonical_digest([("fixture-root", DIGEST)])
    receipt_payload = {
        "schema": "legacy_subsystem_removal_receipt@2",
        "receipt_id": receipt_id,
        "schema_generation": FINAL_SCHEMA_GENERATION,
        "final_schema_manifest_digest": FINAL_SCHEMA_MANIFEST_DIGEST,
        "manifest_digest": DIGEST,
        "historical_receipt_digest": DIGEST,
        "database_backup_digest": DIGEST,
        "storage_backup_digest": DIGEST,
        "quiescence_receipt_digest": DIGEST,
        "expected_object_set_digest": canonical_digest(identities),
        "removed_object_set_digest": canonical_digest(removed),
        "already_absent_set_digest": canonical_digest(already_absent),
        "root_identity_set_digest": root_set_digest,
        "error_object_set_digest": canonical_digest([]),
        "expected_byte_total": sum(sizes),
        "removed_byte_total": sum(
            size
            for size, disposition in zip(sizes, dispositions, strict=True)
            if disposition == "removed"
        ),
        "completed_at": "2026-08-18T00:01:00+00:00",
        "state": "complete",
    }
    receipt_digest = canonical_digest(receipt_payload)
    connection.execute(
        """
        INSERT INTO legacy_removal_ledger (
            receipt_id, schema_generation, manifest_digest,
            historical_receipt_digest, database_backup_digest,
            storage_backup_digest, quiescence_receipt_digest,
            expected_object_set_digest, removed_object_set_digest,
            already_absent_set_digest, root_identity_set_digest,
            error_object_set_digest, expected_byte_total, removed_byte_total,
            state, created_at, completed_at, receipt_digest
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'complete', ?, ?, ?)
        """,
        (
            receipt_id,
            FINAL_SCHEMA_GENERATION,
            DIGEST,
            DIGEST,
            DIGEST,
            DIGEST,
            DIGEST,
            receipt_payload["expected_object_set_digest"],
            receipt_payload["removed_object_set_digest"],
            receipt_payload["already_absent_set_digest"],
            root_set_digest,
            receipt_payload["error_object_set_digest"],
            receipt_payload["expected_byte_total"],
            receipt_payload["removed_byte_total"],
            "2026-08-18T00:00:00+00:00",
            "2026-08-18T00:01:00+00:00",
            receipt_digest,
        ),
    )
    connection.executemany(
        """
        INSERT INTO legacy_removal_items (
            receipt_id, object_identity, root_identity, root_path_digest,
            relative_path, content_digest, size_bytes, state, error_digest,
            updated_at
        ) VALUES (?, ?, 'fixture-root', ?, ?, ?, ?, ?, NULL, ?)
        """,
        [
            (
                receipt_id,
                identity,
                DIGEST,
                f"legacy/{identity}.bin",
                DIGEST,
                size,
                disposition,
                "2026-08-18T00:01:00+00:00",
            )
            for identity, size, disposition in zip(
                identities,
                sizes,
                dispositions,
                strict=True,
            )
        ],
    )
    connection.execute(
        """
        UPDATE deployment_schema_state
        SET removal_state='offline_removal_complete',
            removal_receipt_digest=?
        WHERE singleton=1
        """,
        (receipt_digest,),
    )
    connection.commit()
    return receipt_digest


def test_fresh_database_initializes_directly_to_the_final_schema() -> None:
    connection = connect_sqlite(":memory:")

    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    first_manifest = _schema_manifest_digest(connection)
    apply_sqlite_migrations(connection)

    state = connection.execute(
        "SELECT schema_generation, removal_state, removal_receipt_digest, "
        "manifest_digest "
        "FROM deployment_schema_state WHERE singleton=1"
    ).fetchone()
    assert tuple(state) == (
        FINAL_SCHEMA_GENERATION,
        "fresh_install_complete",
        FRESH_INSTALL_BOOTSTRAP_RECEIPT_DIGEST,
        FINAL_SCHEMA_MANIFEST_DIGEST,
    )
    assert first_manifest == FINAL_SCHEMA_MANIFEST_DIGEST
    assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == (
        CURRENT_SQLITE_SCHEMA_VERSION
    )
    assert repositories.sessions.list_by_project("missing") == []
    assert connection.execute("SELECT COUNT(*) FROM legacy_removal_ledger").fetchone()[
        0
    ] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_fresh_bootstrap_receipt_is_deterministic_and_independently_recomputed() -> (
    None
):
    first = _fresh_connection()
    second = _fresh_connection()

    first_receipt = build_fresh_install_bootstrap_receipt(
        first,
        schema_generation=FINAL_SCHEMA_GENERATION,
        schema_manifest_digest=FINAL_SCHEMA_MANIFEST_DIGEST,
    )
    second_receipt = build_fresh_install_bootstrap_receipt(
        second,
        schema_generation=FINAL_SCHEMA_GENERATION,
        schema_manifest_digest=FINAL_SCHEMA_MANIFEST_DIGEST,
    )

    assert first_receipt == second_receipt
    assert first_receipt.receipt_digest == FRESH_INSTALL_BOOTSTRAP_RECEIPT_DIGEST
    assert first_receipt.legacy_initialization_performed is False
    assert first_receipt.empty_application_row_count == 0
    assert first_receipt.empty_application_table_count > 100


def test_normal_startup_rejects_a_retired_schema_without_mutating_it() -> None:
    connection = sqlite3.connect(":memory:")
    retired_table = "session_" + "arti" + "facts"
    connection.execute(f'CREATE TABLE "{retired_table}" (id TEXT PRIMARY KEY)')
    connection.execute(f'INSERT INTO "{retired_table}" VALUES ("old")')

    with pytest.raises(SQLiteSchemaMismatchError, match="offline upgrade"):
        apply_sqlite_migrations(connection)

    assert connection.execute(
        f'SELECT id FROM "{retired_table}"'
    ).fetchall() == [("old",)]
    assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == 0


def test_normal_startup_rejects_an_incomplete_offline_removal() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    connection.execute(
        "UPDATE deployment_schema_state SET removal_state=? WHERE singleton=1",
        ("offline_removal_incomplete",),
    )

    connection.commit()

    _assert_rejected_without_mutation(
        connection,
        match="legacy_removal_incomplete",
    )


@pytest.mark.parametrize(
    ("tamper", "match"),
    [
        (
            lambda connection: connection.execute(
                "UPDATE deployment_schema_state SET removal_receipt_digest=?",
                (DIGEST,),
            ),
            "fresh_install_receipt_mismatch",
        ),
        (
            lambda connection: connection.execute(
                "UPDATE deployment_schema_state SET manifest_digest=?",
                (DIGEST,),
            ),
            "manifest differs",
        ),
    ],
)
def test_fresh_startup_rejects_tampered_metadata_without_mutation(
    tamper: Callable[[sqlite3.Connection], object],
    match: str,
) -> None:
    connection = _fresh_connection()
    tamper(connection)
    connection.commit()

    error = _assert_rejected_without_mutation(connection, match=match)

    assert error.operator_action
    assert error.phase


def test_fresh_startup_accepts_valid_product_rows_without_replaying_bootstrap() -> None:
    connection = _fresh_connection()
    connection.execute(
        """
        INSERT INTO sessions (
            session_id, project_id, title, objective, status,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "session_after_bootstrap",
            "project_after_bootstrap",
            "Durable session",
            "Survive a normal restart",
            "active",
            "2026-08-18T00:00:00+00:00",
            "2026-08-18T00:00:00+00:00",
        ),
    )
    connection.commit()
    before_total_changes = connection.total_changes
    before_bytes = connection.serialize()

    apply_sqlite_migrations(connection)

    assert connection.total_changes == before_total_changes
    assert connection.serialize() == before_bytes
    assert [
        tuple(row)
        for row in connection.execute("SELECT session_id FROM sessions").fetchall()
    ] == [("session_after_bootstrap",)]


def test_fresh_startup_rejects_offline_ledger_variant_mixing() -> None:
    connection = _fresh_connection()
    _seed_complete_offline_ledger(connection)
    connection.execute(
        "UPDATE deployment_schema_state "
        "SET removal_state='fresh_install_complete', removal_receipt_digest=? "
        "WHERE singleton=1",
        (FRESH_INSTALL_BOOTSTRAP_RECEIPT_DIGEST,),
    )
    connection.commit()

    _assert_rejected_without_mutation(
        connection,
        match="fresh startup cannot consume or retain an offline removal ledger",
    )


def test_fresh_startup_rejects_wrong_variant_without_creating_offline_ledger() -> None:
    connection = _fresh_connection()
    connection.execute(
        "UPDATE deployment_schema_state SET removal_state=?, removal_receipt_digest=?",
        ("offline_removal_complete", DIGEST),
    )
    connection.commit()

    _assert_rejected_without_mutation(connection, match="one exact receipt-bound ledger")

    assert connection.execute("SELECT COUNT(*) FROM legacy_removal_ledger").fetchone()[
        0
    ] == 0


def test_fresh_startup_rejects_forbidden_structure_without_mutation() -> None:
    connection = _fresh_connection()
    retired_table = "retired_" + "arti" + "fact" + "_rows"
    connection.execute(f'CREATE TABLE "{retired_table}" (id TEXT PRIMARY KEY)')
    connection.commit()

    _assert_rejected_without_mutation(connection, match="retired structures")


def test_fresh_startup_rejects_foreign_key_failure_without_mutation() -> None:
    connection = _fresh_connection()
    connection.execute("PRAGMA foreign_keys=OFF")
    connection.execute(
        """
        INSERT INTO tasks (
            task_id, session_id, subject, description, status, priority, kind,
            assigned_ref, created_at, updated_at, lane_id, failure_summary,
            failure_ref
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, NULL, NULL)
        """,
        (
            "task_orphan",
            "missing_session",
            "Orphan",
            "Foreign key drift",
            "todo",
            "normal",
            "general",
            "2026-08-18T00:00:00+00:00",
            "2026-08-18T00:00:00+00:00",
        ),
    )
    connection.commit()

    _assert_rejected_without_mutation(connection, match="foreign-key closure")


def test_offline_complete_ledger_passes_independent_startup_verification() -> None:
    connection = _fresh_connection()
    receipt_digest = _seed_complete_offline_ledger(connection)

    apply_sqlite_migrations(connection)

    state = connection.execute(
        "SELECT removal_state, removal_receipt_digest FROM deployment_schema_state"
    ).fetchone()
    assert tuple(state) == ("offline_removal_complete", receipt_digest)


@pytest.mark.parametrize(
    ("tamper_sql", "parameters", "match"),
    [
        (
            "UPDATE legacy_removal_ledger SET state='incomplete', completed_at=NULL",
            (),
            "not a completed",
        ),
        (
            "UPDATE legacy_removal_ledger SET expected_byte_total=expected_byte_total+1",
            (),
            "item, byte, or error closure",
        ),
        (
            "UPDATE legacy_removal_items SET state='error', error_digest=? "
            "WHERE object_identity='legacy-object-0'",
            (DIGEST,),
            "item, byte, or error closure",
        ),
        (
            "DELETE FROM legacy_removal_items WHERE object_identity='legacy-object-0'",
            (),
            "item, byte, or error closure",
        ),
        (
            "UPDATE legacy_removal_ledger SET historical_receipt_digest=?",
            ("sha256:" + "3" * 64,),
            "does not bind",
        ),
        (
            "UPDATE legacy_removal_ledger SET completed_at=?",
            ("2026-08-18T00:02:00+00:00",),
            "does not bind",
        ),
    ],
)
def test_offline_startup_rejects_ledger_closure_drift_without_mutation(
    tamper_sql: str,
    parameters: tuple[object, ...],
    match: str,
) -> None:
    connection = _fresh_connection()
    _seed_complete_offline_ledger(connection)
    connection.execute(tamper_sql, parameters)
    connection.commit()

    _assert_rejected_without_mutation(connection, match=match)


def test_offline_startup_rejects_receipt_digest_drift_without_mutation() -> None:
    connection = _fresh_connection()
    _seed_complete_offline_ledger(connection)
    connection.execute(
        "UPDATE legacy_removal_ledger SET receipt_digest=?",
        (DIGEST,),
    )
    connection.execute(
        "UPDATE deployment_schema_state SET removal_receipt_digest=?",
        (DIGEST,),
    )
    connection.commit()

    _assert_rejected_without_mutation(connection, match="does not bind")


def test_offline_startup_rejects_multiple_ledgers_without_mutation() -> None:
    connection = _fresh_connection()
    _seed_complete_offline_ledger(connection)
    connection.execute(
        """
        INSERT INTO legacy_removal_ledger
        SELECT 'legacy_removal_extra', schema_generation, manifest_digest,
               historical_receipt_digest, database_backup_digest,
               storage_backup_digest, quiescence_receipt_digest,
               expected_object_set_digest, removed_object_set_digest,
               already_absent_set_digest, root_identity_set_digest,
               error_object_set_digest, expected_byte_total, removed_byte_total,
               state, created_at, completed_at, ?
        FROM legacy_removal_ledger WHERE receipt_id='legacy_removal_fixture'
        """,
        ("sha256:" + "2" * 64,),
    )
    connection.commit()

    _assert_rejected_without_mutation(connection, match="one exact receipt-bound ledger")


def test_offline_startup_rejects_generation_drift_without_mutation() -> None:
    connection = _fresh_connection()
    _seed_complete_offline_ledger(connection)
    connection.execute("PRAGMA ignore_check_constraints=ON")
    connection.execute(
        "UPDATE legacy_removal_ledger SET schema_generation=?",
        ("openzyme_file_workspace_final@999",),
    )
    connection.commit()
    connection.execute("PRAGMA ignore_check_constraints=OFF")

    _assert_rejected_without_mutation(connection, match="current-generation")


def test_startup_query_failure_preserves_sqlite_cause_without_mutation() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute(f"PRAGMA user_version={CURRENT_SQLITE_SCHEMA_VERSION}")

    error = _assert_rejected_without_mutation(connection, match="query failed")

    assert isinstance(error.__cause__, sqlite3.OperationalError)
    assert error.phase == "startup_schema_query"
    assert error.operator_action == "inspect_database_integrity_and_permissions"


def test_read_only_filesystem_initialization_failure_preserves_cause(
    tmp_path: Path,
) -> None:
    database = tmp_path / "read-only.sqlite3"
    database.touch()
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    before_bytes = database.read_bytes()
    before_total_changes = connection.total_changes
    before_transaction = connection.in_transaction

    with pytest.raises(
        SQLiteSchemaMismatchError,
        match="failed to initialize final SQLite schema",
    ) as caught:
        apply_sqlite_migrations(connection)

    error = caught.value
    assert isinstance(error.__cause__, sqlite3.OperationalError)
    assert connection.total_changes == before_total_changes
    assert connection.in_transaction is before_transaction
    assert database.read_bytes() == before_bytes
