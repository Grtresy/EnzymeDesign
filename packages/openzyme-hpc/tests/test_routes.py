from __future__ import annotations

from dataclasses import dataclass

from openzyme_contracts import ExternalEffectCertainty
from openzyme_extension_spi import CapabilityRouteInvocation
from openzyme_extension_spi import KernelCommandContext
from openzyme_hpc import HPC_WORKSPACE_ROUTE_ID
from openzyme_hpc import build_hpc_capability_route_runtimes


DIGEST = "sha256:" + "d" * 64


@dataclass
class Application:
    calls: int = 0

    def invoke_route(self, *, invocation):
        self.calls += 1
        return {
            "capability_id": invocation.capability_id,
            "effect_certainty": ExternalEffectCertainty.NO_EFFECT.value,
        }


def _invocation(*, route_id: str, capability_id: str) -> CapabilityRouteInvocation:
    return CapabilityRouteInvocation(
        context=KernelCommandContext(
            command_id="command-1",
            session_id="session-1",
            actor_id="member-1",
            owner_plugin_id="openzyme.hpc",
            authority_lease_id="lease-1",
            authority_generation=1,
            authority_fence=1,
            expected_session_version=1,
            extension_bundle_digest=DIGEST,
            capability_binding_digest=DIGEST,
            idempotency_key="route-1",
            correlation_id="correlation-1",
            route_id=route_id,
        ),
        route_id=route_id,
        capability_id=capability_id,
        payload={},
    )


def test_workspace_route_forwards_only_declared_capability_without_fallback() -> None:
    application = Application()
    runtime = {
        item.route_id: item
        for item in build_hpc_capability_route_runtimes(application)
    }[HPC_WORKSPACE_ROUTE_ID]

    result = runtime.invoke(
        _invocation(
            route_id=HPC_WORKSPACE_ROUTE_ID,
            capability_id="openzyme.hpc.workspace",
        )
    )

    assert result.ok is True
    assert result.payload["route_id"] == HPC_WORKSPACE_ROUTE_ID
    assert result.payload["fallback_performed"] is False
    assert application.calls == 1


def test_route_rejects_undeclared_capability_before_application_call() -> None:
    application = Application()
    runtime = {
        item.route_id: item
        for item in build_hpc_capability_route_runtimes(application)
    }[HPC_WORKSPACE_ROUTE_ID]

    result = runtime.invoke(
        _invocation(
            route_id=HPC_WORKSPACE_ROUTE_ID,
            capability_id="software.hmmer",
        )
    )

    assert result.ok is False
    assert result.error_code == "hpc_route_capability_mismatch"
    assert result.payload["mutation_applied"] is False
    assert application.calls == 0
