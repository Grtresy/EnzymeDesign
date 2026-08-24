from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import datetime
import json

import pytest

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import FILE_WORKSPACE_FAILURE_FACT_PUBLIC_FIELDS
from openzyme_contracts import FILE_WORKSPACE_FAILURE_IDENTITY_PUBLIC_FIELDS
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import ToolExposure
from openzyme_contracts import ToolExposureDecision
from openzyme_contracts import ToolSpec
from openzyme_contracts import WorkflowAuthorityBinding
from openzyme_contracts import WorkflowAuthorityDerivationKind
from openzyme_contracts import WorkflowAuthorityStatus
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import CapabilityProvision
from openzyme_extension_spi import CapabilityRequirement
from openzyme_extension_spi import ComponentIdentity
from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import DistributionManifest
from openzyme_extension_spi import KernelSelection
from openzyme_extension_spi import PluginManifest
from openzyme_extension_spi import PluginRequirementMode
from openzyme_extension_spi import PluginSelection
from openzyme_extension_spi import RouteContribution
from openzyme_extension_spi import ToolContribution
from openzyme_kernel import CapabilityRegistry
from openzyme_kernel import ExtensionBundleRegistry
from openzyme_kernel import KernelContractError
from openzyme_kernel import MountedRuntimeCapabilityGateway
from openzyme_kernel import RuntimeToolScope
from openzyme_kernel import ToolAffordanceContext
from openzyme_kernel import activate_plugin_composition
from openzyme_kernel import build_declared_tool_catalog
from openzyme_kernel import build_route_catalog
from openzyme_kernel import resolve_tool_affordance_snapshot
from openzyme_kernel import subject_policy_digest
from openzyme_kernel.catalog import DECLARED_TOOL_CATALOG_SCHEMA_VERSION
from openzyme_kernel.catalog import DeclaredToolCatalog
from openzyme_kernel.catalog import DeclaredToolEntry
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.tool_exposure import InMemoryCommandToolExpansionStore
from openzyme_kernel.tool_exposure import KernelCapabilitiesInspectRuntime
from openzyme_kernel.tool_exposure import ToolExposureRolePolicy
from openzyme_kernel.tool_exposure import resolve_tool_exposure_snapshot
from openzyme_runtime_spi import RuntimeToolRequest
from openzyme_runtime_spi import RuntimeToolInvocationError


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


