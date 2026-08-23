from __future__ import annotations

from dataclasses import replace

import pytest

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import ResourceCapabilityFact
from openzyme_contracts import ResourceCapabilityKind
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import TargetInventoryBinding
from openzyme_contracts import ToolAffordanceState
from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import CapabilityProvision
from openzyme_extension_spi import CapabilityRequirement
from openzyme_extension_spi import CapabilityRequirementKind
from openzyme_extension_spi import ComponentIdentity
from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import DistributionManifest
from openzyme_extension_spi import KernelSelection
from openzyme_extension_spi import PluginManifest
from openzyme_extension_spi import PluginRequirementMode
from openzyme_extension_spi import PluginSelection
from openzyme_extension_spi import RouteContribution
from openzyme_extension_spi import ToolContribution
from openzyme_kernel import KernelContractError
from openzyme_kernel import CapabilityRegistry
from openzyme_kernel import ExtensionBundleRegistry
from openzyme_kernel import ToolAffordanceContext
from openzyme_kernel import ToolSubjectPolicyAction
from openzyme_kernel import ToolSubjectPolicyDecision
from openzyme_kernel import activate_plugin_composition
from openzyme_kernel import build_declared_tool_catalog
from openzyme_kernel import build_route_catalog
from openzyme_kernel import inspect_tool_affordances
from openzyme_kernel import inspect_capabilities
from openzyme_kernel import model_visible_tool_specs
from openzyme_kernel import resolve_tool_affordance_snapshot
from openzyme_kernel import revalidate_continuation_route
from openzyme_kernel import revalidate_tool_dispatch
from openzyme_kernel import subject_policy_digest


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
    routes: tuple[RouteContribution, ...] = (),
) -> PluginManifest:
    return PluginManifest(
        identity=_identity(plugin_id, ComponentKind.PLUGIN),
        required_kernel_contract="openzyme.kernel@1",
        required_extension_spi_contract="openzyme.extension-spi@1",
        provides=provides,
        requires=requires,
        tools=tools,
        routes=routes,
    )


