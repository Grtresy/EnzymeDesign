from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Any

import httpx
from openzyme_contracts import FILE_WORKSPACE_CORE_SECTION_FIELDS
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_extension_spi import KernelQueryContext
from openzyme_kernel import KernelCoreProjectionSource

from .file_workspace_v2 import FileWorkspaceV2HostSurface
from .security import HostSecurityPolicy
from .v2_app import HostV2Dependencies
from .v2_app import HostV2MutationInvocation
from .v2_app import HostV2SessionBootstrapInvocation
from .v2_app import create_v2_app


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _release() -> LayeredReleaseIdentity:
    return LayeredReleaseIdentity(
        kernel_contract_digest=_digest("eval-kernel"),
        core_schema_digest=_digest("eval-core-schema"),
        adapter_bundle_digest=_digest("eval-adapters"),
        extension_bundle_digest=_digest("eval-extension-bundle"),
        declared_tool_catalog_digest=_digest("eval-declared-tools"),
        route_catalog_digest=_digest("eval-routes"),
        projection_catalog_digest=_digest("eval-projections"),
        migration_catalog_digest=_digest("eval-migrations"),
        workspace_backend_digest=_digest("eval-workspace-backend"),
        host_build_digest=_digest("eval-host"),
        client_build_digest=_digest("eval-client"),
    )


@dataclass(frozen=True, slots=True)
class _EvalCoreProvider:
    release: LayeredReleaseIdentity

    def inspect(
        self,
        *,
        session_id: str,
        actor_id: str,
        correlation_id: str,
    ) -> KernelCoreProjectionSource:
        binding_digest = _digest(f"binding:{session_id}:{actor_id}")
        affordance_digest = _digest(f"affordance:{session_id}:{actor_id}")
        array_sections = {
            "tasks",
            "lanes",
            "agents",
            "approvals",
            "authority_leases",
            "publications",
        }
        payload: dict[str, object] = {
            field: [] if field in array_sections else {}
            for field in FILE_WORKSPACE_CORE_SECTION_FIELDS
        }
        payload["session"] = {
            "session_id": session_id,
            "project_id": "project-eval",
            "resident_readiness": {
                "schema_version": "resident_teammate_readiness@1",
                "readiness": "ready",
                "workspace_id": "workspace-eval",
                "workspace_generation": 1,
                "provisioning_intent_id": "provisioning-eval",
                "provisioning_intent_digest": _digest("provisioning-eval"),
                "failure_id": None,
                "next_action": "message_or_drain",
            },
        }
        payload["conversation"] = {
            "messages": [],
            "memories": [],
            "transcript": {
                "schema_version": "ordered_transcript@1",
                "messages": [],
                "transcript_digest": canonical_sha256_digest(
                    {
                        "schema_version": "ordered_transcript@1",
                        "messages": [],
                    }
                ),
            },
        }
        payload["protocol"] = {"records": [], "inbox": []}
        payload["operations"] = {
            "controlled": [],
            "continuations": [],
            "publication_intents": [],
            "task_evidence": [],
            "command_receipts": [],
        }
        payload["failures"] = {"observations": []}
        payload["runtime"] = {
            "commands": [],
            "signals": [],
            "session_leases": [],
            "turn_commands": [],
            "continuation_intents": [],
            "settlement_intents": [],
            "outcome_consumptions": [],
            "outcomes": [],
            "workflow_authority": {
                "schema_version": "workflow_authority_projection@1",
                "bindings": [],
                "signal_links": [],
            },
        }
        payload["workspace"] = {
            "generations": [],
            "runtime_bindings": [],
            "repository_binding_pins": [],
            "checkpoints": [],
            "revision_path_verifications": [],
            "provisioning": {
                "schema_version": "workspace_provisioning_public@2",
                "intent_id": "provisioning-eval",
                "intent_digest": _digest("provisioning-eval"),
                "intent_state_version": 2,
                "status": "ready",
                "workspace_id": "workspace-eval",
                "workspace_generation": 1,
                "runtime_binding_id": "runtime-binding-eval",
                "failure_id": None,
                "error_code": None,
                "effect_certainty": "effect_known",
                "mutation_applied": True,
                "fallback_performed": False,
                "retry_permitted": False,
                "reconcile_required": False,
                "diagnostic_id": None,
                "next_action": "message_or_drain",
                "reconciliation": None,
            },
        }
        payload["capability_binding"] = {
            "binding_revision": 1,
            "binding_digest": binding_digest,
        }
        payload["tool_reflection"] = {
            "declared_tool_catalog_digest": (
                self.release.declared_tool_catalog_digest
            ),
            "capability_binding_digest": binding_digest,
            "affordance_snapshot_digest": affordance_digest,
            "available_tool_names": [],
            "affordances": [],
            "tool_exposure": {
                "schema_version": "tool_exposure_public@1",
                "exposure_snapshot_id": "exposure-eval",
                "exposure_snapshot_digest": _digest("exposure-eval"),
                "direct_tool_names": [],
                "deferred_tool_names": [],
                "command_expansions": [],
            },
        }
        return KernelCoreProjectionSource(
            context=KernelQueryContext(
                session_id=session_id,
                actor_id=actor_id,
                owner_plugin_id="openzyme.kernel",
                authority_lease_id="lease-eval-query",
                extension_bundle_digest=self.release.extension_bundle_digest,
                capability_binding_digest=binding_digest,
                correlation_id=correlation_id,
            ),
            core_payload=payload,
        )


