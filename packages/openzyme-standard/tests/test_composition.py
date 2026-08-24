from pathlib import Path
from datetime import UTC
from datetime import datetime
import sqlite3

import pytest

from openzyme_extension_spi import CompositionManifestState
from openzyme_extension_spi import parse_distribution_composition_toml
from openzyme_standard import STANDARD_ADAPTER_SLOTS
from openzyme_standard import STANDARD_KERNEL_ENTITY_TYPES
from openzyme_standard import activate_standard_composition
from openzyme_standard import build_standard_fresh_install_seed
from openzyme_standard import build_standard_kernel_control_store
from openzyme_standard import build_standard_kernel_publication_runtime
from openzyme_standard import inspect_standard_kernel_store_codec_coverage
from openzyme_standard import load_standard_composition
from openzyme_standard import mount_standard_kernel_workspace_tool_set
from openzyme_standard import select_standard_component_locators
from openzyme_standard import verify_standard_deployment_startup_read_only
from openzyme_kernel import DeploymentSurface
from openzyme_kernel import KernelContractError
from openzyme_kernel import mount_runtime_tool_set
from openzyme_kernel.collaboration_tools import CollaborationToolApplications
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_store_sqlite import OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration
from openzyme_store_sqlite import seed_fresh_install_composition_offline
from openzyme_store_sqlite import verify_composite_store_schema_read_only


ROOT = Path(__file__).resolve().parents[3]


def test_packaged_standard_composition_matches_repository_distribution() -> None:
    packaged = load_standard_composition()
    repository = (
        ROOT / "distributions/openzyme-standard/openzyme-composition.toml"
    ).read_bytes()

    assert packaged == parse_distribution_composition_toml(repository)
    assert packaged.manifest.required_plugin_ids == ()
    assert packaged.manifest.optional_plugin_ids == ()
    assert tuple(sorted(item.slot_id for item in packaged.manifest.adapters)) == (
        STANDARD_ADAPTER_SLOTS
    )


def test_standard_selects_only_four_exact_required_adapters() -> None:
    selected = select_standard_component_locators()

    assert [locator.component_id for locator in selected.selected] == [
        "openzyme.process.podman",
        "openzyme.runtime.llm",
        "openzyme.store.sqlite",
        "openzyme.workspace.git.lfs",
    ]
    assert selected.ignored_component_ids == ()
    assert all(
        not locator.component_id.startswith("enzymedesign.")
        for locator in selected.selected
    )


def test_standard_builds_an_exact_plugin_free_active_composition() -> None:
    document = load_standard_composition()
    activated = activate_standard_composition()

    assert document.manifest_state is CompositionManifestState.ACTIVE
    assert activated.distribution_id == "openzyme.standard"
    assert len(activated.adapters) == 4
    assert activated.plugins.activations == ()
    assert activated.drivers == ()
    assert tuple(
        entry.contract.tool_name for entry in activated.declared_tool_catalog.entries
    ) == (
        "approval.request",
        "capabilities.inspect",
        "protocol.send",
        "task.create",
        "task.delegate",
        "task.finish",
        "task.update",
        "workspace.exec",
        "workspace.fs.list",
        "workspace.fs.mutate",
        "workspace.fs.read",
        "workspace.status",
        "world.inspect",
    )
    assert all(
        entry.owner_component_id == "openzyme.kernel"
        for entry in activated.declared_tool_catalog.entries
    )


