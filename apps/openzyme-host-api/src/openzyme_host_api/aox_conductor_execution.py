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
from .aox_public_conductor_bundle import _load_canonical_object
from .aox_public_conductor_bundle import _load_receipt_chain
from .aox_public_conductor_bundle import _load_response_envelope
from .aox_public_conductor_bundle import _validate_events
from .aox_public_conductor_bundle import _validate_runtime_command_handoffs
from .aox_public_conductor_bundle import _validate_startup


CONDUCTOR_EXECUTION_CONTRACT_SCHEMA_ID = (
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
PUBLIC_CONDUCTOR_PROJECT_ID = "aox-blank-world-cutover"

_CONTRACT_FIELDS = {
    "schema_id",
    "launch_id",
    "campaign_id",
    "plan_digest",
    "preflight_receipt_digest",
    "session_id",
    "project_id",
    "public_cli_command",
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
    payload = {
        "schema_id": CONDUCTOR_EXECUTION_CONTRACT_SCHEMA_ID,
        "launch_id": slot_claim.get("launch_id"),
        "campaign_id": preflight.get("campaign_id"),
        "plan_digest": preflight.get("plan_digest"),
        "preflight_receipt_digest": preflight.get("receipt_digest"),
        "session_id": slot.get("session_id"),
        "project_id": PUBLIC_CONDUCTOR_PROJECT_ID,
        "public_cli_command": "openzyme-aox-cutover public-host",
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
    expected = build_conductor_execution_contract(preflight)
    if set(value) != _CONTRACT_FIELDS or value != expected:
        _fail(
            "public_conductor_execution_contract_invalid",
            "public conductor execution contract does not reproduce preflight",
            identity="execution_contract",
        )
    return evidence_root, value, preflight


def public_response_path(preflight_path: Path, response_name: str) -> Path:
    evidence_root, contract, _ = load_conductor_execution_contract(preflight_path)
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
    drain_route = f"/v3/sessions/{session_id}/runtime/drain"
    status_pattern = re.compile(
        rf"/v3/sessions/{re.escape(session_id)}/runtime/commands/[^/]+"
    )
    drains = [
        receipt
        for receipt in receipts
        if receipt.get("method") == "POST" and receipt.get("route") == drain_route
    ]
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
    envelopes, response_paths, response_descriptors = _response_descriptors(
        evidence_root=evidence_root,
        receipts=receipts,
    )
    session_id = str(contract["session_id"])
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
