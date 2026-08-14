from __future__ import annotations

from collections.abc import Mapping
import re

from openzyme_engines import PODMAN_SANDBOX_PREFLIGHT_FAILURE_CODES


AOX_CUTOVER_LAUNCH_FAILURE_SCHEMA_ID = "aox_cutover_launch_failure@4"
LEGACY_AOX_CUTOVER_LAUNCH_FAILURE_SCHEMA_ID = "aox_cutover_launch_failure@3"

_ERROR_CODE = re.compile(r"[a-z][a-z0-9_.-]{0,127}")
_SCHEMA_PATH = re.compile(r"[A-Za-z][A-Za-z0-9_.\[\]-]{0,255}")
_SCHEMA_FIELD = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}")
_RUNNER_TOOL_ID = re.compile(r"[a-z][a-z0-9._-]{0,127}")
_RUNNER_ERROR_CODE = re.compile(
    r"(?:[A-Z][A-Z0-9_]{0,63}|[a-z][a-z0-9_]{0,95})"
)
_RUNNER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_CONFIG_CANDIDATE_ID = re.compile(r"aox-config-[0-9a-f]{32}")
_RUNNER_STAGES = frozenset({"runner_call", "runner_result"})
_RUNNER_PHASES = frozenset(
    "allocated transport_ready remote_layout_ready input_staging inputs_verified "
    "preflight_passed dispatch_prepared dispatching remote_pending remote_terminal "
    "outputs_fetching outputs_verified terminal".split()
)
_RUNNER_EFFECT_CERTAINTIES = frozenset(
    "no_effect dispatch_in_doubt effect_known terminal_known unproven".split()
)
_RETRY_ELIGIBILITIES = frozenset(
    "same_phase_safe verify_then_retry reconcile_required terminal".split()
)


