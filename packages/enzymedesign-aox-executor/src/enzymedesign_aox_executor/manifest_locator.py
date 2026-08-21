from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


AOX_EXECUTOR_MANIFEST_DIGEST = (
    "sha256:701777714b6998537bb2556ebd5aebf7a71147738ef1059ef0b32da32b138e4c"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="enzymedesign.aox.executor",
        component_kind=ComponentKind.DRIVER,
        distribution_name="enzymedesign-aox-executor",
        distribution_version="0.1.0",
        resource_package="enzymedesign_aox_executor",
        resource_name="manifests/driver.json",
        manifest_digest=AOX_EXECUTOR_MANIFEST_DIGEST,
    )


__all__ = ["AOX_EXECUTOR_MANIFEST_DIGEST", "locate_component_manifest"]