def _scope(*, routed: bool = False) -> RuntimeToolScope:
    spec = ToolSpec(
        tool_name="example.observe",
        description="Observe one example.",
        input_schema={"type": "object", "additionalProperties": False},
        output_schema={"type": "object"},
    )
    route_requirement = CapabilityRequirement(
        capability_id="example.route",
        contract_spec="@1",
    )
    plugin = PluginManifest(
        identity=_identity("example.plugin", ComponentKind.PLUGIN),
        required_kernel_contract="openzyme.kernel@1",
        required_extension_spi_contract="openzyme.extension-spi@1",
        provides=(CapabilityProvision("example.route", "1"),) if routed else (),
        tools=(
            ToolContribution(
                owner_plugin_id="example.plugin",
                runtime_id="example.plugin.observe@1",
                contract=spec,
                requirements=(route_requirement,) if routed else (),
                requires_explicit_route=routed,
            ),
        ),
        routes=(
            (
                RouteContribution(
                    route_id="route.adjacent",
                    owner_component_id="example.plugin",
                    capability_ids=("example.route",),
                    route_kind="example.runtime",
                    route_contract_digest=_digest("route-adjacent"),
                    driver_id="example.driver.adjacent",
                ),
                RouteContribution(
                    route_id="route.primary",
                    owner_component_id="example.plugin",
                    capability_ids=("example.route",),
                    route_kind="example.runtime",
                    route_contract_digest=_digest("route-primary"),
                    driver_id="example.driver.primary",
                ),
            )
            if routed
            else ()
        ),
    )
    distribution = DistributionManifest(
        identity=_identity("example.distribution", ComponentKind.DISTRIBUTION),
        kernel=KernelSelection(
            contract_id="openzyme.kernel@1",
            contract_digest=_digest("kernel"),
            implementation_component_id="openzyme.kernel",
            implementation_manifest_digest=_digest("kernel-manifest"),
        ),
        adapters=(),
        plugins=(
            PluginSelection(
                plugin_id="example.plugin",
                manifest_digest=plugin.manifest_digest,
                requirement_mode=PluginRequirementMode.REQUIRED,
            ),
        ),
        drivers=(),
        delivery_surfaces=(),
    )
    composition = activate_plugin_composition(
        distribution,
        located_plugin_manifests={"example.plugin": plugin},
    )
    catalog = build_declared_tool_catalog(
        kernel_tools=(),
        composition=composition,
    )
    routes = build_route_catalog(composition)
    binding = SessionCapabilityBindingRevision.create(
        binding_id="binding-1",
        session_id="session-1",
        revision=1,
        extension_bundle_digest=composition.extension_bundle_digest,
        route_catalog_digest=routes.catalog_digest,
        inventory_bindings=(),
        created_by_actor_id="operator-1",
        created_at="2026-08-21T00:00:00+00:00",
    )
    lease = AgentAuthorityLease.create(
        lease_id="lease-1",
        session_id="session-1",
        agent_member_id="member-1",
        grants=(),
        generation=1,
        fence=1,
        state=AgentAuthorityLeaseState.ACTIVE,
        issued_at="2026-08-21T00:00:00+00:00",
        expires_at="2026-09-01T00:00:00+00:00",
    )
    registry = CapabilityRegistry.create(
        extension_bundle=ExtensionBundleRegistry.create(
            composition,
            activation_epoch=1,
        ),
        binding=binding,
        route_catalog=routes,
        resource_facts=(),
    )
    context = ToolAffordanceContext(
        session_id="session-1",
        agent_member_id="member-1",
        turn_id="turn-1",
        declared_catalog=catalog,
        capability_binding=binding,
        capability_registry=registry,
        authority_lease=lease,
        workspace_generation=1,
        workspace_ready=True,
        health_observation_digest=_digest("health"),
        observed_at="2026-08-21T00:00:01+00:00",
        subject_role="worker",
        task_id="task-1",
        subject_policy_digest=subject_policy_digest(
            session_id="session-1",
            agent_member_id="member-1",
            subject_role="worker",
            task_id="task-1",
            decisions=(),
        ),
    )
    snapshot = resolve_tool_affordance_snapshot(
        context,
        snapshot_id="snapshot-1",
        created_at="2026-08-21T00:00:01+00:00",
    )
    return RuntimeToolScope(
        command_id="command-1",
        catalog=catalog,
        snapshot=snapshot,
        current_context=context,
    )


def _workflow() -> WorkflowAuthorityBinding:
    registry_digest = _digest("workflow-registry")
    selection_digest = canonical_sha256_digest(
        {
            "schema_version": "workflow_selection_binding@1",
            "registry_snapshot_digest": registry_digest,
            "selected_workflow_refs": ["workflow.observe@1"],
        }
    )
    return WorkflowAuthorityBinding(
        authority_id="workflow-authority-1",
        session_id="session-1",
        project_id="project-1",
        request_lineage_id="lineage-1",
        source_message_id="message-1",
        source_principal_id="user-1",
        authorized_actor_id="member-1",
        selected_workflow_refs=("workflow.observe@1",),
        selection_digest=selection_digest,
        registry_snapshot_digest=registry_digest,
        derivation_kind=WorkflowAuthorityDerivationKind.ROOT_MESSAGE,
        status=WorkflowAuthorityStatus.ACTIVE,
        epoch=2,
        state_version=1,
        created_at="2026-08-21T00:00:00+00:00",
        updated_at="2026-08-21T00:00:00+00:00",
        task_id="task-1",
    )


