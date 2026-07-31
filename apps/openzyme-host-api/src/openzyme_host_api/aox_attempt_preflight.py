from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
import stat
from typing import Any

from .aox_authority_storage import publish_private_canonical_authority
from .aox_attempt_authority import AOX_ATTEMPT_AUTHORITY_SLOT_CLAIM_SCHEMA_ID
from .aox_cutover_evidence import (
    BLANK_WORLD_ROOT_PROOF_SCHEMA_ID,
    BlankWorldRoots,
    CutoverEvidenceError,
    canonical_digest,
    canonical_json_bytes,
)
from .aox_live_run_class import AoxLiveRunClass


ATTEMPT_PREFLIGHT_SCHEMA_ID = "aox_attempt_preflight@2"
ATTEMPT_PREFLIGHT_FILENAME = "aox-attempt-preflight.json"
ATTEMPT_SLOT_CLAIM_FILENAME = "aox-attempt-slot-claim.json"
_PREFLIGHT_FIELDS = {
    "schema_id",
    "run_class",
    "campaign_id",
    "plan_digest",
    "consumption_digest",
    "identity_digest",
    "allowed_prerequisite_digest",
    "architecture_qualification_digest",
    "effective_config",
    "slot",
    "slot_claim",
    "root_proof",
    "created_at",
    "receipt_digest",
}
_ROOT_PROOF_FIELDS = {
    "schema_id", "architecture_qualification", "attempt_id", "attempt_kind",
    "root_identity", "root_names", "initial_entries", "sqlite_preexisting",
    "provider_cache_mode", "evidence_cache_reuse", "hpc_workspace_label",
    "allowed_prerequisite_digest", "allowed_prerequisites",
}
_ROOT_NAMES = {
    "artifact": "artifacts", "blob": "blobs", "sandbox": "sandboxes",
    "hpc": "hpc-workspace", "evidence": "evidence",
}
_INITIAL_ENTRIES = {"sqlite": 0, **dict.fromkeys(_ROOT_NAMES, 0)}


def _reject(code: str, message: str, **details: object) -> None:
    raise CutoverEvidenceError(code, message, details=details)


def build_attempt_preflight_receipt(
    *,
    identity: Mapping[str, object],
    allowed_prerequisites: Mapping[str, object],
    architecture_qualification: Mapping[str, object],
    effective_config: Mapping[str, object],
    authority_plan: Mapping[str, object],
    authority_consumption: Mapping[str, object],
    slot: Mapping[str, object],
    slot_claim: Mapping[str, object],
    roots: BlankWorldRoots,
) -> dict[str, Any]:
    slots = authority_plan.get("slots")
    if not all(
        (
            isinstance(slots, list),
            isinstance(slots, list) and dict(slot) in slots,
            slot.get("attempt_id") == roots.attempt_id,
            slot.get("attempt_kind") == roots.attempt_kind,
            authority_consumption.get("plan_digest")
            == authority_plan.get("plan_digest"),
            roots.proof.get("allowed_prerequisite_digest")
            == canonical_digest(dict(allowed_prerequisites)),
            roots.proof.get("architecture_qualification")
            == dict(architecture_qualification),
            slot_claim.get("schema_id") == AOX_ATTEMPT_AUTHORITY_SLOT_CLAIM_SCHEMA_ID,
            slot_claim.get("campaign_id") == authority_plan.get("campaign_id"),
            slot_claim.get("plan_digest") == authority_plan.get("plan_digest"),
            slot_claim.get("consumption_digest")
            == canonical_digest(dict(authority_consumption)),
            slot_claim.get("ordinal") == slot.get("ordinal"),
            all(
                slot_claim.get(key) == slot.get(key)
                for key in (
                    "attempt_kind",
                    "attempt_id",
                    "session_id",
                    "task_id",
                    "lane_id",
                    "envelope_id",
                    "request_digest",
                )
            ),
            slot_claim.get("claim_digest")
            == canonical_digest(
                {
                    key: value
                    for key, value in dict(slot_claim).items()
                    if key != "claim_digest"
                }
            ),
        )
    ):
        _reject(
            "attempt_preflight_source_mismatch",
            "preflight sources do not bind one slot",
        )
    payload: dict[str, Any] = {
        "schema_id": ATTEMPT_PREFLIGHT_SCHEMA_ID,
        "run_class": AoxLiveRunClass.FORMAL_ACCEPTANCE.value,
        "campaign_id": authority_plan["campaign_id"],
        "plan_digest": authority_plan["plan_digest"],
        "consumption_digest": canonical_digest(dict(authority_consumption)),
        "identity_digest": canonical_digest(dict(identity)),
        "allowed_prerequisite_digest": canonical_digest(dict(allowed_prerequisites)),
        "architecture_qualification_digest": canonical_digest(
            dict(architecture_qualification)
        ),
        "effective_config": dict(effective_config),
        "slot": dict(slot),
        "slot_claim": dict(slot_claim),
        "root_proof": dict(roots.proof),
        "created_at": datetime.now(UTC).isoformat(),
    }
    return {**payload, "receipt_digest": canonical_digest(payload)}


