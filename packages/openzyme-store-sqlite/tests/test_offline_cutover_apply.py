from __future__ import annotations

import sqlite3

import pytest

from openzyme_contracts import DeploymentActivationEpoch
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import SessionCompositionPin
from openzyme_contracts import canonical_sha256_digest
from openzyme_store_sqlite import CutoverInventoryKind
from openzyme_store_sqlite import CutoverInventoryObservation
from openzyme_store_sqlite import FreshInstallCompositionSeed
from openzyme_store_sqlite import MigrationSourceIdentity
from openzyme_store_sqlite import OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE
from openzyme_store_sqlite import OfflineBackupKind
from openzyme_store_sqlite import OfflineBackupObservation
from openzyme_store_sqlite import OfflineCutoverApplicationPlan
from openzyme_store_sqlite import OfflineCutoverDisposition
from openzyme_store_sqlite import OfflineCutoverItem
from openzyme_store_sqlite import OfflineCutoverItemKind
from openzyme_store_sqlite import OfflineCutoverLedgerReceipt
from openzyme_store_sqlite import OfflineCutoverState
from openzyme_store_sqlite import OfflineSessionAdoption
from openzyme_store_sqlite import QuiescenceObservation
from openzyme_store_sqlite import QuiescenceRequirement
from openzyme_store_sqlite import QuiescenceSurfaceKind
from openzyme_store_sqlite import SQLiteDeploymentProofError
from openzyme_store_sqlite import STORE_MIGRATIONS
from openzyme_store_sqlite import SessionCutoverDisposition
from openzyme_store_sqlite import SessionCutoverDispositionKind
from openzyme_store_sqlite import apply_offline_cutover_transaction
from openzyme_store_sqlite import build_offline_cutover_dry_run
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration
from openzyme_store_sqlite import verify_composite_store_schema_read_only
from openzyme_store_sqlite import verify_offline_backup_set
from openzyme_store_sqlite import verify_offline_cutover_deployment_read_only
from openzyme_store_sqlite import verify_offline_quiescence


def _digest(label: str) -> str:
    return canonical_sha256_digest({"identity": label})


def _database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.create_function(
        "openzyme_mutation_write_allowed",
        2,
        lambda _session_id, _channel: 1,
    )
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
        epoch_id="offline-epoch-1",
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
        schema_verification_digest=_digest("schema-verification"),
        wheel_verification_digest=_digest("wheel-verification"),
        activated_by_actor_id="operator-1",
        activated_at="2026-08-20T04:00:00Z",
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


def _backup_set():
    return verify_offline_backup_set(
        tuple(
            OfflineBackupObservation(
                backup_id=f"backup-{kind.value}",
                backup_kind=kind,
                source_identity_digest=_digest(f"source-{kind.value}"),
                source_content_digest=_digest(f"content-{kind.value}"),
                source_size_bytes=10,
                backup_identity_digest=_digest(f"backup-{kind.value}"),
                backup_content_digest=_digest(f"content-{kind.value}"),
                backup_size_bytes=10,
                independent_readback_digest=_digest(f"content-{kind.value}"),
                verifier_id="independent-verifier",
                recoverable=True,
                verified_at="2026-08-20T04:00:00Z",
            )
            for kind in OfflineBackupKind
        )
    )


