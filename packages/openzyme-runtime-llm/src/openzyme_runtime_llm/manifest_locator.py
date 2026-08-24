from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


LLM_COMPONENT_MANIFEST_DIGEST = (
    "sha256:81002a92774355a83e26b1b141171ab881d42922e4b73a4ee53f7bb257fdd853"
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
