from openzyme_extension_spi import read_located_component_manifest
from openzyme_hpc import HPC_SCHEDULER_PORT_CONTRACT
from openzyme_hpc_slurm.manifest_locator import locate_component_manifest


def test_slurm_manifest_implements_only_target_scoped_scheduler_port() -> None:
    manifest = read_located_component_manifest(locate_component_manifest())

    assert manifest.identity.component_id == "openzyme.hpc.slurm"
    assert manifest.target_scoped is True
    assert [item.contribution_id for item in manifest.port_contracts] == [
        HPC_SCHEDULER_PORT_CONTRACT
    ]
