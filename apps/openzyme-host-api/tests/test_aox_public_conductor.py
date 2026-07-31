from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from openzyme_core import MUTATION_LOCAL_SETTLEMENT_SCHEMA_ID
from openzyme_host_api import aox_public_conductor_bundle as conductor_bundle
from openzyme_host_api.aox_attempt_authority import attempt_admission_arguments
from openzyme_host_api.aox_attempt_authority import authority_grant_payload
from openzyme_host_api.aox_attempt_preflight import build_attempt_preflight_receipt
from openzyme_host_api.aox_attempt_preflight import load_attempt_preflight_receipt
from openzyme_host_api.aox_attempt_preflight import publish_attempt_preflight_receipt
from openzyme_host_api.aox_cutover_evidence import BlankWorldRoots
from openzyme_host_api.aox_cutover_evidence import CutoverEvidenceError
from openzyme_host_api.aox_cutover_evidence import canonical_digest
from openzyme_host_api.aox_cutover_evidence import canonical_json_bytes
from openzyme_host_api.aox_host_supervision import HOST_SUPERVISION_RECEIPT_SCHEMA_ID
from openzyme_host_api.aox_host_supervision import host_supervision_contract_digest
from openzyme_host_api.aox_host_supervision import validate_supervised_host_receipt
from openzyme_host_api.aox_public_conductor_bundle import PUBLIC_API_RECEIPT_SCHEMA_ID
from openzyme_host_api.aox_public_conductor_bundle import PUBLIC_CONDUCTOR_MESSAGE
from openzyme_host_api.aox_public_conductor_bundle import PUBLIC_CONDUCTOR_OBJECTIVE
from openzyme_host_api.aox_public_conductor_bundle import PUBLIC_CONDUCTOR_TITLE
from openzyme_host_api.aox_public_conductor_bundle import PUBLIC_RESPONSE_ENVELOPE_SCHEMA_ID
from openzyme_host_api.aox_public_conductor_bundle import _load_receipt_chain
from openzyme_host_api.aox_public_conductor_bundle import _read_bound_artifact_file
from openzyme_host_api.aox_public_conductor_bundle import _validate_control_slot_binding
from openzyme_host_api.aox_public_conductor_bundle import _validate_receipt_chain


def _digest_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _slot() -> dict[str, object]:
    campaign_id = "aox_campaign_test"
    request = {
        "command": "scientific.attempt.authorize",
        "session_id": "sess_aox",
        "task_id": "task_aox",
        "campaign_id": campaign_id,
        "workflow_id": "aox_blank_world",
        "root_ref": "attempts/positive-aox",
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
        "attempt_id": "positive-aox",
        "session_id": "sess_aox",
        "task_id": "task_aox",
        "lane_id": "lane_aox",
        "scope": "formal",
        "authority_request": request,
        "envelope_id": "attempt_authority_aox",
        "request_digest": "sha256:" + "a" * 64,
    }


