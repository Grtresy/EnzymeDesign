from dataclasses import replace

import pytest

from openzyme_contracts import FILE_WORKSPACE_CORE_SECTION_FIELDS
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION
from openzyme_contracts import FileWorkspaceCoreProjectionV2
from openzyme_contracts import FileWorkspacePublicV2
from openzyme_contracts import FileWorkspaceToolReflection
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import ToolAffordance
from openzyme_contracts import ToolAffordanceSnapshot
from openzyme_contracts import ToolAffordanceState
from openzyme_contracts import ToolExposure
from openzyme_contracts import ToolExposureDecision
from openzyme_contracts import ToolExposureSnapshot
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import load_file_workspace_public_v2_json_schema
from openzyme_contracts.public_workspace import (
    FILE_WORKSPACE_FAILURE_OBSERVATION_PUBLIC_FIELDS,
)
from openzyme_contracts.public_workspace import (
    FILE_WORKSPACE_PUBLIC_TOOL_AFFORDANCE_STATES,
)
from openzyme_contracts.public_workspace import (
    FILE_WORKSPACE_RUNTIME_OUTCOME_CONSUMPTION_PUBLIC_FIELDS,
)
from openzyme_contracts.public_workspace import FILE_WORKSPACE_TOOL_AFFORDANCE_FIELDS
from openzyme_contracts.public_workspace import FILE_WORKSPACE_TOOL_REFLECTION_FIELDS


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


def _core_payload() -> dict[str, object]:
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
    payload["failures"] = {"observations": []}
    return payload


def _snapshot() -> ToolAffordanceSnapshot:
    snapshot = ToolAffordanceSnapshot(
        snapshot_id="snapshot-1",
        session_id="session-1",
        agent_member_id="member-1",
        turn_id="turn-1",
        declared_tool_catalog_digest=_digest("tools"),
        capability_binding_digest=_digest("binding"),
        authority_lease_digest=_digest("authority"),
        workspace_generation=1,
        health_observation_digest=_digest("health"),
        subject_policy_digest=_digest("policy"),
        affordances=(
            ToolAffordance(
                tool_name="workspace.status",
                tool_contract_digest=_digest("workspace.status"),
                state=ToolAffordanceState.AVAILABLE,
                required_authorities=(),
            ),
        ),
        created_at="2026-08-20T00:00:00Z",
        snapshot_digest="sha256:" + "0" * 64,
    )
    return replace(
        snapshot,
        snapshot_digest=canonical_sha256_digest(snapshot.digest_payload()),
    )


def test_affordance_snapshot_uses_zero_for_an_unprovisioned_workspace() -> None:
    snapshot = replace(_snapshot(), workspace_generation=0)
    snapshot = replace(
        snapshot,
        snapshot_digest=canonical_sha256_digest(snapshot.digest_payload()),
    )
    assert snapshot.workspace_generation == 0
    assert snapshot.has_valid_digest()

    with pytest.raises(ValueError, match="non-negative"):
        replace(_snapshot(), workspace_generation=-1)


def test_public_v2_root_and_release_identity_are_closed() -> None:
    reflection = FileWorkspaceToolReflection(
        declared_tool_catalog_digest=_digest("tools"),
        affordance_snapshot=_snapshot(),
    )
    core = _core_payload()
    core["capability_binding"] = {"binding_digest": _digest("binding")}
    core["tool_reflection"] = reflection.to_dict()
    projection = FileWorkspacePublicV2(
        release=_release(),
        core=FileWorkspaceCoreProjectionV2(core),
        extensions=(),
    )

    payload = projection.to_dict()
    assert set(payload) == {"schema_version", "release", "core", "extensions"}
    assert payload["schema_version"] == FILE_WORKSPACE_PUBLIC_V2_SCHEMA_VERSION
    assert payload["release"]["public_contract_digest"] == (
        FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
    )
    assert FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE.endswith("version=2")
    assert payload["extensions"] == {}
    assert projection.projection_digest.startswith("sha256:")


def test_layered_release_identity_parser_is_closed_and_round_trips() -> None:
    release = _release()
    assert LayeredReleaseIdentity.from_dict(release.to_dict()) == release

    unknown = {**release.to_dict(), "legacy_tool_catalog_digest": _digest("old")}
    with pytest.raises(ValueError, match="fields are closed"):
        LayeredReleaseIdentity.from_dict(unknown)

    stale = {**release.to_dict(), "schema_version": "legacy_release@1"}
    with pytest.raises(ValueError, match="unsupported"):
        LayeredReleaseIdentity.from_dict(stale)


