from __future__ import annotations

import re
from typing import Any

from openzyme_domain import RuntimeCommandRecord
from openzyme_runtime import sanitize_public_diagnostic_payload
from openzyme_runtime import sanitize_public_diagnostic_text

from .runtime_drain_receipts import (
    RUNTIME_COMMAND_OUTCOME_LEGACY_SCHEMA_VERSION,
)
from .runtime_drain_receipts import RUNTIME_COMMAND_OUTCOME_SCHEMA_VERSION
from .runtime_drain_receipts import validate_runtime_command_outcome_v2


_PRIVATE_RUNTIME_COMMAND_KEYS = frozenset(
    {
        "claim_owner",
        "lease_owner",
        "lease_token",
        "lease_expires_at",
        "fencing_token",
        "process_id",
        "pid",
        "socket",
        "control_socket",
        "checkpoint_path",
        "host_path",
        "private_result_locator",
        "raw_diagnostic",
        "raw_log",
    }
)
_RUNTIME_COMMAND_OUTCOME_V2_KEYS = frozenset(
    {
        "schema_version",
        "core_receipt_formed",
        "scheduler_status",
        "processed_signal_count",
        "suspended",
        "projection_status",
        "projection_error_code",
        "projection_failed_stage",
        "replay_safe",
        "output_count",
        "output_ids",
        "output_ids_truncated",
        "event_count",
        "event_ids",
        "event_ids_truncated",
        "recovery_required",
    }
)


def _drop_private_runtime_authority(value: object) -> object:
    if isinstance(value, dict):
        public: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            normalized = re.sub(
                r"[^a-z0-9]+",
                "_",
                key_text.casefold(),
            ).strip("_")
            if normalized in _PRIVATE_RUNTIME_COMMAND_KEYS:
                continue
            public[key_text] = _drop_private_runtime_authority(item)
        return public
    if isinstance(value, (list, tuple)):
        return [_drop_private_runtime_authority(item) for item in value]
    return value


def sanitize_runtime_command_outcome(
    value: object,
) -> dict[str, Any] | None:
    if value is None:
        return None
    sanitized = sanitize_public_diagnostic_payload(
        _drop_private_runtime_authority(value)
    )
    if not isinstance(sanitized, dict):
        return None
    schema_version = sanitized.get("schema_version")
    if schema_version == RUNTIME_COMMAND_OUTCOME_LEGACY_SCHEMA_VERSION:
        return sanitized
    if schema_version == RUNTIME_COMMAND_OUTCOME_SCHEMA_VERSION:
        bounded = {
            key: value
            for key, value in sanitized.items()
            if key in _RUNTIME_COMMAND_OUTCOME_V2_KEYS
        }
        try:
            validate_runtime_command_outcome_v2(bounded)
        except ValueError:
            return None
        return bounded
    return sanitized


def project_runtime_command(record: RuntimeCommandRecord) -> dict[str, Any]:
    """Project mutable command state without worker or process authority."""

    return {
        "schema_version": "runtime_command_status@1",
        "session_id": record.session_id,
        "command_id": record.command_id,
        "command_type": record.command_type.value,
        "status": record.status.value,
        "status_url": (
            f"/v3/sessions/{record.session_id}/runtime/commands/{record.command_id}"
        ),
        "accepted_at": record.accepted_at,
        "started_at": record.started_at,
        "completed_at": record.completed_at,
        "bounded_outcome_summary": sanitize_runtime_command_outcome(
            record.bounded_outcome_summary
        ),
        "error_code": record.error_code,
        "safe_error_summary": (
            None
            if record.safe_error_summary is None
            else sanitize_public_diagnostic_text(record.safe_error_summary)[:2_000]
        ),
        "safe_retry_hint": (
            None
            if record.safe_retry_hint is None
            else sanitize_public_diagnostic_text(record.safe_retry_hint)[:2_000]
        ),
    }


__all__ = ["project_runtime_command", "sanitize_runtime_command_outcome"]
