from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


PREPROCESS_COMPONENT_MANIFEST_DIGEST = (
    "sha256:d6d25c26c6afdd6bed95d22672784769458abe309bf7ed8c996eab7c9c179ea0"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="enzymedesign.docking.preprocess",
        component_kind=ComponentKind.PLUGIN,
        distribution_name="enzymedesign-docking-preprocess",
        distribution_version="0.1.0",
        resource_package="enzymedesign_docking_preprocess",
        resource_name="manifests/plugin.json",
        manifest_digest=PREPROCESS_COMPONENT_MANIFEST_DIGEST,
    )


__all__ = ["PREPROCESS_COMPONENT_MANIFEST_DIGEST", "locate_component_manifest"]
