from __future__ import annotations

from dataclasses import replace

import pytest

from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import AdapterManifest
from openzyme_extension_spi import AdapterRequirementMode
from openzyme_extension_spi import AdapterSelection
from openzyme_extension_spi import CapabilityProvision
from openzyme_extension_spi import CapabilityRequirement
from openzyme_extension_spi import CapabilityRequirementKind
from openzyme_extension_spi import ComponentIdentity
from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import CompositionManifestState
from openzyme_extension_spi import DistributionCompositionDocument
from openzyme_extension_spi import DistributionManifest
from openzyme_extension_spi import DriverManifest
from openzyme_extension_spi import DriverSelection
from openzyme_extension_spi import ExtensionManifestLocator
from openzyme_extension_spi import HttpMethod
from openzyme_extension_spi import HttpRouteContribution
from openzyme_extension_spi import KernelSelection
from openzyme_extension_spi import NamedContribution
from openzyme_extension_spi import PluginActivationState
from openzyme_extension_spi import PluginManifest
from openzyme_extension_spi import PluginRequirementMode
from openzyme_extension_spi import PluginSelection
from openzyme_extension_spi import QualificationSpec
from openzyme_extension_spi import RouteContribution
from openzyme_extension_spi import SelectedComponentPackage
from openzyme_extension_spi import ToolContribution
from openzyme_kernel import DeclaredToolEntry
from openzyme_kernel import KernelActivationIdentity
from openzyme_kernel import KernelContractError
from openzyme_kernel import activate_distribution_composition
from openzyme_kernel import select_distribution_manifest_locators


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


def _kernel_identity() -> KernelActivationIdentity:
    return KernelActivationIdentity(
        component_id="openzyme.kernel",
        distribution_name="openzyme-kernel",
        distribution_version="1.0.0",
        contract_digest=_digest("kernel-contract"),
        manifest_digest=_digest("kernel-manifest"),
    )


def _adapter(
    component_id: str = "openzyme.process.local",
    *,
    target_scoped: bool = False,
) -> AdapterManifest:
    return AdapterManifest(
        identity=_identity(component_id, ComponentKind.ADAPTER),
        required_contracts=("openzyme.contracts@1",),
        port_contracts=(
            NamedContribution(
                contribution_id="openzyme.process-isolation@1",
                contract_digest=_digest("process-port"),
            ),
        ),
        configuration_schema_digest=_digest(f"{component_id}:configuration"),
        preflight_contract_digest=_digest(f"{component_id}:preflight"),
        target_scoped=target_scoped,
    )


def _plugin(
    plugin_id: str = "openzyme.compute",
    *,
    resource_requirement: bool = False,
    contribution_id: str | None = None,
    state_namespace: str | None = None,
) -> PluginManifest:
    contribution_id = contribution_id or plugin_id
    requirements: tuple[CapabilityRequirement, ...] = ()
    if resource_requirement:
        requirements = (
            CapabilityRequirement(
                capability_id="software.compute",
                contract_spec="@1",
                kind=CapabilityRequirementKind.RESOURCE,
                version_spec=">=1,<2",
                operations=("run",),
            ),
        )
    tool = ToolContribution(
        owner_plugin_id=plugin_id,
        runtime_id=f"{plugin_id}.runtime",
        contract=ToolSpec(
            tool_name=f"{plugin_id}.run",
            description="Run one typed test operation.",
            input_schema={"type": "object", "additionalProperties": False},
            output_schema={"type": "object", "additionalProperties": False},
        ),
        requirements=requirements,
        requires_explicit_route=True,
    )
    named = NamedContribution(contribution_id, _digest(contribution_id))
    state_kwargs: dict[str, object] = {}
    if state_namespace is not None:
        state_kwargs = {
            "schemas": (named,),
            "migrations": (named,),
            "transaction_participants": (named,),
            "state_namespace": state_namespace,
            "migration_bundle_digest": _digest(f"{state_namespace}:migrations"),
        }
    qualification = QualificationSpec(
        qualification_spec_id=f"{plugin_id}.qualification@1",
        owner_plugin_id=plugin_id,
        capability_id="software.compute",
        contract_version="1",
        version_argv=("compute", "--version"),
        smoke_argv=("compute", "--smoke"),
        expected_result_schema={"type": "object", "additionalProperties": False},
    )
    return PluginManifest(
        identity=_identity(plugin_id, ComponentKind.PLUGIN),
        required_kernel_contract="openzyme.kernel@1",
        required_extension_spi_contract="openzyme.extension-spi@1",
        provides=(CapabilityProvision(plugin_id, "1", operations=("run",)),),
        requires=requirements,
        tools=(tool,),
        qualification_specs=(qualification,),
        routes=(
            RouteContribution(
                route_id=f"{plugin_id}.local-route",
                owner_component_id=plugin_id,
                capability_ids=(plugin_id,),
                route_kind="local",
                route_contract_digest=_digest(f"{plugin_id}:route"),
                driver_id=f"{plugin_id}.local-driver",
            ),
        ),
        projections=(named,),
        workers=(named,),
        finish_validators=(named,),
        **state_kwargs,
    )


