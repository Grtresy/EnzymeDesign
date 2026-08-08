from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openzyme_core import MUTATION_LOCAL_SETTLEMENT_SCHEMA_ID
from openzyme_core import sandbox_image_record
from openzyme_host_api import aox_cutover_evidence as cutover_evidence
from openzyme_host_api import aox_formal_slot_failure as formal_slot_failure
from openzyme_host_api import aox_public_conductor_bundle as conductor_bundle
from openzyme_host_api.aox_attempt_authority import (
    AOX_ATTEMPT_AUTHORITY_SLOT_CLAIM_SCHEMA_ID,
)
from openzyme_host_api.aox_attempt_authority import authority_grant_payload
from openzyme_host_api.aox_attempt_authority import authority_grant_identity
from openzyme_host_api.aox_attempt_preflight import build_attempt_preflight_receipt
from openzyme_host_api.aox_attempt_preflight import load_attempt_preflight_receipt
from openzyme_host_api.aox_attempt_preflight import publish_attempt_launch_profile
from openzyme_host_api.aox_attempt_preflight import publish_attempt_preflight_receipt
from openzyme_host_api.aox_attempt_preflight import publish_attempt_slot_claim_evidence
from openzyme_host_api import aox_conductor_execution
from openzyme_host_api.aox_conductor_execution import (
    publish_conductor_execution_contract,
)
from openzyme_host_api.aox_cutover_evidence import BlankWorldRoots
from openzyme_host_api.aox_cutover_evidence import CutoverEvidenceError
from openzyme_host_api.aox_cutover_evidence import canonical_digest
from openzyme_host_api.aox_cutover_evidence import canonical_json_bytes
from openzyme_host_api.aox_host_supervision import HOST_SANDBOX_BOOTSTRAP_SCHEMA_ID
from openzyme_host_api.aox_host_supervision import HOST_STARTUP_SCHEMA_ID
from openzyme_host_api.aox_host_supervision import HOST_SUPERVISION_RECEIPT_SCHEMA_ID
from openzyme_host_api.aox_host_supervision import host_supervision_contract_digest
from openzyme_host_api.aox_host_supervision import validate_supervised_host_receipt
from openzyme_host_api.aox_launch_profile import build_aox_cutover_launch_profile
from openzyme_host_api.aox_public_conductor_bundle import PUBLIC_API_RECEIPT_SCHEMA_ID
from openzyme_host_api.aox_public_conductor_bundle import PUBLIC_CONDUCTOR_MESSAGE
from openzyme_host_api.aox_public_conductor_bundle import PUBLIC_CONDUCTOR_OBJECTIVE
from openzyme_host_api.aox_public_conductor_bundle import PUBLIC_CONDUCTOR_TITLE
from openzyme_host_api.aox_public_conductor_bundle import PUBLIC_RESPONSE_ENVELOPE_SCHEMA_ID
from openzyme_host_api.aox_public_conductor_bundle import _load_receipt_chain
from openzyme_host_api.aox_public_conductor_bundle import _read_bound_artifact_file
from openzyme_host_api.aox_public_conductor_bundle import _validate_control_slot_binding
from openzyme_host_api.aox_public_conductor_bundle import _validate_receipt_chain
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime.reliability import ControlledOperationOwnerPolicy


def _digest_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _slot() -> dict[str, object]:
    campaign_id = "aox_campaign_test"
    root_ref = f"formal-slots/{campaign_id}/1/fixture"
    policy = {
        "workflow_id": "aox_blank_world",
        "grantor_kind": "operator",
        "grantor_ref": "operator:aox-cutover",
        "allowed_scopes": ["formal"],
        "allowed_effect_classes": ["hpc", "provider"],
        "allowed_providers": ["aox-provider-routes@test"],
        "allowed_hpc_targets": ["aox-hpc-routes@test"],
        "max_attempts": 1,
        "max_micu": 100,
        "max_cost_microunits": 1000,
        "max_wall_time_seconds": 600,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "idempotency_key": f"{campaign_id}:authority:1",
    }
    return {
        "ordinal": 1,
        "attempt_kind": "positive",
        "session_id": "sess_aox",
        "root_ref": root_ref,
        "scope": "formal",
        "authority_policy": policy,
        "authority_policy_digest": canonical_digest(policy),
    }


def _control(slot: dict[str, object]) -> dict[str, object]:
    campaign_id = "aox_campaign_test"
    task_id = "task_agent_owned_execution"
    envelope_id, request_digest, request = authority_grant_identity(
        slot,
        campaign_id=campaign_id,
        task_id=task_id,
    )
    shared = {
        "session_id": slot["session_id"],
        "task_id": task_id,
        "campaign_id": campaign_id,
        "workflow_id": request["workflow_id"],
    }
    attempt_id = f"{slot['attempt_kind']}-aox"
    lane_id = f"lane-{slot['attempt_kind']}-aox"
    admission_key = f"agent-attempt-{slot['attempt_kind']}"
    actor_ref = "agent:executor"
    selection_id = "selection_aox"
    closure_request_id = "closure_request_aox"
    return {
        "attempt_authority": {
            **shared,
            "envelope_id": envelope_id,
            "root_ref": request["root_ref"],
            "idempotency_key": request["idempotency_key"],
            "request_digest": request_digest,
        },
        "admission_request": {
            **shared,
            "admission_request_id": "admission_request_aox",
            "envelope_id": envelope_id,
            "lane_id": lane_id,
            "scope": slot["scope"],
            "idempotency_key": admission_key,
            "actor_ref": actor_ref,
        },
        "attempt": {
            **shared,
            "attempt_id": attempt_id,
            "admission_request_id": "admission_request_aox",
            "envelope_id": envelope_id,
            "lane_id": lane_id,
            "root_ref": request["root_ref"],
            "scope": slot["scope"],
            "idempotency_key": admission_key,
            "created_by": actor_ref,
        },
        "selection": {
            "selection_id": selection_id,
            "attempt_id": attempt_id,
            "operation_universe_digest": "sha256:" + "b" * 64,
        },
        "operation_universe": {
            "occurrences": [
                {
                    "operation_id": "operation_failed",
                    "approval_id": None,
                }
            ]
        },
        "dispositions": [
            {
                "selection_id": selection_id,
                "operation_id": "operation_failed",
                "kind": "failed",
                "reason_code": "typed_failure",
                "replacement_operation_id": None,
            }
        ],
        "adoptions": [],
        "materializations": [],
        "closure_request": {
            "closure_request_id": closure_request_id,
            "attempt_id": attempt_id,
            "selection_id": selection_id,
        },
        "closure": {
            "closure_request_id": closure_request_id,
            "attempt_id": attempt_id,
            "selection_id": selection_id,
        },
    }


def _receipt(
    sequence: int,
    method: str,
    route: str,
    request: object,
    *,
    status_code: int = 200,
) -> dict[str, object]:
    return {
        "schema_id": PUBLIC_API_RECEIPT_SCHEMA_ID,
        "sequence": sequence,
        "method": method,
        "route": route,
        "status_code": status_code,
        "request": request,
        "request_digest": canonical_digest(request),
        "response_digest": canonical_digest({"raw": sequence}),
        "response_semantic_digest": canonical_digest({"semantic": sequence}),
    }


