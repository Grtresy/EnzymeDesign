from __future__ import annotations

import sqlite3

import pytest

from openzyme_store_sqlite import OwnerPartitionedSchemaVerificationError
from openzyme_store_sqlite import ENZYMEDESIGN_OWNER_SCHEMA_PROFILE
from openzyme_store_sqlite import OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE
from openzyme_store_sqlite import apply_sqlite_migrations
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration
from openzyme_store_sqlite import STORE_SCHEMA_USER_VERSION
from openzyme_store_sqlite import verify_owner_partitioned_schema_read_only


def _database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    apply_sqlite_migrations(connection)
    return connection


def test_owner_partitioned_startup_proof_is_read_only_and_plugin_free() -> None:
    connection = _database()
    before = connection.total_changes

    proof = verify_owner_partitioned_schema_read_only(connection)

    assert proof.table_count == 147
    assert proof.index_count == 134
    assert proof.trigger_count == 674
    assert proof.foreign_key_count == 422
    assert proof.mutation_applied is False
    assert proof.plugin_import_performed is False
    assert proof.writer_enabled is False
    assert connection.total_changes == before
    assert connection.in_transaction is False


def test_owner_partitioned_startup_rejects_schema_drift_without_repair() -> None:
    connection = _database()
    connection.execute("DROP TRIGGER mutation_guard_tasks_insert")
    connection.commit()
    before = connection.total_changes

    with pytest.raises(OwnerPartitionedSchemaVerificationError) as error:
        verify_owner_partitioned_schema_read_only(connection)

    assert error.value.phase == "object_closure"
    assert error.value.mutation_applied is False
    assert connection.total_changes == before
    assert connection.in_transaction is False


def _profile_database(profile) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(
        connection,
        profile=profile,
    )
    install_store_schema_for_offline_migration(connection)
    return connection


def test_fresh_standard_and_enzymedesign_profiles_install_only_selected_owners() -> None:
    standard = _profile_database(OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE)
    enzymedesign = _profile_database(ENZYMEDESIGN_OWNER_SCHEMA_PROFILE)

    standard_proof = verify_owner_partitioned_schema_read_only(
        standard,
        profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
        composite_user_version=STORE_SCHEMA_USER_VERSION,
    )
    enzymedesign_proof = verify_owner_partitioned_schema_read_only(
        enzymedesign,
        profile=ENZYMEDESIGN_OWNER_SCHEMA_PROFILE,
        composite_user_version=STORE_SCHEMA_USER_VERSION,
    )

    assert standard_proof.table_count == 98
    assert standard_proof.index_count == 104
    assert standard_proof.trigger_count == 449
    assert standard_proof.foreign_key_count == 300
    assert standard_proof.schema_profile_digest == (
        OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE.profile_digest
    )
    assert enzymedesign_proof.table_count == 144
    assert enzymedesign_proof.index_count == 134
    assert enzymedesign_proof.trigger_count == 674
    assert enzymedesign_proof.foreign_key_count == 421
    assert enzymedesign_proof.schema_profile_digest == (
        ENZYMEDESIGN_OWNER_SCHEMA_PROFILE.profile_digest
    )
    assert standard_proof.observed_schema_digest != (
        enzymedesign_proof.observed_schema_digest
    )

    standard_tables = {
        str(row[0])
        for row in standard.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    enzyme_tables = {
        str(row[0])
        for row in enzymedesign.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert "scientific_attempt_records" not in standard_tables
    assert "executor_hpc_workspace_records" not in standard_tables
    assert "session_report_draft_records" not in standard_tables
    assert "legacy_removal_ledger" not in standard_tables
    assert "scientific_attempt_records" in enzyme_tables
    assert "executor_hpc_workspace_records" in enzyme_tables
    assert "session_report_draft_records" in enzyme_tables
    assert "legacy_removal_ledger" not in enzyme_tables


def test_profile_verifier_rejects_cross_distribution_schema_without_mutation() -> None:
    enzymedesign = _profile_database(ENZYMEDESIGN_OWNER_SCHEMA_PROFILE)
    before = enzymedesign.total_changes

    with pytest.raises(OwnerPartitionedSchemaVerificationError) as rejected:
        verify_owner_partitioned_schema_read_only(
            enzymedesign,
            profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
            composite_user_version=STORE_SCHEMA_USER_VERSION,
        )

    assert rejected.value.phase == "object_closure"
    assert rejected.value.mutation_applied is False
    assert enzymedesign.total_changes == before