def publish_attempt_preflight_receipt(
    receipt: Mapping[str, object], *, roots: BlankWorldRoots
) -> Path:
    path = roots.evidence_root / ATTEMPT_PREFLIGHT_FILENAME
    publish_private_canonical_authority(
        path, canonical_json_bytes(dict(receipt)) + b"\n"
    )
    return path


def publish_attempt_slot_claim_evidence(
    slot_claim: Mapping[str, object], *, roots: BlankWorldRoots
) -> Path:
    path = roots.evidence_root / ATTEMPT_SLOT_CLAIM_FILENAME
    publish_private_canonical_authority(
        path, canonical_json_bytes(dict(slot_claim)) + b"\n"
    )
    return path


def _load_canonical_private_file(path: Path) -> dict[str, Any]:
    try:
        metadata, content = path.lstat(), path.read_bytes()
        value = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CutoverEvidenceError(
            "attempt_preflight_unreadable",
            "attempt preflight receipt is not readable canonical JSON",
        ) from exc
    if not all((
        stat.S_ISREG(metadata.st_mode),
        not stat.S_ISLNK(metadata.st_mode),
        stat.S_IMODE(metadata.st_mode) & 0o077 == 0,
        isinstance(value, dict),
        isinstance(value, dict) and content == canonical_json_bytes(value) + b"\n",
    )):
        _reject("attempt_preflight_invalid", "preflight receipt is unsafe or noncanonical")
    return dict(value)


