from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from types import SimpleNamespace
from typing import Any

from openzyme_pipeline import aox_finalization

from .aox_attempt_authority import attempt_admission_arguments, authority_grant_payload
from .aox_attempt_preflight import load_attempt_preflight_receipt
from .aox_bundle_finalizer import (
    AoxBundleFinalizationError,
    _calculation_receipts,
    _verify_calculation_receipts,
)
from .aox_cutover_evidence import (
    ATTEMPT_BUNDLE_SCHEMA_ID_V3,
    CAMPAIGN_DECISION_SCHEMA_ID,
    FAULT_ARTIFACT_BYTE_FLIP_ID,
    CutoverEvidenceError,
    VerificationIssue,
    VerificationResult,
    _normalize_identity,
    _strict_json_loads,
    _validate_ledger_transition,
    _write_append_only_bytes,
    canonical_digest,
    canonical_json_bytes,
)
from .aox_final_deliverable_validation import (
    S15_AOX_HMM_FIXED_DELIVERABLES,
    validate_aox_final_artifacts,
)
from .aox_host_supervision import (
    HOST_STARTUP_FILENAME,
    HOST_STARTUP_SCHEMA_ID,
    HOST_SUPERVISION_FILENAME,
    validate_supervised_host_receipt,
)
from .aox_selected_chain_evidence import _verify_selected_chain_control


PUBLIC_CONDUCTOR_BUNDLE_PROFILE_ID = "aox_public_conductor_bundle@1"
PUBLIC_API_RECEIPT_SCHEMA_ID = "openzyme_public_api_receipt@2"
PUBLIC_RESPONSE_ENVELOPE_SCHEMA_ID = "openzyme_public_host_response@1"
PUBLIC_CONDUCTOR_ATTESTATION_DIR = "aox-public-conductor"
PUBLIC_CONDUCTOR_BUNDLE_FILENAME = "attempt-bundle.json"
PUBLIC_CONDUCTOR_OBJECTIVE = (
    "Run the canonical blank-world AOX/HMM product path and publish "
    "a source-linked scientific report."
)
PUBLIC_CONDUCTOR_TITLE = "AOX blank-world formal"
PUBLIC_CONDUCTOR_MESSAGE = (
    "Execute the pinned AOX/HMM workflow under the exact scientific-attempt "
    "authority. Use only public Host tools, resolve approvals explicitly, "
    "close the selected chain, and publish the source-linked report."
)

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_ANY = object()
_RECEIPT_FIELDS = {
    "schema_id", "sequence", "method", "route", "status_code", "request",
    "request_digest", "response_digest", "response_semantic_digest",
}
_RESPONSE_FIELDS = {
    "schema_id", "receipt", "response", "response_semantic_digest",
    "envelope_digest",
}
_FINALIZATION_FIELDS = {
    "schema_id", "status", "receipt_id", "receipt_digest", "bundle_digest",
    "session_id", "execution_task_id", "agent_id", "attempt_id", "selection_id",
    "sandbox_workspace_id", "sandbox_run_id", "source_snapshot_artifact_id",
    "source_tree_digest", "artifacts", "calculation_receipts",
    "validation_metadata", "validation",
}
_SOURCE_NAMES = {
    "identity.json", "preflight.json", "host-startup.json",
    "host-supervision.json", "public-api-receipts.jsonl",
    "workspace-response.json", "events-response.json", "evidence-response.json",
    "micu-before.json", "micu-after.json",
}


def _content_digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _fail(code: str, message: str, *, identity: str) -> None:
    raise CutoverEvidenceError(code, message, details={"identity": identity})


def _safe_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if not all((
        value,
        "\\" not in value,
        "\x00" not in value,
        not path.is_absolute(),
        path.as_posix() == value,
        all(part not in {"", ".", ".."} for part in path.parts),
    )):
        _fail("public_conductor_artifact_path_invalid", "unsafe artifact path", identity="deliverables.relative_path")
    return value


def _read_bound_artifact_file(
    artifact_root: Path, relative_path: str, *, identity: str
) -> tuple[Path, bytes]:
    root = artifact_root.expanduser().absolute()
    path = root / _safe_relative_path(relative_path)
    try:
        root_meta, path_meta = root.lstat(), path.lstat()
        resolved_root, resolved_path = root.resolve(strict=True), path.resolve(strict=True)
    except OSError as exc:
        raise CutoverEvidenceError(
            "public_conductor_artifact_unreadable",
            "public conductor artifact root or source is unreadable",
            details={"identity": identity},
        ) from exc
    if not all((
        stat.S_ISDIR(root_meta.st_mode), not stat.S_ISLNK(root_meta.st_mode),
        resolved_root == root, stat.S_ISREG(path_meta.st_mode),
        not stat.S_ISLNK(path_meta.st_mode), resolved_path == path,
        resolved_root in resolved_path.parents,
    )):
        _fail("public_conductor_artifact_path_invalid", "artifact is outside its real root", identity=identity)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened, chunks = os.fstat(descriptor), []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    if (opened.st_dev, opened.st_ino) != (path_meta.st_dev, path_meta.st_ino):
        _fail("public_conductor_artifact_identity_drift", "artifact identity changed", identity=identity)
    return path, b"".join(chunks)


def _load_canonical_object(
    path: Path, *, identity: str
) -> tuple[dict[str, Any], bytes]:
    try:
        metadata, content = path.lstat(), path.read_bytes()
        value = _strict_json_loads(content.decode())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CutoverEvidenceError(
            "public_conductor_source_unreadable",
            "public conductor source is not readable canonical JSON",
            details={"identity": identity},
        ) from exc
    if not all((
        stat.S_ISREG(metadata.st_mode), not stat.S_ISLNK(metadata.st_mode),
        isinstance(value, dict),
        isinstance(value, dict) and content == canonical_json_bytes(value) + b"\n",
    )):
        _fail("public_conductor_source_noncanonical", "source is not canonical JSON", identity=identity)
    return dict(value), content