def _driver(plugin_id: str = "openzyme.compute") -> DriverManifest:
    driver_id = f"{plugin_id}.local-driver"
    return DriverManifest(
        identity=_identity(driver_id, ComponentKind.DRIVER),
        owning_plugin_id=plugin_id,
        owning_plugin_contract=f"{plugin_id}@1",
        route_kind="local",
        required_port_contracts=("openzyme.process-isolation@1",),
        workload_contract_digest=_digest(f"{driver_id}:workload"),
        result_contract_digest=_digest(f"{driver_id}:result"),
    )


def _package_ref(
    selection_key: str,
    identity: ComponentIdentity,
    manifest_digest: str,
) -> SelectedComponentPackage:
    return SelectedComponentPackage(
        selection_key=selection_key,
        component_id=identity.component_id,
        component_kind=identity.component_kind,
        distribution_name=identity.distribution_name,
        distribution_version=identity.distribution_version,
        manifest_digest=manifest_digest,
    )


def _locator(
    manifest: AdapterManifest | PluginManifest | DriverManifest,
) -> ExtensionManifestLocator:
    identity = manifest.identity
    return ExtensionManifestLocator(
        component_id=identity.component_id,
        component_kind=identity.component_kind,
        distribution_name=identity.distribution_name,
        distribution_version=identity.distribution_version,
        resource_package=identity.component_id.replace(".", "_"),
        resource_name=f"manifests/{identity.component_kind.value}.json",
        manifest_digest=manifest.manifest_digest,
    )


def _document(
    *,
    adapters: tuple[tuple[AdapterSelection, AdapterManifest], ...] = (),
    plugins: tuple[
        tuple[PluginSelection, PluginManifest], ...
    ] = (),
    drivers: tuple[tuple[DriverSelection, DriverManifest], ...] = (),
) -> DistributionCompositionDocument:
    kernel = _kernel_identity()
    manifest = DistributionManifest(
        identity=_identity("test.distribution", ComponentKind.DISTRIBUTION),
        kernel=KernelSelection(
            contract_id="openzyme.kernel@1",
            contract_digest=kernel.contract_digest,
            implementation_component_id=kernel.component_id,
            implementation_manifest_digest=kernel.manifest_digest,
        ),
        adapters=tuple(selection for selection, _ in adapters),
        plugins=tuple(selection for selection, _ in plugins),
        drivers=tuple(selection for selection, _ in drivers),
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
        )
    ]
    refs.extend(
        _package_ref(
            f"adapter:{selection.selection_key}",
            adapter.identity,
            adapter.manifest_digest,
        )
        for selection, adapter in adapters
    )
    refs.extend(
        _package_ref(
            f"plugin:{selection.plugin_id}",
            plugin.identity,
            plugin.manifest_digest,
        )
        for selection, plugin in plugins
    )
    refs.extend(
        _package_ref(
            f"driver:{selection.selection_key}",
            driver.identity,
            driver.manifest_digest,
        )
        for selection, driver in drivers
    )
    return DistributionCompositionDocument(
        manifest_state=CompositionManifestState.ACTIVE,
        manifest=manifest,
        selected_packages=tuple(refs),
        ambient_discovery_enables_components=False,
        session_hot_swap=False,
    )


