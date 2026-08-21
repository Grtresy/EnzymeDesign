from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


HMMER_COMPONENT_MANIFEST_DIGEST = (
    "sha256:5f023f299ce35cee254a3617d85bf057885b31a71249bcf1b9455bff5b288f7f"
)
HMMER_LOCAL_DRIVER_MANIFEST_DIGEST = (
    "sha256:32748b4746d7401aa606a1285a612b3c15d8c86c1354ea8bb3c870044836ea3e"
)
HMMER_HPC_DRIVER_MANIFEST_DIGEST = (
    "sha256:20c9c745b7d8ec4807d301e7e7b9dc0ca2134d98768ab8219b0dcbaceb3c15fc"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="enzymedesign.hmmer",
        component_kind=ComponentKind.PLUGIN,
        distribution_name="enzymedesign-hmmer",
        distribution_version="0.1.0",
        resource_package="enzymedesign_hmmer",
        resource_name="manifests/plugin.json",
        manifest_digest=HMMER_COMPONENT_MANIFEST_DIGEST,
    )


def locate_local_driver_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="enzymedesign.hmmer.local",
        component_kind=ComponentKind.DRIVER,
        distribution_name="enzymedesign-hmmer",
        distribution_version="0.1.0",
        resource_package="enzymedesign_hmmer",
        resource_name="manifests/local-driver.json",
        manifest_digest=HMMER_LOCAL_DRIVER_MANIFEST_DIGEST,
    )


def locate_hpc_driver_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="enzymedesign.hmmer.hpc",
        component_kind=ComponentKind.DRIVER,
        distribution_name="enzymedesign-hmmer",
        distribution_version="0.1.0",
        resource_package="enzymedesign_hmmer",
        resource_name="manifests/hpc-driver.json",
        manifest_digest=HMMER_HPC_DRIVER_MANIFEST_DIGEST,
    )


__all__ = [
    "HMMER_COMPONENT_MANIFEST_DIGEST",
    "HMMER_HPC_DRIVER_MANIFEST_DIGEST",
    "HMMER_LOCAL_DRIVER_MANIFEST_DIGEST",
    "locate_component_manifest",
    "locate_hpc_driver_manifest",
    "locate_local_driver_manifest",
]