def _load_receipt_chain(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    try:
        metadata, content = path.lstat(), path.read_bytes()
    except OSError as exc:
        raise CutoverEvidenceError(
            "public_receipt_chain_unreadable",
            "public Host receipt chain is unreadable",
            details={"identity": "receipt_chain"},
        ) from exc
    if not all((
        stat.S_ISREG(metadata.st_mode), not stat.S_ISLNK(metadata.st_mode),
        bool(content), content.endswith(b"\n"),
    )):
        _fail("public_receipt_chain_invalid", "receipt chain is not complete JSONL", identity="receipt_chain")
    records: list[dict[str, Any]] = []
    for sequence, line in enumerate(content.splitlines(), 1):
        try:
            raw = _strict_json_loads(line.decode())
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise CutoverEvidenceError(
                "public_receipt_chain_invalid",
                "public Host receipt chain contains invalid JSONL",
                details={"identity": f"receipt_chain[{sequence}]"},
            ) from exc
        valid = isinstance(raw, dict) and all((
            set(raw) == _RECEIPT_FIELDS,
            raw.get("schema_id") == PUBLIC_API_RECEIPT_SCHEMA_ID,
            raw.get("sequence") == sequence,
            canonical_json_bytes(raw) == line,
            raw.get("request_digest") == canonical_digest(raw.get("request")),
            type(raw.get("status_code")) is int,
            200 <= int(raw.get("status_code") or 0) < 300,
            all(_DIGEST.fullmatch(str(raw.get(name) or "")) for name in (
                "request_digest", "response_digest", "response_semantic_digest"
            )),
        ))
        if not valid:
            _fail("public_receipt_chain_invalid", "receipt chain is not successful and closed", identity=f"receipt_chain[{sequence}]")
        records.append(dict(raw))
    return records, content


def _load_response_envelope(
    path: Path, *, identity: str, receipts: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Any], bytes]:
    value, content = _load_canonical_object(path, identity=identity)
    receipt = value.get("receipt")
    payload = {key: item for key, item in value.items() if key != "envelope_digest"}
    if not (isinstance(receipt, dict) and all((
        set(value) == _RESPONSE_FIELDS,
        value.get("schema_id") == PUBLIC_RESPONSE_ENVELOPE_SCHEMA_ID,
        set(receipt) == _RECEIPT_FIELDS,
        value.get("response_semantic_digest") == canonical_digest(value.get("response")),
        receipt.get("response_semantic_digest") == value.get("response_semantic_digest"),
        value.get("envelope_digest") == canonical_digest(payload),
        sum(dict(item) == receipt for item in receipts) == 1,
    ))):
        _fail("public_response_binding_invalid", "response does not bind one receipt", identity=identity)
    return value, content


def _validate_startup(
    startup: Mapping[str, Any], *, preflight: Mapping[str, Any]
) -> dict[str, Any]:
    value, slot = dict(startup), dict(preflight["slot"])
    request = dict(slot.get("authority_request") or {})
    fields = {
        "schema_id", "base_url", "attempt_id", "attempt_kind", "session_id",
        "task_id", "lane_id", "attempt_authority_id",
        "attempt_authority_request_digest", "campaign_id",
        "preflight_receipt_digest", "process_epoch", "child_pid", "child_pgid",
        "child_start_time_ticks", "timeout_seconds", "started_at", "receipt_digest",
    }
    bindings = {
        "attempt_id": slot.get("attempt_id"), "attempt_kind": slot.get("attempt_kind"),
        "session_id": slot.get("session_id"), "task_id": slot.get("task_id"),
        "lane_id": slot.get("lane_id"), "attempt_authority_id": slot.get("envelope_id"),
        "attempt_authority_request_digest": slot.get("request_digest"),
        "campaign_id": preflight.get("campaign_id"),
        "preflight_receipt_digest": preflight.get("receipt_digest"),
        "timeout_seconds": request.get("max_wall_time_seconds"),
    }
    payload = {key: item for key, item in value.items() if key != "receipt_digest"}
    if not all((
        set(value) == fields, value.get("schema_id") == HOST_STARTUP_SCHEMA_ID,
        str(value.get("base_url") or "").startswith("http://127.0.0.1:"),
        all(value.get(key) == expected for key, expected in bindings.items()),
        all(type(value.get(key)) is int and value[key] > 0 for key in (
            "child_pid", "child_pgid", "child_start_time_ticks"
        )),
        value.get("child_pid") == value.get("child_pgid"),
        bool(value.get("process_epoch")), bool(value.get("started_at")),
        value.get("receipt_digest") == canonical_digest(payload),
    )):
        _fail("host_startup_receipt_invalid", "Host startup does not bind preflight", identity="host_startup")
    return value


def _validate_control_slot_binding(
    *, slot: Mapping[str, Any], control: Mapping[str, Any]
) -> None:
    parts = {
        name: dict(control.get(name) or {})
        for name in (
            "attempt_authority", "admission_request", "attempt", "selection",
            "closure_request", "closure",
        )
    }
    request = dict(slot.get("authority_request") or {})
    shared = {
        "session_id": slot.get("session_id"), "task_id": slot.get("task_id"),
        "campaign_id": request.get("campaign_id"), "workflow_id": request.get("workflow_id"),
    }
    admission_key = f"{request.get('campaign_id')}:attempt:{slot.get('ordinal')}"
    expected = {
        "attempt_authority": {
            **shared, "envelope_id": slot.get("envelope_id"),
            "root_ref": request.get("root_ref"),
            "idempotency_key": request.get("idempotency_key"),
        },
        "admission_request": {
            **shared, "envelope_id": slot.get("envelope_id"),
            "lane_id": slot.get("lane_id"), "scope": slot.get("scope"),
            "idempotency_key": admission_key,
        },
        "attempt": {
            **shared, "attempt_id": slot.get("attempt_id"),
            "envelope_id": slot.get("envelope_id"), "lane_id": slot.get("lane_id"),
            "scope": slot.get("scope"), "idempotency_key": admission_key,
        },
    }
    selection, admission, attempt = (
        parts[name] for name in ("selection", "admission_request", "attempt")
    )
    closure_request, closure = parts["closure_request"], parts["closure"]
    valid = all(
        all(parts[name].get(key) == item for key, item in bindings.items())
        for name, bindings in expected.items()
    ) and all((
        attempt.get("admission_request_id") == admission.get("admission_request_id"),
        selection.get("attempt_id") == slot.get("attempt_id"),
        closure_request.get("attempt_id") == slot.get("attempt_id"),
        closure_request.get("selection_id") == selection.get("selection_id"),
        closure.get("attempt_id") == slot.get("attempt_id"),
        closure.get("selection_id") == selection.get("selection_id"),
        closure.get("closure_request_id") == closure_request.get("closure_request_id"),
    ))
    if not valid:
        _fail("public_conductor_control_slot_mismatch", "closed control differs from authority", identity="closed_evidence.scientific_attempt_control")


