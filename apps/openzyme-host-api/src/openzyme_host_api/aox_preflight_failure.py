from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import stat
from typing import Any

from .aox_architecture_qualification import (
    AoxArchitectureQualificationError,
    normalize_architecture_qualification_receipt,
)
from .aox_attempt_authority import (
    AOX_ATTEMPT_AUTHORITY_CONSUMPTION_SCHEMA_ID,
    AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID,
    attempt_authority_consumption_path,
    attempt_authority_slot_claim_path,
)
from .aox_authority_storage import publish_private_canonical_authority
from .aox_cutover_evidence import (
    CutoverEvidenceError,
    VerificationIssue,
    _normalize_identity,
    _write_append_only_bytes,
    assert_formal_campaign_root,
    canonical_digest,
    canonical_json_bytes,
    normalize_aox_cutover_prerequisites,
)
from .aox_launch_profile import (
    launch_profile_digest,
    normalize_aox_cutover_launch_profile,
)
from .aox_live_run_class import AoxLiveRunClass
from .aox_launch_failure import AOX_CUTOVER_LAUNCH_FAILURE_SCHEMA_ID
from .aox_launch_failure import LEGACY_AOX_CUTOVER_LAUNCH_FAILURE_SCHEMA_ID
from .aox_launch_failure import AoxLaunchFailureSchemaError
from .aox_launch_failure import normalize_aox_cutover_launch_failure


FORMAL_PREFLIGHT_FAILURE_SCHEMA_ID = "aox_formal_preflight_failure@2"
LEGACY_FORMAL_PREFLIGHT_FAILURE_SCHEMA_IDS = frozenset(
    {"aox_formal_preflight_failure@1"}
)
_FORMAL_PREFLIGHT_FAILURE_STAGE = "actual_launch_guard_pre_slot_claim"
_LEGACY_FORMAL_PREFLIGHT_FAILURE_STAGE = "effective_config_pre_slot_claim"
FORMAL_PREFLIGHT_FAILURE_DECISION_SCHEMA_ID = (
    "aox_blank_world_campaign_preflight_failure_decision@1"
)

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_ERROR_CODE = re.compile(r"[a-z][a-z0-9_.-]{0,127}")
_RECEIPT_FIELDS = {
    "schema_id",
    "sealed_at",
    "run_class",
    "acceptance_eligible",
    "state_reusable",
    "failed_stage",
    "campaign_id",
    "plan_digest",
    "consumption_digest",
    "launch_profile_digest",
    "slot_ordinal",
    "attempt_kind",
    "session_id",
    "root_ref",
    "authority_policy_digest",
    "campaign_root_identity",
    "authority_plan_file",
    "authority_consumption_file",
    "identity",
    "allowed_prerequisites",
    "architecture_qualification",
    "launch_profile",
    "authority_plan",
    "authority_consumption",
    "failure",
    "effect_closure",
    "receipt_digest",
}
_EFFECT_CLOSURE = {
    "effect_certainty": "no_effect",
    "slot_claim_created": False,
    "campaign_attempt_root_created": False,
    "host_started": False,
    "session_created": False,
    "scientific_attempt_count": 0,
    "micu_delta": 0,
    "provider_dispatch_started": False,
    "runner_dispatch_started": False,
    "hpc_dispatch_started": False,
    "browser_action_started": False,
}
_DECISION_FIELDS = {
    "schema_id",
    "decided_at",
    "decision",
    "campaign_id",
    "plan_digest",
    "slot_ordinal",
    "attempt_kind",
    "preflight_failure_digest",
    "attempt_digests",
    "attempt_ids",
    "blocker",
    "decision_digest",
}
_BLOCKER_FIELDS = {"code", "identity", "message"}
_PLAN_FIELDS = {
    "schema_id",
    "campaign_id",
    "identity_digest",
    "allowed_prerequisite_digest",
    "architecture_qualification_digest",
    "launch_profile_digest",
    "issued_at",
    "expires_at",
    "slots",
    "plan_digest",
}
_SLOT_FIELDS = {
    "ordinal",
    "attempt_kind",
    "session_id",
    "root_ref",
    "scope",
    "authority_policy",
    "authority_policy_digest",
}


