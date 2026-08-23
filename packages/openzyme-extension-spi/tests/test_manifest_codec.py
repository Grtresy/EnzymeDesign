from __future__ import annotations

import json

import pytest

from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_json_bytes
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import AdapterManifest
from openzyme_extension_spi import CapabilityProvision
from openzyme_extension_spi import CapabilityRequirement
from openzyme_extension_spi import CapabilityRequirementKind
from openzyme_extension_spi import ComponentIdentity
from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import DriverManifest
from openzyme_extension_spi import ExtensionManifestLocator
from openzyme_extension_spi import NamedContribution
from openzyme_extension_spi import PluginManifest
from openzyme_extension_spi import QualificationSpec
from openzyme_extension_spi import RouteContribution
from openzyme_extension_spi import ToolContribution
from openzyme_extension_spi import parse_component_manifest_json
from openzyme_extension_spi import verify_located_component_manifest


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _identity(component_id: str, kind: ComponentKind) -> ComponentIdentity:
    return ComponentIdentity(
        component_id=component_id,
        component_kind=kind,
        component_version="1.0.0",
        distribution_name=component_id.replace(".", "-"),
        distribution_version="1.0.0",
        build_digest=_digest(f"{component_id}:build"),
        contract_digest=_digest(f"{component_id}:contract"),
    )


def _adapter() -> AdapterManifest:
    return AdapterManifest(
        identity=_identity("openzyme.store.sqlite", ComponentKind.ADAPTER),
        required_contracts=("openzyme.control-store@1",),
        port_contracts=(
            NamedContribution(
                "openzyme.control-store@1",
                _digest("control-store-port"),
            ),
        ),
        configuration_schema_digest=_digest("sqlite-configuration"),
        preflight_contract_digest=_digest("sqlite-preflight"),
    )


def _plugin() -> PluginManifest:
    plugin_id = "enzymedesign.hmmer"
    compute = CapabilityRequirement(
        "openzyme.execution.revision-job",
        "@1",
    )
    hmmer = CapabilityRequirement(
        "software.hmmer",
        "@1",
        kind=CapabilityRequirementKind.RESOURCE,
        operations=("hmmsearch",),
        version_spec=">=3.3,<4",
        same_target_as="openzyme.execution.revision-job",
    )
    return PluginManifest(
        identity=_identity(plugin_id, ComponentKind.PLUGIN),
        required_kernel_contract="openzyme.kernel@1",
        required_extension_spi_contract="openzyme.extension-spi@1",
        provides=(CapabilityProvision(plugin_id, "1", operations=("search",)),),
        requires=(compute, hmmer),
        tools=(
            ToolContribution(
                owner_plugin_id=plugin_id,
                runtime_id=f"{plugin_id}.runtime",
                contract=ToolSpec(
                    tool_name=f"{plugin_id}.search",
                    description="Run one formal HMMER search.",
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                    required_authorities=("external_compute",),
                ),
                requirements=(compute, hmmer),
                requires_workspace=True,
                requires_explicit_route=True,
            ),
        ),
        qualification_specs=(
            QualificationSpec(
                qualification_spec_id=f"{plugin_id}.qualification@1",
                owner_plugin_id=plugin_id,
                capability_id="software.hmmer",
                contract_version="1",
                version_argv=("hmmsearch", "-h"),
                smoke_argv=("hmmsearch", "--help"),
                expected_result_schema={"type": "object"},
            ),
        ),
        routes=(
            RouteContribution(
                route_id=f"{plugin_id}.hpc-primary",
                owner_component_id=plugin_id,
                capability_ids=(
                    plugin_id,
                    "openzyme.execution.revision-job",
                    "software.hmmer",
                ),
                route_kind="hpc",
                route_contract_digest=_digest("hmmer-route"),
                target_id="hpc-primary",
                driver_id=f"{plugin_id}.hpc",
                requirements=(hmmer,),
            ),
        ),
    )


def _driver() -> DriverManifest:
    return DriverManifest(
        identity=_identity("enzymedesign.hmmer.hpc", ComponentKind.DRIVER),
        owning_plugin_id="enzymedesign.hmmer",
        owning_plugin_contract="enzymedesign.hmmer@1",
        route_kind="hpc",
        required_port_contracts=("openzyme.execution-dispatch@1",),
        workload_contract_digest=_digest("hmmer-workload"),
        result_contract_digest=_digest("hmmer-result"),
    )


@pytest.mark.parametrize("manifest", (_adapter(), _plugin(), _driver()))
def test_closed_manifest_codec_round_trips_every_component_kind(
    manifest: AdapterManifest | PluginManifest | DriverManifest,
) -> None:
    encoded = canonical_json_bytes(manifest.to_dict())
    decoded = parse_component_manifest_json(encoded)

    assert decoded == manifest
    assert decoded.manifest_digest == manifest.manifest_digest


def test_manifest_codec_rejects_unknown_duplicate_and_unsupported_schema() -> None:
    payload = _adapter().to_dict()
    payload["ambient_registration"] = True
    with pytest.raises(ValueError, match="fields are closed"):
        parse_component_manifest_json(json.dumps(payload))

    with pytest.raises(ValueError, match="duplicate key"):
        parse_component_manifest_json(
            '{"schema_version":"openzyme_adapter_manifest@1",'
            '"schema_version":"openzyme_plugin_manifest@1"}'
        )

    with pytest.raises(ValueError, match="unsupported"):
        parse_component_manifest_json('{"schema_version":"future@9"}')


def test_route_requirement_rejects_unlisted_same_target_capability() -> None:
    with pytest.raises(ValueError, match="same-target resource capabilities"):
        RouteContribution(
            route_id="enzymedesign.hmmer.local",
            owner_component_id="enzymedesign.hmmer",
            capability_ids=("software.hmmer",),
            route_kind="local",
            route_contract_digest=_digest("hmmer-local-route"),
            target_id="local",
            driver_id="enzymedesign.hmmer.local",
            requirements=(
                CapabilityRequirement(
                    capability_id="software.hmmer",
                    contract_spec="@1",
                    kind=CapabilityRequirementKind.RESOURCE,
                    version_spec=">=3.3,<4",
                    same_target_as="openzyme.execution.revision-job",
                ),
            ),
        )


def test_locator_verification_binds_package_version_kind_and_manifest_digest() -> None:
    manifest = _plugin()
    locator = ExtensionManifestLocator(
        component_id=manifest.identity.component_id,
        component_kind=manifest.identity.component_kind,
        distribution_name=manifest.identity.distribution_name,
        distribution_version=manifest.identity.distribution_version,
        resource_package="enzymedesign_hmmer",
        resource_name="manifests/plugin.json",
        manifest_digest=manifest.manifest_digest,
    )
    source = canonical_json_bytes(manifest.to_dict())

    assert (
        verify_located_component_manifest(
            locator,
            source,
            installed_distribution_name=manifest.identity.distribution_name,
            installed_distribution_version=manifest.identity.distribution_version,
        )
        == manifest
    )
    with pytest.raises(ValueError, match="version drifted"):
        verify_located_component_manifest(
            locator,
            source,
            installed_distribution_name=manifest.identity.distribution_name,
            installed_distribution_version="2.0.0",
        )
    with pytest.raises(ValueError, match="identity drifted"):
        verify_located_component_manifest(
            locator,
            canonical_json_bytes(_adapter().to_dict()),
            installed_distribution_name=manifest.identity.distribution_name,
            installed_distribution_version=manifest.identity.distribution_version,
        )
