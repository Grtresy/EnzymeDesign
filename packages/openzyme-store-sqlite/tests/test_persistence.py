from __future__ import annotations

import sqlite3

import pytest

from openzyme_contracts import ResourceCapabilityFact
from openzyme_contracts import ResourceCapabilityKind
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import TargetInventoryBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_store_sqlite import SQLiteCompositionIdentityRepository
from openzyme_store_sqlite import SQLitePersistenceError
from openzyme_store_sqlite import SQLiteResourceCapabilityFactRepository
from openzyme_store_sqlite import SQLiteSessionCapabilityBindingRepository
from openzyme_store_sqlite import SQLiteUnitOfWork
from openzyme_store_sqlite import SQLiteWorkspaceOperationReceiptRepository
from openzyme_store_sqlite import install_store_schema_for_offline_migration


def _database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    install_store_schema_for_offline_migration(connection)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _binding(revision: int, *, generation: int) -> SessionCapabilityBindingRevision:
    return SessionCapabilityBindingRevision.create(
        binding_id=f"binding-{revision}",
        session_id="session-1",
        revision=revision,
        extension_bundle_digest="sha256:" + "a" * 64,
        route_catalog_digest="sha256:" + "b" * 64,
        inventory_bindings=(
            TargetInventoryBinding(
                target_id="hpc-primary",
                inventory_generation=generation,
                inventory_digest="sha256:" + f"{generation}" * 64,
                qualification_valid_until="2026-08-21T00:00:00Z",
            ),
        ),
        created_by_actor_id="operator-1",
        created_at=f"2026-08-20T00:0{revision}:00Z",
    )


def test_binding_repository_is_append_only_and_monotonic() -> None:
    connection = _database()
    repository = SQLiteSessionCapabilityBindingRepository(connection)
    first = _binding(1, generation=1)
    second = _binding(2, generation=2)

    with SQLiteUnitOfWork(connection) as unit:
        repository.append(first, expected_previous_revision=None)
        unit.commit()
    with SQLiteUnitOfWork(connection) as unit:
        repository.append(second, expected_previous_revision=1)
        unit.commit()

    assert repository.latest("session-1") == second

    with pytest.raises(SQLitePersistenceError, match="drifted"):
        with SQLiteUnitOfWork(connection):
            repository.append(_binding(3, generation=3), expected_previous_revision=1)


def test_stable_bundle_catalog_fact_and_receipt_persist_without_health() -> None:
    connection = _database()
    identities = SQLiteCompositionIdentityRepository(connection)
    facts = SQLiteResourceCapabilityFactRepository(connection)
    receipts = SQLiteWorkspaceOperationReceiptRepository(connection)
    bundle = {"extensions": ["openzyme.science@1"]}
    catalog = {"tools": ["scientific.attempt.create"]}
    fact = ResourceCapabilityFact(
        capability_id="software.hmmer",
        kind=ResourceCapabilityKind.SOFTWARE,
        target_id="hpc-primary",
        inventory_generation=1,
        qualification_digest="sha256:" + "c" * 64,
        environment_digest="sha256:" + "d" * 64,
        inventory_digest="sha256:" + "e" * 64,
        operations=("hmmbuild", "hmmsearch"),
        version="3.4",
    )

    with SQLiteUnitOfWork(connection) as unit:
        identities.append_extension_bundle(
            bundle_digest=canonical_sha256_digest(bundle),
            bundle=bundle,
            activation_epoch_id="epoch-1",
            created_at="2026-08-20T00:00:00Z",
        )
        identities.append_catalog_identity(
            catalog_kind="declared_tool",
            catalog_digest=canonical_sha256_digest(catalog),
            activation_epoch_id="epoch-1",
            catalog=catalog,
            created_at="2026-08-20T00:00:00Z",
        )
        facts.append(fact, created_at="2026-08-20T00:00:00Z")
        receipt_digest = receipts.append(
            operation_id="operation-1",
            workspace_id="workspace-1",
            workspace_generation=1,
            operation_kind="workspace.process.exec",
            effect_certainty="settled",
            receipt={"exit_code": 0, "mutation_applied": True},
            settled_at="2026-08-20T00:01:00Z",
        )
        unit.commit()

    assert facts.list_generation(target_id="hpc-primary", inventory_generation=1) == (fact,)
    assert receipt_digest.startswith("sha256:")
    stored_bundle = connection.execute(
        "SELECT bundle_json FROM openzyme_store_extension_bundle_records"
    ).fetchone()[0]
    assert "health" not in stored_bundle


def test_catalog_kind_is_closed_and_transaction_is_required() -> None:
    connection = _database()
    repository = SQLiteCompositionIdentityRepository(connection)
    catalog = {"value": 1}

    with pytest.raises(SQLitePersistenceError, match="active Unit of Work"):
        repository.append_catalog_identity(
            catalog_kind="route",
            catalog_digest=canonical_sha256_digest(catalog),
            activation_epoch_id="epoch-1",
            catalog=catalog,
            created_at="2026-08-20T00:00:00Z",
        )

    with pytest.raises(SQLitePersistenceError, match="closed set"):
        with SQLiteUnitOfWork(connection):
            repository.append_catalog_identity(
                catalog_kind="target_health",
                catalog_digest=canonical_sha256_digest(catalog),
                activation_epoch_id="epoch-1",
                catalog=catalog,
                created_at="2026-08-20T00:00:00Z",
            )