@dataclass(frozen=True, slots=True)
class FormalPreflightFailureVerification:
    passed: bool
    failure_digest: str | None
    campaign_id: str | None
    plan_digest: str | None
    attempt_kind: str | None
    slot_ordinal: int | None
    issue: VerificationIssue | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": "aox_formal_preflight_failure_verification@1",
            "passed": self.passed,
            "failure_digest": self.failure_digest,
            "campaign_id": self.campaign_id,
            "plan_digest": self.plan_digest,
            "attempt_kind": self.attempt_kind,
            "slot_ordinal": self.slot_ordinal,
            "issue": None if self.issue is None else self.issue.to_dict(),
        }


def _fail(code: str, message: str, *, identity: str) -> None:
    raise CutoverEvidenceError(code, message, details={"identity": identity})


def _aware_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _load_private_canonical(path: Path, *, identity: str) -> dict[str, Any]:
    candidate = path.expanduser().absolute()
    try:
        metadata = candidate.lstat()
        content = candidate.read_bytes()
        value = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CutoverEvidenceError(
            "formal_preflight_failure_source_unreadable",
            "formal preflight failure source is unreadable canonical JSON",
            details={"identity": identity},
        ) from exc
    if not all(
        (
            stat.S_ISREG(metadata.st_mode),
            not stat.S_ISLNK(metadata.st_mode),
            stat.S_IMODE(metadata.st_mode) & 0o077 == 0,
            candidate.resolve(strict=True) == candidate,
            isinstance(value, dict),
            isinstance(value, dict) and content == canonical_json_bytes(value) + b"\n",
        )
    ):
        _fail(
            "formal_preflight_failure_source_invalid",
            "formal preflight failure source must be one private canonical file",
            identity=identity,
        )
    return dict(value)


def formal_preflight_failure_path(plan_path: Path, ordinal: int) -> Path:
    if type(ordinal) is not int or ordinal not in {1, 2, 3}:
        _fail(
            "formal_preflight_failure_slot_invalid",
            "formal preflight failure requires slot 1, 2, or 3",
            identity="slot_ordinal",
        )
    return plan_path.with_name(
        f"{plan_path.name}.slot-{ordinal}.preflight-failure.json"
    )


def _normalize_preflight_launch_failure(
    value: Mapping[str, object],
    *,
    legacy: bool = False,
) -> dict[str, object]:
    try:
        failure = normalize_aox_cutover_launch_failure(
            value,
            allow_legacy_v3=legacy,
        )
    except AoxLaunchFailureSchemaError as exc:
        _fail(
            "formal_preflight_failure_cause_invalid",
            "preflight failure cause is not the closed public schema",
            identity=exc.identity,
        )
    if legacy:
        if failure["schema_id"] != LEGACY_AOX_CUTOVER_LAUNCH_FAILURE_SCHEMA_ID:
            _fail(
                "formal_preflight_failure_cause_invalid",
                "historical preflight evidence requires the historical launch schema",
                identity="failure.schema_id",
            )
        projection = failure.get("failure_details")
    else:
        if failure["schema_id"] != AOX_CUTOVER_LAUNCH_FAILURE_SCHEMA_ID:
            _fail(
                "formal_preflight_failure_cause_invalid",
                "current preflight evidence requires the current launch schema",
                identity="failure.schema_id",
            )
        if "failure_occurrence" in failure:
            _fail(
                "formal_preflight_failure_cause_invalid",
                "preflight launch guard cannot adopt another occurrence identity",
                identity="failure.failure_occurrence",
            )
        projection = failure.get("failure_cause")
    if isinstance(projection, Mapping) and projection.get("kind") not in {
        "schema_field",
        "sandbox_runtime",
    }:
        _fail(
            "formal_preflight_failure_cause_invalid",
            "preflight launch guard accepts only schema or sandbox causes",
            identity="failure",
        )
    return failure


