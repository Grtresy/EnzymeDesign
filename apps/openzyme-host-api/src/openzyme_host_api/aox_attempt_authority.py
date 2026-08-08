from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import secrets
import stat
from typing import Any

from openzyme_core import scientific_attempt_authorization_identity

from .aox_authority_storage import publish_private_canonical_authority
from .aox_cutover_evidence import canonical_digest, canonical_json_bytes
from .aox_cutover_evidence import CutoverEvidenceError
from .aox_live_run_class import AoxLiveRunClass, FORMAL_ACCEPTANCE_RUN_POLICY
from .aox_launch_profile import launch_profile_digest
from .aox_scientific_contract import AOX_SELECTED_CHAIN_WORKFLOW_ID


AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID = "aox_live_attempt_authority_plan@4"
AOX_ATTEMPT_AUTHORITY_CONSUMPTION_SCHEMA_ID = (
    "aox_live_attempt_authority_consumption@5"
)
AOX_ATTEMPT_AUTHORITY_SLOT_CLAIM_SCHEMA_ID = "aox_attempt_authority_slot_claim@3"
AOX_ATTEMPT_AUTHORITY_GRANTOR_REF = "user:local-dev"

_PLAN_FIELDS = set(
    "schema_id campaign_id identity_digest allowed_prerequisite_digest "
    "architecture_qualification_digest launch_profile_digest issued_at expires_at "
    "slots plan_digest".split()
)
_SLOT_FIELDS = set(
    "ordinal attempt_kind session_id root_ref scope authority_policy "
    "authority_policy_digest".split()
)
_POLICY_FIELDS = set(
    "workflow_id grantor_kind grantor_ref allowed_scopes allowed_effect_classes "
    "allowed_providers allowed_hpc_targets max_attempts max_micu "
    "max_cost_microunits max_wall_time_seconds expires_at idempotency_key".split()
)
_CONSUMPTION_FIELDS = set(
    "schema_id run_class plan_schema_id plan_digest campaign_id consumption_file "
    "consumed_at".split()
)
_CLAIM_FIELDS = set(
    "schema_id run_class campaign_id plan_digest consumption_digest ordinal "
    "attempt_kind launch_id session_id root_ref authority_policy_digest "
    "campaign_root_identity claim_file claimed_at claim_digest".split()
)
_CAMPAIGN_ID_PATTERN = FORMAL_ACCEPTANCE_RUN_POLICY.campaign_id_pattern
_CONTROL_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")


def _reject(code: str, message: str, **details: object) -> None:
    raise CutoverEvidenceError(code, message, details=details)


