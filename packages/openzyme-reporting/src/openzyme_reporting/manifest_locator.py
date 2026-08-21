from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


REPORTING_COMPONENT_MANIFEST_DIGEST = (
    "sha256:9bf0fa73204072eda5154e7f67c9a30a3819b899c8fbf553de64a60284976476"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="openzyme.reporting",
        component_kind=ComponentKind.PLUGIN,
        distribution_name="openzyme-reporting",
        distribution_version="0.1.0",
        resource_package="openzyme_reporting",
        resource_name="manifests/plugin.json",
        manifest_digest=REPORTING_COMPONENT_MANIFEST_DIGEST,
    )


__all__ = ["REPORTING_COMPONENT_MANIFEST_DIGEST", "locate_component_manifest"]
