from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC
from datetime import datetime
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any

from openzyme_core import scientific_attempt_authorization_identity

from .aox_cutover_evidence import canonical_digest
from .aox_cutover_evidence import canonical_json_bytes
from .aox_cutover_evidence import CutoverEvidenceError
from .aox_scientific_contract import (
    AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST,
)
from .aox_scientific_contract import AOX_SELECTED_CHAIN_WORKFLOW_ID


AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID = "aox_live_attempt_authority_plan@1"
AOX_ATTEMPT_AUTHORITY_CONSUMPTION_SCHEMA_ID = (
    "aox_live_attempt_authority_consumption@1"
)
AOX_ATTEMPT_AUTHORITY_GRANTOR_REF = "user:local-dev"

_PLAN_FIELDS = frozenset(
    {
        "schema_id",
        "campaign_id",
        "identity_digest",
        "allowed_prerequisite_digest",
        "architecture_qualification_digest",
        "issued_at",
        "expires_at",
        "slots",
        "plan_digest",
    }
)
_SLOT_FIELDS = frozenset(
    {
        "ordinal",
        "attempt_kind",
        "attempt_id",
        "session_id",
        "task_id",
        "lane_id",
        "scope",
        "authority_request",
        "envelope_id",
        "request_digest",
    }
)
_ATTEMPT_ID_PATTERN = re.compile(r"^(positive|fault)-[a-f0-9]{32}$")
_CAMPAIGN_ID_PATTERN = re.compile(r"^aox_campaign_[a-f0-9]{24}$")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_timestamp(
    value: object,
    *,
    code: str,
    label: str,
) -> datetime:
    if not isinstance(value, str) or not value:
        raise CutoverEvidenceError(
            code,
            f"attempt authority {label} must be a non-empty ISO-8601 timestamp",
        )
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CutoverEvidenceError(
            code,
            f"attempt authority {label} is not valid ISO-8601",
        ) from exc
    if parsed.tzinfo is None:
        raise CutoverEvidenceError(
            code,
            f"attempt authority {label} must include a timezone",
        )
    return parsed.astimezone(UTC)


def _parse_future_timestamp(value: object) -> datetime:
    parsed = _parse_timestamp(
        value,
        code="attempt_authority_expiry_invalid",
        label="expiry",
    )
    if parsed <= datetime.now(UTC):
        raise CutoverEvidenceError(
            "attempt_authority_expired",
            "attempt authority plan has expired",
        )
    return parsed


def _attempt_suffix(attempt_id: str) -> str:
    return attempt_id.replace("-", "_")


