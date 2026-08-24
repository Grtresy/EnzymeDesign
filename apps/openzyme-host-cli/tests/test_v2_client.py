from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
import json
from pathlib import Path

import pytest

from openzyme_client import OpenZymeClientContractError
from openzyme_contracts import FILE_WORKSPACE_CORE_SECTION_FIELDS
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION
from openzyme_contracts import FileWorkspaceCoreProjectionV2
from openzyme_contracts import FileWorkspacePublicV2
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import canonical_sha256_digest
from openzyme_host_cli import HostApiV2Client
from openzyme_host_cli.cli import run_cli
from openzyme_host_cli.renderers import render_v3_workspace_v2
from openzyme_host_cli.v2_client import load_expected_release_identity


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _public_failure(
    failure_id: str,
    *,
    session_id: str = "session-1",
) -> dict[str, object]:
    return {
        "schema_version": "failure_observation@2",
        "failure_id": failure_id,
        "session_id": session_id,
        "source_kind": "workspace_provisioning",
        "source_ref": "provisioning-1",
        "source_version": _digest(failure_id),
        "phase": "settlement",
        "failure_class": "controlled_effect",
        "recoverability": "reconciliation_required",
        "effect_certainty": "no_effect",
        "retry_eligibility": "reconcile_required",
        "actor_kind": "system",
        "error_code": "workspace_provisioning_failed",
        "safe_summary": "Workspace provisioning did not settle successfully.",
        "facts": {},
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
        "mutation_applied": False,
        "fallback_performed": False,
        "cause_chain": [],
        "diagnostic_id": f"diagnostic-{failure_id}",
        "next_action": "inspect_recovery_state",
    }


def _runtime_command(
    *,
    status: str = "accepted",
    session_id: str = "session-1",
) -> dict[str, object]:
    terminal = status in {"completed", "failed", "locked", "cancelled"}
    return {
        "schema_version": "runtime_command_public@1",
        "command_id": "runtime-drain-1",
        "session_id": session_id,
        "command_type": "runtime.drain",
        "request_digest": _digest("runtime-drain-1"),
        "idempotency_key": "runtime-drain-1",
        "status": status,
        "max_signals": 3,
        "max_steps_per_agent": 8,
        "auto_enqueue_ready_tasks": False,
        "state_version": 1,
        "fencing_token": 0,
        "accepted_at": "2026-08-24T00:00:00Z",
        "claim_owner": None,
        "lease_expires_at": None,
        "bounded_outcome_summary": (
            {
                "schema_version": "runtime_command_outcome_summary_public@1",
                "processed_signals": 0,
                "turn_count": 0,
                "turns_digest": canonical_sha256_digest([]),
                "runtime_executed": False,
                "task_transition_performed": False,
                "fallback_performed": False,
            }
            if terminal
            else None
        ),
        "failure_id": "failure-runtime-drain-1" if status == "failed" else None,
        "diagnostic_id": ("diagnostic-runtime-drain-1" if status == "failed" else None),
        "error_code": (
            "runtime_context_identity_stale" if status == "failed" else None
        ),
        "safe_error_summary": (
            "Runtime context projection failed before provider invocation."
            if status == "failed"
            else None
        ),
        "safe_retry_hint": (
            "Inspect the exact diagnostic; no provider or fallback ran."
            if status == "failed"
            else None
        ),
        "started_at": None,
        "completed_at": "2026-08-24T00:00:01Z" if terminal else None,
    }


