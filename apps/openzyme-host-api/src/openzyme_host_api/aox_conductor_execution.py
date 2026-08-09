from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import stat
from typing import Any

from .aox_attempt_preflight import ATTEMPT_CONDUCTOR_CONTRACT_FILENAME
from .aox_attempt_preflight import ATTEMPT_PREFLIGHT_FILENAME
from .aox_attempt_preflight import load_attempt_preflight_receipt
from .aox_authority_storage import publish_private_canonical_authority
from .aox_cutover_evidence import CutoverEvidenceError
from .aox_cutover_evidence import canonical_digest
from .aox_cutover_evidence import canonical_json_bytes
from .aox_host_supervision import HOST_STARTUP_FILENAME
from .aox_host_supervision import HOST_SUPERVISION_FATAL_FILENAME
from .aox_host_supervision import HOST_SUPERVISION_FILENAME
from .aox_public_conductor_contract import PUBLIC_CONDUCTOR_PROJECT_ID
from .aox_public_conductor_contract import entry_message_request
from .aox_public_conductor_contract import runtime_drain_constraints
from .aox_public_conductor_contract import session_create_request
from .aox_public_conductor_contract import validate_bounded_drain_receipts
from .aox_public_conductor_contract import validate_bounded_drain_request
from .aox_public_conductor_contract import validate_canonical_entry_receipts
from .aox_public_conductor_contract import workflow_ref_from_preflight
from .aox_public_conductor_bundle import _load_canonical_object
from .aox_public_conductor_bundle import _load_receipt_chain
from .aox_public_conductor_bundle import _load_response_envelope
from .aox_public_conductor_bundle import _validate_events
from .aox_public_conductor_bundle import _validate_runtime_command_handoffs
from .aox_public_conductor_bundle import _validate_startup


CONDUCTOR_EXECUTION_CONTRACT_SCHEMA_ID = "aox_public_conductor_execution_contract@2"
LEGACY_CONDUCTOR_EXECUTION_CONTRACT_SCHEMA_ID = (
    "aox_public_conductor_execution_contract@1"
)
CONDUCTOR_EXECUTION_CONTRACT_FILENAME = ATTEMPT_CONDUCTOR_CONTRACT_FILENAME
CONDUCTOR_RETIREMENT_READINESS_SCHEMA_ID = (
    "aox_public_conductor_retirement_readiness@1"
)
CONDUCTOR_RETIREMENT_READINESS_FILENAME = (
    "aox-public-conductor-retirement-readiness.json"
)
PUBLIC_API_RECEIPT_CHAIN_FILENAME = "public-api-receipts.jsonl"
PUBLIC_RESPONSE_PREFIX = "public-response-"
PUBLIC_RESPONSE_SUFFIX = ".json"

_CONTRACT_FIELDS = {
    "schema_id",
    "launch_id",
    "campaign_id",
    "plan_digest",
    "preflight_receipt_digest",
    "session_id",
    "project_id",
    "public_cli_command",
    "late_bound_authority_command",
    "session_create_request",
    "entry_message_request",
    "entry_message_count",
    "runtime_drain_constraints",
    "receipt_chain_name",
    "response_name_pattern",
    "retirement_readiness_name",
    "required_final_reads",
    "contract_digest",
}
_READINESS_FIELDS = {
    "schema_id",
    "launch_id",
    "campaign_id",
    "plan_digest",
    "preflight_receipt_digest",
    "execution_contract_digest",
    "host_startup_receipt_digest",
    "session_id",
    "closure_mode",
    "scientific_attempt_count",
    "receipt_chain",
    "sealed_responses",
    "final_workspace_response_name",
    "final_event_response_name",
    "handoff_response_names",
    "evidence_response_name",
    "sealed_at",
    "receipt_digest",
}
_RECEIPT_CHAIN_FIELDS = {
    "name",
    "content_digest",
    "record_count",
    "last_sequence",
}
_RESPONSE_DESCRIPTOR_FIELDS = {
    "name",
    "content_digest",
    "sequence",
    "method",
    "route",
    "envelope_digest",
}
_SAFE_RESPONSE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_EVIDENCE_ROUTE = re.compile(
    r"/v3/sessions/[^/]+/scientific-attempts/[^/]+/selections/[^/]+/evidence"
)
_TERMINAL_RUNTIME_COMMAND_STATUSES = {
    "completed",
    "failed",
    "locked",
    "cancelled",
}


def _fail(code: str, message: str, *, identity: str) -> None:
    raise CutoverEvidenceError(code, message, details={"identity": identity})


