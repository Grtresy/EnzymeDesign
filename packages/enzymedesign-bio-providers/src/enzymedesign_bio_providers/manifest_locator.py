from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import ExtensionManifestLocator


BIO_PROVIDERS_COMPONENT_MANIFEST_DIGEST = (
    "sha256:fade33a29b2af8e5ce9fc30c48482c10b159295886c4d78a8de0d9e2919858e6"
)


def locate_component_manifest() -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id="enzymedesign.bio-providers",
        component_kind=ComponentKind.PLUGIN,
        distribution_name="enzymedesign-bio-providers",
        distribution_version="0.1.0",
        resource_package="enzymedesign_bio_providers",
        resource_name="manifests/plugin.json",
        manifest_digest=BIO_PROVIDERS_COMPONENT_MANIFEST_DIGEST,
    )


__all__ = ["BIO_PROVIDERS_COMPONENT_MANIFEST_DIGEST", "locate_component_manifest"]
