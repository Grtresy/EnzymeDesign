from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


PODMAN_COMPONENT_MANIFEST_DIGEST = (
    "sha256:42fbd21f02f1c5c374cbfcf0dea6c129d474010485bb80ef5e821d86e80816b0"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    """Return metadata only; importing this locator never activates an Adapter."""

    return ExtensionManifestLocator(
        component_id="openzyme.process.podman",
        component_kind=ComponentKind.ADAPTER,
        distribution_name="openzyme-process-podman",
        distribution_version="0.1.0",
        resource_package="openzyme_process_podman",
        resource_name="manifests/adapter.json",
        manifest_digest=PODMAN_COMPONENT_MANIFEST_DIGEST,
    )


__all__ = [
    "PODMAN_COMPONENT_MANIFEST_DIGEST",
    "locate_component_manifest",
]
