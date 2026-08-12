from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .aox_attempt_preflight import (
    ATTEMPT_CONDUCTOR_CONTRACT_FILENAME,
    ATTEMPT_PREFLIGHT_FILENAME,
    ATTEMPT_SLOT_CLAIM_FILENAME,
    ATTEMPT_START_CLAIM_FILENAME,
    ATTEMPT_START_CLAIM_SCHEMA_ID,
    load_attempt_launch_profile,
    load_attempt_preflight_receipt,
    load_private_canonical_attempt_source,
)
from .aox_authority_storage import publish_private_canonical_authority
from .aox_cutover_evidence import (
    CutoverEvidenceError,
    canonical_digest,
    canonical_json_bytes,
    safe_micu_ledger_snapshot,
    validate_safe_micu_ledger_snapshot,
)
from .aox_launch_profile import AOX_CUTOVER_LAUNCH_PROFILE_FILENAME


_INITIAL_SOURCE_NAMES = frozenset(
    {
        AOX_CUTOVER_LAUNCH_PROFILE_FILENAME,
        ATTEMPT_CONDUCTOR_CONTRACT_FILENAME,
        ATTEMPT_PREFLIGHT_FILENAME,
        ATTEMPT_SLOT_CLAIM_FILENAME,
    }
)
_CLAIM_FIELDS = set(
    "schema_id launch_id preflight_receipt_digest slot_claim_digest "
    "launch_profile_digest execution_contract_digest "
    "ledger_identity_digest micu_before micu_before_digest process_epoch claimed_at "
    "claim_digest".split()
)


def _fail(code: str, message: str, **details: object) -> None:
    raise CutoverEvidenceError(code, message, details=details)


def _validate_clean_root(preflight_path: Path, *, allowed_evidence: frozenset[str]) -> None:
    root = preflight_path.parent.parent
    if root.is_symlink() or not root.is_dir():
        _fail("attempt_prestart_root_invalid", "attempt root is not one real directory",
              identity="attempt_root")
    expected_roots = {"artifacts", "blobs", "evidence", "hpc-workspace", "sandboxes"}
    root_entries = {item.name for item in root.iterdir()}
    if root_entries != expected_roots:
        _fail("attempt_prestart_contamination",
              "attempt root contains an unexpected lifecycle entry",
              entries=sorted(root_entries - expected_roots))
    for name in ("artifacts", "blobs", "hpc-workspace", "sandboxes"):
        path = root / name
        if path.is_symlink() or not path.is_dir() or any(path.iterdir()):
            _fail("attempt_prestart_contamination",
                  "attempt effect root is not empty and private", root=name)
    evidence = root / "evidence"
    if evidence.is_symlink() or not evidence.is_dir():
        _fail("attempt_prestart_root_invalid",
              "attempt evidence root is not one real directory", identity="evidence")
    names = {item.name for item in evidence.iterdir()}
    if names != allowed_evidence or any(
        item.is_symlink() or not item.is_file() for item in evidence.iterdir()
    ):
        _fail("attempt_prestart_contamination",
              "attempt evidence does not match the closed lifecycle phase",
              entries=sorted(names))


def _load_bound_execution_contract(
    preflight_path: Path, preflight: Mapping[str, Any]
) -> dict[str, Any]:
    from .aox_conductor_execution import load_conductor_execution_contract

    _, value, loaded_preflight = load_conductor_execution_contract(preflight_path)
    if loaded_preflight != preflight:
        _fail("attempt_prestart_source_invalid", "execution contract is not bound",
              identity="execution_contract")
    return value


def _load_bound_ledger_path(
    preflight_path: Path, preflight: Mapping[str, Any]
) -> Path:
    slot_claim = load_private_canonical_attempt_source(
        preflight_path.parent / ATTEMPT_SLOT_CLAIM_FILENAME
    )
    if slot_claim != preflight.get("slot_claim"):
        _fail("attempt_prestart_source_invalid",
              "slot claim differs from its preflight binding", identity="slot_claim")
    profile = load_attempt_launch_profile(preflight_path)
    return Path(str(profile["ledger_path"])).expanduser().resolve()


def build_attempt_start_claim(
    *,
    preflight: Mapping[str, Any],
    execution_contract: Mapping[str, Any],
    micu_before: Mapping[str, Any],
    process_epoch: str,
    claimed_at: str | None = None,
) -> dict[str, Any]:
    slot_claim = dict(preflight["slot_claim"])
    before = validate_safe_micu_ledger_snapshot(micu_before)
    effective_claimed_at = claimed_at or datetime.now(UTC).isoformat()
    try:
        claimed_timestamp = datetime.fromisoformat(effective_claimed_at)
    except ValueError:
        claimed_timestamp = None
    if not process_epoch or claimed_timestamp is None or claimed_timestamp.tzinfo is None:
        _fail("attempt_start_claim_invalid",
              "attempt start claim requires an epoch and aware timestamp",
              identity="attempt_start_claim")
    payload = {
        "schema_id": ATTEMPT_START_CLAIM_SCHEMA_ID,
        "launch_id": slot_claim["launch_id"],
        "preflight_receipt_digest": preflight["receipt_digest"],
        "slot_claim_digest": slot_claim["claim_digest"],
        "launch_profile_digest": preflight["launch_profile_digest"],
        "execution_contract_digest": execution_contract["contract_digest"],
        "ledger_identity_digest": before["ledger_identity_digest"],
        "micu_before": before,
        "micu_before_digest": canonical_digest(before),
        "process_epoch": process_epoch,
        "claimed_at": effective_claimed_at,
    }
    return {**payload, "claim_digest": canonical_digest(payload)}


