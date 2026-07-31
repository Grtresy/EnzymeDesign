from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC
from datetime import datetime
import json
from pathlib import Path
import secrets
import stat
from typing import Any

from openzyme_core import scientific_attempt_authorization_identity

from .aox_authority_storage import publish_private_canonical_authority
from .aox_cutover_evidence import canonical_digest
from .aox_cutover_evidence import canonical_json_bytes
from .aox_cutover_evidence import CutoverEvidenceError
from .aox_live_run_class import AoxLiveRunClass
from .aox_live_run_class import FORMAL_ACCEPTANCE_RUN_POLICY
from .aox_scientific_contract import (
    AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_DIGEST,
)
from .aox_scientific_contract import AOX_SELECTED_CHAIN_WORKFLOW_ID


AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID = "aox_live_attempt_authority_plan@1"
AOX_ATTEMPT_AUTHORITY_CONSUMPTION_SCHEMA_ID = "aox_live_attempt_authority_consumption@2"
AOX_ATTEMPT_AUTHORITY_SLOT_CLAIM_SCHEMA_ID = "aox_attempt_authority_slot_claim@1"
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
_ATTEMPT_ID_PATTERN = FORMAL_ACCEPTANCE_RUN_POLICY.attempt_id_pattern
_CAMPAIGN_ID_PATTERN = FORMAL_ACCEPTANCE_RUN_POLICY.campaign_id_pattern


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
        session_id, task_id, lane_id, root_ref = (
            FORMAL_ACCEPTANCE_RUN_POLICY.identities(attempt_id)
        )
        scope = "fault" if attempt_kind == "fault" else "formal"
        authority_arguments = {
            "session_id": session_id,
            "task_id": task_id,
            "campaign_id": campaign_id,
            "workflow_id": AOX_SELECTED_CHAIN_WORKFLOW_ID,
            "root_ref": root_ref,
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
        (
            expected_session_id,
            expected_task_id,
            expected_lane_id,
            expected_root_ref,
        ) = FORMAL_ACCEPTANCE_RUN_POLICY.identities(
            "" if not isinstance(attempt_id, str) else attempt_id
        )
        expected_scope = "fault" if attempt_kind == "fault" else "formal"
        request = slot.get("authority_request")
        if (
            type(slot.get("ordinal")) is not int
            or slot.get("ordinal") != ordinal
            or not isinstance(attempt_id, str)
            or _ATTEMPT_ID_PATTERN.fullmatch(attempt_id) is None
            or attempt_id in seen_attempt_ids
            or slot.get("session_id") != expected_session_id
            or slot.get("task_id") != expected_task_id
            or slot.get("lane_id") != expected_lane_id
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
            or request.get("root_ref") != expected_root_ref
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
    if plan.get("schema_id") != AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID:
        raise CutoverEvidenceError(
            "attempt_authority_plan_class_mismatch",
            "formal authority publisher rejects non-formal plans",
        )
    publish_private_canonical_authority(
        path,
        canonical_json_bytes(dict(plan)) + b"\n",
    )


def consume_aox_attempt_authority_plan(
    plan: Mapping[str, object],
    *,
    plan_path: Path,
    path: Path,
) -> dict[str, Any]:
    if (
        plan.get("schema_id") != AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID
        or not isinstance(plan.get("slots"), list)
        or len(plan["slots"]) != 3
    ):
        raise CutoverEvidenceError(
            "attempt_authority_plan_class_mismatch",
            "formal authority consumption rejects non-formal plans",
        )
    expected_path = attempt_authority_consumption_path(plan_path)
    if path != expected_path:
        raise CutoverEvidenceError(
            "attempt_authority_consumption_target_mismatch",
            "authority consumption must use the one deterministic sibling target",
            details={"expected_file": expected_path.name},
        )
    receipt = {
        "schema_id": AOX_ATTEMPT_AUTHORITY_CONSUMPTION_SCHEMA_ID,
        "run_class": AoxLiveRunClass.FORMAL_ACCEPTANCE.value,
        "plan_schema_id": AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID,
        "plan_digest": plan["plan_digest"],
        "campaign_id": plan["campaign_id"],
        "consumption_file": path.name,
        "consumed_at": _utc_now(),
    }
    publish_private_canonical_authority(
        path,
        canonical_json_bytes(receipt) + b"\n",
    )
    return receipt


def attempt_authority_consumption_path(plan_path: Path) -> Path:
    return plan_path.with_name(f"{plan_path.name}.consumed.json")


def attempt_authority_slot_claim_path(plan_path: Path, ordinal: int) -> Path:
    if type(ordinal) is not int or ordinal not in {1, 2, 3}:
        raise CutoverEvidenceError(
            "attempt_authority_slot_ordinal_invalid",
            "formal authority slot ordinal must be exactly 1, 2, or 3",
        )
    return plan_path.with_name(f"{plan_path.name}.slot-{ordinal}.claimed.json")


def claim_aox_attempt_authority_slot(
    *,
    plan: Mapping[str, object],
    consumption: Mapping[str, object],
    plan_path: Path,
    ordinal: int,
    campaign_root: Path,
) -> dict[str, Any]:
    """Atomically consume one authority slot before any attempt root is created."""

    slots = plan.get("slots")
    if (
        plan.get("schema_id") != AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID
        or not isinstance(slots, list)
        or len(slots) != 3
        or type(ordinal) is not int
        or ordinal not in {1, 2, 3}
    ):
        raise CutoverEvidenceError(
            "attempt_authority_slot_claim_invalid",
            "formal slot claim requires one exact slot from a three-slot plan",
        )
    if consumption.get("plan_digest") != plan.get("plan_digest"):
        raise CutoverEvidenceError(
            "attempt_authority_slot_claim_invalid",
            "formal slot claim consumption does not bind its plan",
        )
    slot = dict(slots[ordinal - 1])
    if slot.get("ordinal") != ordinal:
        raise CutoverEvidenceError(
            "attempt_authority_slot_claim_invalid",
            "formal slot ordinal does not reproduce its plan position",
        )
    claim_path = attempt_authority_slot_claim_path(plan_path, ordinal)
    root_identity = canonical_digest(
        {"campaign_root": str(campaign_root.expanduser().absolute())}
    )
    payload: dict[str, Any] = {
        "schema_id": AOX_ATTEMPT_AUTHORITY_SLOT_CLAIM_SCHEMA_ID,
        "run_class": AoxLiveRunClass.FORMAL_ACCEPTANCE.value,
        "campaign_id": plan["campaign_id"],
        "plan_digest": plan["plan_digest"],
        "consumption_digest": canonical_digest(dict(consumption)),
        "ordinal": ordinal,
        "attempt_kind": slot["attempt_kind"],
        "attempt_id": slot["attempt_id"],
        "session_id": slot["session_id"],
        "task_id": slot["task_id"],
        "lane_id": slot["lane_id"],
        "envelope_id": slot["envelope_id"],
        "request_digest": slot["request_digest"],
        "campaign_root_identity": root_identity,
        "claim_file": claim_path.name,
        "claimed_at": _utc_now(),
    }
    claim = {**payload, "claim_digest": canonical_digest(payload)}
    publish_private_canonical_authority(
        claim_path,
        canonical_json_bytes(claim) + b"\n",
    )
    return claim


def validate_aox_attempt_authority_slot_claim(
    claim: Mapping[str, object],
    *,
    plan: Mapping[str, object],
    consumption: Mapping[str, object],
    plan_path: Path,
    ordinal: int,
    campaign_root: Path,
) -> dict[str, Any]:
    normalized = dict(claim)
    slots = plan.get("slots")
    slot = (
        dict(slots[ordinal - 1])
        if isinstance(slots, list) and len(slots) == 3 and ordinal in {1, 2, 3}
        else {}
    )
    payload = {key: value for key, value in normalized.items() if key != "claim_digest"}
    expected_path = attempt_authority_slot_claim_path(plan_path, ordinal)
    expected_fields = {
        "schema_id",
        "run_class",
        "campaign_id",
        "plan_digest",
        "consumption_digest",
        "ordinal",
        "attempt_kind",
        "attempt_id",
        "session_id",
        "task_id",
        "lane_id",
        "envelope_id",
        "request_digest",
        "campaign_root_identity",
        "claim_file",
        "claimed_at",
        "claim_digest",
    }
    expected_bindings = {
        "campaign_id": plan.get("campaign_id"),
        "plan_digest": plan.get("plan_digest"),
        "consumption_digest": canonical_digest(dict(consumption)),
        "ordinal": ordinal,
        "attempt_kind": slot.get("attempt_kind"),
        "attempt_id": slot.get("attempt_id"),
        "session_id": slot.get("session_id"),
        "task_id": slot.get("task_id"),
        "lane_id": slot.get("lane_id"),
        "envelope_id": slot.get("envelope_id"),
        "request_digest": slot.get("request_digest"),
        "campaign_root_identity": canonical_digest(
            {"campaign_root": str(campaign_root.expanduser().absolute())}
        ),
        "claim_file": expected_path.name,
    }
    if not all(
        (
            set(normalized) == expected_fields,
            normalized.get("schema_id") == AOX_ATTEMPT_AUTHORITY_SLOT_CLAIM_SCHEMA_ID,
            normalized.get("run_class") == AoxLiveRunClass.FORMAL_ACCEPTANCE.value,
            all(
                normalized.get(key) == value for key, value in expected_bindings.items()
            ),
            normalized.get("claim_digest") == canonical_digest(payload),
        )
    ):
        raise CutoverEvidenceError(
            "attempt_authority_slot_claim_invalid",
            "formal slot claim does not bind its exact plan slot and campaign root",
        )
    _parse_timestamp(
        normalized.get("claimed_at"),
        code="attempt_authority_slot_claim_invalid",
        label="claimed_at",
    )
    return normalized


def load_aox_attempt_authority_slot_claim(
    path: Path,
    *,
    plan: Mapping[str, object],
    consumption: Mapping[str, object],
    plan_path: Path,
    ordinal: int,
    campaign_root: Path,
) -> dict[str, Any]:
    expected_path = attempt_authority_slot_claim_path(plan_path, ordinal)
    try:
        metadata = path.lstat()
        content = path.read_bytes()
        value = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CutoverEvidenceError(
            "attempt_authority_slot_claim_unreadable",
            "formal slot claim is not readable canonical JSON",
        ) from exc
    if not all(
        (
            path == expected_path,
            stat.S_ISREG(metadata.st_mode),
            not stat.S_ISLNK(metadata.st_mode),
            stat.S_IMODE(metadata.st_mode) & 0o077 == 0,
            isinstance(value, dict),
            isinstance(value, dict) and content == canonical_json_bytes(value) + b"\n",
        )
    ):
        raise CutoverEvidenceError(
            "attempt_authority_slot_claim_invalid",
            "formal slot claim must be its exact private canonical sibling",
        )
    return validate_aox_attempt_authority_slot_claim(
        value,
        plan=plan,
        consumption=consumption,
        plan_path=plan_path,
        ordinal=ordinal,
        campaign_root=campaign_root,
    )


def validate_aox_attempt_authority_consumption(
    receipt: Mapping[str, object],
    *,
    plan: Mapping[str, object],
    plan_path: Path,
) -> dict[str, Any]:
    normalized = dict(receipt)
    expected_path = attempt_authority_consumption_path(plan_path)
    if (
        plan.get("schema_id") != AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID
        or not isinstance(plan.get("slots"), list)
        or len(plan["slots"]) != 3
    ):
        raise CutoverEvidenceError(
            "attempt_authority_plan_class_mismatch",
            "formal consumption validation rejects non-formal plans",
        )
    if (
        set(normalized)
        != {
            "schema_id",
            "run_class",
            "plan_schema_id",
            "plan_digest",
            "campaign_id",
            "consumption_file",
            "consumed_at",
        }
        or normalized.get("schema_id")
        != AOX_ATTEMPT_AUTHORITY_CONSUMPTION_SCHEMA_ID
        or normalized.get("run_class")
        != AoxLiveRunClass.FORMAL_ACCEPTANCE.value
        or normalized.get("plan_schema_id")
        != AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID
        or normalized.get("plan_digest") != plan.get("plan_digest")
        or normalized.get("campaign_id") != plan.get("campaign_id")
        or normalized.get("consumption_file") != expected_path.name
    ):
        raise CutoverEvidenceError(
            "attempt_authority_consumption_invalid",
            "formal consumption receipt does not bind its exact plan class",
        )
    _parse_timestamp(
        normalized.get("consumed_at"),
        code="attempt_authority_consumption_invalid",
        label="consumed_at",
    )
    return normalized


def load_aox_attempt_authority_consumption(
    path: Path,
    *,
    plan: Mapping[str, object],
    plan_path: Path,
) -> dict[str, Any]:
    expected_path = attempt_authority_consumption_path(plan_path)
    try:
        metadata = path.lstat()
        content = path.read_bytes()
        value = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CutoverEvidenceError(
            "attempt_authority_consumption_unreadable",
            "formal authority consumption is not readable canonical JSON",
        ) from exc
    if (
        path != expected_path
        or stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or not isinstance(value, dict)
        or content != canonical_json_bytes(value) + b"\n"
    ):
        raise CutoverEvidenceError(
            "attempt_authority_consumption_invalid",
            "formal authority consumption must be its exact private canonical sibling",
        )
    return validate_aox_attempt_authority_consumption(
        value,
        plan=plan,
        plan_path=plan_path,
    )


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
    }


__all__ = [
    "AOX_ATTEMPT_AUTHORITY_CONSUMPTION_SCHEMA_ID",
    "AOX_ATTEMPT_AUTHORITY_GRANTOR_REF",
    "AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID",
    "AOX_ATTEMPT_AUTHORITY_SLOT_CLAIM_SCHEMA_ID",
    "attempt_admission_arguments",
    "attempt_authority_consumption_path",
    "attempt_authority_slot_claim_path",
    "authority_grant_payload",
    "build_aox_attempt_authority_plan",
    "claim_aox_attempt_authority_slot",
    "consume_aox_attempt_authority_plan",
    "load_aox_attempt_authority_plan",
    "load_aox_attempt_authority_consumption",
    "load_aox_attempt_authority_slot_claim",
    "publish_aox_attempt_authority_plan",
    "validate_aox_attempt_authority_consumption",
    "validate_aox_attempt_authority_plan",
    "validate_aox_attempt_authority_slot_claim",
]
