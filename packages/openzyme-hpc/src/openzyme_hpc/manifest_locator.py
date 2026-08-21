from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


HPC_COMPONENT_MANIFEST_DIGEST = (
    "sha256:0c8ac4ad5753c9829c10163ebeb6bf71bd5343063865f112556034c48292b16e"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="openzyme.hpc",
        component_kind=ComponentKind.PLUGIN,
        distribution_name="openzyme-hpc",
        distribution_version="0.1.0",
        resource_package="openzyme_hpc",
        resource_name="manifests/plugin.json",
        manifest_digest=HPC_COMPONENT_MANIFEST_DIGEST,
    )


__all__ = ["HPC_COMPONENT_MANIFEST_DIGEST", "locate_component_manifest"]
