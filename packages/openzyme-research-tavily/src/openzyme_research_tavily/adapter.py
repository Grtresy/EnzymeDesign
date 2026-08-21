from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
import hashlib
from typing import Callable
from typing import Protocol

from openzyme_contracts import ExternalEffectCertainty
from openzyme_research import BoundedCallableClient
from openzyme_research import ProviderRequestError
from openzyme_research import ProviderOutcome
from openzyme_research import ResearchFinding
from openzyme_research import ResearchSource
from openzyme_research import ResearchUnit
from openzyme_research import ResearchUnitResult
from openzyme_research import ResearchProviderReceipt
from openzyme_research import RESEARCH_PROVIDER_CONTRACT_DIGEST
from openzyme_research import ResearchProviderDescriptor
from openzyme_research import ResearchProviderKind
from openzyme_research import ResearchProviderRequest
from openzyme_research import ResearchProviderSource
from openzyme_research import SourceRefKind
from openzyme_research import safe_public_locator


class MissingTavilyDependencyError(RuntimeError):
    pass


class SecretMaterialResolver(Protocol):
    def resolve(self, secret_locator: str) -> str: ...


SearchCallable = Callable[..., dict[str, object]]
ExtractCallable = Callable[..., dict[str, object]]


@dataclass(frozen=True, slots=True)
class TavilyConfiguration:
    secret_locator: str
    max_results: int = 3
    topic: str = "general"
    include_raw_content: bool = True
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.secret_locator or self.secret_locator != self.secret_locator.strip():
            raise ValueError("Tavily secret_locator must be one exact non-empty locator")
        if not 1 <= self.max_results <= 20:
            raise ValueError("Tavily max_results must be between 1 and 20")
        if not 0 < self.timeout_seconds <= 120:
            raise ValueError("Tavily timeout must be between 0 and 120 seconds")


