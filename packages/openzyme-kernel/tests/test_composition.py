from __future__ import annotations

from dataclasses import replace
import importlib.metadata

import pytest

from openzyme_contracts import ToolSpec
from openzyme_contracts import ResourceCapabilityFact
from openzyme_contracts import ResourceCapabilityKind
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import TargetInventoryBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import CapabilityProvision
from openzyme_extension_spi import CapabilityRequirement
from openzyme_extension_spi import CapabilityRequirementKind
from openzyme_extension_spi import ComponentIdentity
from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import DistributionManifest
from openzyme_extension_spi import KernelSelection
from openzyme_extension_spi import PluginActivationState
from openzyme_extension_spi import PluginManifest
from openzyme_extension_spi import PluginRequirementMode
from openzyme_extension_spi import PluginSelection
from openzyme_extension_spi import NamedContribution
from openzyme_extension_spi import QualificationSpec
from openzyme_extension_spi import RouteContribution
from openzyme_extension_spi import ToolContribution
from openzyme_kernel import KernelContractError
from openzyme_kernel import CapabilityRegistry
from openzyme_kernel import ExtensionBundleRegistry
from openzyme_kernel import activate_plugin_composition
from openzyme_kernel import build_declared_tool_catalog
from openzyme_kernel import build_route_catalog


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


def _plugin(
    plugin_id: str,
    *,
    provides: tuple[CapabilityProvision, ...] = (),
    requires: tuple[CapabilityRequirement, ...] = (),
    tools: tuple[ToolContribution, ...] = (),
) -> PluginManifest:
    return PluginManifest(
        identity=_identity(plugin_id, ComponentKind.PLUGIN),
        required_kernel_contract="openzyme.kernel@1",
        required_extension_spi_contract="openzyme.extension-spi@1",
        provides=provides,
        requires=requires,
        tools=tools,
    )


def _distribution(
    selections: tuple[PluginSelection, ...],
) -> DistributionManifest:
    return DistributionManifest(
        identity=_identity("test.distribution", ComponentKind.DISTRIBUTION),
        kernel=KernelSelection(
            contract_id="openzyme.kernel@1",
            contract_digest=_digest("kernel"),
            implementation_component_id="openzyme.kernel",
            implementation_manifest_digest=_digest("kernel-manifest"),
        ),
        adapters=(),
        plugins=selections,
        drivers=(),
        delivery_surfaces=(),
    )


def _selection(
    manifest: PluginManifest,
    *,
    mode: PluginRequirementMode = PluginRequirementMode.REQUIRED,
) -> PluginSelection:
    return PluginSelection(
        plugin_id=manifest.identity.component_id,
        manifest_digest=manifest.manifest_digest,
        requirement_mode=mode,
    )


def test_kernel_wheel_runtime_dependencies_are_contracts_and_spi_only() -> None:
    requirements = (
        importlib.metadata.metadata("openzyme-kernel").get_all("Requires-Dist") or []
    )
    runtime_requirements = sorted(
        requirement for requirement in requirements if "extra ==" not in requirement
    )

    assert runtime_requirements == [
        "openzyme-contracts",
        "openzyme-extension-spi",
        "openzyme-runtime-spi",
    ]


def test_optional_absence_is_inactive_and_unlisted_manifest_is_ignored() -> None:
    optional = _plugin("openzyme.research")
    ambient = _plugin("ambient.plugin")
    composition = activate_plugin_composition(
        _distribution((_selection(optional, mode=PluginRequirementMode.OPTIONAL),)),
        located_plugin_manifests={"ambient.plugin": ambient},
    )

    activation = composition.activation_for("openzyme.research")
    assert activation is not None
    assert activation.state is PluginActivationState.INACTIVE
    assert composition.contributing_manifests == ()
    assert composition.ignored_component_ids == ("ambient.plugin",)