def test_standard_builds_and_verifies_a_deterministic_plugin_free_fresh_seed() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(
        connection,
        profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
    )
    install_store_schema_for_offline_migration(connection)
    schema = verify_composite_store_schema_read_only(
        connection,
        owner_schema_profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
    )
    digest = "sha256:" + "1" * 64
    seed = build_standard_fresh_install_seed(
        schema_proof=schema,
        installed_wheel_set_digest=digest,
        host_build_digest="sha256:" + "2" * 64,
        client_build_digest="sha256:" + "3" * 64,
        epoch_id="standard-fresh-1",
        sequence=1,
        activated_by_actor_id="operator-1",
        activated_at="2026-08-20T00:00:00+00:00",
    )

    proof = seed_fresh_install_composition_offline(connection, seed)

    assert proof.receipt.distribution_id == "openzyme.standard"
    assert proof.receipt.owner_schema_profile_id == (
        OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE.profile_id
    )
    assert proof.schema.composition is not None
    assert proof.schema.composition.verified_catalog_count == 7
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM openzyme_store_extension_state_records"
        ).fetchone()[0]
        == 0
    )

    before = connection.total_changes
    startup = verify_standard_deployment_startup_read_only(
        connection,
        seed=seed,
        observed_installed_wheel_set_digest=digest,
        verified_at="2026-08-20T00:01:00+00:00",
    )
    assert startup.gate.active_epoch == seed.activation_epoch
    assert startup.session_composition_proof.verified_session_count == 0
    assert startup.gate.require_active(DeploymentSurface.REPOSITORY_WRITER)
    assert startup.mounted_surfaces.tools == ()
    assert startup.mounted_surfaces.capability_routes == ()
    assert startup.mounted_surfaces.http_routes == ()
    assert startup.mounted_surfaces.projections == ()
    assert startup.mounted_surfaces.workers == ()
    assert startup.mounted_surfaces.finish_validators == ()
    assert startup.mounted_surfaces.transaction_participants == ()
    assert startup.proof_digest.startswith("sha256:")
    assert connection.total_changes == before


def test_standard_mounts_all_kernel_base_runtimes_without_a_plugin_bundle() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(
        connection,
        profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
    )
    install_store_schema_for_offline_migration(connection)
    schema = verify_composite_store_schema_read_only(
        connection,
        owner_schema_profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
    )
    wheel_digest = "sha256:" + "1" * 64
    seed = build_standard_fresh_install_seed(
        schema_proof=schema,
        installed_wheel_set_digest=wheel_digest,
        host_build_digest="sha256:" + "2" * 64,
        client_build_digest="sha256:" + "3" * 64,
        epoch_id="standard-runtime-mount",
        sequence=1,
        activated_by_actor_id="operator-1",
        activated_at="2026-08-20T00:00:00+00:00",
    )
    seed_fresh_install_composition_offline(connection, seed)
    startup = verify_standard_deployment_startup_read_only(
        connection,
        seed=seed,
        observed_installed_wheel_set_digest=wheel_digest,
        verified_at="2026-08-20T00:01:00+00:00",
    )

    mounted = mount_standard_kernel_workspace_tool_set(
        startup=startup,
        coordinator=object(),
        context_resolver=object(),
        collaboration_applications=CollaborationToolApplications(
            world=object(),
            collaboration=object(),
            tasks=object(),
            protocol=object(),
            approvals=object(),
        ),
        collaboration_context_resolver=object(),
    )

    assert tuple(name for name, _ in mounted.tools) == (
        "approval.request",
        "capabilities.inspect",
        "protocol.send",
        "task.create",
        "task.delegate",
        "task.finish",
        "task.update",
        "workspace.exec",
        "workspace.fs.list",
        "workspace.fs.mutate",
        "workspace.fs.read",
        "workspace.status",
        "world.inspect",
    )
    assert all(
        runtime.owner_component_id == "openzyme.kernel" for _, runtime in mounted.tools
    )
    assert startup.mounted_surfaces.tools == ()
    assert mounted.declared_tool_catalog_digest == (
        seed.activation_epoch.release_identity.declared_tool_catalog_digest
    )

    with pytest.raises(KernelContractError) as raised:
        mount_runtime_tool_set(
            gate=startup.gate,
            catalog=activate_standard_composition().declared_tool_catalog,
            kernel_runtimes=tuple(
                runtime for name, runtime in mounted.tools if name != "workspace.status"
            ),
            extension_surfaces=startup.mounted_surfaces,
        )
    assert raised.value.code == "tool_runtime_catalog_mismatch"
    assert raised.value.details["missing_tool_names"] == ("workspace.status",)