def _plan(
    seed: FreshInstallCompositionSeed,
    *,
    adoption: OfflineSessionAdoption,
) -> OfflineCutoverApplicationPlan:
    observations = tuple(
        CutoverInventoryObservation(
            inventory_kind=kind,
            identity_digest=_digest(f"inventory-{kind.value}"),
            item_count=(1 if kind is CutoverInventoryKind.SESSION else 0),
            expected_disposition_digest=_digest(f"disposition-{kind.value}"),
        )
        for kind in CutoverInventoryKind
    )
    dry_run = build_offline_cutover_dry_run(
        source_release_digest=_digest("source-release"),
        target_release_digest=seed.activation_epoch.release_identity.release_digest,
        observations=observations,
    )
    required = tuple(
        QuiescenceRequirement(owner_id=f"owner-{kind.value}", surface_kind=kind)
        for kind in QuiescenceSurfaceKind
    )
    quiescence = verify_offline_quiescence(
        required=required,
        observed=tuple(
            QuiescenceObservation(
                owner_id=item.owner_id,
                surface_kind=item.surface_kind,
                stopped_or_isolated=True,
                observation_digest=_digest(f"stopped-{item.owner_id}"),
            )
            for item in required
        ),
        deployment_inventory_digest=dry_run.proof_digest,
        unsettled_effect_identities=(),
        unknown_effect_count=0,
        verified_at="2026-08-20T04:01:00Z",
    )
    disposition = SessionCutoverDisposition(
        session_id=adoption.pin.session_id,
        disposition=SessionCutoverDispositionKind.MIGRATED_AT2,
        composition_pin_digest=adoption.pin.pin_digest,
        capability_binding_digest=adoption.initial_binding.binding_digest,
        evidence_digest=_digest("session-evidence"),
    )
    item = OfflineCutoverItem(
        item_kind=OfflineCutoverItemKind.SESSION,
        item_id=adoption.pin.session_id,
        expected_disposition=OfflineCutoverDisposition.MIGRATED,
        observed_disposition=OfflineCutoverDisposition.MIGRATED,
        item_payload={
            "pin_digest": adoption.pin.pin_digest,
            "binding_digest": adoption.initial_binding.binding_digest,
        },
    )
    backups = _backup_set()
    ledger = OfflineCutoverLedgerReceipt(
        ledger_id="ledger-1",
        state=OfflineCutoverState.COMPLETE,
        source_release_digest=dry_run.source_release_digest,
        target_release_digest=dry_run.target_release_digest,
        source_schema_manifest_digest=_digest("source-schema"),
        target_schema_manifest_digest=seed.schema_proof.complete_schema_manifest_digest,
        legacy_migration_receipt_digest=_digest("legacy-migration"),
        component_inventory_digest=_digest("components"),
        table_owner_manifest_digest=seed.table_owner_manifest_digest,
        import_owner_manifest_digest=_digest("imports"),
        authority_mapping_set_digest=canonical_sha256_digest([]),
        inventory_binding_set_digest=canonical_sha256_digest(
            [adoption.initial_binding.binding_digest]
        ),
        continuation_set_digest=_digest("continuations"),
        unsettled_effect_set_digest=quiescence.unsettled_effect_set_digest,
        quiescence_receipt_digest=quiescence.receipt_digest,
        backups=backups.receipts,
        session_dispositions=(disposition,),
        items=(item,),
        completed_at="2026-08-20T04:02:00Z",
    )
    return OfflineCutoverApplicationPlan(
        target_seed=seed,
        dry_run=dry_run,
        quiescence=quiescence,
        backup_set=backups,
        authority_mappings=(),
        session_adoptions=(adoption,),
        ledger=ledger,
    )


def _adoption(seed: FreshInstallCompositionSeed) -> OfflineSessionAdoption:
    binding = SessionCapabilityBindingRevision.create(
        binding_id="binding-session-1-r1",
        session_id="session-1",
        revision=1,
        extension_bundle_digest=(
            seed.activation_epoch.release_identity.extension_bundle_digest
        ),
        route_catalog_digest=seed.activation_epoch.release_identity.route_catalog_digest,
        inventory_bindings=(),
        created_by_actor_id="operator-1",
        created_at="2026-08-20T04:00:00Z",
    )
    pin = SessionCompositionPin.create(
        pin_id="pin-session-1",
        session_id="session-1",
        deployment_epoch=seed.activation_epoch,
        initial_capability_binding_id=binding.binding_id,
        initial_capability_binding_revision=1,
        initial_capability_binding_digest=binding.binding_digest,
        created_by_actor_id="operator-1",
        created_at="2026-08-20T04:00:00Z",
    )
    return OfflineSessionAdoption(pin=pin, initial_binding=binding)


def test_offline_cutover_commits_session_and_complete_ledger_atomically() -> None:
    connection = _database()
    seed = _seed(connection)
    adoption = _adoption(seed)
    connection.execute(
        "INSERT INTO sessions (session_id, project_id, title, objective, status, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "session-1",
            "project-1",
            "title",
            "objective",
            "completed",
            "2026-08-20T03:00:00Z",
            "2026-08-20T03:00:00Z",
        ),
    )
    connection.commit()
    plan = _plan(seed, adoption=adoption)

    proof = apply_offline_cutover_transaction(connection, plan=plan)
    restarted = verify_offline_cutover_deployment_read_only(connection, plan=plan)

    assert restarted.proof_digest == proof.proof_digest
    assert proof.ledger_digest == plan.ledger.ledger_digest
    assert proof.session_composition.verified_session_count == 1
    assert connection.execute(
        "SELECT proof_variant FROM openzyme_store_deployment_schema_state"
    ).fetchone()[0] == "offline_removal_complete"
    assert connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_fresh_install_receipts"
    ).fetchone()[0] == 0


def test_offline_cutover_failure_rolls_back_every_target_row() -> None:
    connection = _database()
    seed = _seed(connection)
    plan = _plan(seed, adoption=_adoption(seed))

    with pytest.raises(SQLiteDeploymentProofError) as error:
        apply_offline_cutover_transaction(connection, plan=plan)

    assert error.value.phase == "session_adoption_source"
    for table in (
        "openzyme_store_deployment_activation_epochs",
        "openzyme_store_extension_bundle_records",
        "openzyme_store_catalog_identity_records",
        "openzyme_store_session_composition_pins",
        "openzyme_store_session_capability_binding_revisions",
        "openzyme_store_offline_cutover_ledgers",
        "openzyme_store_deployment_schema_state",
    ):
        assert connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 0
    assert connection.in_transaction is False
