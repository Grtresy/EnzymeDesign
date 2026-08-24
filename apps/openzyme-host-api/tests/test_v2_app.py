from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import subprocess
import sys
from typing import Any

import httpx
import pytest
from openzyme_contracts import FILE_WORKSPACE_CORE_SECTION_FIELDS
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import ToolResult
from openzyme_contracts import (
    WORKSPACE_PROVISIONING_RECONCILIATION_ADMISSION_RESULT_FIELDS,
)
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import HttpRouteInvocation
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_extension_spi import KernelQueryContext
from openzyme_kernel import KernelCoreProjectionSource
from openzyme_host_api import FileWorkspaceV2HostSurface
from openzyme_host_api import HostPrincipal
from openzyme_host_api import HostSecurityPolicy
from openzyme_host_api import HostV2CommandError
from openzyme_host_api import HostV2Dependencies
from openzyme_host_api import HostV2MutationInvocation
from openzyme_host_api import HostV2SessionBootstrapInvocation
from openzyme_host_api import HostV2WorkspaceProvisioningReconciliationInvocation
from openzyme_host_api import HostV2WorkspaceProvisioningSuccessorInvocation
from openzyme_host_api import create_v2_app


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _public_failure(
    failure_id: str,
    *,
    session_id: str,
    effect_certainty: str,
) -> dict[str, object]:
    uncertain = effect_certainty == "dispatch_in_doubt"
    return {
        "schema_version": "failure_observation@2",
        "failure_id": failure_id,
        "session_id": session_id,
        "source_kind": "workspace_provisioning",
        "source_ref": "provisioning-1",
        "source_version": _digest(failure_id),
        "phase": "settlement",
        "failure_class": "controlled_effect",
        "recoverability": ("reconciliation_required" if uncertain else "terminal"),
        "effect_certainty": effect_certainty,
        "retry_eligibility": "reconcile_required" if uncertain else "terminal",
        "actor_kind": "system",
        "error_code": "workspace_provisioning_failed",
        "safe_summary": "Workspace provisioning did not settle successfully.",
        "facts": {
            "fallback_performed": False,
            "reconcile_required": uncertain,
            **({} if uncertain else {"mutation_applied": False}),
        },
        "likely_causes": [],
        "evidence_refs": [],
        "created_at": "2026-08-24T00:00:00Z",
        "task_id": None,
        "lane_id": None,
        "agent_id": None,
        "safe_hint": "Inspect the public recovery state.",
        "component": "workspace_provisioning",
        "operation": "settle",
        "identities": {"session_id": session_id},
        "mutation_applied": None if uncertain else False,
        "fallback_performed": False,
        "cause_chain": [],
        "diagnostic_id": f"diagnostic-{failure_id}",
        "next_action": (
            "reconcile_workspace_provisioning"
            if uncertain
            else "create_successor_workspace_generation"
        ),
    }


