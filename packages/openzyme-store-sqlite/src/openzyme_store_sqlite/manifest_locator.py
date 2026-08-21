from __future__ import annotations

from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


SQLITE_COMPONENT_MANIFEST_DIGEST = (
    "sha256:ef17029ddd1bced87e501aa05692c692faf27980c10ab2db8a37dc52057b3c2b"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="openzyme.store.sqlite",
        component_kind=ComponentKind.ADAPTER,
        distribution_name="openzyme-store-sqlite",
        distribution_version="0.1.0",
        resource_package="openzyme_store_sqlite",
        resource_name="manifests/adapter.json",
        manifest_digest=SQLITE_COMPONENT_MANIFEST_DIGEST,
    )


__all__ = ["SQLITE_COMPONENT_MANIFEST_DIGEST", "locate_component_manifest"]
