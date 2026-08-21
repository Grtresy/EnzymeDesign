from __future__ import annotations

from dataclasses import replace
import json
import sqlite3

import pytest

from openzyme_contracts import DeploymentActivationEpoch
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import ResourceCapabilityFact
from openzyme_contracts import ResourceCapabilityKind
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import SessionCompositionPin
from openzyme_contracts import TargetInventoryBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_store_sqlite import FreshInstallCompositionSeed
from openzyme_store_sqlite import MigrationSourceIdentity
from openzyme_store_sqlite import OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE
from openzyme_store_sqlite import SQLiteDeploymentProofError
from openzyme_store_sqlite import SQLiteResourceCapabilityFactRepository
from openzyme_store_sqlite import SQLiteSessionCapabilityBindingRepository
from openzyme_store_sqlite import SQLiteUnitOfWork
from openzyme_store_sqlite import STORE_MIGRATIONS
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration
from openzyme_store_sqlite import seed_fresh_install_composition_offline
from openzyme_store_sqlite import verify_composite_store_schema_read_only
from openzyme_store_sqlite import verify_fresh_install_deployment_read_only
from openzyme_store_sqlite import verify_session_composition_state_read_only


def _digest(label: str) -> str:
    return canonical_sha256_digest({"identity": label})


def _database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(
        connection,
        profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
    )
    install_store_schema_for_offline_migration(connection)
    return connection


def _seed(connection: sqlite3.Connection) -> FreshInstallCompositionSeed:
    schema = verify_composite_store_schema_read_only(
        connection,
        owner_schema_profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
    )
    payloads = tuple(
        (kind, {"catalog_kind": kind, "distribution_id": "openzyme-standard"})
        for kind in (
            "adapter_bundle",
            "extension_bundle",
            "declared_tool",
            "route",
            "projection",
            "migration",
            "workspace_backend",
        )
    )
    digests = {kind: canonical_sha256_digest(payload) for kind, payload in payloads}
    release = LayeredReleaseIdentity(
        kernel_contract_digest=_digest("kernel"),
        core_schema_digest=schema.complete_schema_manifest_digest,
        adapter_bundle_digest=digests["adapter_bundle"],
        extension_bundle_digest=digests["extension_bundle"],
        declared_tool_catalog_digest=digests["declared_tool"],
        route_catalog_digest=digests["route"],
        projection_catalog_digest=digests["projection"],
        migration_catalog_digest=digests["migration"],
        workspace_backend_digest=digests["workspace_backend"],
        host_build_digest=_digest("host"),
        client_build_digest=_digest("client"),
    )
    epoch = DeploymentActivationEpoch.create(
        epoch_id="activation-standard-1",
        sequence=1,
        distribution_id="openzyme-standard",
        kernel_manifest_digest=_digest("kernel-manifest"),
        distribution_manifest_digest=_digest("distribution-manifest"),
        composition_document_digest=_digest("composition-document"),
        composition_activation_digest=_digest("composition-activation"),
        driver_bundle_digest=_digest("driver-bundle"),
        http_route_catalog_digest=_digest("http-routes"),
        contribution_catalogs_digest=_digest("contribution-catalogs"),
        release_identity=release,
        schema_verification_digest=schema.proof_digest,
        wheel_verification_digest=_digest("wheel-proof"),
        activated_by_actor_id="operator-1",
        activated_at="2026-08-20T00:00:00+00:00",
    )
    return FreshInstallCompositionSeed(
        schema_proof=schema,
        owner_schema_profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
        activation_epoch=epoch,
        catalog_payloads=payloads,
        migration_sources=tuple(
            MigrationSourceIdentity(
                owner_component_id=item.owner_component_id,
                migration_id=item.migration_id,
                migration_digest=item.sql_digest,
            )
            for item in STORE_MIGRATIONS
        ),
        installed_wheel_set_digest=_digest("installed-wheels"),
        table_owner_manifest_digest=schema.owner_schema.table_owner_manifest_digest,
    )


def test_fresh_standard_seed_is_deterministic_and_restart_verification_is_read_only() -> None:
    connection = _database()
    seed = _seed(connection)

    created = seed_fresh_install_composition_offline(connection, seed)
    before = connection.total_changes
    restarted = verify_fresh_install_deployment_read_only(connection, seed=seed)

    assert restarted.proof_digest == created.proof_digest
    assert restarted.receipt.receipt_digest == created.receipt.receipt_digest
    assert restarted.schema.composition is not None
    assert restarted.schema.composition.verified_catalog_count == 7
    assert restarted.mutation_applied is False
    assert restarted.plugin_import_performed is False
    assert restarted.writer_enabled is False
    assert connection.total_changes == before
    assert connection.in_transaction is False


def test_fresh_seed_refuses_an_existing_occurrence_without_partial_rows() -> None:
    connection = _database()
    seed = _seed(connection)
    seed_fresh_install_composition_offline(connection, seed)
    before = connection.total_changes

    with pytest.raises(SQLiteDeploymentProofError) as error:
        seed_fresh_install_composition_offline(connection, seed)

    assert error.value.phase == "fresh_empty_closure"
    assert error.value.mutation_applied is False
    assert connection.total_changes == before


def test_tampered_state_digest_fails_closed_without_repair() -> None:
    connection = _database()
    seed = _seed(connection)
    seed_fresh_install_composition_offline(connection, seed)
    connection.execute(
        "UPDATE openzyme_store_deployment_schema_state SET state_digest = ?",
        (_digest("tampered"),),
    )
    connection.commit()
    before = connection.total_changes

    with pytest.raises(SQLiteDeploymentProofError) as error:
        verify_fresh_install_deployment_read_only(connection, seed=seed)

    assert error.value.phase == "deployment_state"
    assert error.value.mutation_applied is False
    assert connection.total_changes == before