def _control(slot: dict[str, object]) -> dict[str, object]:
    request = dict(slot["authority_request"])
    shared = {
        "session_id": slot["session_id"],
        "task_id": slot["task_id"],
        "campaign_id": request["campaign_id"],
        "workflow_id": request["workflow_id"],
    }
    admission_key = f"{request['campaign_id']}:attempt:{slot['ordinal']}"
    selection_id = "selection_aox"
    closure_request_id = "closure_request_aox"
    return {
        "attempt_authority": {
            **shared,
            "envelope_id": slot["envelope_id"],
            "root_ref": request["root_ref"],
            "idempotency_key": request["idempotency_key"],
        },
        "admission_request": {
            **shared,
            "admission_request_id": "admission_request_aox",
            "envelope_id": slot["envelope_id"],
            "lane_id": slot["lane_id"],
            "scope": slot["scope"],
            "idempotency_key": admission_key,
        },
        "attempt": {
            **shared,
            "attempt_id": slot["attempt_id"],
            "admission_request_id": "admission_request_aox",
            "envelope_id": slot["envelope_id"],
            "lane_id": slot["lane_id"],
            "scope": slot["scope"],
            "idempotency_key": admission_key,
        },
        "selection": {
            "selection_id": selection_id,
            "attempt_id": slot["attempt_id"],
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
            "attempt_id": slot["attempt_id"],
            "selection_id": selection_id,
        },
        "closure": {
            "closure_request_id": closure_request_id,
            "attempt_id": slot["attempt_id"],
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
) -> list[dict[str, object]]:
    session_id = str(slot["session_id"])
    attempt_id = str(slot["attempt_id"])
    selection = dict(control["selection"])
    selection_id = str(selection["selection_id"])
    command_route = f"/v3/sessions/{session_id}/scientific-attempt-commands"
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
            f"/v3/sessions/{session_id}/scientific-attempt-authorizations",
            authority_grant_payload(slot),
        ),
        _receipt(
            4,
            "POST",
            command_route,
            {
                "command": "attempt.create",
                "arguments": attempt_admission_arguments(slot),
            },
        ),
        _receipt(
            5,
            "POST",
            f"/v3/sessions/{session_id}/scientific-attempt-admissions/finalize",
            {"admission_request_id": "admission_request_aox"},
        ),
        _receipt(
            6,
            "POST",
            command_route,
            {
                "command": "scientific.selection.begin",
                "arguments": {"attempt_id": attempt_id},
            },
        ),
        _receipt(
            7,
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
            8,
            "GET",
            f"/v3/sessions/{session_id}/runtime/commands/runtime_command_aox",
            {},
        ),
        _receipt(
            9,
            "POST",
            command_route,
            {
                "command": "scientific.operation.disposition",
                "arguments": {
                    "selection_id": selection_id,
                    "operation_id": "operation_failed",
                    "kind": "failed",
                    "reason_code": "typed_failure",
                    "replacement_operation_id": None,
                },
            },
        ),
        _receipt(
            10,
            "POST",
            command_route,
            {
                "command": "scientific.selection.seal",
                "arguments": {
                    "selection_id": selection_id,
                    "expected_universe_digest": selection[
                        "operation_universe_digest"
                    ],
                },
            },
        ),
        _receipt(
            11,
            "POST",
            command_route,
            {
                "command": "scientific.attempt.close",
                "arguments": {
                    "attempt_id": attempt_id,
                    "selection_id": selection_id,
                },
            },
        ),
        _receipt(
            12,
            "POST",
            f"/v3/sessions/{session_id}/scientific-attempt-closures/finalize",
            {"closure_request_id": "closure_request_aox"},
        ),
        _receipt(13, "GET", f"/v3/sessions/{session_id}/workspace", {}),
        _receipt(
            14,
            "GET",
            f"/v3/sessions/{session_id}/events?replay=1&after_cursor=0",
            {"replay": True, "after_cursor": 0},
        ),
        _receipt(
            15,
            "GET",
            f"/v3/sessions/{session_id}/scientific-attempts/{attempt_id}/"
            f"selections/{selection_id}/evidence",
            {},
        ),
    ]
    return records


