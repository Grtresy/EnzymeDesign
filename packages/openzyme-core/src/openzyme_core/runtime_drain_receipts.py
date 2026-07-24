from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


RUNTIME_COMMAND_OUTCOME_LEGACY_SCHEMA_VERSION = "runtime_command_outcome@1"
RUNTIME_COMMAND_OUTCOME_SCHEMA_VERSION = "runtime_command_outcome@2"
RUNTIME_DRAIN_CORE_RECEIPT_SCHEMA_VERSION = "runtime_drain_core_receipt@1"
RUNTIME_DRAIN_PROJECTION_OUTCOME_SCHEMA_VERSION = (
    "runtime_drain_projection_outcome@1"
)

_SAFE_STATUS = re.compile(r"[a-z][a-z0-9_.-]{0,127}")
_SCHEDULER_STATUSES = frozenset(
    {
        "completed",
        "failed",
        "locked",
        "waiting_approval",
    }
)
_PROJECTION_STATUSES = frozenset({"complete", "failed"})
_PUBLIC_OUTPUT_ID_LIMIT = 16
_PUBLIC_EVENT_ID_LIMIT = 64
_V2_REQUIRED_KEYS = frozenset(
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
    }
)


def _require_identity_tuple(
    field_name: str,
    values: tuple[str, ...],
) -> None:
    if not isinstance(values, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must contain unique identities")
    if any(
        not isinstance(value, str)
        or not value
        or value != value.strip()
        for value in values
    ):
        raise ValueError(f"{field_name} contains an invalid identity")


@dataclass(frozen=True, slots=True)
class RuntimeDrainCoreReceipt:
    """Immutable scheduler facts formed before projection settlement."""

    scheduler_status: str
    processed_signal_count: int
    suspended: bool
    output_ids: tuple[str, ...] = ()
    event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.scheduler_status not in _SCHEDULER_STATUSES:
            raise ValueError("runtime drain scheduler status is invalid")
        if (
            type(self.processed_signal_count) is not int
            or self.processed_signal_count < 0
        ):
            raise ValueError(
                "runtime drain processed signal count must be non-negative"
            )
        if not isinstance(self.suspended, bool):
            raise TypeError("runtime drain suspended must be a boolean")
        _require_identity_tuple("output_ids", self.output_ids)
        _require_identity_tuple("event_ids", self.event_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RUNTIME_DRAIN_CORE_RECEIPT_SCHEMA_VERSION,
            "scheduler_status": self.scheduler_status,
            "processed_signal_count": self.processed_signal_count,
            "suspended": self.suspended,
            "output_count": len(self.output_ids),
            "output_ids": list(self.output_ids),
            "event_count": len(self.event_ids),
            "event_ids": list(self.event_ids),
        }

    def bounded_outcome_summary(
        self,
        projection: RuntimeDrainProjectionOutcome,
    ) -> dict[str, Any]:
        replay_safe = (
            self.processed_signal_count == 0
            and projection.status == "complete"
            and self.scheduler_status in {"completed", "locked"}
        )
        return {
            "schema_version": RUNTIME_COMMAND_OUTCOME_SCHEMA_VERSION,
            "core_receipt_formed": True,
            "scheduler_status": self.scheduler_status,
            "processed_signal_count": self.processed_signal_count,
            "suspended": self.suspended,
            "projection_status": projection.status,
            "projection_error_code": projection.error_code,
            "projection_failed_stage": projection.failed_stage,
            "replay_safe": replay_safe,
            "output_count": len(self.output_ids),
            "output_ids": list(self.output_ids[:_PUBLIC_OUTPUT_ID_LIMIT]),
            "output_ids_truncated": (
                len(self.output_ids) > _PUBLIC_OUTPUT_ID_LIMIT
            ),
            "event_count": len(self.event_ids),
            "event_ids": list(self.event_ids[:_PUBLIC_EVENT_ID_LIMIT]),
            "event_ids_truncated": (
                len(self.event_ids) > _PUBLIC_EVENT_ID_LIMIT
            ),
        }


@dataclass(frozen=True, slots=True)
class RuntimeDrainProjectionOutcome:
    """Typed settlement result kept separate from scheduler progress."""

    status: str
    error_code: str | None = None
    safe_summary: str | None = None
    failed_stage: str | None = None

    def __post_init__(self) -> None:
        if self.status not in _PROJECTION_STATUSES:
            raise ValueError("runtime drain projection status is invalid")
        if self.status == "complete":
            if (
                self.error_code is not None
                or self.safe_summary is not None
                or self.failed_stage is not None
            ):
                raise ValueError(
                    "complete runtime drain projection cannot carry failure facts"
                )
            return
        if (
            self.error_code is None
            or _SAFE_STATUS.fullmatch(self.error_code) is None
        ):
            raise ValueError(
                "failed runtime drain projection requires a safe error code"
            )
        if not self.safe_summary:
            raise ValueError(
                "failed runtime drain projection requires a safe summary"
            )
        if (
            self.failed_stage is None
            or _SAFE_STATUS.fullmatch(self.failed_stage) is None
        ):
            raise ValueError(
                "failed runtime drain projection requires a safe stage"
            )

    @classmethod
    def complete(cls) -> RuntimeDrainProjectionOutcome:
        return cls(status="complete")

    @classmethod
    def failed(
        cls,
        *,
        safe_summary: str,
        failed_stage: str,
    ) -> RuntimeDrainProjectionOutcome:
        return cls(
            status="failed",
            error_code="runtime_projection_failed",
            safe_summary=safe_summary,
            failed_stage=failed_stage,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": (
                RUNTIME_DRAIN_PROJECTION_OUTCOME_SCHEMA_VERSION
            ),
            "status": self.status,
            "error_code": self.error_code,
            "safe_summary": self.safe_summary,
            "failed_stage": self.failed_stage,
        }