class AoxCutoverLaunchError(RuntimeError):
    """Typed private launch error with independently authorized public projections."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
        public_occurrence: Mapping[str, object] | None = None,
        public_cause: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = {} if details is None else dict(details)
        self.public_occurrence = {} if public_occurrence is None else dict(public_occurrence)
        self.public_cause = {} if public_cause is None else dict(public_cause)


class AoxLaunchFailureSchemaError(ValueError):
    def __init__(self, identity: str) -> None:
        super().__init__(f"invalid AOX launch failure field: {identity}")
        self.identity = identity


def _matches(pattern: re.Pattern[str], value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _normalize_config_candidate_occurrence(
    raw: Mapping[str, object],
) -> dict[str, object] | None:
    expected = set(
        "kind phase effect_certainty retry_eligibility reconciliation_required "
        "terminal_scope request_digest idempotency_key exact_handle contract_digest "
        "candidate_id".split()
    )
    if set(raw) != expected or raw.get("phase") not in {"validation", "publication"}:
        return None
    if any(not _matches(_DIGEST, raw.get(key)) for key in (
        "request_digest", "contract_digest"
    )) or any(not _matches(_CONFIG_CANDIDATE_ID, raw.get(key)) for key in (
        "idempotency_key", "exact_handle", "candidate_id"
    )):
        return None
    if (
        raw["idempotency_key"] != raw["candidate_id"]
        or raw["exact_handle"] != raw["candidate_id"]
    ):
        return None
    facts = (
        raw["effect_certainty"],
        raw["retry_eligibility"],
        raw["reconciliation_required"],
        raw["terminal_scope"],
    )
    valid_facts = (
        {("no_effect", "terminal", False, "config_candidate_occurrence")}
        if raw["phase"] == "validation"
        else {
            ("no_effect", "terminal", False, "config_candidate_publication_occurrence"),
            (
                "unproven", "reconcile_required", True,
                "config_candidate_publication_occurrence",
            ),
        }
    )
    if facts not in valid_facts:
        return None
    return dict(raw)


def _normalize_runner_occurrence(
    raw: Mapping[str, object],
) -> dict[str, object] | None:
    required = set(
        "kind tool_id stage phase effect_certainty retry_eligibility "
        "reconciliation_required terminal_scope authority_scope "
        "scientific_attempt_counted".split()
    )
    optional = set(
        "runner_run_id runner_attempt_receipt_digest request_digest "
        "reservation_identity_digest idempotency_key".split()
    )
    if not required <= set(raw) or not set(raw) <= required | optional:
        return None
    tool_id = raw.get("tool_id")
    retry = raw.get("retry_eligibility")
    if (
        not _matches(_RUNNER_TOOL_ID, tool_id)
        or raw.get("stage") not in _RUNNER_STAGES
        or raw.get("phase") not in _RUNNER_PHASES
        or raw.get("effect_certainty") not in _RUNNER_EFFECT_CERTAINTIES
        or retry not in _RETRY_ELIGIBILITIES
        or not isinstance(raw.get("reconciliation_required"), bool)
        or raw["reconciliation_required"] != (retry == "reconcile_required")
        or raw.get("terminal_scope") != "runner_operation_occurrence"
        or raw.get("authority_scope") != "preparation_only"
        or raw.get("scientific_attempt_counted") is not False
    ):
        return None
    normalized = {key: raw[key] for key in required}
    if "runner_run_id" in raw:
        value = raw["runner_run_id"]
        if not _matches(_RUNNER_ID, value):
            return None
        normalized["runner_run_id"] = value
    for key in (
        "runner_attempt_receipt_digest",
        "request_digest",
        "reservation_identity_digest",
        "idempotency_key",
    ):
        if key not in raw:
            continue
        value = raw[key]
        if not _matches(_DIGEST, value):
            return None
        normalized[key] = value
    if "idempotency_key" in raw and raw.get("idempotency_key") != raw.get(
        "reservation_identity_digest"
    ):
        return None
    return normalized


def _normalize_occurrence(raw: Mapping[str, object]) -> dict[str, object] | None:
    kind = raw.get("kind")
    if kind == "config_candidate":
        return _normalize_config_candidate_occurrence(raw)
    if kind == "runner_attestation":
        return _normalize_runner_occurrence(raw)
    return None


def _normalize_cause(raw: Mapping[str, object]) -> dict[str, object] | None:
    kind = raw.get("kind")
    if kind == "sandbox_runtime":
        if (
            set(raw) != {"kind", "failure_code"}
            or raw.get("failure_code") not in PODMAN_SANDBOX_PREFLIGHT_FAILURE_CODES
        ):
            return None
        return dict(raw)
    if kind == "runner_error":
        code = raw.get("failure_code")
        if (
            set(raw) != {"kind", "failure_code"}
            or not _matches(_RUNNER_ERROR_CODE, code)
        ):
            return None
        return dict(raw)
    if kind != "schema_field" or not set(raw).issubset(
        {"kind", "identity", "missing", "unexpected"}
    ):
        return None
    identity = raw.get("identity")
    if not _matches(_SCHEMA_PATH, identity):
        return None
    normalized: dict[str, object] = {"kind": kind, "identity": identity}
    for key in ("missing", "unexpected"):
        if key not in raw:
            continue
        values = raw[key]
        if (
            not isinstance(values, (list, tuple))
            or any(
                not _matches(_SCHEMA_FIELD, value)
                for value in values
            )
            or list(values) != sorted(set(values))
        ):
            return None
        normalized[key] = list(values)
    return normalized


def _normalize_legacy_details(
    raw: Mapping[str, object],
) -> dict[str, object] | None:
    if raw.get("kind") not in {"schema_field", "sandbox_runtime"}:
        return None
    return _normalize_cause(raw)


def aox_cutover_launch_failure_payload(
    error: AoxCutoverLaunchError,
) -> dict[str, object]:
    """Serialize independently safe occurrence and cause facts to current @4."""

    payload: dict[str, object] = {
        "schema_id": AOX_CUTOVER_LAUNCH_FAILURE_SCHEMA_ID,
        "status": "failed",
        "failure_code": error.code,
    }
    occurrence = _normalize_occurrence(error.public_occurrence)
    cause = _normalize_cause(error.public_cause)
    if occurrence is not None:
        payload["failure_occurrence"] = occurrence
    if cause is not None:
        payload["failure_cause"] = cause
    return payload


def normalize_aox_cutover_launch_failure(
    value: Mapping[str, object],
    *,
    allow_legacy_v3: bool = False,
) -> dict[str, object]:
    """Validate a closed public launch failure without promoting legacy writers."""

    failure = dict(value)
    required = {"schema_id", "status", "failure_code"}
    if (
        failure.get("status") != "failed"
        or not isinstance(failure.get("failure_code"), str)
        or _ERROR_CODE.fullmatch(str(failure["failure_code"])) is None
    ):
        raise AoxLaunchFailureSchemaError("failure")
    if failure.get("schema_id") == AOX_CUTOVER_LAUNCH_FAILURE_SCHEMA_ID:
        if not required <= set(failure) or not set(failure) <= required | {
            "failure_occurrence",
            "failure_cause",
        }:
            raise AoxLaunchFailureSchemaError("failure")
        occurrence = failure.get("failure_occurrence")
        cause = failure.get("failure_cause")
        if occurrence is not None:
            if not isinstance(occurrence, Mapping):
                raise AoxLaunchFailureSchemaError("failure.failure_occurrence")
            normalized_occurrence = _normalize_occurrence(occurrence)
            if normalized_occurrence is None:
                raise AoxLaunchFailureSchemaError("failure.failure_occurrence")
            failure["failure_occurrence"] = normalized_occurrence
        if cause is not None:
            if not isinstance(cause, Mapping):
                raise AoxLaunchFailureSchemaError("failure.failure_cause")
            normalized_cause = _normalize_cause(cause)
            if normalized_cause is None:
                raise AoxLaunchFailureSchemaError("failure.failure_cause")
            failure["failure_cause"] = normalized_cause
        return failure
    if not allow_legacy_v3 or failure.get("schema_id") != (
        LEGACY_AOX_CUTOVER_LAUNCH_FAILURE_SCHEMA_ID
    ):
        raise AoxLaunchFailureSchemaError("failure.schema_id")
    if frozenset(failure) not in {
        frozenset(required),
        frozenset(required | {"failure_details"}),
    }:
        raise AoxLaunchFailureSchemaError("failure")
    details = failure.get("failure_details")
    if details is not None:
        if not isinstance(details, Mapping):
            raise AoxLaunchFailureSchemaError("failure.failure_details")
        normalized_details = _normalize_legacy_details(details)
        if normalized_details is None:
            raise AoxLaunchFailureSchemaError("failure.failure_details")
        failure["failure_details"] = normalized_details
    return failure


__all__ = [
    "AOX_CUTOVER_LAUNCH_FAILURE_SCHEMA_ID",
    "LEGACY_AOX_CUTOVER_LAUNCH_FAILURE_SCHEMA_ID",
    "AoxCutoverLaunchError",
    "AoxLaunchFailureSchemaError",
    "aox_cutover_launch_failure_payload",
    "normalize_aox_cutover_launch_failure",
]
