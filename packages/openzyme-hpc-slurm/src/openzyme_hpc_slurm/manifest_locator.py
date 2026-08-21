from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


SLURM_COMPONENT_MANIFEST_DIGEST = (
    "sha256:36e534f2219b3ed9b78a215a93f8cb1572bff30ca6ff3c379eb46835c41eb103"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="openzyme.hpc.slurm",
        component_kind=ComponentKind.ADAPTER,
        distribution_name="openzyme-hpc-slurm",
        distribution_version="0.1.0",
        resource_package="openzyme_hpc_slurm",
        resource_name="manifests/adapter.json",
        manifest_digest=SLURM_COMPONENT_MANIFEST_DIGEST,
    )


__all__ = ["SLURM_COMPONENT_MANIFEST_DIGEST", "locate_component_manifest"]
