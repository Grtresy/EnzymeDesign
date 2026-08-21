from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


STRUCTURE_COMPONENT_MANIFEST_DIGEST = (
    "sha256:a865e9ee8ef3f7f2b3ffd36cfe8da45b557c9db410915a3d5db91a5a016d9235"
)
FPOCKET_LOCAL_DRIVER_MANIFEST_DIGEST = (
    "sha256:0e219e213a1c80da1c810b9f86dde4690789969e685021328362833f8abe9b2a"
)
FPOCKET_HPC_DRIVER_MANIFEST_DIGEST = (
    "sha256:08ec3edd57a9a96b3226fa5c576d94001b5e87b41618de1b801f4c3cd674cb5b"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="enzymedesign.structure",
        component_kind=ComponentKind.PLUGIN,
        distribution_name="enzymedesign-structure",
        distribution_version="0.1.0",
        resource_package="enzymedesign_structure",
        resource_name="manifests/plugin.json",
        manifest_digest=STRUCTURE_COMPONENT_MANIFEST_DIGEST,
    )


def locate_local_driver_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="enzymedesign.fpocket.local",
        component_kind=ComponentKind.DRIVER,
        distribution_name="enzymedesign-structure",
        distribution_version="0.1.0",
        resource_package="enzymedesign_structure",
        resource_name="manifests/local-driver.json",
        manifest_digest=FPOCKET_LOCAL_DRIVER_MANIFEST_DIGEST,
    )


def locate_hpc_driver_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="enzymedesign.fpocket.hpc",
        component_kind=ComponentKind.DRIVER,
        distribution_name="enzymedesign-structure",
        distribution_version="0.1.0",
        resource_package="enzymedesign_structure",
        resource_name="manifests/hpc-driver.json",
        manifest_digest=FPOCKET_HPC_DRIVER_MANIFEST_DIGEST,
    )


__all__ = [
    "FPOCKET_HPC_DRIVER_MANIFEST_DIGEST",
    "FPOCKET_LOCAL_DRIVER_MANIFEST_DIGEST",
    "STRUCTURE_COMPONENT_MANIFEST_DIGEST",
    "locate_component_manifest",
    "locate_hpc_driver_manifest",
    "locate_local_driver_manifest",
]
