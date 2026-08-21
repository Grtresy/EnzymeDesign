from __future__ import annotations

from dataclasses import replace
import importlib.metadata

import pytest

from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import AdapterManifest
from openzyme_extension_spi import AdapterSelection
from openzyme_extension_spi import CapabilityCardinality
from openzyme_extension_spi import CapabilityProvision
from openzyme_extension_spi import CapabilityRequirement
from openzyme_extension_spi import CapabilityRequirementKind
from openzyme_extension_spi import ComponentIdentity
from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import DistributionManifest
from openzyme_extension_spi import DriverSelection
from openzyme_extension_spi import HttpMethod
from openzyme_extension_spi import HttpRouteContribution
from openzyme_extension_spi import KernelSelection
from openzyme_extension_spi import NamedContribution
from openzyme_extension_spi import PluginManifest
from openzyme_extension_spi import PluginRequirementMode
from openzyme_extension_spi import PluginSelection
from openzyme_extension_spi import QualificationSpec
from openzyme_extension_spi import ToolContribution


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _identity(component_id: str, kind: ComponentKind) -> ComponentIdentity:
    return ComponentIdentity(
        component_id=component_id,
        component_kind=kind,
        component_version="1.0.0",
        distribution_name=component_id,
        distribution_version="1.0.0",
        build_digest=_digest(f"{component_id}:build"),
        contract_digest=_digest(f"{component_id}:contract"),
    )


def _kernel_selection() -> KernelSelection:
    return KernelSelection(
        contract_id="openzyme.kernel@1",
        contract_digest=_digest("kernel-contract"),
        implementation_component_id="openzyme.kernel",
        implementation_manifest_digest=_digest("kernel-manifest"),
    )


def _adapter_selection(slot_id: str, component_id: str) -> AdapterSelection:
    return AdapterSelection(
        slot_id=slot_id,
        adapter_component_id=component_id,
        manifest_digest=_digest(component_id),
    )


def test_spi_dependency_closure_is_contracts_only() -> None:
    requirements = (
        importlib.metadata.metadata("openzyme-extension-spi").get_all("Requires-Dist")
        or []
    )
    runtime_requirements = [
        requirement for requirement in requirements if "extra ==" not in requirement
    ]

    assert runtime_requirements == ["openzyme-contracts"]


def test_plugin_manifest_is_canonical_and_package_independent() -> None:
    hmmer_contract = ToolSpec(
        tool_name="enzymedesign.hmmer.search",
        description="Run a formal HMMER search.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        required_authorities=("external_compute",),
    )
    requirement_compute = CapabilityRequirement(
        capability_id="openzyme.execution.revision-job",
        contract_spec="@1",
    )
    requirement_hmmer = CapabilityRequirement(
        capability_id="software.hmmer",
        contract_spec="@1",
        kind=CapabilityRequirementKind.RESOURCE,
        version_spec=">=3.3,<4",
        operations=("hmmsearch",),
        same_target_as="openzyme.execution.revision-job",
    )
    qualification = QualificationSpec(
        qualification_spec_id="enzymedesign.hmmer.qualification@1",
        owner_plugin_id="enzymedesign.hmmer",
        capability_id="software.hmmer",
        contract_version="1",
        version_argv=("hmmsearch", "-h"),
        smoke_argv=("hmmsearch", "--help"),
        expected_result_schema={"type": "object"},
    )
    first = PluginManifest(
        identity=_identity("enzymedesign.hmmer", ComponentKind.PLUGIN),
        required_kernel_contract="openzyme.kernel@1",
        required_extension_spi_contract="openzyme.extension-spi@1",
        provides=(
            CapabilityProvision(
                capability_id="enzymedesign.hmmer",
                contract_version="1",
                cardinality=CapabilityCardinality.MULTI_ROUTE,
            ),
        ),
        requires=(requirement_hmmer, requirement_compute),
        tools=(
            ToolContribution(
                owner_plugin_id="enzymedesign.hmmer",
                runtime_id="enzymedesign.hmmer.runtime",
                contract=hmmer_contract,
                requirements=(requirement_hmmer, requirement_compute),
            ),
        ),
        qualification_specs=(qualification,),
    )
    second = PluginManifest(
        identity=_identity("enzymedesign.hmmer", ComponentKind.PLUGIN),
        required_kernel_contract="openzyme.kernel@1",
        required_extension_spi_contract="openzyme.extension-spi@1",
        provides=first.provides,
        requires=(requirement_compute, requirement_hmmer),
        tools=first.tools,
        qualification_specs=first.qualification_specs,
    )

    assert first.manifest_digest == second.manifest_digest
    assert "openzyme-hpc" not in str(first.to_dict())
    assert "slurm" not in str(first.to_dict()).lower()


