from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from typing import Any
from typing import Callable
from typing import Protocol

from openzyme_domain import SourceRefKind


class MissingTavilyDependencyError(RuntimeError):
    """Raised when Tavily support is requested without the optional dependency."""


class MissingTavilyApiKeyError(RuntimeError):
    """Raised when Tavily support is requested without an API key."""


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

    @property
    def status(self) -> str:
        if self.escalation_reason is not None:
            return "escalated"
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
            "status": self.status,
        }


class ResearchAdapter(Protocol):
    def conduct(self, *, episode_id: str, research_brief: str, unit: ResearchUnit) -> ResearchUnitResult: ...


SearchCallable = Callable[..., dict[str, Any]]


def _clip_text(value: str | None, *, limit: int = 280) -> str:
    if value is None:
        return ""
    trimmed = value.strip()
    if len(trimmed) <= limit:
        return trimmed
    return f"{trimmed[: limit - 3].rstrip()}..."


@dataclass(slots=True)
class TavilyResearchAdapter:
    api_key: str | None = None
    max_results: int = 3
    topic: str = "general"
    include_raw_content: bool = True
    search_callable: SearchCallable | None = None

    def conduct(self, *, episode_id: str, research_brief: str, unit: ResearchUnit) -> ResearchUnitResult:
        del episode_id, research_brief
        response = self.search(unit.query)
        return self.normalize_response(unit=unit, response=response)

    def search(self, query: str) -> dict[str, Any]:
        search = self.search_callable or self._load_search_callable()
        return search(
            query=query,
            max_results=self.max_results,
            include_raw_content=self.include_raw_content,
            topic=self.topic,
        )

    def normalize_response(self, *, unit: ResearchUnit, response: dict[str, Any]) -> ResearchUnitResult:
        raw_results = list(response.get("results", []))
        if not raw_results:
            return ResearchUnitResult(
                unit_id=unit.unit_id,
                summary=f"No search results were found for {unit.topic}.",
                findings=(),
                unresolved_gaps=(f"No search results for query: {unit.query}",),
                error_message="no_results",
            )

        findings: list[ResearchFinding] = []
        for result in raw_results:
            title = str(result.get("title") or unit.topic)
            locator = str(result.get("url") or "")
            content = _clip_text(str(result.get("content") or result.get("raw_content") or title))
            findings.append(
                ResearchFinding(
                    summary=content or title,
                    query=unit.query,
                    confidence_label="medium",
                    sources=(
                        ResearchSource(
                            title=title,
                            locator=locator,
                            kind=SourceRefKind.WEB_PAGE,
                            snippet=_clip_text(str(result.get("raw_content") or result.get("content") or "")),
                        ),
                    ),
                )
            )

        return ResearchUnitResult(
            unit_id=unit.unit_id,
            summary=_clip_text(
                f"{unit.topic}: " + " ".join(finding.summary for finding in findings[:2]),
                limit=400,
            ),
            findings=tuple(findings),
        )

    def _load_search_callable(self) -> SearchCallable:
        api_key = self.api_key
        if not api_key:
            raise MissingTavilyApiKeyError("TavilyResearchAdapter requires TAVILY_API_KEY")
        try:
            from tavily import TavilyClient
        except ImportError as exc:  # pragma: no cover - exercised only when dependency is missing
            raise MissingTavilyDependencyError(
                "Install openzyme-research[tavily] to use TavilyResearchAdapter"
            ) from exc

        client = TavilyClient(api_key=api_key)
        return client.search