def validate_attempt_start_claim(
    path: Path,
    *,
    preflight: Mapping[str, Any],
    execution_contract: Mapping[str, Any],
    process_epoch: str | None = None,
    require_phase_closed: bool = False,
) -> dict[str, Any]:
    value = load_private_canonical_attempt_source(path)
    before = value.get("micu_before")
    try:
        normalized_before = validate_safe_micu_ledger_snapshot(
            before if isinstance(before, Mapping) else {}
        )
    except CutoverEvidenceError as exc:
        raise CutoverEvidenceError(
            "attempt_start_claim_invalid", "attempt start claim contains an invalid MICU baseline",
            details={"identity": "micu_before"}) from exc
    declared_epoch, claimed_at = value.get("process_epoch"), value.get("claimed_at")
    try:
        claimed_timestamp = datetime.fromisoformat(str(claimed_at or ""))
    except ValueError:
        claimed_timestamp = None
    expected = build_attempt_start_claim(
        preflight=preflight,
        execution_contract=execution_contract,
        micu_before=normalized_before,
        process_epoch=str(declared_epoch or ""),
        claimed_at=str(claimed_at or ""),
    )
    if not all((
        set(value) == _CLAIM_FIELDS,
        value.get("schema_id") == ATTEMPT_START_CLAIM_SCHEMA_ID,
        path.name == ATTEMPT_START_CLAIM_FILENAME,
        path.resolve() == path,
        isinstance(declared_epoch, str) and bool(declared_epoch),
        process_epoch is None or declared_epoch == process_epoch,
        claimed_timestamp is not None and claimed_timestamp.tzinfo is not None,
        value == expected,
    )):
        _fail("attempt_start_claim_invalid",
              "attempt start claim does not reproduce its source bindings",
              identity="attempt_start_claim")
    if require_phase_closed:
        _validate_clean_root(
            path.parent / ATTEMPT_PREFLIGHT_FILENAME,
            allowed_evidence=_INITIAL_SOURCE_NAMES | {ATTEMPT_START_CLAIM_FILENAME},
        )
    return value


def load_bound_attempt_start_claim(
    preflight_path: Path,
    *,
    process_epoch: str | None = None,
    require_phase_closed: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = preflight_path.expanduser().resolve(strict=True)
    preflight = load_attempt_preflight_receipt(path)
    contract = _load_bound_execution_contract(path, preflight)
    claim = validate_attempt_start_claim(
        path.parent / ATTEMPT_START_CLAIM_FILENAME, preflight=preflight,
        execution_contract=contract, process_epoch=process_epoch,
        require_phase_closed=require_phase_closed)
    return preflight, claim


def claim_attempt_start(
    preflight_path: Path,
    *,
    process_epoch: str,
) -> tuple[Path, dict[str, Any], Path]:
    path = preflight_path.expanduser().resolve(strict=True)
    preflight = load_attempt_preflight_receipt(path)
    execution_contract = _load_bound_execution_contract(path, preflight)
    claim_path = path.parent / ATTEMPT_START_CLAIM_FILENAME
    if claim_path.exists() or claim_path.is_symlink():
        try:
            validate_attempt_start_claim(
                claim_path,
                preflight=preflight,
                execution_contract=execution_contract,
            )
        except CutoverEvidenceError as exc:
            raise CutoverEvidenceError(
                "attempt_start_claim_invalid", "existing attempt start claim is not reusable",
                details={"identity": "attempt_start_claim"}) from exc
        _fail("attempt_start_already_claimed", "attempt start has already been claimed",
              identity="attempt_start_claim")
    _validate_clean_root(path, allowed_evidence=_INITIAL_SOURCE_NAMES)
    ledger_path = _load_bound_ledger_path(path, preflight)
    before = safe_micu_ledger_snapshot(ledger_path)
    claim = build_attempt_start_claim(
        preflight=preflight,
        execution_contract=execution_contract,
        micu_before=before,
        process_epoch=process_epoch,
    )
    try:
        publish_private_canonical_authority(claim_path, canonical_json_bytes(claim) + b"\n")
    except CutoverEvidenceError:
        if claim_path.exists() and not claim_path.is_symlink():
            try:
                validate_attempt_start_claim(
                    claim_path,
                    preflight=preflight,
                    execution_contract=execution_contract,
                )
            except CutoverEvidenceError:
                pass
            else:
                _fail("attempt_start_already_claimed",
                      "attempt start was claimed by another contender",
                      identity="attempt_start_claim")
        raise
    current = safe_micu_ledger_snapshot(ledger_path)
    if current != before:
        _fail("attempt_micu_ledger_drift", "MICU ledger changed across the atomic start claim",
              identity="micu_ledger")
    validated = validate_attempt_start_claim(
        claim_path,
        preflight=preflight,
        execution_contract=execution_contract,
        process_epoch=process_epoch,
        require_phase_closed=True,
    )
    return claim_path, validated, ledger_path
