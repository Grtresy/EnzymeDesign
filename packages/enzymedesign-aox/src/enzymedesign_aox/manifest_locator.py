from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


# Updated together with manifests/plugin.json. Discovery only locates this
# exact resource; it never activates an installed package ambiently.
AOX_COMPONENT_MANIFEST_DIGEST = (
    "sha256:6eebd9bceaaceb812e45b14b2c5d3511b0edfd68b54ec1b3c1af21d6789d708b"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="enzymedesign.aox",
        component_kind=ComponentKind.PLUGIN,
        distribution_name="enzymedesign-aox",
        distribution_version="0.1.0",
        resource_package="enzymedesign_aox",
        resource_name="manifests/plugin.json",
        manifest_digest=AOX_COMPONENT_MANIFEST_DIGEST,
    )


__all__ = ["AOX_COMPONENT_MANIFEST_DIGEST", "locate_component_manifest"]
