from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace

import pytest

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import ComponentIdentity
from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import DistributionManifest
from openzyme_extension_spi import KernelSelection
from openzyme_extension_spi import PluginManifest
from openzyme_extension_spi import PluginRequirementMode
from openzyme_extension_spi import PluginSelection
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


def _scope() -> RuntimeToolScope:
    spec = ToolSpec(
        tool_name="example.observe",
        description="Observe one example.",
        input_schema={"type": "object", "additionalProperties": False},
        output_schema={"type": "object"},
    )
    plugin = PluginManifest(
        identity=_identity("example.plugin", ComponentKind.PLUGIN),
        required_kernel_contract="openzyme.kernel@1",
        required_extension_spi_contract="openzyme.extension-spi@1",
        tools=(
            ToolContribution(
                owner_plugin_id="example.plugin",
                runtime_id="example.plugin.observe@1",
                contract=spec,
            ),
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


def _request(scope: RuntimeToolScope, *, digest: str | None = None) -> RuntimeToolRequest:
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
