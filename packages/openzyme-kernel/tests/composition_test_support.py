from __future__ import annotations

from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import AdapterManifest
from openzyme_extension_spi import AdapterSelection
from openzyme_extension_spi import CapabilityProvision
from openzyme_extension_spi import ComponentIdentity
from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import CompositionManifestState
from openzyme_extension_spi import DistributionCompositionDocument
from openzyme_extension_spi import DistributionManifest
from openzyme_extension_spi import DriverManifest
from openzyme_extension_spi import DriverSelection
from openzyme_extension_spi import HttpMethod
from openzyme_extension_spi import HttpRouteContribution
from openzyme_extension_spi import KernelSelection
from openzyme_extension_spi import NamedContribution
from openzyme_extension_spi import PluginManifest
from openzyme_extension_spi import PluginRequirementMode
from openzyme_extension_spi import PluginSelection
from openzyme_extension_spi import RouteContribution
from openzyme_extension_spi import SelectedComponentPackage
from openzyme_extension_spi import ToolContribution
from openzyme_kernel import ActivatedDistributionComposition
from openzyme_kernel import DeploymentActivationCoordinator
from openzyme_kernel import DeploymentActivationGate
from openzyme_kernel import DeploymentActivationRequest
from openzyme_kernel import DeploymentVerificationKind
from openzyme_kernel import KernelActivationIdentity
from openzyme_kernel import ReadOnlyDeploymentVerification
from openzyme_kernel import activate_distribution_composition


def digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def identity(component_id: str, kind: ComponentKind) -> ComponentIdentity:
    return ComponentIdentity(
        component_id=component_id,
        component_kind=kind,
        component_version="1.0.0",
        distribution_name=component_id.replace(".", "-"),
        distribution_version="1.0.0",
        build_digest=digest(f"{component_id}:build"),
        contract_digest=digest(f"{component_id}:contract"),
    )


def activated_composition(
    *,
    include_plugin: bool = True,
) -> tuple[
    ActivatedDistributionComposition,
    LayeredReleaseIdentity,
    PluginManifest | None,
]:
    kernel = KernelActivationIdentity(
        component_id="openzyme.kernel",
        distribution_name="openzyme-kernel",
        distribution_version="1.0.0",
        contract_digest=digest("kernel-contract"),
        manifest_digest=digest("kernel-manifest"),
    )
    adapter = AdapterManifest(
        identity=identity("openzyme.workspace.git.lfs", ComponentKind.ADAPTER),
        required_contracts=("openzyme.contracts@1",),
        port_contracts=(
            NamedContribution(
                "openzyme.workspace-revision-backend@1",
                digest("workspace-port"),
            ),
        ),
        configuration_schema_digest=digest("workspace-config"),
        preflight_contract_digest=digest("workspace-preflight"),
    )
    adapter_selection = AdapterSelection(
        slot_id="workspace.backend",
        adapter_component_id=adapter.identity.component_id,
        manifest_digest=adapter.manifest_digest,
    )
    plugin = _plugin() if include_plugin else None
    driver = _driver() if include_plugin else None
    plugin_selections = (
        ()
        if plugin is None
        else (
            PluginSelection(
                plugin_id=plugin.identity.component_id,
                manifest_digest=plugin.manifest_digest,
                requirement_mode=PluginRequirementMode.REQUIRED,
            ),
        )
    )
    driver_selections = (
        ()
        if driver is None
        else (
            DriverSelection(
                slot_id="test.plugin:local",
                driver_id=driver.identity.component_id,
                owning_plugin_id=plugin.identity.component_id,
                manifest_digest=driver.manifest_digest,
            ),
        )
    )
    distribution = DistributionManifest(
        identity=identity("test.distribution", ComponentKind.DISTRIBUTION),
        kernel=KernelSelection(
            contract_id="openzyme.kernel@1",
            contract_digest=kernel.contract_digest,
            implementation_component_id=kernel.component_id,
            implementation_manifest_digest=kernel.manifest_digest,
        ),
        adapters=(adapter_selection,),
        plugins=plugin_selections,
        drivers=driver_selections,
        delivery_surfaces=(),
    )
    refs = [
        SelectedComponentPackage(
            selection_key="kernel",
            component_id=kernel.component_id,
            component_kind=ComponentKind.KERNEL,
            distribution_name=kernel.distribution_name,
            distribution_version=kernel.distribution_version,
            manifest_digest=kernel.manifest_digest,
        ),
        SelectedComponentPackage(
            selection_key=f"adapter:{adapter_selection.selection_key}",
            component_id=adapter.identity.component_id,
            component_kind=ComponentKind.ADAPTER,
            distribution_name=adapter.identity.distribution_name,
            distribution_version=adapter.identity.distribution_version,
            manifest_digest=adapter.manifest_digest,
        ),
    ]
    manifests: dict[str, AdapterManifest | PluginManifest | DriverManifest] = {
        adapter.identity.component_id: adapter,
    }
    if plugin is not None and driver is not None:
        refs.extend(
            (
                SelectedComponentPackage(
                    selection_key=f"plugin:{plugin.identity.component_id}",
                    component_id=plugin.identity.component_id,
                    component_kind=ComponentKind.PLUGIN,
                    distribution_name=plugin.identity.distribution_name,
                    distribution_version=plugin.identity.distribution_version,
                    manifest_digest=plugin.manifest_digest,
                ),
                SelectedComponentPackage(
                    selection_key=f"driver:{driver_selections[0].selection_key}",
                    component_id=driver.identity.component_id,
                    component_kind=ComponentKind.DRIVER,
                    distribution_name=driver.identity.distribution_name,
                    distribution_version=driver.identity.distribution_version,
                    manifest_digest=driver.manifest_digest,
                ),
            )
        )
        manifests[plugin.identity.component_id] = plugin
        manifests[driver.identity.component_id] = driver
    document = DistributionCompositionDocument(
        manifest_state=CompositionManifestState.ACTIVE,
        manifest=distribution,
        selected_packages=tuple(refs),
        ambient_discovery_enables_components=False,
        session_hot_swap=False,
    )
    composition = activate_distribution_composition(
        document,
        kernel_identity=kernel,
        located_manifests=manifests,
    )
    release = LayeredReleaseIdentity(
        kernel_contract_digest=kernel.contract_digest,
        core_schema_digest=digest("core-schema"),
        adapter_bundle_digest=composition.adapter_bundle_digest,
        extension_bundle_digest=composition.plugins.extension_bundle_digest,
        declared_tool_catalog_digest=composition.declared_tool_catalog.catalog_digest,
        route_catalog_digest=composition.route_catalog.catalog_digest,
        projection_catalog_digest=(
            composition.contribution_catalogs.projection.catalog_digest
        ),
        migration_catalog_digest=(
            composition.contribution_catalogs.migration.catalog_digest
        ),
        workspace_backend_digest=adapter.manifest_digest,
        host_build_digest=digest("host-build"),
        client_build_digest=digest("client-build"),
    )
    return composition, release, plugin


