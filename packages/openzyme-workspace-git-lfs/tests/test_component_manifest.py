from openzyme_extension_spi import read_located_component_manifest

from openzyme_workspace_git_lfs import WORKSPACE_BACKEND_CONTRACT_DIGEST
from openzyme_workspace_git_lfs import WORKSPACE_BACKEND_ID
from openzyme_workspace_git_lfs import WORKSPACE_BACKEND_IMPLEMENTATION_DIGEST
from openzyme_workspace_git_lfs.manifest_locator import locate_component_manifest


def test_git_lfs_adapter_manifest_declares_workspace_backend_port() -> None:
    manifest = read_located_component_manifest(locate_component_manifest())

    assert manifest.identity.component_id == "openzyme.workspace.git.lfs"
    assert [item.contribution_id for item in manifest.port_contracts] == [
        "openzyme.workspace-backend-port@1"
    ]
    assert WORKSPACE_BACKEND_ID == "openzyme.workspace.git-lfs@1"
    assert manifest.identity.contract_digest == WORKSPACE_BACKEND_CONTRACT_DIGEST
    assert manifest.manifest_digest == WORKSPACE_BACKEND_IMPLEMENTATION_DIGEST
    assert locate_component_manifest().manifest_digest == (
        WORKSPACE_BACKEND_IMPLEMENTATION_DIGEST
    )