def _release() -> LayeredReleaseIdentity:
    return LayeredReleaseIdentity(
        kernel_contract_digest=_digest("kernel"),
        core_schema_digest=_digest("schema"),
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


def _projection(
    release: LayeredReleaseIdentity,
    *,
    approvals: tuple[dict[str, object], ...] = (),
    readiness: str = "ready",
    session_id: str = "session-1",
    current_resident: bool = True,
) -> FileWorkspacePublicV2:
    arrays = {
        "tasks",
        "lanes",
        "agents",
        "approvals",
        "authority_leases",
        "publications",
    }
    core: dict[str, object] = {
        key: [] if key in arrays else {} for key in FILE_WORKSPACE_CORE_SECTION_FIELDS
    }
    binding_digest = _digest("binding")
    core["session"] = {
        "session_id": session_id,
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
    core["protocol"] = {"records": [], "inbox": []}
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
    core["capability_binding"] = {"binding_digest": binding_digest}
    core["runtime"] = {
        "signals": [],
        "session_leases": [],
        "turn_commands": [],
        "continuation_intents": [],
        "settlement_intents": [],
        "outcome_consumptions": [],
        "commands": [],
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
    core["operations"] = {
        "controlled": [],
        "continuations": [],
        "publication_intents": [],
        "task_evidence": [],
        "command_receipts": [],
    }
    core["failures"] = {"observations": []}
    core["tool_reflection"] = {
        "declared_tool_catalog_digest": release.declared_tool_catalog_digest,
        "capability_binding_digest": binding_digest,
        "affordance_snapshot_digest": _digest("affordance"),
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
    core["approvals"] = list(approvals)
    if readiness in {"provisioning", "successor-pending"}:
        successor = readiness == "successor-pending"
        core["session"]["resident_readiness"].update(  # type: ignore[index,union-attr]
            {
                "readiness": "provisioning",
                "workspace_generation": 2 if successor else 1,
                "provisioning_intent_id": (
                    "provisioning-2" if successor else "provisioning-1"
                ),
                "provisioning_intent_digest": _digest(
                    "provisioning-2" if successor else "provisioning-1"
                ),
                "next_action": "wait_for_provisioning_worker",
            }
        )
        core["workspace"]["provisioning"].update(  # type: ignore[index,union-attr]
            {
                "intent_id": "provisioning-2" if successor else "provisioning-1",
                "intent_digest": _digest(
                    "provisioning-2" if successor else "provisioning-1"
                ),
                "intent_state_version": 1 if successor else 2,
                "status": "pending",
                "workspace_generation": 2 if successor else 1,
                "runtime_binding_id": None,
                "effect_certainty": None,
                "mutation_applied": None,
                "next_action": "wait_for_provisioning_worker",
            }
        )
    elif readiness in {"blocked", "blocked-known"}:
        reconcile_required = readiness == "blocked"
        next_action = (
            "reconcile_workspace_provisioning"
            if reconcile_required
            else "create_successor_workspace_generation"
        )
        effect_certainty = "dispatch_in_doubt" if reconcile_required else "no_effect"
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
                _public_failure("failure-provisioning-1", session_id=session_id)
            ]
        }
    elif readiness == "reconciliation-pending":
        core["session"]["resident_readiness"].update(  # type: ignore[index,union-attr]
            {
                "readiness": "blocked",
                "failure_id": "failure-provisioning-1",
                "next_action": "wait_for_reconciliation_worker",
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
                "next_action": "wait_for_reconciliation_worker",
                "reconciliation": {
                    "schema_version": "workspace_provisioning_reconciliation_public@1",
                    "reconciliation_id": "reconciliation-provisioning-1",
                    "reconciliation_digest": _digest("reconciliation-provisioning-1"),
                    "status": "pending",
                    "attempt": 1,
                    "parent_reconciliation_id": None,
                    "blocked_intent_state_version": 3,
                    "blocked_intent_digest": _digest("provisioning-1"),
                    "source_receipt_id": "receipt-provisioning-1",
                    "source_receipt_digest": _digest("receipt-provisioning-1"),
                    "dispatch_receipt_digest": _digest("dispatch-provisioning-1"),
                    "result_receipt_id": None,
                    "result_receipt_digest": None,
                    "effect_certainty": None,
                    "mutation_applied": None,
                    "fallback_performed": False,
                    "retry_permitted": False,
                    "reconcile_required": False,
                    "failure_id": None,
                    "diagnostic_id": None,
                    "requested_at": "2026-08-24T00:01:00Z",
                    "requested_claim_seconds": 120,
                    "settled_at": None,
                    "next_action": "wait_for_reconciliation_worker",
                },
            }
        )
        core["failures"] = {
            "observations": [
                _public_failure("failure-provisioning-1", session_id=session_id)
            ]
        }
    elif readiness == "blocked-reconciled":
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
                    "schema_version": "workspace_provisioning_reconciliation_public@1",
                    "reconciliation_id": "reconciliation-provisioning-1",
                    "reconciliation_digest": _digest("reconciliation-provisioning-1"),
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
                _public_failure("failure-reconciliation-1", session_id=session_id)
            ]
        }
    if not current_resident:
        core["session"].pop("resident_readiness")  # type: ignore[union-attr]
        core["workspace"].pop("provisioning")  # type: ignore[union-attr]
    return FileWorkspacePublicV2(
        release=release,
        core=FileWorkspaceCoreProjectionV2(core),
        extensions=(),
    )


@dataclass(frozen=True)
class _Response:
    status_code: int
    content: bytes
    headers: dict[str, str]


class _Session:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        content: bytes | None,
    ) -> _Response:
        self.calls.append((method, url, headers, content))
        return self.response

    def close(self) -> None:
        raise AssertionError("injected session must not be closed by the client")


class _SequencedSession(_Session):
    def __init__(self, responses: list[_Response]) -> None:
        super().__init__(responses[0])
        self._responses = list(responses)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        content: bytes | None,
    ) -> _Response:
        self.calls.append((method, url, headers, content))
        return self._responses.pop(0)


def _session(
    release: LayeredReleaseIdentity,
    *,
    media_type: str = FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
    projection: FileWorkspacePublicV2 | None = None,
) -> _Session:
    projection = projection or _projection(release)
    body = json.dumps(
        projection.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    binding_digest = _digest("binding")
    affordance_digest = _digest("affordance")
    return _Session(
        _Response(
            status_code=200,
            content=body,
            headers={
                "content-type": media_type,
                "OpenZyme-Workspace-Contract": (
                    FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION
                ),
                "OpenZyme-Release-Digest": release.release_digest,
                "OpenZyme-Public-Contract-Digest": (
                    FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
                ),
                "OpenZyme-Projection-Digest": projection.projection_digest,
                "OpenZyme-Capability-Binding-Digest": binding_digest,
                "OpenZyme-Affordance-Snapshot-Digest": affordance_digest,
            },
        )
    )


def _admission_response(
    release: LayeredReleaseIdentity,
    *,
    receipt: dict[str, object] | None = None,
    projection: FileWorkspacePublicV2 | None = None,
) -> _Response:
    inspected = _session(release, projection=projection).response
    return _Response(
        status_code=202,
        content=json.dumps(
            receipt or {"status": "accepted"},
            sort_keys=True,
        ).encode("utf-8"),
        headers=dict(inspected.headers),
    )


def _successor_receipt_result(
    *,
    resolved_reconciliation_id: str | None,
) -> dict[str, object]:
    return {
        "failed_intent_id": "provisioning-1",
        "resolved_reconciliation_id": resolved_reconciliation_id,
        "successor_intent_id": "provisioning-2",
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


def _reconciliation_admission_receipt_result() -> dict[str, object]:
    return {
        "reconciliation_id": "reconciliation-provisioning-1",
        "reconciliation_digest": _digest("reconciliation-provisioning-1"),
        "intent_id": "provisioning-1",
        "blocked_intent_state_version": 3,
        "blocked_intent_digest": _digest("provisioning-1"),
        "source_receipt_id": "receipt-provisioning-1",
        "source_receipt_digest": _digest("receipt-provisioning-1"),
        "dispatch_receipt_digest": _digest("dispatch-provisioning-1"),
        "attempt": 1,
        "parent_reconciliation_id": None,
        "requested_claim_seconds": 120,
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


def test_cli_v2_client_delegates_exact_guard_to_openzyme_client() -> None:
    release = _release()
    session = _session(release)
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        auth_token="secret",
        session=session,
    )

    projection, verified = client.inspect_workspace("session-1")

    assert projection.core.payload["session"]["session_id"] == "session-1"
    assert (
        projection.core.payload["session"]["resident_readiness"]["readiness"] == "ready"
    )
    assert verified.release_digest == release.release_digest
    method, path, headers, body = session.calls[0]
    assert (method, path, body) == (
        "GET",
        "/v3/sessions/session-1/workspace",
        None,
    )
    assert headers["Accept"] == FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
    assert headers["Authorization"] == "Bearer secret"


def test_cli_v2_client_rejects_media_drift_without_legacy_fallback() -> None:
    release = _release()
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=_session(
            release,
            media_type="application/vnd.openzyme.file-workspace+json;version=1",
        ),
    )

    with pytest.raises(OpenZymeClientContractError) as rejected:
        client.inspect_workspace("session-1")
    assert rejected.value.code == "client_workspace_media_type_mismatch"
    assert rejected.value.mutation_applied is False
    assert rejected.value.fallback_performed is False


def test_cli_v2_rejects_legacy_resident_state_without_synthesizing_defaults() -> None:
    release = _release()
    legacy = _projection(release, current_resident=False)
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=_session(release, projection=legacy),
    )

    with pytest.raises(OpenZymeClientContractError) as rejected:
        client.inspect_workspace("session-1")

    assert rejected.value.code == "cli_resident_teammate_state_incompatible"
    assert rejected.value.fallback_performed is False


