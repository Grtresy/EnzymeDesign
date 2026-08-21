from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


SLURM_COMPONENT_MANIFEST_DIGEST = (
    "sha256:573f7473b929113afcc3c261fae35883605d3861e296e66a28d9d09a47f930a2"
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
