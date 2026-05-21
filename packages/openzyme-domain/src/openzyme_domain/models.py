from __future__ import annotations

from datetime import UTC
from datetime import datetime
from enum import StrEnum


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {self.SUCCEEDED, self.FAILED, self.CANCELLED}


class ArtifactKind(StrEnum):
    LOG = "log"
    SEQUENCE = "sequence"
    STRUCTURE = "structure"
    REPORT = "report"
    RESEARCH_DOSSIER = "research_dossier"
    RESULT = "result"
    CACHE = "cache"
    OTHER = "other"


class SourceRefKind(StrEnum):
    WEB_PAGE = "web_page"
    PAPER = "paper"
    DATASET = "dataset"
    REPORT = "report"
    OTHER = "other"