def test_adapter_manifest_cannot_accept_plugin_tool_contributions() -> None:
    with pytest.raises(TypeError):
        AdapterManifest(
            identity=_identity("openzyme.store.sqlite", ComponentKind.ADAPTER),
            required_contracts=("openzyme.control-store@1",),
            port_contracts=(
                NamedContribution(
                    contribution_id="openzyme.control-store@1",
                    contract_digest=_digest("store-port"),
                ),
            ),
            configuration_schema_digest=_digest("store-config"),
            preflight_contract_digest=_digest("store-preflight"),
            tools=(),  # type: ignore[call-arg]
        )


def test_standard_distribution_can_require_zero_semantic_plugins() -> None:
    standard = DistributionManifest(
        identity=_identity("openzyme.standard", ComponentKind.DISTRIBUTION),
        kernel=_kernel_selection(),
        adapters=(
            _adapter_selection("kernel.store", "openzyme.store.sqlite"),
            _adapter_selection(
                "workspace.backend",
                "openzyme.workspace.git-lfs",
            ),
            _adapter_selection("agent.turn", "openzyme.runtime.openai"),
            _adapter_selection(
                "process.isolation",
                "openzyme.process.podman",
            ),
        ),
        plugins=(),
        drivers=(),
        delivery_surfaces=(
            NamedContribution(
                contribution_id="openzyme.host-api",
                contract_digest=_digest("host-api"),
            ),
        ),
    )

    assert standard.required_plugin_ids == ()
    assert standard.optional_plugin_ids == ()
    assert standard.manifest_digest.startswith("sha256:")


def test_distribution_rejects_ambiguous_adapter_slot() -> None:
    with pytest.raises(ValueError, match="one exact selected provider"):
        DistributionManifest(
            identity=_identity("openzyme.standard", ComponentKind.DISTRIBUTION),
            kernel=_kernel_selection(),
            adapters=(
                _adapter_selection("kernel.store", "openzyme.store.sqlite"),
                _adapter_selection("kernel.store", "openzyme.store.postgres"),
            ),
            plugins=(),
            drivers=(),
            delivery_surfaces=(),
        )


def test_distribution_rejects_driver_without_owning_plugin() -> None:
    with pytest.raises(ValueError, match="owning Plugin"):
        DistributionManifest(
            identity=_identity("enzymedesign", ComponentKind.DISTRIBUTION),
            kernel=_kernel_selection(),
            adapters=(),
            plugins=(
                PluginSelection(
                    plugin_id="openzyme.compute",
                    manifest_digest=_digest("compute"),
                    requirement_mode=PluginRequirementMode.REQUIRED,
                ),
            ),
            drivers=(
                DriverSelection(
                    slot_id="enzymedesign.hmmer:hpc-primary",
                    driver_id="enzymedesign.hmmer.hpc",
                    owning_plugin_id="enzymedesign.hmmer",
                    manifest_digest=_digest("hmmer-driver"),
                ),
            ),
            delivery_surfaces=(),
        )


def test_distribution_rejects_duplicate_driver_id_across_slots() -> None:
    plugin = PluginSelection(
        plugin_id="enzymedesign.hmmer",
        manifest_digest=_digest("hmmer"),
        requirement_mode=PluginRequirementMode.REQUIRED,
    )
    first = DriverSelection(
        slot_id="hmmer:hpc-primary",
        driver_id="enzymedesign.hmmer.hpc",
        owning_plugin_id=plugin.plugin_id,
        manifest_digest=_digest("hmmer-driver"),
    )
    with pytest.raises(ValueError, match="globally unique driver_id"):
        DistributionManifest(
            identity=_identity("enzymedesign", ComponentKind.DISTRIBUTION),
            kernel=_kernel_selection(),
            adapters=(),
            plugins=(plugin,),
            drivers=(first, replace(first, slot_id="hmmer:hpc-secondary")),
            delivery_surfaces=(),
        )