@dataclass(slots=True)
class TavilyResearchProvider:
    configuration: TavilyConfiguration
    secret_resolver: SecretMaterialResolver | None = None
    search_callable: SearchCallable | None = None
    callable_client: BoundedCallableClient = field(
        default_factory=lambda: BoundedCallableClient(max_attempts=1)
    )
    provider_id: str = "openzyme.research.tavily"
    route_id: str = "openzyme.research.tavily.search@1"
    _observations: dict[str, ResearchProviderReceipt] = field(default_factory=dict)

    @property
    def descriptor(self) -> ResearchProviderDescriptor:
        return ResearchProviderDescriptor(
            adapter_component_id="openzyme.research.tavily",
            provider_id=self.provider_id,
            provider_kind=ResearchProviderKind.WEB,
            contract_digest=RESEARCH_PROVIDER_CONTRACT_DIGEST,
        )

    def dispatch(self, request: ResearchProviderRequest) -> ResearchProviderReceipt:
        try:
            response = self.callable_client.invoke(
                provider="tavily",
                operation="research.search",
                endpoint_id="tavily.search:v1",
                request_identity={
                    "operation_id": request.operation_id,
                    "request_digest": request.request_digest,
                    "query": request.unit.query,
                    "max_results": self.configuration.max_results,
                    "topic": self.configuration.topic,
                    "include_raw_content": self.configuration.include_raw_content,
                },
                call=lambda: self._search()(
                    query=request.unit.query,
                    max_results=self.configuration.max_results,
                    include_raw_content=self.configuration.include_raw_content,
                    topic=self.configuration.topic,
                    timeout=self.configuration.timeout_seconds,
                ),
                safe_provider_identity={
                    "secret_locator_digest": _digest_text(
                        self.configuration.secret_locator
                    )
                },
            )
            payload = response.json_object()
            raw_results = payload.get("results")
            if not isinstance(raw_results, list):
                return self._known_failure(
                    request,
                    error_code="provider_schema_drift",
                    summary="Tavily response results must be an array.",
                    response_digest=response.provenance.response_digest,
                )
            sources: list[ResearchProviderSource] = []
            for index, item in enumerate(raw_results):
                if not isinstance(item, dict):
                    return self._known_failure(
                        request,
                        error_code="provider_schema_drift",
                        summary="Tavily response contains a malformed result row.",
                        response_digest=response.provenance.response_digest,
                    )
                locator = safe_public_locator(str(item.get("url") or ""))
                if locator is None:
                    continue
                content = str(
                    item.get("raw_content")
                    or item.get("content")
                    or item.get("title")
                    or ""
                )
                sources.append(
                    ResearchProviderSource(
                        source_id=f"tavily-{request.operation_id}-{index + 1}",
                        title=str(item.get("title") or request.unit.topic),
                        locator=locator,
                        kind=SourceRefKind.WEB_PAGE,
                        content_digest=_digest_text(content),
                        retrieved_at=response.provenance.retrieved_at,
                        snippet=content[:8192],
                    )
                )
            status = "completed" if sources else "empty"
            receipt = ResearchProviderReceipt(
                operation_id=request.operation_id,
                provider_id=self.provider_id,
                provider_operation_id=(
                    response.provenance.request_ids[0]
                    if response.provenance.request_ids
                    else None
                ),
                request_digest=request.request_digest,
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                status=status,
                sources=tuple(sources),
                summary=(
                    f"Tavily returned {len(sources)} safely projectable sources."
                    if sources
                    else "Tavily returned no safely projectable sources."
                ),
                observed_at=response.provenance.retrieved_at,
                response_digest=response.provenance.response_digest,
            )
        except ProviderRequestError as exc:
            failure = exc.result.failure
            assert failure is not None
            ambiguous = failure.error_code in {
                "provider_timeout",
                "provider_unavailable",
            }
            receipt = ResearchProviderReceipt(
                operation_id=request.operation_id,
                provider_id=self.provider_id,
                provider_operation_id=None,
                request_digest=request.request_digest,
                effect_certainty=(
                    ExternalEffectCertainty.DISPATCH_IN_DOUBT
                    if ambiguous
                    else ExternalEffectCertainty.TERMINAL_KNOWN
                ),
                status="dispatch_in_doubt" if ambiguous else "failed",
                sources=(),
                summary=failure.message,
                observed_at=exc.result.provenance.retrieved_at,
                response_digest=(
                    None if ambiguous else exc.result.provenance.response_digest
                ),
                error_code=failure.error_code,
            )
        self._observations[request.operation_id] = receipt
        return receipt

    def reconcile(self, operation_id: str) -> ResearchProviderReceipt:
        try:
            return self._observations[operation_id]
        except KeyError as exc:
            raise KeyError("unknown Tavily controlled-operation identity") from exc

    def _known_failure(
        self,
        request: ResearchProviderRequest,
        *,
        error_code: str,
        summary: str,
        response_digest: str | None,
    ) -> ResearchProviderReceipt:
        return ResearchProviderReceipt(
            operation_id=request.operation_id,
            provider_id=self.provider_id,
            provider_operation_id=None,
            request_digest=request.request_digest,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            status="failed",
            sources=(),
            summary=summary,
            observed_at=datetime.now(UTC).isoformat(),
            response_digest=response_digest,
            error_code=error_code,
        )

    def _search(self) -> SearchCallable:
        if self.search_callable is not None:
            return self.search_callable
        if self.secret_resolver is None:
            raise ValueError("Tavily Adapter requires a secret material resolver")
        api_key = self.secret_resolver.resolve(self.configuration.secret_locator)
        try:
            from tavily import TavilyClient
        except ImportError as exc:  # pragma: no cover - optional live dependency
            raise MissingTavilyDependencyError(
                "Install openzyme-research-tavily[tavily] for live Tavily access"
            ) from exc
        return TavilyClient(api_key=api_key).search