def test_packaged_public_v2_json_schema_matches_runtime_contract() -> None:
    schema = load_file_workspace_public_v2_json_schema()
    assert set(schema["required"]) == {
        "schema_version",
        "release",
        "core",
        "extensions",
    }
    core = schema["$defs"]["core"]
    assert set(core["required"]) == FILE_WORKSPACE_CORE_SECTION_FIELDS
    reflection = schema["$defs"]["tool_reflection"]
    assert set(reflection["required"]) == FILE_WORKSPACE_TOOL_REFLECTION_FIELDS
    affordance = schema["$defs"]["tool_affordance"]
    assert set(affordance["required"]) == FILE_WORKSPACE_TOOL_AFFORDANCE_FIELDS
    assert set(affordance["properties"]["state"]["enum"]) == (
        FILE_WORKSPACE_PUBLIC_TOOL_AFFORDANCE_STATES
    )
    failures = schema["$defs"]["failure_observations"]
    assert failures["additionalProperties"] is False
    failure = schema["$defs"]["failure_observation_public"]
    assert set(failure["required"]) == (
        FILE_WORKSPACE_FAILURE_OBSERVATION_PUBLIC_FIELDS
    )
    consumption = schema["$defs"]["runtime_outcome_consumption"]
    assert set(consumption["required"]) == (
        FILE_WORKSPACE_RUNTIME_OUTCOME_CONSUMPTION_PUBLIC_FIELDS
    )


def test_public_v2_rejects_top_level_domain_fields_and_catalog_drift() -> None:
    core = _core_payload()
    core["scientific_attempts"] = []
    with pytest.raises(ValueError, match="core section fields are closed"):
        FileWorkspaceCoreProjectionV2(core)

    with pytest.raises(ValueError, match="another declared catalog"):
        FileWorkspaceToolReflection(
            declared_tool_catalog_digest=_digest("other-tools"),
            affordance_snapshot=_snapshot(),
        )


def test_public_v2_accepts_ready_reconciliation_without_rewriting_failed_intent() -> (
    None
):
    intent_digest = _digest("blocked-intent")
    core = _core_payload()
    core["session"] = {
        "resident_readiness": {
            "schema_version": "resident_teammate_readiness@1",
            "readiness": "ready",
            "workspace_id": "workspace-1",
            "workspace_generation": 1,
            "provisioning_intent_id": "intent-1",
            "provisioning_intent_digest": intent_digest,
            "failure_id": None,
            "next_action": "message_or_drain",
        }
    }
    core["workspace"] = {
        "provisioning": {
            "schema_version": "workspace_provisioning_public@2",
            "intent_id": "intent-1",
            "intent_digest": intent_digest,
            "intent_state_version": 3,
            "status": "blocked",
            "workspace_id": "workspace-1",
            "workspace_generation": 1,
            "runtime_binding_id": "workspace-1",
            "failure_id": "failure-original",
            "error_code": "workspace_provisioning_dispatch_in_doubt",
            "effect_certainty": "dispatch_in_doubt",
            "mutation_applied": None,
            "fallback_performed": False,
            "retry_permitted": False,
            "reconcile_required": True,
            "diagnostic_id": "diagnostic-original",
            "next_action": "message_or_drain",
            "reconciliation": {
                "schema_version": ("workspace_provisioning_reconciliation_public@1"),
                "reconciliation_id": "reconciliation-1",
                "reconciliation_digest": _digest("reconciliation"),
                "status": "ready",
                "attempt": 1,
                "parent_reconciliation_id": None,
                "blocked_intent_state_version": 3,
                "blocked_intent_digest": intent_digest,
                "source_receipt_id": "receipt-original",
                "source_receipt_digest": _digest("receipt-original"),
                "dispatch_receipt_digest": _digest("dispatch-original"),
                "result_receipt_id": "receipt-reconciled",
                "result_receipt_digest": _digest("receipt-reconciled"),
                "effect_certainty": "terminal_known",
                "mutation_applied": True,
                "fallback_performed": False,
                "retry_permitted": False,
                "reconcile_required": False,
                "failure_id": None,
                "diagnostic_id": None,
                "requested_at": "2026-08-24T00:01:00Z",
                "requested_claim_seconds": 60,
                "settled_at": "2026-08-24T00:02:00Z",
                "next_action": "message_or_drain",
            },
        }
    }
    core["capability_binding"] = {"binding_digest": _digest("binding")}
    core["tool_reflection"] = FileWorkspaceToolReflection(
        declared_tool_catalog_digest=_digest("tools"),
        affordance_snapshot=_snapshot(),
    ).to_dict()

    projection = FileWorkspaceCoreProjectionV2(core)

    provisioning = projection.payload["workspace"]["provisioning"]
    assert provisioning["status"] == "blocked"
    assert provisioning["reconciliation"]["status"] == "ready"


