from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import RevisionPathRef
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier


RESEARCH_REQUEST_SCHEMA_VERSION = "openzyme_research_request@1"
RESEARCH_PROVIDER_RECEIPT_SCHEMA_VERSION = "openzyme_research_provider_receipt@1"
RESEARCH_INVOCATION_SCHEMA_VERSION = "openzyme_research_invocation@1"
RESEARCH_PUBLICATION_LINK_SCHEMA_VERSION = "openzyme_research_publication_link@1"
RESEARCH_PROVIDER_DESCRIPTOR_SCHEMA_VERSION = "openzyme_research_provider_descriptor@1"
RESEARCH_PROVIDER_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "contract": "openzyme.research.provider@1",
        "descriptor": RESEARCH_PROVIDER_DESCRIPTOR_SCHEMA_VERSION,
        "request": "ResearchProviderRequest",
        "receipt": RESEARCH_PROVIDER_RECEIPT_SCHEMA_VERSION,
        "provider_kinds": ["web", "document", "browser"],
        "operations": ["dispatch", "reconcile"],
        "fallback": "forbidden",
    }
)


def _bounded_text(value: str, *, field_name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    normalized = value.strip()
    if len(normalized.encode("utf-8")) > limit:
        raise ValueError(f"{field_name} exceeds {limit} bytes")
    return normalized


class ResearchInvocationStatus(StrEnum):
    ADMITTED = "admitted"
    RUNNING = "running"
    DISPATCH_IN_DOUBT = "dispatch_in_doubt"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"

    @property
    def terminal(self) -> bool:
        return self in {self.COMPLETED, self.PARTIAL, self.FAILED}


class ResearchProviderKind(StrEnum):
    WEB = "web"
    DOCUMENT = "document"
    BROWSER = "browser"


@dataclass(frozen=True, slots=True)
class ResearchProviderDescriptor:
    adapter_component_id: str
    provider_id: str
    provider_kind: ResearchProviderKind
    contract_digest: str
    operations: tuple[str, ...] = ("dispatch", "reconcile")
    schema_version: str = RESEARCH_PROVIDER_DESCRIPTOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESEARCH_PROVIDER_DESCRIPTOR_SCHEMA_VERSION:
            raise ValueError("unsupported Research provider descriptor schema")
        require_identifier(
            self.adapter_component_id,
            field_name="adapter_component_id",
        )
        require_identifier(self.provider_id, field_name="provider_id")
        require_digest(self.contract_digest, field_name="contract_digest")
        if not self.operations or len(set(self.operations)) != len(self.operations):
            raise ValueError("Research provider operations must be unique and non-empty")
        for operation in self.operations:
            require_identifier(operation, field_name="operation")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "adapter_component_id": self.adapter_component_id,
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind.value,
            "contract_digest": self.contract_digest,
            "operations": list(self.operations),
        }


