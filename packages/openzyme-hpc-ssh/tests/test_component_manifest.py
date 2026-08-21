from openzyme_contracts import WORKSPACE_FILESYSTEM_PORT_CONTRACT
from openzyme_contracts import WORKSPACE_OBSERVATION_PORT_CONTRACT
from openzyme_contracts import WORKSPACE_PROCESS_PORT_CONTRACT
from openzyme_contracts import WORKSPACE_TRANSFER_PORT_CONTRACT
from openzyme_extension_spi import read_located_component_manifest
from openzyme_hpc_ssh.manifest_locator import locate_component_manifest


def test_ssh_adapter_manifest_is_target_scoped_and_exact() -> None:
    manifest = read_located_component_manifest(locate_component_manifest())

    assert manifest.identity.component_id == "openzyme.hpc.ssh"
    assert manifest.target_scoped is True
    assert {item.contribution_id for item in manifest.port_contracts} == {
        WORKSPACE_FILESYSTEM_PORT_CONTRACT,
        WORKSPACE_OBSERVATION_PORT_CONTRACT,
        WORKSPACE_PROCESS_PORT_CONTRACT,
        WORKSPACE_TRANSFER_PORT_CONTRACT,
    }