def _exposed_scope(*, routed: bool = False) -> RuntimeToolScope:
    base = _scope(routed=routed)
    capabilities = ToolSpec(
        tool_name="capabilities.inspect",
        description="Inspect bounded non-Hidden capabilities.",
        input_schema={"type": "object", "additionalProperties": False},
    )
    hidden = ToolSpec(
        tool_name="secret.hidden",
        description="Must not be disclosed.",
        input_schema={"type": "object", "additionalProperties": False},
    )
    entries = tuple(
        sorted(
            (
                *base.catalog.entries,
                DeclaredToolEntry(
                    owner_component_id="openzyme.kernel",
                    runtime_id="openzyme.kernel.runtime.capabilities.inspect",
                    contract=capabilities,
                ),
                DeclaredToolEntry(
                    owner_component_id="secret.plugin",
                    runtime_id="secret.plugin.runtime",
                    contract=hidden,
                ),
            ),
            key=lambda entry: entry.contract.tool_name,
        )
    )
    catalog = DeclaredToolCatalog(
        entries=entries,
        catalog_digest=canonical_sha256_digest(
            {
                "schema_version": DECLARED_TOOL_CATALOG_SCHEMA_VERSION,
                "entries": [entry.to_dict() for entry in entries],
            }
        ),
    )
    context = replace(base.current_context, declared_catalog=catalog)
    snapshot = resolve_tool_affordance_snapshot(
        context,
        snapshot_id="snapshot-exposed-1",
        created_at="2026-08-21T00:00:01+00:00",
    )
    workflow = _workflow()
    exposure = resolve_tool_exposure_snapshot(
        snapshot_id="exposure-1",
        session_id="session-1",
        agent_member_id="member-1",
        turn_id="turn-1",
        catalog=catalog,
        affordance_snapshot=snapshot,
        workflow_binding=workflow,
        policy=ToolExposureRolePolicy(
            policy_id="exposure-policy-1",
            distribution_id="distribution-1",
            release_digest=_digest("release"),
            subject_role="worker",
            decisions=(
                ToolExposureDecision(
                    "capabilities.inspect",
                    ToolExposure.DIRECT,
                    "stable_baseline",
                ),
                ToolExposureDecision(
                    "example.observe",
                    ToolExposure.DEFERRED,
                    "long_tail",
                ),
                ToolExposureDecision(
                    "secret.hidden",
                    ToolExposure.HIDDEN,
                    "role_forbidden",
                ),
            ),
        ),
        adopted_release_digest=_digest("release"),
        created_at="2026-08-21T00:00:01+00:00",
    )
    return RuntimeToolScope(
        command_id="command-1",
        catalog=catalog,
        snapshot=snapshot,
        current_context=context,
        exposure_snapshot=exposure,
        current_workflow_authority=workflow,
    )


@dataclass
class _Scopes:
    scope: RuntimeToolScope

    def get(self, command_id: str):
        return self.scope if command_id == self.scope.command_id else None


@dataclass
class _Runtime:
    contract: ToolSpec
    calls: int = 0
    explode: bool = False
    typed_error: RuntimeToolInvocationError | None = None
    owner_plugin_id: str = "example.plugin"
    runtime_id: str = "example.plugin.observe@1"

    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        self.calls += 1
        if self.typed_error is not None:
            raise self.typed_error
        if self.explode:
            raise RuntimeError("private provider detail")
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            status="observed",
            summary="Observed.",
            payload={"task_finished": False},
        )


def _request(
    scope: RuntimeToolScope, *, digest: str | None = None
) -> RuntimeToolRequest:
    snapshot_digest = digest or scope.snapshot.snapshot_digest
    return RuntimeToolRequest(
        request_id="request-1",
        invocation=ToolInvocation(
            call_id="call-1",
            tool_name="example.observe",
            arguments={},
            session_id="session-1",
            agent_member_id="member-1",
            task_id="task-1",
            affordance_snapshot_digest=snapshot_digest,
        ),
        affordance_snapshot_digest=snapshot_digest,
    )


