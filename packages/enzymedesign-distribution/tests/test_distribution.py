from pathlib import Path
import sqlite3

from enzymedesign_distribution import activate_enzymedesign_composition
from enzymedesign_distribution import build_enzymedesign_scientific_contributions
from enzymedesign_distribution import build_enzymedesign_fresh_install_seed
from enzymedesign_distribution import load_enzymedesign_composition
from enzymedesign_distribution import select_enzymedesign_component_locators
from enzymedesign_distribution import verify_enzymedesign_deployment_startup_read_only
from openzyme_extension_spi import CompositionManifestState
from openzyme_extension_spi import parse_distribution_composition_toml
from openzyme_store_sqlite import ENZYMEDESIGN_OWNER_SCHEMA_PROFILE
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration
from openzyme_store_sqlite import seed_fresh_install_composition_offline
from openzyme_store_sqlite import verify_composite_store_schema_read_only
from openzyme_kernel import DeploymentSurface


ROOT = Path(__file__).resolve().parents[3]


def test_packaged_distribution_exactly_matches_repository_manifest() -> None:
    packaged = load_enzymedesign_composition()
    repository = parse_distribution_composition_toml(
        (ROOT / "distributions/enzymedesign/openzyme-composition.toml").read_bytes()
    )

    assert packaged == repository
    assert "openzyme.standard" not in {
        item.plugin_id for item in packaged.manifest.plugins
    }
    assert "enzymedesign.bio-providers" in packaged.manifest.required_plugin_ids


def test_distribution_selects_exact_plugins_adapters_and_drivers() -> None:
    selected = select_enzymedesign_component_locators()

    assert len(selected.selected) == 30
    assert selected.ignored_component_ids == ()
    assert "enzymedesign.bio-provider-http" in {
        item.component_id for item in selected.selected
    }
    assert "enzymedesign.aox.executor" in {
        item.component_id for item in selected.selected
    }


def test_distribution_builds_exact_active_catalogs_without_live_probes() -> None:
    document = load_enzymedesign_composition()
    activated = activate_enzymedesign_composition()

    assert document.manifest_state is CompositionManifestState.ACTIVE
    assert activated.distribution_id == "enzymedesign"
    assert len(activated.adapters) == 8
    assert len(activated.plugins.activations) == 14
    assert len(activated.drivers) == 8
    assert len(activated.declared_tool_catalog.entries) == 37
    assert {
        entry.contract.tool_name
        for entry in activated.declared_tool_catalog.entries
        if entry.owner_component_id == "openzyme.kernel"
    } == {
        "workspace.status",
        "workspace.fs.read",
        "workspace.fs.list",
        "workspace.fs.mutate",
        "workspace.exec",
    }


def test_enzymedesign_fresh_seed_binds_selected_plugin_schema_and_catalogs() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(
        connection,
        profile=ENZYMEDESIGN_OWNER_SCHEMA_PROFILE,
    )
    install_store_schema_for_offline_migration(connection)
    schema = verify_composite_store_schema_read_only(
        connection,
        owner_schema_profile=ENZYMEDESIGN_OWNER_SCHEMA_PROFILE,
    )
    seed = build_enzymedesign_fresh_install_seed(
        schema_proof=schema,
        installed_wheel_set_digest="sha256:" + "4" * 64,
        host_build_digest="sha256:" + "5" * 64,
        client_build_digest="sha256:" + "6" * 64,
        epoch_id="enzymedesign-fresh-1",
        sequence=1,
        activated_by_actor_id="operator-1",
        activated_at="2026-08-20T00:00:00+00:00",
    )

    proof = seed_fresh_install_composition_offline(connection, seed)

    assert proof.receipt.distribution_id == "enzymedesign"
    assert proof.receipt.owner_schema_profile_id == (
        ENZYMEDESIGN_OWNER_SCHEMA_PROFILE.profile_id
    )
    assert proof.schema.composition is not None
    assert proof.schema.composition.verified_catalog_count == 7
    assert connection.execute(
        "SELECT COUNT(*) FROM scientific_attempt_records"
    ).fetchone()[0] == 0

    before = connection.total_changes
    startup = verify_enzymedesign_deployment_startup_read_only(
        connection,
        seed=seed,
        observed_installed_wheel_set_digest="sha256:" + "4" * 64,
        verified_at="2026-08-20T00:01:00+00:00",
    )
    assert startup.gate.active_epoch == seed.activation_epoch
    assert startup.session_composition_proof.verified_session_count == 0
    assert startup.gate.require_active(DeploymentSurface.RUNTIME)
    assert connection.total_changes == before


def test_distribution_owns_aox_workflow_and_finalization_registration() -> None:
    contributions = build_enzymedesign_scientific_contributions()
    contract = contributions.workflow_contract_registry.contracts[0]

    assert (
        contributions.workflow_contract_registry.resolve(
            workflow_id=contract.workflow_id,
            workflow_contract_digest=contract.digest,
        )
        is contract
    )
    assert type(contributions.finalization_handler).__name__ == (
        "AoxScientificDeliverableRequestHandler"
    )
