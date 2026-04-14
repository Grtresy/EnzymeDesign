from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from enum import StrEnum
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


class EpisodeStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    COMPLETED = "completed"
    ARCHIVED = "archived"

    @property
    def is_terminal(self) -> bool:
        return self in {self.FAILED, self.COMPLETED, self.ARCHIVED}


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {self.APPROVED, self.REJECTED, self.EXPIRED, self.CANCELLED}


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {self.SUCCEEDED, self.FAILED, self.CANCELLED}


class ReportStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    PUBLISHED = "published"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {self.PUBLISHED, self.FAILED}


class DecisionStatus(StrEnum):
    PROPOSED = "proposed"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"


class ArtifactKind(StrEnum):
    LOG = "log"
    STRUCTURE = "structure"
    REPORT = "report"
    RESULT = "result"
    CACHE = "cache"
    OTHER = "other"


class SourceRefKind(StrEnum):
    WEB_PAGE = "web_page"
    PAPER = "paper"
    DATASET = "dataset"
    REPORT = "report"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Project:
    project_id: str
    name: str
    created_at: str
    updated_at: str
    description: str | None = None

    @classmethod
    def create(cls, project_id: str, name: str, description: str | None = None) -> "Project":
        now = utc_now_iso()
        return cls(
            project_id=project_id,
            name=name,
            created_at=now,
            updated_at=now,
            description=description,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Episode:
    episode_id: str
    project_id: str
    objective: str
    status: EpisodeStatus
    created_at: str
    updated_at: str

    @classmethod
    def create(
        cls,
        episode_id: str,
        project_id: str,
        objective: str,
        status: EpisodeStatus = EpisodeStatus.DRAFT,
    ) -> "Episode":
        now = utc_now_iso()
        return cls(
            episode_id=episode_id,
            project_id=project_id,
            objective=objective,
            status=status,
            created_at=now,
            updated_at=now,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True, slots=True)
class Decision:
    decision_id: str
    episode_id: str
    phase: str
    turn_index: int
    action_kind: str
    status: DecisionStatus
    summary: str
    rationale: str
    created_at: str
    action_payload: dict[str, Any] | None = None
    observation_payload: dict[str, Any] | None = None
    project_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True, slots=True)
class Approval:
    approval_id: str
    episode_id: str
    status: ApprovalStatus
    requested_action: str
    created_at: str
    resolved_at: str | None = None
    run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True, slots=True)
class Run:
    run_id: str
    episode_id: str
    status: RunStatus
    execution_mode: str
    created_at: str
    completed_at: str | None = None
    approval_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    artifact_id: str
    episode_id: str
    kind: ArtifactKind
    storage_uri: str
    created_at: str
    run_id: str | None = None
    title: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()
    provenance: dict[str, Any] | None = None
    availability: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        data["tags"] = list(self.tags)
        return data


@dataclass(frozen=True, slots=True)
class ReportRecord:
    report_id: str
    episode_id: str
    run_id: str | None
    status: ReportStatus
    title: str
    summary: str
    stage_summary: str
    created_at: str
    updated_at: str
    artifact_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    episode_id: str
    summary: str
    query: str
    created_at: str
    confidence_label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SourceRef:
    source_ref_id: str
    evidence_id: str
    episode_id: str
    title: str
    locator: str
    kind: SourceRefKind
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        return data


@dataclass(frozen=True, slots=True)
class ResearchSummaryRecord:
    episode_id: str
    summary: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class UnresolvedGapRecord:
    gap_id: str
    episode_id: str
    summary: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CORE_ENTITY_NAMES: tuple[str, ...] = (
    "Project",
    "Episode",
    "Decision",
    "Approval",
    "Run",
    "ArtifactRecord",
    "ReportRecord",
)

# Phase C entities extend the Phase A core set by referencing these anchors.
EPISODE_EXTENSION_TARGETS: frozenset[str] = frozenset({"Episode"})
DECISION_EXTENSION_TARGETS: frozenset[str] = frozenset({"Episode", "Decision"})
RUN_EXTENSION_TARGETS: frozenset[str] = frozenset({"Episode", "Run"})
APPROVAL_EXTENSION_TARGETS: frozenset[str] = frozenset({"Episode", "Approval"})
ARTIFACT_EXTENSION_TARGETS: frozenset[str] = frozenset({"Episode", "Run", "ArtifactRecord"})
REPORT_EXTENSION_TARGETS: frozenset[str] = frozenset({"Episode", "Run", "ReportRecord"})
RESEARCH_EXTENSION_TARGETS: frozenset[str] = frozenset(
    {"Episode", "EvidenceRecord", "SourceRef", "ResearchSummaryRecord", "UnresolvedGapRecord"}
)
DESIGN_EXTENSION_TARGETS: frozenset[str] = frozenset({"Episode", "ArtifactRecord", "Decision"})