def test_activation_epoch_must_bind_the_exact_schema_manifest() -> None:
    connection = _database()
    seed = _seed(connection)
    mismatched = replace(
        seed.activation_epoch.release_identity,
        core_schema_digest=_digest("another-schema"),
    )

    with pytest.raises(ValueError, match="does not bind the exact schema manifest"):
        replace(
            seed,
            activation_epoch=DeploymentActivationEpoch.create(
                epoch_id="activation-standard-2",
                sequence=2,
                distribution_id="openzyme-standard",
                kernel_manifest_digest=_digest("kernel-manifest"),
                distribution_manifest_digest=_digest("distribution-manifest"),
                composition_document_digest=_digest("composition-document"),
                composition_activation_digest=_digest("composition-activation"),
                driver_bundle_digest=_digest("driver-bundle"),
                http_route_catalog_digest=_digest("http-routes"),
                contribution_catalogs_digest=_digest("contribution-catalogs"),
                release_identity=mismatched,
                schema_verification_digest=_digest("schema-verification"),
                wheel_verification_digest=_digest("wheel-proof"),
                activated_by_actor_id="operator-1",
                activated_at="2026-08-20T00:00:00+00:00",
            ),
        )


def test_startup_verifies_session_pin_binding_and_inventory_closure_read_only() -> None:
    connection = _database()
    seed = _seed(connection)
    seed_fresh_install_composition_offline(connection, seed)
    inventory_digest = _digest("hpc-inventory")
    fact = ResourceCapabilityFact(
        capability_id="software.hmmer",
        kind=ResourceCapabilityKind.SOFTWARE,
        target_id="hpc-primary",
        inventory_generation=1,
        qualification_digest=_digest("qualification"),
        environment_digest=_digest("environment"),
        inventory_digest=inventory_digest,
        operations=("hmmsearch",),
        version="3.4",
    )
    binding = SessionCapabilityBindingRevision.create(
        binding_id="binding-session-1-r1",
        session_id="session-1",
        revision=1,
        extension_bundle_digest=(
            seed.activation_epoch.release_identity.extension_bundle_digest
        ),
        route_catalog_digest=seed.activation_epoch.release_identity.route_catalog_digest,
        inventory_bindings=(
            TargetInventoryBinding(
                target_id="hpc-primary",
                inventory_generation=1,
                inventory_digest=inventory_digest,
                qualification_valid_until="2026-08-21T00:00:00Z",
            ),
        ),
        created_by_actor_id="operator-1",
        created_at="2026-08-20T00:01:00Z",
    )
    pin = SessionCompositionPin.create(
        pin_id="pin-session-1",
        session_id="session-1",
        deployment_epoch=seed.activation_epoch,
        initial_capability_binding_id=binding.binding_id,
        initial_capability_binding_revision=1,
        initial_capability_binding_digest=binding.binding_digest,
        created_by_actor_id="operator-1",
        created_at="2026-08-20T00:01:00Z",
    )
    with SQLiteUnitOfWork(connection) as unit:
        SQLiteResourceCapabilityFactRepository(connection).append(
            fact,
            created_at="2026-08-20T00:00:30Z",
        )
        SQLiteSessionCapabilityBindingRepository(connection).append(
            binding,
            expected_previous_revision=None,
        )
        connection.execute(
            """
            INSERT INTO openzyme_store_session_composition_pins (
                pin_id, session_id, deployment_epoch_id,
                deployment_activation_digest, distribution_id,
                composition_bundle_digest, release_digest, pin_digest,
                pin_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pin.pin_id,
                pin.session_id,
                pin.deployment_epoch_id,
                pin.deployment_activation_digest,
                pin.distribution_id,
                pin.composition_bundle_digest,
                pin.release_identity.release_digest,
                pin.pin_digest,
                json.dumps(
                    pin.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                pin.created_at,
            ),
        )
        unit.commit()

    before = connection.total_changes
    proof = verify_session_composition_state_read_only(
        connection,
        activation_epoch=seed.activation_epoch,
    )

    assert proof.verified_session_count == 1
    assert proof.verified_binding_revision_count == 1
    assert proof.verified_inventory_binding_count == 1
    assert proof.mutation_applied is False
    assert connection.total_changes == before


def test_startup_rejects_orphan_binding_without_repair() -> None:
    connection = _database()
    seed = _seed(connection)
    seed_fresh_install_composition_offline(connection, seed)
    binding = SessionCapabilityBindingRevision.create(
        binding_id="binding-orphan-r1",
        session_id="session-orphan",
        revision=1,
        extension_bundle_digest=(
            seed.activation_epoch.release_identity.extension_bundle_digest
        ),
        route_catalog_digest=seed.activation_epoch.release_identity.route_catalog_digest,
        inventory_bindings=(),
        created_by_actor_id="operator-1",
        created_at="2026-08-20T00:01:00Z",
    )
    with SQLiteUnitOfWork(connection) as unit:
        SQLiteSessionCapabilityBindingRepository(connection).append(
            binding,
            expected_previous_revision=None,
        )
        unit.commit()
    before = connection.total_changes

    with pytest.raises(SQLiteDeploymentProofError) as error:
        verify_session_composition_state_read_only(
            connection,
            activation_epoch=seed.activation_epoch,
        )

    assert error.value.phase == "session_binding_orphan"
    assert connection.total_changes == before