def test_gateway_lists_and_dispatches_only_the_exact_afforded_runtime() -> None:
    scope = _scope()
    runtime = _Runtime(scope.catalog.entries[0].contract)
    gateway = MountedRuntimeCapabilityGateway(
        scopes=_Scopes(scope),
        runtimes=((runtime.contract.tool_name, runtime),),
    )

    specs = gateway.list_tools(
        command_id="command-1",
        affordance_snapshot_digest=scope.snapshot.snapshot_digest,
    )
    result = gateway.invoke(command_id="command-1", request=_request(scope))

    assert [spec.tool_name for spec in specs] == ["example.observe"]
    assert result.ok is True
    assert runtime.calls == 1


def test_gateway_rejects_stale_snapshot_before_runtime_without_fallback() -> None:
    scope = _scope()
    runtime = _Runtime(scope.catalog.entries[0].contract)
    gateway = MountedRuntimeCapabilityGateway(
        scopes=_Scopes(scope),
        runtimes=((runtime.contract.tool_name, runtime),),
    )

    result = gateway.invoke(
        command_id="command-1",
        request=_request(scope, digest=_digest("stale")),
    )

    assert result.error_code == "tool_affordance_stale"
    assert result.payload["effect_certainty"] == "no_effect"
    assert result.payload["fallback_performed"] is False
    assert runtime.calls == 0


def test_gateway_revalidates_current_authority_before_runtime() -> None:
    scope = _scope()
    previous = scope.current_context.authority_lease
    revoked = AgentAuthorityLease.create(
        lease_id=previous.lease_id,
        session_id=previous.session_id,
        agent_member_id=previous.agent_member_id,
        grants=previous.grants,
        generation=previous.generation,
        fence=previous.fence,
        state=AgentAuthorityLeaseState.REVOKED,
        issued_at=previous.issued_at,
        expires_at=previous.expires_at,
    )
    current = replace(scope.current_context, authority_lease=revoked)
    scope = replace(scope, current_context=current)
    runtime = _Runtime(scope.catalog.entries[0].contract)
    gateway = MountedRuntimeCapabilityGateway(
        scopes=_Scopes(scope),
        runtimes=((runtime.contract.tool_name, runtime),),
    )

    result = gateway.invoke(command_id="command-1", request=_request(scope))

    assert result.error_code == "tool_affordance_stale"
    assert runtime.calls == 0


def test_gateway_preserves_unknown_effect_when_runtime_raises() -> None:
    scope = _scope()
    runtime = _Runtime(scope.catalog.entries[0].contract, explode=True)
    gateway = MountedRuntimeCapabilityGateway(
        scopes=_Scopes(scope),
        runtimes=((runtime.contract.tool_name, runtime),),
    )

    result = gateway.invoke(command_id="command-1", request=_request(scope))

    assert result.error_code == "extension_tool_runtime_failed"
    assert result.payload["effect_certainty"] == "dispatch_in_doubt"
    assert result.payload["mutation_applied"] is None
    assert result.payload["reconcile_required"] is True
    assert result.payload["fallback_performed"] is False
    assert result.payload["retry_performed"] is False
    assert result.terminates_turn is True
    assert result.failure_observation is not None
    assert result.failure_observation["schema_version"] == "failure_observation@2"
    assert result.failure_observation["component"] == "example.plugin"
    assert result.failure_observation["phase"] == "tool_dispatch"
    assert result.failure_observation["identities"] == {
        "command_id": "command-1",
        "component_id": "example.plugin",
    }
    assert result.failure_observation["source_ref"] == "call-1"
    assert result.failure_observation["source_version"] == (
        runtime.contract.contract_digest
    )
    assert set(result.failure_observation["facts"]) <= (
        FILE_WORKSPACE_FAILURE_FACT_PUBLIC_FIELDS
    )
    assert None not in result.failure_observation["facts"].values()
    assert set(result.failure_observation["identities"]) <= (
        FILE_WORKSPACE_FAILURE_IDENTITY_PUBLIC_FIELDS
    )
    assert result.failure_observation["effect_certainty"] == "dispatch_in_doubt"
    assert result.failure_observation["mutation_applied"] is None
    assert result.failure_observation["fallback_performed"] is False
    assert result.failure_observation["retry_eligibility"] == "reconcile_required"
    assert result.failure_observation["next_action"] == (
        "reconcile_exact_tool_dispatch"
    )
    assert result.private_diagnostic is not None
    assert "private provider detail" in result.private_diagnostic.exception_message
    assert (
        result.private_diagnostic.failure_id
        == (result.failure_observation["failure_id"])
    )
    public_wire = json.dumps(result.to_dict(), sort_keys=True)
    assert "private provider detail" not in public_wire
    assert "traceback" not in public_wire
    assert result.private_diagnostic.record_digest not in public_wire
    assert runtime.calls == 1