def test_cli_v2_message_is_bound_to_the_inspected_mutation_scope() -> None:
    release = _release()
    inspection = _session(release).response
    mutation = _admission_response(release)
    session = _SequencedSession([inspection, mutation, inspection])
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=session,
    )

    result = client.post_message(
        "session-1",
        message="continue",
        task_id=None,
        lane_id=None,
        workflow_refs=(),
        skill_keys=(),
        idempotency_key="message-1",
    )

    assert result["response_status"] == 202
    assert result["receipt"] == {"status": "accepted"}
    assert result["canonical_workspace"]["core"]["session"]["session_id"] == (
        "session-1"
    )
    assert [call[0] for call in session.calls] == ["GET", "POST", "GET"]
    _, path, headers, body = session.calls[1]
    assert path == "/v3/sessions/session-1/messages"
    assert (
        headers["OpenZyme-Projection-Digest"]
        == (inspection.headers["OpenZyme-Projection-Digest"])
    )
    assert headers["OpenZyme-Capability-Binding-Digest"] == _digest("binding")
    assert json.loads(body or b"{}") == {
        "message": "continue",
        "workflow_refs": [],
    }


def test_cli_v2_message_sends_canonical_workflow_refs_without_skill_fallback() -> None:
    release = _release()
    inspection = _session(release).response
    mutation = _admission_response(release)
    session = _SequencedSession([inspection, mutation, inspection])
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=session,
    )

    result = client.post_message(
        "session-1",
        message="use the selected workflow",
        task_id="task-1",
        lane_id="lane-1",
        workflow_refs=("workflow.example@1",),
        skill_keys=(),
        idempotency_key="message-workflow-1",
    )

    assert result["receipt"] == {"status": "accepted"}
    assert json.loads(session.calls[1][3] or b"{}") == {
        "lane_id": "lane-1",
        "message": "use the selected workflow",
        "task_id": "task-1",
        "workflow_refs": ["workflow.example@1"],
    }


def test_cli_v2_canonical_message_does_not_require_the_legacy_argument() -> None:
    release = _release()
    inspection = _session(release).response
    session = _SequencedSession(
        [
            inspection,
            _admission_response(release),
            inspection,
        ]
    )
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=session,
    )

    client.post_message(
        "session-1",
        message="continue",
        task_id=None,
        lane_id=None,
        workflow_refs=(),
        idempotency_key="message-canonical-1",
    )

    assert json.loads(session.calls[1][3] or b"{}") == {
        "message": "continue",
        "workflow_refs": [],
    }


def test_cli_v2_rejects_noncanonical_workflow_order_without_rewriting() -> None:
    release = _release()
    session = _session(release)
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=session,
    )

    with pytest.raises(OpenZymeClientContractError) as rejected:
        client.post_message(
            "session-1",
            message="do not rewrite my selection",
            task_id=None,
            lane_id=None,
            workflow_refs=("workflow.z@1", "workflow.a@1"),
            idempotency_key="message-order-1",
        )

    assert rejected.value.code == "cli_workflow_selection_invalid"
    assert session.calls == []


def test_cli_v2_rejects_mixed_workflow_selection_without_post() -> None:
    release = _release()
    session = _session(release)
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=session,
    )

    with pytest.raises(OpenZymeClientContractError) as rejected:
        client.post_message(
            "session-1",
            message="ambiguous",
            task_id=None,
            lane_id=None,
            workflow_refs=("workflow.example@1",),
            skill_keys=("legacy-key",),
            idempotency_key="message-ambiguous-1",
        )

    assert rejected.value.code == "cli_workflow_selection_ambiguous"
    assert session.calls == []