def test_public_receipts_reproduce_exact_authority_and_selected_chain() -> None:
    slot = _slot()
    control = _control(slot)

    _validate_control_slot_binding(slot=slot, control=control)
    _validate_receipt_chain(
        _receipt_chain(slot, control),
        slot=slot,
        identity={"workflow_ref": "workflow:aox@1.0.0#sha256:" + "c" * 64},
        control=control,
    )


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            lambda chain: chain[4]["request"].update(
                {"admission_request_id": "other"}
            ),
            "public_conductor_command_chain_invalid",
        ),
        (
            lambda chain: chain[8]["request"]["arguments"].update(
                {"selection_id": "other"}
            ),
            "public_conductor_selected_chain_request_invalid",
        ),
        (
            lambda chain: chain.insert(
                12,
                chain.pop(12),
            ),
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
    if expected_code == "public_conductor_command_order_invalid":
        chain[12]["sequence"] = 10
    else:
        mutation(chain)

    with pytest.raises(CutoverEvidenceError) as error:
        _validate_receipt_chain(
            chain,
            slot=slot,
            identity={"workflow_ref": "workflow:aox@1.0.0#sha256:" + "c" * 64},
            control=control,
        )

    assert error.value.code == expected_code


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

    with pytest.raises(CutoverEvidenceError) as error:
        _load_receipt_chain(path)

    assert error.value.code == "public_receipt_chain_invalid"


def test_closed_control_rejects_authority_slot_mix() -> None:
    slot = _slot()
    control = _control(slot)
    control["attempt"]["task_id"] = "task_other"

    with pytest.raises(CutoverEvidenceError) as error:
        _validate_control_slot_binding(slot=slot, control=control)

    assert error.value.code == "public_conductor_control_slot_mismatch"


def _preflight_fixture(
    tmp_path: Path,
    *,
    slot: dict[str, object] | None = None,
) -> tuple[Path, dict[str, object], Path]:
    slot = _slot() if slot is None else slot
    attempt_root = tmp_path / str(slot["attempt_id"])
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
    effective_config = {
        "schema_id": "aox_blank_world_runtime_config@4",
        "conductor": {"orchestration_owner": "codex_tester"},
    }
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
    prerequisites = {"config_digest": canonical_digest(effective_config)}
    qualification = {"schema_id": "qualification@1"}
    proof = {
        "schema_id": "aox_blank_world_root_proof@2",
        "attempt_id": slot["attempt_id"],
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
        attempt_id=str(slot["attempt_id"]),
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
        "campaign_id": dict(slot["authority_request"])["campaign_id"],
        "plan_digest": "sha256:" + "d" * 64,
        "slots": [slot],
    }
    consumption = {"plan_digest": plan["plan_digest"], "status": "consumed"}
    receipt = build_attempt_preflight_receipt(
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
        effective_config=effective_config,
        authority_plan=plan,
        authority_consumption=consumption,
        slot=slot,
        roots=roots,
    )
    path = publish_attempt_preflight_receipt(receipt, roots=roots)
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
        attempt_id="fault-aox",
        scope="fault",
    )
    request = dict(slot["authority_request"])
    request["root_ref"] = "attempts/fault-aox"
    request["allowed_scopes"] = ["fault"]
    slot["authority_request"] = request
    return slot