def test_gateway_preserves_typed_runtime_effect_truth() -> None:
    scope = _scope()
    runtime = _Runtime(
        scope.catalog.entries[0].contract,
        typed_error=RuntimeToolInvocationError(
            code="provider_rejected_request",
            summary="The provider rejected the bounded request.",
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            mutation_applied=False,
            diagnostic_id="diagnostic-provider-rejected-1",
            reconcile_required=False,
            status="rejected",
            hint="Correct the request before trying a new occurrence.",
        ),
    )
    gateway = MountedRuntimeCapabilityGateway(
        scopes=_Scopes(scope),
        runtimes=((runtime.contract.tool_name, runtime),),
    )

    result = gateway.invoke(command_id="command-1", request=_request(scope))

    assert result.error_code == "provider_rejected_request"
    assert result.status == "rejected"
    assert result.payload["effect_certainty"] == "no_effect"
    assert result.payload["mutation_applied"] is False
    assert result.payload["reconcile_required"] is False
    assert result.payload["diagnostic_id"] == "diagnostic-provider-rejected-1"


def test_gateway_fails_closed_when_visible_runtime_is_missing() -> None:
    scope = _scope()
    gateway = MountedRuntimeCapabilityGateway(scopes=_Scopes(scope), runtimes=())

    with pytest.raises(KernelContractError) as raised:
        gateway.list_tools(
            command_id="command-1",
            affordance_snapshot_digest=scope.snapshot.snapshot_digest,
        )

    assert raised.value.code == "tool_runtime_not_mounted"


def test_gateway_rejects_runtime_owner_or_runtime_id_drift() -> None:
    scope = _scope()
    runtime = _Runtime(
        scope.catalog.entries[0].contract,
        owner_plugin_id="other.plugin",
    )
    gateway = MountedRuntimeCapabilityGateway(
        scopes=_Scopes(scope),
        runtimes=((runtime.contract.tool_name, runtime),),
    )

    result = gateway.invoke(command_id="command-1", request=_request(scope))

    assert result.error_code == "tool_runtime_not_mounted"
    assert result.payload["effect_certainty"] == "no_effect"
    assert runtime.calls == 0


def test_gateway_expands_only_exact_deferred_tool_for_current_command() -> None:
    scope = _exposed_scope()
    observe = scope.catalog.get("example.observe")
    capabilities = scope.catalog.get("capabilities.inspect")
    assert observe is not None
    assert capabilities is not None
    runtime = _Runtime(observe.contract)
    expansions = InMemoryCommandToolExpansionStore()
    gateway = MountedRuntimeCapabilityGateway(
        scopes=_Scopes(scope),
        runtimes=(
            (
                "capabilities.inspect",
                KernelCapabilitiesInspectRuntime(capabilities.contract),
            ),
            ("example.observe", runtime),
        ),
        expansions=expansions,
        clock=DeterministicClock(datetime(2026, 8, 21, 0, 0, 2, tzinfo=UTC)),
    )

    initial = gateway.list_tools(
        command_id=scope.command_id,
        affordance_snapshot_digest=scope.snapshot.snapshot_digest,
    )
    inspection = gateway.invoke(
        command_id=scope.command_id,
        request=RuntimeToolRequest(
            request_id="inspection-request-1",
            invocation=ToolInvocation(
                call_id="inspection-call-1",
                tool_name="capabilities.inspect",
                arguments={
                    "expand_tool_names": ["example.observe", "secret.hidden"],
                    "max_items": 20,
                },
                session_id="session-1",
                agent_member_id="member-1",
                task_id="task-1",
                affordance_snapshot_digest=scope.snapshot.snapshot_digest,
            ),
            affordance_snapshot_digest=scope.snapshot.snapshot_digest,
        ),
    )
    expanded = gateway.list_tools(
        command_id=scope.command_id,
        affordance_snapshot_digest=scope.snapshot.snapshot_digest,
    )
    hidden = gateway.invoke(
        command_id=scope.command_id,
        request=RuntimeToolRequest(
            request_id="hidden-request-1",
            invocation=ToolInvocation(
                call_id="hidden-call-1",
                tool_name="secret.hidden",
                arguments={},
                session_id="session-1",
                agent_member_id="member-1",
                task_id="task-1",
                affordance_snapshot_digest=scope.snapshot.snapshot_digest,
            ),
            affordance_snapshot_digest=scope.snapshot.snapshot_digest,
        ),
    )

    assert tuple(spec.tool_name for spec in initial) == ("capabilities.inspect",)
    assert inspection.ok is True
    assert inspection.payload["inspection"]["undisclosed_or_unknown_count"] == 1
    assert "secret.hidden" not in str(inspection.payload)
    assert tuple(spec.tool_name for spec in expanded) == (
        "capabilities.inspect",
        "example.observe",
    )
    assert expansions.get("command-1").expanded_tool_names == ("example.observe",)
    assert hidden.error_code == "tool_not_exposed"
    assert hidden.tool_name == "unexposed.tool"
    assert "secret.hidden" not in str(hidden.to_dict())