def _campaign_root_identity(campaign_root: Path) -> str:
    assert_formal_campaign_root(campaign_root)
    candidate = campaign_root.expanduser().absolute()
    try:
        parent = candidate.parent.resolve(strict=True)
    except OSError as exc:
        raise CutoverEvidenceError(
            "formal_preflight_failure_root_invalid",
            "formal campaign root parent is not one existing real directory",
            details={"identity": "campaign_root"},
        ) from exc
    if candidate.parent != parent or parent.is_symlink() or not parent.is_dir():
        _fail(
            "formal_preflight_failure_root_invalid",
            "formal campaign root parent is not one existing real directory",
            identity="campaign_root",
        )
    if candidate.exists() or candidate.is_symlink():
        try:
            metadata = candidate.lstat()
            entries = tuple(candidate.iterdir())
        except OSError as exc:
            raise CutoverEvidenceError(
                "formal_preflight_failure_root_invalid",
                "formal campaign root cannot be inspected",
                details={"identity": "campaign_root"},
            ) from exc
        if not all(
            (
                stat.S_ISDIR(metadata.st_mode),
                not stat.S_ISLNK(metadata.st_mode),
                candidate.resolve(strict=True) == candidate,
                stat.S_IMODE(metadata.st_mode) & 0o077 == 0,
                not entries,
            )
        ):
            _fail(
                "formal_preflight_failure_root_not_pristine",
                "preflight failure requires an absent or empty private campaign root",
                identity="campaign_root",
            )
    return canonical_digest({"campaign_root": str(candidate)})


