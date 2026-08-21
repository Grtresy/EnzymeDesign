from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


BIO_PROVIDER_HTTP_COMPONENT_MANIFEST_DIGEST = (
    "sha256:67010aa78958f419d3cf76c32862dba538747c29e6df64285e03cbd729c7baab"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="enzymedesign.bio-provider-http",
        component_kind=ComponentKind.ADAPTER,
        distribution_name="enzymedesign-bio-provider-adapters",
        distribution_version="0.1.0",
        resource_package="enzymedesign_bio_provider_adapters",
        resource_name="manifests/adapter.json",
        manifest_digest=BIO_PROVIDER_HTTP_COMPONENT_MANIFEST_DIGEST,
    )


__all__ = [
    "BIO_PROVIDER_HTTP_COMPONENT_MANIFEST_DIGEST",
    "locate_component_manifest",
]