def _content_digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _private_canonical_object(path: Path, *, identity: str) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        content = path.read_bytes()
        value = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CutoverEvidenceError(
            "public_conductor_execution_source_unreadable",
            "public conductor execution source is unreadable",
            details={"identity": identity},
        ) from exc
    if not all(
        (
            stat.S_ISREG(metadata.st_mode),
            not stat.S_ISLNK(metadata.st_mode),
            stat.S_IMODE(metadata.st_mode) & 0o077 == 0,
            isinstance(value, dict),
            isinstance(value, dict) and content == canonical_json_bytes(value) + b"\n",
        )
    ):
        _fail(
            "public_conductor_execution_source_invalid",
            "public conductor execution source is unsafe or noncanonical",
            identity=identity,
        )
    return dict(value)


def _evidence_root(preflight_path: Path) -> tuple[Path, dict[str, Any]]:
    path = preflight_path.expanduser().resolve(strict=True)
    if path.name != ATTEMPT_PREFLIGHT_FILENAME:
        _fail(
            "public_conductor_preflight_path_invalid",
            "public conductor execution requires the canonical preflight receipt",
            identity="preflight",
        )
    preflight = load_attempt_preflight_receipt(path)
    return path.parent, preflight


def build_conductor_execution_contract(
    preflight: Mapping[str, Any],
) -> dict[str, Any]:
    slot = dict(preflight.get("slot") or {})
    slot_claim = dict(preflight.get("slot_claim") or {})
    session_id = slot.get("session_id")
    workflow_ref = workflow_ref_from_preflight(preflight)
    payload = {
        "schema_id": CONDUCTOR_EXECUTION_CONTRACT_SCHEMA_ID,
        "launch_id": slot_claim.get("launch_id"),
        "campaign_id": preflight.get("campaign_id"),
        "plan_digest": preflight.get("plan_digest"),
        "preflight_receipt_digest": preflight.get("receipt_digest"),
        "session_id": session_id,
        "project_id": PUBLIC_CONDUCTOR_PROJECT_ID,
        "public_cli_command": "openzyme-aox-cutover public-host",
        "late_bound_authority_command": (
            "openzyme-aox-cutover grant-task-authority"
        ),
        "session_create_request": (
            session_create_request(session_id) if isinstance(session_id, str) else {}
        ),
        "entry_message_request": entry_message_request(workflow_ref),
        "entry_message_count": 1,
        "runtime_drain_constraints": runtime_drain_constraints(),
        "receipt_chain_name": PUBLIC_API_RECEIPT_CHAIN_FILENAME,
        "response_name_pattern": (
            f"{PUBLIC_RESPONSE_PREFIX}<label>{PUBLIC_RESPONSE_SUFFIX}"
        ),
        "retirement_readiness_name": CONDUCTOR_RETIREMENT_READINESS_FILENAME,
        "required_final_reads": ["workspace", "events"],
    }
    if not all(
        isinstance(payload[name], str) and payload[name]
        for name in (
            "launch_id",
            "campaign_id",
            "plan_digest",
            "preflight_receipt_digest",
            "session_id",
        )
    ):
        _fail(
            "public_conductor_execution_contract_source_invalid",
            "public conductor execution contract lacks one preflight identity",
            identity="preflight",
        )
    return {**payload, "contract_digest": canonical_digest(payload)}


def publish_conductor_execution_contract(
    preflight_path: Path,
) -> tuple[Path, dict[str, Any]]:
    evidence_root, preflight = _evidence_root(preflight_path)
    contract = build_conductor_execution_contract(preflight)
    destination = evidence_root / CONDUCTOR_EXECUTION_CONTRACT_FILENAME
    publish_private_canonical_authority(
        destination,
        canonical_json_bytes(contract) + b"\n",
    )
    return destination, contract