def build_aox_attempt_authority_plan(
    *,
    identity: Mapping[str, object],
    allowed_prerequisites: Mapping[str, object],
    architecture_qualification: Mapping[str, object],
    expires_at: str,
    max_micu_per_attempt: int,
    max_cost_microunits_per_attempt: int,
    max_wall_time_seconds_per_attempt: int,
    issued_at: str | None = None,
) -> dict[str, Any]:
    """Build a reviewable three-slot grant without creating any attempt root."""

    expiry = _parse_future_timestamp(expires_at)
    effective_issued_at = issued_at or _utc_now()
    issued = _parse_timestamp(
        effective_issued_at,
        code="attempt_authority_issued_at_invalid",
        label="issued_at",
    )
    if issued > expiry:
        raise CutoverEvidenceError(
            "attempt_authority_time_order_invalid",
            "attempt authority issued_at must not follow expires_at",
        )
    if issued > datetime.now(UTC):
        raise CutoverEvidenceError(
            "attempt_authority_not_yet_valid",
            "attempt authority issued_at is in the future",
        )
    resource_values = (
        max_micu_per_attempt,
        max_cost_microunits_per_attempt,
        max_wall_time_seconds_per_attempt,
    )
    if any(
        type(value) is not int or value < 0
        for value in resource_values
    ):
        raise CutoverEvidenceError(
            "attempt_authority_resource_invalid",
            "attempt authority resources must be non-negative integers",
        )
    identity_digest = canonical_digest(dict(identity))
    prerequisite_digest = canonical_digest(dict(allowed_prerequisites))
    qualification_digest = canonical_digest(dict(architecture_qualification))
    campaign_id = (
        "aox_campaign_"
        + canonical_digest(
            {
                "identity_digest": identity_digest,
                "allowed_prerequisite_digest": prerequisite_digest,
                "architecture_qualification_digest": qualification_digest,
                "nonce": secrets.token_hex(32),
            }
        ).removeprefix("sha256:")[:24]
    )
    provider_token = f"aox-provider-routes@{identity_digest}"
    hpc_target_token = f"aox-hpc-routes@{identity_digest}"
    slots: list[dict[str, Any]] = []
    for ordinal, attempt_kind in enumerate(
        ("positive", "positive", "fault"),
        start=1,
    ):
        attempt_id = f"{attempt_kind}-{secrets.token_hex(16)}"
        suffix = _attempt_suffix(attempt_id)
        session_id = f"sess_formal_{suffix}"
        task_id = f"aox_execution_cutover_{suffix}"
        lane_id = f"lane_aox_execution_{suffix}"
        scope = "fault" if attempt_kind == "fault" else "formal"
        authority_arguments = {
            "session_id": session_id,
            "task_id": task_id,
            "campaign_id": campaign_id,
            "workflow_id": AOX_SELECTED_CHAIN_WORKFLOW_ID,
            "root_ref": f"attempts/{attempt_id}",
            "grantor_kind": "operator",
            "grantor_ref": AOX_ATTEMPT_AUTHORITY_GRANTOR_REF,
            "allowed_scopes": (scope,),
            "allowed_effect_classes": ("hpc", "provider"),
            "allowed_providers": (provider_token,),
            "allowed_hpc_targets": (hpc_target_token,),
            "max_attempts": 1,
            "max_micu": max_micu_per_attempt,
            "max_cost_microunits": max_cost_microunits_per_attempt,
            "max_wall_time_seconds": max_wall_time_seconds_per_attempt,
            "expires_at": expires_at,
            "idempotency_key": f"{campaign_id}:authority:{ordinal}",
        }
        envelope_id, request_digest, request = (
            scientific_attempt_authorization_identity(**authority_arguments)
        )
        slots.append(
            {
                "ordinal": ordinal,
                "attempt_kind": attempt_kind,
                "attempt_id": attempt_id,
                "session_id": session_id,
                "task_id": task_id,
                "lane_id": lane_id,
                "scope": scope,
                "authority_request": request,
                "envelope_id": envelope_id,
                "request_digest": request_digest,
            }
        )
    payload: dict[str, Any] = {
        "schema_id": AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID,
        "campaign_id": campaign_id,
        "identity_digest": identity_digest,
        "allowed_prerequisite_digest": prerequisite_digest,
        "architecture_qualification_digest": qualification_digest,
        "issued_at": effective_issued_at,
        "expires_at": expires_at,
        "slots": slots,
    }
    return {**payload, "plan_digest": canonical_digest(payload)}