def test_cli_v2_polls_runtime_command_without_resubmitting_drain() -> None:
    release = _release()
    inspection = _session(release).response
    command_status = {
        "schema_version": "runtime_command_status@1",
        "session_id": "session-1",
        "command": _runtime_command(),
        "projection_digest": inspection.headers["OpenZyme-Projection-Digest"],
        "mutation_applied": False,
        "fallback_performed": False,
    }
    response = _Response(
        status_code=200,
        content=json.dumps(command_status, sort_keys=True).encode("utf-8"),
        headers=dict(inspection.headers),
    )
    session = _SequencedSession([response])
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=session,
    )

    result = client.inspect_runtime_command(
        "session-1",
        command_id="runtime-drain-1",
    )

    assert result["command"]["status"] == "accepted"
    assert [call[0] for call in session.calls] == ["GET"]
    assert session.calls[0][1] == (
        "/v3/sessions/session-1/runtime/commands/runtime-drain-1"
    )
    assert all(call[0] != "POST" for call in session.calls)


def test_cli_runtime_status_accepts_safe_failure_ids_and_rejects_private_fields() -> (
    None
):
    release = _release()
    inspection = _session(release).response
    headers = dict(inspection.headers)

    def response_for(command: dict[str, object]) -> _Response:
        return _Response(
            status_code=200,
            content=json.dumps(
                {
                    "schema_version": "runtime_command_status@1",
                    "session_id": "session-1",
                    "command": command,
                    "projection_digest": headers["OpenZyme-Projection-Digest"],
                    "mutation_applied": False,
                    "fallback_performed": False,
                },
                sort_keys=True,
            ).encode("utf-8"),
            headers=headers,
        )

    safe_client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=_SequencedSession([response_for(_runtime_command(status="failed"))]),
    )
    safe = safe_client.inspect_runtime_command(
        "session-1",
        command_id="runtime-drain-1",
    )["command"]
    assert safe["failure_id"] == "failure-runtime-drain-1"
    assert safe["diagnostic_id"] == "diagnostic-runtime-drain-1"
    assert "private_context" not in json.dumps(safe, sort_keys=True)

    unsafe = {
        **_runtime_command(status="failed"),
        "traceback_text": "PRIVATE TRACEBACK",
    }
    unsafe_client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=_SequencedSession([response_for(unsafe)]),
    )
    with pytest.raises(OpenZymeClientContractError) as rejected:
        unsafe_client.inspect_runtime_command(
            "session-1",
            command_id="runtime-drain-1",
        )
    assert rejected.value.code == "cli_runtime_command_payload_invalid"