def runtime_command_pre_core_failure_summary(
    *,
    recovery_required: bool = False,
) -> dict[str, Any]:
    """Return a closed v2 summary when no core receipt reached the worker."""

    summary: dict[str, Any] = {
        "schema_version": RUNTIME_COMMAND_OUTCOME_SCHEMA_VERSION,
        "core_receipt_formed": False,
        "scheduler_status": "not_started",
        "processed_signal_count": 0,
        "suspended": False,
        "projection_status": "not_started",
        "projection_error_code": None,
        "projection_failed_stage": None,
        "replay_safe": False,
        "output_count": 0,
        "output_ids": [],
        "output_ids_truncated": False,
        "event_count": 0,
        "event_ids": [],
        "event_ids_truncated": False,
    }
    if recovery_required:
        summary["recovery_required"] = True
    return summary


def validate_runtime_command_outcome_v2(
    summary: dict[str, Any],
) -> None:
    """Validate the closed public v2 outcome written by a new command worker."""

    keys = set(summary)
    if not _V2_REQUIRED_KEYS.issubset(keys) or keys - (
        _V2_REQUIRED_KEYS | {"recovery_required"}
    ):
        raise ValueError("runtime command v2 outcome fields are invalid")
    if summary.get("schema_version") != RUNTIME_COMMAND_OUTCOME_SCHEMA_VERSION:
        raise ValueError("runtime command outcome schema is not v2")
    core_formed = summary.get("core_receipt_formed")
    processed_count = summary.get("processed_signal_count")
    suspended = summary.get("suspended")
    replay_safe = summary.get("replay_safe")
    if not isinstance(core_formed, bool):
        raise ValueError("runtime command core receipt flag is invalid")
    if type(processed_count) is not int or processed_count < 0:
        raise ValueError("runtime command processed signal count is invalid")
    if not isinstance(suspended, bool) or not isinstance(replay_safe, bool):
        raise ValueError("runtime command boolean outcome facts are invalid")
    scheduler_status = summary.get("scheduler_status")
    projection_status = summary.get("projection_status")
    if scheduler_status not in _SCHEDULER_STATUSES | {"not_started"}:
        raise ValueError("runtime command scheduler status is invalid")
    if projection_status not in _PROJECTION_STATUSES | {"not_started"}:
        raise ValueError("runtime command projection status is invalid")
    if core_formed:
        if scheduler_status == "not_started" or projection_status == "not_started":
            raise ValueError("formed runtime receipt has an unstarted layer")
    elif (
        scheduler_status != "not_started"
        or projection_status != "not_started"
        or processed_count != 0
    ):
        raise ValueError("unformed runtime receipt reports scheduler progress")
    if processed_count > 0 and replay_safe:
        raise ValueError("runtime command replay cannot be safe after progress")
    if projection_status == "failed":
        if (
            summary.get("projection_error_code")
            != "runtime_projection_failed"
            or not isinstance(summary.get("projection_failed_stage"), str)
            or replay_safe
        ):
            raise ValueError("runtime projection failure facts are invalid")
    elif (
        summary.get("projection_error_code") is not None
        or summary.get("projection_failed_stage") is not None
    ):
        raise ValueError(
            "nonfailed runtime projection carries failure identities"
        )
    for prefix, limit in (
        ("output", _PUBLIC_OUTPUT_ID_LIMIT),
        ("event", _PUBLIC_EVENT_ID_LIMIT),
    ):
        count = summary.get(f"{prefix}_count")
        identities = summary.get(f"{prefix}_ids")
        truncated = summary.get(f"{prefix}_ids_truncated")
        if type(count) is not int or count < 0:
            raise ValueError(f"runtime command {prefix} count is invalid")
        if (
            not isinstance(identities, list)
            or len(identities) > limit
            or len(set(identities)) != len(identities)
            or any(not isinstance(identity, str) or not identity for identity in identities)
            or count < len(identities)
            or not isinstance(truncated, bool)
            or truncated != (count > len(identities))
        ):
            raise ValueError(
                f"runtime command bounded {prefix} identities are invalid"
            )
    recovery_required = summary.get("recovery_required")
    if recovery_required is not None and not isinstance(
        recovery_required,
        bool,
    ):
        raise ValueError("runtime command recovery flag is invalid")


__all__ = [
    "RUNTIME_COMMAND_OUTCOME_LEGACY_SCHEMA_VERSION",
    "RUNTIME_COMMAND_OUTCOME_SCHEMA_VERSION",
    "RUNTIME_DRAIN_CORE_RECEIPT_SCHEMA_VERSION",
    "RUNTIME_DRAIN_PROJECTION_OUTCOME_SCHEMA_VERSION",
    "RuntimeDrainCoreReceipt",
    "RuntimeDrainProjectionOutcome",
    "runtime_command_pre_core_failure_summary",
    "validate_runtime_command_outcome_v2",
]
