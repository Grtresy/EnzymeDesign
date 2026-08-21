from __future__ import annotations

from importlib.resources import files

import pytest

from enzymedesign_alphafold import ALPHAFOLD_COMPONENT_MANIFEST_DIGEST
from enzymedesign_alphafold import ALPHAFOLD_DRIVER_REQUEST_CONTRACT_DIGEST
from enzymedesign_alphafold import ALPHAFOLD_HPC_DRIVER_MANIFEST_DIGEST
from enzymedesign_alphafold import ALPHAFOLD_TOOL_SPEC
from enzymedesign_alphafold import AlphaFoldHpcDriver
from enzymedesign_alphafold import build_alphafold_plugin_runtime_surfaces
from enzymedesign_alphafold import locate_component_manifest
from enzymedesign_alphafold import locate_hpc_driver_manifest
from openzyme_extension_spi import DriverInvocationRequest
from openzyme_extension_spi import DriverManifest
from openzyme_extension_spi import PluginManifest
from openzyme_extension_spi import parse_component_manifest_json


DIGEST = "sha256:" + "1" * 64


class _RuntimeApplication:
    def request(self, *, invocation):
        return {"workload_id": "workload-af3", "workload_digest": DIGEST, "state": "admitted"}

    def invoke_route(self, *, invocation, driver_id):
        return {"state": "compiled", "driver_id": driver_id}


def _manifest(locator):
    return parse_component_manifest_json(
        files(locator.resource_package)
        .joinpath(locator.resource_name)
        .read_text(encoding="utf-8")
    )


def test_alphafold_manifest_binds_software_assets_database_and_gpu() -> None:
    plugin = _manifest(locate_component_manifest())
    driver = _manifest(locate_hpc_driver_manifest())

    assert isinstance(plugin, PluginManifest)
    assert isinstance(driver, DriverManifest)
    assert plugin.manifest_digest == ALPHAFOLD_COMPONENT_MANIFEST_DIGEST
    assert driver.manifest_digest == ALPHAFOLD_HPC_DRIVER_MANIFEST_DIGEST
    assert {item.capability_id for item in plugin.requires} == {
        "accelerator.cuda",
        "asset.alphafold3-model-parameters",
        "dataset.alphafold3-database",
        "openzyme.execution.revision-job",
        "software.alphafold3",
    }
    assert all(
        item.same_target_as == "openzyme.execution.revision-job"
        for item in plugin.requires
        if item.capability_id != "openzyme.execution.revision-job"
    )


def test_alphafold_runtime_surfaces_match_the_declared_hpc_route() -> None:
    application = _RuntimeApplication()
    surfaces = build_alphafold_plugin_runtime_surfaces(
        application=application,
        route_application=application,
    )

    assert len(surfaces.tools) == 1
    assert [item.route_id for item in surfaces.capability_routes] == [
        "enzymedesign.alphafold.hpc-primary@1"
    ]


def _request(**extra):
    payload = {
        "workload_id": "workload-af3",
        "cwd": "analysis/alphafold3",
        "resource_policy_digest": DIGEST,
        "environment_policy_digest": DIGEST,
        "inputs": (
            {
                "revision_id": "revision-1",
                "commit": "a" * 40,
                "tree": "b" * 40,
                "path": "inputs/job.json",
                "content_digest": DIGEST,
            },
        ),
        "result_root": "results/alphafold3",
        **extra,
    }
    return DriverInvocationRequest(
        driver_id="enzymedesign.alphafold.hpc",
        owning_plugin_id="enzymedesign.alphafold",
        route_id="hpc-primary.revision-job",
        tool_name=ALPHAFOLD_TOOL_SPEC.tool_name,
        tool_contract_digest=ALPHAFOLD_TOOL_SPEC.contract_digest,
        request_contract_digest=ALPHAFOLD_DRIVER_REQUEST_CONTRACT_DIGEST,
        payload=payload,
    )


def test_alphafold_driver_compiles_without_private_resource_paths() -> None:
    manifest = _manifest(locate_hpc_driver_manifest())
    assert isinstance(manifest, DriverManifest)
    workload = AlphaFoldHpcDriver(manifest).compile(_request())

    assert list(workload.workload["argv"]) == [
        "python",
        "run_alphafold.py",
        "--json_path",
        "inputs/job.json",
        "--output_dir",
        "results/alphafold3",
    ]
    assert "database_path" not in workload.workload
    assert "model_parameters_path" not in workload.workload
    assert "credential" not in workload.workload


@pytest.mark.parametrize(
    "extra",
    (
        {"database_path": "/private/database"},
        {"model_parameters_path": "/private/models"},
        {"argv": ["python", "other.py"]},
    ),
)
def test_alphafold_driver_rejects_private_or_compiled_fields(extra) -> None:
    manifest = _manifest(locate_hpc_driver_manifest())
    assert isinstance(manifest, DriverManifest)
    with pytest.raises(ValueError, match="fields are closed"):
        AlphaFoldHpcDriver(manifest).compile(_request(**extra))