def test_standard_writer_opens_only_after_every_kernel_entity_has_a_real_codec() -> (
    None
):
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(
        connection,
        profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
    )
    install_store_schema_for_offline_migration(connection)
    schema = verify_composite_store_schema_read_only(
        connection,
        owner_schema_profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
    )
    wheel_digest = "sha256:" + "1" * 64
    seed = build_standard_fresh_install_seed(
        schema_proof=schema,
        installed_wheel_set_digest=wheel_digest,
        host_build_digest="sha256:" + "2" * 64,
        client_build_digest="sha256:" + "3" * 64,
        epoch_id="standard-codec-closure",
        sequence=1,
        activated_by_actor_id="operator-1",
        activated_at="2026-08-20T00:00:00+00:00",
    )
    seed_fresh_install_composition_offline(connection, seed)
    startup = verify_standard_deployment_startup_read_only(
        connection,
        seed=seed,
        observed_installed_wheel_set_digest=wheel_digest,
        verified_at="2026-08-20T00:01:00+00:00",
    )
    coverage = inspect_standard_kernel_store_codec_coverage()

    assert coverage.required_entity_types == STANDARD_KERNEL_ENTITY_TYPES
    assert coverage.available_entity_types == STANDARD_KERNEL_ENTITY_TYPES
    assert coverage.ready is True
    assert coverage.missing_entity_types == ()
    assert coverage.coverage_digest.startswith("sha256:")
    assert "task" not in coverage.missing_entity_types
    assert "agent_authority_lease" not in coverage.missing_entity_types
    assert "project_repository_binding" not in coverage.missing_entity_types
    assert "workspace_generation" not in coverage.missing_entity_types
    before = connection.total_changes
    store = build_standard_kernel_control_store(connection, startup=startup)

    assert tuple(sorted(store.codecs)) == STANDARD_KERNEL_ENTITY_TYPES
    assert connection.total_changes == before

    runtime = build_standard_kernel_publication_runtime(
        connection,
        startup=startup,
        clock=DeterministicClock(datetime(2026, 8, 20, 0, 2, tzinfo=UTC)),
        ids=DeterministicIdGenerator(),
        revision_backend=object(),
        manifest_policy=object(),
    )
    assert runtime.store.provider_id == "openzyme.store.sqlite"
    assert tuple(sorted(runtime.store.codecs)) == STANDARD_KERNEL_ENTITY_TYPES
    assert runtime.coordinator is not None
    assert connection.total_changes == before


def test_standard_startup_keeps_gate_closed_on_installed_wheel_drift() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(
        connection,
        profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
    )
    install_store_schema_for_offline_migration(connection)
    schema = verify_composite_store_schema_read_only(
        connection,
        owner_schema_profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
    )
    seed = build_standard_fresh_install_seed(
        schema_proof=schema,
        installed_wheel_set_digest="sha256:" + "1" * 64,
        host_build_digest="sha256:" + "2" * 64,
        client_build_digest="sha256:" + "3" * 64,
        epoch_id="standard-fresh-drift",
        sequence=1,
        activated_by_actor_id="operator-1",
        activated_at="2026-08-20T00:00:00+00:00",
    )
    seed_fresh_install_composition_offline(connection, seed)
    before = connection.total_changes

    with pytest.raises(KernelContractError) as error:
        verify_standard_deployment_startup_read_only(
            connection,
            seed=seed,
            observed_installed_wheel_set_digest="sha256:" + "9" * 64,
            verified_at="2026-08-20T00:01:00+00:00",
        )

    assert error.value.code == "deployment_verification_failed"
    assert connection.total_changes == before