def _fixture() -> tuple[
    object,
    object,
    SessionCapabilityBindingRevision,
    AgentAuthorityLease,
    ResourceCapabilityFact,
    ExtensionBundleRegistry,
    object,
]:
    compute_requirement = CapabilityRequirement(
        capability_id="openzyme.execution.revision-job",
        contract_spec="@1",
    )
    hmmer_requirement = CapabilityRequirement(
        capability_id="software.hmmer",
        contract_spec="@1",
        kind=CapabilityRequirementKind.RESOURCE,
        operations=("hmmsearch",),
        version_spec=">=3.3,<4",
        same_target_as="openzyme.execution.revision-job",
    )
    compute = _plugin(
        "openzyme.compute",
        provides=(CapabilityProvision("openzyme.execution.revision-job", "1"),),
    )
    hmmer = _plugin(
        "enzymedesign.hmmer",
        provides=(CapabilityProvision("enzymedesign.hmmer", "1"),),
        requires=(compute_requirement, hmmer_requirement),
        tools=(
            ToolContribution(
                owner_plugin_id="enzymedesign.hmmer",
                runtime_id="enzymedesign.hmmer.search-runtime",
                contract=ToolSpec(
                    tool_name="enzymedesign.hmmer.search",
                    description="Run a formal route-bound HMMER search.",
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                    required_authorities=("external_compute",),
                ),
                requirements=(compute_requirement, hmmer_requirement),
                requires_workspace=True,
                requires_explicit_route=True,
            ),
        ),
    )
    hpc = _plugin(
        "openzyme.hpc",
        routes=(
            RouteContribution(
                route_id="hpc:primary/hmmer:3.4",
                owner_component_id="openzyme.hpc",
                capability_ids=(
                    "openzyme.execution.revision-job",
                    "software.hmmer",
                ),
                route_kind="openzyme.compute.hpc",
                route_contract_digest=_digest("route"),
                target_id="hpc:primary",
                driver_id="enzymedesign.hmmer.hpc",
                requirements=(
                    CapabilityRequirement(
                        capability_id="software.hmmer",
                        contract_spec="@1",
                        kind=CapabilityRequirementKind.RESOURCE,
                        operations=("hmmsearch",),
                        version_spec="==3.4",
                        same_target_as="openzyme.execution.revision-job",
                    ),
                ),
            ),
            RouteContribution(
                route_id="local:unbound/hmmer:future",
                owner_component_id="openzyme.hpc",
                capability_ids=(
                    "openzyme.execution.revision-job",
                    "software.hmmer",
                ),
                route_kind="openzyme.compute.local",
                route_contract_digest=_digest("unbound-route"),
                target_id="local:unbound",
                driver_id="enzymedesign.hmmer.local",
                requirements=(
                    CapabilityRequirement(
                        capability_id="software.hmmer",
                        contract_spec="@1",
                        kind=CapabilityRequirementKind.RESOURCE,
                        operations=("hmmsearch",),
                        version_spec="==9.9",
                        same_target_as="openzyme.execution.revision-job",
                    ),
                ),
            ),
        ),
    )
    manifests = {item.identity.component_id: item for item in (compute, hmmer, hpc)}
    distribution = DistributionManifest(
        identity=_identity("enzymedesign", ComponentKind.DISTRIBUTION),
        kernel=KernelSelection(
            contract_id="openzyme.kernel@1",
            contract_digest=_digest("kernel"),
            implementation_component_id="openzyme.kernel",
            implementation_manifest_digest=_digest("kernel-manifest"),
        ),
        adapters=(),
        plugins=tuple(
            PluginSelection(
                plugin_id=manifest.identity.component_id,
                manifest_digest=manifest.manifest_digest,
                requirement_mode=PluginRequirementMode.REQUIRED,
            )
            for manifest in manifests.values()
        ),
        drivers=(),
        delivery_surfaces=(),
    )
    composition = activate_plugin_composition(
        distribution,
        located_plugin_manifests=manifests,
    )
    catalog = build_declared_tool_catalog(
        kernel_tools=(),
        composition=composition,
    )
    route_catalog = build_route_catalog(composition)
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
                inventory_digest=_digest("inventory"),
                qualification_valid_until="2026-08-20T00:00:00Z",
            ),
        ),
        created_by_actor_id="operator-1",
        created_at="2026-08-19T00:00:00Z",
    )
    lease = AgentAuthorityLease.create(
        lease_id="lease-1",
        session_id="session-1",
        agent_member_id="member-1",
        grants=(
            AuthorityGrant.create(
                grant_id="grant-1",
                scope_id="session-1",
                operations=("external_compute",),
                generation=1,
                fence=1,
            ),
        ),
        generation=1,
        fence=1,
        state=AgentAuthorityLeaseState.ACTIVE,
        issued_at="2026-08-19T00:00:00Z",
        expires_at="2026-09-01T00:00:00Z",
    )
    resource = ResourceCapabilityFact(
        capability_id="software.hmmer",
        kind=ResourceCapabilityKind.SOFTWARE,
        target_id="hpc:primary",
        inventory_generation=7,
        qualification_digest=_digest("qualification"),
        environment_digest=_digest("environment"),
        inventory_digest=_digest("inventory"),
        operations=("hmmsearch",),
        version="3.4",
    )
    extension_registry = ExtensionBundleRegistry.create(
        composition,
        activation_epoch=1,
    )
    return (
        catalog,
        route_catalog,
        binding,
        lease,
        resource,
        extension_registry,
        composition,
    )


