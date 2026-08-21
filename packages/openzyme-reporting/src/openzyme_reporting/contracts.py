from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class SessionReportStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    PUBLISHED = "published"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {self.READY, self.PUBLISHED, self.FAILED}


class SessionReportDraftStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    READY = "ready"
    PUBLISHED = "published"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {self.PUBLISHED, self.FAILED}


@dataclass(frozen=True, slots=True)
class SessionReportRecord:
    report_id: str
    session_id: str
    task_id: str | None
    lane_id: str | None
    invocation_id: str | None
    run_id: str | None
    status: SessionReportStatus
    title: str
    summary: str
    stage_summary: str
    created_at: str
    updated_at: str
    content_ref_id: str | None = None
    report_version: int = 1
    supersedes_report_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True, slots=True)
class SessionReportDraftRecord:
    draft_id: str
    session_id: str
    task_id: str | None
    owner_agent_id: str | None
    status: SessionReportDraftStatus
    title: str
    summary: str
    content_ref: str | None
    published_report_id: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


__all__ = [
    "SessionReportDraftRecord",
    "SessionReportDraftStatus",
    "SessionReportRecord",
    "SessionReportStatus",
]