def _require(value: object, code: str, message: str, **details: object) -> None:
    if not value:
        _reject(code, message, **details)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _timestamp(value: object, *, code: str, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        _reject(code, f"attempt authority {label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CutoverEvidenceError(
            code, f"attempt authority {label} is not valid ISO-8601"
        ) from exc
    if parsed.tzinfo is None:
        _reject(code, f"attempt authority {label} must include a timezone")
    return parsed.astimezone(UTC)


def _future_timestamp(value: object) -> datetime:
    parsed = _timestamp(
        value, code="attempt_authority_expiry_invalid", label="expiry"
    )
    _require(
        parsed > datetime.now(UTC),
        "attempt_authority_expired",
        "attempt authority plan has expired",
    )
    return parsed


def _load_private_canonical(path: Path, *, unreadable_code: str) -> dict[str, Any]:
    try:
        metadata, content = path.lstat(), path.read_bytes()
        value = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CutoverEvidenceError(
            unreadable_code, "authority record is not readable canonical JSON"
        ) from exc
    _require(
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and stat.S_IMODE(metadata.st_mode) & 0o077 == 0
        and isinstance(value, dict)
        and content == canonical_json_bytes(value) + b"\n",
        unreadable_code,
        "authority record must be one private canonical file",
    )
    return dict(value)


def _resource_limits(policy: Mapping[str, object], *, ordinal: int) -> tuple[int, int, int]:
    resources = (
        policy.get("max_micu"),
        policy.get("max_cost_microunits"),
        policy.get("max_wall_time_seconds"),
    )
    if any(type(value) is not int or value < 0 for value in resources):
        _reject(
            "attempt_authority_resource_invalid",
            "attempt authority resources must be non-negative integers",
            ordinal=ordinal,
        )
    return resources  # type: ignore[return-value]


def build_aox_attempt_authority_plan(
    *,
    identity: Mapping[str, object],
    allowed_prerequisites: Mapping[str, object],
    architecture_qualification: Mapping[str, object],
    launch_profile: Mapping[str, object],
    expires_at: str,
    max_micu_per_attempt: int,
    max_cost_microunits_per_attempt: int,
    max_wall_time_seconds_per_attempt: int,
    issued_at: str | None = None,
) -> dict[str, Any]:
    """Build three task-free slots without creating task or attempt truth."""

    expiry = _future_timestamp(expires_at)
    effective_issued_at = issued_at or _utc_now()
    issued = _timestamp(
        effective_issued_at,
        code="attempt_authority_issued_at_invalid",
        label="issued_at",
    )
    _require(
        issued <= expiry,
        "attempt_authority_time_order_invalid",
        "attempt authority issued_at must not follow expires_at",
    )
    _require(
        issued <= datetime.now(UTC),
        "attempt_authority_not_yet_valid",
        "attempt authority issued_at is in the future",
    )
    resources = (
        max_micu_per_attempt,
        max_cost_microunits_per_attempt,
        max_wall_time_seconds_per_attempt,
    )
    if any(type(value) is not int or value < 0 for value in resources):
        _reject(
            "attempt_authority_resource_invalid",
            "attempt authority resources must be non-negative integers",
        )

    identity_digest = canonical_digest(dict(identity))
    prerequisite_digest = canonical_digest(dict(allowed_prerequisites))
    qualification_digest = canonical_digest(dict(architecture_qualification))
    pinned_launch_profile_digest = launch_profile_digest(launch_profile)
    campaign_id = "aox_campaign_" + canonical_digest(
        {
            "identity_digest": identity_digest,
            "allowed_prerequisite_digest": prerequisite_digest,
            "architecture_qualification_digest": qualification_digest,
            "launch_profile_digest": pinned_launch_profile_digest,
            "nonce": secrets.token_hex(32),
        }
    ).removeprefix("sha256:")[:24]
    slots: list[dict[str, Any]] = []
    for ordinal, attempt_kind in enumerate(("positive", "positive", "fault"), 1):
        nonce = secrets.token_hex(16)
        scope = "fault" if attempt_kind == "fault" else "formal"
        policy = {
            "workflow_id": AOX_SELECTED_CHAIN_WORKFLOW_ID,
            "grantor_kind": "operator",
            "grantor_ref": AOX_ATTEMPT_AUTHORITY_GRANTOR_REF,
            "allowed_scopes": [scope],
            "allowed_effect_classes": ["hpc", "provider"],
            "allowed_providers": [f"aox-provider-routes@{identity_digest}"],
            "allowed_hpc_targets": [f"aox-hpc-routes@{identity_digest}"],
            "max_attempts": 1,
            "max_micu": max_micu_per_attempt,
            "max_cost_microunits": max_cost_microunits_per_attempt,
            "max_wall_time_seconds": max_wall_time_seconds_per_attempt,
            "expires_at": expires_at,
            "idempotency_key": f"{campaign_id}:authority:{ordinal}",
        }
        slots.append(
            {
                "ordinal": ordinal,
                "attempt_kind": attempt_kind,
                "session_id": f"sess_aox_formal_{nonce}",
                "root_ref": f"formal-slots/{campaign_id}/{ordinal}/{nonce}",
                "scope": scope,
                "authority_policy": policy,
                "authority_policy_digest": canonical_digest(policy),
            }
        )
    payload: dict[str, Any] = {
        "schema_id": AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID,
        "campaign_id": campaign_id,
        "identity_digest": identity_digest,
        "allowed_prerequisite_digest": prerequisite_digest,
        "architecture_qualification_digest": qualification_digest,
        "launch_profile_digest": pinned_launch_profile_digest,
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
    launch_profile: Mapping[str, object],
) -> dict[str, Any]:
    normalized = dict(plan)
    if (
        set(normalized) != _PLAN_FIELDS
        or normalized.get("schema_id") != AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID
    ):
        _reject(
            "attempt_authority_plan_schema_invalid",
            "only the current task-free AOX authority plan is accepted",
        )
    expiry = _future_timestamp(normalized.get("expires_at"))
    issued = _timestamp(
        normalized.get("issued_at"),
        code="attempt_authority_issued_at_invalid",
        label="issued_at",
    )
    _require(
        issued <= expiry,
        "attempt_authority_time_order_invalid",
        "attempt authority issued_at must not follow expires_at",
    )
    _require(
        issued <= datetime.now(UTC),
        "attempt_authority_not_yet_valid",
        "attempt authority issued_at is in the future",
    )
    campaign_id = normalized.get("campaign_id")
    if not isinstance(campaign_id, str) or not _CAMPAIGN_ID_PATTERN.fullmatch(
        campaign_id
    ):
        _reject(
            "attempt_authority_campaign_id_invalid",
            "AOX authority campaign id is malformed",
        )
    expected_digests = {
        "identity_digest": canonical_digest(dict(identity)),
        "allowed_prerequisite_digest": canonical_digest(
            dict(allowed_prerequisites)
        ),
        "architecture_qualification_digest": canonical_digest(
            dict(architecture_qualification)
        ),
        "launch_profile_digest": launch_profile_digest(launch_profile),
    }
    expected_plan_digest = canonical_digest(
        {key: value for key, value in normalized.items() if key != "plan_digest"}
    )
    drift = {
        key: {"expected": expected, "actual": normalized.get(key)}
        for key, expected in {
            **expected_digests,
            "plan_digest": expected_plan_digest,
        }.items()
        if normalized.get(key) != expected
    }
    if drift:
        _reject(
            "attempt_authority_plan_digest_mismatch",
            "AOX authority plan does not bind current launch declarations",
            drift=drift,
        )
    slots = normalized.get("slots")
    if not isinstance(slots, list) or [
        item.get("attempt_kind") if isinstance(item, dict) else None for item in slots
    ] != ["positive", "positive", "fault"]:
        _reject(
            "attempt_authority_plan_slots_invalid",
            "AOX authority requires positive, positive, fault in order",
        )

    seen: set[tuple[str, str]] = set()
    resource_limits: tuple[int, int, int] | None = None
    for ordinal, raw_slot in enumerate(slots, 1):
        if not isinstance(raw_slot, dict) or set(raw_slot) != _SLOT_FIELDS:
            _reject(
                "attempt_authority_slot_schema_invalid",
                "AOX authority slot is not the current closed schema",
                ordinal=ordinal,
            )
        slot = dict(raw_slot)
        scope = "fault" if slot.get("attempt_kind") == "fault" else "formal"
        root_ref = slot.get("root_ref")
        root_parts = str(root_ref or "").split("/")
        nonce = root_parts[-1] if len(root_parts) == 4 else ""
        control_identity = (str(slot.get("session_id") or ""), str(root_ref or ""))
        identity_valid = all(
            (
                slot.get("ordinal") == ordinal,
                re.fullmatch(r"[a-f0-9]{32}", nonce) is not None,
                root_ref == f"formal-slots/{campaign_id}/{ordinal}/{nonce}",
                slot.get("session_id") == f"sess_aox_formal_{nonce}",
                _CONTROL_ID_PATTERN.fullmatch(control_identity[0]) is not None,
                control_identity not in seen,
                slot.get("scope") == scope,
            )
        )
        policy = slot.get("authority_policy")
        if not identity_valid or not isinstance(policy, dict):
            _reject(
                "attempt_authority_slot_identity_invalid",
                "AOX authority slot identities do not reproduce",
                ordinal=ordinal,
            )
        seen.add(control_identity)
        current_limits = _resource_limits(policy, ordinal=ordinal)
        if resource_limits is None:
            resource_limits = current_limits
        elif current_limits != resource_limits:
            _reject(
                "attempt_authority_resource_mismatch",
                "all authority slots must carry identical resource ceilings",
                ordinal=ordinal,
            )
        expected_policy = {
            "workflow_id": AOX_SELECTED_CHAIN_WORKFLOW_ID,
            "grantor_kind": "operator",
            "grantor_ref": AOX_ATTEMPT_AUTHORITY_GRANTOR_REF,
            "allowed_scopes": [scope],
            "allowed_effect_classes": ["hpc", "provider"],
            "allowed_providers": [
                f"aox-provider-routes@{expected_digests['identity_digest']}"
            ],
            "allowed_hpc_targets": [
                f"aox-hpc-routes@{expected_digests['identity_digest']}"
            ],
            "max_attempts": 1,
            "max_micu": policy.get("max_micu"),
            "max_cost_microunits": policy.get("max_cost_microunits"),
            "max_wall_time_seconds": policy.get("max_wall_time_seconds"),
            "expires_at": normalized["expires_at"],
            "idempotency_key": f"{campaign_id}:authority:{ordinal}",
        }
        if (
            set(policy) != _POLICY_FIELDS
            or policy != expected_policy
            or slot.get("authority_policy_digest") != canonical_digest(policy)
        ):
            _reject(
                "attempt_authority_slot_policy_mismatch",
                "AOX authority slot does not reproduce its task-free policy",
                ordinal=ordinal,
            )
    return normalized


def load_aox_attempt_authority_plan(
    path: Path,
    *,
    identity: Mapping[str, object],
    allowed_prerequisites: Mapping[str, object],
    architecture_qualification: Mapping[str, object],
    launch_profile: Mapping[str, object],
) -> dict[str, Any]:
    value = _load_private_canonical(
        path, unreadable_code="attempt_authority_plan_unreadable"
    )
    return validate_aox_attempt_authority_plan(
        value,
        identity=identity,
        allowed_prerequisites=allowed_prerequisites,
        architecture_qualification=architecture_qualification,
        launch_profile=launch_profile,
    )


def publish_aox_attempt_authority_plan(
    plan: Mapping[str, object], path: Path
) -> None:
    if plan.get("schema_id") != AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID:
        _reject(
            "attempt_authority_plan_class_mismatch",
            "formal publisher accepts only the current task-free plan",
        )
    publish_private_canonical_authority(
        path, canonical_json_bytes(dict(plan)) + b"\n"
    )


def attempt_authority_consumption_path(plan_path: Path) -> Path:
    return plan_path.with_name(f"{plan_path.name}.consumed.json")


def attempt_authority_slot_claim_path(plan_path: Path, ordinal: int) -> Path:
    if type(ordinal) is not int or ordinal not in {1, 2, 3}:
        _reject(
            "attempt_authority_slot_ordinal_invalid",
            "formal authority ordinal must be exactly 1, 2, or 3",
        )
    return plan_path.with_name(f"{plan_path.name}.slot-{ordinal}.claimed.json")


def consume_aox_attempt_authority_plan(
    plan: Mapping[str, object], *, plan_path: Path, path: Path
) -> dict[str, Any]:
    if (
        plan.get("schema_id") != AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID
        or not isinstance(plan.get("slots"), list)
        or len(plan["slots"]) != 3
    ):
        _reject(
            "attempt_authority_plan_class_mismatch",
            "formal consumption accepts only the current three-slot plan",
        )
    expected_path = attempt_authority_consumption_path(plan_path)
    if path != expected_path:
        _reject(
            "attempt_authority_consumption_target_mismatch",
            "authority consumption must use its deterministic sibling target",
            expected_file=expected_path.name,
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
    publish_private_canonical_authority(path, canonical_json_bytes(receipt) + b"\n")
    return receipt


def load_aox_attempt_authority_consumption(
    path: Path, *, plan: Mapping[str, object], plan_path: Path
) -> dict[str, Any]:
    if path != attempt_authority_consumption_path(plan_path):
        _reject(
            "attempt_authority_consumption_invalid",
            "formal consumption must be its deterministic sibling",
        )
    normalized = _load_private_canonical(
        path, unreadable_code="attempt_authority_consumption_unreadable"
    )
    expected = {
        "schema_id": AOX_ATTEMPT_AUTHORITY_CONSUMPTION_SCHEMA_ID,
        "run_class": AoxLiveRunClass.FORMAL_ACCEPTANCE.value,
        "plan_schema_id": AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID,
        "plan_digest": plan.get("plan_digest"),
        "campaign_id": plan.get("campaign_id"),
        "consumption_file": attempt_authority_consumption_path(plan_path).name,
    }
    if (
        plan.get("schema_id") != AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID
        or set(normalized) != _CONSUMPTION_FIELDS
        or any(normalized.get(key) != value for key, value in expected.items())
    ):
        _reject(
            "attempt_authority_consumption_invalid",
            "formal consumption does not bind the current exact plan",
        )
    _timestamp(
        normalized.get("consumed_at"),
        code="attempt_authority_consumption_invalid",
        label="consumed_at",
    )
    return normalized


def _claim_identity(
    *,
    plan: Mapping[str, object],
    slot: Mapping[str, object],
    ordinal: int,
    campaign_root: Path,
) -> tuple[str, str]:
    root_identity = canonical_digest(
        {"campaign_root": str(campaign_root.expanduser().absolute())}
    )
    launch_id = "formal-slot-" + canonical_digest(
        {
            "campaign_id": plan.get("campaign_id"),
            "ordinal": ordinal,
            "session_id": slot.get("session_id"),
            "root_ref": slot.get("root_ref"),
            "authority_policy_digest": slot.get("authority_policy_digest"),
            "campaign_root_identity": root_identity,
        }
    ).removeprefix("sha256:")[:24]
    return launch_id, root_identity


def _claim_payload(
    *, plan: Mapping[str, object], consumption: Mapping[str, object],
    slot: Mapping[str, object], plan_path: Path, ordinal: int,
    campaign_root: Path, claimed_at: object,
) -> dict[str, Any]:
    launch_id, root_identity = _claim_identity(
        plan=plan, slot=slot, ordinal=ordinal, campaign_root=campaign_root
    )
    return {
        "schema_id": AOX_ATTEMPT_AUTHORITY_SLOT_CLAIM_SCHEMA_ID,
        "run_class": AoxLiveRunClass.FORMAL_ACCEPTANCE.value,
        "campaign_id": plan.get("campaign_id"),
        "plan_digest": plan.get("plan_digest"),
        "consumption_digest": canonical_digest(dict(consumption)),
        "ordinal": ordinal,
        "attempt_kind": slot.get("attempt_kind"),
        "launch_id": launch_id,
        "session_id": slot.get("session_id"),
        "root_ref": slot.get("root_ref"),
        "authority_policy_digest": slot.get("authority_policy_digest"),
        "campaign_root_identity": root_identity,
        "claim_file": attempt_authority_slot_claim_path(plan_path, ordinal).name,
        "claimed_at": claimed_at,
    }


def claim_aox_attempt_authority_slot(
    *,
    plan: Mapping[str, object],
    consumption: Mapping[str, object],
    plan_path: Path,
    ordinal: int,
    campaign_root: Path,
) -> dict[str, Any]:
    """Atomically claim one task-free slot without inventing task truth."""

    slots = plan.get("slots")
    if (
        plan.get("schema_id") != AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID
        or not isinstance(slots, list)
        or len(slots) != 3
        or type(ordinal) is not int
        or ordinal not in {1, 2, 3}
        or consumption.get("schema_id")
        != AOX_ATTEMPT_AUTHORITY_CONSUMPTION_SCHEMA_ID
        or consumption.get("plan_digest") != plan.get("plan_digest")
    ):
        _reject(
            "attempt_authority_slot_claim_invalid",
            "formal claim requires one current consumed three-slot plan",
        )
    slot = dict(slots[ordinal - 1])
    if slot.get("ordinal") != ordinal:
        _reject(
            "attempt_authority_slot_claim_invalid",
            "formal slot ordinal does not reproduce its plan position",
        )
    claim_path = attempt_authority_slot_claim_path(plan_path, ordinal)
    payload = _claim_payload(
        plan=plan, consumption=consumption, slot=slot, plan_path=plan_path,
        ordinal=ordinal, campaign_root=campaign_root, claimed_at=_utc_now(),
    )
    claim = {**payload, "claim_digest": canonical_digest(payload)}
    publish_private_canonical_authority(
        claim_path, canonical_json_bytes(claim) + b"\n"
    )
    return claim


def load_aox_attempt_authority_slot_claim(
    path: Path,
    *,
    plan: Mapping[str, object],
    consumption: Mapping[str, object],
    plan_path: Path,
    ordinal: int,
    campaign_root: Path,
) -> dict[str, Any]:
    if path != attempt_authority_slot_claim_path(plan_path, ordinal):
        _reject(
            "attempt_authority_slot_claim_invalid",
            "formal claim must be its deterministic sibling",
        )
    normalized = _load_private_canonical(
        path, unreadable_code="attempt_authority_slot_claim_unreadable"
    )
    slots = plan.get("slots")
    slot = (
        dict(slots[ordinal - 1])
        if isinstance(slots, list) and len(slots) == 3 and ordinal in {1, 2, 3}
        else {}
    )
    expected = _claim_payload(
        plan=plan, consumption=consumption, slot=slot, plan_path=plan_path,
        ordinal=ordinal, campaign_root=campaign_root,
        claimed_at=normalized.get("claimed_at"),
    )
    payload = {
        key: value for key, value in normalized.items() if key != "claim_digest"
    }
    valid = all(
        (
            plan.get("schema_id") == AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID,
            consumption.get("schema_id")
            == AOX_ATTEMPT_AUTHORITY_CONSUMPTION_SCHEMA_ID,
            set(normalized) == _CLAIM_FIELDS,
            payload == expected,
            normalized.get("claim_digest") == canonical_digest(payload),
        )
    )
    if not valid:
        _reject(
            "attempt_authority_slot_claim_invalid",
            "formal claim does not bind its current exact slot and campaign root",
        )
    _timestamp(
        normalized.get("claimed_at"),
        code="attempt_authority_slot_claim_invalid",
        label="claimed_at",
    )
    return normalized


def authority_grant_identity(
    slot: Mapping[str, object], *, campaign_id: str, task_id: str
) -> tuple[str, str, dict[str, Any]]:
    """Late-bind one consumed task-free slot to a canonical execution task."""

    return scientific_attempt_authorization_identity(
        session_id=str(slot["session_id"]),
        task_id=task_id,
        campaign_id=campaign_id,
        root_ref=str(slot["root_ref"]),
        **dict(slot["authority_policy"]),
    )


def authority_grant_payload(
    slot: Mapping[str, object], *, campaign_id: str, task_id: str
) -> dict[str, Any]:
    """Project a late-bound request into the public Host payload."""

    _, _, canonical_request = authority_grant_identity(
        slot, campaign_id=campaign_id, task_id=task_id
    )
    request = dict(canonical_request)
    for key in ("command", "session_id", "grantor_ref", "idempotency_key"):
        request.pop(key)
    return request