def _context(
    *,
    include_resource: bool = True,
    resource_version: str = "3.4",
    unavailable: bool = False,
    hidden: bool = False,
    policy_decisions: tuple[ToolSubjectPolicyDecision, ...] = (),
) -> ToolAffordanceContext:
    (
        catalog,
        route_catalog,
        binding,
        lease,
        resource,
        extension_registry,
        _composition,
    ) = _fixture()
    capability_registry = CapabilityRegistry.create(
        extension_bundle=extension_registry,
        binding=binding,
        route_catalog=route_catalog,  # type: ignore[arg-type]
        resource_facts=(replace(resource, version=resource_version),)
        if include_resource
        else (),
    )
    return ToolAffordanceContext(
        session_id="session-1",
        agent_member_id="member-1",
        turn_id="turn-1",
        declared_catalog=catalog,  # type: ignore[arg-type]
        capability_binding=binding,
        capability_registry=capability_registry,
        authority_lease=lease,
        workspace_generation=2,
        workspace_ready=True,
        health_observation_digest=_digest("health"),
        observed_at="2026-08-19T00:00:01Z",
        subject_role="researcher",
        task_id="task-1",
        subject_policy_digest=subject_policy_digest(
            session_id="session-1",
            agent_member_id="member-1",
            subject_role="researcher",
            task_id="task-1",
            decisions=policy_decisions,
        ),
        policy_decisions=policy_decisions,
        unavailable_route_ids=(
            frozenset({"hpc:primary/hmmer:3.4"}) if unavailable else frozenset()
        ),
        hidden_tool_names=(
            frozenset({"enzymedesign.hmmer.search"}) if hidden else frozenset()
        ),
    )


def test_resource_and_route_make_formal_tool_available() -> None:
    context = _context()
    snapshot = resolve_tool_affordance_snapshot(
        context,
        snapshot_id="snapshot-1",
        created_at="2026-08-19T00:00:01Z",
    )

    assert snapshot.has_valid_digest()
    assert snapshot.model_visible_tool_names == ("enzymedesign.hmmer.search",)
    assert snapshot.affordances[0].state is ToolAffordanceState.AVAILABLE
    assert snapshot.affordances[0].route_ids == ("hpc:primary/hmmer:3.4",)
    assert snapshot.affordances[0].route_refs[0].inventory_generation == 7
    assert tuple(
        spec.tool_name
        for spec in model_visible_tool_specs(
            snapshot=snapshot,
            catalog=context.declared_catalog,
        )
    ) == ("enzymedesign.hmmer.search",)

    with pytest.raises(KernelContractError) as missing_route:
        revalidate_tool_dispatch(
            snapshot=snapshot,
            context=context,
            tool_name="enzymedesign.hmmer.search",
            selected_route_id=None,
        )
    assert missing_route.value.code == "missing_route_id"
    assert missing_route.value.effect_certainty == "no_effect"

    admission = revalidate_tool_dispatch(
        snapshot=snapshot,
        context=context,
        tool_name="enzymedesign.hmmer.search",
        selected_route_id="hpc:primary/hmmer:3.4",
    )
    assert admission.route_id == "hpc:primary/hmmer:3.4"
    assert admission.target_id == "hpc:primary"
    assert admission.driver_id == "enzymedesign.hmmer.hpc"
    assert admission.route_digest is not None


def test_route_specific_version_rejects_globally_compatible_target() -> None:
    snapshot = resolve_tool_affordance_snapshot(
        _context(resource_version="3.3"),
        snapshot_id="snapshot-route-version-drift",
        created_at="2026-08-19T00:00:01Z",
    )

    assert snapshot.model_visible_tool_names == ()
    assert snapshot.affordances[0].state is ToolAffordanceState.BLOCKED_QUALIFICATION
    assert snapshot.affordances[0].blockers[0].code == (
        "software_requirement_unsatisfied"
    )
    assert snapshot.affordances[0].blockers[0].requirement == "software.hmmer==3.4"


