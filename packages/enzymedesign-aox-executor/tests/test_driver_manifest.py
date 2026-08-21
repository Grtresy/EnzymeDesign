from importlib.resources import files

from enzymedesign_aox import AOX_SCIENTIFIC_FILE_BUNDLE_CONTRACT_DIGEST
from enzymedesign_aox_executor import AOX_EXECUTOR_MANIFEST_DIGEST
from enzymedesign_aox_executor import aox_finalization
from enzymedesign_aox_executor import locate_component_manifest
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import parse_component_manifest_json


def test_aox_executor_driver_manifest_binds_calculations_and_result() -> None:
    locator = locate_component_manifest()
    manifest = parse_component_manifest_json(
        files(locator.resource_package)
        .joinpath(locator.resource_name)
        .read_text(encoding="utf-8")
    )

    assert manifest.manifest_digest == AOX_EXECUTOR_MANIFEST_DIGEST
    assert locator.manifest_digest == AOX_EXECUTOR_MANIFEST_DIGEST
    assert manifest.owning_plugin_id == "enzymedesign.aox"
    assert manifest.owning_plugin_contract == "enzymedesign.aox.workflow@1"
    assert manifest.route_kind == "sandbox"
    assert manifest.required_port_contracts == (
        "openzyme.process-isolation-port@1",
    )
    assert manifest.workload_contract_digest == canonical_sha256_digest(
        aox_finalization.installed_calculation_manifest()
    )
    assert (
        manifest.result_contract_digest
        == AOX_SCIENTIFIC_FILE_BUNDLE_CONTRACT_DIGEST
    )


def test_aox_executor_has_no_platform_private_or_hpc_implementation_imports() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in files("enzymedesign_aox_executor").iterdir()
        if path.name.endswith(".py")
    )

    for forbidden in (
        "openzyme_core",
        "openzyme_host_api",
        "openzyme_hpc",
        "openzyme_hpc_slurm",
        "openzyme_hpc_ssh",
        "paramiko",
        "sqlite3",
    ):
        assert forbidden not in source