def _validate_receipt_chain(
    receipts: Sequence[Mapping[str, Any]],
    *,
    slot: Mapping[str, Any],
    identity: Mapping[str, str],
    control: Mapping[str, Any],
) -> None:
    records = [dict(item) for item in receipts]
    if [item.get("sequence") for item in records] != list(range(1, len(records) + 1)):
        _fail("public_conductor_command_order_invalid", "command sequence is discontinuous", identity="receipt_chain")
    _validate_control_slot_binding(slot=slot, control=control)
    session_id, attempt_id = str(slot["session_id"]), str(slot["attempt_id"])
    selection = dict(control.get("selection") or {})
    selection_id = str(selection.get("selection_id") or "")
    command_route = f"/v3/sessions/{session_id}/scientific-attempt-commands"
    routes = {
        "grant": f"/v3/sessions/{session_id}/scientific-attempt-authorizations",
        "admission": f"/v3/sessions/{session_id}/scientific-attempt-admissions/finalize",
        "closure": f"/v3/sessions/{session_id}/scientific-attempt-closures/finalize",
        "drain": f"/v3/sessions/{session_id}/runtime/drain",
        "pending": f"/v3/sessions/{session_id}/pending-approvals",
        "workspace": f"/v3/sessions/{session_id}/workspace",
        "events": f"/v3/sessions/{session_id}/events?replay=1&after_cursor=0",
        "export": (
            f"/v3/sessions/{session_id}/scientific-attempts/{attempt_id}/"
            f"selections/{selection_id}/evidence"
        ),
    }
    remaining = list(records)

    def consume(
        method: str, route: str, request: object = _ANY, *, code: str
    ) -> dict[str, Any]:
        matches = [
            item for item in remaining
            if item.get("method") == method and item.get("route") == route
            and (request is _ANY or item.get("request") == request)
        ]
        if len(matches) != 1:
            _fail(code, "public command chain differs from its sealed control", identity="receipt_chain")
        remaining.remove(matches[0])
        return matches[0]

    core_code = "public_conductor_command_chain_invalid"
    milestones = [
        consume("POST", "/v3/sessions", {
            "session_id": session_id, "project_id": "aox-blank-world-cutover",
            "objective": PUBLIC_CONDUCTOR_OBJECTIVE, "title": PUBLIC_CONDUCTOR_TITLE,
        }, code=core_code),
        consume("POST", f"/v3/sessions/{session_id}/messages", {
            "message_digest": _content_digest(PUBLIC_CONDUCTOR_MESSAGE.encode()),
            "skill_keys": [identity["workflow_ref"]], "task_id": None, "lane_id": None,
        }, code=core_code),
        consume("POST", routes["grant"], authority_grant_payload(slot), code=core_code),
        consume("POST", command_route, {
            "command": "attempt.create", "arguments": attempt_admission_arguments(slot)
        }, code=core_code),
        consume("POST", routes["admission"], {
            "admission_request_id": dict(control.get("admission_request") or {}).get(
                "admission_request_id"
            )
        }, code=core_code),
    ]
    selected_code = "public_conductor_selected_chain_request_invalid"
    begin = consume("POST", command_route, {
        "command": "scientific.selection.begin", "arguments": {"attempt_id": attempt_id}
    }, code=selected_code)
    dynamic: list[dict[str, Any]] = []
    for item in control.get("dispositions") or []:
        if isinstance(item, dict):
            dynamic.append(consume("POST", command_route, {
                "command": "scientific.operation.disposition",
                "arguments": {key: item.get(key) for key in (
                    "selection_id", "operation_id", "kind", "reason_code",
                    "replacement_operation_id",
                )},
            }, code=selected_code))
    for item in control.get("adoptions") or []:
        if isinstance(item, dict):
            dynamic.append(consume("POST", command_route, {
                "command": "scientific.operation.adopt",
                "arguments": {key: item.get(key) for key in (
                    "selection_id", "operation_id", "workflow_role", "reason_code"
                )},
            }, code=selected_code))
    for item in control.get("materializations") or []:
        if isinstance(item, dict):
            dynamic.append(consume("POST", command_route, {
                "command": "scientific.artifact.materialize",
                "arguments": {
                    "selection_id": item.get("selection_id"),
                    "adoption_id": item.get("adoption_id"),
                    "source_artifact_id": item.get("source_artifact_id"),
                    "target_sandbox_run_id": item.get("target_sandbox_run_id"),
                    "target": item.get("target_path"),
                },
            }, code=selected_code))
    seal = consume("POST", command_route, {
        "command": "scientific.selection.seal",
        "arguments": {
            "selection_id": selection_id,
            "expected_universe_digest": selection.get("operation_universe_digest"),
        },
    }, code=selected_code)
    close = consume("POST", command_route, {
        "command": "scientific.attempt.close",
        "arguments": {"attempt_id": attempt_id, "selection_id": selection_id},
    }, code=selected_code)
    closure = consume("POST", routes["closure"], {
        "closure_request_id": dict(control.get("closure_request") or {}).get(
            "closure_request_id"
        )
    }, code=core_code)
    final = {
        name: consume("GET", routes[name], request, code="public_conductor_command_order_invalid")
        for name, request in (
            ("workspace", {}), ("events", {"replay": True, "after_cursor": 0}),
            ("export", {}),
        )
    }
    approval_ids = {
        str(item["approval_id"])
        for item in dict(control.get("operation_universe") or {}).get("occurrences") or []
        if isinstance(item, dict) and item.get("approval_id") is not None
    }
    approvals = [
        consume("POST", f"/v3/approvals/{approval_id}/resolve", code="public_conductor_approval_chain_invalid")
        for approval_id in sorted(approval_ids)
    ]
    drain_request = {
        "max_signals": 1, "max_steps_per_agent": 8,
        "auto_enqueue_ready_tasks": False,
    }
    drains = [item for item in remaining if (
        item.get("method"), item.get("route"), item.get("request")
    ) == ("POST", routes["drain"], drain_request)]
    statuses = [item for item in remaining if (
        item.get("method") == "GET" and item.get("request") == {}
        and re.fullmatch(
            rf"/v3/sessions/{re.escape(session_id)}/runtime/commands/[^/]+",
            str(item.get("route") or ""),
        )
    )]
    pending = [item for item in remaining if (
        item.get("method"), item.get("route"), item.get("request")
    ) == ("GET", routes["pending"], {})]
    for item in (*drains, *statuses, *pending):
        remaining.remove(item)
    if not drains or not statuses or remaining or (
        approvals and (not pending or min(item["sequence"] for item in approvals)
                       <= min(item["sequence"] for item in pending))
    ):
        _fail("public_conductor_approval_chain_invalid", "drain or approval chain is incomplete", identity="receipt_chain")
    order = [item["sequence"] for item in (*milestones, begin, seal, close, closure)]
    dynamic_ordered = all(
        begin["sequence"] < item["sequence"] < seal["sequence"] for item in dynamic
    )
    last_mutation = max(
        item["sequence"] for item in records if item.get("method") in {"POST", "PATCH"}
    )
    if order != sorted(set(order)) or not dynamic_ordered or any(
        item["sequence"] <= last_mutation for item in final.values()
    ):
        _fail("public_conductor_command_order_invalid", "command/read order is not closed", identity="receipt_chain")


