from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


LLM_COMPONENT_MANIFEST_DIGEST = (
    "sha256:6e16b2af91d4e18b25747fd7bab071bfa4261b26c520c04e58cf78fb0ea0713a"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="openzyme.runtime.llm",
        component_kind=ComponentKind.ADAPTER,
        distribution_name="openzyme-runtime-llm",
        distribution_version="0.1.0",
        resource_package="openzyme_runtime_llm",
        resource_name="manifests/adapter.json",
        manifest_digest=LLM_COMPONENT_MANIFEST_DIGEST,
    )


__all__ = ["LLM_COMPONENT_MANIFEST_DIGEST", "locate_component_manifest"]