def test_missing_resource_blocks_model_list_but_is_inspectable() -> None:
    snapshot = resolve_tool_affordance_snapshot(
        _context(include_resource=False),
        snapshot_id="snapshot-1",
        created_at="2026-08-19T00:00:01Z",
    )

    assert snapshot.model_visible_tool_names == ()
    assert snapshot.affordances[0].state is ToolAffordanceState.BLOCKED_QUALIFICATION
    inspection = inspect_tool_affordances(snapshot)
    assert inspection[0]["blockers"] == [
        {
            "code": "software_requirement_unsatisfied",
            "requirement": "software.hmmer>=3.3,<4",
            "target_id": "hpc:primary",
        }
    ]


def test_hidden_tool_is_absent_from_function_list_and_inspection() -> None:
    snapshot = resolve_tool_affordance_snapshot(
        _context(hidden=True),
        snapshot_id="snapshot-1",
        created_at="2026-08-19T00:00:01Z",
    )

    assert snapshot.model_visible_tool_names == ()
    assert inspect_tool_affordances(snapshot) == ()


def test_task_role_policy_can_block_or_hide_without_changing_catalog() -> None:
    blocked_context = _context(
        policy_decisions=(
            ToolSubjectPolicyDecision(
                tool_name="enzymedesign.hmmer.search",
                action=ToolSubjectPolicyAction.BLOCK,
                blocker_code="task_role_policy_denied",
            ),
        )
    )
    hidden_context = _context(
        policy_decisions=(
            ToolSubjectPolicyDecision(
                tool_name="enzymedesign.hmmer.search",
                action=ToolSubjectPolicyAction.HIDE,
            ),
        )
    )
    blocked = resolve_tool_affordance_snapshot(
        blocked_context,
        snapshot_id="snapshot-blocked",
        created_at="2026-08-19T00:00:01Z",
    )
    hidden = resolve_tool_affordance_snapshot(
        hidden_context,
        snapshot_id="snapshot-hidden",
        created_at="2026-08-19T00:00:01Z",
    )

    assert blocked.declared_tool_catalog_digest == hidden.declared_tool_catalog_digest
    assert blocked.affordances[0].state is ToolAffordanceState.BLOCKED_AUTHORITY
    assert blocked.affordances[0].blockers[0].code == "task_role_policy_denied"
    assert inspect_tool_affordances(hidden) == ()


def test_target_health_changes_affordance_without_changing_release_catalog() -> None:
    healthy_context = _context()
    unavailable_context = _context(unavailable=True)
    healthy = resolve_tool_affordance_snapshot(
        healthy_context,
        snapshot_id="snapshot-1",
        created_at="2026-08-19T00:00:01Z",
    )
    unavailable = resolve_tool_affordance_snapshot(
        unavailable_context,
        snapshot_id="snapshot-2",
        created_at="2026-08-19T00:00:02Z",
    )

    assert (
        healthy.declared_tool_catalog_digest == unavailable.declared_tool_catalog_digest
    )
    assert unavailable.affordances[0].state is (
        ToolAffordanceState.TEMPORARILY_UNAVAILABLE
    )


def test_scheduler_queue_pressure_does_not_remove_an_accepting_route() -> None:
    # Queue pressure is an observation, not an unavailable route.  As long as
    # the scheduler accepts new work, it must not be placed in
    # unavailable_route_ids or disappear from the Agent affordance.
    queued_context = replace(
        _context(),
        health_observation_digest=_digest("scheduler-accepting-queue-busy"),
    )
    snapshot = resolve_tool_affordance_snapshot(
        queued_context,
        snapshot_id="snapshot-queue-busy",
        created_at="2026-08-19T00:00:02Z",
    )

    assert snapshot.affordances[0].state is ToolAffordanceState.AVAILABLE
    assert snapshot.affordances[0].route_ids == ("hpc:primary/hmmer:3.4",)