@dataclass(slots=True)
class _EvalCommandGateway:
    bootstrap_count: int = 0
    mutation_count: int = 0

    def bootstrap(
        self,
        invocation: HostV2SessionBootstrapInvocation,
    ) -> KernelMutationReceipt:
        self.bootstrap_count += 1
        return KernelMutationReceipt.create(
            command_id=invocation.idempotency_key,
            service_id="openzyme.eval.kernel-gateway",
            operation="session.bootstrap",
            mutation_applied=True,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            result={
                "session_id": invocation.session_id,
                "workspace_readiness": "provisioning",
                "runtime_executed": False,
                "task_transition_performed": False,
                "fallback_performed": False,
            },
        )

    def invoke(self, invocation: HostV2MutationInvocation) -> KernelMutationReceipt:
        self.mutation_count += 1
        return KernelMutationReceipt.create(
            command_id=invocation.idempotency_key,
            service_id="openzyme.eval.kernel-gateway",
            operation=invocation.route_id,
            mutation_applied=True,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            result={
                "accepted": True,
                "runtime_executed": False,
                "task_transition_performed": False,
                "fallback_performed": False,
            },
        )


async def run_eval() -> dict[str, Any]:
    """Exercise the exact generic Host @2 boundary without external effects."""

    release = _release()
    surface = FileWorkspaceV2HostSurface(
        release=release,
        core_provider=_EvalCoreProvider(release),
        projection_contributors=(),
        authorized_projection_contracts={},
        activation_digest=_digest("eval-activation"),
        runtime_mount_digest=_digest("eval-runtime-mount"),
    )
    gateway = _EvalCommandGateway()
    app = create_v2_app(
        HostV2Dependencies(
            security_policy=HostSecurityPolicy.from_settings(None),
            workspace_surface=surface,
            command_gateway=gateway,
        )
    )
    base_headers = {
        "Accept": FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
        "OpenZyme-Workspace-Contract": "file_workspace_public@2",
        "X-Request-Id": "host-v2-eval",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://openzyme-eval.invalid",
    ) as client:
        bootstrap = await client.post(
            "/v3/sessions",
            headers={
                **base_headers,
                "Content-Type": "application/json",
                "Idempotency-Key": "eval-bootstrap-1",
                "OpenZyme-Release-Digest": release.release_digest,
                "OpenZyme-Public-Contract-Digest": (
                    FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
                ),
            },
            json={"session_id": "session-eval"},
        )
        bootstrap.raise_for_status()

        inspected = await client.get(
            "/v3/sessions/session-eval/workspace",
            headers=base_headers,
        )
        inspected.raise_for_status()
        mutation_headers = {
            **base_headers,
            "Content-Type": "application/json",
            "Idempotency-Key": "eval-message-1",
        }
        for name in (
            "OpenZyme-Release-Digest",
            "OpenZyme-Public-Contract-Digest",
            "OpenZyme-Projection-Digest",
            "OpenZyme-Capability-Binding-Digest",
            "OpenZyme-Affordance-Snapshot-Digest",
        ):
            mutation_headers[name] = inspected.headers[name]

        stale_headers = {
            **mutation_headers,
            "Idempotency-Key": "eval-message-stale",
            "OpenZyme-Affordance-Snapshot-Digest": _digest("stale"),
        }
        stale = await client.post(
            "/v3/sessions/session-eval/messages",
            headers=stale_headers,
            json={"content": "must not dispatch"},
        )
        if stale.status_code != 409:
            raise RuntimeError("Host @2 eval expected stale identity rejection")
        stale_body = stale.json()
        if stale_body.get("error", {}).get("code") != (
            "file_workspace_v2_mutation_identity_stale"
        ):
            raise RuntimeError("Host @2 eval observed an unexpected stale error")
        if gateway.mutation_count != 0:
            raise RuntimeError("stale Host @2 mutation reached the Kernel gateway")

        accepted = await client.post(
            "/v3/sessions/session-eval/messages",
            headers=mutation_headers,
            json={"message": "bounded eval", "workflow_refs": []},
        )
        accepted.raise_for_status()
        if bootstrap.status_code != 202 or accepted.status_code != 202:
            raise RuntimeError("Host @2 eval expected asynchronous admission status")
        if accepted.json().get("result", {}).get("runtime_executed") is not False:
            raise RuntimeError("Host @2 message admission executed runtime synchronously")

    projection = inspected.json()
    core = projection["core"]
    reflection = core["tool_reflection"]
    return {
        "schema_version": "openzyme_host_v2_eval@1",
        "status": "passed",
        "public_contract": "file_workspace_public@2",
        "public_contract_digest": FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST,
        "release_digest": release.release_digest,
        "extension_bundle_digest": release.extension_bundle_digest,
        "declared_tool_catalog_digest": (
            reflection["declared_tool_catalog_digest"]
        ),
        "capability_binding_digest": reflection["capability_binding_digest"],
        "affordance_snapshot_digest": reflection["affordance_snapshot_digest"],
        "workspace_backend_digest": release.workspace_backend_digest,
        "bootstrap_count": gateway.bootstrap_count,
        "accepted_mutation_count": gateway.mutation_count,
        "stale_mutation_rejected_before_dispatch": True,
        "external_effect_performed": False,
        "fallback_performed": False,
    }


def main() -> None:
    print(json.dumps(asyncio.run(run_eval()), sort_keys=True))


if __name__ == "__main__":
    main()