def _runtime_command_failure(*, session_id: str) -> dict[str, object]:
    return {
        "schema_version": "failure_observation@2",
        "failure_id": "failure-runtime-drain-1",
        "session_id": session_id,
        "source_kind": "runtime_command",
        "source_ref": "runtime-drain-1",
        "source_version": _digest("runtime-drain-claimed-1"),
        "phase": "runtime_context_projection",
        "failure_class": "harness",
        "recoverability": "terminal",
        "effect_certainty": "no_effect",
        "retry_eligibility": "terminal",
        "actor_kind": "system",
        "error_code": "runtime_context_identity_stale",
        "safe_summary": "Runtime context projection failed before provider invocation.",
        "facts": {
            "mutation_applied": False,
            "fallback_performed": False,
            "retry_performed": False,
            "retry_eligibility": "terminal",
            "reconcile_required": False,
        },
        "likely_causes": [],
        "evidence_refs": [],
        "created_at": "2026-08-24T00:00:01Z",
        "task_id": None,
        "lane_id": None,
        "agent_id": None,
        "safe_hint": "Inspect the exact diagnostic; no provider or fallback ran.",
        "component": "openzyme.standard.runtime_worker",
        "operation": "runtime_command_execute",
        "identities": {
            "command_id": "runtime-drain-1",
            "session_id": session_id,
        },
        "mutation_applied": False,
        "fallback_performed": False,
        "cause_chain": [],
        "diagnostic_id": "diagnostic-runtime-drain-1",
        "next_action": "inspect_runtime_command_diagnostic",
    }


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
    readiness: str = "ready"
    runtime_status: str = "accepted"

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
            "resident_readiness": {
                "schema_version": "resident_teammate_readiness@1",
                "readiness": "ready",
                "workspace_id": "workspace-1",
                "workspace_generation": 1,
                "provisioning_intent_id": "provisioning-1",
                "provisioning_intent_digest": _digest("provisioning-1"),
                "failure_id": None,
                "next_action": "message_or_drain",
            },
        }
        core["conversation"] = {
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
        core["protocol"] = {"records": [], "inbox": []}
        core["operations"] = {
            "controlled": [],
            "continuations": [],
            "publication_intents": [],
            "task_evidence": [],
            "command_receipts": [],
        }
        runtime_failed = self.runtime_status == "failed"
        core["failures"] = {
            "observations": (
                [_runtime_command_failure(session_id=session_id)]
                if runtime_failed
                else []
            )
        }
        core["capability_binding"] = {"binding_digest": binding_digest}
        core["runtime"] = {
            "commands": [
                {
                    "schema_version": "runtime_command_public@1",
                    "command_id": "runtime-drain-1",
                    "session_id": session_id,
                    "command_type": "runtime.drain",
                    "request_digest": _digest("runtime-drain-1"),
                    "idempotency_key": "runtime-drain-1",
                    "status": self.runtime_status,
                    "max_signals": 3,
                    "max_steps_per_agent": 8,
                    "auto_enqueue_ready_tasks": False,
                    "state_version": 3 if runtime_failed else 1,
                    "fencing_token": 1 if runtime_failed else 0,
                    "accepted_at": "2026-08-24T00:00:00Z",
                    "claim_owner": "runtime-worker-1" if runtime_failed else None,
                    "lease_expires_at": (
                        "2026-08-24T00:10:00Z" if runtime_failed else None
                    ),
                    "bounded_outcome_summary": (
                        {
                            "schema_version": (
                                "runtime_command_outcome_summary_public@1"
                            ),
                            "processed_signals": 0,
                            "turn_count": 0,
                            "turns_digest": canonical_sha256_digest([]),
                            "runtime_executed": False,
                            "task_transition_performed": False,
                            "fallback_performed": False,
                        }
                        if runtime_failed
                        else None
                    ),
                    "failure_id": (
                        "failure-runtime-drain-1" if runtime_failed else None
                    ),
                    "diagnostic_id": (
                        "diagnostic-runtime-drain-1" if runtime_failed else None
                    ),
                    "error_code": (
                        "runtime_context_identity_stale" if runtime_failed else None
                    ),
                    "safe_error_summary": (
                        "Runtime context projection failed before provider invocation."
                        if runtime_failed
                        else None
                    ),
                    "safe_retry_hint": (
                        "Inspect the exact diagnostic; no provider or fallback ran."
                        if runtime_failed
                        else None
                    ),
                    "started_at": ("2026-08-24T00:00:00Z" if runtime_failed else None),
                    "completed_at": (
                        "2026-08-24T00:00:01Z" if runtime_failed else None
                    ),
                }
            ],
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
        core["workspace"] = {
            "generations": [],
            "runtime_bindings": [],
            "repository_binding_pins": [],
            "checkpoints": [],
            "revision_path_verifications": [],
            "provisioning": {
                "schema_version": "workspace_provisioning_public@2",
                "intent_id": "provisioning-1",
                "intent_digest": _digest("provisioning-1"),
                "intent_state_version": 2,
                "status": "ready",
                "workspace_id": "workspace-1",
                "workspace_generation": 1,
                "runtime_binding_id": "workspace-1",
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
        core["tool_reflection"] = {
            "declared_tool_catalog_digest": (self.release.declared_tool_catalog_digest),
            "capability_binding_digest": binding_digest,
            "affordance_snapshot_digest": snapshot_digest,
            "available_tool_names": [],
            "affordances": [],
            "tool_exposure": {
                "schema_version": "tool_exposure_public@1",
                "exposure_snapshot_id": "public-exposure-1",
                "exposure_snapshot_digest": _digest("public-exposure-1"),
                "direct_tool_names": [],
                "deferred_tool_names": [],
                "command_expansions": [],
            },
        }
        if self.readiness == "provisioning":
            core["session"]["resident_readiness"].update(  # type: ignore[index,union-attr]
                {
                    "readiness": "provisioning",
                    "next_action": "wait_for_provisioning_worker",
                }
            )
            core["workspace"]["provisioning"].update(  # type: ignore[index,union-attr]
                {
                    "status": "pending",
                    "runtime_binding_id": None,
                    "effect_certainty": None,
                    "mutation_applied": None,
                    "next_action": "wait_for_provisioning_worker",
                }
            )
        elif self.readiness in {"blocked", "blocked-known"}:
            reconcile_required = self.readiness == "blocked"
            next_action = (
                "reconcile_workspace_provisioning"
                if reconcile_required
                else "create_successor_workspace_generation"
            )
            effect_certainty = (
                "dispatch_in_doubt" if reconcile_required else "no_effect"
            )
            core["session"]["resident_readiness"].update(  # type: ignore[index,union-attr]
                {
                    "readiness": "blocked",
                    "failure_id": "failure-provisioning-1",
                    "next_action": next_action,
                }
            )
            core["workspace"]["provisioning"].update(  # type: ignore[index,union-attr]
                {
                    "intent_state_version": 3,
                    "status": "blocked",
                    "runtime_binding_id": None,
                    "failure_id": "failure-provisioning-1",
                    "error_code": "workspace_provisioning_failed",
                    "effect_certainty": effect_certainty,
                    "mutation_applied": None if reconcile_required else False,
                    "reconcile_required": reconcile_required,
                    "diagnostic_id": "diagnostic-provisioning-1",
                    "next_action": next_action,
                }
            )
            core["failures"] = {
                "observations": [
                    _public_failure(
                        "failure-provisioning-1",
                        session_id=session_id,
                        effect_certainty=effect_certainty,
                    )
                ]
            }
        elif self.readiness == "blocked-reconciled":
            core["session"]["resident_readiness"].update(  # type: ignore[index,union-attr]
                {
                    "readiness": "blocked",
                    "failure_id": "failure-reconciliation-1",
                    "next_action": "create_successor_workspace_generation",
                }
            )
            core["workspace"]["provisioning"].update(  # type: ignore[index,union-attr]
                {
                    "intent_state_version": 3,
                    "status": "blocked",
                    "runtime_binding_id": None,
                    "failure_id": "failure-provisioning-1",
                    "error_code": "workspace_provisioning_failed",
                    "effect_certainty": "dispatch_in_doubt",
                    "mutation_applied": None,
                    "reconcile_required": True,
                    "diagnostic_id": "diagnostic-provisioning-1",
                    "next_action": "create_successor_workspace_generation",
                    "reconciliation": {
                        "schema_version": (
                            "workspace_provisioning_reconciliation_public@1"
                        ),
                        "reconciliation_id": "reconciliation-provisioning-1",
                        "reconciliation_digest": _digest(
                            "reconciliation-provisioning-1"
                        ),
                        "status": "blocked",
                        "attempt": 1,
                        "parent_reconciliation_id": None,
                        "blocked_intent_state_version": 3,
                        "blocked_intent_digest": _digest("provisioning-1"),
                        "source_receipt_id": "receipt-provisioning-1",
                        "source_receipt_digest": _digest("receipt-provisioning-1"),
                        "dispatch_receipt_digest": _digest("dispatch-provisioning-1"),
                        "result_receipt_id": "receipt-reconciliation-1",
                        "result_receipt_digest": _digest("receipt-reconciliation-1"),
                        "effect_certainty": "no_effect",
                        "mutation_applied": False,
                        "fallback_performed": False,
                        "retry_permitted": False,
                        "reconcile_required": False,
                        "failure_id": "failure-reconciliation-1",
                        "diagnostic_id": "diagnostic-reconciliation-1",
                        "requested_at": "2026-08-24T00:01:00Z",
                        "requested_claim_seconds": 120,
                        "settled_at": "2026-08-24T00:02:00Z",
                        "next_action": "create_successor_workspace_generation",
                    },
                }
            )
            core["failures"] = {
                "observations": [
                    _public_failure(
                        "failure-reconciliation-1",
                        session_id=session_id,
                        effect_certainty="no_effect",
                    )
                ]
            }
        elif self.readiness == "legacy":
            core["session"].pop("resident_readiness")  # type: ignore[union-attr]
            core["workspace"].pop("provisioning")  # type: ignore[union-attr]
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


def _successor_result(
    invocation: HostV2WorkspaceProvisioningSuccessorInvocation,
) -> dict[str, object]:
    return {
        "failed_intent_id": invocation.failed_intent_id,
        "resolved_reconciliation_id": invocation.resolved_reconciliation_id,
        "successor_intent_id": "provisioning-successor-2",
        "workspace_id": "workspace-1",
        "generation": 2,
        "readiness": "provisioning",
        "successor_intent_created": True,
        "workspace_generation_reserved": True,
        "workspace_provisioning_enqueued": True,
        "adapter_invoked": False,
        "external_effect_performed": False,
        "runtime_executed": False,
        "task_transition_performed": False,
        "fallback_performed": False,
    }


def _reconciliation_admission_result(
    invocation: HostV2WorkspaceProvisioningReconciliationInvocation,
) -> dict[str, object]:
    return {
        "reconciliation_id": "reconciliation-provisioning-1",
        "reconciliation_digest": _digest("reconciliation-provisioning-1"),
        "intent_id": invocation.intent_id,
        "blocked_intent_state_version": invocation.expected_intent_version,
        "blocked_intent_digest": invocation.intent_digest,
        "source_receipt_id": "receipt-provisioning-1",
        "source_receipt_digest": _digest("receipt-provisioning-1"),
        "dispatch_receipt_digest": _digest("dispatch-provisioning-1"),
        "attempt": 1,
        "parent_reconciliation_id": None,
        "requested_claim_seconds": invocation.claim_seconds,
        "status": "pending",
        "readiness": "blocked",
        "historical_intent_preserved": True,
        "reconciliation_enqueued": True,
        "workspace_provisioning_reconciliation_enqueued": True,
        "adapter_invoked": False,
        "external_effect_performed": False,
        "runtime_executed": False,
        "task_transition_performed": False,
        "fallback_performed": False,
    }


@dataclass
class _CommandGateway:
    invocations: list[HostV2MutationInvocation]
    bootstraps: list[HostV2SessionBootstrapInvocation]
    reconciliations: list[HostV2WorkspaceProvisioningReconciliationInvocation]
    successors: list[HostV2WorkspaceProvisioningSuccessorInvocation]

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
            result={
                "session_id": invocation.session_id,
                "workspace_readiness": "provisioning",
                "runtime_executed": False,
                "task_transition_performed": False,
                "fallback_performed": False,
            },
        )

    def invoke(self, invocation: HostV2MutationInvocation) -> KernelMutationReceipt:
        self.invocations.append(invocation)
        return KernelMutationReceipt.create(
            command_id=invocation.idempotency_key,
            service_id="test.kernel.gateway",
            operation=invocation.route_id,
            mutation_applied=True,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            result={
                "accepted": True,
                "runtime_executed": False,
                "task_transition_performed": False,
                "fallback_performed": False,
            },
        )

    def reconcile_workspace_provisioning(
        self,
        invocation: HostV2WorkspaceProvisioningReconciliationInvocation,
    ) -> KernelMutationReceipt:
        self.reconciliations.append(invocation)
        return KernelMutationReceipt.create(
            command_id=invocation.idempotency_key,
            service_id="test.kernel.gateway",
            operation="admit_reconciliation",
            mutation_applied=True,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            result=_reconciliation_admission_result(invocation),
        )

    def create_workspace_provisioning_successor(
        self,
        invocation: HostV2WorkspaceProvisioningSuccessorInvocation,
    ) -> KernelMutationReceipt:
        self.successors.append(invocation)
        return KernelMutationReceipt.create(
            command_id=invocation.idempotency_key,
            service_id="test.kernel.gateway",
            operation="replace_failed_generation",
            mutation_applied=True,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            result=_successor_result(invocation),
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


class _SynchronousReconciliationGateway(_CommandGateway):
    def reconcile_workspace_provisioning(
        self,
        invocation: HostV2WorkspaceProvisioningReconciliationInvocation,
    ) -> KernelMutationReceipt:
        self.reconciliations.append(invocation)
        return KernelMutationReceipt.create(
            command_id=invocation.idempotency_key,
            service_id="test.kernel.gateway",
            operation="settle_reconciliation",
            mutation_applied=True,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            result={
                **_reconciliation_admission_result(invocation),
                "status": "ready",
                "readiness": "ready",
                "reconciliation_enqueued": False,
                "workspace_provisioning_reconciliation_enqueued": False,
                "adapter_invoked": True,
                "external_effect_performed": True,
            },
        )


@dataclass
class _HostileReconciliationGateway(_CommandGateway):
    effect_certainty: ExternalEffectCertainty
    result_updates: dict[str, object]

    def reconcile_workspace_provisioning(
        self,
        invocation: HostV2WorkspaceProvisioningReconciliationInvocation,
    ) -> KernelMutationReceipt:
        self.reconciliations.append(invocation)
        result = _reconciliation_admission_result(invocation)
        result.update(self.result_updates)
        return KernelMutationReceipt.create(
            command_id=invocation.idempotency_key,
            service_id="test.kernel.gateway",
            operation="admit_reconciliation",
            mutation_applied=True,
            effect_certainty=self.effect_certainty,
            result=result,
        )


@dataclass
class _HostileSuccessorGateway(_CommandGateway):
    effect_certainty: ExternalEffectCertainty
    result_updates: dict[str, object]

    def create_workspace_provisioning_successor(
        self,
        invocation: HostV2WorkspaceProvisioningSuccessorInvocation,
    ) -> KernelMutationReceipt:
        self.successors.append(invocation)
        result = _successor_result(invocation)
        result.update(self.result_updates)
        return KernelMutationReceipt.create(
            command_id=invocation.idempotency_key,
            service_id="test.kernel.gateway",
            operation="replace_failed_generation",
            mutation_applied=True,
            effect_certainty=self.effect_certainty,
            result=result,
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


def _surface(
    *,
    readiness: str = "ready",
    runtime_status: str = "accepted",
) -> FileWorkspaceV2HostSurface:
    release = _release()
    return FileWorkspaceV2HostSurface(
        release=release,
        core_provider=_CoreProvider(
            release,
            readiness=readiness,
            runtime_status=runtime_status,
        ),
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


def _app(
    gateway: _CommandGateway,
    *,
    readiness: str = "ready",
    runtime_status: str = "accepted",
) -> _AppClient:
    return _AppClient(
        create_v2_app(
            HostV2Dependencies(
                security_policy=HostSecurityPolicy.from_settings(None),
                workspace_surface=_surface(
                    readiness=readiness,
                    runtime_status=runtime_status,
                ),
                command_gateway=gateway,
                http_routes=(_ExtensionRoute(),),
            )
        )
    )


def _gateway() -> _CommandGateway:
    return _CommandGateway([], [], [], [])


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

    assert response.status_code == 202, response.text
    assert response.headers["OpenZyme-Release-Digest"] == (
        surface.release.release_digest
    )
    assert response.json()["operation"] == "session.bootstrap"
    assert response.json()["result"]["workspace_readiness"] == "provisioning"
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
        json={"message": "continue", "workflow_refs": []},
    )

    assert mutated.status_code == 202, mutated.text
    assert mutated.json()["mutation_applied"] is True
    assert mutated.json()["result"]["runtime_executed"] is False
    assert len(gateway.invocations) == 1
    assert gateway.invocations[0].route_id == "openzyme.kernel.message.send@2"
    assert gateway.invocations[0].payload == {
        "message": "continue",
        "workflow_refs": (),
    }
    assert gateway.invocations[0].precondition.query_context.session_id == "session-1"


@pytest.mark.parametrize(
    ("path", "payload", "route_id"),
    (
        (
            "/v3/sessions/session-1/messages",
            {"message": "continue", "workflow_refs": []},
            "openzyme.kernel.message.send@2",
        ),
        (
            "/v3/sessions/session-1/runtime/drain",
            {"max_signals": 1, "max_steps_per_agent": 1},
            "openzyme.kernel.runtime.drain@2",
        ),
        (
            "/v3/sessions/session-1/approvals",
            {"intent_digest": _digest("approval")},
            "openzyme.kernel.approval.request@2",
        ),
        (
            "/v3/sessions/session-1/approvals/approval-1/decision",
            {
                "decision": "approved",
                "intent_digest": _digest("approval"),
                "resolution_ref": "gesture-1",
            },
            "openzyme.kernel.approval.decide@2",
        ),
    ),
)
def test_resident_admission_mutations_return_202_without_host_execution(
    path: str,
    payload: dict[str, object],
    route_id: str,
) -> None:
    gateway = _gateway()
    client = _app(gateway)
    inspected = client.get(
        "/v3/sessions/session-1/workspace",
        headers=_base_headers(),
    )

    response = client.post(
        path,
        headers=_mutation_headers(inspected),
        json=payload,
    )

    assert response.status_code == 202, response.text
    assert response.json()["result"]["runtime_executed"] is False
    assert gateway.invocations[-1].route_id == route_id


def test_host_admits_only_the_exact_blocked_workspace_reconciliation() -> None:
    gateway = _gateway()
    client = _app(gateway, readiness="blocked")
    inspected = client.get(
        "/v3/sessions/session-1/workspace",
        headers=_base_headers(),
    )

    response = client.post(
        "/v3/sessions/session-1/workspace/provisioning/reconcile",
        headers={
            **_mutation_headers(inspected),
            "Idempotency-Key": "reconcile-provisioning-1",
        },
        json={
            "intent_id": "provisioning-1",
            "intent_digest": _digest("provisioning-1"),
            "expected_intent_version": 3,
            "claim_seconds": 120,
        },
    )

    assert response.status_code == 202, response.text
    receipt = response.json()
    assert receipt["operation"] == "admit_reconciliation"
    assert receipt["mutation_applied"] is True
    assert receipt["effect_certainty"] == "no_effect"
    assert receipt["fallback_performed"] is False
    assert set(receipt["result"]) == (
        WORKSPACE_PROVISIONING_RECONCILIATION_ADMISSION_RESULT_FIELDS
    )
    assert "claim_token" not in receipt["result"]
    assert "claim_owner_id" not in receipt["result"]
    assert receipt["result"]["requested_claim_seconds"] == 120
    assert receipt["result"]["reconciliation_enqueued"] is True
    assert receipt["result"]["workspace_provisioning_reconciliation_enqueued"] is True
    assert receipt["result"]["adapter_invoked"] is False
    assert receipt["result"]["runtime_executed"] is False
    assert receipt["result"]["task_transition_performed"] is False
    assert receipt["result"]["external_effect_performed"] is False
    assert gateway.invocations == []
    assert gateway.successors == []
    assert len(gateway.reconciliations) == 1
    invocation = gateway.reconciliations[0]
    assert invocation.session_id == "session-1"
    assert invocation.actor_id == "user:local-dev"
    assert invocation.idempotency_key == "reconcile-provisioning-1"
    assert invocation.correlation_id == "request-v2-test"
    assert invocation.intent_id == "provisioning-1"
    assert invocation.intent_digest == _digest("provisioning-1")
    assert invocation.expected_intent_version == 3
    assert invocation.claim_seconds == 120


@pytest.mark.parametrize(
    ("effect_certainty", "result_updates"),
    (
        (ExternalEffectCertainty.TERMINAL_KNOWN, {}),
        (ExternalEffectCertainty.NO_EFFECT, {"adapter_invoked": True}),
        (ExternalEffectCertainty.NO_EFFECT, {"runtime_executed": True}),
        (ExternalEffectCertainty.NO_EFFECT, {"task_transition_performed": True}),
        (ExternalEffectCertainty.NO_EFFECT, {"status": "ready"}),
        (ExternalEffectCertainty.NO_EFFECT, {"attempt": 2}),
        (ExternalEffectCertainty.NO_EFFECT, {"claim_token": "private-token"}),
        (ExternalEffectCertainty.NO_EFFECT, {"tool_requests": ["private-tool"]}),
    ),
)
def test_host_rejects_hostile_reconciliation_admission_receipt(
    effect_certainty: ExternalEffectCertainty,
    result_updates: dict[str, object],
) -> None:
    gateway = _HostileReconciliationGateway(
        [],
        [],
        [],
        [],
        effect_certainty,
        result_updates,
    )
    client = _app(gateway, readiness="blocked")
    inspected = client.get(
        "/v3/sessions/session-1/workspace",
        headers=_base_headers(),
    )

    response = client.post(
        "/v3/sessions/session-1/workspace/provisioning/reconcile",
        headers={
            **_mutation_headers(inspected),
            "Idempotency-Key": "reconcile-hostile-provisioning-1",
        },
        json={
            "intent_id": "provisioning-1",
            "intent_digest": _digest("provisioning-1"),
            "expected_intent_version": 3,
            "claim_seconds": 120,
        },
    )

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == (
        "workspace_provisioning_reconciliation_admission_receipt_invalid"
    )
    serialized = json.dumps(error, sort_keys=True)
    assert "private-token" not in serialized
    assert "private-tool" not in serialized
    assert error["fallback_performed"] is False


def test_host_never_returns_202_for_inline_reconciliation_observation() -> None:
    gateway = _SynchronousReconciliationGateway([], [], [], [])
    client = _app(gateway, readiness="blocked")
    inspected = client.get(
        "/v3/sessions/session-1/workspace",
        headers=_base_headers(),
    )

    response = client.post(
        "/v3/sessions/session-1/workspace/provisioning/reconcile",
        headers={
            **_mutation_headers(inspected),
            "Idempotency-Key": "reconcile-inline-provisioning-1",
        },
        json={
            "intent_id": "provisioning-1",
            "intent_digest": _digest("provisioning-1"),
            "expected_intent_version": 3,
            "claim_seconds": 120,
        },
    )

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == (
        "workspace_provisioning_reconciliation_admission_receipt_invalid"
    )
    assert error["mutation_applied"] is True
    assert error["effect_certainty"] == "terminal_known"
    assert error["fallback_performed"] is False
    assert error["details"]["adapter_invoked"] is True
    assert error["details"]["external_effect_performed"] is True
    assert gateway.invocations == []
    assert len(gateway.reconciliations) == 1


def test_host_admits_only_pending_successor_without_running_other_work() -> None:
    gateway = _gateway()
    client = _app(gateway, readiness="blocked-known")
    inspected = client.get(
        "/v3/sessions/session-1/workspace",
        headers=_base_headers(),
    )

    response = client.post(
        "/v3/sessions/session-1/workspace/provisioning/successor",
        headers={
            **_mutation_headers(inspected),
            "Idempotency-Key": "successor-provisioning-1",
        },
        json={
            "failed_intent_id": "provisioning-1",
            "failed_intent_digest": _digest("provisioning-1"),
            "expected_failed_intent_version": 3,
            "resolved_reconciliation_id": None,
        },
    )

    assert response.status_code == 202, response.text
    receipt = response.json()
    assert receipt["operation"] == "replace_failed_generation"
    assert receipt["mutation_applied"] is True
    assert receipt["effect_certainty"] == "no_effect"
    assert receipt["fallback_performed"] is False
    assert receipt["result"]["failed_intent_id"] == "provisioning-1"
    assert receipt["result"]["resolved_reconciliation_id"] is None
    assert receipt["result"]["successor_intent_id"] == ("provisioning-successor-2")
    assert receipt["result"]["workspace_id"] == "workspace-1"
    assert receipt["result"]["generation"] == 2
    assert receipt["result"]["readiness"] == "provisioning"
    assert receipt["result"]["successor_intent_created"] is True
    assert receipt["result"]["workspace_generation_reserved"] is True
    assert receipt["result"]["workspace_provisioning_enqueued"] is True
    assert receipt["result"]["adapter_invoked"] is False
    assert receipt["result"]["runtime_executed"] is False
    assert receipt["result"]["task_transition_performed"] is False
    assert receipt["result"]["external_effect_performed"] is False
    assert gateway.invocations == []
    assert gateway.reconciliations == []
    assert len(gateway.successors) == 1
    invocation = gateway.successors[0]
    assert invocation.session_id == "session-1"
    assert invocation.actor_id == "user:local-dev"
    assert invocation.idempotency_key == "successor-provisioning-1"
    assert invocation.correlation_id == "request-v2-test"
    assert invocation.failed_intent_id == "provisioning-1"
    assert invocation.failed_intent_digest == _digest("provisioning-1")
    assert invocation.expected_failed_intent_version == 3
    assert invocation.resolved_reconciliation_id is None


def test_host_successor_binds_exact_resolved_reconciliation_lineage() -> None:
    gateway = _gateway()
    client = _app(gateway, readiness="blocked-reconciled")
    inspected = client.get(
        "/v3/sessions/session-1/workspace",
        headers=_base_headers(),
    )

    response = client.post(
        "/v3/sessions/session-1/workspace/provisioning/successor",
        headers={
            **_mutation_headers(inspected),
            "Idempotency-Key": "successor-reconciled-provisioning-1",
        },
        json={
            "failed_intent_id": "provisioning-1",
            "failed_intent_digest": _digest("provisioning-1"),
            "expected_failed_intent_version": 3,
            "resolved_reconciliation_id": "reconciliation-provisioning-1",
        },
    )

    assert response.status_code == 202, response.text
    assert response.json()["effect_certainty"] == "no_effect"
    assert response.json()["fallback_performed"] is False
    assert gateway.invocations == []
    assert gateway.reconciliations == []
    assert len(gateway.successors) == 1
    invocation = gateway.successors[0]
    assert invocation.failed_intent_id == "provisioning-1"
    assert invocation.failed_intent_digest == _digest("provisioning-1")
    assert invocation.expected_failed_intent_version == 3
    assert invocation.resolved_reconciliation_id == ("reconciliation-provisioning-1")


@pytest.mark.parametrize(
    ("effect_certainty", "result_updates"),
    (
        (ExternalEffectCertainty.TERMINAL_KNOWN, {}),
        (ExternalEffectCertainty.NO_EFFECT, {"adapter_invoked": True}),
        (ExternalEffectCertainty.NO_EFFECT, {"runtime_executed": True}),
        (
            ExternalEffectCertainty.NO_EFFECT,
            {"task_transition_performed": True},
        ),
        (
            ExternalEffectCertainty.NO_EFFECT,
            {"tool_requests": [{"name": "user-guessed.hidden-tool"}]},
        ),
    ),
)
def test_host_rejects_hostile_successor_receipt_before_returning_202(
    effect_certainty: ExternalEffectCertainty,
    result_updates: dict[str, object],
) -> None:
    gateway = _HostileSuccessorGateway(
        invocations=[],
        bootstraps=[],
        reconciliations=[],
        successors=[],
        effect_certainty=effect_certainty,
        result_updates=result_updates,
    )
    client = _app(gateway, readiness="blocked-known")
    inspected = client.get(
        "/v3/sessions/session-1/workspace",
        headers=_base_headers(),
    )

    response = client.post(
        "/v3/sessions/session-1/workspace/provisioning/successor",
        headers={
            **_mutation_headers(inspected),
            "Idempotency-Key": "hostile-successor-provisioning-1",
        },
        json={
            "failed_intent_id": "provisioning-1",
            "failed_intent_digest": _digest("provisioning-1"),
            "expected_failed_intent_version": 3,
            "resolved_reconciliation_id": None,
        },
    )

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == (
        "workspace_provisioning_successor_admission_receipt_invalid"
    )
    assert error["mutation_applied"] is True
    assert error["effect_certainty"] == effect_certainty.value
    assert error["fallback_performed"] is False
    assert "tool_requests" not in error["details"]
    assert gateway.invocations == []
    assert gateway.reconciliations == []
    assert len(gateway.successors) == 1


@pytest.mark.parametrize(
    ("path", "readiness", "payload"),
    (
        (
            "/v3/sessions/session-1/workspace/provisioning/reconcile",
            "blocked",
            {
                "intent_id": "provisioning-1",
                "intent_digest": _digest("provisioning-1"),
                "expected_intent_version": 2,
                "claim_seconds": 120,
            },
        ),
        (
            "/v3/sessions/session-1/workspace/provisioning/successor",
            "blocked-known",
            {
                "failed_intent_id": "provisioning-1",
                "failed_intent_digest": _digest("stale-intent"),
                "expected_failed_intent_version": 3,
                "resolved_reconciliation_id": None,
            },
        ),
        (
            "/v3/sessions/session-1/workspace/provisioning/successor",
            "blocked-reconciled",
            {
                "failed_intent_id": "provisioning-1",
                "failed_intent_digest": _digest("provisioning-1"),
                "expected_failed_intent_version": 3,
                "resolved_reconciliation_id": "reconciliation-stale-1",
            },
        ),
    ),
)
def test_workspace_recovery_rejects_stale_projection_fences_before_gateway(
    path: str,
    readiness: str,
    payload: dict[str, object],
) -> None:
    gateway = _gateway()
    client = _app(gateway, readiness=readiness)
    inspected = client.get(
        "/v3/sessions/session-1/workspace",
        headers=_base_headers(),
    )

    response = client.post(
        path,
        headers=_mutation_headers(inspected),
        json=payload,
    )

    assert response.status_code == 409
    assert response.json()["error"]["mutation_applied"] is False
    assert response.json()["error"]["fallback_performed"] is False
    assert gateway.invocations == []
    assert gateway.reconciliations == []
    assert gateway.successors == []


@pytest.mark.parametrize(
    ("path", "readiness", "payload", "error_code"),
    (
        (
            "/v3/sessions/session-1/workspace/provisioning/reconcile",
            "blocked",
            {
                "intent_id": "provisioning-1",
                "intent_digest": _digest("provisioning-1"),
                "expected_intent_version": 3,
                "claim_seconds": 120,
            },
            "workspace_provisioning_reconciliation_gateway_unconfigured",
        ),
        (
            "/v3/sessions/session-1/workspace/provisioning/successor",
            "blocked-known",
            {
                "failed_intent_id": "provisioning-1",
                "failed_intent_digest": _digest("provisioning-1"),
                "expected_failed_intent_version": 3,
                "resolved_reconciliation_id": None,
            },
            "workspace_provisioning_successor_gateway_unconfigured",
        ),
    ),
)
def test_workspace_recovery_fails_closed_without_direct_distribution_gateway(
    path: str,
    readiness: str,
    payload: dict[str, object],
    error_code: str,
) -> None:
    gateway = _UncertainCommandGateway([])
    client = _AppClient(
        create_v2_app(
            HostV2Dependencies(
                security_policy=HostSecurityPolicy.from_settings(None),
                workspace_surface=_surface(readiness=readiness),
                command_gateway=gateway,
            )
        )
    )
    inspected = client.get(
        "/v3/sessions/session-1/workspace",
        headers=_base_headers(),
    )

    response = client.post(
        path,
        headers=_mutation_headers(inspected),
        json=payload,
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == error_code
    assert response.json()["error"]["mutation_applied"] is False
    assert response.json()["error"]["effect_certainty"] == "no_effect"
    assert response.json()["error"]["fallback_performed"] is False
    assert gateway.invocations == []


@pytest.mark.parametrize(
    ("path", "readiness", "payload"),
    (
        (
            "/v3/sessions/session-1/workspace/provisioning/reconcile",
            "blocked",
            {
                "intent_id": "provisioning-1",
                "intent_digest": _digest("provisioning-1"),
                "expected_intent_version": 3,
                "claim_seconds": 120,
            },
        ),
        (
            "/v3/sessions/session-1/workspace/provisioning/successor",
            "blocked-known",
            {
                "failed_intent_id": "provisioning-1",
                "failed_intent_digest": _digest("provisioning-1"),
                "expected_failed_intent_version": 3,
                "resolved_reconciliation_id": None,
            },
        ),
    ),
)
def test_workspace_recovery_requires_project_scoped_operator_role(
    path: str,
    readiness: str,
    payload: dict[str, object],
) -> None:
    token = "project-user-token"
    gateway = _gateway()
    client = _AppClient(
        create_v2_app(
            HostV2Dependencies(
                security_policy=HostSecurityPolicy(
                    deployment_profile="shared",
                    principals_by_digest={
                        hashlib.sha256(token.encode("utf-8")).hexdigest(): (
                            HostPrincipal(
                                principal_id="user:project-member",
                                roles=frozenset({"user"}),
                                project_ids=frozenset({"project-1"}),
                            )
                        )
                    },
                    debug_enabled=False,
                ),
                workspace_surface=_surface(readiness=readiness),
                command_gateway=gateway,
            )
        )
    )
    authorization = {"Authorization": f"Bearer {token}"}
    inspected = client.get(
        "/v3/sessions/session-1/workspace",
        headers={**_base_headers(), **authorization},
    )

    response = client.post(
        path,
        headers={**_mutation_headers(inspected), **authorization},
        json=payload,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == (
        "workspace_provisioning_operator_required"
    )
    assert response.json()["error"]["mutation_applied"] is False
    assert response.json()["error"]["effect_certainty"] == "no_effect"
    assert response.json()["error"]["fallback_performed"] is False
    assert gateway.invocations == []
    assert gateway.reconciliations == []
    assert gateway.successors == []


@pytest.mark.parametrize(
    ("path", "readiness", "payload", "error_code"),
    (
        (
            "/v3/sessions/session-1/workspace/provisioning/reconcile",
            "blocked",
            {
                "intent_id": "provisioning-1",
                "intent_digest": _digest("provisioning-1"),
                "expected_intent_version": 3,
                "claim_seconds": 0,
            },
            "workspace_provisioning_reconciliation_payload_invalid",
        ),
        (
            "/v3/sessions/session-1/workspace/provisioning/reconcile",
            "blocked",
            {
                "intent_id": "provisioning-1",
                "intent_digest": _digest("provisioning-1"),
                "expected_intent_version": 3,
                "claim_seconds": 120,
                "reconcile": True,
            },
            "workspace_provisioning_reconciliation_payload_invalid",
        ),
        (
            "/v3/sessions/session-1/workspace/provisioning/successor",
            "blocked-known",
            {
                "failed_intent_id": "provisioning-1",
                "failed_intent_digest": _digest("provisioning-1"),
                "expected_failed_intent_version": 3,
                "resolved_reconciliation_id": None,
                "run_provisioning": True,
            },
            "workspace_provisioning_successor_payload_invalid",
        ),
    ),
)
def test_workspace_recovery_payloads_are_closed_and_bounded(
    path: str,
    readiness: str,
    payload: dict[str, object],
    error_code: str,
) -> None:
    gateway = _gateway()
    client = _app(gateway, readiness=readiness)
    inspected = client.get(
        "/v3/sessions/session-1/workspace",
        headers=_base_headers(),
    )

    response = client.post(
        path,
        headers=_mutation_headers(inspected),
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == error_code
    assert response.json()["error"]["mutation_applied"] is False
    assert response.json()["error"]["effect_certainty"] == "no_effect"
    assert response.json()["error"]["fallback_performed"] is False
    assert gateway.invocations == []
    assert gateway.reconciliations == []
    assert gateway.successors == []


@pytest.mark.parametrize(
    ("payload", "error_code"),
    (
        (
            {"message": "continue"},
            "message_workflow_selection_required",
        ),
        (
            {"content": "continue", "workflow_refs": []},
            "message_payload_fields_invalid",
        ),
        (
            {
                "message": "continue",
                "workflow_refs": [],
                "skill_keys": ["workflow.compat"],
            },
            "message_workflow_selection_ambiguous",
        ),
        (
            {
                "message": "continue",
                "workflow_refs": ["workflow.z", "workflow.a"],
            },
            "message_workflow_selection_invalid",
        ),
    ),
)
def test_message_wire_rejects_missing_retired_mixed_or_noncanonical_selection(
    payload: dict[str, object],
    error_code: str,
) -> None:
    gateway = _gateway()
    client = _app(gateway)
    inspected = client.get(
        "/v3/sessions/session-1/workspace",
        headers=_base_headers(),
    )

    response = client.post(
        "/v3/sessions/session-1/messages",
        headers=_mutation_headers(inspected),
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == error_code
    assert response.json()["error"]["mutation_applied"] is False
    assert gateway.invocations == []


def test_message_wire_preserves_compatibility_skill_keys_as_selection_request() -> None:
    gateway = _gateway()
    client = _app(gateway)
    inspected = client.get(
        "/v3/sessions/session-1/workspace",
        headers=_base_headers(),
    )

    response = client.post(
        "/v3/sessions/session-1/messages",
        headers=_mutation_headers(inspected),
        json={"message": "continue", "skill_keys": ["workflow.compat"]},
    )

    assert response.status_code == 202, response.text
    assert gateway.invocations[0].payload["skill_keys"] == ("workflow.compat",)


@pytest.mark.parametrize(
    ("path", "payload"),
    (
        (
            "/v3/sessions/session-1/messages",
            {"message": "continue", "workflow_refs": []},
        ),
        (
            "/v3/sessions/session-1/runtime/drain",
            {"max_signals": 1, "max_steps_per_agent": 1},
        ),
        (
            "/v3/sessions/session-1/approvals/approval-1/decision",
            {"decision": "approved", "intent_digest": _digest("approval")},
        ),
    ),
)
def test_resident_mutations_are_disabled_until_workspace_is_ready(
    path: str,
    payload: dict[str, object],
) -> None:
    gateway = _gateway()
    client = _app(gateway, readiness="provisioning")
    inspected = client.get(
        "/v3/sessions/session-1/workspace",
        headers=_base_headers(),
    )

    response = client.post(
        path,
        headers=_mutation_headers(inspected),
        json=payload,
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "resident_teammate_not_ready"
    assert error["details"]["readiness"] == "provisioning"
    assert error["details"]["next_action"] == "wait_for_provisioning_worker"
    assert error["mutation_applied"] is False
    assert gateway.invocations == []


def test_generic_v2_host_polls_runtime_command_without_resubmitting() -> None:
    gateway = _gateway()
    client = _app(gateway)

    response = client.get(
        "/v3/sessions/session-1/runtime/commands/runtime-drain-1",
        headers=_base_headers(),
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
    payload = response.json()
    assert payload["schema_version"] == "runtime_command_status@1"
    assert payload["command"]["command_id"] == "runtime-drain-1"
    assert payload["command"]["status"] == "accepted"
    assert payload["mutation_applied"] is False
    assert payload["fallback_performed"] is False
    assert gateway.invocations == []


def test_generic_v2_host_exposes_only_safe_failed_runtime_command_pair_ids() -> None:
    gateway = _gateway()
    client = _app(gateway, runtime_status="failed")

    response = client.get(
        "/v3/sessions/session-1/runtime/commands/runtime-drain-1",
        headers=_base_headers(),
    )

    assert response.status_code == 200, response.text
    command = response.json()["command"]
    assert command["status"] == "failed"
    assert command["failure_id"] == "failure-runtime-drain-1"
    assert command["diagnostic_id"] == "diagnostic-runtime-drain-1"
    serialized = json.dumps(command, sort_keys=True)
    assert "private_context" not in serialized
    assert "traceback" not in serialized
    assert "stdout" not in serialized
    assert "stderr" not in serialized
    assert gateway.invocations == []


def test_generic_v2_host_rejects_unknown_runtime_command_without_drain() -> None:
    gateway = _gateway()
    client = _app(gateway)

    response = client.get(
        "/v3/sessions/session-1/runtime/commands/runtime-drain-missing",
        headers=_base_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "runtime_command_not_found"
    assert response.json()["error"]["mutation_applied"] is False
    assert gateway.invocations == []


def test_generic_v2_host_rejects_legacy_resident_state_without_online_seed() -> None:
    gateway = _gateway()
    client = _app(gateway, readiness="legacy")

    response = client.get(
        "/v3/sessions/session-1/workspace",
        headers=_base_headers(),
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "resident_teammate_state_incompatible"
    assert error["mutation_applied"] is False
    assert error["fallback_performed"] is False
    assert error["details"]["next_action"] == (
        "create_new_session_or_run_offline_migration"
    )
    assert gateway.invocations == []


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
