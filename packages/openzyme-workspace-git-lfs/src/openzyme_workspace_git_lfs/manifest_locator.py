from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


GIT_LFS_COMPONENT_MANIFEST_DIGEST = (
    "sha256:99bb32be534b0ca9e1e7ea15102c1b35342ca3591d324c0364135a278c7a08b3"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="openzyme.workspace.git.lfs",
        component_kind=ComponentKind.ADAPTER,
        distribution_name="openzyme-workspace-git-lfs",
        distribution_version="0.1.0",
        resource_package="openzyme_workspace_git_lfs",
        resource_name="manifests/adapter.json",
        manifest_digest=GIT_LFS_COMPONENT_MANIFEST_DIGEST,
    )


__all__ = ["GIT_LFS_COMPONENT_MANIFEST_DIGEST", "locate_component_manifest"]