def test_cli_runtime_status_command_uses_one_observation_get(tmp_path: Path) -> None:
    release = _release()
    release_path = tmp_path / "release.json"
    _write_release(release_path, release)
    inspected = _session(release).response
    response = _Response(
        status_code=200,
        content=json.dumps(
            {
                "schema_version": "runtime_command_status@1",
                "session_id": "session-1",
                "command": _runtime_command(status="completed"),
                "projection_digest": inspected.headers["OpenZyme-Projection-Digest"],
                "mutation_applied": False,
                "fallback_performed": False,
            },
            sort_keys=True,
        ).encode("utf-8"),
        headers=dict(inspected.headers),
    )
    session = _SequencedSession([response])
    stdout = StringIO()

    exit_code = run_cli(
        [
            "--release-identity",
            str(release_path),
            "--session-id",
            "session-1",
            "runtime",
            "status",
            "--command-id",
            "runtime-drain-1",
        ],
        session=session,
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert json.loads(stdout.getvalue())["command"]["status"] == "completed"
    assert [(call[0], call[1]) for call in session.calls] == [
        (
            "GET",
            "/v3/sessions/session-1/runtime/commands/runtime-drain-1",
        )
    ]


def _write_release(path: Path, release: LayeredReleaseIdentity) -> None:
    path.write_text(
        json.dumps(release.to_dict(), sort_keys=True),
        encoding="utf-8",
    )


def test_cli_v2_loads_one_closed_operator_pinned_release(tmp_path: Path) -> None:
    release = _release()
    release_path = tmp_path / "release.json"
    _write_release(release_path, release)

    assert load_expected_release_identity(release_path) == release

    release_path.write_text('{"unknown":true}', encoding="utf-8")
    with pytest.raises(OpenZymeClientContractError) as rejected:
        load_expected_release_identity(release_path)
    assert rejected.value.code == "cli_release_identity_invalid"
    assert rejected.value.fallback_performed is False


def test_cli_exact_v2_show_uses_closed_projection_renderer(tmp_path: Path) -> None:
    release = _release()
    release_path = tmp_path / "release.json"
    _write_release(release_path, release)
    session = _session(release)
    stdout = StringIO()
    stderr = StringIO()

    exit_code = run_cli(
        [
            "--release-identity",
            str(release_path),
            "--session-id",
            "session-1",
            "sessions",
            "show",
        ],
        session=session,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert "Session session-1" in stdout.getvalue()
    assert "Extension sections: 0" in stdout.getvalue()
    assert [call[0] for call in session.calls] == ["GET"]


@pytest.mark.parametrize(
    ("resource_args", "expected_title"),
    (
        (("conversation",), "Canonical conversation transcript"),
        (("tasks",), "Canonical Task board"),
        (("agents",), "Resident Agent members"),
        (("approvals",), "Approval truth"),
        (("failures",), "Public-safe failure observations"),
        (("readiness",), "Resident readiness and workspace provisioning"),
        (("workspace",), "Canonical workspace truth"),
        (("tool-exposure",), "Direct and Deferred tool exposure"),
        (("runtime", "show"), "Canonical runtime truth"),
        (("protocol", "--view", "delegations"), "Delegations and protocol records"),
        (("protocol", "--view", "inbox"), "Protocol inbox"),
    ),
)
def test_cli_exact_v2_projection_views_are_read_only(
    tmp_path: Path,
    resource_args: tuple[str, ...],
    expected_title: str,
) -> None:
    release = _release()
    release_path = tmp_path / "release.json"
    _write_release(release_path, release)
    session = _session(release)
    stdout = StringIO()

    exit_code = run_cli(
        [
            "--release-identity",
            str(release_path),
            "--session-id",
            "session-1",
            *resource_args,
        ],
        session=session,
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert expected_title in stdout.getvalue()
    assert [call[0] for call in session.calls] == ["GET"]


def test_cli_workspace_renderer_exposes_populated_collaboration_and_failure_truth() -> (
    None
):
    payload = _projection(_release()).to_dict()
    core = payload["core"]
    assert isinstance(core, dict)
    core["tasks"] = [
        {"task_id": "task-1", "subject": "Inspect evidence", "status": "active"}
    ]
    core["agents"] = [
        {
            "agent_member_id": "teammate-1",
            "role": "teammate",
            "readiness": "ready",
        }
    ]
    protocol = core["protocol"]
    assert isinstance(protocol, dict)
    protocol["records"] = [
        {
            "protocol_ref": "delegation-1",
            "kind": "task_delegation",
            "task_id": "task-1",
            "recipient_member_id": "teammate-1",
        }
    ]
    protocol["inbox"] = [
        {
            "message_id": "inbox-1",
            "recipient_member_id": "teammate-1",
            "status": "pending",
        }
    ]
    core["approvals"] = [
        {
            "approval_id": "approval-1",
            "status": "pending",
            "intent_digest": _digest("approval-1"),
        }
    ]
    failures = core["failures"]
    assert isinstance(failures, dict)
    failures["observations"] = [
        _public_failure("failure-runtime-1", session_id="session-1")
    ]

    rendered = render_v3_workspace_v2(payload)

    for expected in (
        "task-1",
        "teammate-1",
        "delegation-1",
        "inbox-1",
        "approval-1",
        "failure-runtime-1",
        "diagnostic-failure-runtime-1",
        "inspect_recovery_state",
    ):
        assert expected in rendered


def test_cli_exact_v2_bootstraps_session_without_projection_preflight(
    tmp_path: Path,
) -> None:
    release = _release()
    release_path = tmp_path / "release.json"
    _write_release(release_path, release)
    bootstrap = _admission_response(
        release,
        receipt={
            "operation": "session.bootstrap",
            "result": {"workspace_readiness": "provisioning"},
        },
    )
    inspection = _session(
        release,
        projection=_projection(release, session_id="session-2"),
    ).response
    session = _SequencedSession([bootstrap, inspection])
    stdout = StringIO()
    stderr = StringIO()

    exit_code = run_cli(
        [
            "--release-identity",
            str(release_path),
            "sessions",
            "create",
            "--project-id",
            "project-1",
            "--session-id",
            "session-2",
            "--objective",
            "prove plugin-free bootstrap",
            "--idempotency-key",
            "bootstrap-session-2",
        ],
        session=session,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert len(session.calls) == 2
    method, path, headers, body = session.calls[0]
    assert (method, path) == ("POST", "/v3/sessions")
    assert headers["OpenZyme-Release-Digest"] == release.release_digest
    assert "OpenZyme-Projection-Digest" not in headers
    assert json.loads(body or b"{}") == {
        "objective": "prove plugin-free bootstrap",
        "project_id": "project-1",
        "session_id": "session-2",
        "title": "prove plugin-free bootstrap",
    }
    assert session.calls[1][0:2] == ("GET", "/v3/sessions/session-2/workspace")
    assert '"canonical_workspace"' in stdout.getvalue()


def test_cli_approval_decision_reads_exact_intent_and_reinspects_truth(
    tmp_path: Path,
) -> None:
    release = _release()
    release_path = tmp_path / "release.json"
    _write_release(release_path, release)
    pending = _projection(
        release,
        approvals=(
            {
                "approval_id": "approval-1",
                "intent_digest": _digest("approval-1"),
                "status": "pending",
            },
        ),
    )
    settled = _projection(
        release,
        approvals=(
            {
                "approval_id": "approval-1",
                "intent_digest": _digest("approval-1"),
                "status": "approved",
            },
        ),
    )
    pending_response = _session(release, projection=pending).response
    mutation = _admission_response(
        release,
        receipt={"operation": "approval.decide", "status": "accepted"},
        projection=pending,
    )
    settled_response = _session(release, projection=settled).response
    session = _SequencedSession(
        [pending_response, pending_response, mutation, settled_response]
    )
    stdout = StringIO()

    exit_code = run_cli(
        [
            "--release-identity",
            str(release_path),
            "--session-id",
            "session-1",
            "approvals",
            "decide",
            "--approval-id",
            "approval-1",
            "--decision",
            "approved",
            "--idempotency-key",
            "approval-gesture-1",
        ],
        session=session,
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert [call[0] for call in session.calls] == ["GET", "GET", "POST", "GET"]
    assert session.calls[2][1] == (
        "/v3/sessions/session-1/approvals/approval-1/decision"
    )
    assert json.loads(session.calls[2][3] or b"{}") == {
        "decision": "approved",
        "intent_digest": _digest("approval-1"),
        "resolution_ref": "approval-gesture-1",
    }
    rendered = json.loads(stdout.getvalue())
    assert rendered["receipt"]["operation"] == "approval.decide"
    assert rendered["canonical_workspace"]["core"]["approvals"][0]["status"] == (
        "approved"
    )


def test_cli_admits_exact_reconciliation_and_reinspects_pending_truth() -> None:
    release = _release()
    blocked = _projection(release, readiness="blocked")
    pending = _projection(release, readiness="reconciliation-pending")
    blocked_response = _session(release, projection=blocked).response
    mutation = _admission_response(
        release,
        projection=blocked,
        receipt={
            "operation": "admit_reconciliation",
            "mutation_applied": True,
            "effect_certainty": "no_effect",
            "fallback_performed": False,
            "result": _reconciliation_admission_receipt_result(),
        },
    )
    session = _SequencedSession(
        [blocked_response, mutation, _session(release, projection=pending).response]
    )
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=session,
    )

    result = client.reconcile_workspace_provisioning(
        "session-1",
        expected_intent_version=3,
        claim_seconds=120,
        idempotency_key="reconcile-provisioning-1",
    )

    assert result["response_status"] == 202
    assert result["receipt"]["effect_certainty"] == "no_effect"
    assert result["receipt"]["fallback_performed"] is False
    assert result["receipt"]["result"]["requested_claim_seconds"] == 120
    assert result["receipt"]["result"]["reconciliation_enqueued"] is True
    assert (
        result["receipt"]["result"]["workspace_provisioning_reconciliation_enqueued"]
        is True
    )
    assert result["receipt"]["result"]["adapter_invoked"] is False
    assert result["receipt"]["result"]["runtime_executed"] is False
    assert result["receipt"]["result"]["task_transition_performed"] is False
    assert result["receipt"]["result"]["external_effect_performed"] is False
    assert (
        result["canonical_workspace"]["core"]["session"]["resident_readiness"][
            "readiness"
        ]
        == "blocked"
    )
    provisioning = result["canonical_workspace"]["core"]["workspace"]["provisioning"]
    assert provisioning["intent_id"] == "provisioning-1"
    assert provisioning["intent_state_version"] == 3
    assert provisioning["status"] == "blocked"
    assert provisioning["reconciliation"]["status"] == "pending"
    assert provisioning["reconciliation"]["fallback_performed"] is False
    assert [call[0] for call in session.calls] == ["GET", "POST", "GET"]
    assert session.calls[1][1] == (
        "/v3/sessions/session-1/workspace/provisioning/reconcile"
    )
    assert json.loads(session.calls[1][3] or b"{}") == {
        "claim_seconds": 120,
        "expected_intent_version": 3,
        "intent_digest": _digest("provisioning-1"),
        "intent_id": "provisioning-1",
    }


def test_cli_rejects_202_that_claims_inline_reconciliation_observation() -> None:
    release = _release()
    blocked = _projection(release, readiness="blocked")
    mutation = _admission_response(
        release,
        projection=blocked,
        receipt={
            "operation": "settle_reconciliation",
            "mutation_applied": True,
            "effect_certainty": "terminal_known",
            "fallback_performed": False,
            "result": {
                **_reconciliation_admission_receipt_result(),
                "status": "ready",
                "readiness": "ready",
                "reconciliation_enqueued": False,
                "workspace_provisioning_reconciliation_enqueued": False,
                "adapter_invoked": True,
                "external_effect_performed": True,
            },
        },
    )
    session = _SequencedSession(
        [
            _session(release, projection=blocked).response,
            mutation,
        ]
    )
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=session,
    )

    with pytest.raises(OpenZymeClientContractError) as rejected:
        client.reconcile_workspace_provisioning(
            "session-1",
            expected_intent_version=3,
            claim_seconds=120,
            idempotency_key="reconcile-inline-provisioning-1",
        )

    assert rejected.value.code == (
        "cli_workspace_reconciliation_admission_receipt_invalid"
    )
    assert rejected.value.mutation_applied is True
    assert rejected.value.effect_certainty == "terminal_known"
    assert rejected.value.fallback_performed is False
    assert [call[0] for call in session.calls] == ["GET", "POST"]


@pytest.mark.parametrize(
    "result_updates",
    (
        {"adapter_invoked": True},
        {"runtime_executed": True},
        {"task_transition_performed": True},
        {"status": "ready"},
        {"attempt": 2},
        {"reconciliation_id": "provisioning-1"},
        {"claim_token": "private-token"},
        {"tool_requests": ["private-tool"]},
    ),
)
def test_cli_rejects_hostile_reconciliation_admission_receipt(
    result_updates: dict[str, object],
) -> None:
    release = _release()
    blocked = _projection(release, readiness="blocked")
    result = _reconciliation_admission_receipt_result()
    result.update(result_updates)
    mutation = _admission_response(
        release,
        projection=blocked,
        receipt={
            "operation": "admit_reconciliation",
            "mutation_applied": True,
            "effect_certainty": "no_effect",
            "fallback_performed": False,
            "result": result,
        },
    )
    session = _SequencedSession(
        [_session(release, projection=blocked).response, mutation]
    )
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=session,
    )

    with pytest.raises(OpenZymeClientContractError) as rejected:
        client.reconcile_workspace_provisioning(
            "session-1",
            expected_intent_version=3,
            claim_seconds=120,
            idempotency_key="reconcile-hostile-provisioning-1",
        )

    assert rejected.value.code == (
        "cli_workspace_reconciliation_admission_receipt_invalid"
    )
    assert "private-token" not in str(rejected.value)
    assert "private-tool" not in str(rejected.value)
    assert [call[0] for call in session.calls] == ["GET", "POST"]


def test_cli_creates_successor_from_exact_known_failure_without_running_it() -> None:
    release = _release()
    blocked = _projection(release, readiness="blocked-known")
    pending = _projection(release, readiness="successor-pending")
    blocked_response = _session(release, projection=blocked).response
    mutation = _admission_response(
        release,
        projection=blocked,
        receipt={
            "operation": "replace_failed_generation",
            "mutation_applied": True,
            "effect_certainty": "no_effect",
            "fallback_performed": False,
            "result": _successor_receipt_result(resolved_reconciliation_id=None),
        },
    )
    session = _SequencedSession(
        [blocked_response, mutation, _session(release, projection=pending).response]
    )
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=session,
    )

    result = client.create_workspace_provisioning_successor(
        "session-1",
        expected_failed_intent_version=3,
        resolved_reconciliation_id=None,
        idempotency_key="successor-provisioning-1",
    )

    assert result["response_status"] == 202
    assert result["receipt"]["effect_certainty"] == "no_effect"
    assert result["receipt"]["fallback_performed"] is False
    assert result["receipt"]["result"] == _successor_receipt_result(
        resolved_reconciliation_id=None
    )
    assert result["receipt"]["result"]["runtime_executed"] is False
    assert result["receipt"]["result"]["task_transition_performed"] is False
    assert result["receipt"]["result"]["external_effect_performed"] is False
    successor = result["canonical_workspace"]["core"]["workspace"]["provisioning"]
    assert successor["intent_id"] == "provisioning-2"
    assert successor["intent_state_version"] == 1
    assert successor["workspace_generation"] == 2
    assert successor["status"] == "pending"
    assert [call[0] for call in session.calls] == ["GET", "POST", "GET"]
    assert session.calls[1][1] == (
        "/v3/sessions/session-1/workspace/provisioning/successor"
    )
    assert json.loads(session.calls[1][3] or b"{}") == {
        "expected_failed_intent_version": 3,
        "failed_intent_digest": _digest("provisioning-1"),
        "failed_intent_id": "provisioning-1",
        "resolved_reconciliation_id": None,
    }


def test_cli_derives_exact_resolved_reconciliation_for_successor() -> None:
    release = _release()
    blocked = _projection(release, readiness="blocked-reconciled")
    pending = _projection(release, readiness="successor-pending")
    mutation = _admission_response(
        release,
        projection=blocked,
        receipt={
            "operation": "replace_failed_generation",
            "mutation_applied": True,
            "effect_certainty": "no_effect",
            "fallback_performed": False,
            "result": _successor_receipt_result(
                resolved_reconciliation_id="reconciliation-provisioning-1"
            ),
        },
    )
    session = _SequencedSession(
        [
            _session(release, projection=blocked).response,
            mutation,
            _session(release, projection=pending).response,
        ]
    )
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=session,
    )

    result = client.create_workspace_provisioning_successor(
        "session-1",
        expected_failed_intent_version=3,
        resolved_reconciliation_id=None,
        idempotency_key="successor-reconciled-provisioning-1",
    )

    assert result["response_status"] == 202
    assert result["receipt"]["effect_certainty"] == "no_effect"
    assert result["receipt"]["fallback_performed"] is False
    assert json.loads(session.calls[1][3] or b"{}") == {
        "expected_failed_intent_version": 3,
        "failed_intent_digest": _digest("provisioning-1"),
        "failed_intent_id": "provisioning-1",
        "resolved_reconciliation_id": "reconciliation-provisioning-1",
    }