def activate_gate(
    composition: ActivatedDistributionComposition,
    release: LayeredReleaseIdentity,
    *,
    epoch_id: str = "deployment-epoch-1",
) -> tuple[DeploymentActivationGate, object]:
    gate = DeploymentActivationGate()
    wheel_digest = digest("wheel-set")
    proofs = tuple(
        ReadOnlyDeploymentVerification.create(
            verification_id=f"verify-{kind.value}",
            verification_kind=kind,
            verifier_id="test-verifier",
            expected_digest=expected,
            observed_digest=expected,
            verified_at="2026-08-19T00:00:00+00:00",
        )
        for kind, expected in (
            (DeploymentVerificationKind.COMPOSITION, composition.activation_digest),
            (DeploymentVerificationKind.CORE_SCHEMA, release.core_schema_digest),
            (DeploymentVerificationKind.INSTALLED_WHEELS, wheel_digest),
        )
    )
    epoch = DeploymentActivationCoordinator(gate).activate(
        composition=composition,
        release_identity=release,
        request=DeploymentActivationRequest(
            epoch_id=epoch_id,
            sequence=1,
            expected_wheel_set_digest=wheel_digest,
            activated_by_actor_id="operator-1",
            activated_at="2026-08-19T00:00:00+00:00",
            verifications=proofs,
        ),
    )
    return gate, epoch


def _plugin() -> PluginManifest:
    plugin_id = "test.plugin"
    return PluginManifest(
        identity=identity(plugin_id, ComponentKind.PLUGIN),
        required_kernel_contract="openzyme.kernel@1",
        required_extension_spi_contract="openzyme.extension-spi@1",
        provides=(CapabilityProvision("test.capability", "1", operations=("run",)),),
        tools=(
            ToolContribution(
                owner_plugin_id=plugin_id,
                runtime_id="test.plugin.tool-runtime",
                contract=ToolSpec(
                    tool_name="test.plugin.run",
                    description="Run the test Plugin.",
                    input_schema={"type": "object", "additionalProperties": False},
                    output_schema={"type": "object", "additionalProperties": False},
                ),
                requires_explicit_route=True,
            ),
        ),
        routes=(
            RouteContribution(
                route_id="test.plugin.local-route",
                owner_component_id=plugin_id,
                capability_ids=("test.capability",),
                route_kind="local",
                route_contract_digest=digest("route-contract"),
                driver_id="test.plugin.local-driver",
            ),
        ),
        http_routes=(
            HttpRouteContribution(
                route_id="test.plugin.http-route",
                owner_plugin_id=plugin_id,
                method=HttpMethod.GET,
                path="/v3/extensions/test-plugin",
                contract_digest=digest("http-route-contract"),
            ),
        ),
        projections=(NamedContribution("test.plugin.projection", digest("projection")),),
        workers=(NamedContribution("test.plugin.worker", digest("worker")),),
        finish_validators=(
            NamedContribution("test.plugin.validator", digest("validator")),
        ),
        schemas=(NamedContribution("test.plugin.schema", digest("schema")),),
        migrations=(
            NamedContribution("test.plugin.migration", digest("migration")),
        ),
        transaction_participants=(
            NamedContribution("test.plugin.participant", digest("participant")),
        ),
        state_namespace="test_plugin",
        migration_bundle_digest=digest("migration-bundle"),
    )


def _driver() -> DriverManifest:
    return DriverManifest(
        identity=identity("test.plugin.local-driver", ComponentKind.DRIVER),
        owning_plugin_id="test.plugin",
        owning_plugin_contract="test.capability@1",
        route_kind="local",
        required_port_contracts=("openzyme.workspace-revision-backend@1",),
        workload_contract_digest=digest("driver-workload"),
        result_contract_digest=digest("driver-result"),
    )


__all__ = ["activate_gate", "activated_composition", "digest"]