def _selection(
    plugin: PluginManifest,
    *,
    mode: PluginRequirementMode = PluginRequirementMode.REQUIRED,
) -> PluginSelection:
    return PluginSelection(
        plugin_id=plugin.identity.component_id,
        manifest_digest=plugin.manifest_digest,
        requirement_mode=mode,
    )


def _driver_selection(driver: DriverManifest) -> DriverSelection:
    return DriverSelection(
        slot_id=f"{driver.owning_plugin_id}:local",
        driver_id=driver.identity.component_id,
        owning_plugin_id=driver.owning_plugin_id,
        manifest_digest=driver.manifest_digest,
    )


def test_distribution_activation_builds_independent_deterministic_catalogs() -> None:
    adapter = _adapter()
    adapter_selection = AdapterSelection(
        slot_id="process.isolation",
        adapter_component_id=adapter.identity.component_id,
        manifest_digest=adapter.manifest_digest,
    )
    plugin = _plugin(state_namespace="openzyme.compute")
    driver = _driver()
    document = _document(
        adapters=((adapter_selection, adapter),),
        plugins=((_selection(plugin), plugin),),
        drivers=((_driver_selection(driver), driver),),
    )
    ambient = _adapter("ambient.adapter")
    kernel_tool = DeclaredToolEntry(
        owner_component_id="openzyme.kernel",
        runtime_id="openzyme.kernel.capabilities.inspect",
        contract=ToolSpec(
            tool_name="capabilities.inspect",
            description="Inspect effective capabilities.",
            input_schema={"type": "object", "additionalProperties": False},
            output_schema={"type": "object", "additionalProperties": False},
        ),
    )

    first = activate_distribution_composition(
        document,
        kernel_identity=_kernel_identity(),
        located_manifests={
            ambient.identity.component_id: ambient,
            driver.identity.component_id: driver,
            plugin.identity.component_id: plugin,
            adapter.identity.component_id: adapter,
        },
        kernel_tools=(kernel_tool,),
    )
    second = activate_distribution_composition(
        document,
        kernel_identity=_kernel_identity(),
        located_manifests={
            adapter.identity.component_id: adapter,
            plugin.identity.component_id: plugin,
            driver.identity.component_id: driver,
            ambient.identity.component_id: ambient,
        },
        kernel_tools=(kernel_tool,),
    )

    assert first.activation_digest == second.activation_digest
    assert first.ignored_component_ids == ("ambient.adapter",)
    assert first.adapters[0].selection.slot_id == "process.isolation"
    assert first.drivers[0].manifest.owning_plugin_id == "openzyme.compute"
    assert first.plugins.activation_for("openzyme.compute").state is (
        PluginActivationState.ACTIVE
    )
    assert [
        entry.contract.tool_name for entry in first.declared_tool_catalog.entries
    ] == ["capabilities.inspect", "openzyme.compute.run"]
    assert len(first.route_catalog.routes) == 1
    assert len(first.contribution_catalogs.projection.entries) == 1
    assert len(first.contribution_catalogs.worker.entries) == 1
    assert len(first.contribution_catalogs.finish_validator.entries) == 1
    assert len(first.contribution_catalogs.schema.entries) == 1
    assert len(first.contribution_catalogs.migration.entries) == 1
    assert len(first.contribution_catalogs.transaction_participant.entries) == 1
    assert len(first.contribution_catalogs.qualification.entries) == 1


