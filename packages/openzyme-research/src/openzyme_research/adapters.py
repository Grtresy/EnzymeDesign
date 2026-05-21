from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
import time
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
    def conduct(
        self, *, session_id: str, research_brief: str, unit: ResearchUnit
    ) -> ResearchUnitResult: ...


SearchCallable = Callable[..., dict[str, Any]]
ExtractCallable = Callable[..., dict[str, Any]]


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
    timeout_seconds: float = 30.0
    diagnostic_label: str | None = None
    search_callable: SearchCallable | None = None
    extract_callable: ExtractCallable | None = None

    def conduct(
        self, *, session_id: str, research_brief: str, unit: ResearchUnit
    ) -> ResearchUnitResult:
        del session_id, research_brief
        response = self.web_search(query=unit.query, topic=unit.topic)
        return self.normalize_search_response(unit=unit, response=response)

    def search(self, query: str) -> dict[str, Any]:
        return self.web_search(query=query)

    def web_search(
        self,
        *,
        query: str,
        max_results: int | None = None,
        topic: str | None = None,
        include_raw_content: bool | None = None,
    ) -> dict[str, Any]:
        search = self.search_callable or self._load_search_callable()
        self._log_stage(f"Tavily web.search start query={query!r}")
        started = time.monotonic()
        try:
            return search(
                query=query,
                max_results=self.max_results if max_results is None else max_results,
                include_raw_content=self.include_raw_content
                if include_raw_content is None
                else include_raw_content,
                topic=self.topic if topic is None else topic,
                timeout=self.timeout_seconds,
            )
        finally:
            self._log_stage(
                f"Tavily web.search finished elapsed={time.monotonic() - started:.2f}s"
            )

    def normalize_response(
        self, *, unit: ResearchUnit, response: dict[str, Any]
    ) -> ResearchUnitResult:
        return self.normalize_search_response(unit=unit, response=response)

    def normalize_search_response(
        self, *, unit: ResearchUnit, response: dict[str, Any]
    ) -> ResearchUnitResult:
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
            content = _clip_text(
                str(result.get("content") or result.get("raw_content") or title)
            )
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
                            snippet=_clip_text(
                                str(
                                    result.get("raw_content")
                                    or result.get("content")
                                    or ""
                                )
                            ),
                        ),
                    ),
                )
            )

        return ResearchUnitResult(
            unit_id=unit.unit_id,
            summary=_clip_text(
                f"{unit.topic}: "
                + " ".join(finding.summary for finding in findings[:2]),
                limit=400,
            ),
            findings=tuple(findings),
        )

    def fetch_url(
        self,
        *,
        url: str,
        query: str | None = None,
        extract_depth: str = "basic",
        format: str = "markdown",
        include_images: bool = False,
    ) -> dict[str, Any]:
        extract = self.extract_callable or self._load_extract_callable()
        self._log_stage(f"Tavily web.fetch start url={url!r}")
        started = time.monotonic()
        try:
            return extract(
                urls=[url],
                extract_depth=extract_depth,
                format=format,
                include_images=include_images,
                timeout=self.timeout_seconds,
            )
        finally:
            self._log_stage(
                f"Tavily web.fetch finished elapsed={time.monotonic() - started:.2f}s"
            )

    def normalize_fetch_response(
        self,
        *,
        url: str,
        query: str | None,
        response: dict[str, Any],
    ) -> ResearchUnitResult:
        raw_results = list(response.get("results", []))
        if not raw_results:
            failures = list(response.get("failed_results", []))
            reason = "No extracted content was returned."
            if failures:
                failure = dict(failures[0])
                reason = str(failure.get("error") or failure.get("message") or reason)
            return ResearchUnitResult(
                unit_id="web-fetch",
                summary=f"No extracted content was returned for {url}.",
                findings=(),
                unresolved_gaps=(f"Could not fetch URL {url}: {reason}",),
                error_message="no_extracted_content",
            )

        result = dict(raw_results[0])
        title = str(result.get("title") or result.get("url") or url)
        locator = str(result.get("url") or url)
        content = _clip_text(
            str(result.get("raw_content") or result.get("content") or title), limit=600
        )
        return ResearchUnitResult(
            unit_id="web-fetch",
            summary=content or f"Fetched content from {locator}.",
            findings=(
                ResearchFinding(
                    summary=content or title,
                    query=query or url,
                    confidence_label="medium",
                    sources=(
                        ResearchSource(
                            title=title,
                            locator=locator,
                            kind=SourceRefKind.WEB_PAGE,
                            snippet=content or None,
                        ),
                    ),
                ),
            ),
        )

    def _load_search_callable(self) -> SearchCallable:
        api_key = self.api_key
        if not api_key:
            raise MissingTavilyApiKeyError(
                "TavilyResearchAdapter requires TAVILY_API_KEY"
            )
        try:
            from tavily import TavilyClient
        except (
            ImportError
        ) as exc:  # pragma: no cover - exercised only when dependency is missing
            raise MissingTavilyDependencyError(
                "Install openzyme-research[tavily] to use TavilyResearchAdapter"
            ) from exc

        client = TavilyClient(api_key=api_key)
        return client.search

    def _load_extract_callable(self) -> ExtractCallable:
        api_key = self.api_key
        if not api_key:
            raise MissingTavilyApiKeyError(
                "TavilyResearchAdapter requires TAVILY_API_KEY"
            )
        try:
            from tavily import TavilyClient
        except (
            ImportError
        ) as exc:  # pragma: no cover - exercised only when dependency is missing
            raise MissingTavilyDependencyError(
                "Install openzyme-research[tavily] to use TavilyResearchAdapter"
            ) from exc

        client = TavilyClient(api_key=api_key)
        return client.extract

    def _log_stage(self, message: str) -> None:
        if self.diagnostic_label is None:
            return
        print(f"[{self.diagnostic_label}] {message}", flush=True)