def test_plugin_manifest_rejects_duplicate_tool_names_and_wrong_owner() -> None:
    contract = ToolSpec(
        tool_name="openzyme.research.start",
        description="Start one bounded research operation.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )
    wrong_owner = ToolContribution(
        owner_plugin_id="other.plugin",
        runtime_id="openzyme.research.runtime",
        contract=contract,
    )

    with pytest.raises(ValueError, match="owned by"):
        PluginManifest(
            identity=_identity("openzyme.research", ComponentKind.PLUGIN),
            required_kernel_contract="openzyme.kernel@1",
            required_extension_spi_contract="openzyme.extension-spi@1",
            tools=(wrong_owner,),
        )

    contribution = ToolContribution(
        owner_plugin_id="openzyme.research",
        runtime_id="openzyme.research.runtime",
        contract=contract,
    )
    with pytest.raises(ValueError, match="unique canonical names"):
        PluginManifest(
            identity=_identity("openzyme.research", ComponentKind.PLUGIN),
            required_kernel_contract="openzyme.kernel@1",
            required_extension_spi_contract="openzyme.extension-spi@1",
            tools=(contribution, contribution),
        )


def test_plugin_state_contributions_require_one_explicit_namespace() -> None:
    schema = NamedContribution(
        contribution_id="openzyme.science.schema@1",
        contract_digest=_digest("science-schema"),
    )
    migration = NamedContribution(
        contribution_id="openzyme.science.migration.001",
        contract_digest=_digest("science-migration"),
    )
    participant = NamedContribution(
        contribution_id="openzyme.science.transaction-participant@1",
        contract_digest=_digest("science-participant"),
    )

    manifest = PluginManifest(
        identity=_identity("openzyme.science", ComponentKind.PLUGIN),
        required_kernel_contract="openzyme.kernel@1",
        required_extension_spi_contract="openzyme.extension-spi@1",
        schemas=(schema,),
        migrations=(migration,),
        transaction_participants=(participant,),
        state_namespace="openzyme.science",
        migration_bundle_digest=_digest("science-migrations"),
    )

    assert manifest.to_dict()["schemas"] == [schema.to_dict()]
    assert manifest.to_dict()["migrations"] == [migration.to_dict()]
    assert manifest.to_dict()["transaction_participants"] == [
        participant.to_dict()
    ]
    with pytest.raises(ValueError, match="state_namespace"):
        PluginManifest(
            identity=_identity("openzyme.science", ComponentKind.PLUGIN),
            required_kernel_contract="openzyme.kernel@1",
            required_extension_spi_contract="openzyme.extension-spi@1",
            schemas=(schema,),
        )


def test_plugin_manifest_rejects_unknown_unbounded_hook() -> None:
    with pytest.raises(TypeError):
        PluginManifest(
            identity=_identity("openzyme.research", ComponentKind.PLUGIN),
            required_kernel_contract="openzyme.kernel@1",
            required_extension_spi_contract="openzyme.extension-spi@1",
            on_any_event=lambda _event: None,  # type: ignore[call-arg]
        )


def test_plugin_tools_are_dotted_and_http_routes_are_normalized() -> None:
    with pytest.raises(ValueError, match="dotted"):
        ToolContribution(
            owner_plugin_id="openzyme.research",
            runtime_id="openzyme.research.runtime",
            contract=ToolSpec(
                tool_name="research",
                description="Invalid undotted canonical name.",
                input_schema={"type": "object"},
            ),
        )

    route = HttpRouteContribution(
        route_id="openzyme.research.status-route@1",
        owner_plugin_id="openzyme.research",
        method=HttpMethod.GET,
        path="/v3/research/{invocation_id}/",
        contract_digest=_digest("research-http-route"),
    )
    manifest = PluginManifest(
        identity=_identity("openzyme.research", ComponentKind.PLUGIN),
        required_kernel_contract="openzyme.kernel@1",
        required_extension_spi_contract="openzyme.extension-spi@1",
        http_routes=(route,),
    )

    assert manifest.http_routes[0].path == "/v3/research/{invocation_id}"
    assert manifest.http_routes[0].route_key == (
        "GET /v3/research/{invocation_id}"
    )
    with pytest.raises(ValueError, match="non-canonical"):
        HttpRouteContribution(
            route_id="invalid.route@1",
            owner_plugin_id="openzyme.research",
            method=HttpMethod.GET,
            path="/v3//research",
            contract_digest=_digest("invalid-route"),
        )
