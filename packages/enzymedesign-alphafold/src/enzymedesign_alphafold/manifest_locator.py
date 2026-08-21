from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


ALPHAFOLD_COMPONENT_MANIFEST_DIGEST = (
    "sha256:9575ac56ea3a66b6353691d9b9bcc2210856419ea2081c90b23a53d265ea610f"
)
ALPHAFOLD_HPC_DRIVER_MANIFEST_DIGEST = (
    "sha256:02184a38f253fcb2fb0a5bf09f21dec752e3adc764c2040ec93e15d058064f2f"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="enzymedesign.alphafold",
        component_kind=ComponentKind.PLUGIN,
        distribution_name="enzymedesign-alphafold",
        distribution_version="0.1.0",
        resource_package="enzymedesign_alphafold",
        resource_name="manifests/plugin.json",
        manifest_digest=ALPHAFOLD_COMPONENT_MANIFEST_DIGEST,
    )


def locate_hpc_driver_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="enzymedesign.alphafold.hpc",
        component_kind=ComponentKind.DRIVER,
        distribution_name="enzymedesign-alphafold",
        distribution_version="0.1.0",
        resource_package="enzymedesign_alphafold",
        resource_name="manifests/hpc-driver.json",
        manifest_digest=ALPHAFOLD_HPC_DRIVER_MANIFEST_DIGEST,
    )


__all__ = [
    "ALPHAFOLD_COMPONENT_MANIFEST_DIGEST",
    "ALPHAFOLD_HPC_DRIVER_MANIFEST_DIGEST",
    "locate_component_manifest",
    "locate_hpc_driver_manifest",
]