@dataclass(frozen=True, slots=True)
class ResearchRequest:
    request_id: str
    session_id: str
    actor_id: str
    brief: str
    units: tuple["ResearchUnitSpec", ...]
    created_at: str
    task_id: str | None = None
    lane_id: str | None = None
    schema_version: str = RESEARCH_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESEARCH_REQUEST_SCHEMA_VERSION:
            raise ValueError("unsupported Research request schema")
        for field_name in ("request_id", "session_id", "actor_id", "created_at"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in ("task_id", "lane_id"):
            value = getattr(self, field_name)
            if value is not None:
                require_identifier(value, field_name=field_name)
        object.__setattr__(
            self,
            "brief",
            _bounded_text(self.brief, field_name="brief", limit=8_192),
        )
        if not 1 <= len(self.units) <= 8:
            raise ValueError("Research request requires between one and eight units")
        unit_ids = [unit.unit_id for unit in self.units]
        if len(set(unit_ids)) != len(unit_ids):
            raise ValueError("Research unit IDs must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "actor_id": self.actor_id,
            "task_id": self.task_id,
            "lane_id": self.lane_id,
            "brief": self.brief,
            "units": [unit.to_dict() for unit in self.units],
            "created_at": self.created_at,
        }

    @property
    def request_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class ResearchUnitSpec:
    unit_id: str
    topic: str
    query: str

    def __post_init__(self) -> None:
        require_identifier(self.unit_id, field_name="unit_id")
        object.__setattr__(
            self, "topic", _bounded_text(self.topic, field_name="topic", limit=1_024)
        )
        object.__setattr__(
            self, "query", _bounded_text(self.query, field_name="query", limit=4_096)
        )

    def to_dict(self) -> dict[str, str]:
        return {"unit_id": self.unit_id, "topic": self.topic, "query": self.query}


@dataclass(frozen=True, slots=True)
class ResearchProviderRequest:
    operation_id: str
    request_digest: str
    session_id: str
    unit: ResearchUnitSpec
    deadline_at: str

    def __post_init__(self) -> None:
        for field_name in ("operation_id", "session_id", "deadline_at"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.request_digest, field_name="request_digest")


@dataclass(frozen=True, slots=True)
class ResearchProviderSource:
    source_id: str
    title: str
    locator: str
    kind: SourceRefKind
    content_digest: str
    retrieved_at: str
    snippet: str | None = None
    external_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("source_id", "retrieved_at"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        object.__setattr__(
            self, "title", _bounded_text(self.title, field_name="title", limit=2_048)
        )
        object.__setattr__(
            self, "locator", _bounded_text(self.locator, field_name="locator", limit=4_096)
        )
        require_digest(self.content_digest, field_name="content_digest")
        if self.snippet is not None and len(self.snippet.encode("utf-8")) > 8_192:
            raise ValueError("snippet exceeds 8192 bytes")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        return data


@dataclass(frozen=True, slots=True)
class ResearchProviderReceipt:
    operation_id: str
    provider_id: str
    provider_operation_id: str | None
    request_digest: str
    effect_certainty: ExternalEffectCertainty
    status: str
    sources: tuple[ResearchProviderSource, ...]
    summary: str
    observed_at: str
    response_digest: str | None = None
    error_code: str | None = None
    fallback_performed: bool = False
    schema_version: str = RESEARCH_PROVIDER_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESEARCH_PROVIDER_RECEIPT_SCHEMA_VERSION:
            raise ValueError("unsupported Research provider receipt schema")
        for field_name in ("operation_id", "provider_id", "status", "observed_at"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.request_digest, field_name="request_digest")
        if self.response_digest is not None:
            require_digest(self.response_digest, field_name="response_digest")
        if self.fallback_performed:
            raise ValueError("Research provider receipts never permit hidden fallback")
        if self.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
            if self.sources or self.response_digest is not None:
                raise ValueError("dispatch-in-doubt receipt cannot assert provider results")
        if self.error_code is not None:
            require_identifier(self.error_code, field_name="error_code")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "provider_id": self.provider_id,
            "provider_operation_id": self.provider_operation_id,
            "request_digest": self.request_digest,
            "effect_certainty": self.effect_certainty.value,
            "status": self.status,
            "sources": [source.to_dict() for source in self.sources],
            "summary": self.summary,
            "observed_at": self.observed_at,
            "response_digest": self.response_digest,
            "error_code": self.error_code,
            "fallback_performed": self.fallback_performed,
        }


@dataclass(frozen=True, slots=True)
class ResearchInvocationRecord:
    invocation_id: str
    request: ResearchRequest
    provider_id: str
    route_id: str
    status: ResearchInvocationStatus
    operation_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    started_at: str
    updated_at: str
    state_version: int = 1
    publication_ref: RevisionPathRef | None = None
    schema_version: str = RESEARCH_INVOCATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in ("invocation_id", "provider_id", "route_id", "started_at", "updated_at"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.state_version < 1:
            raise ValueError("state_version must be positive")
        if len(set(self.operation_ids)) != len(self.operation_ids):
            raise ValueError("operation IDs must be unique")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("source IDs must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "invocation_id": self.invocation_id,
            "request": self.request.to_dict(),
            "request_digest": self.request.request_digest,
            "provider_id": self.provider_id,
            "route_id": self.route_id,
            "status": self.status.value,
            "operation_ids": list(self.operation_ids),
            "source_ids": list(self.source_ids),
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "state_version": self.state_version,
            "publication_ref": (
                None if self.publication_ref is None else self.publication_ref.to_dict()
            ),
        }


class SourceRefKind(StrEnum):
    WEB_PAGE = "web_page"
    PAPER = "paper"
    DATASET = "dataset"
    REPORT = "report"
    OTHER = "other"


class ResearchSummaryStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    NEEDS_CLARIFICATION = "needs_clarification"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {
            self.COMPLETED,
            self.PARTIAL,
            self.NEEDS_CLARIFICATION,
            self.FAILED,
        }


@dataclass(frozen=True, slots=True)
class ResearchSummary:
    summary_id: str
    session_id: str
    task_id: str | None
    lane_id: str | None
    invocation_id: str
    status: ResearchSummaryStatus
    completion_reason: str
    research_brief: str
    summary: str
    created_at: str
    updated_at: str
    clarification_question: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True, slots=True)
class ResearchEvidence:
    evidence_id: str
    session_id: str
    task_id: str | None
    lane_id: str | None
    invocation_id: str
    summary_id: str
    summary: str
    query: str
    created_at: str
    confidence_label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ResearchSourceRef:
    source_ref_id: str
    session_id: str
    task_id: str | None
    lane_id: str | None
    invocation_id: str
    evidence_id: str
    title: str
    locator: str
    kind: SourceRefKind
    created_at: str
    snippet: str | None = None
    provider: str | None = None
    external_id: str | None = None
    pmid: str | None = None
    doi: str | None = None
    authors: tuple[dict[str, Any], ...] = ()
    venue: str | None = None
    publication_date: str | None = None
    retrieved_at: str | None = None
    request_digest: str | None = None
    response_digest: str | None = None
    provider_provenance: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        data["authors"] = [dict(author) for author in self.authors]
        data["provider_provenance"] = (
            {}
            if self.provider_provenance is None
            else dict(self.provider_provenance)
        )
        return data


@dataclass(frozen=True, slots=True)
class ResearchGap:
    gap_id: str
    session_id: str
    task_id: str | None
    lane_id: str | None
    invocation_id: str
    summary_id: str
    summary: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "RESEARCH_INVOCATION_SCHEMA_VERSION",
    "RESEARCH_PROVIDER_RECEIPT_SCHEMA_VERSION",
    "RESEARCH_PUBLICATION_LINK_SCHEMA_VERSION",
    "RESEARCH_REQUEST_SCHEMA_VERSION",
    "ResearchEvidence",
    "ResearchGap",
    "ResearchInvocationRecord",
    "ResearchInvocationStatus",
    "ResearchProviderReceipt",
    "ResearchProviderRequest",
    "ResearchProviderSource",
    "ResearchRequest",
    "ResearchSourceRef",
    "ResearchSummary",
    "ResearchSummaryStatus",
    "ResearchUnitSpec",
    "SourceRefKind",
]