def test_locator_selection_is_exact_and_ambient_packages_are_not_loaded() -> None:
    adapter = _adapter()
    selection = AdapterSelection(
        slot_id="process.isolation",
        adapter_component_id=adapter.identity.component_id,
        manifest_digest=adapter.manifest_digest,
    )
    optional = replace(_plugin("optional.plugin"), routes=())
    document = _document(
        adapters=((selection, adapter),),
        plugins=(
            (
                _selection(optional, mode=PluginRequirementMode.OPTIONAL),
                optional,
            ),
        ),
    )
    ambient = _adapter("ambient.adapter")

    selected = select_distribution_manifest_locators(
        document,
        (_locator(ambient), _locator(adapter)),
    )

    assert [item.component_id for item in selected.selected] == [
        "openzyme.process.local"
    ]
    assert selected.ignored_component_ids == ("ambient.adapter",)
    assert selected.selection_digest.startswith("sha256:")

    with pytest.raises(KernelContractError) as missing:
        select_distribution_manifest_locators(document, (_locator(ambient),))
    assert missing.value.code == "required_component_locator_missing"

    drifted = replace(
        _locator(adapter),
        distribution_version="2.0.0",
    )
    with pytest.raises(KernelContractError) as drift:
        select_distribution_manifest_locators(document, (drifted,))
    assert drift.value.code == "extension_locator_identity_drift"


def test_target_scoped_adapter_selection_is_bound_by_exact_slot_and_target() -> None:
    adapter = _adapter("openzyme.hpc.ssh", target_scoped=True)
    first_selection = AdapterSelection(
        slot_id="hpc.workspace",
        target_id="hpc-primary",
        adapter_component_id=adapter.identity.component_id,
        manifest_digest=adapter.manifest_digest,
    )
    second_selection = replace(first_selection, target_id="hpc-secondary")
    document = _document(
        adapters=((first_selection, adapter), (second_selection, adapter)),
    )

    activated = activate_distribution_composition(
        document,
        kernel_identity=_kernel_identity(),
        located_manifests={adapter.identity.component_id: adapter},
    )

    assert [item.selection.target_id for item in activated.adapters] == [
        "hpc-primary",
        "hpc-secondary",
    ]
    one_target = _document(adapters=((first_selection, adapter),))
    single = activate_distribution_composition(
        one_target,
        kernel_identity=_kernel_identity(),
        located_manifests={adapter.identity.component_id: adapter},
    )
    assert activated.adapter_bundle_digest != single.adapter_bundle_digest


def test_optional_absent_is_inactive_and_its_driver_does_not_mount() -> None:
    adapter = _adapter()
    adapter_selection = AdapterSelection(
        slot_id="process.isolation",
        adapter_component_id=adapter.identity.component_id,
        manifest_digest=adapter.manifest_digest,
    )
    plugin = _plugin("optional.compute")
    driver = _driver("optional.compute")
    document = _document(
        adapters=((adapter_selection, adapter),),
        plugins=((_selection(plugin, mode=PluginRequirementMode.OPTIONAL), plugin),),
        drivers=((_driver_selection(driver), driver),),
    )

    activated = activate_distribution_composition(
        document,
        kernel_identity=_kernel_identity(),
        located_manifests={adapter.identity.component_id: adapter},
    )

    optional = activated.plugins.activation_for("optional.compute")
    assert optional is not None
    assert optional.state is PluginActivationState.INACTIVE
    assert activated.drivers == ()
    assert activated.route_catalog.routes == ()


def test_resource_requirement_degrades_but_keeps_declared_contracts() -> None:
    plugin = _plugin("resource.plugin", resource_requirement=True)
    driverless = replace(plugin, routes=())
    document = _document(plugins=((_selection(driverless), driverless),))

    activated = activate_distribution_composition(
        document,
        kernel_identity=_kernel_identity(),
        located_manifests={driverless.identity.component_id: driverless},
    )

    state = activated.plugins.activation_for("resource.plugin")
    assert state is not None
    assert state.state is PluginActivationState.DEGRADED
    assert state.blockers[0].code == "resource_capability_unbound"
    assert activated.declared_tool_catalog.get("resource.plugin.run") is not None


