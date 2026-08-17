from __future__ import annotations

import sqlite3

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import connect_sqlite
from openzyme_core.migration_assets import apply_sqlite_migrations
from openzyme_core.migration_assets import CURRENT_SQLITE_SCHEMA_VERSION
from openzyme_core.migration_assets import FINAL_SCHEMA_GENERATION
from openzyme_core.migration_assets import FINAL_SCHEMA_MANIFEST_DIGEST
from openzyme_core.migration_assets import SQLiteSchemaMismatchError
from openzyme_core.migration_assets import _schema_manifest_digest


def test_fresh_database_initializes_directly_to_the_final_schema() -> None:
    connection = connect_sqlite(":memory:")

    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    first_manifest = _schema_manifest_digest(connection)
    apply_sqlite_migrations(connection)

    state = connection.execute(
        "SELECT schema_generation, removal_state, manifest_digest "
        "FROM deployment_schema_state WHERE singleton=1"
    ).fetchone()
    assert tuple(state) == (
        FINAL_SCHEMA_GENERATION,
        "fresh_install_complete",
        FINAL_SCHEMA_MANIFEST_DIGEST,
    )
    assert first_manifest == FINAL_SCHEMA_MANIFEST_DIGEST
    assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == (
        CURRENT_SQLITE_SCHEMA_VERSION
    )
    assert repositories.sessions.list_by_project("missing") == []
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


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

    with pytest.raises(SQLiteSchemaMismatchError, match="legacy_removal_incomplete"):
        apply_sqlite_migrations(connection)
