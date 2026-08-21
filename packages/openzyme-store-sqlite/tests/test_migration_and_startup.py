from __future__ import annotations

from dataclasses import replace
import sqlite3

import pytest

from openzyme_store_sqlite import ClosedSQLiteMigrationCatalog
from openzyme_store_sqlite import SQLiteMigrationCatalogError
from openzyme_store_sqlite import SQLiteStartupVerificationError
from openzyme_store_sqlite import STORE_MIGRATION_CATALOG
from openzyme_store_sqlite import STORE_MIGRATIONS
from openzyme_store_sqlite import install_store_schema_for_offline_migration
from openzyme_store_sqlite import verify_store_schema_read_only


def _database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    install_store_schema_for_offline_migration(connection)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def test_closed_catalog_and_startup_proof_are_exact_and_read_only() -> None:
    connection = _database()
    before = connection.total_changes

    proof = verify_store_schema_read_only(connection)

    assert proof.migration_catalog_digest == STORE_MIGRATION_CATALOG.catalog_digest
    assert proof.object_count == 23
    assert proof.foreign_key_count == 5
    assert proof.mutation_applied is False
    assert proof.plugin_import_performed is False
    assert proof.writer_enabled is False
    assert connection.total_changes == before
    assert connection.in_transaction is False


def test_catalog_rejects_digest_drift() -> None:
    drifted = replace(STORE_MIGRATIONS[0], sql_digest="sha256:" + "f" * 64)
    with pytest.raises(SQLiteMigrationCatalogError, match="digest drifted"):
        ClosedSQLiteMigrationCatalog((drifted,))


def test_startup_rejects_missing_schema_without_mutation() -> None:
    connection = sqlite3.connect(":memory:")
    before = connection.total_changes

    with pytest.raises(SQLiteStartupVerificationError) as caught:
        verify_store_schema_read_only(connection)

    assert caught.value.phase == "user_version"
    assert caught.value.mutation_applied is False
    assert connection.total_changes == before
    assert connection.in_transaction is False


def test_startup_rejects_unowned_object_without_repair() -> None:
    connection = _database()
    connection.execute("CREATE TABLE openzyme_store_stray_table (value TEXT)")
    before = connection.total_changes

    with pytest.raises(SQLiteStartupVerificationError) as caught:
        verify_store_schema_read_only(connection)

    assert caught.value.phase == "object_closure"
    assert caught.value.observed == {
        "missing": [],
        "unexpected": ["openzyme_store_stray_table"],
    }
    assert connection.total_changes == before
    assert connection.in_transaction is False