@dataclass(slots=True)
class TavilyResearchAdapter:
    """Temporary old-shape facade owned by the Tavily Adapter wheel.

    It exists only while the legacy Deep Research graph is cut over.  The
    provider call still uses a single dispatch and never selects a fallback.
    """

    api_key: str | None = None
    max_results: int = 3
    topic: str = "general"
    include_raw_content: bool = True
    timeout_seconds: float = 30.0
    diagnostic_label: str | None = None
    search_callable: SearchCallable | None = None
    extract_callable: ExtractCallable | None = None
    callable_client: BoundedCallableClient = field(
        default_factory=lambda: BoundedCallableClient(max_attempts=1)
    )

    def conduct(
        self,
        *,
        session_id: str,
        research_brief: str,
        unit: ResearchUnit,
    ) -> ResearchUnitResult:
        del session_id, research_brief
        return self.normalize_search_response(
            unit=unit,
            response=self.web_search(query=unit.query),
        )

    def search(self, query: str) -> dict[str, object]:
        return self.web_search(query=query)

    def web_search(
        self,
        *,
        query: str,
        max_results: int | None = None,
        topic: str | None = None,
        include_raw_content: bool | None = None,
    ) -> dict[str, object]:
        effective_max = self.max_results if max_results is None else max_results
        effective_topic = self.topic if topic is None else topic
        effective_raw = (
            self.include_raw_content
            if include_raw_content is None
            else include_raw_content
        )
        try:
            response = self.callable_client.invoke(
                provider="tavily",
                operation="research.search",
                endpoint_id="tavily.search:v1",
                request_identity={
                    "query": query,
                    "max_results": effective_max,
                    "topic": effective_topic,
                    "include_raw_content": effective_raw,
                },
                call=lambda: self._legacy_search()(
                    query=query,
                    max_results=effective_max,
                    include_raw_content=effective_raw,
                    topic=effective_topic,
                    timeout=self.timeout_seconds,
                ),
                safe_provider_identity={"api_key_configured": bool(self.api_key)},
            )
            payload = response.json_object()
            results = payload.get("results")
            if not isinstance(results, list):
                results = []
            return {
                "results": results,
                "provider_call": {
                    "outcome": (
                        ProviderOutcome.COMPLETED.value
                        if results
                        else ProviderOutcome.DEGRADED.value
                    ),
                    "provenance": response.provenance.to_dict(),
                    "fallback_performed": False,
                },
            }
        except ProviderRequestError as exc:
            failure = exc.result.failure
            assert failure is not None
            return {
                "results": [],
                "provider_call": {
                    "outcome": ProviderOutcome.DEGRADED.value,
                    "provenance": exc.result.provenance.to_dict(),
                    "failure": failure.to_dict(),
                    "fallback_performed": False,
                },
            }

    def fetch_url(
        self,
        *,
        url: str,
        query: str | None = None,
        extract_depth: str = "basic",
        format: str = "markdown",
        include_images: bool = False,
    ) -> dict[str, object]:
        public_url = safe_public_locator(url)
        if public_url is None:
            raise ValueError("web.fetch requires a public HTTP(S) URL")
        try:
            response = self.callable_client.invoke(
                provider="tavily",
                operation="research.fetch",
                endpoint_id="tavily.extract:v1",
                request_identity={
                    "locator_digest": _digest_text(public_url),
                    "query": query,
                    "extract_depth": extract_depth,
                    "format": format,
                    "include_images": include_images,
                },
                call=lambda: self._legacy_extract()(
                    urls=[public_url],
                    query=query,
                    extract_depth=extract_depth,
                    format=format,
                    include_images=include_images,
                    timeout=self.timeout_seconds,
                ),
                safe_provider_identity={"api_key_configured": bool(self.api_key)},
            )
            payload = response.json_object()
            results = payload.get("results")
            failed_results = payload.get("failed_results")
            return {
                "results": results if isinstance(results, list) else [],
                "failed_results": (
                    failed_results if isinstance(failed_results, list) else []
                ),
                "provider_call": {
                    "outcome": (
                        ProviderOutcome.COMPLETED.value
                        if isinstance(results, list) and results
                        else ProviderOutcome.DEGRADED.value
                    ),
                    "provenance": response.provenance.to_dict(),
                    "failure": (
                        None
                        if isinstance(results, list) and results
                        else {
                            "error_code": "provider_empty",
                            "message": "Tavily returned no extracted content.",
                            "retryable": False,
                        }
                    ),
                    "fallback_performed": False,
                },
            }
        except ProviderRequestError as exc:
            failure = exc.result.failure
            assert failure is not None
            return {
                "results": [],
                "failed_results": [],
                "provider_call": {
                    "outcome": ProviderOutcome.DEGRADED.value,
                    "provenance": exc.result.provenance.to_dict(),
                    "failure": failure.to_dict(),
                    "fallback_performed": False,
                },
            }

    def normalize_response(
        self,
        *,
        unit: ResearchUnit,
        response: dict[str, object],
    ) -> ResearchUnitResult:
        return self.normalize_search_response(unit=unit, response=response)

    def normalize_search_response(
        self,
        *,
        unit: ResearchUnit,
        response: dict[str, object],
    ) -> ResearchUnitResult:
        raw_results = response.get("results")
        results = raw_results if isinstance(raw_results, list) else []
        findings: list[ResearchFinding] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            locator = safe_public_locator(str(item.get("url") or ""))
            if locator is None:
                continue
            title = str(item.get("title") or unit.topic)
            content = str(
                item.get("content") or item.get("raw_content") or title
            )[:8192]
            findings.append(
                ResearchFinding(
                    summary=content,
                    query=unit.query,
                    confidence_label="medium",
                    sources=(
                        ResearchSource(
                            title=title,
                            locator=locator,
                            kind=SourceRefKind.WEB_PAGE,
                            snippet=content,
                        ),
                    ),
                )
            )
        return ResearchUnitResult(
            unit_id=unit.unit_id,
            summary=(
                f"{unit.topic}: "
                + " ".join(finding.summary for finding in findings[:2])
            )[:400],
            findings=tuple(findings),
            unresolved_gaps=(
                () if findings else ("Provider returned no safely projectable sources.",)
            ),
            provider_outcome=(
                ProviderOutcome.COMPLETED.value
                if findings
                else ProviderOutcome.DEGRADED.value
            ),
            provider_call=(
                dict(response.get("provider_call") or {})
                if isinstance(response.get("provider_call"), dict)
                else None
            ),
        )

    def normalize_fetch_response(
        self,
        *,
        url: str,
        query: str | None,
        response: dict[str, object],
    ) -> ResearchUnitResult:
        return self.normalize_search_response(
            unit=ResearchUnit(
                unit_id="web-fetch",
                topic="web fetch",
                query=query or _digest_text(url),
            ),
            response=response,
        )

    def _legacy_search(self) -> SearchCallable:
        if self.search_callable is not None:
            return self.search_callable
        if not self.api_key:
            raise ValueError("TavilyResearchAdapter requires an API key")
        try:
            from tavily import TavilyClient
        except ImportError as exc:  # pragma: no cover
            raise MissingTavilyDependencyError(
                "Install openzyme-research-tavily[tavily] for live Tavily access"
            ) from exc
        return TavilyClient(api_key=self.api_key).search

    def _legacy_extract(self) -> ExtractCallable:
        if self.extract_callable is not None:
            return self.extract_callable
        if not self.api_key:
            raise ValueError("TavilyResearchAdapter requires an API key")
        try:
            from tavily import TavilyClient
        except ImportError as exc:  # pragma: no cover
            raise MissingTavilyDependencyError(
                "Install openzyme-research-tavily[tavily] for live Tavily access"
            ) from exc
        return TavilyClient(api_key=self.api_key).extract


def _digest_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "MissingTavilyDependencyError",
    "SecretMaterialResolver",
    "TavilyConfiguration",
    "TavilyResearchAdapter",
    "TavilyResearchProvider",
]