def test_dispatch_rejects_binding_or_health_drift_without_route_fallback() -> None:
    context = _context()
    snapshot = resolve_tool_affordance_snapshot(
        context,
        snapshot_id="snapshot-1",
        created_at="2026-08-19T00:00:01Z",
    )
    drifted_context = replace(
        context,
        health_observation_digest=_digest("new-health"),
    )

    with pytest.raises(KernelContractError) as stale:
        revalidate_tool_dispatch(
            snapshot=snapshot,
            context=drifted_context,
            tool_name="enzymedesign.hmmer.search",
            selected_route_id="hpc:primary/hmmer:3.4",
        )
    assert stale.value.code == "tool_affordance_stale"
    assert stale.value.effect_certainty == "no_effect"
    assert stale.value.fallback_performed is False


def test_expired_qualification_is_blocked_before_dispatch() -> None:
    snapshot = resolve_tool_affordance_snapshot(
        replace(_context(), observed_at="2026-08-21T00:00:00Z"),
        snapshot_id="snapshot-expired",
        created_at="2026-08-21T00:00:00Z",
    )

    assert snapshot.model_visible_tool_names == ()
    assert snapshot.affordances[0].state is ToolAffordanceState.BLOCKED_QUALIFICATION
    assert snapshot.affordances[0].blockers[0].code == "qualification_expired"


def test_revoked_authority_after_model_selection_is_stale_no_effect() -> None:
    context = _context()
    snapshot = resolve_tool_affordance_snapshot(
        context,
        snapshot_id="snapshot-1",
        created_at="2026-08-19T00:00:01Z",
    )
    revoked = AgentAuthorityLease.create(
        lease_id=context.authority_lease.lease_id,
        session_id=context.session_id,
        agent_member_id=context.agent_member_id,
        grants=context.authority_lease.grants,
        generation=context.authority_lease.generation,
        fence=context.authority_lease.fence,
        state=AgentAuthorityLeaseState.REVOKED,
        issued_at=context.authority_lease.issued_at,
        expires_at=context.authority_lease.expires_at,
    )

    with pytest.raises(KernelContractError) as stale:
        revalidate_tool_dispatch(
            snapshot=snapshot,
            context=replace(context, authority_lease=revoked),
            tool_name="enzymedesign.hmmer.search",
            selected_route_id="hpc:primary/hmmer:3.4",
        )
    assert stale.value.code == "tool_affordance_stale"
    assert stale.value.effect_certainty == "no_effect"
    assert stale.value.fallback_performed is False


def test_continuation_remains_bound_to_original_route_proof() -> None:
    context = _context()
    snapshot = resolve_tool_affordance_snapshot(
        context,
        snapshot_id="snapshot-1",
        created_at="2026-08-19T00:00:01Z",
    )
    admission = revalidate_tool_dispatch(
        snapshot=snapshot,
        context=context,
        tool_name="enzymedesign.hmmer.search",
        selected_route_id="hpc:primary/hmmer:3.4",
    )

    assert revalidate_continuation_route(
        original_admission=admission,
        context=context,
    ) is admission
    with pytest.raises(KernelContractError) as stale:
        revalidate_continuation_route(
            original_admission=replace(
                admission,
                route_id="hpc:secondary/hmmer:3.4",
            ),
            context=context,
        )
    assert stale.value.code == "tool_affordance_stale"
    assert stale.value.effect_certainty == "no_effect"
    assert stale.value.fallback_performed is False


def test_capability_inspection_is_safe_and_hides_private_transport_facts() -> None:
    context = _context()
    snapshot = resolve_tool_affordance_snapshot(
        context,
        snapshot_id="snapshot-1",
        created_at="2026-08-19T00:00:01Z",
    )
    *_, composition = _fixture()
    inspection = inspect_capabilities(
        composition=composition,  # type: ignore[arg-type]
        registry=context.capability_registry,
        snapshot=snapshot,
    )
    serialized = str(inspection).lower()

    assert inspection["routes"][0]["target_id"] == "hpc:primary"
    assert inspection["tools"][0]["tool_name"] == "enzymedesign.hmmer.search"
    for forbidden in ("credential", "ssh_host", "remote_path", "binary_locator"):
        assert forbidden not in serialized