def validate_aox_attempt_authority_plan(
    plan: Mapping[str, object],
    *,
    identity: Mapping[str, object],
    allowed_prerequisites: Mapping[str, object],
    architecture_qualification: Mapping[str, object],
) -> dict[str, Any]:
    normalized = dict(plan)
    if (
        set(normalized) != _PLAN_FIELDS
        or normalized.get("schema_id")
        != AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID
    ):
        raise CutoverEvidenceError(
            "attempt_authority_plan_schema_invalid",
            "AOX attempt authority plan has an unsupported closed schema",
        )
    expiry = _parse_future_timestamp(normalized.get("expires_at"))
    issued = _parse_timestamp(
        normalized.get("issued_at"),
        code="attempt_authority_issued_at_invalid",
        label="issued_at",
    )
    if issued > expiry:
        raise CutoverEvidenceError(
            "attempt_authority_time_order_invalid",
            "attempt authority issued_at must not follow expires_at",
        )
    if issued > datetime.now(UTC):
        raise CutoverEvidenceError(
            "attempt_authority_not_yet_valid",
            "attempt authority issued_at is in the future",
        )
    campaign_id = normalized.get("campaign_id")
    if (
        not isinstance(campaign_id, str)
        or _CAMPAIGN_ID_PATTERN.fullmatch(campaign_id) is None
    ):
        raise CutoverEvidenceError(
            "attempt_authority_campaign_id_invalid",
            "AOX authority plan campaign id is malformed",
        )
    expected_digests = {
        "identity_digest": canonical_digest(dict(identity)),
        "allowed_prerequisite_digest": canonical_digest(
            dict(allowed_prerequisites)
        ),
        "architecture_qualification_digest": canonical_digest(
            dict(architecture_qualification)
        ),
    }
    drift = {
        key: {"expected": expected, "actual": normalized.get(key)}
        for key, expected in expected_digests.items()
        if normalized.get(key) != expected
    }
    payload_without_digest = {
        key: value
        for key, value in normalized.items()
        if key != "plan_digest"
    }
    if normalized.get("plan_digest") != canonical_digest(
        payload_without_digest
    ):
        drift["plan_digest"] = {
            "expected": canonical_digest(payload_without_digest),
            "actual": normalized.get("plan_digest"),
        }
    if drift:
        raise CutoverEvidenceError(
            "attempt_authority_plan_digest_mismatch",
            "AOX attempt authority plan does not bind current launch declarations",
            details={"drift": drift},
        )
    slots = normalized.get("slots")
    if (
        not isinstance(slots, list)
        or len(slots) != 3
        or [item.get("attempt_kind") for item in slots if isinstance(item, dict)]
        != ["positive", "positive", "fault"]
    ):
        raise CutoverEvidenceError(
            "attempt_authority_plan_slots_invalid",
            "AOX authority plan must contain positive, positive, fault in order",
        )
    seen_attempt_ids: set[str] = set()
    seen_envelope_ids: set[str] = set()
    resource_limits: tuple[int, int, int] | None = None
    expected_provider_token = (
        f"aox-provider-routes@{expected_digests['identity_digest']}"
    )
    expected_hpc_target_token = (
        f"aox-hpc-routes@{expected_digests['identity_digest']}"
    )
    for ordinal, raw_slot in enumerate(slots, start=1):
        if not isinstance(raw_slot, dict) or set(raw_slot) != _SLOT_FIELDS:
            raise CutoverEvidenceError(
                "attempt_authority_slot_schema_invalid",
                "AOX authority slot has an unsupported closed schema",
                details={"ordinal": ordinal},
            )
        slot = dict(raw_slot)
        attempt_id = slot.get("attempt_id")
        attempt_kind = slot.get("attempt_kind")
        suffix = (
            ""
            if not isinstance(attempt_id, str)
            else _attempt_suffix(attempt_id)
        )
        expected_scope = "fault" if attempt_kind == "fault" else "formal"
        request = slot.get("authority_request")
        if (
            type(slot.get("ordinal")) is not int
            or slot.get("ordinal") != ordinal
            or not isinstance(attempt_id, str)
            or _ATTEMPT_ID_PATTERN.fullmatch(attempt_id) is None
            or attempt_id in seen_attempt_ids
            or slot.get("session_id") != f"sess_formal_{suffix}"
            or slot.get("task_id") != f"aox_execution_cutover_{suffix}"
            or slot.get("lane_id") != f"lane_aox_execution_{suffix}"
            or slot.get("scope") != expected_scope
            or not isinstance(request, dict)
        ):
            raise CutoverEvidenceError(
                "attempt_authority_slot_identity_invalid",
                "AOX authority slot identities do not reproduce",
                details={"ordinal": ordinal},
            )
        seen_attempt_ids.add(attempt_id)
        request_resources = (
            request.get("max_micu"),
            request.get("max_cost_microunits"),
            request.get("max_wall_time_seconds"),
        )
        if any(
            type(value) is not int or value < 0
            for value in request_resources
        ):
            raise CutoverEvidenceError(
                "attempt_authority_resource_invalid",
                "attempt authority resources must be non-negative integers",
                details={"ordinal": ordinal},
            )
        typed_resources = (
            int(request_resources[0]),
            int(request_resources[1]),
            int(request_resources[2]),
        )
        if resource_limits is None:
            resource_limits = typed_resources
        elif typed_resources != resource_limits:
            raise CutoverEvidenceError(
                "attempt_authority_resource_mismatch",
                "all AOX authority slots must carry identical resource ceilings",
                details={"ordinal": ordinal},
            )
        request_arguments = {
            key: value
            for key, value in request.items()
            if key not in {"command", "policy_digest"}
        }
        try:
            envelope_id, request_digest, expected_request = (
                scientific_attempt_authorization_identity(
                    **request_arguments
                )
            )
        except (TypeError, ValueError) as exc:
            raise CutoverEvidenceError(
                "attempt_authority_slot_request_invalid",
                "AOX authority slot grant request is malformed",
                details={"ordinal": ordinal},
            ) from exc
        if (
            request != expected_request
            or request.get("session_id") != slot["session_id"]
            or request.get("task_id") != slot["task_id"]
            or request.get("campaign_id") != normalized["campaign_id"]
            or request.get("workflow_id")
            != AOX_SELECTED_CHAIN_WORKFLOW_ID
            or request.get("root_ref") != f"attempts/{attempt_id}"
            or request.get("grantor_kind") != "operator"
            or request.get("grantor_ref")
            != AOX_ATTEMPT_AUTHORITY_GRANTOR_REF
            or request.get("allowed_scopes") != [expected_scope]
            or request.get("allowed_effect_classes") != ["hpc", "provider"]
            or request.get("allowed_providers")
            != [expected_provider_token]
            or request.get("allowed_hpc_targets")
            != [expected_hpc_target_token]
            or request.get("max_attempts") != 1
            or request.get("expires_at") != normalized["expires_at"]
            or request.get("idempotency_key")
            != f"{campaign_id}:authority:{ordinal}"
            or slot.get("envelope_id") != envelope_id
            or slot.get("request_digest") != request_digest
            or envelope_id in seen_envelope_ids
        ):
            raise CutoverEvidenceError(
                "attempt_authority_slot_request_mismatch",
                "AOX authority slot does not reproduce its exact durable grant",
                details={"ordinal": ordinal},
            )
        seen_envelope_ids.add(envelope_id)
    return normalized


