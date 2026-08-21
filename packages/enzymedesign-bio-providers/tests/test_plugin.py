from importlib.resources import files

from enzymedesign_bio_provider_adapters import DeterministicBioProviderAdapter
from enzymedesign_bio_providers import BIO_PROVIDER_ROUTE_IDS
from enzymedesign_bio_providers import build_bio_provider_route_runtimes
from enzymedesign_bio_providers import locate_component_manifest
from openzyme_extension_spi import CapabilityRouteInvocation
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import parse_component_manifest_json


DIGEST = "sha256:" + "d" * 64


def _invocation(route_id: str, capability_id: str, payload: dict):
    return CapabilityRouteInvocation(
        context=KernelCommandContext(
            command_id="command-1",
            session_id="session-1",
            actor_id="member-1",
            owner_plugin_id="enzymedesign.bio-providers",
            authority_lease_id="lease-1",
            authority_generation=1,
            authority_fence=1,
            expected_session_version=1,
            extension_bundle_digest=DIGEST,
            capability_binding_digest=DIGEST,
            idempotency_key="provider-1",
            correlation_id="correlation-1",
            route_id=route_id,
        ),
        route_id=route_id,
        capability_id=capability_id,
        payload=payload,
    )


def test_plugin_routes_delegate_to_one_exact_adapter_without_terminal_inference() -> (
    None
):
    runtimes = {
        item.route_id: item
        for item in build_bio_provider_route_runtimes(DeterministicBioProviderAdapter())
    }
    route_id = BIO_PROVIDER_ROUTE_IDS["enzymedesign.provider.uniprot"]

    result = runtimes[route_id].invoke(
        _invocation(
            route_id,
            "enzymedesign.provider.uniprot",
            {"operation": "lookup", "accession": "P12345"},
        )
    )

    assert result.ok is True
    assert result.payload["fallback_performed"] is False
    assert result.payload["publication_created"] is False
    assert result.payload["scientific_evidence_created"] is False
    assert result.payload["task_finished"] is False


def test_plugin_manifest_provides_three_exact_routes() -> None:
    locator = locate_component_manifest()
    manifest = parse_component_manifest_json(
        files(locator.resource_package)
        .joinpath(locator.resource_name)
        .read_text(encoding="utf-8")
    )

    assert manifest.manifest_digest == locator.manifest_digest
    assert {item.capability_id for item in manifest.provides} == set(
        BIO_PROVIDER_ROUTE_IDS
    )
    assert {item.route_id for item in manifest.routes} == set(
        BIO_PROVIDER_ROUTE_IDS.values()
    )
