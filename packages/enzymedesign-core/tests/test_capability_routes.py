from __future__ import annotations

from dataclasses import dataclass

from enzymedesign_core import ExactProductCapabilityRouteRuntime
from openzyme_extension_spi import CapabilityRouteInvocation
from openzyme_extension_spi import KernelCommandContext


DIGEST = "sha256:" + "1" * 64


@dataclass
class _Application:
    calls: int = 0

    def invoke_route(self, *, invocation, driver_id):
        self.calls += 1
        return {"state": "compiled", "observed_driver_id": driver_id}


def _invocation(*, route_id: str, capability_id: str) -> CapabilityRouteInvocation:
    return CapabilityRouteInvocation(
        context=KernelCommandContext(
            command_id="command-1",
            session_id="session-1",
            actor_id="agent-1",
            owner_plugin_id="enzymedesign.example",
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
        payload={"request": "bounded"},
    )


def test_exact_product_route_delegates_without_fallback_or_task_terminal() -> None:
    application = _Application()
    runtime = ExactProductCapabilityRouteRuntime(
        route_id="enzymedesign.example.local@1",
        owner_plugin_id="enzymedesign.example",
        driver_id="enzymedesign.example.local",
        capability_ids=("enzymedesign.example",),
        application=application,
    )

    result = runtime.invoke(
        _invocation(
            route_id="enzymedesign.example.local@1",
            capability_id="enzymedesign.example",
        )
    )

    assert result.ok is True
    assert result.payload["driver_id"] == "enzymedesign.example.local"
    assert result.payload["fallback_performed"] is False
    assert result.payload["task_finished"] is False
    assert application.calls == 1


def test_exact_product_route_rejects_identity_or_capability_drift() -> None:
    application = _Application()
    runtime = ExactProductCapabilityRouteRuntime(
        route_id="enzymedesign.example.local@1",
        owner_plugin_id="enzymedesign.example",
        driver_id="enzymedesign.example.local",
        capability_ids=("enzymedesign.example",),
        application=application,
    )

    wrong_route = runtime.invoke(
        _invocation(
            route_id="enzymedesign.example.other@1",
            capability_id="enzymedesign.example",
        )
    )
    wrong_capability = runtime.invoke(
        _invocation(
            route_id="enzymedesign.example.local@1",
            capability_id="enzymedesign.other",
        )
    )

    assert wrong_route.error_code == "product_route_identity_mismatch"
    assert wrong_capability.error_code == "product_route_capability_mismatch"
    assert application.calls == 0
