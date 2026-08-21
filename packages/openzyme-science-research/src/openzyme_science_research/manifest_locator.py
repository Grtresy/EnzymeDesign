from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


SCIENCE_RESEARCH_COMPONENT_MANIFEST_DIGEST = (
    "sha256:fc91b346c744afeee1bfd4b7103ec5a991a974902584fff242a6cc35d205aba9"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="openzyme.science-research",
        component_kind=ComponentKind.PLUGIN,
        distribution_name="openzyme-science-research",
        distribution_version="0.1.0",
        resource_package="openzyme_science_research",
        resource_name="manifests/plugin.json",
        manifest_digest=SCIENCE_RESEARCH_COMPONENT_MANIFEST_DIGEST,
    )


__all__ = ["SCIENCE_RESEARCH_COMPONENT_MANIFEST_DIGEST", "locate_component_manifest"]