def test_public_v2_rejects_tool_reflection_binding_or_affordance_drift() -> None:
    reflection = FileWorkspaceToolReflection(
        declared_tool_catalog_digest=_digest("tools"),
        affordance_snapshot=_snapshot(),
    ).to_dict()
    core = _core_payload()
    core["capability_binding"] = {"binding_digest": _digest("other-binding")}
    core["tool_reflection"] = reflection
    with pytest.raises(ValueError, match="another capability binding"):
        FileWorkspaceCoreProjectionV2(core)

    core["capability_binding"] = {"binding_digest": _digest("binding")}
    core["tool_reflection"] = {
        **reflection,
        "available_tool_names": [],
    }
    with pytest.raises(ValueError, match="differ from public affordances"):
        FileWorkspaceCoreProjectionV2(core)


def test_public_tool_exposure_keeps_deferred_affordance_non_callable() -> None:
    snapshot = _snapshot()
    exposure = ToolExposureSnapshot(
        exposure_snapshot_id="exposure-1",
        session_id=snapshot.session_id,
        agent_member_id=snapshot.agent_member_id,
        turn_id=snapshot.turn_id,
        subject_policy_digest=_digest("policy"),
        declared_tool_catalog_digest=snapshot.declared_tool_catalog_digest,
        capability_binding_digest=snapshot.capability_binding_digest,
        affordance_snapshot_id=snapshot.snapshot_id,
        affordance_snapshot_digest=snapshot.snapshot_digest,
        workflow_authority_id="authority-1",
        workflow_authority_epoch=1,
        workflow_authority_digest=_digest("authority"),
        catalog_tool_names=("workspace.status",),
        decisions=(
            ToolExposureDecision(
                tool_name="workspace.status",
                exposure=ToolExposure.DEFERRED,
                reason_code="long_tail",
            ),
        ),
        created_at="2026-08-24T00:00:00+00:00",
    )
    reflection = FileWorkspaceToolReflection(
        declared_tool_catalog_digest=_digest("tools"),
        affordance_snapshot=snapshot,
        exposure_snapshot=exposure,
    ).to_dict()

    assert reflection["available_tool_names"] == []
    assert reflection["affordances"][0]["state"] == "available"
    assert reflection["tool_exposure"]["deferred_tool_names"] == ["workspace.status"]
    assert "hidden_tool_names" not in reflection["tool_exposure"]

    core = _core_payload()
    core["capability_binding"] = {"binding_digest": _digest("binding")}
    core["tool_reflection"] = reflection
    FileWorkspaceCoreProjectionV2(core)


def test_public_runtime_command_accepts_initial_zero_fence() -> None:
    core = _core_payload()
    core["capability_binding"] = {"binding_digest": _digest("binding")}
    core["tool_reflection"] = FileWorkspaceToolReflection(
        declared_tool_catalog_digest=_digest("tools"),
        affordance_snapshot=_snapshot(),
    ).to_dict()
    core["runtime"] = {
        "commands": [
            {
                "schema_version": "runtime_command_public@1",
                "command_id": "runtime-command-1",
                "session_id": "session-1",
                "command_type": "runtime.drain",
                "request_digest": _digest("runtime-request"),
                "idempotency_key": "runtime-drain-1",
                "status": "accepted",
                "max_signals": 2,
                "max_steps_per_agent": 3,
                "auto_enqueue_ready_tasks": False,
                "state_version": 1,
                "fencing_token": 0,
                "accepted_at": "2026-08-24T00:00:00+00:00",
                "claim_owner": None,
                "lease_expires_at": None,
                "bounded_outcome_summary": None,
                "failure_id": None,
                "diagnostic_id": None,
                "error_code": None,
                "safe_error_summary": None,
                "safe_retry_hint": None,
                "started_at": None,
                "completed_at": None,
            }
        ]
    }

    FileWorkspaceCoreProjectionV2(core)


