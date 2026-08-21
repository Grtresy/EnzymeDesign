from __future__ import annotations

import sqlite3
import json

import pytest

from openzyme_store_sqlite import OwnerPartitionedSchemaVerificationError
from openzyme_store_sqlite import SQLiteStartupVerificationError
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration
from openzyme_store_sqlite import verify_composite_store_schema_read_only
from openzyme_store_sqlite import SQLiteStartupCompositionExpectation
from openzyme_store_sqlite import SQLiteStartupCompositionVerificationError
from openzyme_contracts import canonical_sha256_digest


def _database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(connection)
    install_store_schema_for_offline_migration(connection)
    return connection


def test_composite_startup_proves_both_exact_closures_without_writes() -> None:
    connection = _database()
    before = connection.total_changes

    proof = verify_composite_store_schema_read_only(connection)

    assert proof.user_version == 4
    assert proof.owner_schema.table_count == 150
    assert proof.store_schema.object_count == 23
    assert proof.complete_object_count == 150 + 134 + 679 + 23
    assert proof.mutation_applied is False
    assert proof.plugin_import_performed is False
    assert proof.writer_enabled is False
    assert connection.total_changes == before
    assert connection.in_transaction is False


def test_composite_startup_attributes_owner_and_store_namespace_drift() -> None:
    owner_drift = _database()
    owner_drift.execute("DROP TRIGGER mutation_guard_tasks_insert")
    owner_drift.commit()
    with pytest.raises(OwnerPartitionedSchemaVerificationError):
        verify_composite_store_schema_read_only(owner_drift)

    store_drift = _database()
    store_drift.execute("DROP INDEX openzyme_store_outbox_pending_idx")
    store_drift.commit()
    with pytest.raises(SQLiteStartupVerificationError):
        verify_composite_store_schema_read_only(store_drift)


def test_owner_partitioned_installer_refuses_nonempty_database() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE existing (value TEXT)")
    with pytest.raises(OwnerPartitionedSchemaVerificationError) as error:
        install_owner_partitioned_schema_for_offline_migration(connection)
    assert error.value.phase == "offline_migration_admission"
    assert error.value.mutation_applied is False


def test_composition_identity_is_verified_before_plugin_import_or_writer() -> None:
    connection = _database()
    payloads = {
        "adapter_bundle": {"adapters": ["openzyme.store.sqlite"]},
        "extension_bundle": {"plugins": []},
        "migration": {"catalog": "migration@1"},
    }
    digests = {
        kind: canonical_sha256_digest(payload) for kind, payload in payloads.items()
    }
    connection.execute("BEGIN IMMEDIATE")
    connection.execute(
        """
        INSERT INTO openzyme_store_extension_bundle_records
        VALUES (?, ?, ?, ?)
        """,
        (
            digests["extension_bundle"],
            json.dumps(payloads["extension_bundle"], sort_keys=True),
            "activation-1",
            "2026-08-20T00:00:00+00:00",
        ),
    )
    for kind, payload in payloads.items():
        connection.execute(
            """
            INSERT INTO openzyme_store_catalog_identity_records
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                kind,
                digests[kind],
                "activation-1",
                json.dumps(payload, sort_keys=True),
                "2026-08-20T00:00:00+00:00",
            ),
        )
    connection.commit()
    expectation = SQLiteStartupCompositionExpectation(
        activation_epoch_id="activation-1",
        extension_bundle_digest=digests["extension_bundle"],
        catalog_digests=tuple(digests.items()),
    )
    before = connection.total_changes

    proof = verify_composite_store_schema_read_only(
        connection,
        expectation=expectation,
    )

    assert proof.composition is not None
    assert proof.composition.verified_catalog_count == 3
    assert proof.plugin_import_performed is False
    assert proof.writer_enabled is False
    assert connection.total_changes == before


def test_composition_catalog_drift_fails_closed_with_zero_mutation() -> None:
    connection = _database()
    payload = {"plugins": []}
    digest = canonical_sha256_digest(payload)
    connection.execute(
        """
        INSERT INTO openzyme_store_extension_bundle_records
        VALUES (?, ?, ?, ?)
        """,
        (digest, json.dumps(payload), "activation-1", "2026-08-20T00:00:00+00:00"),
    )
    connection.commit()
    expectation = SQLiteStartupCompositionExpectation(
        activation_epoch_id="activation-1",
        extension_bundle_digest=digest,
        catalog_digests=(
            ("adapter_bundle", canonical_sha256_digest({"missing": "adapter"})),
            ("extension_bundle", digest),
            ("migration", canonical_sha256_digest({"missing": "migration"})),
        ),
    )
    before = connection.total_changes

    with pytest.raises(SQLiteStartupCompositionVerificationError) as error:
        verify_composite_store_schema_read_only(
            connection,
            expectation=expectation,
        )

    assert error.value.phase == "catalog_closure"
    assert error.value.mutation_applied is False
    assert error.value.plugin_import_performed is False
    assert connection.total_changes == before
