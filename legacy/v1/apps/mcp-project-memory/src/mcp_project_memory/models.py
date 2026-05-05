from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class ProjectRecord:
    project_id: str
    root: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EpisodeRecord:
    project_id: str
    episode_id: str
    archived: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DecisionRecord:
    decision_id: str
    project_id: str
    episode_id: str
    type: str
    reason: str
    author: str
    evidence_refs: list[str]
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RunManifestRecord:
    run_id: str
    project_id: str
    episode_id: str
    path: str
    tool: str | None = None
    status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CandidateSummaryRecord:
    candidate_id: str
    project_id: str
    episode_id: str
    path: str
    status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExperimentResultRecord:
    experiment_id: str
    project_id: str
    episode_id: str
    path: str
    candidate_ids: list[str]
    run_ids: list[str]
    imported_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