def _receipt_chain(
    slot: dict[str, object],
    control: dict[str, object],
    *,
    fault_artifact_id: str | None = None,
) -> list[dict[str, object]]:
    session_id = str(slot["session_id"])
    attempt_id = str(dict(control["attempt"])["attempt_id"])
    selection = dict(control["selection"])
    selection_id = str(selection["selection_id"])
    records = [
        _receipt(
            1,
            "POST",
            "/v3/sessions",
            {
                "session_id": session_id,
                "project_id": "aox-blank-world-cutover",
                "objective": PUBLIC_CONDUCTOR_OBJECTIVE,
                "title": PUBLIC_CONDUCTOR_TITLE,
            },
        ),
        _receipt(
            2,
            "POST",
            f"/v3/sessions/{session_id}/messages",
            {
                "message_digest": _digest_bytes(PUBLIC_CONDUCTOR_MESSAGE.encode()),
                "skill_keys": ["workflow:aox@1.0.0#sha256:" + "c" * 64],
                "task_id": None,
                "lane_id": None,
            },
        ),
        _receipt(
            3,
            "POST",
            f"/v3/sessions/{session_id}/runtime/drain",
            {
                "max_signals": 1,
                "max_steps_per_agent": 8,
                "auto_enqueue_ready_tasks": False,
            },
            status_code=202,
        ),
        _receipt(
            4,
            "GET",
            f"/v3/sessions/{session_id}/runtime/commands/runtime_command_aox",
            {},
        ),
        _receipt(
            5,
            "GET",
            f"/v3/sessions/{session_id}/workspace",
            {},
        ),
        _receipt(
            6,
            "POST",
            f"/v3/sessions/{session_id}/scientific-attempt-authorizations",
            authority_grant_payload(
                slot,
                campaign_id="aox_campaign_test",
                task_id=str(dict(control["attempt"])["task_id"]),
            ),
        ),
    ]
    if fault_artifact_id is not None:
        records.append(
            _receipt(
                len(records) + 1,
                "POST",
                f"/v3/sessions/{session_id}/aox-fault-injections/reference-byte-flip",
                {"attempt_id": attempt_id, "artifact_id": fault_artifact_id},
            )
        )
    records.extend(
        [
            _receipt(
                len(records) + 1,
                "GET",
                f"/v3/sessions/{session_id}/workspace",
                {},
            ),
            _receipt(
                len(records) + 2,
                "GET",
                f"/v3/sessions/{session_id}/events?replay=1&after_cursor=0",
                {"replay": True, "after_cursor": 0},
            ),
            _receipt(
                len(records) + 3,
                "GET",
                f"/v3/sessions/{session_id}/scientific-attempts/{attempt_id}/"
                f"selections/{selection_id}/evidence",
                {},
            ),
        ]
    )
    return records


def _terminal_handoffs(
    records: list[dict[str, object]],
    *,
    slot: dict[str, object],
    control: dict[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    session_id = str(slot["session_id"])
    command_id = "runtime_command_aox"
    status_url = f"/v3/sessions/{session_id}/runtime/commands/{command_id}"
    drain_receipt = next(
        item
        for item in records
        if item["method"] == "POST"
        and item["route"] == f"/v3/sessions/{session_id}/runtime/drain"
    )
    status_receipt = next(
        item
        for item in records
        if item["method"] == "GET" and item["route"] == status_url
    )
    workspace_receipt = next(
        item
        for item in records
        if item["method"] == "GET"
        and item["route"] == f"/v3/sessions/{session_id}/workspace"
    )
    responses = (
        (
            drain_receipt,
            {
                "schema_version": "runtime_command_status@1",
                "session_id": session_id,
                "command_id": command_id,
                "command_type": "runtime.drain",
                "status": "accepted",
                "status_url": status_url,
                "accepted_at": "2026-08-04T00:00:00+00:00",
                "started_at": None,
                "completed_at": None,
                "bounded_outcome_summary": None,
                "error_code": None,
                "safe_error_summary": None,
                "safe_retry_hint": None,
            },
        ),
        (
            status_receipt,
            {
                "schema_version": "runtime_command_status@1",
                "session_id": session_id,
                "command_id": command_id,
                "command_type": "runtime.drain",
                "status": "completed",
                "status_url": status_url,
                "accepted_at": "2026-08-04T00:00:00+00:00",
                "started_at": "2026-08-04T00:00:01+00:00",
                "completed_at": "2026-08-04T00:00:02+00:00",
                "bounded_outcome_summary": {},
                "error_code": None,
                "safe_error_summary": None,
                "safe_retry_hint": None,
            },
        ),
        (
            workspace_receipt,
            {
                "session": {"session_id": session_id},
                "task_board": {
                    "items": [
                        {
                            "task": {
                                "task_id": dict(control["attempt"])["task_id"],
                                "kind": "execution",
                            }
                        }
                    ]
                },
            },
        ),
    )
    envelopes: list[dict[str, object]] = []
    for receipt, response in responses:
        receipt["response_semantic_digest"] = canonical_digest(response)
        payload = {
            "schema_id": PUBLIC_RESPONSE_ENVELOPE_SCHEMA_ID,
            "receipt": receipt,
            "response": response,
            "response_semantic_digest": canonical_digest(response),
        }
        envelopes.append({**payload, "envelope_digest": canonical_digest(payload)})
    events = [
        {
            "cursor": 1,
            "session_id": session_id,
            "event_type": "runtime.command.finished",
            "command_id": command_id,
            "payload": {
                "command_id": command_id,
                "command_type": "runtime.drain",
                "status": "completed",
                "completed_at": "2026-08-04T00:00:02+00:00",
                "bounded_outcome_summary": {},
                "error_code": None,
                "safe_error_summary": None,
                "safe_retry_hint": None,
            },
        }
    ]
    return envelopes, events


def _validate_test_chain(
    records: list[dict[str, object]],
    *,
    slot: dict[str, object],
    control: dict[str, object],
) -> None:
    handoffs, events = _terminal_handoffs(records, slot=slot, control=control)
    _validate_receipt_chain(
        records,
        slot=slot,
        campaign_id="aox_campaign_test",
        identity={"workflow_ref": "workflow:aox@1.0.0#sha256:" + "c" * 64},
        control=control,
        handoff_envelopes=handoffs,
        events=events,
    )


def test_public_receipts_cover_only_conductor_owned_control_and_final_reads() -> None:
    slot = _slot()
    control = _control(slot)

    _validate_control_slot_binding(
        slot=slot,
        campaign_id="aox_campaign_test",
        control=control,
    )
    _validate_test_chain(_receipt_chain(slot, control), slot=slot, control=control)


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            lambda chain: chain[5]["request"].update({"task_id": "other"}),
            "public_conductor_command_chain_invalid",
        ),
        (
            lambda chain: chain.append(
                _receipt(
                    len(chain) + 1,
                    "POST",
                    "/v3/sessions/sess_aox/scientific-attempt-commands",
                    {"command": "scientific.selection.begin", "arguments": {}},
                ),
            ),
            "public_conductor_actor_boundary_invalid",
        ),
        (
            lambda chain: chain[-1].update({"sequence": 4}),
            "public_conductor_command_order_invalid",
        ),
    ],
)
def test_public_receipts_reject_source_mix_and_order_drift(
    mutation,
    expected_code: str,
) -> None:
    slot = _slot()
    control = _control(slot)
    chain = _receipt_chain(slot, control)
    mutation(chain)

    with pytest.raises(CutoverEvidenceError) as error:
        _validate_test_chain(chain, slot=slot, control=control)

    assert error.value.code == expected_code


def test_public_receipts_require_settled_status_after_each_bounded_drain() -> None:
    slot = _slot()
    control = _control(slot)
    chain = _receipt_chain(slot, control)
    chain[2], chain[3] = chain[3], chain[2]
    for sequence, receipt in enumerate(chain, start=1):
        receipt["sequence"] = sequence

    with pytest.raises(CutoverEvidenceError) as error:
        _validate_test_chain(chain, slot=slot, control=control)

    assert error.value.code == "public_terminal_handoff_invalid"


def test_public_terminal_handoff_requires_exact_finished_event_projection() -> None:
    slot = _slot()
    control = _control(slot)
    chain = _receipt_chain(slot, control)
    handoffs, events = _terminal_handoffs(chain, slot=slot, control=control)
    events[0]["payload"]["completed_at"] = "2026-08-04T00:00:03+00:00"

    with pytest.raises(CutoverEvidenceError) as error:
        _validate_receipt_chain(
            chain,
            slot=slot,
            campaign_id="aox_campaign_test",
            identity={"workflow_ref": "workflow:aox@1.0.0#sha256:" + "c" * 64},
            control=control,
            handoff_envelopes=handoffs,
            events=events,
        )

    assert error.value.code == "public_terminal_handoff_event_mismatch"