def test_expanded_deferred_dispatch_rejects_exact_route_drift_without_adjacent_fallback() -> (
    None
):
    scope = _exposed_scope(routed=True)
    observe = scope.catalog.get("example.observe")
    capabilities = scope.catalog.get("capabilities.inspect")
    assert observe is not None
    assert capabilities is not None
    original = next(
        (
            affordance
            for affordance in scope.snapshot.affordances
            if affordance.tool_name == "example.observe"
        ),
        None,
    )
    assert original is not None
    assert original.route_ids == ("route.adjacent", "route.primary")
    runtime = _Runtime(observe.contract)
    expansions = InMemoryCommandToolExpansionStore()
    scopes = _Scopes(scope)
    gateway = MountedRuntimeCapabilityGateway(
        scopes=scopes,
        runtimes=(
            (
                "capabilities.inspect",
                KernelCapabilitiesInspectRuntime(capabilities.contract),
            ),
            ("example.observe", runtime),
        ),
        expansions=expansions,
        clock=DeterministicClock(datetime(2026, 8, 21, 0, 0, 2, tzinfo=UTC)),
    )
    inspection = gateway.invoke(
        command_id=scope.command_id,
        request=RuntimeToolRequest(
            request_id="inspection-route-request-1",
            invocation=ToolInvocation(
                call_id="inspection-route-call-1",
                tool_name="capabilities.inspect",
                arguments={"expand_tool_names": ["example.observe"]},
                session_id="session-1",
                agent_member_id="member-1",
                task_id="task-1",
                affordance_snapshot_digest=scope.snapshot.snapshot_digest,
            ),
            affordance_snapshot_digest=scope.snapshot.snapshot_digest,
        ),
    )
    assert inspection.ok is True
    assert expansions.get(scope.command_id) is not None

    drifted_context = replace(
        scope.current_context,
        unavailable_route_ids=frozenset({"route.primary"}),
    )
    scopes.scope = replace(scope, current_context=drifted_context)
    current_snapshot = resolve_tool_affordance_snapshot(
        drifted_context,
        snapshot_id="current-route-observation",
        created_at="2026-08-21T00:00:03+00:00",
    )
    current = next(
        (
            affordance
            for affordance in current_snapshot.affordances
            if affordance.tool_name == "example.observe"
        ),
        None,
    )
    assert current is not None
    assert current.route_ids == ("route.adjacent",)

    result = gateway.invoke(
        command_id=scope.command_id,
        request=RuntimeToolRequest(
            request_id="expanded-route-request-1",
            invocation=ToolInvocation(
                call_id="expanded-route-call-1",
                tool_name="example.observe",
                arguments={},
                session_id="session-1",
                agent_member_id="member-1",
                task_id="task-1",
                route_id="route.primary",
                affordance_snapshot_digest=scope.snapshot.snapshot_digest,
            ),
            affordance_snapshot_digest=scope.snapshot.snapshot_digest,
        ),
    )

    assert result.error_code == "tool_affordance_stale"
    assert result.payload["effect_certainty"] == "no_effect"
    assert result.payload["mutation_applied"] is False
    assert result.payload["fallback_performed"] is False
    assert result.payload["retry_performed"] is False
    assert runtime.calls == 0