@pytest.mark.parametrize(
    ("effect_certainty", "result_updates"),
    (
        ("terminal_known", {}),
        ("no_effect", {"adapter_invoked": True}),
        ("no_effect", {"runtime_executed": True}),
        ("no_effect", {"task_transition_performed": True}),
        (
            "no_effect",
            {"tool_requests": [{"name": "user-guessed.hidden-tool"}]},
        ),
    ),
)
def test_cli_rejects_hostile_successor_receipt_before_reinspection(
    effect_certainty: str,
    result_updates: dict[str, object],
) -> None:
    release = _release()
    blocked = _projection(release, readiness="blocked-known")
    pending = _projection(release, readiness="successor-pending")
    receipt_result = _successor_receipt_result(resolved_reconciliation_id=None)
    receipt_result.update(result_updates)
    mutation = _admission_response(
        release,
        projection=blocked,
        receipt={
            "operation": "replace_failed_generation",
            "mutation_applied": True,
            "effect_certainty": effect_certainty,
            "fallback_performed": False,
            "result": receipt_result,
        },
    )
    session = _SequencedSession(
        [
            _session(release, projection=blocked).response,
            mutation,
            _session(release, projection=pending).response,
        ]
    )
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=session,
    )

    with pytest.raises(OpenZymeClientContractError) as rejected:
        client.create_workspace_provisioning_successor(
            "session-1",
            expected_failed_intent_version=3,
            resolved_reconciliation_id=None,
            idempotency_key="hostile-successor-provisioning-1",
        )

    assert rejected.value.code == ("cli_workspace_successor_admission_receipt_invalid")
    assert rejected.value.mutation_applied is True
    assert rejected.value.effect_certainty == effect_certainty
    assert rejected.value.fallback_performed is False
    assert [call[0] for call in session.calls] == ["GET", "POST"]


