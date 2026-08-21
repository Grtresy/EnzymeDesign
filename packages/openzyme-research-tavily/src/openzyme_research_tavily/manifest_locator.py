from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


TAVILY_COMPONENT_MANIFEST_DIGEST = (
    "sha256:674b9896ed24b4b37813b68028f6da951cb7a5b1497d348ca11f133ac14eedf0"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="openzyme.research.tavily",
        component_kind=ComponentKind.ADAPTER,
        distribution_name="openzyme-research-tavily",
        distribution_version="0.1.0",
        resource_package="openzyme_research_tavily",
        resource_name="manifests/adapter.json",
        manifest_digest=TAVILY_COMPONENT_MANIFEST_DIGEST,
    )


__all__ = ["TAVILY_COMPONENT_MANIFEST_DIGEST", "locate_component_manifest"]