def test_expanded_deferred_dispatch_rejects_exact_runtime_drift_without_fallback() -> (
    None
):
    scope = _exposed_scope()
    observe = scope.catalog.get("example.observe")
    capabilities = scope.catalog.get("capabilities.inspect")
    assert observe is not None
    assert capabilities is not None
    runtime = _Runtime(observe.contract)
    expansions = InMemoryCommandToolExpansionStore()
    gateway = MountedRuntimeCapabilityGateway(
        scopes=_Scopes(scope),
        runtimes=(
            (
                "capabilities.inspect",
                KernelCapabilitiesInspectRuntime(capabilities.contract),
            ),
            ("example.observe", runtime),
        ),
        expansions=expansions,
        clock=DeterministicClock(datetime(2026, 8, 21, 0, 0, 2, tzinfo=UTC)),
    )
    inspection = gateway.invoke(
        command_id=scope.command_id,
        request=RuntimeToolRequest(
            request_id="inspection-runtime-request-1",
            invocation=ToolInvocation(
                call_id="inspection-runtime-call-1",
                tool_name="capabilities.inspect",
                arguments={"expand_tool_names": ["example.observe"]},
                session_id="session-1",
                agent_member_id="member-1",
                task_id="task-1",
                affordance_snapshot_digest=scope.snapshot.snapshot_digest,
            ),
            affordance_snapshot_digest=scope.snapshot.snapshot_digest,
        ),
    )
    assert inspection.ok is True

    drifted_runtime = _Runtime(
        observe.contract,
        owner_plugin_id="adjacent.plugin",
        runtime_id="adjacent.plugin.observe@1",
    )
    gateway.runtimes = (
        (
            "capabilities.inspect",
            KernelCapabilitiesInspectRuntime(capabilities.contract),
        ),
        ("example.observe", drifted_runtime),
    )
    result = gateway.invoke(command_id=scope.command_id, request=_request(scope))

    assert result.error_code == "tool_runtime_not_mounted"
    assert result.payload["effect_certainty"] == "no_effect"
    assert result.payload["mutation_applied"] is False
    assert result.payload["fallback_performed"] is False
    assert result.payload["retry_performed"] is False
    assert runtime.calls == 0
    assert drifted_runtime.calls == 0


def test_provider_step_revalidation_rejects_revoked_workflow_epoch() -> None:
    scope = _exposed_scope()
    current = scope.current_workflow_authority
    assert current is not None
    revoked = replace(
        current,
        status=WorkflowAuthorityStatus.REVOKED,
        state_version=current.state_version + 1,
        updated_at="2026-08-21T00:00:02+00:00",
        revoked_at="2026-08-21T00:00:02+00:00",
    )
    scope = replace(scope, current_workflow_authority=revoked)
    gateway = MountedRuntimeCapabilityGateway(scopes=_Scopes(scope), runtimes=())
    exposure = scope.exposure_snapshot
    assert exposure is not None

    with pytest.raises(KernelContractError) as raised:
        gateway.revalidate_provider_step(
            command_id=scope.command_id,
            workflow_authority_id=exposure.workflow_authority_id,
            workflow_authority_epoch=exposure.workflow_authority_epoch,
            workflow_authority_digest=exposure.workflow_authority_digest,
            tool_exposure_snapshot_id=exposure.exposure_snapshot_id,
            tool_exposure_snapshot_digest=exposure.exposure_snapshot_digest,
        )

    assert raised.value.code == "runtime_turn_fence_stale"