def test_cli_rejects_stale_resolved_reconciliation_before_successor_post() -> None:
    release = _release()
    session = _session(
        release,
        projection=_projection(release, readiness="blocked-reconciled"),
    )
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=session,
    )

    with pytest.raises(OpenZymeClientContractError) as rejected:
        client.create_workspace_provisioning_successor(
            "session-1",
            expected_failed_intent_version=3,
            resolved_reconciliation_id="reconciliation-stale-1",
            idempotency_key="successor-stale-reconciliation-1",
        )

    assert rejected.value.code == "cli_workspace_recovery_fence_stale"
    assert [call[0] for call in session.calls] == ["GET"]


@pytest.mark.parametrize(
    ("operation", "readiness"),
    (
        ("reconcile", "blocked"),
        ("successor", "blocked-known"),
    ),
)
def test_cli_workspace_recovery_rejects_explicit_stale_version_before_post(
    operation: str,
    readiness: str,
) -> None:
    release = _release()
    session = _session(release, projection=_projection(release, readiness=readiness))
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=session,
    )

    with pytest.raises(OpenZymeClientContractError) as rejected:
        if operation == "reconcile":
            client.reconcile_workspace_provisioning(
                "session-1",
                expected_intent_version=2,
                claim_seconds=120,
                idempotency_key="reconcile-stale-1",
            )
        else:
            client.create_workspace_provisioning_successor(
                "session-1",
                expected_failed_intent_version=2,
                resolved_reconciliation_id=None,
                idempotency_key="successor-stale-1",
            )

    assert rejected.value.code == "cli_workspace_recovery_fence_stale"
    assert [call[0] for call in session.calls] == ["GET"]