def test_required_absence_and_optional_integrity_drift_both_fail() -> None:
    plugin = _plugin("openzyme.research")
    required_distribution = _distribution((_selection(plugin),))
    with pytest.raises(KernelContractError) as missing:
        activate_plugin_composition(
            required_distribution,
            located_plugin_manifests={},
        )
    assert missing.value.code == "required_plugin_missing"
    assert missing.value.mutation_applied is False

    optional_selection = PluginSelection(
        plugin_id=plugin.identity.component_id,
        manifest_digest=_digest("wrong-manifest"),
        requirement_mode=PluginRequirementMode.OPTIONAL,
    )
    with pytest.raises(KernelContractError) as drift:
        activate_plugin_composition(
            _distribution((optional_selection,)),
            located_plugin_manifests={plugin.identity.component_id: plugin},
        )
    assert drift.value.code == "plugin_manifest_digest_mismatch"


def test_semantic_dependency_missing_fails_and_cycle_fails() -> None:
    consumer = _plugin(
        "consumer.plugin",
        requires=(
            CapabilityRequirement(
                capability_id="missing.capability",
                contract_spec="@1",
            ),
        ),
    )
    with pytest.raises(KernelContractError) as missing:
        activate_plugin_composition(
            _distribution((_selection(consumer),)),
            located_plugin_manifests={consumer.identity.component_id: consumer},
        )
    assert missing.value.code == "plugin_dependency_unsatisfied"

    first = _plugin(
        "first.plugin",
        provides=(CapabilityProvision("capability.first", "1"),),
        requires=(CapabilityRequirement("capability.second", "@1"),),
    )
    second = _plugin(
        "second.plugin",
        provides=(CapabilityProvision("capability.second", "1"),),
        requires=(CapabilityRequirement("capability.first", "@1"),),
    )
    with pytest.raises(KernelContractError) as cycle:
        activate_plugin_composition(
            _distribution((_selection(first), _selection(second))),
            located_plugin_manifests={
                first.identity.component_id: first,
                second.identity.component_id: second,
            },
        )
    assert cycle.value.code == "capability_dependency_cycle"

    third = _plugin(
        "third.plugin",
        provides=(CapabilityProvision("capability.third", "1"),),
        requires=(CapabilityRequirement("capability.first", "@1"),),
    )
    first_transitive = replace(
        first,
        requires=(CapabilityRequirement("capability.second", "@1"),),
    )
    second_transitive = replace(
        second,
        requires=(CapabilityRequirement("capability.third", "@1"),),
    )
    with pytest.raises(KernelContractError) as transitive:
        activate_plugin_composition(
            _distribution(
                (
                    _selection(first_transitive),
                    _selection(second_transitive),
                    _selection(third),
                )
            ),
            located_plugin_manifests={
                item.identity.component_id: item
                for item in (first_transitive, second_transitive, third)
            },
        )
    assert transitive.value.code == "capability_dependency_cycle"


def test_same_target_constraint_must_reference_another_declared_requirement() -> None:
    plugin = _plugin(
        "consumer.plugin",
        requires=(
            CapabilityRequirement(
                capability_id="software.hmmer",
                contract_spec="@1",
                kind=CapabilityRequirementKind.RESOURCE,
                version_spec=">=3.3,<4",
                same_target_as="openzyme.execution.revision-job",
            ),
        ),
    )

    with pytest.raises(KernelContractError) as invalid:
        activate_plugin_composition(
            _distribution((_selection(plugin),)),
            located_plugin_manifests={plugin.identity.component_id: plugin},
        )
    assert invalid.value.code == "same_target_requirement_missing"