def test_required_missing_optional_integrity_and_target_scope_fail_closed() -> None:
    required = _plugin("required.plugin")
    required = replace(required, routes=())
    missing_document = _document(plugins=((_selection(required), required),))
    with pytest.raises(KernelContractError) as missing:
        activate_distribution_composition(
            missing_document,
            kernel_identity=_kernel_identity(),
            located_manifests={},
        )
    assert missing.value.code == "required_plugin_missing"

    optional_adapter = _adapter()
    optional_adapter_selection = AdapterSelection(
        slot_id="research.provider",
        adapter_component_id=optional_adapter.identity.component_id,
        manifest_digest=optional_adapter.manifest_digest,
        requirement_mode=AdapterRequirementMode.OPTIONAL,
    )
    optional_adapter_document = _document(
        adapters=((optional_adapter_selection, optional_adapter),)
    )
    activated_without_optional_adapter = activate_distribution_composition(
        optional_adapter_document,
        kernel_identity=_kernel_identity(),
        located_manifests={},
    )
    assert activated_without_optional_adapter.adapters == ()

    expected_optional = replace(_plugin("optional.plugin"), routes=())
    optional_document = _document(
        plugins=(
            (
                _selection(
                    expected_optional,
                    mode=PluginRequirementMode.OPTIONAL,
                ),
                expected_optional,
            ),
        ),
    )
    observed_optional = replace(
        expected_optional,
        configuration_schema_digest=_digest("drifted-configuration"),
    )
    with pytest.raises(KernelContractError) as optional_drift:
        activate_distribution_composition(
            optional_document,
            kernel_identity=_kernel_identity(),
            located_manifests={
                observed_optional.identity.component_id: observed_optional
            },
        )
    assert optional_drift.value.code == "selected_component_identity_drift"

    adapter = _adapter(target_scoped=False)
    selection = AdapterSelection(
        slot_id="process.isolation",
        target_id="target-one",
        adapter_component_id=adapter.identity.component_id,
        manifest_digest=adapter.manifest_digest,
    )
    target_document = _document(adapters=((selection, adapter),))
    with pytest.raises(KernelContractError) as target:
        activate_distribution_composition(
            target_document,
            kernel_identity=_kernel_identity(),
            located_manifests={adapter.identity.component_id: adapter},
        )
    assert target.value.code == "adapter_target_scope_mismatch"


def test_driver_requires_owner_contract_port_and_route() -> None:
    adapter = _adapter()
    adapter_selection = AdapterSelection(
        slot_id="process.isolation",
        adapter_component_id=adapter.identity.component_id,
        manifest_digest=adapter.manifest_digest,
    )
    plugin = _plugin()
    driver = _driver()

    def activate(candidate: DriverManifest) -> None:
        document = _document(
            adapters=((adapter_selection, adapter),),
            plugins=((_selection(plugin), plugin),),
            drivers=((_driver_selection(candidate), candidate),),
        )
        activate_distribution_composition(
            document,
            kernel_identity=_kernel_identity(),
            located_manifests={
                adapter.identity.component_id: adapter,
                plugin.identity.component_id: plugin,
                candidate.identity.component_id: candidate,
            },
        )

    with pytest.raises(KernelContractError) as owner:
        activate(replace(driver, owning_plugin_contract="wrong.contract@1"))
    assert owner.value.code == "driver_owner_contract_mismatch"

    with pytest.raises(KernelContractError) as port:
        activate(
            replace(
                driver,
                required_port_contracts=("openzyme.unselected-port@1",),
            )
        )
    assert port.value.code == "driver_port_contract_unsatisfied"

    with pytest.raises(KernelContractError) as route:
        activate(replace(driver, route_kind="remote"))
    assert route.value.code == "driver_route_missing"


