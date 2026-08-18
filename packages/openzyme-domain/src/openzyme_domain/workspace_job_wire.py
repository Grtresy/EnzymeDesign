from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
from typing import Any
from typing import Mapping


RUNNER_HANDLE_SCHEMA = "workspace_job_runner_handle@1"
DOMAIN_HANDLE_SCHEMA = "external_job_handle@1"
CANCELLATION_INTENT_SCHEMA = "workspace_job_cancellation_intent@1"
CANCELLATION_RECEIPT_SCHEMA = "workspace_job_cancellation_receipt@1"
OBSERVATION_SCHEMA = "external_job_observation@1"
RECONCILIATION_SCHEMA = "workspace_job_reconciliation@1"

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})
_OBSERVATION_STATES = _TERMINAL_STATES | {"queued", "running", "unknown"}

RUNNER_HANDLE_FIELDS = frozenset(
    {
        "schema_version",
        "disposition",
        "handle_id",
        "execution_id",
        "operation_id",
        "dispatch_id",
        "runner_run_id",
        "job_root_token",
        "target_profile_digest",
        "workspace_id",
        "remote_workspace_generation",
        "source_commit",
        "source_manifest_digest",
        "backend",
        "raw_handle_ciphertext",
        "acceptance_receipt_digest",
        "accepted_at",
        "credential_consumed_at",
        "credential_consumption_receipt_digest",
        "handle_digest",
    }
)
DOMAIN_HANDLE_FIELDS = frozenset(
    {
        "schema_version",
        "handle_id",
        "execution_id",
        "operation_id",
        "dispatch_id",
        "runner_run_id",
        "job_root_token",
        "target_profile_digest",
        "workspace_id",
        "remote_workspace_generation",
        "source_commit",
        "source_manifest_digest",
        "backend",
        "raw_handle_ciphertext",
        "acceptance_receipt_digest",
        "accepted_at",
        "handle_digest",
    }
)
CANCELLATION_INTENT_FIELDS = frozenset(
    {
        "schema_version",
        "cancellation_id",
        "execution_id",
        "handle_id",
        "execution_state_version",
        "execution_fencing_token",
        "idempotency_key",
        "reason_digest",
        "created_at",
    }
)
CANCELLATION_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_id",
        "cancellation_id",
        "handle_id",
        "cancellation_requested",
        "terminal_settlement_proven",
        "backend_receipt_digest",
        "created_at",
        "receipt_digest",
    }
)
OBSERVATION_FIELDS = frozenset(
    {
        "schema_version",
        "observation_id",
        "handle_id",
        "execution_id",
        "dispatch_id",
        "observation_index",
        "state",
        "exit_code",
        "terminal_receipt_digest",
        "bounded_stdout",
        "bounded_stderr",
        "observed_at",
        "observation_digest",
    }
)
RECONCILIATION_FIELDS = frozenset(
    {
        "schema_version",
        "disposition",
        "safe_error_code",
        "reconciliation_receipt_digest",
    }
)


class WorkspaceJobWireContractError(ValueError):
    """A stable, safe failure raised before a workspace-job wire value is used."""

    def __init__(
        self,
        error_code: str,
        *,
        contract: str,
        phase: str,
        field: str | None = None,
        detail: str,
    ) -> None:
        self.error_code = error_code
        self.contract = contract
        self.phase = phase
        self.field = field
        self.detail = detail
        field_text = "" if field is None else f" field={field}"
        super().__init__(
            f"{error_code}: contract={contract} phase={phase}{field_text} detail={detail}"
        )


def canonical_workspace_job_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise WorkspaceJobWireContractError(
            "workspace_job_wire_not_canonical_json",
            contract="workspace_job_wire",
            phase="canonicalize",
            detail=f"{exc.__class__.__name__}: value is not closed JSON",
        ) from exc