def _validate_embedded_sources(
    receipt: Mapping[str, Any],
    *,
    receipt_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ordinal = receipt.get("slot_ordinal")
    if type(ordinal) is not int or ordinal not in {1, 2, 3}:
        _fail(
            "formal_preflight_failure_slot_invalid",
            "formal preflight failure slot is invalid",
            identity="slot_ordinal",
        )
    plan_file = receipt.get("authority_plan_file")
    consumption_file = receipt.get("authority_consumption_file")
    if (
        not isinstance(plan_file, str)
        or not plan_file
        or Path(plan_file).name != plan_file
        or not isinstance(consumption_file, str)
        or not consumption_file
        or Path(consumption_file).name != consumption_file
    ):
        _fail(
            "formal_preflight_failure_source_binding_invalid",
            "formal preflight failure source names are unsafe",
            identity="authority_sources",
        )
    plan_path = receipt_path.parent / plan_file
    consumption_path = receipt_path.parent / consumption_file
    if receipt_path != formal_preflight_failure_path(plan_path, ordinal):
        _fail(
            "formal_preflight_failure_path_invalid",
            "formal preflight failure is not the deterministic plan sibling",
            identity="formal_preflight_failure",
        )
    if consumption_path != attempt_authority_consumption_path(plan_path):
        _fail(
            "formal_preflight_failure_source_binding_invalid",
            "formal preflight failure consumption source is not deterministic",
            identity="authority_consumption_file",
        )
    plan = _load_private_canonical(plan_path, identity="authority_plan")
    consumption = _load_private_canonical(
        consumption_path,
        identity="authority_consumption",
    )
    if plan != receipt.get("authority_plan") or consumption != receipt.get(
        "authority_consumption"
    ):
        _fail(
            "formal_preflight_failure_source_digest_mismatch",
            "formal preflight failure authority sources drifted",
            identity="authority_sources",
        )
    claim_path = attempt_authority_slot_claim_path(plan_path, ordinal)
    if claim_path.exists() or claim_path.is_symlink():
        _fail(
            "formal_preflight_failure_claim_exists",
            "preflight failure cannot coexist with a slot claim",
            identity="slot_claim",
        )
    return plan, consumption, dict(plan["slots"][ordinal - 1])


def _validate_receipt(
    value: Mapping[str, Any],
    *,
    path: Path,
) -> dict[str, Any]:
    receipt = dict(value)
    if set(receipt) != _RECEIPT_FIELDS:
        _fail(
            "formal_preflight_failure_schema_invalid",
            "formal preflight failure is not the current closed schema",
            identity="formal_preflight_failure",
        )
    legacy = receipt.get("schema_id") in LEGACY_FORMAL_PREFLIGHT_FAILURE_SCHEMA_IDS
    if receipt.get("schema_id") != FORMAL_PREFLIGHT_FAILURE_SCHEMA_ID and not legacy:
        _fail(
            "formal_preflight_failure_schema_invalid",
            "formal preflight failure schema is unsupported",
            identity="formal_preflight_failure.schema_id",
        )
    plan, consumption, slot = _validate_embedded_sources(receipt, receipt_path=path)
    identity = _normalize_identity(dict(receipt.get("identity") or {}))
    prerequisites = normalize_aox_cutover_prerequisites(
        dict(receipt.get("allowed_prerequisites") or {}),
        identity=identity,
    )
    qualification = normalize_architecture_qualification_receipt(
        dict(receipt.get("architecture_qualification") or {}),
        expected_source_commit=str(identity["git_commit"]),
    )
    profile = normalize_aox_cutover_launch_profile(
        dict(receipt.get("launch_profile") or {})
    )
    failure = _normalize_preflight_launch_failure(
        dict(receipt.get("failure") or {}),
        legacy=legacy,
    )
    plan_payload = {key: item for key, item in plan.items() if key != "plan_digest"}
    expected_consumption = {
        "schema_id": AOX_ATTEMPT_AUTHORITY_CONSUMPTION_SCHEMA_ID,
        "run_class": AoxLiveRunClass.FORMAL_ACCEPTANCE.value,
        "plan_schema_id": AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID,
        "plan_digest": plan.get("plan_digest"),
        "campaign_id": plan.get("campaign_id"),
        "consumption_file": receipt["authority_consumption_file"],
    }
    source_bindings_valid = all(
        (
            set(plan) == _PLAN_FIELDS,
            plan.get("schema_id") == AOX_ATTEMPT_AUTHORITY_PLAN_SCHEMA_ID,
            plan.get("plan_digest") == canonical_digest(plan_payload),
            isinstance(plan.get("slots"), list) and len(plan["slots"]) == 3,
            set(slot) == _SLOT_FIELDS,
            slot.get("ordinal") == receipt.get("slot_ordinal"),
            receipt.get("identity") == identity,
            receipt.get("allowed_prerequisites") == prerequisites,
            receipt.get("architecture_qualification") == qualification,
            receipt.get("launch_profile") == profile,
            plan.get("identity_digest") == canonical_digest(identity),
            plan.get("allowed_prerequisite_digest") == canonical_digest(prerequisites),
            plan.get("architecture_qualification_digest")
            == canonical_digest(qualification),
            plan.get("launch_profile_digest") == launch_profile_digest(profile),
            profile.get("source_commit") == identity.get("git_commit"),
            profile.get("config_digest") == identity.get("config_digest"),
            set(consumption)
            == {
                *expected_consumption,
                "consumed_at",
            },
            all(
                consumption.get(key) == expected
                for key, expected in expected_consumption.items()
            ),
            _aware_timestamp(consumption.get("consumed_at")),
        )
    )
    payload = {key: item for key, item in receipt.items() if key != "receipt_digest"}
    semantics_valid = all(
        (
            receipt.get("run_class") == AoxLiveRunClass.FORMAL_ACCEPTANCE.value,
            receipt.get("acceptance_eligible") is False,
            receipt.get("state_reusable") is False,
            receipt.get("failed_stage")
            == (
                _LEGACY_FORMAL_PREFLIGHT_FAILURE_STAGE
                if legacy
                else _FORMAL_PREFLIGHT_FAILURE_STAGE
            ),
            _aware_timestamp(receipt.get("sealed_at")),
            receipt.get("campaign_id") == plan.get("campaign_id"),
            receipt.get("plan_digest") == plan.get("plan_digest"),
            receipt.get("consumption_digest") == canonical_digest(consumption),
            receipt.get("launch_profile_digest") == launch_profile_digest(profile),
            receipt.get("attempt_kind") == slot.get("attempt_kind"),
            receipt.get("session_id") == slot.get("session_id"),
            receipt.get("root_ref") == slot.get("root_ref"),
            receipt.get("authority_policy_digest")
            == slot.get("authority_policy_digest"),
            _DIGEST.fullmatch(str(receipt.get("campaign_root_identity") or ""))
            is not None,
            receipt.get("effect_closure") == _EFFECT_CLOSURE,
            receipt.get("failure") == failure,
            receipt.get("receipt_digest") == canonical_digest(payload),
            source_bindings_valid,
        )
    )
    if not semantics_valid:
        _fail(
            "formal_preflight_failure_semantics_invalid",
            "formal preflight failure does not prove one no-effect pre-root failure",
            identity="formal_preflight_failure",
        )
    return receipt


def seal_formal_preflight_failure(
    *,
    plan_path: Path,
    campaign_root: Path,
    slot_ordinal: int,
    identity: Mapping[str, object],
    allowed_prerequisites: Mapping[str, object],
    architecture_qualification: Mapping[str, object],
    launch_profile: Mapping[str, object],
    authority_plan: Mapping[str, object],
    authority_consumption: Mapping[str, object],
    failure: Mapping[str, object],
    sealed_at: str | None = None,
) -> tuple[Path, str]:
    resolved_plan_path = plan_path.expanduser().resolve(strict=True)
    slot_claim_path = attempt_authority_slot_claim_path(
        resolved_plan_path,
        slot_ordinal,
    )
    if slot_claim_path.exists() or slot_claim_path.is_symlink():
        _fail(
            "formal_preflight_failure_claim_exists",
            "preflight failure cannot be sealed after a slot claim",
            identity="slot_claim",
        )
    campaign_root_identity = _campaign_root_identity(campaign_root)
    plan = dict(authority_plan)
    consumption = dict(authority_consumption)
    slots = plan.get("slots")
    if not isinstance(slots, list) or len(slots) != 3:
        _fail(
            "formal_preflight_failure_plan_invalid",
            "preflight failure requires one current three-slot authority plan",
            identity="authority_plan",
        )
    slot = dict(slots[slot_ordinal - 1])
    payload: dict[str, Any] = {
        "schema_id": FORMAL_PREFLIGHT_FAILURE_SCHEMA_ID,
        "sealed_at": sealed_at or datetime.now(UTC).isoformat(),
        "run_class": AoxLiveRunClass.FORMAL_ACCEPTANCE.value,
        "acceptance_eligible": False,
        "state_reusable": False,
        "failed_stage": _FORMAL_PREFLIGHT_FAILURE_STAGE,
        "campaign_id": plan.get("campaign_id"),
        "plan_digest": plan.get("plan_digest"),
        "consumption_digest": canonical_digest(consumption),
        "launch_profile_digest": launch_profile_digest(launch_profile),
        "slot_ordinal": slot_ordinal,
        "attempt_kind": slot.get("attempt_kind"),
        "session_id": slot.get("session_id"),
        "root_ref": slot.get("root_ref"),
        "authority_policy_digest": slot.get("authority_policy_digest"),
        "campaign_root_identity": campaign_root_identity,
        "authority_plan_file": resolved_plan_path.name,
        "authority_consumption_file": attempt_authority_consumption_path(
            resolved_plan_path
        ).name,
        "identity": dict(identity),
        "allowed_prerequisites": dict(allowed_prerequisites),
        "architecture_qualification": dict(architecture_qualification),
        "launch_profile": dict(launch_profile),
        "authority_plan": plan,
        "authority_consumption": consumption,
        "failure": _normalize_preflight_launch_failure(failure),
        "effect_closure": dict(_EFFECT_CLOSURE),
    }
    receipt = {**payload, "receipt_digest": canonical_digest(payload)}
    destination = formal_preflight_failure_path(resolved_plan_path, slot_ordinal)
    _validate_receipt(receipt, path=destination)
    publish_private_canonical_authority(
        destination,
        canonical_json_bytes(receipt) + b"\n",
    )
    return destination, str(receipt["receipt_digest"])


def verify_formal_preflight_failure(
    path: Path,
) -> FormalPreflightFailureVerification:
    try:
        resolved = path.expanduser().absolute()
        receipt = _load_private_canonical(
            resolved,
            identity="formal_preflight_failure",
        )
        value = _validate_receipt(receipt, path=resolved)
        return FormalPreflightFailureVerification(
            passed=True,
            failure_digest=str(value["receipt_digest"]),
            campaign_id=str(value["campaign_id"]),
            plan_digest=str(value["plan_digest"]),
            attempt_kind=str(value["attempt_kind"]),
            slot_ordinal=int(value["slot_ordinal"]),
        )
    except (
        CutoverEvidenceError,
        AoxArchitectureQualificationError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        code = (
            exc.code
            if isinstance(exc, CutoverEvidenceError)
            else "formal_preflight_failure_unreadable"
        )
        identity = (
            str(exc.details.get("identity") or "formal_preflight_failure")
            if isinstance(exc, CutoverEvidenceError)
            else "formal_preflight_failure"
        )
        return FormalPreflightFailureVerification(
            passed=False,
            failure_digest=None,
            campaign_id=None,
            plan_digest=None,
            attempt_kind=None,
            slot_ordinal=None,
            issue=VerificationIssue(
                code=code,
                identity=identity,
                message="formal preflight failure verification failed",
            ),
        )


def evaluate_formal_preflight_failure(
    path: Path,
    *,
    decided_at: str | None = None,
) -> dict[str, Any]:
    verification = verify_formal_preflight_failure(path)
    if not verification.passed:
        issue = verification.issue
        raise CutoverEvidenceError(
            "formal_preflight_failure_verification_failed",
            "formal preflight failure must verify before campaign reduction",
            details={
                "identity": (
                    "formal_preflight_failure" if issue is None else issue.identity
                )
            },
        )
    receipt = _load_private_canonical(
        path.expanduser().absolute(),
        identity="formal_preflight_failure",
    )
    failure = dict(receipt["failure"])
    cause = failure.get("failure_cause", failure.get("failure_details"))
    if isinstance(cause, dict) and cause.get("kind") == "sandbox_runtime":
        blocker_identity = f"sandbox_runtime.{cause['failure_code']}"
    elif isinstance(cause, dict) and cause.get("identity"):
        blocker_identity = str(cause["identity"])
    else:
        blocker_identity = "effective_config"
    decision: dict[str, Any] = {
        "schema_id": FORMAL_PREFLIGHT_FAILURE_DECISION_SCHEMA_ID,
        "decided_at": decided_at or datetime.now(UTC).isoformat(),
        "decision": "NO-GO",
        "campaign_id": receipt["campaign_id"],
        "plan_digest": receipt["plan_digest"],
        "slot_ordinal": receipt["slot_ordinal"],
        "attempt_kind": receipt["attempt_kind"],
        "preflight_failure_digest": receipt["receipt_digest"],
        "attempt_digests": [],
        "attempt_ids": [],
        "blocker": {
            "code": failure["failure_code"],
            "identity": blocker_identity,
            "message": (
                "the consumed authority failed before slot claim, campaign attempt "
                "root creation, Host startup, or scientific attempt creation"
            ),
        },
    }
    return {**decision, "decision_digest": canonical_digest(decision)}


def seal_formal_preflight_failure_decision(
    decision: Mapping[str, Any],
    destination: Path,
) -> str:
    value = dict(decision)
    blocker = value.get("blocker")
    payload = {key: item for key, item in value.items() if key != "decision_digest"}
    valid = all(
        (
            set(value) == _DECISION_FIELDS,
            value.get("schema_id") == FORMAL_PREFLIGHT_FAILURE_DECISION_SCHEMA_ID,
            value.get("decision") == "NO-GO",
            _aware_timestamp(value.get("decided_at")),
            isinstance(value.get("campaign_id"), str)
            and bool(value.get("campaign_id")),
            _DIGEST.fullmatch(str(value.get("plan_digest") or "")) is not None,
            type(value.get("slot_ordinal")) is int,
            value.get("slot_ordinal") in {1, 2, 3},
            value.get("attempt_kind") in {"positive", "fault"},
            _DIGEST.fullmatch(str(value.get("preflight_failure_digest") or ""))
            is not None,
            value.get("attempt_digests") == [],
            value.get("attempt_ids") == [],
            isinstance(blocker, dict) and set(blocker) == _BLOCKER_FIELDS,
            isinstance(blocker, dict)
            and _ERROR_CODE.fullmatch(str(blocker.get("code") or "")) is not None,
            isinstance(blocker, dict)
            and isinstance(blocker.get("identity"), str)
            and bool(blocker.get("identity")),
            isinstance(blocker, dict)
            and isinstance(blocker.get("message"), str)
            and bool(blocker.get("message")),
            value.get("decision_digest") == canonical_digest(payload),
        )
    )
    if not valid:
        _fail(
            "formal_preflight_failure_decision_invalid",
            "formal preflight failure decision is not the closed NO-GO schema",
            identity="decision",
        )
    _write_append_only_bytes(
        destination,
        canonical_json_bytes(value) + b"\n",
        error_code="campaign_decision_append_only",
        error_message="campaign decision already exists and cannot be overwritten",
    )
    return str(value["decision_digest"])


__all__ = [
    "FORMAL_PREFLIGHT_FAILURE_DECISION_SCHEMA_ID",
    "FORMAL_PREFLIGHT_FAILURE_SCHEMA_ID",
    "LEGACY_FORMAL_PREFLIGHT_FAILURE_SCHEMA_IDS",
    "FormalPreflightFailureVerification",
    "evaluate_formal_preflight_failure",
    "formal_preflight_failure_path",
    "seal_formal_preflight_failure",
    "seal_formal_preflight_failure_decision",
    "verify_formal_preflight_failure",
]
