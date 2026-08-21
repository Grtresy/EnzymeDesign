from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


COMPUTE_COMPONENT_MANIFEST_DIGEST = (
    "sha256:a7d6817f2817bef188d0e0256d2a45e168995a0f45fb072061e882b2ffa3415a"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="openzyme.compute",
        component_kind=ComponentKind.PLUGIN,
        distribution_name="openzyme-compute",
        distribution_version="0.1.0",
        resource_package="openzyme_compute",
        resource_name="manifests/plugin.json",
        manifest_digest=COMPUTE_COMPONENT_MANIFEST_DIGEST,
    )


__all__ = ["COMPUTE_COMPONENT_MANIFEST_DIGEST", "locate_component_manifest"]
