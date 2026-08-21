"""Provider-neutral compatibility seam for the legacy Research graph.

New Plugin orchestration uses :class:`ResearchProviderPort`.  These bounded DTOs
remain temporarily because the legacy Host graph still consumes the old
``conduct`` shape during offline cutover; no concrete provider lives here.
"""

from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from typing import Any
from typing import Protocol

from .contracts import SourceRefKind
from .provider_runtime import ProviderOutcome


@dataclass(frozen=True, slots=True)
class ResearchUnit:
    unit_id: str
    topic: str
    query: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ResearchSource:
    title: str
    locator: str
    kind: SourceRefKind
    snippet: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        return data


@dataclass(frozen=True, slots=True)
class ResearchFinding:
    summary: str
    query: str
    confidence_label: str | None
    sources: tuple[ResearchSource, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "query": self.query,
            "confidence_label": self.confidence_label,
            "sources": [source.to_dict() for source in self.sources],
        }


@dataclass(frozen=True, slots=True)
class ResearchUnitResult:
    unit_id: str
    summary: str
    findings: tuple[ResearchFinding, ...]
    unresolved_gaps: tuple[str, ...] = ()
    error_message: str | None = None
    escalation_reason: str | None = None
    provider_outcome: str | None = None
    provider_call: dict[str, Any] | None = None

    @property
    def status(self) -> str:
        if self.escalation_reason is not None:
            return "escalated"
        if self.provider_outcome == ProviderOutcome.DEGRADED.value:
            return "partial"
        if self.error_message is not None:
            return "failed"
        return "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "summary": self.summary,
            "findings": [finding.to_dict() for finding in self.findings],
            "unresolved_gaps": list(self.unresolved_gaps),
            "error_message": self.error_message,
            "escalation_reason": self.escalation_reason,
            "provider_outcome": self.provider_outcome,
            "provider_call": self.provider_call,
            "status": self.status,
        }


class ResearchAdapter(Protocol):
    def conduct(
        self,
        *,
        session_id: str,
        research_brief: str,
        unit: ResearchUnit,
    ) -> ResearchUnitResult: ...


__all__ = [
    "ResearchAdapter",
    "ResearchFinding",
    "ResearchSource",
    "ResearchUnit",
    "ResearchUnitResult",
]