def load_conductor_execution_contract(
    preflight_path: Path,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    evidence_root, preflight = _evidence_root(preflight_path)
    path = evidence_root / CONDUCTOR_EXECUTION_CONTRACT_FILENAME
    value = _private_canonical_object(path, identity="execution_contract")
    if value.get("schema_id") == LEGACY_CONDUCTOR_EXECUTION_CONTRACT_SCHEMA_ID:
        _fail(
            "public_conductor_execution_contract_legacy_non_admissible",
            "legacy conductor execution contracts are read-only historical evidence",
            identity="execution_contract.schema_id",
        )
    expected = build_conductor_execution_contract(preflight)
    if set(value) != _CONTRACT_FIELDS or value != expected:
        _fail(
            "public_conductor_execution_contract_invalid",
            "public conductor execution contract does not reproduce preflight",
            identity="execution_contract",
        )
    return evidence_root, value, preflight


def bound_public_response_path(
    *,
    evidence_root: Path,
    contract: Mapping[str, Any],
    response_name: str,
) -> Path:
    if _SAFE_RESPONSE_NAME.fullmatch(response_name) is None:
        _fail(
            "public_conductor_response_name_invalid",
            "public conductor response name is outside the closed label grammar",
            identity="response_name",
        )
    if (evidence_root / contract["retirement_readiness_name"]).exists():
        _fail(
            "public_conductor_state_already_sealed",
            "public conductor state is already sealed for Host retirement",
            identity="retirement_readiness",
        )
    destination = (
        evidence_root
        / f"{PUBLIC_RESPONSE_PREFIX}{response_name}{PUBLIC_RESPONSE_SUFFIX}"
    )
    try:
        destination.lstat()
    except FileNotFoundError:
        return destination
    except OSError as exc:
        raise CutoverEvidenceError(
            "public_conductor_response_target_unreadable",
            "public conductor response target cannot be prevalidated",
            details={"identity": "response_name"},
        ) from exc
    raise CutoverEvidenceError(
        "public_conductor_response_target_exists",
        "public conductor response name was already consumed",
        details={"identity": "response_name"},
    )


def public_response_path(preflight_path: Path, response_name: str) -> Path:
    evidence_root, contract, _ = load_conductor_execution_contract(preflight_path)
    return bound_public_response_path(
        evidence_root=evidence_root,
        contract=contract,
        response_name=response_name,
    )


def load_active_public_host_context(
    preflight_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    evidence_root, contract, preflight = load_conductor_execution_contract(
        preflight_path
    )
    if any(
        (evidence_root / name).exists()
        for name in (HOST_SUPERVISION_FILENAME, HOST_SUPERVISION_FATAL_FILENAME)
    ):
        _fail(
            "public_conductor_host_not_active",
            "public Host already has terminal supervision evidence",
            identity="host_supervision",
        )
    startup_value, _ = _load_canonical_object(
        evidence_root / HOST_STARTUP_FILENAME,
        identity="host_startup",
    )
    startup = _validate_startup(startup_value, preflight=preflight)
    return preflight, contract, startup, evidence_root


def _contract_workflow_ref(contract: Mapping[str, Any]) -> str:
    entry = contract.get("entry_message_request")
    skill_keys = entry.get("skill_keys") if isinstance(entry, Mapping) else None
    if not (
        isinstance(skill_keys, list)
        and len(skill_keys) == 1
        and isinstance(skill_keys[0], str)
    ):
        _fail(
            "public_conductor_execution_contract_invalid",
            "execution contract lacks one exact entry workflow binding",
            identity="execution_contract.entry_message_request.skill_keys",
        )
    return skill_keys[0]


def _current_receipts(
    *, evidence_root: Path, contract: Mapping[str, Any]
) -> list[dict[str, Any]]:
    path = evidence_root / str(contract["receipt_chain_name"])
    try:
        path.lstat()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise CutoverEvidenceError(
            "public_receipt_chain_unreadable",
            "public Host receipt chain cannot be inspected before the next action",
            details={"identity": "receipt_chain"},
        ) from exc
    receipts, _ = _load_receipt_chain(path, allow_failure_responses=True)
    return receipts


def _canonical_entry_progress(
    receipts: Sequence[Mapping[str, Any]], *, contract: Mapping[str, Any]
) -> str:
    session_id = str(contract["session_id"])
    workflow_ref = _contract_workflow_ref(contract)
    if not receipts:
        return "session_create"
    if len(receipts) == 1:
        receipt = dict(receipts[0])
        if not (
            receipt.get("sequence") == 1
            and receipt.get("method") == "POST"
            and receipt.get("route") == "/v3/sessions"
            and receipt.get("request") == session_create_request(session_id)
            and type(receipt.get("status_code")) is int
            and 200 <= receipt["status_code"] < 300
        ):
            _fail(
                "public_conductor_entry_state_invalid",
                "formal receipt chain did not begin with the canonical session",
                identity="receipt_chain[1]",
            )
        return "entry_message"
    validate_canonical_entry_receipts(
        receipts,
        session_id=session_id,
        workflow_ref=workflow_ref,
        code="public_conductor_entry_state_invalid",
    )
    return "ready"


def _closed_cli_options(
    tokens: Sequence[str],
    *,
    allowed: frozenset[str],
    repeated: frozenset[str] = frozenset(),
) -> dict[str, str | list[str]]:
    values: dict[str, str | list[str]] = {}
    cursor = 0
    while cursor < len(tokens):
        token = tokens[cursor]
        if not token.startswith("--"):
            _fail(
                "public_conductor_command_arguments_invalid",
                "formal command contains an unexpected positional argument",
                identity="host_cli_args",
            )
        raw = token[2:]
        if "=" in raw:
            name, value = raw.split("=", 1)
        else:
            name = raw
            cursor += 1
            if cursor >= len(tokens):
                _fail(
                    "public_conductor_command_arguments_invalid",
                    "formal command option lacks its value",
                    identity=f"host_cli_args.{name}",
                )
            value = tokens[cursor]
        if name not in allowed:
            _fail(
                "public_conductor_command_arguments_invalid",
                "formal command contains an option outside its public contract",
                identity=f"host_cli_args.{name}",
            )
        if name in repeated:
            current = values.setdefault(name, [])
            if not isinstance(current, list):
                raise AssertionError(name)
            current.append(value)
        elif name in values:
            _fail(
                "public_conductor_command_arguments_invalid",
                "formal command repeats a single-valued option",
                identity=f"host_cli_args.{name}",
            )
        else:
            values[name] = value
        cursor += 1
    return values


def _validate_session_create_command(
    forwarded: Sequence[str], *, contract: Mapping[str, Any]
) -> None:
    if list(forwarded[:2]) != ["sessions", "create"]:
        _fail(
            "public_conductor_session_create_required",
            "the first formal public action must create the canonical session",
            identity="host_cli_args",
        )
    options = _closed_cli_options(
        forwarded[2:], allowed=frozenset({"objective", "title"})
    )
    expected = dict(contract["session_create_request"])
    if options != {
        "objective": expected["objective"],
        "title": expected["title"],
    }:
        _fail(
            "public_conductor_session_create_invalid",
            "formal session creation differs from its source-bound contract",
            identity="host_cli_args.sessions.create",
        )


def _validate_entry_message_command(
    forwarded: Sequence[str], *, contract: Mapping[str, Any]
) -> None:
    if list(forwarded[:2]) != ["sessions", "message"]:
        _fail(
            "public_conductor_entry_message_required",
            "the second formal public action must send the canonical entry message",
            identity="host_cli_args",
        )
    options = _closed_cli_options(
        forwarded[2:],
        allowed=frozenset({"message", "skill-key", "task-id", "lane-id"}),
        repeated=frozenset({"skill-key"}),
    )
    expected = dict(contract["entry_message_request"])
    if options != {
        "message": expected["message"],
        "skill-key": list(expected["skill_keys"]),
    }:
        _fail(
            "public_conductor_entry_message_invalid",
            "formal entry message lacks its exact pinned workflow binding",
            identity="host_cli_args.sessions.message",
        )


def _validate_drain_command(forwarded: Sequence[str]) -> None:
    options = _closed_cli_options(
        forwarded[2:],
        allowed=frozenset(
            {"max-signals", "max-steps-per-agent", "idempotency-key"}
        ),
    )
    try:
        request = {
            "max_signals": int(options.get("max-signals", "3")),
            "max_steps_per_agent": int(options.get("max-steps-per-agent", "8")),
            "auto_enqueue_ready_tasks": False,
        }
    except (TypeError, ValueError) as exc:
        raise CutoverEvidenceError(
            "public_conductor_drain_request_invalid",
            "formal runtime drain bounds are not integers",
            details={"identity": "host_cli_args.runtime.drain"},
        ) from exc
    validate_bounded_drain_request(
        request,
        identity="host_cli_args.runtime.drain",
    )


def validate_public_host_command(
    *,
    contract: Mapping[str, Any],
    evidence_root: Path,
    forwarded: Sequence[str],
) -> None:
    if contract.get("schema_id") != CONDUCTOR_EXECUTION_CONTRACT_SCHEMA_ID:
        _fail(
            "public_conductor_execution_contract_legacy_non_admissible",
            "only the current conductor execution contract may issue Host actions",
            identity="execution_contract.schema_id",
        )
    if len(forwarded) < 2:
        _fail(
            "public_conductor_command_missing",
            "public-host requires one complete thin Host CLI command",
            identity="host_cli_args",
        )
    receipts = _current_receipts(evidence_root=evidence_root, contract=contract)
    progress = _canonical_entry_progress(receipts, contract=contract)
    if progress == "session_create":
        _validate_session_create_command(forwarded, contract=contract)
        return
    if progress == "entry_message":
        _validate_entry_message_command(forwarded, contract=contract)
        return
    validate_bounded_drain_receipts(
        receipts,
        session_id=str(contract["session_id"]),
    )
    action = list(forwarded[:2])
    if action in (["sessions", "create"], ["sessions", "message"]):
        _fail(
            "public_conductor_entry_already_closed",
            "formal execution permits exactly one canonical session entry",
            identity="host_cli_args",
        )
    if action == ["scientific", "authorize"]:
        _fail(
            "public_conductor_authority_command_required",
            "formal scientific authority must use grant-task-authority",
            identity="host_cli_args.scientific.authorize",
        )
    if action == ["runtime", "drain"]:
        _validate_drain_command(forwarded)


def _pregrant_terminal_sequences(
    *,
    receipts: Sequence[Mapping[str, Any]],
    envelopes: Mapping[int, Mapping[str, Any]],
    session_id: str,
) -> list[int]:
    drains = validate_bounded_drain_receipts(receipts, session_id=session_id)
    if not drains:
        _fail(
            "public_conductor_pregrant_state_invalid",
            "late-bound authority requires at least one sealed bounded drain",
            identity="receipt_chain",
        )
    statuses = [
        dict(receipt)
        for receipt in receipts
        if receipt.get("method") == "GET"
        and re.fullmatch(
            rf"/v3/sessions/{re.escape(session_id)}/runtime/commands/[^/]+",
            str(receipt.get("route") or ""),
        )
    ]
    ordered_drains = sorted(drains, key=lambda item: int(item["sequence"]))
    terminal_sequences: list[int] = []
    for index, drain in enumerate(ordered_drains):
        drain_sequence = int(drain["sequence"])
        admission = dict(envelopes.get(drain_sequence, {}).get("response") or {})
        command_id = str(admission.get("command_id") or "")
        status_route = f"/v3/sessions/{session_id}/runtime/commands/{command_id}"
        upper_bound = (
            int(ordered_drains[index + 1]["sequence"])
            if index + 1 < len(ordered_drains)
            else len(receipts) + 1
        )
        terminals = [
            status
            for status in statuses
            if drain_sequence < int(status["sequence"]) < upper_bound
            and status.get("route") == status_route
            and dict(envelopes.get(int(status["sequence"]), {}).get("response") or {}).get(
                "status"
            )
            in _TERMINAL_RUNTIME_COMMAND_STATUSES
        ]
        if not (
            admission.get("schema_version") == "runtime_command_status@1"
            and admission.get("session_id") == session_id
            and admission.get("command_type") == "runtime.drain"
            and admission.get("status_url") == status_route
            and bool(command_id)
            and len(terminals) == 1
        ):
            _fail(
                "public_conductor_pregrant_state_invalid",
                "late-bound authority requires every drain admission and terminal response",
                identity=f"receipt_chain[{drain_sequence}]",
            )
        terminal_sequence = int(terminals[0]["sequence"])
        terminal = dict(envelopes[terminal_sequence].get("response") or {})
        if not (
            terminal.get("schema_version") == "runtime_command_status@1"
            and terminal.get("session_id") == session_id
            and terminal.get("command_id") == command_id
            and terminal.get("command_type") == "runtime.drain"
            and terminal.get("status_url") == status_route
            and bool(terminal.get("completed_at"))
        ):
            _fail(
                "public_conductor_pregrant_state_invalid",
                "pre-grant terminal response does not reproduce its runtime command",
                identity=f"runtime_command:{command_id}",
            )
        terminal_sequences.append(terminal_sequence)
    return terminal_sequences


def resolve_pregrant_execution_task(
    *,
    preflight: Mapping[str, Any],
    contract: Mapping[str, Any],
    evidence_root: Path,
    task_id: str,
) -> dict[str, Any]:
    receipts = _current_receipts(evidence_root=evidence_root, contract=contract)
    session_id = str(contract["session_id"])
    validate_canonical_entry_receipts(
        receipts,
        session_id=session_id,
        workflow_ref=_contract_workflow_ref(contract),
        code="public_conductor_pregrant_state_invalid",
    )
    grant_route = f"/v3/sessions/{session_id}/scientific-attempt-authorizations"
    if any(
        receipt.get("method") == "POST" and receipt.get("route") == grant_route
        for receipt in receipts
    ):
        _fail(
            "public_conductor_authority_already_granted",
            "formal task authority is a one-use late-bound action",
            identity="receipt_chain",
        )
    envelopes, _, _ = _response_descriptors(
        evidence_root=evidence_root,
        receipts=receipts,
    )
    terminal_sequences = _pregrant_terminal_sequences(
        receipts=receipts,
        envelopes=envelopes,
        session_id=session_id,
    )
    workspace_route = f"/v3/sessions/{session_id}/workspace"
    mutation_sequences = [
        int(receipt["sequence"])
        for receipt in receipts
        if receipt.get("method") in {"POST", "PATCH", "PUT", "DELETE"}
    ]
    workspace_receipts = [
        dict(receipt)
        for receipt in receipts
        if receipt.get("method") == "GET"
        and receipt.get("route") == workspace_route
        and int(receipt["sequence"]) > max(terminal_sequences)
        and (
            not mutation_sequences
            or int(receipt["sequence"]) > max(mutation_sequences)
        )
    ]
    if len(workspace_receipts) != 1:
        _fail(
            "public_conductor_pregrant_read_invalid",
            "late-bound authority requires one sealed post-drain task read",
            identity="pregrant_workspace",
        )
    workspace = envelopes[int(workspace_receipts[0]["sequence"])].get("response")
    task_items = (
        dict(workspace.get("task_board") or {}).get("items")
        if isinstance(workspace, Mapping)
        else None
    )
    execution_tasks = [
        dict(item["task"])
        for item in (task_items or [])
        if isinstance(item, Mapping)
        and isinstance(item.get("task"), Mapping)
        and item["task"].get("kind") == "execution"
    ]
    if not (
        isinstance(workspace, Mapping)
        and dict(workspace.get("session") or {}).get("session_id") == session_id
        and len(execution_tasks) == 1
        and execution_tasks[0].get("task_id") == task_id
    ):
        _fail(
            "public_task_late_binding_invalid",
            "operator-selected task is not the unique canonical execution task",
            identity="pregrant_workspace",
        )
    slot = dict(preflight.get("slot") or {})
    if slot.get("session_id") != session_id:
        _fail(
            "public_task_late_binding_invalid",
            "preflight and public task session identities differ",
            identity="preflight.slot.session_id",
        )
    return execution_tasks[0]


def _response_descriptors(
    *,
    evidence_root: Path,
    receipts: Sequence[Mapping[str, Any]],
) -> tuple[dict[int, dict[str, Any]], dict[int, Path], list[dict[str, Any]]]:
    envelopes: dict[int, dict[str, Any]] = {}
    paths: dict[int, Path] = {}
    descriptors: list[dict[str, Any]] = []
    candidates = sorted(
        path
        for path in evidence_root.iterdir()
        if path.name.startswith(PUBLIC_RESPONSE_PREFIX)
        and path.name.endswith(PUBLIC_RESPONSE_SUFFIX)
    )
    for path in candidates:
        envelope, content = _load_response_envelope(
            path,
            identity=f"sealed_response:{path.name}",
            receipts=receipts,
        )
        receipt = dict(envelope["receipt"])
        sequence = int(receipt["sequence"])
        if sequence in envelopes:
            _fail(
                "public_conductor_response_duplicate",
                "one public receipt has multiple sealed response envelopes",
                identity=f"receipt_chain[{sequence}]",
            )
        envelopes[sequence] = envelope
        paths[sequence] = path
        descriptors.append(
            {
                "name": path.name,
                "content_digest": _content_digest(content),
                "sequence": sequence,
                "method": receipt["method"],
                "route": receipt["route"],
                "envelope_digest": envelope["envelope_digest"],
            }
        )
    expected_sequences = {int(receipt["sequence"]) for receipt in receipts}
    if set(envelopes) != expected_sequences:
        _fail(
            "public_conductor_response_set_incomplete",
            "every formal public Host response must be sealed exactly once",
            identity="sealed_responses",
        )
    return envelopes, paths, sorted(descriptors, key=lambda item: item["sequence"])


def _final_public_reads(
    *,
    receipts: Sequence[Mapping[str, Any]],
    envelopes: Mapping[int, Mapping[str, Any]],
    session_id: str,
) -> tuple[int, int, dict[str, Any], list[dict[str, Any]]]:
    workspace_route = f"/v3/sessions/{session_id}/workspace"
    event_prefix = f"/v3/sessions/{session_id}/events?replay=1&after_cursor="
    workspace_sequences = [
        int(receipt["sequence"])
        for receipt in receipts
        if receipt.get("method") == "GET"
        and receipt.get("route") == workspace_route
    ]
    event_sequences = [
        int(receipt["sequence"])
        for receipt in receipts
        if receipt.get("method") == "GET"
        and str(receipt.get("route") or "").startswith(event_prefix)
    ]
    if not workspace_sequences or not event_sequences:
        _fail(
            "public_conductor_final_reads_missing",
            "Host retirement requires final public workspace and event reads",
            identity="final_reads",
        )
    workspace_sequence = max(workspace_sequences)
    event_sequence = max(event_sequences)
    mutation_sequences = [
        int(receipt["sequence"])
        for receipt in receipts
        if receipt.get("method") in {"POST", "PATCH", "PUT", "DELETE"}
    ]
    if mutation_sequences and min(workspace_sequence, event_sequence) <= max(
        mutation_sequences
    ):
        _fail(
            "public_conductor_final_reads_stale",
            "Host retirement final reads precede a public state change",
            identity="final_reads",
        )
    workspace = envelopes[workspace_sequence].get("response")
    if not (
        isinstance(workspace, dict)
        and dict(workspace.get("session") or {}).get("session_id") == session_id
    ):
        _fail(
            "public_conductor_final_workspace_invalid",
            "final public workspace has the wrong session identity",
            identity="final_workspace",
        )
    events = _validate_events(
        envelopes[event_sequence].get("response"),
        session_id=session_id,
    )
    return workspace_sequence, event_sequence, dict(workspace), events


def _handoff_sequences(
    *,
    receipts: Sequence[Mapping[str, Any]],
    envelopes: Mapping[int, Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    session_id: str,
    final_sequence: int,
) -> set[int]:
    status_pattern = re.compile(
        rf"/v3/sessions/{re.escape(session_id)}/runtime/commands/[^/]+"
    )
    drains = validate_bounded_drain_receipts(
        receipts,
        session_id=session_id,
        code="public_conductor_handoff_drain_invalid",
    )
    statuses = [
        receipt
        for receipt in receipts
        if receipt.get("method") == "GET"
        and status_pattern.fullmatch(str(receipt.get("route") or ""))
    ]
    grant_receipts = [
        receipt
        for receipt in receipts
        if receipt.get("method") == "POST"
        and receipt.get("route")
        == f"/v3/sessions/{session_id}/scientific-attempt-authorizations"
    ]
    if not drains:
        if statuses or grant_receipts:
            _fail(
                "public_conductor_handoff_sequence_invalid",
                "terminal status or late-bound authority requires a prior bounded drain",
                identity="runtime_handoffs",
            )
        return set()
    candidate_sequences = {
        int(receipt["sequence"]) for receipt in (*drains, *statuses)
    }
    handoff_envelopes = [
        dict(envelopes[sequence]) for sequence in sorted(candidate_sequences)
    ]
    command_handoffs, _, used = _validate_runtime_command_handoffs(
        records=receipts,
        drains=drains,
        statuses=statuses,
        handoff_envelopes=handoff_envelopes,
        events=events,
        session_id=session_id,
        final_sequence=final_sequence,
    )
    if grant_receipts:
        first_terminal_sequence = int(
            dict(command_handoffs[0]["terminal_receipt"])["sequence"]
        )
        first_grant_sequence = min(
            int(receipt["sequence"]) for receipt in grant_receipts
        )
        pregrant_workspace = [
            int(receipt["sequence"])
            for receipt in receipts
            if receipt.get("method") == "GET"
            and receipt.get("route") == f"/v3/sessions/{session_id}/workspace"
            and first_terminal_sequence
            < int(receipt["sequence"])
            < first_grant_sequence
        ]
        if len(pregrant_workspace) != 1:
            _fail(
                "public_conductor_pregrant_read_invalid",
                "late-bound authority requires one sealed pre-grant task read",
                identity="pregrant_workspace",
            )
        used.add(pregrant_workspace[0])
    return used


def _build_retirement_readiness(
    preflight_path: Path,
    *,
    sealed_at: str,
    require_active_host: bool,
) -> dict[str, Any]:
    if require_active_host:
        preflight, contract, startup, evidence_root = (
            load_active_public_host_context(preflight_path)
        )
    else:
        evidence_root, contract, preflight = load_conductor_execution_contract(
            preflight_path
        )
        startup_value, _ = _load_canonical_object(
            evidence_root / HOST_STARTUP_FILENAME,
            identity="host_startup",
        )
        startup = _validate_startup(startup_value, preflight=preflight)
    receipt_chain_path = evidence_root / str(contract["receipt_chain_name"])
    receipts, receipt_bytes = _load_receipt_chain(
        receipt_chain_path,
        allow_failure_responses=True,
    )
    session_id = str(contract["session_id"])
    validate_canonical_entry_receipts(
        receipts,
        session_id=session_id,
        workflow_ref=_contract_workflow_ref(contract),
        code="public_conductor_retirement_entry_invalid",
    )
    validate_bounded_drain_receipts(
        receipts,
        session_id=session_id,
        code="public_conductor_retirement_drain_invalid",
    )
    envelopes, response_paths, response_descriptors = _response_descriptors(
        evidence_root=evidence_root,
        receipts=receipts,
    )
    workspace_sequence, event_sequence, workspace, events = _final_public_reads(
        receipts=receipts,
        envelopes=envelopes,
        session_id=session_id,
    )
    handoff_sequences = _handoff_sequences(
        receipts=receipts,
        envelopes=envelopes,
        events=events,
        session_id=session_id,
        final_sequence=min(workspace_sequence, event_sequence),
    )
    attempt_state = workspace.get("scientific_attempts")
    attempt_count = (
        attempt_state.get("attempt_count")
        if isinstance(attempt_state, dict)
        else None
    )
    attempts = attempt_state.get("attempts") if isinstance(attempt_state, dict) else None
    if not (
        type(attempt_count) is int
        and attempt_count in {0, 1}
        and isinstance(attempts, list)
        and len(attempts) == attempt_count
    ):
        _fail(
            "public_conductor_attempt_state_invalid",
            "final workspace does not expose one closed formal attempt cardinality",
            identity="final_workspace.scientific_attempts",
        )
    evidence_sequences = [
        int(receipt["sequence"])
        for receipt in receipts
        if receipt.get("method") == "GET"
        and _EVIDENCE_ROUTE.fullmatch(str(receipt.get("route") or ""))
    ]
    if attempt_count == 0 and evidence_sequences:
        _fail(
            "public_conductor_evidence_mode_invalid",
            "zero-attempt retirement must not contain a scientific evidence export",
            identity="evidence_response",
        )
    if attempt_count == 1 and len(evidence_sequences) != 1:
        _fail(
            "public_conductor_evidence_mode_invalid",
            "attempt retirement requires one sealed scientific evidence export",
            identity="evidence_response",
        )
    evidence_sequence = evidence_sequences[0] if evidence_sequences else None
    payload = {
        "schema_id": CONDUCTOR_RETIREMENT_READINESS_SCHEMA_ID,
        "launch_id": contract["launch_id"],
        "campaign_id": contract["campaign_id"],
        "plan_digest": contract["plan_digest"],
        "preflight_receipt_digest": contract["preflight_receipt_digest"],
        "execution_contract_digest": contract["contract_digest"],
        "host_startup_receipt_digest": startup["receipt_digest"],
        "session_id": session_id,
        "closure_mode": "slot_failure" if attempt_count == 0 else "attempt",
        "scientific_attempt_count": attempt_count,
        "receipt_chain": {
            "name": receipt_chain_path.name,
            "content_digest": _content_digest(receipt_bytes),
            "record_count": len(receipts),
            "last_sequence": len(receipts),
        },
        "sealed_responses": response_descriptors,
        "final_workspace_response_name": response_paths[
            workspace_sequence
        ].name,
        "final_event_response_name": response_paths[event_sequence].name,
        "handoff_response_names": [
            response_paths[sequence].name for sequence in sorted(handoff_sequences)
        ],
        "evidence_response_name": (
            None if evidence_sequence is None else response_paths[evidence_sequence].name
        ),
        "sealed_at": sealed_at,
    }
    return {**payload, "receipt_digest": canonical_digest(payload)}


def seal_conductor_retirement_readiness(
    preflight_path: Path,
) -> tuple[Path, dict[str, Any]]:
    evidence_root, _, _ = load_conductor_execution_contract(preflight_path)
    destination = evidence_root / CONDUCTOR_RETIREMENT_READINESS_FILENAME
    readiness = _build_retirement_readiness(
        preflight_path,
        sealed_at=datetime.now(UTC).isoformat(),
        require_active_host=True,
    )
    publish_private_canonical_authority(
        destination,
        canonical_json_bytes(readiness) + b"\n",
    )
    return destination, readiness


def load_conductor_retirement_readiness(
    readiness_path: Path,
    *,
    preflight_path: Path,
) -> dict[str, Any]:
    evidence_root, _, _ = load_conductor_execution_contract(preflight_path)
    path = readiness_path.expanduser().resolve(strict=True)
    if path != evidence_root / CONDUCTOR_RETIREMENT_READINESS_FILENAME:
        _fail(
            "public_conductor_retirement_readiness_path_invalid",
            "retirement readiness must be the canonical evidence-root sibling",
            identity="retirement_readiness",
        )
    value = _private_canonical_object(path, identity="retirement_readiness")
    if not (
        set(value) == _READINESS_FIELDS
        and isinstance(value.get("receipt_chain"), dict)
        and set(value["receipt_chain"]) == _RECEIPT_CHAIN_FIELDS
        and isinstance(value.get("sealed_responses"), list)
        and all(
            isinstance(item, dict) and set(item) == _RESPONSE_DESCRIPTOR_FIELDS
            for item in value["sealed_responses"]
        )
        and isinstance(value.get("handoff_response_names"), list)
        and value.get("closure_mode") in {"attempt", "slot_failure"}
    ):
        _fail(
            "public_conductor_retirement_readiness_invalid",
            "retirement readiness is not one closed execution receipt",
            identity="retirement_readiness",
        )
    expected = _build_retirement_readiness(
        preflight_path,
        sealed_at=str(value.get("sealed_at") or ""),
        require_active_host=False,
    )
    if value != expected:
        _fail(
            "public_conductor_retirement_readiness_drift",
            "retirement readiness sources changed after sealing",
            identity="retirement_readiness",
        )
    return value


def retirement_readiness_sources(
    readiness_path: Path,
    *,
    preflight_path: Path,
) -> dict[str, Any]:
    value = load_conductor_retirement_readiness(
        readiness_path,
        preflight_path=preflight_path,
    )
    evidence_root = readiness_path.expanduser().resolve(strict=True).parent
    descriptor_names = {
        str(item["name"]) for item in value["sealed_responses"]
    }

    def source(name: object, *, identity: str) -> Path:
        if not isinstance(name, str) or name not in descriptor_names:
            _fail(
                "public_conductor_retirement_source_invalid",
                "retirement readiness references an unknown sealed response",
                identity=identity,
            )
        return evidence_root / name

    return {
        "readiness": value,
        "receipt_chain": evidence_root / value["receipt_chain"]["name"],
        "workspace": source(
            value["final_workspace_response_name"],
            identity="final_workspace",
        ),
        "events": source(
            value["final_event_response_name"],
            identity="final_events",
        ),
        "handoffs": [
            source(name, identity="handoff_response")
            for name in value["handoff_response_names"]
        ],
        "evidence": (
            None
            if value["evidence_response_name"] is None
            else source(value["evidence_response_name"], identity="evidence_response")
        ),
    }