def _startup_receipt(
    *,
    preflight: dict[str, object],
) -> dict[str, object]:
    slot = dict(preflight["slot"])
    timeout = dict(slot["authority_request"])["max_wall_time_seconds"]
    payload = {
        "schema_id": "aox_supervised_host_startup@1",
        "base_url": "http://127.0.0.1:41234",
        "attempt_id": slot["attempt_id"],
        "attempt_kind": slot["attempt_kind"],
        "session_id": slot["session_id"],
        "task_id": slot["task_id"],
        "lane_id": slot["lane_id"],
        "attempt_authority_id": slot["envelope_id"],
        "attempt_authority_request_digest": slot["request_digest"],
        "campaign_id": preflight["campaign_id"],
        "preflight_receipt_digest": preflight["receipt_digest"],
        "process_epoch": "epoch-aox",
        "child_pid": 1234,
        "child_pgid": 1234,
        "child_start_time_ticks": 5678,
        "timeout_seconds": timeout,
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
        attempt_id=slot["attempt_id"],
        attempt_kind=slot["attempt_kind"],
        session_id=slot["session_id"],
        task_id=slot["task_id"],
        lane_id=slot["lane_id"],
        attempt_authority_id=slot["envelope_id"],
        attempt_authority_request_digest=slot["request_digest"],
        campaign_id=preflight["campaign_id"],
        preflight_receipt_digest=preflight["receipt_digest"],
        host_startup_receipt_digest=startup["receipt_digest"],
        process_epoch=startup["process_epoch"],
        timeout_seconds=startup["timeout_seconds"],
    )
    payload = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    receipt["receipt_digest"] = canonical_digest(payload)
    return receipt


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
                        "task_id": slot["task_id"],
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
    events = [
        {
            "cursor": 1,
            "session_id": slot["session_id"],
            "event_type": "scientific.operation.failed",
        }
    ]
    selection_id = dict(control["selection"])["selection_id"]
    export_payload = {
        "schema_id": "aox_closed_attempt_evidence@1",
        "session_id": slot["session_id"],
        "attempt_id": slot["attempt_id"],
        "selection_id": selection_id,
        "scientific_attempt_control": control,
        "finalization_receipt": None,
        "deliverables": [],
    }
    closed_export = {
        **export_payload,
        "export_digest": canonical_digest(export_payload),
    }
    receipts = _receipt_chain(slot, control)
    for index, response in ((12, workspace), (13, events), (14, closed_export)):
        receipts[index]["response_semantic_digest"] = canonical_digest(response)
    receipt_path = preflight_path.parent / "public-api-receipts.jsonl"
    receipt_path.write_bytes(
        b"".join(canonical_json_bytes(item) + b"\n" for item in receipts)
    )
    workspace_path = preflight_path.parent / "workspace-response.json"
    events_path = preflight_path.parent / "events-response.json"
    evidence_path = preflight_path.parent / "evidence-response.json"
    _seal_response(workspace_path, receipt=receipts[12], response=workspace)
    _seal_response(events_path, receipt=receipts[13], response=events)
    _seal_response(evidence_path, receipt=receipts[14], response=closed_export)
    ledger_before = preflight_path.parent / "micu-before.json"
    ledger_after = preflight_path.parent / "micu-after.json"
    _write_canonical(ledger_before, {"sequence": 1})
    _write_canonical(ledger_after, {"sequence": 2})

    monkeypatch.setattr(conductor_bundle, "_validate_control", lambda **_: None)
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

    assert verification.passed is True
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
    ledger_states = ({"state": 0}, {"state": 1}, {"state": 2}, {"state": 3})
    for index, kind in enumerate(("positive", "positive", "fault")):
        attempt_id = f"{kind}-{index}"
        bundle_digest = "sha256:" + str(index + 1) * 64
        payload = {
            "identity": {"identity_digest": "sha256:" + "a" * 64},
            "clean_world": {"root_identity": "sha256:" + str(index + 4) * 64},
            "product_path": {
                "public_api_receipt_chain_digest": "sha256:"
                + str(index + 7) * 64
            },
            "micu_ledger": {
                "before": ledger_states[index],
                "after": ledger_states[index + 1],
            },
            "scientific_outcome": {
                "cutover_eligible": kind == "positive",
                "status": "passed" if kind == "positive" else "controlled_failure",
            },
            "report": {"status": "published" if kind == "positive" else "withheld"},
            "deliverables": [{} for _ in range(17)] if kind == "positive" else [],
            "fault_injection": (
                None
                if kind == "positive"
                else {
                    "operation_id": "operation_failed",
                    "error_code": "sandbox_exec_nonzero",
                }
            ),
        }
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

    decision = conductor_bundle.evaluate_public_conductor_campaign(
        records,
        decided_at="2026-07-31T00:02:00+00:00",
    )

    assert decision["decision"] == "NO-GO"
    assert decision["blocker"]["code"] == "fault_contract_unproven"


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
        "attempt_id": "positive-aox",
        "attempt_kind": "positive",
        "session_id": "sess_aox",
        "task_id": "task_aox",
        "lane_id": "lane_aox",
        "attempt_authority_id": "attempt_authority_aox",
        "attempt_authority_request_digest": "sha256:" + "a" * 64,
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
        attempt_id="positive-aox",
        attempt_kind="positive",
        attempt_authority_id="attempt_authority_aox",
        attempt_authority_request_digest="sha256:" + "a" * 64,
    ) == receipt

    tampered = deepcopy(receipt)
    tampered["active_mutation_writer_count"] = 1
    payload = {key: value for key, value in tampered.items() if key != "receipt_digest"}
    tampered["receipt_digest"] = canonical_digest(payload)
    with pytest.raises(CutoverEvidenceError) as error:
        validate_supervised_host_receipt(
            tampered,
            attempt_id="positive-aox",
            attempt_kind="positive",
            attempt_authority_id="attempt_authority_aox",
            attempt_authority_request_digest="sha256:" + "a" * 64,
        )
    assert error.value.code == "host_supervision_receipt_invalid"