def test_single_capability_provider_and_capability_route_ids_are_unique() -> None:
    first = _plugin(
        "first.plugin",
        provides=(CapabilityProvision("single.capability", "1"),),
    )
    second = _plugin(
        "second.plugin",
        provides=(CapabilityProvision("single.capability", "1"),),
    )
    with pytest.raises(KernelContractError) as provider:
        activate_plugin_composition(
            _distribution((_selection(first), _selection(second))),
            located_plugin_manifests={
                first.identity.component_id: first,
                second.identity.component_id: second,
            },
        )
    assert provider.value.code == "capability_provider_collision"

    route_id = "shared.route@1"
    first_route = replace(
        first,
        provides=(CapabilityProvision("first.capability", "1"),),
        routes=(
            RouteContribution(
                route_id=route_id,
                owner_component_id=first.identity.component_id,
                capability_ids=("first.capability",),
                route_kind="local",
                route_contract_digest=_digest("first-route"),
            ),
        ),
    )
    second_route = replace(
        second,
        provides=(CapabilityProvision("second.capability", "1"),),
        routes=(
            RouteContribution(
                route_id=route_id,
                owner_component_id=second.identity.component_id,
                capability_ids=("second.capability",),
                route_kind="local",
                route_contract_digest=_digest("second-route"),
            ),
        ),
    )
    composition = activate_plugin_composition(
        _distribution((_selection(first_route), _selection(second_route))),
        located_plugin_manifests={
            first_route.identity.component_id: first_route,
            second_route.identity.component_id: second_route,
        },
    )
    with pytest.raises(KernelContractError) as route:
        build_route_catalog(composition)
    assert route.value.code == "route_catalog_collision"


@pytest.mark.parametrize(
    ("attribute", "expected_code", "stateful"),
    (
        ("projections", "projection_catalog_collision", False),
        ("workers", "worker_catalog_collision", False),
        ("finish_validators", "finish_validator_catalog_collision", False),
        ("schemas", "schema_catalog_collision", True),
        ("migrations", "migration_catalog_collision", True),
        (
            "transaction_participants",
            "transaction_participant_catalog_collision",
            True,
        ),
    ),
)
def test_named_contribution_catalogs_fail_closed_on_global_collision(
    attribute: str,
    expected_code: str,
    stateful: bool,
) -> None:
    shared = NamedContribution("shared.contribution@1", _digest(attribute))
    first_kwargs: dict[str, object] = {attribute: (shared,)}
    second_kwargs: dict[str, object] = {attribute: (shared,)}
    if stateful:
        first_kwargs.update(
            state_namespace="first.state",
            migration_bundle_digest=_digest("first-state"),
        )
        second_kwargs.update(
            state_namespace="second.state",
            migration_bundle_digest=_digest("second-state"),
        )
    first = replace(_plugin("first.plugin"), **first_kwargs)
    second = replace(_plugin("second.plugin"), **second_kwargs)
    composition = activate_plugin_composition(
        _distribution((_selection(first), _selection(second))),
        located_plugin_manifests={
            first.identity.component_id: first,
            second.identity.component_id: second,
        },
    )
    from openzyme_kernel import build_extension_contribution_catalogs

    with pytest.raises(KernelContractError) as collision:
        build_extension_contribution_catalogs(composition)
    assert collision.value.code == expected_code


def test_qualification_ids_are_unique_across_plugins() -> None:
    qualification_id = "shared.qualification@1"

    def qualified(plugin_id: str) -> PluginManifest:
        return replace(
            _plugin(plugin_id),
            qualification_specs=(
                QualificationSpec(
                    qualification_spec_id=qualification_id,
                    owner_plugin_id=plugin_id,
                    capability_id=f"software.{plugin_id}",
                    contract_version="1",
                    version_argv=("tool", "--version"),
                    smoke_argv=("tool", "--smoke"),
                    expected_result_schema={"type": "object"},
                ),
            ),
        )

    first = qualified("first.plugin")
    second = qualified("second.plugin")
    composition = activate_plugin_composition(
        _distribution((_selection(first), _selection(second))),
        located_plugin_manifests={
            first.identity.component_id: first,
            second.identity.component_id: second,
        },
    )
    from openzyme_kernel import build_extension_contribution_catalogs

    with pytest.raises(KernelContractError) as collision:
        build_extension_contribution_catalogs(composition)
    assert collision.value.code == "qualification_catalog_collision"


