from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


VINA_COMPONENT_MANIFEST_DIGEST = (
    "sha256:cc033b5d96d31b6554dc67640ae1e39e249b4b98fc54edcfd9864c8d11e0302f"
)
VINA_LOCAL_DRIVER_MANIFEST_DIGEST = (
    "sha256:715eba8841165efad30ad2ba1f78ccd2a5652dd65e3defdfc168a1aa5a333746"
)
VINA_HPC_DRIVER_MANIFEST_DIGEST = (
    "sha256:1f153ac9c5c02afafb537631061c9b6f6ad4d59a9aee9c5d15e4f5b6a510cc5f"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="enzymedesign.vina",
        component_kind=ComponentKind.PLUGIN,
        distribution_name="enzymedesign-vina",
        distribution_version="0.1.0",
        resource_package="enzymedesign_vina",
        resource_name="manifests/plugin.json",
        manifest_digest=VINA_COMPONENT_MANIFEST_DIGEST,
    )


def locate_local_driver_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="enzymedesign.vina.local",
        component_kind=ComponentKind.DRIVER,
        distribution_name="enzymedesign-vina",
        distribution_version="0.1.0",
        resource_package="enzymedesign_vina",
        resource_name="manifests/local-driver.json",
        manifest_digest=VINA_LOCAL_DRIVER_MANIFEST_DIGEST,
    )


def locate_hpc_driver_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="enzymedesign.vina.hpc",
        component_kind=ComponentKind.DRIVER,
        distribution_name="enzymedesign-vina",
        distribution_version="0.1.0",
        resource_package="enzymedesign_vina",
        resource_name="manifests/hpc-driver.json",
        manifest_digest=VINA_HPC_DRIVER_MANIFEST_DIGEST,
    )


__all__ = [
    "VINA_COMPONENT_MANIFEST_DIGEST",
    "VINA_HPC_DRIVER_MANIFEST_DIGEST",
    "VINA_LOCAL_DRIVER_MANIFEST_DIGEST",
    "locate_component_manifest",
    "locate_hpc_driver_manifest",
    "locate_local_driver_manifest",
]