def test_public_terminal_handoff_rejects_unsealed_status_and_ambiguous_task() -> None:
    slot = _slot()
    control = _control(slot)
    chain = _receipt_chain(slot, control)
    handoffs, events = _terminal_handoffs(chain, slot=slot, control=control)

    with pytest.raises(CutoverEvidenceError) as missing_status:
        _validate_receipt_chain(
            chain,
            slot=slot,
            campaign_id="aox_campaign_test",
            identity={"workflow_ref": "workflow:aox@1.0.0#sha256:" + "c" * 64},
            control=control,
            handoff_envelopes=[handoffs[0], handoffs[2]],
            events=events,
        )
    assert missing_status.value.code == "public_terminal_handoff_invalid"

    task_board = handoffs[2]["response"]["task_board"]["items"]
    task_board.append(
        {"task": {"task_id": "second_execution_task", "kind": "execution"}}
    )
    handoffs[2]["receipt"]["response_semantic_digest"] = canonical_digest(
        handoffs[2]["response"]
    )
    handoffs[2]["response_semantic_digest"] = canonical_digest(
        handoffs[2]["response"]
    )
    handoffs[2]["envelope_digest"] = canonical_digest(
        {
            key: value
            for key, value in handoffs[2].items()
            if key != "envelope_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as ambiguous_task:
        _validate_receipt_chain(
            chain,
            slot=slot,
            campaign_id="aox_campaign_test",
            identity={"workflow_ref": "workflow:aox@1.0.0#sha256:" + "c" * 64},
            control=control,
            handoff_envelopes=handoffs,
            events=events,
        )
    assert ambiguous_task.value.code == "public_task_late_binding_invalid"


def test_public_receipt_loader_enforces_record_and_byte_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "bounded-receipts.jsonl"
    records = [
        _receipt(
            sequence,
            "GET",
            "/v3/runtime/health",
            {},
        )
        for sequence in range(1, 3)
    ]
    path.write_bytes(b"".join(canonical_json_bytes(item) + b"\n" for item in records))
    path.chmod(0o600)
    monkeypatch.setattr(conductor_bundle, "_MAX_RECEIPT_RECORDS", 1)

    with pytest.raises(CutoverEvidenceError) as record_error:
        _load_receipt_chain(path)
    assert record_error.value.code == "public_receipt_chain_too_large"

    monkeypatch.setattr(conductor_bundle, "_MAX_RECEIPT_CHAIN_BYTES", 1)
    with pytest.raises(CutoverEvidenceError) as byte_error:
        _load_receipt_chain(path)
    assert byte_error.value.code == "public_receipt_chain_invalid"


def test_public_receipts_bind_explicit_approved_decision() -> None:
    slot = _slot()
    control = _control(slot)
    control["operation_universe"]["occurrences"][0]["approval_id"] = "approval:aox"
    chain = _receipt_chain(slot, control)
    chain.insert(
        4,
        _receipt(
            0,
            "GET",
            f"/v3/sessions/{slot['session_id']}/pending-approvals",
            {},
        ),
    )
    chain.insert(
        6,
        _receipt(
            0,
            "POST",
            "/v3/approvals/approval:aox/resolve",
            {"decision": "approved"},
        ),
    )
    for sequence, receipt in enumerate(chain, start=1):
        receipt["sequence"] = sequence

    _validate_test_chain(chain, slot=slot, control=control)

    chain[6]["request"] = {"decision": "rejected"}
    with pytest.raises(CutoverEvidenceError) as error:
        _validate_test_chain(chain, slot=slot, control=control)
    assert error.value.code == "public_conductor_approval_chain_invalid"


def test_public_receipt_loader_rejects_failed_or_resealed_records(
    tmp_path: Path,
) -> None:
    receipt = _receipt(
        1,
        "POST",
        "/v3/sessions",
        {"project_id": "p", "objective": "o"},
        status_code=500,
    )
    path = tmp_path / "receipts.jsonl"
    path.write_bytes(canonical_json_bytes(receipt) + b"\n")
    path.chmod(0o600)

    with pytest.raises(CutoverEvidenceError) as error:
        _load_receipt_chain(path)

    assert error.value.code == "public_receipt_chain_invalid"
    records, _ = _load_receipt_chain(path, allow_failure_responses=True)
    assert records == [receipt]


def test_closed_control_rejects_authority_slot_mix() -> None:
    slot = _slot()
    control = _control(slot)
    control["attempt"]["task_id"] = "task_other"

    with pytest.raises(CutoverEvidenceError) as error:
        _validate_control_slot_binding(
            slot=slot,
            campaign_id="aox_campaign_test",
            control=control,
        )

    assert error.value.code == "public_conductor_control_slot_mismatch"


def _preflight_fixture(
    tmp_path: Path,
    *,
    slot: dict[str, object] | None = None,
) -> tuple[Path, dict[str, object], Path]:
    slot = _slot() if slot is None else slot
    launch_id = "formal-slot-" + "f" * 24
    attempt_root = tmp_path / launch_id
    roots_by_name = {
        name: attempt_root / directory
        for name, directory in (
            ("artifact", "artifacts"),
            ("blob", "blobs"),
            ("sandbox", "sandboxes"),
            ("hpc", "hpc-workspace"),
            ("evidence", "evidence"),
        )
    }
    attempt_root.mkdir(mode=0o700)
    for path in roots_by_name.values():
        path.mkdir(mode=0o700)
    effective_config = {"schema_id": "aox_blank_world_runtime_config@5"}
    identity = {
        "git_commit": "a" * 40,
        "config_digest": canonical_digest(effective_config),
        "workflow_ref": "workflow:aox@1.0.0#sha256:" + "c" * 64,
        "scoring_contract_digest": "sha256:" + "1" * 64,
        "scoring_implementation_digest": "sha256:" + "2" * 64,
        "image_digest": "sha256:" + "3" * 64,
        "sdk_digest": "sha256:" + "4" * 64,
    }
    identity_path = tmp_path / "identity.json"
    identity_path.write_bytes(canonical_json_bytes(identity) + b"\n")
    prerequisites = {
        "config_digest": canonical_digest(effective_config),
        "image_digest": identity["image_digest"],
        "sdk_digest": identity["sdk_digest"],
    }
    qualification = {"schema_id": "qualification@1"}
    settings = OpenZymeSettings.from_env()
    settings = replace(
        settings,
        reliability=replace(
            settings.reliability,
            controlled_operation_owner_policy=(
                ControlledOperationOwnerPolicy.ROUTE_ALLOWLIST_V1
            ),
        ),
    )
    launch_profile = build_aox_cutover_launch_profile(
        settings=settings,
        ledger_path=tmp_path / "micu-ledger.json",
        source_commit=str(identity["git_commit"]),
        config_digest=str(identity["config_digest"]),
        created_at="2026-07-31T00:00:00+00:00",
    )
    proof = {
        "schema_id": "aox_blank_world_root_proof@3",
        "launch_id": launch_id,
        "attempt_kind": slot["attempt_kind"],
        "root_identity": "sha256:" + "e" * 64,
        "root_names": {
            "artifact": "artifacts",
            "blob": "blobs",
            "sandbox": "sandboxes",
            "hpc": "hpc-workspace",
            "evidence": "evidence",
        },
        "initial_entries": {
            "sqlite": 0,
            "artifact": 0,
            "blob": 0,
            "sandbox": 0,
            "hpc": 0,
            "evidence": 0,
        },
        "sqlite_preexisting": False,
        "provider_cache_mode": "bypass",
        "evidence_cache_reuse": False,
        "hpc_workspace_label": "aox-cutover-test",
        "allowed_prerequisite_digest": canonical_digest(prerequisites),
        "allowed_prerequisites": prerequisites,
        "architecture_qualification": qualification,
    }
    roots = BlankWorldRoots(
        launch_id=launch_id,
        attempt_kind=str(slot["attempt_kind"]),
        attempt_root=attempt_root,
        sqlite_path=attempt_root / "control-plane.sqlite3",
        artifact_root=roots_by_name["artifact"],
        blob_root=roots_by_name["blob"],
        sandbox_root=roots_by_name["sandbox"],
        hpc_root=roots_by_name["hpc"],
        evidence_root=roots_by_name["evidence"],
        hpc_workspace_label="aox-hpc-positive-aox",
        proof=proof,
    )
    plan = {
        "campaign_id": "aox_campaign_test",
        "plan_digest": "sha256:" + "d" * 64,
        "launch_profile_digest": launch_profile["profile_digest"],
        "slots": [slot],
    }
    consumption = {"plan_digest": plan["plan_digest"], "status": "consumed"}
    claim_payload = {
        "schema_id": AOX_ATTEMPT_AUTHORITY_SLOT_CLAIM_SCHEMA_ID,
        "run_class": "formal_acceptance",
        "campaign_id": plan["campaign_id"],
        "plan_digest": plan["plan_digest"],
        "consumption_digest": canonical_digest(consumption),
        "ordinal": slot["ordinal"],
        "attempt_kind": slot["attempt_kind"],
        "launch_id": launch_id,
        "session_id": slot["session_id"],
        "root_ref": slot["root_ref"],
        "authority_policy_digest": slot["authority_policy_digest"],
        "campaign_root_identity": "sha256:" + "9" * 64,
        "claim_file": "authority.json.slot-1.claimed.json",
        "claimed_at": "2026-07-31T00:00:00+00:00",
    }
    slot_claim = {
        **claim_payload,
        "claim_digest": canonical_digest(claim_payload),
    }
    publish_attempt_slot_claim_evidence(slot_claim, roots=roots)
    publish_attempt_launch_profile(launch_profile, roots=roots)
    receipt = build_attempt_preflight_receipt(
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
        launch_profile=launch_profile,
        effective_config=effective_config,
        authority_plan=plan,
        authority_consumption=consumption,
        slot=slot,
        slot_claim=slot_claim,
        roots=roots,
    )
    path = publish_attempt_preflight_receipt(receipt, roots=roots)
    publish_conductor_execution_contract(path)
    return path, receipt, identity_path


def test_preflight_is_exact_and_single_start(tmp_path: Path) -> None:
    path, receipt, _ = _preflight_fixture(tmp_path)

    assert load_attempt_preflight_receipt(path, require_unstarted=True) == receipt
    (path.parent.parent / "control-plane.sqlite3").touch()
    with pytest.raises(CutoverEvidenceError) as error:
        load_attempt_preflight_receipt(path, require_unstarted=True)
    assert error.value.code == "attempt_preflight_already_started"


def _write_canonical(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _seal_response(
    path: Path,
    *,
    receipt: dict[str, object],
    response: object,
) -> None:
    payload = {
        "schema_id": PUBLIC_RESPONSE_ENVELOPE_SCHEMA_ID,
        "receipt": receipt,
        "response": response,
        "response_semantic_digest": canonical_digest(response),
    }
    _write_canonical(
        path,
        {**payload, "envelope_digest": canonical_digest(payload)},
    )


def _fault_slot() -> dict[str, object]:
    slot = deepcopy(_slot())
    slot.update(
        attempt_kind="fault",
        scope="fault",
    )
    policy = dict(slot["authority_policy"])
    policy["allowed_scopes"] = ["fault"]
    slot["authority_policy"] = policy
    slot["authority_policy_digest"] = canonical_digest(policy)
    return slot


def _startup_receipt(
    *,
    preflight: dict[str, object],
) -> dict[str, object]:
    slot = dict(preflight["slot"])
    timeout = dict(slot["authority_policy"])["max_wall_time_seconds"]
    prerequisites = dict(dict(preflight["root_proof"])["allowed_prerequisites"])
    identity_payload = {
        "configured_image_ref": "localhost/openzyme-pipeline-sandbox:dev",
        "immutable_image_ref": prerequisites["image_digest"],
        "image_digest": prerequisites["image_digest"],
        "pipeline_sdk_digest": prerequisites["sdk_digest"],
        "sandbox_protocol_version": "s10",
    }
    runtime_identity = {
        **identity_payload,
        "runtime_identity_digest": canonical_digest(identity_payload),
    }
    image_ref = (
        "localhost/openzyme-pipeline-sandbox@" + str(prerequisites["image_digest"])
    )
    registry_record = sandbox_image_record(
        image_ref=image_ref,
        image_digest=str(prerequisites["image_digest"]),
        now="2026-07-31T00:00:00+00:00",
    ).to_dict()
    bootstrap_payload = {
        "schema_id": HOST_SANDBOX_BOOTSTRAP_SCHEMA_ID,
        "preflight_receipt_digest": preflight["receipt_digest"],
        "runtime_identity": runtime_identity,
        "registry_projection": {
            key: registry_record[key]
            for key in (
                "image_ref",
                "image_digest",
                "sandbox_protocol_version",
                "manifest_schema_version",
                "compatibility",
            )
        },
    }
    bootstrap = {
        **bootstrap_payload,
        "receipt_digest": canonical_digest(bootstrap_payload),
    }
    payload = {
        "schema_id": HOST_STARTUP_SCHEMA_ID,
        "base_url": "http://127.0.0.1:41234",
        "launch_id": dict(preflight["slot_claim"])["launch_id"],
        "attempt_kind": slot["attempt_kind"],
        "session_id": slot["session_id"],
        "root_ref": slot["root_ref"],
        "authority_policy_digest": slot["authority_policy_digest"],
        "campaign_id": preflight["campaign_id"],
        "preflight_receipt_digest": preflight["receipt_digest"],
        "process_epoch": "epoch-aox",
        "child_pid": 1234,
        "child_pgid": 1234,
        "child_start_time_ticks": 5678,
        "timeout_seconds": timeout,
        "sandbox_bootstrap": bootstrap,
        "started_at": "2026-07-31T00:00:00+00:00",
    }
    return {**payload, "receipt_digest": canonical_digest(payload)}


def _bound_supervision_receipt(
    *,
    preflight: dict[str, object],
    startup: dict[str, object],
) -> dict[str, object]:
    slot = dict(preflight["slot"])
    receipt = _supervision_receipt()
    receipt.update(
        launch_id=dict(preflight["slot_claim"])["launch_id"],
        attempt_kind=slot["attempt_kind"],
        session_id=slot["session_id"],
        root_ref=slot["root_ref"],
        authority_policy_digest=slot["authority_policy_digest"],
        campaign_id=preflight["campaign_id"],
        preflight_receipt_digest=preflight["receipt_digest"],
        host_startup_receipt_digest=startup["receipt_digest"],
        process_epoch=startup["process_epoch"],
        timeout_seconds=startup["timeout_seconds"],
    )
    payload = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    receipt["receipt_digest"] = canonical_digest(payload)
    return receipt


def _formal_slot_failure_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    attempt_exists: bool = False,
    late_mutation: bool = False,
    typed_cause: bool = True,
) -> dict[str, object]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    preflight_path, preflight, identity_path = _preflight_fixture(tmp_path)
    evidence_root = preflight_path.parent
    slot = dict(preflight["slot"])
    startup = _startup_receipt(preflight=preflight)
    supervision = _bound_supervision_receipt(
        preflight=preflight,
        startup=startup,
    )
    _write_canonical(evidence_root / "aox-host-startup.json", startup)
    _write_canonical(evidence_root / "aox-host-supervision.json", supervision)

    session_id = str(slot["session_id"])
    command_id = "runtime_command_failed"
    status_url = f"/v3/sessions/{session_id}/runtime/commands/{command_id}"
    records = [
        _receipt(
            1,
            "POST",
            "/v3/sessions",
            {
                "session_id": session_id,
                "project_id": "aox-blank-world-cutover",
                "objective": PUBLIC_CONDUCTOR_OBJECTIVE,
                "title": PUBLIC_CONDUCTOR_TITLE,
            },
        ),
        _receipt(
            2,
            "POST",
            f"/v3/sessions/{session_id}/messages",
            {
                "message_digest": _digest_bytes(PUBLIC_CONDUCTOR_MESSAGE.encode()),
                "skill_keys": [
                    "workflow:aox@1.0.0#sha256:" + "c" * 64
                ],
                "task_id": None,
                "lane_id": None,
            },
        ),
        _receipt(
            3,
            "POST",
            f"/v3/sessions/{session_id}/runtime/drain",
            {
                "max_signals": 1,
                "max_steps_per_agent": 16,
                "auto_enqueue_ready_tasks": False,
            },
            status_code=202,
        ),
        _receipt(4, "GET", status_url, {}),
        _receipt(5, "GET", f"/v3/sessions/{session_id}/workspace", {}),
        _receipt(
            6,
            "GET",
            f"/v3/sessions/{session_id}/events?replay=1&after_cursor=0",
            {"replay": True, "after_cursor": 0},
        ),
    ]
    if late_mutation:
        records.append(
            _receipt(
                7,
                "POST",
                f"/v3/sessions/{session_id}/messages",
                {
                    "message_digest": _digest_bytes(b"late mutation"),
                    "skill_keys": [],
                    "task_id": None,
                    "lane_id": None,
                },
            )
        )
    admitted = {
        "schema_version": "runtime_command_status@1",
        "session_id": session_id,
        "command_id": command_id,
        "command_type": "runtime.drain",
        "status": "accepted",
        "status_url": status_url,
        "accepted_at": "2026-08-06T00:00:00+00:00",
        "started_at": None,
        "completed_at": None,
        "bounded_outcome_summary": None,
        "error_code": None,
        "safe_error_summary": None,
        "safe_retry_hint": None,
    }
    terminal = {
        "schema_version": "runtime_command_status@1",
        "session_id": session_id,
        "command_id": command_id,
        "command_type": "runtime.drain",
        "status": "failed",
        "status_url": status_url,
        "accepted_at": "2026-08-06T00:00:00+00:00",
        "started_at": "2026-08-06T00:00:01+00:00",
        "completed_at": "2026-08-06T00:00:02+00:00",
        "bounded_outcome_summary": {"scheduler_status": "failed"},
        "error_code": (
            "runtime_scheduler_batch_failed" if typed_cause else None
        ),
        "safe_error_summary": "The bounded runtime scheduler batch failed.",
        "safe_retry_hint": "Inspect current session facts.",
    }
    signal_id = "sig_failed_budget"
    failure_observation = {
        "schema_version": "failure_observation@1",
        "failure_id": "failure_budget",
        "session_id": session_id,
        "task_id": "task_execution",
        "agent_id": "agent:executor",
        "source_kind": "runtime_signal",
        "source_ref": signal_id,
        "source_version": "attempt:1",
        "error_code": "agent_turn_budget_exhausted",
        "effect_certainty": "no_effect",
        "recoverability": "agent_can_replan",
        "retry_eligibility": "terminal",
    }
    attempt_ids = ["attempt_existing"] if attempt_exists else []
    workspace = {
        "session": {"session_id": session_id},
        "scientific_attempts": {
            "attempt_count": len(attempt_ids),
            "attempts": [
                {"attempt_id": attempt_id} for attempt_id in attempt_ids
            ],
        },
        "failure_observations": [failure_observation] if typed_cause else [],
    }
    terminal_projection = {
        key: terminal.get(key)
        for key in (
            "command_id",
            "command_type",
            "status",
            "completed_at",
            "bounded_outcome_summary",
            "error_code",
            "safe_error_summary",
            "safe_retry_hint",
        )
    }
    cause_events = [
        {
            "cursor": 1,
            "session_id": session_id,
            "event_type": "agent.runtime_signal.updated",
            "payload": {
                "signal_id": signal_id,
                "status": "failed",
                "error_message": "agent_turn_budget_exhausted",
            },
        },
        {
            "cursor": 2,
            "session_id": session_id,
            "event_type": "runtime.budget_handoff_incomplete",
            "payload": {
                "signal_id": signal_id,
                "error_code": "budget_replan_identity_not_closed",
            },
        },
    ]
    events = [
        *(cause_events if typed_cause else []),
        {
            "cursor": 3,
            "session_id": session_id,
            "event_type": "runtime.command.finished",
            "command_id": command_id,
            "payload": terminal_projection,
        },
    ]
    responses = {
        "public-response-session-create.json": (
            records[0],
            {"session_id": session_id, "status": "created"},
        ),
        "public-response-entry-message.json": (
            records[1],
            {"session_id": session_id, "status": "accepted"},
        ),
        "public-response-drain-admission.json": (records[2], admitted),
        "public-response-drain-terminal.json": (records[3], terminal),
        "public-response-final-workspace.json": (records[4], workspace),
        "public-response-final-events.json": (records[5], events),
    }
    response_paths: dict[str, Path] = {}
    for name, (receipt, response) in responses.items():
        receipt["response_semantic_digest"] = canonical_digest(response)
        path = evidence_root / name
        _seal_response(path, receipt=receipt, response=response)
        response_paths[name] = path
    receipt_path = evidence_root / "public-api-receipts.jsonl"
    receipt_path.write_bytes(
        b"".join(canonical_json_bytes(record) + b"\n" for record in records)
    )
    ledger_before = evidence_root / "micu-before.json"
    ledger_after = evidence_root / "micu-after.json"
    _write_canonical(ledger_before, {"sequence": 1})
    _write_canonical(ledger_after, {"sequence": 2})
    for path in evidence_root.iterdir():
        if path.is_file():
            path.chmod(0o600)
    monkeypatch.setattr(
        formal_slot_failure,
        "_validate_ledger_transition",
        lambda *_: None,
    )
    return {
        "identity": identity_path,
        "preflight": preflight_path,
        "receipt_chain": receipt_path,
        "workspace": response_paths["public-response-final-workspace.json"],
        "events": response_paths["public-response-final-events.json"],
        "handoffs": [
            response_paths["public-response-drain-admission.json"],
            response_paths["public-response-drain-terminal.json"],
        ],
        "ledger_before": ledger_before,
        "ledger_after": ledger_after,
        "evidence_root": evidence_root,
    }


def test_conductor_retirement_readiness_closes_zero_attempt_public_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _formal_slot_failure_fixture(tmp_path, monkeypatch)
    supervision_path = sources["evidence_root"] / "aox-host-supervision.json"
    supervision_path.unlink()

    readiness_path, readiness = (
        aox_conductor_execution.seal_conductor_retirement_readiness(
            sources["preflight"]
        )
    )

    assert readiness["closure_mode"] == "slot_failure"
    assert readiness["scientific_attempt_count"] == 0
    assert readiness["final_workspace_response_name"] == sources["workspace"].name
    assert readiness["final_event_response_name"] == sources["events"].name
    assert readiness["handoff_response_names"] == [
        path.name for path in sources["handoffs"]
    ]
    assert readiness["evidence_response_name"] is None
    _write_canonical(
        supervision_path,
        _bound_supervision_receipt(
            preflight=json.loads(sources["preflight"].read_text()),
            startup=json.loads(
                (sources["evidence_root"] / "aox-host-startup.json").read_text()
            ),
        ),
    )
    supervision_path.chmod(0o600)
    loaded = aox_conductor_execution.load_conductor_retirement_readiness(
        readiness_path,
        preflight_path=sources["preflight"],
    )
    resolved = aox_conductor_execution.retirement_readiness_sources(
        readiness_path,
        preflight_path=sources["preflight"],
    )
    assert loaded == readiness
    assert resolved["receipt_chain"] == sources["receipt_chain"]
    assert resolved["workspace"] == sources["workspace"]
    assert resolved["events"] == sources["events"]


def test_public_response_name_is_prevalidated_before_host_action(
    tmp_path: Path,
) -> None:
    preflight_path, _, _ = _preflight_fixture(tmp_path)
    destination = aox_conductor_execution.public_response_path(
        preflight_path,
        "final-workspace",
    )
    destination.write_text("already consumed")

    with pytest.raises(CutoverEvidenceError) as error:
        aox_conductor_execution.public_response_path(
            preflight_path,
            "final-workspace",
        )

    assert error.value.code == "public_conductor_response_target_exists"


def test_conductor_retirement_readiness_rejects_missing_or_late_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = _formal_slot_failure_fixture(tmp_path / "missing", monkeypatch)
    (missing["evidence_root"] / "aox-host-supervision.json").unlink()
    (missing["evidence_root"] / "public-response-entry-message.json").unlink()
    with pytest.raises(CutoverEvidenceError) as missing_error:
        aox_conductor_execution.seal_conductor_retirement_readiness(
            missing["preflight"]
        )
    assert missing_error.value.code == "public_conductor_response_set_incomplete"

    drift = _formal_slot_failure_fixture(tmp_path / "drift", monkeypatch)
    (drift["evidence_root"] / "aox-host-supervision.json").unlink()
    readiness_path, _ = (
        aox_conductor_execution.seal_conductor_retirement_readiness(
            drift["preflight"]
        )
    )
    with drift["receipt_chain"].open("ab") as handle:
        handle.write(b"{}\n")
    with pytest.raises(CutoverEvidenceError) as drift_error:
        aox_conductor_execution.load_conductor_retirement_readiness(
            readiness_path,
            preflight_path=drift["preflight"],
        )
    assert drift_error.value.code in {
        "public_receipt_chain_invalid",
        "public_conductor_retirement_readiness_drift",
    }


def test_conductor_retirement_readiness_preserves_sealed_public_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _formal_slot_failure_fixture(tmp_path, monkeypatch)
    (sources["evidence_root"] / "aox-host-supervision.json").unlink()
    failure_response = {
        "error": {
            "code": "runtime_status_unavailable",
            "message": "safe public failure",
        }
    }
    failure_receipt = _receipt(
        7,
        "GET",
        "/v3/sessions/sess_aox/pending-approvals",
        {},
        status_code=503,
    )
    failure_receipt["response_semantic_digest"] = canonical_digest(
        failure_response
    )
    failure_path = (
        sources["evidence_root"] / "public-response-pending-failure.json"
    )
    _seal_response(
        failure_path,
        receipt=failure_receipt,
        response=failure_response,
    )
    with sources["receipt_chain"].open("ab") as handle:
        handle.write(canonical_json_bytes(failure_receipt) + b"\n")
    failure_path.chmod(0o600)

    _, readiness = aox_conductor_execution.seal_conductor_retirement_readiness(
        sources["preflight"]
    )

    assert readiness["closure_mode"] == "slot_failure"
    assert readiness["receipt_chain"]["record_count"] == 7
    assert readiness["sealed_responses"][-1]["name"] == failure_path.name
    supervision_path = sources["evidence_root"] / "aox-host-supervision.json"
    _write_canonical(
        supervision_path,
        _bound_supervision_receipt(
            preflight=json.loads(sources["preflight"].read_text()),
            startup=json.loads(
                (sources["evidence_root"] / "aox-host-startup.json").read_text()
            ),
        ),
    )
    supervision_path.chmod(0o600)
    sealed_path, _ = formal_slot_failure.finalize_and_seal_formal_slot_failure(
        identity_path=sources["identity"],
        preflight_path=sources["preflight"],
        receipt_chain_path=sources["receipt_chain"],
        workspace_response_path=sources["workspace"],
        event_response_path=sources["events"],
        handoff_response_paths=sources["handoffs"],
        ledger_before_path=sources["ledger_before"],
        ledger_after_path=sources["ledger_after"],
    )
    assert sealed_path.name == formal_slot_failure.FORMAL_SLOT_FAILURE_FILENAME


def test_formal_slot_failure_seals_without_fabricating_attempt_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _formal_slot_failure_fixture(tmp_path, monkeypatch)
    path, digest = formal_slot_failure.finalize_and_seal_formal_slot_failure(
        identity_path=sources["identity"],
        preflight_path=sources["preflight"],
        receipt_chain_path=sources["receipt_chain"],
        workspace_response_path=sources["workspace"],
        event_response_path=sources["events"],
        handoff_response_paths=sources["handoffs"],
        ledger_before_path=sources["ledger_before"],
        ledger_after_path=sources["ledger_after"],
        sealed_at="2026-08-06T00:01:00+00:00",
    )

    verification = formal_slot_failure.verify_formal_slot_failure(path)
    assert verification.passed is True
    assert verification.failure_digest == digest
    assert path.name == formal_slot_failure.FORMAL_SLOT_FAILURE_FILENAME
    assert not (path.parent / "attempt-bundle.json").exists()
    assert not (path.parent / ".formal-slot-failure-identity.verify.json").exists()
    decision = formal_slot_failure.evaluate_formal_slot_failure(
        path,
        decided_at="2026-08-06T00:02:00+00:00",
    )
    assert decision["decision"] == "NO-GO"
    assert decision["formal_slot_failure_digest"] == digest
    assert decision["attempt_digests"] == []
    assert decision["blocker"]["code"] == "budget_replan_identity_not_closed"
    decision_path = path.parent / "campaign-failure-decision.json"
    assert (
        formal_slot_failure.seal_formal_slot_failure_decision(
            decision,
            decision_path,
        )
        == decision["decision_digest"]
    )
    malformed_decision = deepcopy(decision)
    malformed_decision["decision"] = "GO"
    malformed_decision["decision_digest"] = canonical_digest(
        {
            key: value
            for key, value in malformed_decision.items()
            if key != "decision_digest"
        }
    )
    with pytest.raises(CutoverEvidenceError) as decision_error:
        formal_slot_failure.seal_formal_slot_failure_decision(
            malformed_decision,
            path.parent / "malformed-campaign-decision.json",
        )
    assert decision_error.value.code == (
        "formal_slot_failure_decision_semantics_invalid"
    )

    evidence_root = sources["evidence_root"]
    evidence_root.chmod(0o500)
    try:
        assert formal_slot_failure.verify_formal_slot_failure(path).passed is True
    finally:
        evidence_root.chmod(0o700)

    workspace_path = sources["workspace"]
    workspace_path.write_bytes(workspace_path.read_bytes() + b"\n")
    tampered = formal_slot_failure.verify_formal_slot_failure(path)
    assert tampered.passed is False
    assert tampered.issue is not None
    assert tampered.issue.code == "formal_slot_failure_source_digest_mismatch"


def test_formal_slot_failure_rejects_existing_attempt_and_symlink_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = _formal_slot_failure_fixture(
        tmp_path / "existing",
        monkeypatch,
        attempt_exists=True,
    )
    with pytest.raises(CutoverEvidenceError) as attempt_error:
        formal_slot_failure.finalize_and_seal_formal_slot_failure(
            identity_path=existing["identity"],
            preflight_path=existing["preflight"],
            receipt_chain_path=existing["receipt_chain"],
            workspace_response_path=existing["workspace"],
            event_response_path=existing["events"],
            handoff_response_paths=existing["handoffs"],
            ledger_before_path=existing["ledger_before"],
            ledger_after_path=existing["ledger_after"],
        )
    assert attempt_error.value.code == "formal_slot_failure_attempt_exists"

    clean = _formal_slot_failure_fixture(tmp_path / "symlink", monkeypatch)
    linked_workspace = clean["evidence_root"] / "workspace-linked.json"
    linked_workspace.symlink_to(clean["workspace"].name)
    with pytest.raises(CutoverEvidenceError) as symlink_error:
        formal_slot_failure.finalize_and_seal_formal_slot_failure(
            identity_path=clean["identity"],
            preflight_path=clean["preflight"],
            receipt_chain_path=clean["receipt_chain"],
            workspace_response_path=linked_workspace,
            event_response_path=clean["events"],
            handoff_response_paths=clean["handoffs"],
            ledger_before_path=clean["ledger_before"],
            ledger_after_path=clean["ledger_after"],
        )
    assert symlink_error.value.code == "formal_slot_failure_source_invalid"


def test_formal_slot_failure_rejects_an_inferred_missing_attempt_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _formal_slot_failure_fixture(
        tmp_path,
        monkeypatch,
        typed_cause=False,
    )

    with pytest.raises(CutoverEvidenceError) as error:
        formal_slot_failure.finalize_and_seal_formal_slot_failure(
            identity_path=sources["identity"],
            preflight_path=sources["preflight"],
            receipt_chain_path=sources["receipt_chain"],
            workspace_response_path=sources["workspace"],
            event_response_path=sources["events"],
            handoff_response_paths=sources["handoffs"],
            ledger_before_path=sources["ledger_before"],
            ledger_after_path=sources["ledger_after"],
        )

    assert error.value.code == "formal_slot_failure_cause_unproven"


def test_formal_slot_failure_requires_final_reads_after_public_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _formal_slot_failure_fixture(
        tmp_path,
        monkeypatch,
        late_mutation=True,
    )

    with pytest.raises(CutoverEvidenceError) as error:
        formal_slot_failure.finalize_and_seal_formal_slot_failure(
            identity_path=sources["identity"],
            preflight_path=sources["preflight"],
            receipt_chain_path=sources["receipt_chain"],
            workspace_response_path=sources["workspace"],
            event_response_path=sources["events"],
            handoff_response_paths=sources["handoffs"],
            ledger_before_path=sources["ledger_before"],
            ledger_after_path=sources["ledger_after"],
        )

    assert error.value.code == "formal_slot_failure_final_read_not_latest"


def test_fault_finalizer_seals_once_and_reverifies_from_exact_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slot = _fault_slot()
    preflight_path, preflight, identity_path = _preflight_fixture(
        tmp_path,
        slot=slot,
    )
    startup = _startup_receipt(preflight=preflight)
    supervision = _bound_supervision_receipt(
        preflight=preflight,
        startup=startup,
    )
    _write_canonical(preflight_path.parent / "aox-host-startup.json", startup)
    _write_canonical(
        preflight_path.parent / "aox-host-supervision.json",
        supervision,
    )

    control = _control(slot)
    workspace = {
        "session": {"session_id": slot["session_id"]},
        "task_board": {
            "items": [
                {
                    "task": {
                        "task_id": dict(control["attempt"])["task_id"],
                        "kind": "execution",
                        "status": "blocked",
                    }
                }
            ]
        },
        "reports": [],
        "report_drafts": [],
        "scientific_evidence": {
            "operations": [
                {
                    "operation_id": "operation_failed",
                    "status": "failed",
                    "state_version": 1,
                    "error_code": "sandbox_exec_nonzero",
                    "effect_certainty": "no_effect",
                    "retry_eligibility": "terminal",
                }
            ]
        },
    }
    selection_id = dict(control["selection"])["selection_id"]
    export_payload = {
        "schema_id": "aox_closed_attempt_evidence@2",
        "session_id": slot["session_id"],
        "attempt_id": dict(control["attempt"])["attempt_id"],
        "selection_id": selection_id,
        "scientific_attempt_control": control,
        "finalization_receipt": None,
        "deliverables": [],
        "product_closure": {
            "tasks": [],
            "final_answer": None,
            "fault_negative_state_closure": {
                "injection_receipt": {
                    "target_artifact_id": "artifact_aox_ref21",
                }
            },
        },
    }
    closed_export = {
        **export_payload,
        "export_digest": canonical_digest(export_payload),
    }
    receipts = _receipt_chain(
        slot,
        control,
        fault_artifact_id="artifact_aox_ref21",
    )
    handoffs, events = _terminal_handoffs(
        receipts,
        slot=slot,
        control=control,
    )
    events.append(
        {
            "cursor": 2,
            "session_id": slot["session_id"],
            "event_type": "scientific.operation.failed",
        }
    )
    for index, response in (
        (-3, workspace),
        (-2, events),
        (-1, closed_export),
    ):
        receipts[index]["response_semantic_digest"] = canonical_digest(response)
    receipt_path = preflight_path.parent / "public-api-receipts.jsonl"
    receipt_path.write_bytes(
        b"".join(canonical_json_bytes(item) + b"\n" for item in receipts)
    )
    receipt_path.chmod(0o600)
    workspace_path = preflight_path.parent / "workspace-response.json"
    events_path = preflight_path.parent / "events-response.json"
    evidence_path = preflight_path.parent / "evidence-response.json"
    _seal_response(workspace_path, receipt=receipts[-3], response=workspace)
    _seal_response(events_path, receipt=receipts[-2], response=events)
    _seal_response(evidence_path, receipt=receipts[-1], response=closed_export)
    handoff_paths: list[Path] = []
    for envelope in handoffs:
        sequence = int(dict(envelope["receipt"])["sequence"])
        path = preflight_path.parent / f"handoff-{sequence:04d}.json"
        _write_canonical(path, envelope)
        handoff_paths.append(path)
    ledger_before = preflight_path.parent / "micu-before.json"
    ledger_after = preflight_path.parent / "micu-after.json"
    _write_canonical(ledger_before, {"sequence": 1})
    _write_canonical(ledger_after, {"sequence": 2})

    monkeypatch.setattr(conductor_bundle, "_validate_control", lambda **_: None)
    monkeypatch.setattr(
        conductor_bundle,
        "_validate_closed_export",
        lambda *_, **__: (
            {},
            None,
            {
                "injection_id": "derived_required_artifact_blob_byte_flip@2",
                "error_code": "artifact_blob_digest_mismatch",
            },
            {"operations": [], "artifacts": [], "scientific_checks": {}},
        ),
    )
    monkeypatch.setattr(
        conductor_bundle,
        "_validate_ledger_transition",
        lambda *_: None,
    )
    bundle_path, bundle_digest = (
        conductor_bundle.finalize_and_seal_public_conductor_bundle(
            identity_path=identity_path,
            preflight_path=preflight_path,
            receipt_chain_path=receipt_path,
            workspace_response_path=workspace_path,
            event_response_path=events_path,
            evidence_response_path=evidence_path,
            handoff_response_paths=handoff_paths,
            ledger_before_path=ledger_before,
            ledger_after_path=ledger_after,
            sealed_at="2026-07-31T00:01:00+00:00",
        )
    )
    artifact_root = preflight_path.parent.parent / "artifacts"
    verification = conductor_bundle.verify_public_conductor_bundle(
        bundle_path,
        artifact_root=artifact_root,
    )
    generic_verification = cutover_evidence.verify_attempt_bundle(
        bundle_path,
        artifact_root=artifact_root,
    )

    assert verification.passed is True
    assert generic_verification == verification
    assert verification.bundle_digest == bundle_digest
    assert verification.attempt_kind == "fault"
    with pytest.raises(CutoverEvidenceError) as append_only_error:
        conductor_bundle.finalize_and_seal_public_conductor_bundle(
            identity_path=identity_path,
            preflight_path=preflight_path,
            receipt_chain_path=receipt_path,
            workspace_response_path=workspace_path,
            event_response_path=events_path,
            evidence_response_path=evidence_path,
            handoff_response_paths=handoff_paths,
            ledger_before_path=ledger_before,
            ledger_after_path=ledger_after,
        )
    assert append_only_error.value.code == "public_conductor_bundle_append_only"

    attestation = (
        artifact_root
        / "aox-public-conductor"
        / "attestations"
        / "identity.json"
    )
    attestation.chmod(0o600)
    attestation.write_bytes(b"{}\n")
    tampered = conductor_bundle.verify_public_conductor_bundle(
        bundle_path,
        artifact_root=artifact_root,
    )
    assert tampered.passed is False
    assert tampered.issues[0].code == (
        "public_conductor_attestation_digest_mismatch"
    )


def test_campaign_reducer_keeps_unproven_public_fault_contract_no_go(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[SimpleNamespace] = []
    payloads: list[dict[str, object]] = []
    ledger_states = ({"state": 0}, {"state": 1}, {"state": 2}, {"state": 3})
    for index, kind in enumerate(("positive", "positive", "fault")):
        attempt_id = f"{kind}-{index}"
        bundle_digest = "sha256:" + str(index + 1) * 64
        payload = {
            "bundle_profile": conductor_bundle.PUBLIC_CONDUCTOR_BUNDLE_PROFILE_ID,
            "identity": {"identity_digest": "sha256:" + "a" * 64},
            "clean_world": {"root_identity": "sha256:" + str(index + 4) * 64},
            "product_path": {
                "public_api_receipt_chain_digest": "sha256:"
                + str(index + 7) * 64
            },
            "authority": {
                "campaign_id": "aox_campaign_test",
                "plan_digest": "sha256:" + "f" * 64,
                "slot_claim_digest": "sha256:" + str(index + 4) * 64,
                "slot": {
                    "ordinal": index + 1,
                    "session_id": f"session-{index}",
                    "root_ref": f"formal-slots/aox_campaign_test/{index + 1}/root",
                    "authority_policy_digest": "sha256:"
                    + str(index + 4) * 64,
                },
            },
            "scientific_attempt_control": {
                "attempt_authority": {"envelope_id": f"envelope-{index}"},
                "attempt": {
                    "attempt_id": attempt_id,
                    "lane_id": f"lane-{index}",
                    "task_id": f"task-{index}",
                },
                "admission_request": {
                    "admission_request_id": f"admission-{index}",
                    "idempotency_key": f"agent-key-{index}",
                },
                "selection": {"selection_id": f"selection-{index}"},
            },
            "micu_ledger": {
                "before": ledger_states[index],
                "after": ledger_states[index + 1],
            },
            "scientific_outcome": {
                "cutover_eligible": kind == "positive",
                "status": "passed" if kind == "positive" else "controlled_failure",
            },
            "report": {
                "status": "published" if kind == "positive" else "withheld",
                "report_id": f"report-{index}" if kind == "positive" else None,
                "primary_artifact_id": (
                    f"pubmed-{index}" if kind == "positive" else None
                ),
            },
            "tasks": [
                {"status": "completed" if kind == "positive" else "blocked"}
                for _ in range(3)
            ],
            "final_answer": (
                {"message_id": f"message-{index}"} if kind == "positive" else None
            ),
            "deliverables": [{} for _ in range(17)] if kind == "positive" else [],
            "fault_injection": (
                None
                if kind == "positive"
                else {
                    "operation_id": "operation_failed",
                    "error_code": "sandbox_exec_nonzero",
                    "negative_state_closure": {
                        "schema_id": "aox_fault_negative_state_closure@1",
                        "successful_alternate_consumer_ids": [],
                        "post_fault_final_deliverable_paths": [],
                        "complete_final_deliverable_set_present": False,
                    },
                }
            ),
        }
        payloads.append(payload)
        bundle_path = tmp_path / f"bundle-{index}.json"
        _write_canonical(
            bundle_path,
            {"payload": payload, "bundle_digest": bundle_digest},
        )
        verification = conductor_bundle.VerificationResult(
            passed=True,
            bundle_digest=bundle_digest,
            attempt_id=attempt_id,
            attempt_kind=kind,
            issues=(),
        )
        records.append(
            SimpleNamespace(
                bundle_path=bundle_path,
                artifact_root=tmp_path,
                attempt_id=attempt_id,
                attempt_kind=kind,
                bundle_digest=bundle_digest,
                verification=verification,
            )
        )
    by_path = {
        record.bundle_path: record.verification for record in records
    }
    monkeypatch.setattr(
        conductor_bundle,
        "verify_public_conductor_bundle",
        lambda path, *, artifact_root: by_path[path],
    )

    decision = cutover_evidence.evaluate_campaign(
        records,
        decided_at="2026-07-31T00:02:00+00:00",
    )

    assert decision["decision"] == "NO-GO"
    assert decision["blocker"]["code"] == "fault_contract_unproven"

    payloads[1]["authority"]["plan_digest"] = "sha256:" + "e" * 64
    _write_canonical(
        records[1].bundle_path,
        {"payload": payloads[1], "bundle_digest": records[1].bundle_digest},
    )
    plan_drift = conductor_bundle.evaluate_public_conductor_campaign(
        records,
        decided_at="2026-07-31T00:02:01+00:00",
    )
    assert plan_drift["blocker"]["code"] == "campaign_authority_plan_drift"

    payloads[1]["authority"]["plan_digest"] = "sha256:" + "f" * 64
    payloads[1]["authority"]["slot_claim_digest"] = payloads[0]["authority"][
        "slot_claim_digest"
    ]
    _write_canonical(
        records[1].bundle_path,
        {"payload": payloads[1], "bundle_digest": records[1].bundle_digest},
    )
    claim_collision = conductor_bundle.evaluate_public_conductor_campaign(
        records,
        decided_at="2026-07-31T00:02:02+00:00",
    )
    assert claim_collision["blocker"]["code"] == "campaign_slot_claim_collision"

    payloads[1]["authority"]["slot_claim_digest"] = "sha256:" + "5" * 64
    payloads[1]["authority"]["slot"]["root_ref"] = payloads[0]["authority"][
        "slot"
    ]["root_ref"]
    _write_canonical(
        records[1].bundle_path,
        {"payload": payloads[1], "bundle_digest": records[1].bundle_digest},
    )
    identity_collision = conductor_bundle.evaluate_public_conductor_campaign(
        records,
        decided_at="2026-07-31T00:02:03+00:00",
    )
    assert identity_collision["blocker"]["code"] == ("campaign_slot_identity_collision")


def test_artifact_reader_rejects_intermediate_symlink(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    real = artifact_root / "real"
    real.mkdir(parents=True)
    (real / "source.json").write_text("{}\n")
    (artifact_root / "linked").symlink_to(real, target_is_directory=True)

    with pytest.raises(CutoverEvidenceError) as error:
        _read_bound_artifact_file(
            artifact_root,
            "linked/source.json",
            identity="source",
        )

    assert error.value.code == "public_conductor_artifact_path_invalid"


def _supervision_receipt() -> dict[str, object]:
    payload = {
        "schema_id": HOST_SUPERVISION_RECEIPT_SCHEMA_ID,
        "mode": "policy_free_public_host",
        "launch_id": "formal-slot-" + "f" * 24,
        "attempt_kind": "positive",
        "session_id": "sess_aox",
        "root_ref": "formal-slots/aox_campaign_test/1/fixture",
        "authority_policy_digest": "sha256:" + "a" * 64,
        "campaign_id": "aox_campaign_test",
        "preflight_receipt_digest": "sha256:" + "b" * 64,
        "host_startup_receipt_digest": "sha256:" + "c" * 64,
        "process_epoch": "epoch-aox",
        "shutdown_reason": "operator_stop",
        "child_exit_code": 0,
        "local_state_settled": True,
        "descendant_retirement_proven": True,
        "parent_snapshot_revalidated": True,
        "mutation_authority_schema_id": MUTATION_LOCAL_SETTLEMENT_SCHEMA_ID,
        "mutation_authority_snapshot_digest": "sha256:" + "d" * 64,
        "mutation_authority_observed_row_count": 0,
        "nonterminal_mutation_scope_count": 0,
        "active_mutation_writer_count": 0,
        "sqlite_checkpoint": "passed",
        "sqlite_integrity": "passed",
        "declared_root_sync": True,
        "terminal_frame_digest": "sha256:" + "e" * 64,
        "timeout_seconds": 600.0,
        "startup_timeout_seconds": 60.0,
        "term_grace_seconds": 15.0,
        "kill_grace_seconds": 10.0,
        "supervisor_contract_digest": host_supervision_contract_digest(
            timeout_seconds=600.0,
            startup_timeout_seconds=60.0,
            term_grace_seconds=15.0,
            kill_grace_seconds=10.0,
        ),
        "retired_at": "2026-07-31T00:00:00+00:00",
    }
    return {**payload, "receipt_digest": canonical_digest(payload)}


def test_policy_free_supervision_receipt_accepts_campaign_id_and_rejects_writers() -> None:
    receipt = _supervision_receipt()

    assert validate_supervised_host_receipt(
        receipt,
        launch_id="formal-slot-" + "f" * 24,
        attempt_kind="positive",
        session_id="sess_aox",
        root_ref="formal-slots/aox_campaign_test/1/fixture",
        campaign_id="aox_campaign_test",
        authority_policy_digest="sha256:" + "a" * 64,
    ) == receipt

    tampered = deepcopy(receipt)
    tampered["active_mutation_writer_count"] = 1
    payload = {key: value for key, value in tampered.items() if key != "receipt_digest"}
    tampered["receipt_digest"] = canonical_digest(payload)
    with pytest.raises(CutoverEvidenceError) as error:
        validate_supervised_host_receipt(
            tampered,
            launch_id="formal-slot-" + "f" * 24,
            attempt_kind="positive",
            session_id="sess_aox",
            root_ref="formal-slots/aox_campaign_test/1/fixture",
            campaign_id="aox_campaign_test",
            authority_policy_digest="sha256:" + "a" * 64,
        )
    assert error.value.code == "host_supervision_receipt_invalid"