def _control_projection(
    control: Mapping[str, Any], *, attempt_kind: str,
    receipts: Sequence[Mapping[str, Any]], supervision: Mapping[str, Any]
) -> dict[str, Any]:
    universe = dict(control.get("operation_universe") or {}).get("occurrences") or []
    operations = [dict(item) for item in universe if isinstance(item, dict)]
    adoptions = [dict(item) for item in control.get("adoptions") or [] if isinstance(item, dict)]
    materials = [
        dict(item) for item in control.get("materializations") or [] if isinstance(item, dict)
    ]
    artifacts = {
        str(item.get("source_artifact_id")): {
            "artifact_id": item.get("source_artifact_id"),
            "content_digest": item.get("source_artifact_digest"),
        }
        for item in materials if item.get("source_artifact_id")
    }
    return {
        "attempt_id": dict(control.get("attempt") or {}).get("attempt_id"),
        "attempt_kind": attempt_kind,
        "product_path": {
            "public_api_receipts": [dict(item) for item in receipts],
            "attempt_supervision": dict(supervision),
        },
        "operations": [{
            "operation_id": item.get("operation_id"), "scope": "formal",
            "canonical_ref_kind": "controlled_operation",
            "status": item.get("operation_status"),
        } for item in operations],
        "artifacts": list(artifacts.values()),
        "scientific_checks": {"aox_chain": {"operation_roles": {
            str(item.get("workflow_role")): item.get("operation_id") for item in adoptions
        }}},
    }


def _validate_control(
    control: Mapping[str, Any], *, attempt_kind: str,
    receipts: Sequence[Mapping[str, Any]], supervision: Mapping[str, Any]
) -> dict[str, Any]:
    projection = _control_projection(
        control, attempt_kind=attempt_kind, receipts=receipts, supervision=supervision
    )
    issues: list[VerificationIssue] = []
    _verify_selected_chain_control(projection, control=control, issues=issues)
    if issues:
        issue = issues[0]
        _fail(issue.code, issue.message, identity=issue.identity)
    return projection


def _workspace_task(workspace: Mapping[str, Any], task_id: str) -> dict[str, Any] | None:
    for item in dict(workspace.get("task_board") or {}).get("items") or []:
        task = item.get("task") if isinstance(item, dict) else None
        if isinstance(task, dict) and task.get("task_id") == task_id:
            return dict(task)
    return None


def _typed_fault_failure(workspace: Mapping[str, Any]) -> dict[str, Any] | None:
    failures = [
        dict(item)
        for item in dict(workspace.get("scientific_evidence") or {}).get("operations") or []
        if isinstance(item, dict) and item.get("status") in {"failed", "terminal_failed"}
        and isinstance(item.get("error_code"), str) and item.get("error_code")
    ]
    if not failures:
        return None
    first = min(failures, key=lambda item: (
        int(item.get("state_version") or 0), str(item.get("operation_id") or "")
    ))
    details = dict(first.get("details") or {})
    return {
        "injection_id": first.get("injection_id") or details.get("fault_id"),
        "operation_id": first.get("operation_id"), "error_code": first.get("error_code"),
        "effect_certainty": first.get("effect_certainty"),
        "retry_eligibility": first.get("retry_eligibility"),
        "failure_digest": canonical_digest(first),
    }