def canonical_workspace_job_wire_digest(value: object) -> str:
    encoded = canonical_workspace_job_json(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def require_exact_workspace_job_object(
    value: object,
    *,
    fields: frozenset[str],
    contract: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkspaceJobWireContractError(
            "workspace_job_wire_not_object",
            contract=contract,
            phase="parse",
            detail=f"observed_type={type(value).__name__}",
        )
    observed = {str(key) for key in value}
    if observed != fields or any(not isinstance(key, str) for key in value):
        raise WorkspaceJobWireContractError(
            "workspace_job_wire_fields_mismatch",
            contract=contract,
            phase="parse",
            detail=(
                f"missing={sorted(fields - observed)!r} "
                f"extra={sorted(observed - fields)!r}"
            ),
        )
    return dict(value)


def _fail(
    error_code: str,
    *,
    contract: str,
    phase: str,
    field: str,
    detail: str,
) -> None:
    raise WorkspaceJobWireContractError(
        error_code,
        contract=contract,
        phase=phase,
        field=field,
        detail=detail,
    )


def _require_schema(value: dict[str, Any], schema: str) -> None:
    if value["schema_version"] != schema:
        _fail(
            "workspace_job_wire_schema_unsupported",
            contract=schema,
            phase="parse",
            field="schema_version",
            detail=f"expected={schema!r} observed={value['schema_version']!r}",
        )


def _require_identifier(value: dict[str, Any], field: str, contract: str) -> None:
    observed = value[field]
    if not isinstance(observed, str) or _IDENTIFIER.fullmatch(observed) is None:
        _fail(
            "workspace_job_wire_field_invalid",
            contract=contract,
            phase="validate",
            field=field,
            detail="expected=safe_identifier",
        )


def _require_digest(value: dict[str, Any], field: str, contract: str) -> None:
    observed = value[field]
    if not isinstance(observed, str) or _DIGEST.fullmatch(observed) is None:
        _fail(
            "workspace_job_wire_field_invalid",
            contract=contract,
            phase="validate",
            field=field,
            detail="expected=sha256_digest",
        )


def _require_timestamp(
    value: dict[str, Any],
    field: str,
    contract: str,
    *,
    optional: bool = False,
) -> None:
    observed = value[field]
    if optional and observed is None:
        return
    if not isinstance(observed, str):
        _fail(
            "workspace_job_wire_field_invalid",
            contract=contract,
            phase="validate",
            field=field,
            detail="expected=timezone_aware_iso8601",
        )
    try:
        parsed = datetime.fromisoformat(observed)
    except ValueError as exc:
        raise WorkspaceJobWireContractError(
            "workspace_job_wire_field_invalid",
            contract=contract,
            phase="validate",
            field=field,
            detail="expected=timezone_aware_iso8601",
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(
            "workspace_job_wire_field_invalid",
            contract=contract,
            phase="validate",
            field=field,
            detail="expected=timezone_aware_iso8601",
        )


def _require_positive_int(value: dict[str, Any], field: str, contract: str) -> None:
    observed = value[field]
    if not isinstance(observed, int) or isinstance(observed, bool) or observed < 1:
        _fail(
            "workspace_job_wire_field_invalid",
            contract=contract,
            phase="validate",
            field=field,
            detail="expected=positive_integer",
        )


def _require_expected(
    value: dict[str, Any],
    expected: Mapping[str, object] | None,
    contract: str,
) -> None:
    if expected is None:
        return
    unknown = set(expected) - set(value)
    if unknown:
        _fail(
            "workspace_job_wire_expectation_invalid",
            contract=contract,
            phase="bind_identity",
            field=sorted(unknown)[0],
            detail="expected field is not part of the contract",
        )
    for field, expected_value in expected.items():
        if value[field] != expected_value:
            _fail(
                "workspace_job_wire_identity_mismatch",
                contract=contract,
                phase="bind_identity",
                field=field,
                detail=f"expected={expected_value!r} observed={value[field]!r}",
            )


def _require_payload_digest(
    value: dict[str, Any],
    *,
    digest_field: str,
    contract: str,
) -> None:
    _require_digest(value, digest_field, contract)
    expected = canonical_workspace_job_wire_digest(
        {key: item for key, item in value.items() if key != digest_field}
    )
    if value[digest_field] != expected:
        _fail(
            "workspace_job_wire_digest_mismatch",
            contract=contract,
            phase="verify_digest",
            field=digest_field,
            detail=f"expected={expected} observed={value[digest_field]}",
        )


def parse_workspace_job_runner_handle(
    value: object,
    *,
    expected: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    data = require_exact_workspace_job_object(
        value,
        fields=RUNNER_HANDLE_FIELDS,
        contract=RUNNER_HANDLE_SCHEMA,
    )
    _require_schema(data, RUNNER_HANDLE_SCHEMA)
    for field in (
        "handle_id",
        "execution_id",
        "operation_id",
        "dispatch_id",
        "runner_run_id",
        "job_root_token",
        "workspace_id",
    ):
        _require_identifier(data, field, RUNNER_HANDLE_SCHEMA)
    _require_positive_int(data, "remote_workspace_generation", RUNNER_HANDLE_SCHEMA)
    if not isinstance(data["source_commit"], str) or _OID.fullmatch(data["source_commit"]) is None:
        _fail(
            "workspace_job_wire_field_invalid",
            contract=RUNNER_HANDLE_SCHEMA,
            phase="validate",
            field="source_commit",
            detail="expected=exact_git_oid",
        )
    for field in (
        "target_profile_digest",
        "source_manifest_digest",
        "acceptance_receipt_digest",
    ):
        _require_digest(data, field, RUNNER_HANDLE_SCHEMA)
    if data["disposition"] != "accepted" or data["backend"] not in {"direct", "slurm"}:
        _fail(
            "workspace_job_wire_field_invalid",
            contract=RUNNER_HANDLE_SCHEMA,
            phase="validate",
            field="disposition",
            detail="expected=accepted_with_direct_or_slurm_backend",
        )
    if not isinstance(data["raw_handle_ciphertext"], str) or not data["raw_handle_ciphertext"]:
        _fail(
            "workspace_job_wire_field_invalid",
            contract=RUNNER_HANDLE_SCHEMA,
            phase="validate",
            field="raw_handle_ciphertext",
            detail="expected=non_empty_private_ciphertext",
        )
    _require_timestamp(data, "accepted_at", RUNNER_HANDLE_SCHEMA)
    _require_timestamp(data, "credential_consumed_at", RUNNER_HANDLE_SCHEMA, optional=True)
    credential_digest = data["credential_consumption_receipt_digest"]
    if (data["credential_consumed_at"] is None) != (credential_digest is None):
        _fail(
            "workspace_job_wire_field_invalid",
            contract=RUNNER_HANDLE_SCHEMA,
            phase="validate",
            field="credential_consumption_receipt_digest",
            detail="credential timestamp and receipt must be both present or both absent",
        )
    if credential_digest is not None:
        _require_digest(data, "credential_consumption_receipt_digest", RUNNER_HANDLE_SCHEMA)
    if data["backend"] == "slurm" and credential_digest is None:
        _fail(
            "workspace_job_wire_field_invalid",
            contract=RUNNER_HANDLE_SCHEMA,
            phase="validate",
            field="credential_consumption_receipt_digest",
            detail="slurm handle requires atomic credential consumption proof",
        )
    _require_payload_digest(data, digest_field="handle_digest", contract=RUNNER_HANDLE_SCHEMA)
    _require_expected(data, expected, RUNNER_HANDLE_SCHEMA)
    return data


def parse_external_job_handle(
    value: object,
    *,
    expected: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    data = require_exact_workspace_job_object(
        value,
        fields=DOMAIN_HANDLE_FIELDS,
        contract=DOMAIN_HANDLE_SCHEMA,
    )
    _require_schema(data, DOMAIN_HANDLE_SCHEMA)
    for field in (
        "handle_id",
        "execution_id",
        "operation_id",
        "dispatch_id",
        "runner_run_id",
        "job_root_token",
        "workspace_id",
    ):
        _require_identifier(data, field, DOMAIN_HANDLE_SCHEMA)
    _require_positive_int(data, "remote_workspace_generation", DOMAIN_HANDLE_SCHEMA)
    if not isinstance(data["source_commit"], str) or _OID.fullmatch(data["source_commit"]) is None:
        _fail(
            "workspace_job_wire_field_invalid",
            contract=DOMAIN_HANDLE_SCHEMA,
            phase="validate",
            field="source_commit",
            detail="expected=exact_git_oid",
        )
    for field in (
        "target_profile_digest",
        "source_manifest_digest",
        "acceptance_receipt_digest",
    ):
        _require_digest(data, field, DOMAIN_HANDLE_SCHEMA)
    backend = data["backend"]
    if getattr(backend, "value", backend) not in {"direct", "slurm"}:
        _fail(
            "workspace_job_wire_field_invalid",
            contract=DOMAIN_HANDLE_SCHEMA,
            phase="validate",
            field="backend",
            detail="expected=direct_or_slurm",
        )
    if not isinstance(data["raw_handle_ciphertext"], str) or not data["raw_handle_ciphertext"]:
        _fail(
            "workspace_job_wire_field_invalid",
            contract=DOMAIN_HANDLE_SCHEMA,
            phase="validate",
            field="raw_handle_ciphertext",
            detail="expected=non_empty_private_ciphertext",
        )
    _require_timestamp(data, "accepted_at", DOMAIN_HANDLE_SCHEMA)
    _require_payload_digest(data, digest_field="handle_digest", contract=DOMAIN_HANDLE_SCHEMA)
    _require_expected(data, expected, DOMAIN_HANDLE_SCHEMA)
    return data


def parse_workspace_job_cancellation_intent(
    value: object,
    *,
    expected: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    data = require_exact_workspace_job_object(
        value,
        fields=CANCELLATION_INTENT_FIELDS,
        contract=CANCELLATION_INTENT_SCHEMA,
    )
    _require_schema(data, CANCELLATION_INTENT_SCHEMA)
    for field in ("cancellation_id", "execution_id", "handle_id", "idempotency_key"):
        _require_identifier(data, field, CANCELLATION_INTENT_SCHEMA)
    _require_positive_int(data, "execution_state_version", CANCELLATION_INTENT_SCHEMA)
    fencing = data["execution_fencing_token"]
    if not isinstance(fencing, int) or isinstance(fencing, bool) or fencing < 0:
        _fail(
            "workspace_job_wire_field_invalid",
            contract=CANCELLATION_INTENT_SCHEMA,
            phase="validate",
            field="execution_fencing_token",
            detail="expected=non_negative_integer",
        )
    _require_digest(data, "reason_digest", CANCELLATION_INTENT_SCHEMA)
    _require_timestamp(data, "created_at", CANCELLATION_INTENT_SCHEMA)
    _require_expected(data, expected, CANCELLATION_INTENT_SCHEMA)
    return data


def parse_workspace_job_cancellation_receipt(
    value: object,
    *,
    expected: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    data = require_exact_workspace_job_object(
        value,
        fields=CANCELLATION_RECEIPT_FIELDS,
        contract=CANCELLATION_RECEIPT_SCHEMA,
    )
    _require_schema(data, CANCELLATION_RECEIPT_SCHEMA)
    for field in ("receipt_id", "cancellation_id", "handle_id"):
        _require_identifier(data, field, CANCELLATION_RECEIPT_SCHEMA)
    if data["cancellation_requested"] is not True:
        _fail(
            "workspace_job_wire_field_invalid",
            contract=CANCELLATION_RECEIPT_SCHEMA,
            phase="validate",
            field="cancellation_requested",
            detail="expected=true",
        )
    if data["terminal_settlement_proven"] is not False:
        _fail(
            "workspace_job_wire_field_invalid",
            contract=CANCELLATION_RECEIPT_SCHEMA,
            phase="validate",
            field="terminal_settlement_proven",
            detail="cancellation receipt cannot prove terminal settlement",
        )
    _require_digest(data, "backend_receipt_digest", CANCELLATION_RECEIPT_SCHEMA)
    _require_timestamp(data, "created_at", CANCELLATION_RECEIPT_SCHEMA)
    _require_payload_digest(
        data,
        digest_field="receipt_digest",
        contract=CANCELLATION_RECEIPT_SCHEMA,
    )
    _require_expected(data, expected, CANCELLATION_RECEIPT_SCHEMA)
    return data


def serialize_workspace_job_cancellation_receipt(
    *,
    receipt_id: str,
    cancellation_id: str,
    handle_id: str,
    backend_receipt_digest: str,
    created_at: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": CANCELLATION_RECEIPT_SCHEMA,
        "receipt_id": receipt_id,
        "cancellation_id": cancellation_id,
        "handle_id": handle_id,
        "cancellation_requested": True,
        "terminal_settlement_proven": False,
        "backend_receipt_digest": backend_receipt_digest,
        "created_at": created_at,
    }
    return parse_workspace_job_cancellation_receipt(
        {**payload, "receipt_digest": canonical_workspace_job_wire_digest(payload)}
    )


def parse_external_job_observation(
    value: object,
    *,
    expected: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    data = require_exact_workspace_job_object(
        value,
        fields=OBSERVATION_FIELDS,
        contract=OBSERVATION_SCHEMA,
    )
    _require_schema(data, OBSERVATION_SCHEMA)
    for field in ("observation_id", "handle_id", "execution_id", "dispatch_id"):
        _require_identifier(data, field, OBSERVATION_SCHEMA)
    _require_positive_int(data, "observation_index", OBSERVATION_SCHEMA)
    if data["state"] not in _OBSERVATION_STATES:
        _fail(
            "workspace_job_wire_field_invalid",
            contract=OBSERVATION_SCHEMA,
            phase="validate",
            field="state",
            detail=f"expected_one_of={sorted(_OBSERVATION_STATES)!r}",
        )
    exit_code = data["exit_code"]
    if exit_code is not None and (
        not isinstance(exit_code, int) or isinstance(exit_code, bool)
    ):
        _fail(
            "workspace_job_wire_field_invalid",
            contract=OBSERVATION_SCHEMA,
            phase="validate",
            field="exit_code",
            detail="expected=integer_or_null",
        )
    terminal_digest = data["terminal_receipt_digest"]
    if (data["state"] in _TERMINAL_STATES) != (terminal_digest is not None):
        _fail(
            "workspace_job_wire_field_invalid",
            contract=OBSERVATION_SCHEMA,
            phase="validate",
            field="terminal_receipt_digest",
            detail="terminal state and terminal receipt presence differ",
        )
    if terminal_digest is not None:
        _require_digest(data, "terminal_receipt_digest", OBSERVATION_SCHEMA)
    for field in ("bounded_stdout", "bounded_stderr"):
        observed = data[field]
        if observed is not None and (
            not isinstance(observed, str) or len(observed) > 8192
        ):
            _fail(
                "workspace_job_wire_field_invalid",
                contract=OBSERVATION_SCHEMA,
                phase="validate",
                field=field,
                detail="expected=bounded_string_or_null max_length=8192",
            )
    _require_timestamp(data, "observed_at", OBSERVATION_SCHEMA)
    _require_payload_digest(
        data,
        digest_field="observation_digest",
        contract=OBSERVATION_SCHEMA,
    )
    _require_expected(data, expected, OBSERVATION_SCHEMA)
    return data


def parse_workspace_job_reconciliation(
    value: object,
    *,
    expected_handle: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    if isinstance(value, Mapping) and value.get("disposition") == "accepted":
        return parse_workspace_job_runner_handle(value, expected=expected_handle)
    data = require_exact_workspace_job_object(
        value,
        fields=RECONCILIATION_FIELDS,
        contract=RECONCILIATION_SCHEMA,
    )
    _require_schema(data, RECONCILIATION_SCHEMA)
    if data["disposition"] not in {"unknown", "conflict"}:
        _fail(
            "workspace_job_wire_field_invalid",
            contract=RECONCILIATION_SCHEMA,
            phase="validate",
            field="disposition",
            detail="expected=unknown_or_conflict",
        )
    _require_identifier(data, "safe_error_code", RECONCILIATION_SCHEMA)
    _require_digest(data, "reconciliation_receipt_digest", RECONCILIATION_SCHEMA)
    return data


__all__ = [
    "CANCELLATION_INTENT_FIELDS",
    "CANCELLATION_INTENT_SCHEMA",
    "CANCELLATION_RECEIPT_FIELDS",
    "CANCELLATION_RECEIPT_SCHEMA",
    "DOMAIN_HANDLE_FIELDS",
    "DOMAIN_HANDLE_SCHEMA",
    "OBSERVATION_FIELDS",
    "OBSERVATION_SCHEMA",
    "RECONCILIATION_FIELDS",
    "RECONCILIATION_SCHEMA",
    "RUNNER_HANDLE_FIELDS",
    "RUNNER_HANDLE_SCHEMA",
    "WorkspaceJobWireContractError",
    "canonical_workspace_job_json",
    "canonical_workspace_job_wire_digest",
    "parse_external_job_handle",
    "parse_external_job_observation",
    "parse_workspace_job_cancellation_intent",
    "parse_workspace_job_cancellation_receipt",
    "parse_workspace_job_reconciliation",
    "parse_workspace_job_runner_handle",
    "require_exact_workspace_job_object",
    "serialize_workspace_job_cancellation_receipt",
]
