from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


VINA_COMPONENT_MANIFEST_DIGEST = (
    "sha256:265c51ca2b19c3d8411e7edc2d952127a3a52cbb63abaebf4d6a13260dd436f8"
)
VINA_LOCAL_DRIVER_MANIFEST_DIGEST = (
    "sha256:c20d7484d30669ba82b245297daaff27afd6f6421df8a738072b11d5ab14f2b5"
)
VINA_HPC_DRIVER_MANIFEST_DIGEST = (
    "sha256:60e1745967793bf17993fe1877e94c442dfe49bade4c8bdf26a03e9e7c87bb08"
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