def test_cli_workspace_reconciliation_rejects_unbounded_claim_before_get() -> None:
    release = _release()
    session = _session(release, projection=_projection(release, readiness="blocked"))
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=session,
    )

    with pytest.raises(OpenZymeClientContractError) as rejected:
        client.reconcile_workspace_provisioning(
            "session-1",
            expected_intent_version=3,
            claim_seconds=0,
            idempotency_key="reconcile-unbounded-1",
        )

    assert rejected.value.code == "cli_workspace_reconciliation_claim_invalid"
    assert session.calls == []


@pytest.mark.parametrize(
    ("command", "readiness", "extra_args", "expected_path"),
    (
        (
            "reconcile",
            "blocked",
            (
                "--expected-intent-version",
                "3",
                "--claim-seconds",
                "120",
            ),
            "/v3/sessions/session-1/workspace/provisioning/reconcile",
        ),
        (
            "successor",
            "blocked-known",
            ("--expected-failed-intent-version", "3"),
            "/v3/sessions/session-1/workspace/provisioning/successor",
        ),
    ),
)
def test_cli_workspace_recovery_commands_use_exact_http_only_path(
    tmp_path: Path,
    command: str,
    readiness: str,
    extra_args: tuple[str, ...],
    expected_path: str,
) -> None:
    release = _release()
    release_path = tmp_path / "release.json"
    _write_release(release_path, release)
    blocked = _projection(release, readiness=readiness)
    blocked_response = _session(release, projection=blocked).response
    mutation = _admission_response(
        release,
        projection=blocked,
        receipt={
            "operation": (
                "admit_reconciliation"
                if command == "reconcile"
                else "replace_failed_generation"
            ),
            "mutation_applied": True,
            "effect_certainty": "no_effect",
            "fallback_performed": False,
            "result": (
                _reconciliation_admission_receipt_result()
                if command == "reconcile"
                else _successor_receipt_result(resolved_reconciliation_id=None)
            ),
        },
    )
    canonical = _projection(
        release,
        readiness=(
            "reconciliation-pending" if command == "reconcile" else "successor-pending"
        ),
    )
    session = _SequencedSession(
        [
            blocked_response,
            mutation,
            _session(release, projection=canonical).response,
        ]
    )
    stdout = StringIO()

    exit_code = run_cli(
        [
            "--release-identity",
            str(release_path),
            "--session-id",
            "session-1",
            "provisioning",
            command,
            *extra_args,
            "--idempotency-key",
            f"{command}-provisioning-1",
        ],
        session=session,
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert [call[0] for call in session.calls] == ["GET", "POST", "GET"]
    assert session.calls[1][1] == expected_path
    rendered = json.loads(stdout.getvalue())
    assert rendered["response_status"] == 202
    assert rendered["receipt"]["effect_certainty"] == "no_effect"
    assert rendered["receipt"]["fallback_performed"] is False
    assert rendered["receipt"]["result"]["runtime_executed"] is False
    assert rendered["receipt"]["result"]["task_transition_performed"] is False
    assert rendered["receipt"]["result"]["external_effect_performed"] is False
    if command == "reconcile":
        assert rendered["receipt"]["result"]["requested_claim_seconds"] == 120
        assert rendered["receipt"]["result"]["reconciliation_enqueued"] is True
        assert (
            rendered["receipt"]["result"][
                "workspace_provisioning_reconciliation_enqueued"
            ]
            is True
        )


def test_cli_disables_resident_mutation_before_post_while_provisioning() -> None:
    release = _release()
    pending = _projection(release, readiness="provisioning")
    session = _session(release, projection=pending)
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=session,
    )

    with pytest.raises(OpenZymeClientContractError) as rejected:
        client.post_message(
            "session-1",
            message="continue",
            task_id=None,
            lane_id=None,
            workflow_refs=(),
            skill_keys=(),
            idempotency_key="message-1",
        )

    assert rejected.value.code == "cli_resident_teammate_not_ready"
    assert "wait_for_provisioning_worker" in str(rejected.value)
    assert [call[0] for call in session.calls] == ["GET"]


def test_cli_rejects_non_202_admission_without_treating_body_as_truth() -> None:
    release = _release()
    inspection = _session(release).response
    wrong_status = _Response(
        status_code=200,
        content=b'{"status":"accepted"}',
        headers=dict(inspection.headers),
    )
    session = _SequencedSession([inspection, wrong_status])
    client = HostApiV2Client(
        "http://127.0.0.1:8000",
        expected_release=release,
        session=session,
    )

    with pytest.raises(OpenZymeClientContractError) as rejected:
        client.drain_runtime(
            "session-1",
            max_signals=1,
            max_steps_per_agent=1,
            idempotency_key="drain-1",
        )

    assert rejected.value.code == "cli_admission_status_invalid"
    assert rejected.value.mutation_applied is None
    assert [call[0] for call in session.calls] == ["GET", "POST"]


def test_cli_exact_v2_requires_explicit_mutation_identity_before_transport(
    tmp_path: Path,
) -> None:
    release = _release()
    release_path = tmp_path / "release.json"
    _write_release(release_path, release)
    session = _session(release)
    stderr = StringIO()

    exit_code = run_cli(
        [
            "--release-identity",
            str(release_path),
            "--session-id",
            "session-1",
            "sessions",
            "message",
            "--message",
            "continue",
        ],
        session=session,
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert "explicit --idempotency-key" in stderr.getvalue()
    assert session.calls == []


def test_cli_has_no_legacy_mode_when_release_identity_is_absent() -> None:
    session = _session(_release())
    stderr = StringIO()

    exit_code = run_cli(
        ["--session-id", "session-1", "sessions", "show"],
        session=session,
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert "operator-pinned release identity" in stderr.getvalue()
    assert session.calls == []