def _validate_finalization(
    receipt: Mapping[str, Any], deliverables: Sequence[Mapping[str, Any]],
    *, control: Mapping[str, Any]
) -> tuple[dict[str, bytes], dict[str, Any]]:
    value = dict(receipt)
    attempt, selection = (dict(control.get(name) or {}) for name in ("attempt", "selection"))
    bindings = {
        "attempt_id": attempt.get("attempt_id"),
        "selection_id": selection.get("selection_id"),
        "execution_task_id": attempt.get("task_id"), "agent_id": selection.get("actor_ref"),
    }
    payload = {key: item for key, item in value.items() if key != "receipt_digest"}
    if not all((
        set(value) == _FINALIZATION_FIELDS,
        value.get("schema_id") == aox_finalization.FINALIZATION_RECEIPT_SCHEMA_ID,
        value.get("status") == "passed",
        all(value.get(key) == expected for key, expected in bindings.items()),
        value.get("receipt_digest") == canonical_digest(payload),
    )):
        _fail("aox_finalization_receipt_invalid", "finalization identity is invalid", identity="closed_evidence.finalization_receipt")
    refs, metadata = value.get("artifacts"), value.get("validation_metadata")
    if not (isinstance(refs, list) and isinstance(metadata, dict)
            and set(metadata) == S15_AOX_HMM_FIXED_DELIVERABLES
            and all(isinstance(item, dict) for item in metadata.values())):
        _fail("aox_finalization_receipt_invalid", "finalization preimage is incomplete", identity="closed_evidence.finalization_receipt")
    exported: dict[str, dict[str, Any]] = {}
    contents: dict[str, bytes] = {}
    fields = {"artifact_id", "relative_path", "content_digest", "content_base64"}
    for raw in deliverables:
        if not isinstance(raw, dict) or set(raw) != fields:
            _fail("aox_closed_deliverable_invalid", "malformed deliverable", identity="closed_evidence.deliverables")
        path = _safe_relative_path(str(raw["relative_path"]))
        try:
            content = base64.b64decode(str(raw["content_base64"]), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise CutoverEvidenceError(
                "aox_closed_deliverable_invalid",
                "closed deliverable is not canonical base64", details={"identity": path},
            ) from exc
        if path in exported or _content_digest(content) != raw.get("content_digest"):
            _fail("aox_closed_deliverable_digest_mismatch", "deliverable bytes drifted", identity=path)
        exported[path], contents[path] = dict(raw), content
    refs_by_path = {
        str(item.get("relative_path") or ""): dict(item)
        for item in refs if isinstance(item, dict)
    }
    if not all((
        set(exported) == S15_AOX_HMM_FIXED_DELIVERABLES,
        set(refs_by_path) == S15_AOX_HMM_FIXED_DELIVERABLES,
        all(
            {key: exported[path].get(key) for key in (
                "artifact_id", "relative_path", "content_digest"
            )} == refs_by_path[path]
            for path in refs_by_path
        ),
    )):
        _fail("aox_closed_deliverable_set_invalid", "deliverable set differs from receipt", identity="closed_evidence.deliverables")
    try:
        texts = {path: content.decode() for path, content in contents.items()}
    except UnicodeDecodeError as exc:
        raise CutoverEvidenceError(
            "aox_finalization_artifact_unreadable", "AOX final deliverables must be UTF-8",
            details={"identity": "closed_evidence.deliverables"},
        ) from exc
    metadata_by_path = {str(path): dict(item) for path, item in metadata.items()}
    validation = validate_aox_final_artifacts(set(contents), texts, metadata_by_path)
    if validation.get("passed") is not True or value.get("validation") != validation:
        _fail(
            str(validation.get("earliest_error_code") or "aox_finalization_validation_drift"),
            "offline AOX validation differs from Host finalization",
            identity="closed_evidence.finalization_receipt.validation",
        )
    drafts = {
        path: SimpleNamespace(content=content, content_digest=_content_digest(content))
        for path, content in contents.items()
    }
    try:
        calculations = _calculation_receipts(value.get("calculation_receipts"))
        _verify_calculation_receipts(
            receipts=calculations, drafts_by_path=drafts, validation=validation
        )
    except AoxBundleFinalizationError as exc:
        raise CutoverEvidenceError(
            exc.error_code, exc.public_message,
            details={"identity": "closed_evidence.finalization_receipt"},
        ) from exc
    identity_fields = (
        "session_id", "execution_task_id", "agent_id", "attempt_id", "selection_id",
        "sandbox_workspace_id", "sandbox_run_id", "source_snapshot_artifact_id",
        "source_tree_digest",
    )
    bundle_preimage = {
        "schema_id": aox_finalization.FINAL_BUNDLE_PROFILE_ID,
        **{key: value[key] for key in identity_fields},
        "items": [{
            "relative_path": path, "content_digest": _content_digest(contents[path]),
            "kind": "sequence" if path.endswith(".fasta") else "result",
            "metadata_digest": canonical_digest(metadata[path]),
        } for path in sorted(contents)],
        "calculation_receipts": [calculations[key] for key in sorted(calculations)],
        "validation_digest": canonical_digest(validation),
    }
    if value.get("bundle_digest") != canonical_digest(bundle_preimage):
        _fail("aox_finalization_receipt_bundle_drift", "finalization bundle drifted", identity="closed_evidence.finalization_receipt.bundle_digest")
    return contents, validation


def _validate_closed_export(
    export: Mapping[str, Any], *, slot: Mapping[str, Any], workspace: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]], supervision: Mapping[str, Any]
) -> tuple[dict[str, bytes], dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    value = dict(export)
    control = value.get("scientific_attempt_control")
    payload = {key: item for key, item in value.items() if key != "export_digest"}
    fields = {
        "schema_id", "session_id", "attempt_id", "selection_id",
        "scientific_attempt_control", "finalization_receipt", "deliverables",
        "export_digest",
    }
    if not (isinstance(control, dict) and all((
        set(value) == fields, value.get("schema_id") == "aox_closed_attempt_evidence@1",
        value.get("session_id") == slot.get("session_id"),
        value.get("attempt_id") == slot.get("attempt_id"),
        value.get("selection_id") == dict(control.get("selection") or {}).get("selection_id"),
        value.get("export_digest") == canonical_digest(payload),
        isinstance(value.get("deliverables"), list),
    ))):
        _fail("aox_closed_attempt_export_invalid", "closed export does not bind authority", identity="closed_evidence")
    _validate_control_slot_binding(slot=slot, control=control)
    kind = str(slot["attempt_kind"])
    projection = _validate_control(
        control=control, attempt_kind=kind, receipts=receipts, supervision=supervision
    )
    if projection is None:  # test seam; production validator returns its projection
        projection = _control_projection(
            control,
            attempt_kind=kind,
            receipts=receipts,
            supervision=supervision,
        )
    task = _workspace_task(workspace, str(slot["task_id"]))
    finalization, deliverables = value.get("finalization_receipt"), value["deliverables"]
    if kind == "positive":
        reports = [item for item in workspace.get("reports") or [] if (
            isinstance(item, dict) and item.get("task_id") == slot.get("task_id")
            and item.get("status") == "ready"
        )]
        drafts = [item for item in workspace.get("report_drafts") or [] if (
            isinstance(item, dict) and item.get("task_id") == slot.get("task_id")
            and item.get("status") == "published"
        )]
        if not all((
            task is not None and task.get("status") == "completed",
            len(reports) == 1, len(drafts) == 1, isinstance(finalization, dict),
        )):
            _fail("positive_product_closure_invalid", "positive closure is incomplete", identity="workspace")
        contents, validation = _validate_finalization(
            finalization, deliverables, control=control
        )
        return contents, validation, None, projection
    failure = _typed_fault_failure(workspace)
    if kind != "fault":
        _fail("public_conductor_attempt_kind_invalid", "attempt kind is unsupported", identity="slot.attempt_kind")
    ready_report = any(
        isinstance(item, dict) and item.get("task_id") == slot.get("task_id")
        and item.get("status") == "ready" for item in workspace.get("reports") or []
    )
    if (finalization is not None or deliverables or failure is None or ready_report
            or (task is not None and task.get("status") == "completed")):
        _fail("fault_product_closure_invalid", "fault did not fail closed", identity="workspace.scientific_evidence")
    return {}, None, failure, projection


def _validate_events(events: object, *, session_id: str) -> list[dict[str, Any]]:
    if not isinstance(events, list) or not all(isinstance(item, dict) for item in events):
        _fail("public_event_replay_invalid", "event replay is not an object list", identity="events_response")
    records = [dict(item) for item in events]
    cursors = [item.get("cursor") for item in records]
    if (any(item.get("session_id") != session_id for item in records)
            or any(type(cursor) is not int or cursor <= 0 for cursor in cursors)
            or cursors != sorted(set(cursors))):
        _fail("public_event_replay_invalid", "event replay is not ordered", identity="events_response")
    return records


def _source_payload(
    *, identity_path: Path, preflight_path: Path, receipt_chain_path: Path,
    workspace_response_path: Path, event_response_path: Path,
    evidence_response_path: Path, ledger_before_path: Path,
    ledger_after_path: Path, sealed_at: str,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    identity_value, identity_bytes = _load_canonical_object(identity_path, identity="identity")
    identity = _normalize_identity(identity_value)
    preflight = load_attempt_preflight_receipt(preflight_path)
    preflight_value, preflight_bytes = _load_canonical_object(
        preflight_path, identity="preflight"
    )
    if preflight_value != preflight or preflight.get("identity_digest") != canonical_digest(identity):
        _fail("public_conductor_preflight_identity_mismatch", "preflight identity drifted", identity="preflight.identity_digest")
    slot = dict(preflight["slot"])
    startup_value, startup_bytes = _load_canonical_object(
        preflight_path.parent / HOST_STARTUP_FILENAME, identity="host_startup"
    )
    startup = _validate_startup(startup_value, preflight=preflight)
    supervision_value, supervision_bytes = _load_canonical_object(
        preflight_path.parent / HOST_SUPERVISION_FILENAME, identity="host_supervision"
    )
    supervision = validate_supervised_host_receipt(
        supervision_value, attempt_id=str(slot["attempt_id"]),
        attempt_kind=str(slot["attempt_kind"]),
        attempt_authority_id=str(slot["envelope_id"]),
        attempt_authority_request_digest=str(slot["request_digest"]),
    )
    supervision_bindings = {
        "preflight_receipt_digest": preflight.get("receipt_digest"),
        "host_startup_receipt_digest": startup.get("receipt_digest"),
        "process_epoch": startup.get("process_epoch"),
        "timeout_seconds": startup.get("timeout_seconds"),
        "session_id": slot.get("session_id"), "task_id": slot.get("task_id"),
        "lane_id": slot.get("lane_id"), "campaign_id": preflight.get("campaign_id"),
    }
    if any(supervision.get(key) != item for key, item in supervision_bindings.items()):
        _fail("host_supervision_source_mismatch", "Host supervision source drifted", identity="host_supervision")
    receipts, receipt_bytes = _load_receipt_chain(receipt_chain_path)
    envelopes = {
        name: _load_response_envelope(path, identity=f"{name}_response", receipts=receipts)
        for name, path in (
            ("workspace", workspace_response_path), ("events", event_response_path),
            ("evidence", evidence_response_path),
        )
    }
    workspace = envelopes["workspace"][0].get("response")
    if not isinstance(workspace, dict) or dict(workspace.get("session") or {}).get(
        "session_id"
    ) != slot.get("session_id"):
        _fail(
            "public_workspace_identity_mismatch",
            "final workspace differs from the authority session", identity="workspace_response",
        )
    events = _validate_events(
        envelopes["events"][0].get("response"), session_id=str(slot["session_id"])
    )
    closed = envelopes["evidence"][0].get("response")
    control = closed.get("scientific_attempt_control") if isinstance(closed, dict) else None
    if not isinstance(closed, dict) or not isinstance(control, dict):
        _fail(
            "scientific_attempt_control_missing",
            "closed-attempt export lacks canonical control", identity="evidence_response",
        )
    _validate_receipt_chain(receipts, slot=slot, identity=identity, control=control)
    selection_id = dict(control.get("selection") or {}).get("selection_id")
    expected_routes = {
        "workspace": f"/v3/sessions/{slot['session_id']}/workspace",
        "events": f"/v3/sessions/{slot['session_id']}/events?replay=1&after_cursor=0",
        "evidence": (
            f"/v3/sessions/{slot['session_id']}/scientific-attempts/{slot['attempt_id']}/"
            f"selections/{selection_id}/evidence"
        ),
    }
    if any(
        dict(envelopes[name][0]["receipt"]).get("route") != route
        for name, route in expected_routes.items()
    ):
        _fail(
            "public_response_route_mismatch", "sealed public response uses the wrong route",
            identity="public_response.receipt.route",
        )
    contents, validation, fault, projection = _validate_closed_export(
        closed, slot=slot, workspace=workspace, receipts=receipts, supervision=supervision
    )
    before, before_bytes = _load_canonical_object(ledger_before_path, identity="micu_before")
    after, after_bytes = _load_canonical_object(ledger_after_path, identity="micu_after")
    _validate_ledger_transition(before, after)
    config = dict(preflight.get("effective_config") or {})
    if (config.get("schema_id") != "aox_blank_world_runtime_config@4"
            or dict(config.get("conductor") or {}).get("orchestration_owner")
            != "codex_tester"):
        _fail(
            "public_conductor_effective_config_invalid",
            "preflight lacks the current public-conductor config",
            identity="preflight.effective_config",
        )
    source_bytes = {
        "identity.json": identity_bytes, "preflight.json": preflight_bytes,
        "host-startup.json": startup_bytes, "host-supervision.json": supervision_bytes,
        "public-api-receipts.jsonl": receipt_bytes,
        "workspace-response.json": envelopes["workspace"][1],
        "events-response.json": envelopes["events"][1],
        "evidence-response.json": envelopes["evidence"][1],
        "micu-before.json": before_bytes, "micu-after.json": after_bytes,
    }
    attestations = [{
        "name": name,
        "relative_path": f"{PUBLIC_CONDUCTOR_ATTESTATION_DIR}/attestations/{name}",
        "content_digest": _content_digest(content),
    } for name, content in sorted(source_bytes.items())]
    deliverables = [{
        "relative_path": path,
        "sealed_relative_path": f"{PUBLIC_CONDUCTOR_ATTESTATION_DIR}/deliverables/{path}",
        "content_digest": _content_digest(content),
    } for path, content in sorted(contents.items())]
    kind = str(slot["attempt_kind"])
    payload = {
        "schema_id": ATTEMPT_BUNDLE_SCHEMA_ID_V3,
        "bundle_profile": PUBLIC_CONDUCTOR_BUNDLE_PROFILE_ID,
        "attempt_id": slot["attempt_id"], "attempt_kind": kind, "sealed_at": sealed_at,
        "identity": {**identity, "identity_digest": canonical_digest(identity)},
        "clean_world": dict(preflight["root_proof"]),
        "micu_ledger": {"before": before, "after": after},
        "authority": {
            "campaign_id": preflight["campaign_id"], "plan_digest": preflight["plan_digest"],
            "consumption_digest": preflight["consumption_digest"],
            "preflight_receipt_digest": preflight["receipt_digest"], "slot": slot,
        },
        "effective_config": config,
        "product_path": {
            "host_startup": startup, "attempt_supervision": supervision,
            "public_api_receipts": receipts,
            "public_api_receipt_chain_digest": _content_digest(receipt_bytes),
            "final_workspace_response_digest": envelopes["workspace"][0]["envelope_digest"],
            "final_event_response_digest": envelopes["events"][0]["envelope_digest"],
            "closed_evidence_response_digest": envelopes["evidence"][0]["envelope_digest"],
        },
        "scientific_attempt_control": control,
        "operations": projection["operations"], "artifacts": projection["artifacts"],
        "scientific_checks": {
            **projection["scientific_checks"],
            "finalization_receipt": closed.get("finalization_receipt"),
        },
        "attestations": attestations, "deliverables": deliverables,
        "report": {
            "status": "published" if kind == "positive" else "withheld",
            "cutover_eligible": kind == "positive",
            "workspace_digest": canonical_digest(workspace),
        },
        "scientific_outcome": {
            "cutover_eligible": kind == "positive",
            "status": "passed" if kind == "positive" else "controlled_failure",
            "failure_code": None if fault is None else fault["error_code"],
            "validation_digest": None if validation is None else canonical_digest(validation),
        },
        "fault_injection": fault, "event_count": len(events),
        "event_stream_digest": canonical_digest(events),
    }
    files = {f"attestations/{name}": content for name, content in source_bytes.items()}
    files.update({f"deliverables/{path}": content for path, content in contents.items()})
    return payload, files


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def finalize_and_seal_public_conductor_bundle(
    *, identity_path: Path, preflight_path: Path, receipt_chain_path: Path,
    workspace_response_path: Path, event_response_path: Path,
    evidence_response_path: Path, ledger_before_path: Path,
    ledger_after_path: Path, sealed_at: str | None = None,
) -> tuple[Path, str]:
    preflight_path = preflight_path.expanduser().resolve(strict=True)
    attempt_root = preflight_path.parent.parent
    artifact_root, evidence_root = attempt_root / "artifacts", attempt_root / "evidence"
    destination = evidence_root / PUBLIC_CONDUCTOR_BUNDLE_FILENAME
    target = artifact_root / PUBLIC_CONDUCTOR_ATTESTATION_DIR
    if any(path.exists() or path.is_symlink() for path in (destination, target)):
        _fail(
            "public_conductor_bundle_append_only",
            "public conductor bundle or attestation tree already exists",
            identity="attempt_bundle",
        )
    payload, files = _source_payload(
        identity_path=identity_path, preflight_path=preflight_path,
        receipt_chain_path=receipt_chain_path,
        workspace_response_path=workspace_response_path,
        event_response_path=event_response_path,
        evidence_response_path=evidence_response_path,
        ledger_before_path=ledger_before_path, ledger_after_path=ledger_after_path,
        sealed_at=sealed_at or datetime.now(UTC).isoformat(),
    )
    temporary = Path(tempfile.mkdtemp(prefix=".aox-public-conductor-", dir=artifact_root))
    try:
        for relative, content in sorted(files.items()):
            path = temporary / _safe_relative_path(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            path.chmod(0o400)
        directories = sorted(
            (path for path in temporary.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts), reverse=True,
        )
        for directory in directories:
            _fsync_directory(directory)
            directory.chmod(0o500)
        _fsync_directory(temporary)
        temporary.chmod(0o500)
        try:
            temporary.rename(target)
        except FileExistsError as exc:
            raise CutoverEvidenceError(
                "public_conductor_bundle_append_only",
                "public conductor attestation tree appeared during finalization",
                details={"identity": "attempt_bundle"},
            ) from exc
        _fsync_directory(artifact_root)
    finally:
        if temporary.exists():
            temporary.chmod(0o700)
            shutil.rmtree(temporary)
    bundle_digest = canonical_digest(payload)
    _write_append_only_bytes(
        destination,
        canonical_json_bytes({"payload": payload, "bundle_digest": bundle_digest}) + b"\n",
        error_code="public_conductor_bundle_append_only",
        error_message="public conductor bundle already exists",
    )
    return destination, bundle_digest


def verify_public_conductor_bundle(
    bundle_path: Path, *, artifact_root: Path
) -> VerificationResult:
    issues: list[VerificationIssue] = []
    attempt_id = attempt_kind = declared_digest = None
    try:
        envelope, _ = _load_canonical_object(bundle_path, identity="bundle")
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            _fail("bundle_envelope_invalid", "bundle payload is malformed", identity="bundle")
        attempt_id = str(payload.get("attempt_id") or "") or None
        attempt_kind = str(payload.get("attempt_kind") or "") or None
        declared_digest = str(envelope.get("bundle_digest") or "") or None
        if not all((
            set(envelope) == {"payload", "bundle_digest"},
            payload.get("schema_id") == ATTEMPT_BUNDLE_SCHEMA_ID_V3,
            payload.get("bundle_profile") == PUBLIC_CONDUCTOR_BUNDLE_PROFILE_ID,
            declared_digest == canonical_digest(payload),
        )):
            _fail(
                "bundle_digest_mismatch",
                "public conductor bundle schema or digest does not reproduce",
                identity="bundle",
            )
        sources: dict[str, Path] = {}
        for raw in payload.get("attestations") or []:
            if not isinstance(raw, dict) or set(raw) != {
                "name", "relative_path", "content_digest"
            }:
                _fail(
                    "public_conductor_attestation_invalid",
                    "source attestation is malformed", identity="attestations",
                )
            name = str(raw["name"])
            path, content = _read_bound_artifact_file(
                artifact_root, str(raw["relative_path"]), identity=name
            )
            if name in sources or _content_digest(content) != raw.get("content_digest"):
                _fail(
                    "public_conductor_attestation_digest_mismatch",
                    "source attestation is duplicated or drifted", identity=name,
                )
            sources[name] = path
        if set(sources) != _SOURCE_NAMES:
            _fail(
                "public_conductor_attestation_invalid",
                "source attestation set is incomplete", identity="attestations",
            )
        source_preflight, _ = _load_canonical_object(
            sources["preflight.json"], identity="preflight"
        )
        source_slot = dict(source_preflight.get("slot") or {})
        with tempfile.TemporaryDirectory(prefix="openzyme-aox-public-verify-") as raw:
            root = Path(raw) / str(source_slot.get("attempt_id") or "attempt")
            evidence = root / "evidence"
            root.mkdir(mode=0o700)
            evidence.mkdir(mode=0o700)
            for name in ("artifacts", "blobs", "sandboxes", "hpc-workspace"):
                (root / name).mkdir(mode=0o700)
            reconstructed = {
                "preflight": evidence / "aox-attempt-preflight.json",
                "startup": evidence / HOST_STARTUP_FILENAME,
                "supervision": evidence / HOST_SUPERVISION_FILENAME,
            }
            for source_name, destination in (
                ("preflight.json", reconstructed["preflight"]),
                ("host-startup.json", reconstructed["startup"]),
                ("host-supervision.json", reconstructed["supervision"]),
            ):
                shutil.copyfile(sources[source_name], destination)
                destination.chmod(0o600)
            rebuilt, _ = _source_payload(
                identity_path=sources["identity.json"],
                preflight_path=reconstructed["preflight"],
                receipt_chain_path=sources["public-api-receipts.jsonl"],
                workspace_response_path=sources["workspace-response.json"],
                event_response_path=sources["events-response.json"],
                evidence_response_path=sources["evidence-response.json"],
                ledger_before_path=sources["micu-before.json"],
                ledger_after_path=sources["micu-after.json"],
                sealed_at=str(payload.get("sealed_at") or ""),
            )
        if rebuilt != payload:
            _fail(
                "public_conductor_bundle_source_mismatch",
                "bundle differs from exact source reconstruction", identity="bundle.payload",
            )
        for raw in payload.get("deliverables") or []:
            if not isinstance(raw, dict):
                _fail(
                    "aox_closed_deliverable_invalid", "sealed deliverable is malformed",
                    identity="deliverables",
                )
            _, content = _read_bound_artifact_file(
                artifact_root, str(raw.get("sealed_relative_path") or ""),
                identity=str(raw.get("relative_path") or "deliverables"),
            )
            if _content_digest(content) != raw.get("content_digest"):
                _fail(
                    "aox_closed_deliverable_digest_mismatch",
                    "sealed deliverable bytes drifted",
                    identity=str(raw.get("relative_path") or "deliverables"),
                )
    except CutoverEvidenceError as exc:
        issues.append(VerificationIssue(
            code=exc.code, identity=str(exc.details.get("identity") or "bundle"),
            message=str(exc),
        ))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        issues.append(VerificationIssue(
            code="bundle_unreadable", identity="bundle",
            message=f"public conductor bundle is unreadable: {type(exc).__name__}",
        ))
    return VerificationResult(
        passed=not issues, bundle_digest=declared_digest, attempt_id=attempt_id,
        attempt_kind=attempt_kind, issues=tuple(issues),
    )


def evaluate_public_conductor_campaign(
    records: Sequence[Any], *, decided_at: str | None = None
) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    payloads: list[dict[str, Any]] = []

    def block(code: str, identity: str, message: str) -> None:
        blockers.append({"code": code, "identity": identity, "message": message})

    if len(records) != 3:
        block(
            "campaign_attempt_count", "campaign.attempts",
            "campaign requires two positives followed by one fault",
        )
    expected = ("positive", "positive", "fault")
    for index, record in enumerate(records):
        verification = verify_public_conductor_bundle(
            record.bundle_path, artifact_root=record.artifact_root
        )
        try:
            envelope, _ = _load_canonical_object(
                record.bundle_path, identity=f"campaign.attempts[{index}]"
            )
            raw = envelope.get("payload")
            payloads.append(dict(raw) if isinstance(raw, dict) else {})
        except CutoverEvidenceError:
            payloads.append({})
        if not all((
            verification.passed, verification.attempt_id == record.attempt_id,
            verification.attempt_kind == record.attempt_kind,
            verification.bundle_digest == record.bundle_digest,
            record.verification.passed,
            record.verification.bundle_digest == verification.bundle_digest,
        )):
            issue = verification.issues[0] if verification.issues else None
            block(
                "attempt_verification_failed", str(record.attempt_id),
                "offline verification failed" if issue is None
                else f"{issue.code}: {issue.identity}",
            )
        if index < 3 and record.attempt_kind != expected[index]:
            block(
                "campaign_attempt_order", f"campaign.attempts[{index}]",
                f"expected {expected[index]}, got {record.attempt_kind}",
            )
    if len(payloads) == 3 and all(payloads):
        identities = {
            str(dict(payload.get("identity") or {}).get("identity_digest") or "")
            for payload in payloads
        }
        roots = [
            str(dict(payload.get("clean_world") or {}).get("root_identity") or "")
            for payload in payloads
        ]
        chains = [
            str(dict(payload.get("product_path") or {}).get(
                "public_api_receipt_chain_digest"
            ) or "") for payload in payloads
        ]
        if len(identities) != 1 or "" in identities:
            block(
                "campaign_identity_drift", "campaign.identity",
                "all attempts must use one pinned identity",
            )
        if len(set(roots)) != 3 or "" in roots or len(set(chains)) != 3 or "" in chains:
            block(
                "campaign_attempts_not_independent", "campaign.attempts",
                "attempt roots and receipt chains must be independent",
            )
        if any(
            dict(payloads[index].get("micu_ledger") or {}).get("after")
            != dict(payloads[index + 1].get("micu_ledger") or {}).get("before")
            for index in range(2)
        ):
            block(
                "campaign_micu_ledger_discontinuity", "campaign.attempts",
                "MICU ledger snapshots are not continuous",
            )
        for index, payload in enumerate(payloads[:2]):
            if not all((
                dict(payload.get("scientific_outcome") or {}).get("cutover_eligible") is True,
                dict(payload.get("report") or {}).get("status") == "published",
                len(payload.get("deliverables") or []) == len(S15_AOX_HMM_FIXED_DELIVERABLES),
            )):
                block(
                    "positive_not_cutover_eligible", f"campaign.attempts[{index}]",
                    "positive lacks its report or 17-deliverable closure",
                )
        fault, injection = payloads[2], payloads[2].get("fault_injection")
        if not all((
            dict(fault.get("scientific_outcome") or {}).get("cutover_eligible") is False,
            dict(fault.get("scientific_outcome") or {}).get("status") == "controlled_failure",
            fault.get("deliverables") == [], isinstance(injection, dict),
        )):
            block(
                "fault_not_fail_closed", "campaign.attempts[2]",
                "fault attempt did not preserve fail-closed state",
            )
        elif not all((
            injection.get("injection_id") == FAULT_ARTIFACT_BYTE_FLIP_ID,
            injection.get("error_code") == "artifact_blob_digest_mismatch",
        )):
            block(
                "fault_contract_unproven", "campaign.attempts[2].fault_injection",
                "fault bundle does not prove the required derived byte flip",
            )
    blocker = blockers[0] if blockers else None
    decision = {
        "schema_id": CAMPAIGN_DECISION_SCHEMA_ID,
        "decided_at": decided_at or datetime.now(UTC).isoformat(),
        "decision": "GO" if blocker is None else "NO-GO",
        "attempt_digests": [record.bundle_digest for record in records],
        "attempt_ids": [record.attempt_id for record in records],
        "blocker": blocker,
    }
    return {**decision, "decision_digest": canonical_digest(decision)}


__all__ = [
    "PUBLIC_CONDUCTOR_BUNDLE_FILENAME", "PUBLIC_CONDUCTOR_BUNDLE_PROFILE_ID",
    "PUBLIC_CONDUCTOR_MESSAGE", "PUBLIC_CONDUCTOR_OBJECTIVE", "PUBLIC_CONDUCTOR_TITLE",
    "evaluate_public_conductor_campaign", "finalize_and_seal_public_conductor_bundle",
    "verify_public_conductor_bundle",
]