def load_aox_attempt_authority_plan(
    path: Path,
    *,
    identity: Mapping[str, object],
    allowed_prerequisites: Mapping[str, object],
    architecture_qualification: Mapping[str, object],
) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise CutoverEvidenceError(
            "attempt_authority_plan_unreadable",
            "authority plan is not a readable private regular file",
        ) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise CutoverEvidenceError(
            "attempt_authority_plan_file_invalid",
            "authority plan must be a private regular non-symlink file",
        )
    try:
        content = path.read_bytes()
        plan = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CutoverEvidenceError(
            "attempt_authority_plan_unreadable",
            "authority plan is not readable JSON",
        ) from exc
    if (
        not isinstance(plan, dict)
        or content != canonical_json_bytes(plan) + b"\n"
    ):
        raise CutoverEvidenceError(
            "attempt_authority_plan_noncanonical",
            "authority plan must use canonical JSON bytes",
        )
    return validate_aox_attempt_authority_plan(
        plan,
        identity=identity,
        allowed_prerequisites=allowed_prerequisites,
        architecture_qualification=architecture_qualification,
    )


def publish_aox_attempt_authority_plan(
    plan: Mapping[str, object],
    path: Path,
) -> None:
    _write_exclusive_private(path, canonical_json_bytes(dict(plan)) + b"\n")


