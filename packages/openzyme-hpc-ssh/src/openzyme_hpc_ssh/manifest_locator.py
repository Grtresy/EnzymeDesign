from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


SSH_COMPONENT_MANIFEST_DIGEST = (
    "sha256:7e7555d39077b2f0b7709198d4515a0d35be6b3fe9e1d2e7fc32e0fa79c5ca4a"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="openzyme.hpc.ssh",
        component_kind=ComponentKind.ADAPTER,
        distribution_name="openzyme-hpc-ssh",
        distribution_version="0.1.0",
        resource_package="openzyme_hpc_ssh",
        resource_name="manifests/adapter.json",
        manifest_digest=SSH_COMPONENT_MANIFEST_DIGEST,
    )


__all__ = ["SSH_COMPONENT_MANIFEST_DIGEST", "locate_component_manifest"]
