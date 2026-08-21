from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import subprocess
import sys
from typing import Any

import httpx
from openzyme_contracts import FILE_WORKSPACE_CORE_SECTION_FIELDS
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import ToolResult
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import HttpRouteInvocation
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_extension_spi import KernelQueryContext
from openzyme_kernel import KernelCoreProjectionSource
from openzyme_host_api import FileWorkspaceV2HostSurface
from openzyme_host_api import HostSecurityPolicy
from openzyme_host_api import HostV2CommandError
from openzyme_host_api import HostV2Dependencies
from openzyme_host_api import HostV2MutationInvocation
from openzyme_host_api import HostV2SessionBootstrapInvocation
from openzyme_host_api import create_v2_app


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _release() -> LayeredReleaseIdentity:
    return LayeredReleaseIdentity(
        kernel_contract_digest=_digest("kernel"),
        core_schema_digest=_digest("core-schema"),
        adapter_bundle_digest=_digest("adapters"),
        extension_bundle_digest=_digest("extensions"),
        declared_tool_catalog_digest=_digest("tools"),
        route_catalog_digest=_digest("routes"),
        projection_catalog_digest=_digest("projections"),
        migration_catalog_digest=_digest("migrations"),
        workspace_backend_digest=_digest("workspace"),
        host_build_digest=_digest("host"),
        client_build_digest=_digest("client"),
    )


@dataclass(frozen=True)
class _CoreProvider:
    release: LayeredReleaseIdentity

    def inspect(
        self,
        *,
        session_id: str,
        actor_id: str,
        correlation_id: str,
    ) -> KernelCoreProjectionSource:
        binding_digest = _digest(f"binding:{session_id}:{actor_id}")
        snapshot_digest = _digest(f"affordance:{session_id}:{actor_id}")
        arrays = {
            "tasks",
            "lanes",
            "agents",
            "approvals",
            "authority_leases",
            "publications",
        }
        core: dict[str, object] = {
            field: [] if field in arrays else {}
            for field in FILE_WORKSPACE_CORE_SECTION_FIELDS
        }
        core["session"] = {
            "session_id": session_id,
            "project_id": "project-1",
        }
        core["capability_binding"] = {"binding_digest": binding_digest}
        core["tool_reflection"] = {
            "declared_tool_catalog_digest": (self.release.declared_tool_catalog_digest),
            "capability_binding_digest": binding_digest,
            "affordance_snapshot_digest": snapshot_digest,
            "available_tool_names": [],
            "affordances": [],
        }
        return KernelCoreProjectionSource(
            context=KernelQueryContext(
                session_id=session_id,
                actor_id=actor_id,
                owner_plugin_id="openzyme.kernel",
                authority_lease_id="lease-public-query",
                extension_bundle_digest=self.release.extension_bundle_digest,
                capability_binding_digest=binding_digest,
                correlation_id=correlation_id,
            ),
            core_payload=core,
        )


@dataclass
class _CommandGateway:
    invocations: list[HostV2MutationInvocation]
    bootstraps: list[HostV2SessionBootstrapInvocation]

    def bootstrap(
        self,
        invocation: HostV2SessionBootstrapInvocation,
    ) -> KernelMutationReceipt:
        self.bootstraps.append(invocation)
        return KernelMutationReceipt.create(
            command_id=invocation.idempotency_key,
            service_id="test.kernel.gateway",
            operation="session.bootstrap",
            mutation_applied=True,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            result={"session_id": invocation.session_id},
        )

    def invoke(self, invocation: HostV2MutationInvocation) -> KernelMutationReceipt:
        self.invocations.append(invocation)
        return KernelMutationReceipt.create(
            command_id=invocation.idempotency_key,
            service_id="test.kernel.gateway",
            operation=invocation.route_id,
            mutation_applied=True,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            result={"accepted": True},
        )


