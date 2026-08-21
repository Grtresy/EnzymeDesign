from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


RESEARCH_COMPONENT_MANIFEST_DIGEST = (
    "sha256:d7e9153613f4a26eb60546b543f2c1a49ef52c9637f0279a3812ebe60c934197"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="openzyme.research",
        component_kind=ComponentKind.PLUGIN,
        distribution_name="openzyme-research",
        distribution_version="0.1.0",
        resource_package="openzyme_research",
        resource_name="manifests/plugin.json",
        manifest_digest=RESEARCH_COMPONENT_MANIFEST_DIGEST,
    )


__all__ = ["RESEARCH_COMPONENT_MANIFEST_DIGEST", "locate_component_manifest"]
