from __future__ import annotations

from pathlib import Path
import json
import sqlite3

import pytest

from openzyme_store_sqlite import SQLiteConnectionProvider
from openzyme_store_sqlite import OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE
from openzyme_store_sqlite import SQLiteStoreAdapterError
from openzyme_store_sqlite import SQLiteStoreConfiguration
from openzyme_store_sqlite import SQLiteStartupCompositionExpectation
from openzyme_contracts import canonical_sha256_digest


def _activate_test_composition(
    database: Path,
) -> SQLiteStartupCompositionExpectation:
    epoch = "activation-1"
    payloads = {
        "adapter_bundle": {"kind": "adapter_bundle", "entries": ["sqlite"]},
        "extension_bundle": {"kind": "extension_bundle", "entries": []},
        "migration": {"kind": "migration", "generation": 2},
    }
    digests = {
        kind: canonical_sha256_digest(payload) for kind, payload in payloads.items()
    }
    connection = sqlite3.connect(database)
    connection.execute("BEGIN IMMEDIATE")
    connection.execute(
        """
        INSERT INTO openzyme_store_extension_bundle_records
        (bundle_digest, bundle_json, activated_epoch_id, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            digests["extension_bundle"],
            json.dumps(payloads["extension_bundle"], sort_keys=True),
            epoch,
            "2026-08-20T00:00:00+00:00",
        ),
    )
    for kind, payload in payloads.items():
        connection.execute(
            """
            INSERT INTO openzyme_store_catalog_identity_records
            (catalog_kind, catalog_digest, activation_epoch_id, catalog_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                kind,
                digests[kind],
                epoch,
                json.dumps(payload, sort_keys=True),
                "2026-08-20T00:00:00+00:00",
            ),
        )
    connection.commit()
    connection.close()
    return SQLiteStartupCompositionExpectation(
        activation_epoch_id=epoch,
        extension_bundle_digest=digests["extension_bundle"],
        catalog_digests=tuple(digests.items()),
    )


def test_configuration_is_closed_and_requires_absolute_path(tmp_path: Path) -> None:
    configuration = SQLiteStoreConfiguration.from_dict(
        {"database_path": str(tmp_path / "control.sqlite3")}
    )
    assert configuration.busy_timeout_ms == 5_000

    with pytest.raises(ValueError, match="unknown fields"):
        SQLiteStoreConfiguration.from_dict(
            {
                "database_path": str(tmp_path / "control.sqlite3"),
                "password": "must-not-be-accepted",
            }
        )
    with pytest.raises(ValueError, match="absolute"):
        SQLiteStoreConfiguration(database_path="relative.sqlite3")


def test_preflight_does_not_create_or_open_database(tmp_path: Path) -> None:
    database = tmp_path / "control.sqlite3"
    provider = SQLiteConnectionProvider(
        SQLiteStoreConfiguration(database_path=str(database))
    )

    observation = provider.preflight()

    assert observation.parent_exists is True
    assert observation.database_exists is False
    assert observation.database_opened is False
    assert observation.mutation_applied is False
    assert database.exists() is False


def test_explicit_offline_bootstrap_then_read_only_verify_and_writer_open(
    tmp_path: Path,
) -> None:
    database = tmp_path / "control.sqlite3"
    provider = SQLiteConnectionProvider(
        SQLiteStoreConfiguration(database_path=str(database))
    )

    schema_only = provider.bootstrap_fresh_offline()
    with pytest.raises(SQLiteStoreAdapterError, match="composition startup proof"):
        provider.open_writer(schema_only)

    expectation = _activate_test_composition(database)
    proof = provider.verify(expectation=expectation)
    observed = provider.verify(expectation=expectation)
    writer = provider.open_writer(proof)

    assert observed == proof
    assert proof.composition is not None
    assert writer.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    writer.close()


def test_fresh_bootstrap_refuses_existing_path(tmp_path: Path) -> None:
    database = tmp_path / "control.sqlite3"
    database.write_bytes(b"existing")
    provider = SQLiteConnectionProvider(
        SQLiteStoreConfiguration(database_path=str(database))
    )

    with pytest.raises(SQLiteStoreAdapterError, match="refuses an existing path"):
        provider.bootstrap_fresh_offline()


def test_fresh_standard_bootstrap_binds_selected_owner_schema_profile(
    tmp_path: Path,
) -> None:
    database = tmp_path / "standard.sqlite3"
    provider = SQLiteConnectionProvider(
        SQLiteStoreConfiguration(database_path=str(database))
    )

    proof = provider.bootstrap_fresh_offline(
        owner_schema_profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
    )

    assert proof.owner_schema.schema_profile_id == (
        OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE.profile_id
    )
    assert proof.owner_schema.schema_profile_digest == (
        OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE.profile_digest
    )
    assert proof.owner_schema.table_count == 98
    connection = sqlite3.connect(database)
    assert connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'scientific_attempt_records'"
    ).fetchone() is None
    connection.close()
