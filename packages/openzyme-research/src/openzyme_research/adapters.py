from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
import hashlib
import time
from typing import Any
from typing import Callable
from typing import Protocol

from openzyme_domain import SourceRefKind

from .provider_runtime import BoundedCallableClient
from .provider_runtime import ProviderCallResult
from .provider_runtime import ProviderOutcome
from .provider_runtime import ProviderRequestError
from .provider_runtime import completed_result
from .provider_runtime import degraded_result
from .provider_runtime import safe_public_locator


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
            "provider_call": None
            if self.provider_call is None
            else dict(self.provider_call),
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


def _locator_identity(locator: str) -> str:
    return f"sha256:{hashlib.sha256(locator.encode('utf-8')).hexdigest()}"


def _safe_provider_call(result: ProviderCallResult[Any]) -> dict[str, Any]:
    return {
        "outcome": result.outcome.value,
        "item_count": len(result.items),
        "provenance": result.provenance.to_dict(),
        "failure": None if result.failure is None else result.failure.to_dict(),
        "warnings": list(result.warnings),
    }


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
    callable_client: BoundedCallableClient = field(
        default_factory=BoundedCallableClient
    )

    def conduct(
        self, *, session_id: str, research_brief: str, unit: ResearchUnit
    ) -> ResearchUnitResult:
        del session_id, research_brief
        # ResearchUnit.topic is the semantic subject being investigated, not the
        # provider's search-category enum. Keep provider routing under adapter
        # configuration while preserving the semantic topic in normalized output.
        result = self.web_search_result(query=unit.query)
        return self.normalize_search_result(unit=unit, result=result)

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
        result = self.web_search_result(
            query=query,
            max_results=max_results,
            topic=topic,
            include_raw_content=include_raw_content,
        )
        return {
            "results": [dict(item) for item in result.items],
            "provider_call": _safe_provider_call(result),
        }

    def web_search_result(
        self,
        *,
        query: str,
        max_results: int | None = None,
        topic: str | None = None,
        include_raw_content: bool | None = None,
    ) -> ProviderCallResult[dict[str, Any]]:
        effective_max_results = (
            self.max_results if max_results is None else max_results
        )
        effective_topic = self.topic if topic is None else topic
        effective_include_raw = (
            self.include_raw_content
            if include_raw_content is None
            else include_raw_content
        )
        self._log_stage(f"Tavily web.search start query={query!r}")
        started = time.monotonic()
        try:
            response = self.callable_client.invoke(
                provider="tavily",
                operation="literature.enrich",
                endpoint_id="tavily.search:v1",
                request_identity={
                    "query": query,
                    "max_results": effective_max_results,
                    "topic": effective_topic,
                    "include_raw_content": effective_include_raw,
                },
                call=lambda: (
                    self.search_callable or self._load_search_callable()
                )(
                    query=query,
                    max_results=effective_max_results,
                    include_raw_content=effective_include_raw,
                    topic=effective_topic,
                    timeout=self.timeout_seconds,
                ),
                safe_provider_identity={
                    "api_key_configured": bool(self.api_key),
                },
            )
            payload = response.json_object()
            raw_results = payload.get("results")
            if not isinstance(raw_results, list):
                return degraded_result(
                    provenance=response.provenance,
                    error_code="provider_schema_drift",
                    message="tavily tavily.search:v1 results must be a list",
                    retryable=False,
                )
            results = tuple(
                dict(item) for item in raw_results if isinstance(item, dict)
            )
            if len(results) != len(raw_results):
                return degraded_result(
                    provenance=response.provenance,
                    error_code="provider_schema_drift",
                    message="tavily tavily.search:v1 returned malformed result rows",
                    retryable=False,
                )
            if not results:
                return degraded_result(
                    provenance=response.provenance,
                    error_code="provider_empty",
                    message="tavily enrichment returned no results",
                    retryable=False,
                )
            return completed_result(results, provenance=response.provenance)
        except ProviderRequestError as exc:
            failure = exc.result.failure
            assert failure is not None
            if exc.result.outcome is ProviderOutcome.DEGRADED:
                return exc.result
            return degraded_result(
                provenance=exc.result.provenance,
                error_code=failure.error_code,
                message=failure.message,
                retryable=failure.retryable,
                status_code=failure.status_code,
                warnings=("enrichment_provider_degraded",),
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
                provider_outcome=ProviderOutcome.DEGRADED.value,
                provider_call=dict(response.get("provider_call") or {}),
            )

        findings: list[ResearchFinding] = []
        for result in raw_results:
            title = str(result.get("title") or unit.topic)
            locator = safe_public_locator(str(result.get("url") or ""))
            if locator is None:
                continue
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
            provider_outcome=(
                ProviderOutcome.COMPLETED.value
                if findings
                else ProviderOutcome.DEGRADED.value
            ),
            provider_call=dict(response.get("provider_call") or {}),
            unresolved_gaps=(
                ()
                if findings
                else ("Tavily returned no safely projectable public sources.",)
            ),
        )

    def normalize_search_result(
        self,
        *,
        unit: ResearchUnit,
        result: ProviderCallResult[dict[str, Any]],
    ) -> ResearchUnitResult:
        return self.normalize_search_response(
            unit=unit,
            response={
                "results": [dict(item) for item in result.items],
                "provider_call": _safe_provider_call(result),
            },
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
        result = self.fetch_url_result(
            url=url,
            query=query,
            extract_depth=extract_depth,
            format=format,
            include_images=include_images,
        )
        return {
            "results": [dict(item) for item in result.items],
            "provider_call": _safe_provider_call(result),
        }

    def fetch_url_result(
        self,
        *,
        url: str,
        query: str | None = None,
        extract_depth: str = "basic",
        format: str = "markdown",
        include_images: bool = False,
    ) -> ProviderCallResult[dict[str, Any]]:
        public_url = safe_public_locator(url)
        if public_url is None:
            raise ValueError("web.fetch requires a public HTTP(S) URL")
        self._log_stage("Tavily web.fetch start")
        started = time.monotonic()
        try:
            response = self.callable_client.invoke(
                provider="tavily",
                operation="literature.fetch",
                endpoint_id="tavily.extract:v1",
                request_identity={
                    "locator_digest": _locator_identity(public_url),
                    "query_configured": query is not None,
                    "extract_depth": extract_depth,
                    "format": format,
                    "include_images": include_images,
                },
                call=lambda: (
                    self.extract_callable or self._load_extract_callable()
                )(
                    urls=[public_url],
                    extract_depth=extract_depth,
                    format=format,
                    include_images=include_images,
                    timeout=self.timeout_seconds,
                ),
                safe_provider_identity={
                    "api_key_configured": bool(self.api_key),
                },
            )
            payload = response.json_object()
            raw_results = payload.get("results")
            if not isinstance(raw_results, list):
                return degraded_result(
                    provenance=response.provenance,
                    error_code="provider_schema_drift",
                    message="tavily tavily.extract:v1 results must be a list",
                    retryable=False,
                )
            results = tuple(
                dict(item) for item in raw_results if isinstance(item, dict)
            )
            if len(results) != len(raw_results):
                return degraded_result(
                    provenance=response.provenance,
                    error_code="provider_schema_drift",
                    message="tavily tavily.extract:v1 returned malformed result rows",
                    retryable=False,
                )
            if not results:
                return degraded_result(
                    provenance=response.provenance,
                    error_code="provider_empty",
                    message="tavily enrichment returned no extracted content",
                    retryable=False,
                )
            return completed_result(results, provenance=response.provenance)
        except ProviderRequestError as exc:
            failure = exc.result.failure
            assert failure is not None
            return degraded_result(
                provenance=exc.result.provenance,
                error_code=failure.error_code,
                message=failure.message,
                retryable=failure.retryable,
                status_code=failure.status_code,
                warnings=("enrichment_provider_degraded",),
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
            return ResearchUnitResult(
                unit_id="web-fetch",
                summary="No extracted content was returned for the requested public page.",
                findings=(),
                unresolved_gaps=("Could not fetch the requested public page.",),
                provider_outcome=ProviderOutcome.DEGRADED.value,
                provider_call=dict(response.get("provider_call") or {}),
            )

        result = dict(raw_results[0])
        title = str(result.get("title") or result.get("url") or url)
        locator = safe_public_locator(str(result.get("url") or url))
        if locator is None:
            return ResearchUnitResult(
                unit_id="web-fetch",
                summary="Provider returned no safely projectable public source.",
                findings=(),
                unresolved_gaps=(
                    "Fetched content referenced a private or invalid locator.",
                ),
                provider_outcome=ProviderOutcome.DEGRADED.value,
                provider_call=dict(response.get("provider_call") or {}),
            )
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
            provider_outcome=ProviderOutcome.COMPLETED.value,
            provider_call=dict(response.get("provider_call") or {}),
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
