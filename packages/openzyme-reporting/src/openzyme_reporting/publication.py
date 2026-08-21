from __future__ import annotations

from collections.abc import Mapping
from typing import Any


PUBLISHED_REPORT_SUCCESS_STATUSES = frozenset({"ready", "published"})


def _field(record: object, name: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(name)
    return getattr(record, name, None)


def _status_value(record_or_status: object) -> str:
    status = _field(record_or_status, "status")
    if status is None:
        status = record_or_status
    value = getattr(status, "value", status)
    return str(value or "")


def is_published_report_status(record_or_status: object) -> bool:
    """Return whether a Reporting-owned legacy record has shareable status."""

    return _status_value(record_or_status) in PUBLISHED_REPORT_SUCCESS_STATUSES


def is_published_report_link(
    report: object,
    draft: object,
    *,
    task_id: str | None = None,
) -> bool:
    """Validate the bounded legacy link while callers migrate to ReportVersion."""

    report_id = str(_field(report, "report_id") or "")
    report_task_id = _field(report, "task_id")
    draft_task_id = _field(draft, "task_id")
    content_ref_id = _field(report, "content_ref_id")
    file_native_identity_valid = content_ref_id is None or (
        content_ref_id == _field(draft, "content_ref")
        and int(_field(report, "report_version") or 0) >= 1
    )
    return bool(
        report_id
        and is_published_report_status(report)
        and _status_value(draft) == "published"
        and _field(draft, "published_report_id") == report_id
        and _field(draft, "content_ref")
        and file_native_identity_valid
        and _field(report, "session_id") == _field(draft, "session_id")
        and report_task_id == draft_task_id
        and (task_id is None or report_task_id == task_id)
    )


__all__ = [
    "PUBLISHED_REPORT_SUCCESS_STATUSES",
    "is_published_report_link",
    "is_published_report_status",
]