def consume_aox_attempt_authority_plan(
    plan: Mapping[str, object],
    *,
    plan_path: Path,
    path: Path,
) -> dict[str, Any]:
    expected_path = attempt_authority_consumption_path(plan_path)
    if path != expected_path:
        raise CutoverEvidenceError(
            "attempt_authority_consumption_target_mismatch",
            "authority consumption must use the one deterministic sibling target",
            details={"expected_file": expected_path.name},
        )
    receipt = {
        "schema_id": AOX_ATTEMPT_AUTHORITY_CONSUMPTION_SCHEMA_ID,
        "plan_digest": plan["plan_digest"],
        "campaign_id": plan["campaign_id"],
        "consumed_at": _utc_now(),
    }
    _write_exclusive_private(path, canonical_json_bytes(receipt) + b"\n")
    return receipt


def attempt_authority_consumption_path(plan_path: Path) -> Path:
    return plan_path.with_name(f"{plan_path.name}.consumed.json")


def authority_grant_payload(slot: Mapping[str, object]) -> dict[str, Any]:
    """Project the canonical request into the public Host grant payload."""

    request = dict(slot["authority_request"])
    request.pop("command")
    request.pop("session_id")
    request.pop("grantor_ref")
    request.pop("idempotency_key")
    return request


def attempt_admission_arguments(slot: Mapping[str, object]) -> dict[str, Any]:
    request = dict(slot["authority_request"])
    provider = list(request["allowed_providers"])
    hpc_targets = list(request["allowed_hpc_targets"])
    return {
        "envelope_id": slot["envelope_id"],
        "task_id": slot["task_id"],
        "lane_id": slot["lane_id"],
        "campaign_id": request["campaign_id"],
        "workflow_id": request["workflow_id"],
        "scope": slot["scope"],
        "workflow_contract_digest": (
            AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST
        ),
        "requested_effect_classes": list(
            request["allowed_effect_classes"]
        ),
        "reserved_micu": request["max_micu"],
        "reserved_cost_microunits": request["max_cost_microunits"],
        "reserved_wall_time_seconds": request["max_wall_time_seconds"],
        "provider": provider[0] if len(provider) == 1 else None,
        "hpc_target": hpc_targets[0] if len(hpc_targets) == 1 else None,
        "idempotency_key": (
            f"{request['campaign_id']}:attempt:{slot['ordinal']}"
        ),
    }


def _write_exclusive_private(path: Path, content: bytes) -> None:
    parent = path.parent
    if (
        not parent.is_dir()
        or parent.is_symlink()
        or path.exists()
        or path.is_symlink()
    ):
        raise CutoverEvidenceError(
            "attempt_authority_publish_target_invalid",
            "authority target must be absent under an existing real directory",
        )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        written = 0
        while written < len(content):
            written += os.write(descriptor, content[written:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(path, 0o400, follow_symlinks=False)
    parent_descriptor = os.open(
        parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)


__all__ = [
    "AOX_ATTEMPT_AUTHORITY_CONSUMPTION_SCHEMA_ID",
    "AOX_ATTEMPT_AUTHORITY_GRANTOR_REF",
    "AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID",
    "attempt_admission_arguments",
    "attempt_authority_consumption_path",
    "authority_grant_payload",
    "build_aox_attempt_authority_plan",
    "consume_aox_attempt_authority_plan",
    "load_aox_attempt_authority_plan",
    "publish_aox_attempt_authority_plan",
    "validate_aox_attempt_authority_plan",
]