def test_projection_and_migration_namespace_collisions_reject_whole_activation() -> None:
    first = replace(_plugin("first.plugin"), routes=())
    second = replace(_plugin("second.plugin"), routes=())
    shared = NamedContribution("shared.projection@1", _digest("shared-projection"))
    first_projection = replace(first, projections=(shared,))
    second_projection = replace(second, projections=(shared,))
    projection_document = _document(
        plugins=(
            (_selection(first_projection), first_projection),
            (_selection(second_projection), second_projection),
        )
    )
    with pytest.raises(KernelContractError) as projection:
        activate_distribution_composition(
            projection_document,
            kernel_identity=_kernel_identity(),
            located_manifests={
                first_projection.identity.component_id: first_projection,
                second_projection.identity.component_id: second_projection,
            },
        )
    assert projection.value.code == "projection_catalog_collision"

    first_state = replace(
        first,
        state_namespace="shared.state",
        migration_bundle_digest=_digest("first-migrations"),
    )
    second_state = replace(
        second,
        state_namespace="shared.state",
        migration_bundle_digest=_digest("second-migrations"),
    )
    namespace_document = _document(
        plugins=(
            (_selection(first_state), first_state),
            (_selection(second_state), second_state),
        )
    )
    with pytest.raises(KernelContractError) as namespace:
        activate_distribution_composition(
            namespace_document,
            kernel_identity=_kernel_identity(),
            located_manifests={
                first_state.identity.component_id: first_state,
                second_state.identity.component_id: second_state,
            },
        )
    assert namespace.value.code == "migration_namespace_collision"


def test_normalized_http_method_path_and_cross_catalog_route_ids_are_unique() -> None:
    first = replace(
        _plugin("first.plugin"),
        routes=(),
        http_routes=(
            HttpRouteContribution(
                route_id="first.route@1",
                owner_plugin_id="first.plugin",
                method=HttpMethod.GET,
                path="/v3/shared/{item_id}",
                contract_digest=_digest("first-http"),
            ),
        ),
    )
    second = replace(
        _plugin("second.plugin"),
        routes=(),
        http_routes=(
            HttpRouteContribution(
                route_id="second.route@1",
                owner_plugin_id="second.plugin",
                method=HttpMethod.GET,
                path="/v3/shared/{item_id}/",
                contract_digest=_digest("second-http"),
            ),
        ),
    )
    document = _document(
        plugins=((_selection(first), first), (_selection(second), second))
    )

    with pytest.raises(KernelContractError) as collision:
        activate_distribution_composition(
            document,
            kernel_identity=_kernel_identity(),
            located_manifests={
                first.identity.component_id: first,
                second.identity.component_id: second,
            },
        )
    assert collision.value.code == "http_route_catalog_collision"

    capability_route = replace(
        _plugin("capability.plugin"),
        routes=(
            RouteContribution(
                route_id="shared.route@1",
                owner_component_id="capability.plugin",
                capability_ids=("capability.plugin",),
                route_kind="local",
                route_contract_digest=_digest("capability-route"),
            ),
        ),
        http_routes=(
            HttpRouteContribution(
                route_id="shared.route@1",
                owner_plugin_id="capability.plugin",
                method=HttpMethod.POST,
                path="/v3/capability",
                contract_digest=_digest("capability-http"),
            ),
        ),
    )
    cross_document = _document(
        plugins=((_selection(capability_route), capability_route),)
    )
    with pytest.raises(KernelContractError) as cross:
        activate_distribution_composition(
            cross_document,
            kernel_identity=_kernel_identity(),
            located_manifests={
                capability_route.identity.component_id: capability_route
            },
        )
    assert cross.value.code == "route_id_collision"


def test_scaffold_composition_never_activates() -> None:
    document = replace(
        _document(),
        manifest_state=CompositionManifestState.SCAFFOLD_NOT_ACTIVATABLE,
    )

    with pytest.raises(KernelContractError) as blocked:
        activate_distribution_composition(
            document,
            kernel_identity=_kernel_identity(),
            located_manifests={},
        )
    assert blocked.value.code == "distribution_not_activatable"