def test_public_runtime_command_outcome_summary_is_closed() -> None:
    core = _core_payload()
    core["capability_binding"] = {"binding_digest": _digest("binding")}
    core["tool_reflection"] = FileWorkspaceToolReflection(
        declared_tool_catalog_digest=_digest("tools"),
        affordance_snapshot=_snapshot(),
    ).to_dict()
    summary = {
        "schema_version": "runtime_command_outcome_summary_public@1",
        "processed_signals": 1,
        "turn_count": 1,
        "turns_digest": canonical_sha256_digest([{"turn_id": "turn-1"}]),
        "runtime_executed": True,
        "task_transition_performed": False,
        "fallback_performed": False,
    }
    core["runtime"] = {
        "commands": [
            {
                "schema_version": "runtime_command_public@1",
                "command_id": "runtime-command-1",
                "session_id": "session-1",
                "command_type": "runtime.drain",
                "request_digest": _digest("runtime-request"),
                "idempotency_key": "runtime-drain-1",
                "status": "completed",
                "max_signals": 2,
                "max_steps_per_agent": 3,
                "auto_enqueue_ready_tasks": False,
                "state_version": 3,
                "fencing_token": 2,
                "accepted_at": "2026-08-24T00:00:00+00:00",
                "claim_owner": "runtime-worker-1",
                "lease_expires_at": "2026-08-24T00:02:00+00:00",
                "bounded_outcome_summary": summary,
                "failure_id": None,
                "diagnostic_id": None,
                "error_code": None,
                "safe_error_summary": None,
                "safe_retry_hint": None,
                "started_at": "2026-08-24T00:00:01+00:00",
                "completed_at": "2026-08-24T00:01:00+00:00",
            }
        ]
    }
    FileWorkspaceCoreProjectionV2(core)

    summary["tool_requests"] = [
        {"tool_name": "hidden.admin", "arguments": {"private": "argument"}}
    ]
    with pytest.raises(ValueError, match="forbidden public field|fields are closed"):
        FileWorkspaceCoreProjectionV2(core)


def test_public_runtime_outcome_consumption_is_aggregate_only_and_closed() -> None:
    core = _core_payload()
    core["capability_binding"] = {"binding_digest": _digest("binding")}
    core["tool_reflection"] = FileWorkspaceToolReflection(
        declared_tool_catalog_digest=_digest("tools"),
        affordance_snapshot=_snapshot(),
    ).to_dict()
    consumption = {
        "schema_version": "runtime_outcome_consumption_public@1",
        "consumption_id": "consumption-1",
        "consumption_digest": _digest("consumption-1"),
        "command_id": "command-1",
        "command_digest": _digest("command-1"),
        "outcome_id": "outcome-1",
        "outcome_digest": _digest("outcome-1"),
        "outcome_receipt_id": "receipt-1",
        "outcome_receipt_digest": _digest("receipt-1"),
        "session_id": "session-1",
        "agent_id": "agent-1",
        "agent_member_id": "member-1",
        "signal_id": "signal-1",
        "signal_attempt": 1,
        "continuation_intent_id": None,
        "settlement_intent_id": "settlement-1",
        "consumed_at": "2026-08-24T00:01:00Z",
    }
    core["runtime"] = {"outcome_consumptions": [consumption]}
    FileWorkspaceCoreProjectionV2(core)

    consumption["outcome_receipt"] = {
        "outcome": {
            "messages": ["PRIVATE MESSAGE"],
            "tool_requests": [{"tool_name": "hidden.admin"}],
        }
    }
    with pytest.raises(ValueError, match="forbidden public field|fields are closed"):
        FileWorkspaceCoreProjectionV2(core)


def test_public_projection_rejects_legacy_failure_observation() -> None:
    core = _core_payload()
    core["capability_binding"] = {"binding_digest": _digest("binding")}
    core["tool_reflection"] = FileWorkspaceToolReflection(
        declared_tool_catalog_digest=_digest("tools"),
        affordance_snapshot=_snapshot(),
    ).to_dict()
    core["failures"] = {
        "observations": [
            {
                "schema_version": "failure_observation@1",
                "failure_id": "failure-legacy-1",
                "session_id": "session-1",
            }
        ]
    }
    with pytest.raises(ValueError, match="legacy failure observation"):
        FileWorkspaceCoreProjectionV2(core)


@pytest.mark.parametrize(
    ("section", "value", "match"),
    [
        ("tasks", {}, "section kind is invalid"),
        (
            "authority_leases",
            [{"agent_capability_lease_id": "legacy-lease"}],
            "forbidden public field",
        ),
        (
            "workspace",
            {"artifact_index": []},
            "forbidden public field",
        ),
        (
            "workspace",
            {"backend": {"host_path": "/srv/private"}},
            "forbidden public field",
        ),
        (
            "session",
            {"scientific_attempts": []},
            "forbidden public field",
        ),
        (
            "publications",
            [{"private_ref": "refs/openzyme/private/session/member/g1"}],
            "forbidden public field",
        ),
        (
            "workspace",
            {"lfs_object_locator": "/srv/lfs/aa/bb"},
            "forbidden public field",
        ),
        (
            "runtime",
            {"signals": [{"claim_token": "private-claim"}]},
            "forbidden public field",
        ),
        (
            "runtime",
            {"turn_commands": [{"runtime_lease_token": "private-lease"}]},
            "forbidden public field",
        ),
    ],
)
def test_public_v2_rejects_wrong_core_kinds_and_removed_or_private_fields(
    section: str,
    value: object,
    match: str,
) -> None:
    core = _core_payload()
    core[section] = value
    with pytest.raises(ValueError, match=match):
        FileWorkspaceCoreProjectionV2(core)
