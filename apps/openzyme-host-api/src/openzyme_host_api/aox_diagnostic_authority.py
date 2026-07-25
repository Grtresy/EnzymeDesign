from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
import secrets
import stat
from typing import Any

from openzyme_core import scientific_attempt_authorization_identity

from .aox_attempt_authority import AOX_ATTEMPT_AUTHORITY_GRANTOR_REF
from .aox_authority_storage import publish_private_canonical_authority
from .aox_cutover_evidence import canonical_digest
from .aox_cutover_evidence import canonical_json_bytes
from .aox_cutover_evidence import CutoverEvidenceError
from .aox_live_run_class import AoxLiveRunClass
from .aox_live_run_class import DIAGNOSTIC_RUN_POLICY
from .aox_scientific_contract import AOX_SELECTED_CHAIN_WORKFLOW_ID


AOX_DIAGNOSTIC_AUTHORITY_PLAN_SCHEMA_ID = (
    "aox_diagnostic_attempt_authority_plan@1"
)
AOX_DIAGNOSTIC_AUTHORITY_CONSUMPTION_SCHEMA_ID = (
    "aox_diagnostic_attempt_authority_consumption@1"
)

_PLAN_FIELDS = frozenset(
    {
        "schema_id",
        "run_class",
        "diagnostic_id",
        "root_namespace",
        "identity_digest",
        "allowed_prerequisite_digest",
        "architecture_qualification_digest",
        "issued_at",
        "expires_at",
        "slot",
        "plan_digest",
    }
)
_SLOT_FIELDS = frozenset(
    {
        "run_class",
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
            f"diagnostic authority {label} must be a non-empty ISO-8601 timestamp",
        )
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CutoverEvidenceError(
            code,
            f"diagnostic authority {label} is not valid ISO-8601",
        ) from exc
    if parsed.tzinfo is None:
        raise CutoverEvidenceError(
            code,
            f"diagnostic authority {label} must include a timezone",
        )
    return parsed.astimezone(UTC)


def _validate_time_window(
    *,
    issued_at: str,
    expires_at: str,
) -> None:
    expiry = _parse_timestamp(
        expires_at,
        code="diagnostic_authority_expiry_invalid",
        label="expiry",
    )
    issued = _parse_timestamp(
        issued_at,
        code="diagnostic_authority_issued_at_invalid",
        label="issued_at",
    )
    now = datetime.now(UTC)
    if expiry <= now:
        raise CutoverEvidenceError(
            "diagnostic_authority_expired",
            "diagnostic authority plan has expired",
        )
    if issued > expiry:
        raise CutoverEvidenceError(
            "diagnostic_authority_time_order_invalid",
            "diagnostic authority issued_at must not follow expires_at",
        )
    if issued > now:
        raise CutoverEvidenceError(
            "diagnostic_authority_not_yet_valid",
            "diagnostic authority issued_at is in the future",
        )


def _validate_resources(
    *,
    max_micu: object,
    max_cost_microunits: object,
    max_wall_time_seconds: object,
) -> None:
    if any(
        type(value) is not int or value < 0
        for value in (
            max_micu,
            max_cost_microunits,
            max_wall_time_seconds,
        )
    ):
        raise CutoverEvidenceError(
            "diagnostic_authority_resource_invalid",
            "diagnostic authority resources must be non-negative integers",
        )


def build_aox_diagnostic_authority_plan(
    *,
    identity: Mapping[str, object],
    allowed_prerequisites: Mapping[str, object],
    architecture_qualification: Mapping[str, object],
    expires_at: str,
    max_micu: int,
    max_cost_microunits: int,
    max_wall_time_seconds: int,
    issued_at: str | None = None,
) -> dict[str, Any]:
    """Build one positive-shaped diagnostic slot without creating a root."""

    effective_issued_at = issued_at or _utc_now()
    _validate_time_window(
        issued_at=effective_issued_at,
        expires_at=expires_at,
    )
    _validate_resources(
        max_micu=max_micu,
        max_cost_microunits=max_cost_microunits,
        max_wall_time_seconds=max_wall_time_seconds,
    )
    identity_digest = canonical_digest(dict(identity))
    prerequisite_digest = canonical_digest(dict(allowed_prerequisites))
    qualification_digest = canonical_digest(dict(architecture_qualification))
    diagnostic_id = (
        "aox_diagnostic_"
        + canonical_digest(
            {
                "identity_digest": identity_digest,
                "allowed_prerequisite_digest": prerequisite_digest,
                "architecture_qualification_digest": qualification_digest,
                "nonce": secrets.token_hex(32),
            }
        ).removeprefix("sha256:")[:24]
    )
    root_namespace = diagnostic_id.replace("_", "-")
    attempt_id = f"diagnostic-positive-{secrets.token_hex(16)}"
    session_id, task_id, lane_id, root_ref = (
        DIAGNOSTIC_RUN_POLICY.identities(attempt_id)
    )
    provider_token = f"aox-provider-routes@{identity_digest}"
    hpc_target_token = f"aox-hpc-routes@{identity_digest}"
    authority_arguments = {
        "session_id": session_id,
        "task_id": task_id,
        "campaign_id": diagnostic_id,
        "workflow_id": AOX_SELECTED_CHAIN_WORKFLOW_ID,
        "root_ref": root_ref,
        "grantor_kind": "operator",
        "grantor_ref": AOX_ATTEMPT_AUTHORITY_GRANTOR_REF,
        "allowed_scopes": ("formal",),
        "allowed_effect_classes": ("hpc", "provider"),
        "allowed_providers": (provider_token,),
        "allowed_hpc_targets": (hpc_target_token,),
        "max_attempts": 1,
        "max_micu": max_micu,
        "max_cost_microunits": max_cost_microunits,
        "max_wall_time_seconds": max_wall_time_seconds,
        "expires_at": expires_at,
        "idempotency_key": f"{diagnostic_id}:authority:1",
    }
    envelope_id, request_digest, request = (
        scientific_attempt_authorization_identity(**authority_arguments)
    )
    slot = {
        "run_class": AoxLiveRunClass.DIAGNOSTIC.value,
        "ordinal": 1,
        "attempt_kind": "positive",
        "attempt_id": attempt_id,
        "session_id": session_id,
        "task_id": task_id,
        "lane_id": lane_id,
        "scope": "formal",
        "authority_request": request,
        "envelope_id": envelope_id,
        "request_digest": request_digest,
    }
    payload: dict[str, Any] = {
        "schema_id": AOX_DIAGNOSTIC_AUTHORITY_PLAN_SCHEMA_ID,
        "run_class": AoxLiveRunClass.DIAGNOSTIC.value,
        "diagnostic_id": diagnostic_id,
        "root_namespace": root_namespace,
        "identity_digest": identity_digest,
        "allowed_prerequisite_digest": prerequisite_digest,
        "architecture_qualification_digest": qualification_digest,
        "issued_at": effective_issued_at,
        "expires_at": expires_at,
        "slot": slot,
    }
    return {**payload, "plan_digest": canonical_digest(payload)}


def validate_aox_diagnostic_authority_plan(
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
        != AOX_DIAGNOSTIC_AUTHORITY_PLAN_SCHEMA_ID
        or normalized.get("run_class") != AoxLiveRunClass.DIAGNOSTIC.value
    ):
        raise CutoverEvidenceError(
            "diagnostic_authority_plan_schema_invalid",
            "diagnostic authority plan has an unsupported closed schema",
        )
    issued_at = normalized.get("issued_at")
    expires_at = normalized.get("expires_at")
    if not isinstance(issued_at, str) or not isinstance(expires_at, str):
        raise CutoverEvidenceError(
            "diagnostic_authority_time_invalid",
            "diagnostic authority timestamps must be strings",
        )
    _validate_time_window(issued_at=issued_at, expires_at=expires_at)
    diagnostic_id = normalized.get("diagnostic_id")
    root_namespace = normalized.get("root_namespace")
    if (
        not isinstance(diagnostic_id, str)
        or DIAGNOSTIC_RUN_POLICY.campaign_id_pattern.fullmatch(diagnostic_id)
        is None
        or root_namespace != diagnostic_id.replace("_", "-")
    ):
        raise CutoverEvidenceError(
            "diagnostic_authority_identity_invalid",
            "diagnostic plan id and root namespace do not reproduce",
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
    unsigned = {
        key: value
        for key, value in normalized.items()
        if key != "plan_digest"
    }
    expected_plan_digest = canonical_digest(unsigned)
    if normalized.get("plan_digest") != expected_plan_digest:
        drift["plan_digest"] = {
            "expected": expected_plan_digest,
            "actual": normalized.get("plan_digest"),
        }
    if drift:
        raise CutoverEvidenceError(
            "diagnostic_authority_plan_digest_mismatch",
            "diagnostic authority plan does not bind current declarations",
            details={"drift": drift},
        )
    raw_slot = normalized.get("slot")
    if not isinstance(raw_slot, dict) or set(raw_slot) != _SLOT_FIELDS:
        raise CutoverEvidenceError(
            "diagnostic_authority_slot_schema_invalid",
            "diagnostic authority slot has an unsupported closed schema",
        )
    slot = dict(raw_slot)
    attempt_id = slot.get("attempt_id")
    (
        expected_session_id,
        expected_task_id,
        expected_lane_id,
        expected_root_ref,
    ) = DIAGNOSTIC_RUN_POLICY.identities(
        "" if not isinstance(attempt_id, str) else attempt_id
    )
    request = slot.get("authority_request")
    if (
        slot.get("run_class") != AoxLiveRunClass.DIAGNOSTIC.value
        or slot.get("ordinal") != 1
        or slot.get("attempt_kind") != "positive"
        or not isinstance(attempt_id, str)
        or DIAGNOSTIC_RUN_POLICY.attempt_id_pattern.fullmatch(attempt_id)
        is None
        or slot.get("session_id") != expected_session_id
        or slot.get("task_id") != expected_task_id
        or slot.get("lane_id") != expected_lane_id
        or slot.get("scope") != "formal"
        or not isinstance(request, dict)
    ):
        raise CutoverEvidenceError(
            "diagnostic_authority_slot_identity_invalid",
            "diagnostic authority slot identities do not reproduce",
        )
    _validate_resources(
        max_micu=request.get("max_micu"),
        max_cost_microunits=request.get("max_cost_microunits"),
        max_wall_time_seconds=request.get("max_wall_time_seconds"),
    )
    request_arguments = {
        key: value
        for key, value in request.items()
        if key not in {"command", "policy_digest"}
    }
    try:
        envelope_id, request_digest, expected_request = (
            scientific_attempt_authorization_identity(**request_arguments)
        )
    except (TypeError, ValueError) as exc:
        raise CutoverEvidenceError(
            "diagnostic_authority_slot_request_invalid",
            "diagnostic authority request is malformed",
        ) from exc
    if (
        request != expected_request
        or request.get("session_id") != expected_session_id
        or request.get("task_id") != expected_task_id
        or request.get("campaign_id") != diagnostic_id
        or request.get("workflow_id") != AOX_SELECTED_CHAIN_WORKFLOW_ID
        or request.get("root_ref") != expected_root_ref
        or request.get("grantor_kind") != "operator"
        or request.get("grantor_ref") != AOX_ATTEMPT_AUTHORITY_GRANTOR_REF
        or request.get("allowed_scopes") != ["formal"]
        or request.get("allowed_effect_classes") != ["hpc", "provider"]
        or request.get("allowed_providers")
        != [f"aox-provider-routes@{expected_digests['identity_digest']}"]
        or request.get("allowed_hpc_targets")
        != [f"aox-hpc-routes@{expected_digests['identity_digest']}"]
        or request.get("max_attempts") != 1
        or request.get("expires_at") != expires_at
        or request.get("idempotency_key")
        != f"{diagnostic_id}:authority:1"
        or slot.get("envelope_id") != envelope_id
        or slot.get("request_digest") != request_digest
    ):
        raise CutoverEvidenceError(
            "diagnostic_authority_slot_request_mismatch",
            "diagnostic slot does not reproduce its exact durable grant",
        )
    return normalized


def load_aox_diagnostic_authority_plan(
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
            "diagnostic_authority_plan_unreadable",
            "diagnostic authority plan is not a readable private regular file",
        ) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise CutoverEvidenceError(
            "diagnostic_authority_plan_file_invalid",
            "diagnostic authority plan must be a private regular file",
        )
    try:
        content = path.read_bytes()
        plan = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CutoverEvidenceError(
            "diagnostic_authority_plan_unreadable",
            "diagnostic authority plan is not readable JSON",
        ) from exc
    if (
        not isinstance(plan, dict)
        or content != canonical_json_bytes(plan) + b"\n"
    ):
        raise CutoverEvidenceError(
            "diagnostic_authority_plan_noncanonical",
            "diagnostic authority plan must use canonical JSON bytes",
        )
    return validate_aox_diagnostic_authority_plan(
        plan,
        identity=identity,
        allowed_prerequisites=allowed_prerequisites,
        architecture_qualification=architecture_qualification,
    )


def publish_aox_diagnostic_authority_plan(
    plan: Mapping[str, object],
    path: Path,
) -> None:
    if plan.get("schema_id") != AOX_DIAGNOSTIC_AUTHORITY_PLAN_SCHEMA_ID:
        raise CutoverEvidenceError(
            "diagnostic_authority_plan_class_mismatch",
            "diagnostic publisher rejects non-diagnostic plans",
        )
    publish_private_canonical_authority(
        path,
        canonical_json_bytes(dict(plan)) + b"\n",
    )


def diagnostic_authority_consumption_path(plan_path: Path) -> Path:
    return plan_path.with_name(
        f"{plan_path.name}.diagnostic-consumed.json"
    )


def consume_aox_diagnostic_authority_plan(
    plan: Mapping[str, object],
    *,
    plan_path: Path,
    path: Path,
) -> dict[str, Any]:
    if (
        plan.get("schema_id") != AOX_DIAGNOSTIC_AUTHORITY_PLAN_SCHEMA_ID
        or plan.get("run_class") != AoxLiveRunClass.DIAGNOSTIC.value
        or not isinstance(plan.get("slot"), dict)
    ):
        raise CutoverEvidenceError(
            "diagnostic_authority_plan_class_mismatch",
            "diagnostic authority consumption rejects non-diagnostic plans",
        )
    expected_path = diagnostic_authority_consumption_path(plan_path)
    if path != expected_path:
        raise CutoverEvidenceError(
            "diagnostic_authority_consumption_target_mismatch",
            "diagnostic consumption must use its deterministic sibling target",
            details={"expected_file": expected_path.name},
        )
    receipt = {
        "schema_id": AOX_DIAGNOSTIC_AUTHORITY_CONSUMPTION_SCHEMA_ID,
        "run_class": AoxLiveRunClass.DIAGNOSTIC.value,
        "plan_schema_id": AOX_DIAGNOSTIC_AUTHORITY_PLAN_SCHEMA_ID,
        "plan_digest": plan["plan_digest"],
        "diagnostic_id": plan["diagnostic_id"],
        "root_namespace": plan["root_namespace"],
        "consumption_file": path.name,
        "consumed_at": _utc_now(),
    }
    publish_private_canonical_authority(
        path,
        canonical_json_bytes(receipt) + b"\n",
    )
    return receipt


def validate_aox_diagnostic_authority_consumption(
    receipt: Mapping[str, object],
    *,
    plan: Mapping[str, object],
    plan_path: Path,
) -> dict[str, Any]:
    normalized = dict(receipt)
    expected_path = diagnostic_authority_consumption_path(plan_path)
    expected_fields = {
        "schema_id",
        "run_class",
        "plan_schema_id",
        "plan_digest",
        "diagnostic_id",
        "root_namespace",
        "consumption_file",
        "consumed_at",
    }
    if (
        plan.get("schema_id") != AOX_DIAGNOSTIC_AUTHORITY_PLAN_SCHEMA_ID
        or plan.get("run_class") != AoxLiveRunClass.DIAGNOSTIC.value
        or not isinstance(plan.get("slot"), dict)
    ):
        raise CutoverEvidenceError(
            "diagnostic_authority_plan_class_mismatch",
            "diagnostic consumption validation rejects non-diagnostic plans",
        )
    if (
        set(normalized) != expected_fields
        or normalized.get("schema_id")
        != AOX_DIAGNOSTIC_AUTHORITY_CONSUMPTION_SCHEMA_ID
        or normalized.get("run_class")
        != AoxLiveRunClass.DIAGNOSTIC.value
        or normalized.get("plan_schema_id")
        != AOX_DIAGNOSTIC_AUTHORITY_PLAN_SCHEMA_ID
        or normalized.get("plan_digest") != plan.get("plan_digest")
        or normalized.get("diagnostic_id") != plan.get("diagnostic_id")
        or normalized.get("root_namespace") != plan.get("root_namespace")
        or normalized.get("consumption_file") != expected_path.name
    ):
        raise CutoverEvidenceError(
            "diagnostic_authority_consumption_invalid",
            "diagnostic consumption receipt does not bind its exact plan class",
        )
    _parse_timestamp(
        normalized.get("consumed_at"),
        code="diagnostic_authority_consumption_invalid",
        label="consumed_at",
    )
    return normalized


__all__ = [
    "AOX_DIAGNOSTIC_AUTHORITY_CONSUMPTION_SCHEMA_ID",
    "AOX_DIAGNOSTIC_AUTHORITY_PLAN_SCHEMA_ID",
    "build_aox_diagnostic_authority_plan",
    "consume_aox_diagnostic_authority_plan",
    "diagnostic_authority_consumption_path",
    "load_aox_diagnostic_authority_plan",
    "publish_aox_diagnostic_authority_plan",
    "validate_aox_diagnostic_authority_consumption",
    "validate_aox_diagnostic_authority_plan",
]