@dataclass
class _UncertainCommandGateway:
    invocations: list[HostV2MutationInvocation]

    def bootstrap(
        self,
        invocation: HostV2SessionBootstrapInvocation,
    ) -> KernelMutationReceipt:
        raise AssertionError(invocation)

    def invoke(self, invocation: HostV2MutationInvocation) -> KernelMutationReceipt:
        self.invocations.append(invocation)
        raise HostV2CommandError(
            "runtime_dispatch_in_doubt",
            "runtime command dispatch cannot yet be reconciled",
            status_code=503,
            mutation_applied=None,
            effect_certainty="dispatch_in_doubt",
            details={"retry_performed": False},
        )


@dataclass(frozen=True)
class _ExtensionRoute:
    route_id: str = "test.plugin.http-view@1"
    owner_plugin_id: str = "test.plugin"
    method: str = "GET"
    path: str = "/v3/extensions/test.plugin/sessions/{session_id}"
    contract_digest: str = "sha256:" + "7" * 64

    def invoke(self, invocation: HttpRouteInvocation) -> ToolResult:
        return ToolResult(
            call_id=invocation.context.correlation_id,
            tool_name=self.route_id,
            ok=True,
            status="observed",
            summary="bounded extension view",
            payload={
                "session_id": invocation.context.session_id,
                "actor_id": invocation.context.actor_id,
            },
        )


def _surface() -> FileWorkspaceV2HostSurface:
    release = _release()
    return FileWorkspaceV2HostSurface(
        release=release,
        core_provider=_CoreProvider(release),
        projection_contributors=(),
        authorized_projection_contracts={},
        activation_digest=_digest("activation"),
        runtime_mount_digest=_digest("mount"),
    )


def _base_headers() -> dict[str, str]:
    return {
        "Accept": FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
        "OpenZyme-Workspace-Contract": "file_workspace_public@2",
        "X-Request-Id": "request-v2-test",
    }


@dataclass(frozen=True)
class _AppClient:
    app: Any

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        async def invoke() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app),
                base_url="http://testserver",
            ) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(invoke())

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, **kwargs)


def _app(gateway: _CommandGateway) -> _AppClient:
    return _AppClient(
        create_v2_app(
            HostV2Dependencies(
                security_policy=HostSecurityPolicy.from_settings(None),
                workspace_surface=_surface(),
                command_gateway=gateway,
                http_routes=(_ExtensionRoute(),),
            )
        )
    )


def _gateway() -> _CommandGateway:
    return _CommandGateway([], [])


def _mutation_headers(inspected: object) -> dict[str, str]:
    headers = {
        **_base_headers(),
        "Idempotency-Key": "message-command-1",
        "Content-Type": "application/json",
    }
    for name in (
        "OpenZyme-Release-Digest",
        "OpenZyme-Public-Contract-Digest",
        "OpenZyme-Projection-Digest",
        "OpenZyme-Capability-Binding-Digest",
        "OpenZyme-Affordance-Snapshot-Digest",
    ):
        headers[name] = inspected.headers[name]  # type: ignore[attr-defined]
    return headers