def test_declared_tool_catalog_rejects_duplicate_names_without_override() -> None:
    contract = ToolSpec(
        tool_name="shared.tool",
        description="One canonical tool.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )
    first = _plugin(
        "first.plugin",
        tools=(ToolContribution("first.plugin", "first.runtime", contract),),
    )
    second = _plugin(
        "second.plugin",
        tools=(ToolContribution("second.plugin", "second.runtime", contract),),
    )
    composition = activate_plugin_composition(
        _distribution((_selection(first), _selection(second))),
        located_plugin_manifests={
            first.identity.component_id: first,
            second.identity.component_id: second,
        },
    )

    with pytest.raises(KernelContractError) as collision:
        build_declared_tool_catalog(kernel_tools=(), composition=composition)
    assert collision.value.code == "tool_catalog_collision"
    assert collision.value.details == {
        "first_owner_component_id": "first.plugin",
        "second_owner_component_id": "second.plugin",
        "tool_name": "shared.tool",
    }


def test_non_biological_code_review_plugin_activates_without_kernel_changes() -> None:
    contract = ToolSpec(
        tool_name="software.review.inspect",
        description="Inspect one immutable software revision without mutating it.",
        input_schema={
            "type": "object",
            "properties": {
                "revision_ref": {"type": "string", "minLength": 1},
            },
            "required": ["revision_ref"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"finding_count": {"type": "integer", "minimum": 0}},
            "required": ["finding_count"],
            "additionalProperties": False,
        },
    )
    plugin = _plugin(
        "software.review",
        provides=(CapabilityProvision("software.review", "1", ("inspect",)),),
        tools=(
            ToolContribution(
                owner_plugin_id="software.review",
                runtime_id="software.review.inspect-runtime@1",
                contract=contract,
            ),
        ),
    )
    composition = activate_plugin_composition(
        _distribution((_selection(plugin),)),
        located_plugin_manifests={plugin.identity.component_id: plugin},
    )

    catalog = build_declared_tool_catalog(kernel_tools=(), composition=composition)

    activation = composition.activation_for("software.review")
    assert activation is not None
    assert activation.state is PluginActivationState.ACTIVE
    assert tuple(entry.contract.tool_name for entry in catalog.entries) == (
        "software.review.inspect",
    )
    assert catalog.entries[0].owner_component_id == "software.review"


def test_extension_and_resource_registry_require_exact_session_inventory() -> None:
    compute = _plugin(
        "openzyme.compute",
        provides=(
            CapabilityProvision(
                "openzyme.execution.revision-job",
                "1",
                operations=("submit", "observe"),
            ),
        ),
    )
    composition = activate_plugin_composition(
        _distribution((_selection(compute),)),
        located_plugin_manifests={compute.identity.component_id: compute},
    )
    extension_registry = ExtensionBundleRegistry.create(
        composition,
        activation_epoch=3,
    )
    route_catalog = build_route_catalog(composition)
    inventory_digest = _digest("inventory")
    binding = SessionCapabilityBindingRevision.create(
        binding_id="binding-1",
        session_id="session-1",
        revision=1,
        extension_bundle_digest=composition.extension_bundle_digest,
        route_catalog_digest=route_catalog.catalog_digest,
        inventory_bindings=(
            TargetInventoryBinding(
                target_id="hpc:primary",
                inventory_generation=7,
                inventory_digest=inventory_digest,
                qualification_valid_until="2026-08-20T00:00:00Z",
            ),
        ),
        created_by_actor_id="operator-1",
        created_at="2026-08-19T00:00:00Z",
    )
    resource = ResourceCapabilityFact(
        capability_id="software.hmmer",
        kind=ResourceCapabilityKind.SOFTWARE,
        target_id="hpc:primary",
        inventory_generation=7,
        qualification_digest=_digest("qualification"),
        environment_digest=_digest("environment"),
        inventory_digest=inventory_digest,
        operations=("hmmsearch",),
        version="3.4",
    )
    registry = CapabilityRegistry.create(
        extension_bundle=extension_registry,
        binding=binding,
        route_catalog=route_catalog,
        resource_facts=(resource,),
    )

    assert extension_registry.capability_facts[0].operations == (
        "observe",
        "submit",
    )
    assert extension_registry.registry_digest != registry.registry_digest
    assert registry.resource_facts[0].inventory_digest == inventory_digest

    with pytest.raises(KernelContractError) as drift:
        CapabilityRegistry.create(
            extension_bundle=extension_registry,
            binding=binding,
            route_catalog=route_catalog,
            resource_facts=(replace(resource, inventory_digest=_digest("other")),),
        )
    assert drift.value.code == "resource_fact_inventory_mismatch"
