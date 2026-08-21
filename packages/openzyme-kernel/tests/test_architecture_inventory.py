from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]


def _load_deployment_inventory_module():
    path = ROOT / "scripts" / "inventory-openzyme-deployment-state.py"
    spec = importlib.util.spec_from_file_location(
        "openzyme_deployment_state_inventory", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_architecture_check_module():
    path = ROOT / "scripts" / "check-openzyme-architecture.py"
    spec = importlib.util.spec_from_file_location(
        "openzyme_architecture_check", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_minimal_inventory_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE deployment_schema_state (
                singleton INTEGER PRIMARY KEY,
                schema_generation TEXT NOT NULL,
                manifest_digest TEXT NOT NULL,
                removal_state TEXT NOT NULL,
                removal_receipt_digest TEXT NOT NULL
            );
            INSERT INTO deployment_schema_state VALUES (
                1, 'test-generation', 'sha256:manifest',
                'fresh_install_complete', 'sha256:receipt'
            );
            CREATE TABLE sessions (session_id TEXT PRIMARY KEY, status TEXT NOT NULL);
            CREATE TABLE file_workspace_session_contract_records (
                session_id TEXT PRIMARY KEY
            );
            CREATE TABLE continuation_state_records (
                continuation_id TEXT PRIMARY KEY, status TEXT NOT NULL
            );
            CREATE TABLE controlled_operation_records (
                operation_id TEXT PRIMARY KEY, status TEXT NOT NULL
            );
            CREATE TABLE agent_capability_lease_records (
                lease_id TEXT PRIMARY KEY, status TEXT NOT NULL
            );
            CREATE TABLE session_repository_binding_pins (
                session_id TEXT PRIMARY KEY
            );
            CREATE TABLE executor_hpc_target_qualifications (
                target_profile_id TEXT PRIMARY KEY
            );
            """
        )


def test_source_bound_catalog_and_owner_inventory_is_current() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/check-openzyme-architecture.py"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["catalog_counts"]["tool"] > 0
    assert result["catalog_counts"]["http_route"] > 0
    assert result["catalog_counts"]["qualification_scenario"] > 0
    assert result["catalog_digest"].startswith("sha256:")
    catalog_inventory = json.loads(
        (ROOT / "docs/v3/architecture/catalog-owner-inventory.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["catalog_duplicate_authorities"] == catalog_inventory[
        "expected_temporary_duplicate_authorities"
    ]


def test_product_plugin_reverse_import_gate_applies_to_future_components() -> None:
    module = _load_architecture_check_module()
    policy = json.loads(
        (ROOT / "docs/v3/architecture/component-boundary-policy.json").read_text(
            encoding="utf-8"
        )
    )
    forbidden = set(policy["forbidden_import_roots_by_kind"]["product_plugin"])
    assert {
        "openzyme_core",
        "openzyme_store_sqlite",
        "openzyme_host_api",
        "openzyme_workspace_git_lfs",
        "openzyme_hpc_slurm",
        "openzyme_runtime",
    } <= forbidden

    for import_root in sorted(forbidden):
        with pytest.raises(
            module.ArchitectureCheckError,
            match="forbidden implementation import",
        ):
            module.validate_component_source_policy(
                "enzymedesign.future",
                "product_plugin",
                f"import {import_root}\n",
                policy,
                source_label="future_product_plugin.py",
            )


def test_catalog_observer_reads_manifest_owned_tools_not_only_ast_literals() -> None:
    module = _load_architecture_check_module()
    observed = module.observe_catalog_inventory()
    sequence_tools = {
        item["canonical_id"]
        for item in observed["items"]
        if item["kind"] == "tool"
        and item["current_owner"] == "enzymedesign.sequence.toolpack"
    }

    assert sequence_tools == {
        "enzymedesign.interpro.query",
        "enzymedesign.rcsb.query",
        "enzymedesign.sequence.parse",
        "enzymedesign.uniprot.fetch",
    }


def test_durable_repository_storage_has_only_git_lfs_adapter_authority() -> None:
    legacy_package = ROOT / "packages" / "openzyme-core" / "src" / "openzyme_core"
    adapter_package = (
        ROOT
        / "packages"
        / "openzyme-workspace-git-lfs"
        / "src"
        / "openzyme_workspace_git_lfs"
    )

    assert not (legacy_package / "repository_storage.py").exists()
    assert not (legacy_package / "repository_pre_receive_hook.sh").exists()
    assert not (legacy_package / "repository_owner_refs.py").exists()
    assert not (legacy_package / "git_lfs_repositories.py").exists()
    assert not (legacy_package / "git_lfs_work_products.py").exists()
    assert not (legacy_package / "git_lfs_client_qualification.py").exists()
    assert not (legacy_package / "repository_retention.py").exists()
    assert (adapter_package / "repository_storage.py").is_file()
    assert (adapter_package / "repository_pre_receive_hook.sh").is_file()
    assert (adapter_package / "ref_policy.py").is_file()
    assert (adapter_package / "credential_material.py").is_file()
    assert (adapter_package / "credential_claims.py").is_file()
    assert (adapter_package / "credential_issuance.py").is_file()
    assert (adapter_package / "provision_credential_claims.py").is_file()
    assert (adapter_package / "provision_credential_issuance.py").is_file()
    assert (adapter_package / "sqlite_lfs_repository.py").is_file()
    assert (adapter_package / "work_products.py").is_file()
    assert (adapter_package / "client_qualification.py").is_file()
    assert (adapter_package / "retention.py").is_file()
    assert (adapter_package / "http_transport.py").is_file()
    assert (adapter_package / "binding_mechanism.py").is_file()
    assert (adapter_package / "workspace_lifecycle_mechanism.py").is_file()
    assert (adapter_package / "workspace_status.py").is_file()
    assert (adapter_package / "revision_backend.py").is_file()

    transport_source = (adapter_package / "http_transport.py").read_text(
        encoding="utf-8"
    )
    for forbidden_import in (
        "from openzyme_core",
        "from openzyme_host_api",
        "from openzyme_runtime",
    ):
        assert forbidden_import not in transport_source
    assert "def create_repository_transport_app(" in transport_source

    lifecycle_mechanism_source = (
        adapter_package / "workspace_lifecycle_mechanism.py"
    ).read_text(encoding="utf-8")
    for forbidden_import in (
        "from openzyme_core",
        "from openzyme_host_api",
        "from openzyme_process_podman",
        "from openzyme_runtime",
    ):
        assert forbidden_import not in lifecycle_mechanism_source
    assert "class AgentGitWorkspaceProvisioningMechanism" in (
        lifecycle_mechanism_source
    )
    assert "class AgentGitWorkspaceRecoveryMechanism" in lifecycle_mechanism_source

    revision_backend_source = (adapter_package / "revision_backend.py").read_text(
        encoding="utf-8"
    )
    for forbidden_import in (
        "from openzyme_core",
        "from openzyme_host_api",
        "from openzyme_runtime",
    ):
        assert forbidden_import not in revision_backend_source
    assert "class LocalGitRevisionBackend" in revision_backend_source
    assert '"update-ref"' in revision_backend_source
    assert "def reconcile_publication(" in revision_backend_source
    assert "def observe_publication_namespace(" in revision_backend_source

    assert not (legacy_package / "workspace_checkpoints.py").exists()
    assert not (legacy_package / "workspace_publications.py").exists()
    assert not (legacy_package / "workspace_publication_reads.py").exists()
    kernel_publication_source = (
        ROOT
        / "packages"
        / "openzyme-kernel"
        / "src"
        / "openzyme_kernel"
        / "publication_application.py"
    ).read_text(encoding="utf-8")
    for forbidden_mechanism in (
        "WorkspacePublicationGitReader",
        "WorkspacePublicationRemoteRoute",
        "create_publication_ref_if_absent",
        "read_whole_tree_manifest",
        "read_exact_ref",
        "list_refs",
    ):
        assert forbidden_mechanism not in kernel_publication_source

    host_transport_path = (
        ROOT
        / "apps"
        / "openzyme-host-api"
        / "src"
        / "openzyme_host_api"
        / "repository_transport.py"
    )
    assert not host_transport_path.exists()
    adapter_transport = (
        adapter_package / "http_transport.py"
    ).read_text(encoding="utf-8")
    assert "class RepositoryTransportDependencies" in adapter_transport
    assert "def create_repository_transport_app" in adapter_transport

    # The former Core package is no longer a compatibility surface.  Proving the
    # files are physically absent is stronger than scanning retired sources for
    # individual exports that could otherwise become a second authority again.
    for retired_path in (
        "__init__.py",
        "repository_credentials.py",
        "repository_provision_credentials.py",
    ):
        assert not (legacy_package / retired_path).exists()


def test_deployment_inventory_is_read_only_and_classifies_unsettled_state(
    tmp_path: Path,
) -> None:
    module = _load_deployment_inventory_module()
    database = tmp_path / "control-plane.sqlite3"
    _create_minimal_inventory_database(database)
    before = database.read_bytes()

    empty = module.observe(database, locator_id="test-control-plane")

    assert database.read_bytes() == before
    assert empty["classification"] == "fresh_empty_candidate"
    assert empty["observation"]["mutation_applied"] is False
    assert empty["classification_inputs"]["sessions_total"] == 0

    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO sessions VALUES ('session-1', 'active')")
        connection.execute(
            "INSERT INTO controlled_operation_records VALUES "
            "('operation-1', 'running')"
        )
    before_unsettled = database.read_bytes()

    unsettled = module.observe(database, locator_id="test-control-plane")

    assert database.read_bytes() == before_unsettled
    assert unsettled["classification"] == (
        "requires_offline_session_and_effect_classification"
    )
    assert unsettled["classification_inputs"]["sessions_non_terminal"] == 1
    assert unsettled["classification_inputs"][
        "controlled_operations_unsettled"
    ] == 1
