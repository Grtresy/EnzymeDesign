from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


SEQUENCE_COMPONENT_MANIFEST_DIGEST = (
    "sha256:ea39f8dc2931ef343823e9e30259183d8282cfda7b8f081d022c2ba6079ad319"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="enzymedesign.sequence.toolpack",
        component_kind=ComponentKind.PLUGIN,
        distribution_name="enzymedesign-sequence-toolpack",
        distribution_version="0.1.0",
        resource_package="enzymedesign_sequence_toolpack",
        resource_name="manifests/plugin.json",
        manifest_digest=SEQUENCE_COMPONENT_MANIFEST_DIGEST,
    )


__all__ = ["SEQUENCE_COMPONENT_MANIFEST_DIGEST", "locate_component_manifest"]
