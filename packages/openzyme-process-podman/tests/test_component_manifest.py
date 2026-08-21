from __future__ import annotations

import importlib.metadata
from importlib import resources
import json
import subprocess
import sys

from openzyme_contracts import WORKSPACE_FILESYSTEM_PORT_CONTRACT
from openzyme_contracts import WORKSPACE_FILESYSTEM_PORT_CONTRACT_DIGEST
from openzyme_contracts import WORKSPACE_OBSERVATION_PORT_CONTRACT
from openzyme_contracts import WORKSPACE_OBSERVATION_PORT_CONTRACT_DIGEST
from openzyme_contracts import WORKSPACE_PROCESS_PORT_CONTRACT
from openzyme_contracts import WORKSPACE_PROCESS_PORT_CONTRACT_DIGEST
from openzyme_contracts import WORKSPACE_TRANSFER_PORT_CONTRACT
from openzyme_contracts import WORKSPACE_TRANSFER_PORT_CONTRACT_DIGEST
from openzyme_extension_spi import AdapterManifest
from openzyme_extension_spi import EXTENSION_MANIFEST_ENTRY_POINT_GROUP
from openzyme_extension_spi import discover_extension_manifest_locators
from openzyme_extension_spi import read_located_component_manifest
from openzyme_extension_spi import verify_located_component_manifest
from openzyme_runtime_spi import PROCESS_ISOLATION_PORT_CONTRACT
from openzyme_runtime_spi import PROCESS_ISOLATION_PORT_CONTRACT_DIGEST
from openzyme_process_podman.manifest_locator import locate_component_manifest
from openzyme_process_podman import PODMAN_ADAPTER_CONFIGURATION_SCHEMA_DIGEST
from openzyme_process_podman import PODMAN_ADAPTER_PREFLIGHT_CONTRACT_DIGEST


def test_podman_locator_binds_canonical_resource_and_all_implemented_ports() -> None:
    locator = locate_component_manifest()
    source = (
        resources.files("openzyme_process_podman")
        .joinpath("manifests/adapter.json")
        .read_bytes()
    )
    manifest = verify_located_component_manifest(
        locator,
        source,
        installed_distribution_name="openzyme-process-podman",
        installed_distribution_version="0.1.0",
    )

    assert isinstance(manifest, AdapterManifest)
    assert {
        item.contribution_id: item.contract_digest
        for item in manifest.port_contracts
    } == {
        PROCESS_ISOLATION_PORT_CONTRACT: PROCESS_ISOLATION_PORT_CONTRACT_DIGEST,
        WORKSPACE_FILESYSTEM_PORT_CONTRACT: (
            WORKSPACE_FILESYSTEM_PORT_CONTRACT_DIGEST
        ),
        WORKSPACE_OBSERVATION_PORT_CONTRACT: (
            WORKSPACE_OBSERVATION_PORT_CONTRACT_DIGEST
        ),
        WORKSPACE_PROCESS_PORT_CONTRACT: WORKSPACE_PROCESS_PORT_CONTRACT_DIGEST,
        WORKSPACE_TRANSFER_PORT_CONTRACT: WORKSPACE_TRANSFER_PORT_CONTRACT_DIGEST,
    }
    assert manifest.configuration_schema_digest == (
        PODMAN_ADAPTER_CONFIGURATION_SCHEMA_DIGEST
    )
    assert manifest.preflight_contract_digest == (
        PODMAN_ADAPTER_PREFLIGHT_CONTRACT_DIGEST
    )


def test_installed_entry_point_is_locator_only_and_resource_is_wheel_readable() -> None:
    entry_point = next(
        item
        for item in importlib.metadata.entry_points(
            group=EXTENSION_MANIFEST_ENTRY_POINT_GROUP
        )
        if item.name == "openzyme.process.podman"
    )

    locators = discover_extension_manifest_locators((entry_point,))
    manifest = read_located_component_manifest(locators[0])

    assert isinstance(manifest, AdapterManifest)
    assert manifest.identity.component_id == "openzyme.process.podman"
    assert not hasattr(locators[0], "activate")


def test_locator_import_does_not_import_runtime_implementation_modules() -> None:
    script = """
import json
import sys
from openzyme_process_podman.manifest_locator import locate_component_manifest
locator = locate_component_manifest()
runtime_modules = sorted(
    name for name in sys.modules
    if name in {
        'openzyme_process_podman.filesystem',
        'openzyme_process_podman.lifecycle',
        'openzyme_process_podman.preflight',
        'openzyme_process_podman.process',
        'openzyme_process_podman.state',
        'openzyme_process_podman.transfer',
    }
)
print(json.dumps({'component_id': locator.component_id, 'runtime_modules': runtime_modules}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    observed = json.loads(completed.stdout)

    assert observed == {
        "component_id": "openzyme.process.podman",
        "runtime_modules": [],
    }