def load_attempt_preflight_receipt(
    path: Path, *, require_unstarted: bool = False
) -> dict[str, Any]:
    value = _load_canonical_private_file(path)
    slot, proof, slot_claim = (
        value.get("slot"),
        value.get("root_proof"),
        value.get("slot_claim"),
    )
    attempt_root = path.parent.parent
    payload = {key: item for key, item in value.items() if key != "receipt_digest"}
    structural = all(
        (
            set(value) == _PREFLIGHT_FIELDS,
            value.get("schema_id") == ATTEMPT_PREFLIGHT_SCHEMA_ID,
            value.get("run_class") == AoxLiveRunClass.FORMAL_ACCEPTANCE.value,
            path.name == ATTEMPT_PREFLIGHT_FILENAME,
            path.parent.name == "evidence",
            path.resolve() == path,
            isinstance(slot, dict),
            isinstance(proof, dict),
            isinstance(slot_claim, dict),
        )
    )
    if not structural:
        _reject(
            "attempt_preflight_invalid", "preflight receipt is unsafe or noncanonical"
        )
    assert (
        isinstance(slot, dict)
        and isinstance(proof, dict)
        and isinstance(slot_claim, dict)
    )
    proof_valid = all(
        (
            set(proof) == _ROOT_PROOF_FIELDS,
            proof.get("schema_id") == BLANK_WORLD_ROOT_PROOF_SCHEMA_ID,
            isinstance(proof.get("architecture_qualification"), dict),
            isinstance(proof.get("allowed_prerequisites"), dict),
            proof.get("root_names") == _ROOT_NAMES,
            proof.get("initial_entries") == _INITIAL_ENTRIES,
            proof.get("sqlite_preexisting") is False,
            proof.get("provider_cache_mode") == "bypass",
            proof.get("evidence_cache_reuse") is False,
            bool(proof.get("hpc_workspace_label")),
            str(proof.get("root_identity") or "").startswith("sha256:"),
            value.get("receipt_digest") == canonical_digest(payload),
            slot.get("attempt_id") == attempt_root.name == proof.get("attempt_id"),
            slot.get("attempt_kind") == proof.get("attempt_kind"),
            value.get("allowed_prerequisite_digest")
            == proof.get("allowed_prerequisite_digest"),
            value.get("architecture_qualification_digest")
            == canonical_digest(dict(proof.get("architecture_qualification") or {})),
            canonical_digest(dict(value.get("effective_config") or {}))
            == dict(proof.get("allowed_prerequisites") or {}).get("config_digest"),
            slot_claim.get("schema_id") == AOX_ATTEMPT_AUTHORITY_SLOT_CLAIM_SCHEMA_ID,
            slot_claim.get("campaign_id") == value.get("campaign_id"),
            slot_claim.get("plan_digest") == value.get("plan_digest"),
            slot_claim.get("consumption_digest") == value.get("consumption_digest"),
            slot_claim.get("ordinal") == slot.get("ordinal"),
            all(
                slot_claim.get(key) == slot.get(key)
                for key in (
                    "attempt_kind",
                    "attempt_id",
                    "session_id",
                    "task_id",
                    "lane_id",
                    "envelope_id",
                    "request_digest",
                )
            ),
            slot_claim.get("claim_digest")
            == canonical_digest(
                {key: item for key, item in slot_claim.items() if key != "claim_digest"}
            ),
        )
    )
    if not proof_valid:
        _reject("attempt_preflight_identity_mismatch", "preflight identity does not reproduce")
    resolved_attempt = attempt_root.resolve(strict=True)
    metadata = attempt_root.lstat()
    if not all((
        stat.S_ISDIR(metadata.st_mode),
        not attempt_root.is_symlink(),
        stat.S_IMODE(metadata.st_mode) & 0o077 == 0,
        resolved_attempt == attempt_root,
    )):
        _reject("attempt_preflight_root_invalid", "attempt root is not one private real directory")
    roots = {kind: attempt_root / name for kind, name in _ROOT_NAMES.items()}
    for kind, root in roots.items():
        metadata, resolved = root.lstat(), root.resolve(strict=True)
        if not all((
            stat.S_ISDIR(metadata.st_mode),
            not root.is_symlink(),
            stat.S_IMODE(metadata.st_mode) & 0o077 == 0,
            resolved_attempt in resolved.parents,
        )):
            _reject("attempt_preflight_root_invalid", "root topology drifted", root_kind=kind)
    if require_unstarted:
        nonempty = {
            kind: sorted(item.name for item in root.iterdir())
            for kind, root in roots.items()
            if kind != "evidence" and any(root.iterdir())
        }
        evidence_entries = sorted(item.name for item in roots["evidence"].iterdir())
        if (
            (attempt_root / "control-plane.sqlite3").exists()
            or nonempty
            or (
                evidence_entries
                != sorted([ATTEMPT_PREFLIGHT_FILENAME, ATTEMPT_SLOT_CLAIM_FILENAME])
            )
        ):
            _reject("attempt_preflight_already_started", "attempt root already started", nonempty_roots=nonempty)
    return value


__all__ = [
    "ATTEMPT_PREFLIGHT_FILENAME",
    "ATTEMPT_PREFLIGHT_SCHEMA_ID",
    "ATTEMPT_SLOT_CLAIM_FILENAME",
    "build_attempt_preflight_receipt",
    "load_attempt_preflight_receipt",
    "publish_attempt_preflight_receipt",
    "publish_attempt_slot_claim_evidence",
]