def test_generic_v2_host_bootstraps_before_a_session_projection_exists() -> None:
    gateway = _gateway()
    surface = _surface()
    client = _app(gateway)
    response = client.post(
        "/v3/sessions",
        headers={
            **_base_headers(),
            "Content-Type": "application/json",
            "Idempotency-Key": "bootstrap-session-2",
            "OpenZyme-Release-Digest": surface.release.release_digest,
            "OpenZyme-Public-Contract-Digest": (
                FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
            ),
        },
        json={
            "session_id": "session-2",
            "project_id": "project-1",
            "title": "Plugin-free Standard",
            "objective": "Prove the Kernel path",
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["OpenZyme-Release-Digest"] == (
        surface.release.release_digest
    )
    assert response.json()["operation"] == "session.bootstrap"
    assert len(gateway.bootstraps) == 1
    assert gateway.bootstraps[0].actor_id == "user:local-dev"
    assert gateway.invocations == []


def test_generic_v2_host_serves_closed_projection_and_bound_mutation() -> None:
    gateway = _gateway()
    client = _app(gateway)
    inspected = client.get(
        "/v3/sessions/session-1/workspace",
        headers=_base_headers(),
    )
    assert inspected.status_code == 200, inspected.text
    assert inspected.headers["content-type"] == FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE

    mutated = client.post(
        "/v3/sessions/session-1/messages",
        headers=_mutation_headers(inspected),
        json={"message": "continue"},
    )

    assert mutated.status_code == 200, mutated.text
    assert mutated.json()["mutation_applied"] is True
    assert len(gateway.invocations) == 1
    assert gateway.invocations[0].route_id == "openzyme.kernel.message.send@2"
    assert gateway.invocations[0].precondition.query_context.session_id == "session-1"


def test_generic_v2_host_mounts_only_injected_extension_query_runtime() -> None:
    gateway = _gateway()
    client = _app(gateway)
    response = client.get(
        "/v3/extensions/test.plugin/sessions/session-1",
        headers=_base_headers(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["payload"] == {
        "actor_id": "user:local-dev",
        "session_id": "session-1",
    }
    assert gateway.invocations == []


def test_generic_v2_host_dispatches_closed_nested_kernel_route_by_identity() -> None:
    gateway = _gateway()
    client = _app(gateway)
    inspected = client.get(
        "/v3/sessions/session-1/workspace",
        headers=_base_headers(),
    )
    response = client.post(
        "/v3/sessions/session-1/tasks/task-1/finish",
        headers=_mutation_headers(inspected),
        json={"evidence_refs": []},
    )

    assert response.status_code == 200, response.text
    assert gateway.invocations[0].route_id == "openzyme.kernel.task.finish@2"
    assert gateway.invocations[0].path.endswith("/tasks/task-1/finish")


def test_generic_v2_host_rejects_stale_mutation_before_gateway() -> None:
    gateway = _gateway()
    client = _app(gateway)
    response = client.post(
        "/v3/sessions/session-1/runtime/drain",
        headers={
            **_base_headers(),
            "Idempotency-Key": "drain-command-1",
            "OpenZyme-Release-Digest": _digest("stale"),
        },
        json={"max_signals": 1, "max_steps_per_agent": 1},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == (
        "file_workspace_v2_mutation_identity_stale"
    )
    assert response.json()["error"]["mutation_applied"] is False
    assert gateway.invocations == []


def test_generic_v2_host_preserves_gateway_unknown_effect_without_retry() -> None:
    gateway = _UncertainCommandGateway([])
    dependencies = HostV2Dependencies(
        security_policy=HostSecurityPolicy.from_settings(None),
        workspace_surface=_surface(),
        command_gateway=gateway,
    )
    client = _AppClient(create_v2_app(dependencies))
    inspected = client.get(
        "/v3/sessions/session-1/workspace",
        headers=_base_headers(),
    )
    response = client.post(
        "/v3/sessions/session-1/runtime/drain",
        headers=_mutation_headers(inspected),
        json={"max_signals": 1, "max_steps_per_agent": 1},
    )

    assert response.status_code == 503
    assert response.json()["error"]["mutation_applied"] is None
    assert response.json()["error"]["effect_certainty"] == "dispatch_in_doubt"
    assert response.json()["error"]["fallback_performed"] is False
    assert len(gateway.invocations) == 1


def test_root_import_does_not_load_legacy_runtime_or_product_modules() -> None:
    forbidden = {
        "openzyme_runtime",
        "openzyme_science",
        "openzyme_hpc",
        "openzyme_execution",
        "mcp_hpc_runner",
    }
    script = (
        "import json, sys; import openzyme_host_api; "
        f"print(json.dumps(sorted(set({sorted(forbidden)!r}).intersection(sys.modules))))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == []
