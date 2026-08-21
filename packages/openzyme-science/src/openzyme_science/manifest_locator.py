from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


SCIENCE_COMPONENT_MANIFEST_DIGEST = (
    "sha256:fbac0d99e210ab373c3ed027959ea82b482144be60815f1c7e6f60712f5cca70"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="openzyme.science",
        component_kind=ComponentKind.PLUGIN,
        distribution_name="openzyme-science",
        distribution_version="0.1.0",
        resource_package="openzyme_science",
        resource_name="manifests/plugin.json",
        manifest_digest=SCIENCE_COMPONENT_MANIFEST_DIGEST,
    )


__all__ = ["SCIENCE_COMPONENT_MANIFEST_DIGEST", "locate_component_manifest"]
