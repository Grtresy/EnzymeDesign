from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from typing import Sequence

from pydantic import BaseModel
from pydantic import Field

from openzyme_research import ResearchAdapter
from openzyme_research import ResearchUnit
from openzyme_research import BioResearchService
from openzyme_research import ProviderCallResult
from openzyme_research import ProviderOutcome
from openzyme_research import ProviderRequestError
from openzyme_research import ResearchObservation
from openzyme_research import evaluate_literature_quorum
from openzyme_research import literature_hits_to_findings
from openzyme_research import structure_hits_to_findings

from .limits import LimiterRegistry
from .seams import ResearchTool
from .seams import ResearchToolContext
from .seams import ResearchToolProvider
from .seams import ResearchToolResult


class WebSearchArgs(BaseModel):
    query: str
    max_results: int = Field(default=3, ge=1, le=20)
    topic: str = "general"
    include_raw_content: bool = True


class WebFetchArgs(BaseModel):
    url: str = Field(min_length=1)
    query: str | None = None
    extract_depth: str = Field(default="basic", pattern="^(basic|advanced)$")
    format: str = Field(default="markdown", pattern="^(markdown|text)$")
    include_images: bool = False


class ThinkToolArgs(BaseModel):
    reflection: str = Field(min_length=1)


class ProviderSearchArgs(BaseModel):
    query: str
    limit: int = Field(default=5, ge=1, le=20)


class UniProtLookupArgs(BaseModel):
    accession: str = Field(min_length=1)


class InterProQueryArgs(BaseModel):
    accession: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


def _tool_result(
    tool_name: str, observation: ResearchObservation
) -> ResearchToolResult:
    payload = observation.to_dict()
    return ResearchToolResult(
        tool_name=tool_name, summary=payload["summary"], payload=payload
    )


def _literature_observation(
    service: BioResearchService,
    *,
    provider: str,
    query: str,
    limit: int,
) -> ResearchObservation:
    result_method = getattr(
        service,
        (
            "search_pubmed_result"
            if provider == "pubmed"
            else "search_semantic_scholar_result"
        ),
        None,
    )
    try:
        if callable(result_method):
            provider_result = result_method(query=query, limit=limit)
        elif provider == "pubmed":
            provider_result = service.search_pubmed(query=query, limit=limit)
        else:
            provider_result = service.search_semantic_scholar(
                query=query, limit=limit
            )
    except ProviderRequestError as exc:
        failure = exc.result.failure
        assert failure is not None
        return ResearchObservation(
            status="failed",
            summary=failure.message,
            unresolved_gaps=(failure.message,),
            provider=provider,
            raw_ref={"provider_call": exc.result.to_summary_dict()},
        )
    except Exception as exc:  # provider SDKs can raise non-standard transport errors
        summary = f"{provider} provider call failed before returning a typed outcome"
        return ResearchObservation(
            status="failed",
            summary=summary,
            unresolved_gaps=(summary,),
            provider=provider,
            raw_ref={
                "provider": provider,
                "outcome": "failed",
                "error_code": "provider_unavailable",
                "typed_provider_outcome": False,
                "exception_type": exc.__class__.__name__,
            },
        )

    if isinstance(provider_result, ProviderCallResult):
        hits = provider_result.items
        outcome = provider_result.outcome
        provider_call = provider_result.to_summary_dict()
        quorum = evaluate_literature_quorum(
            pubmed=provider_result if provider == "pubmed" else None,
            semantic_scholar=(
                provider_result if provider == "semantic_scholar" else None
            ),
        )
    else:
        hits = tuple(provider_result)
        outcome = ProviderOutcome.COMPLETED if hits else ProviderOutcome.EMPTY
        provider_call = {
            "provider": provider,
            "outcome": outcome.value,
            "typed_provider_outcome": False,
            "cutover_eligible": False,
        }
        quorum = None
    required_pubmed_failed = (
        provider == "pubmed"
        and (quorum is None or not quorum.cutover_eligible)
    )
    if outcome is ProviderOutcome.FAILED or required_pubmed_failed:
        status = "failed"
    elif outcome is ProviderOutcome.DEGRADED:
        status = "partial"
    else:
        status = "completed"
    gaps: tuple[str, ...] = ()
    if outcome is ProviderOutcome.FAILED:
        failure = (
            provider_result.failure
            if isinstance(provider_result, ProviderCallResult)
            else None
        )
        message = (
            f"{provider} provider failed"
            if failure is None
            else failure.message
        )
        gaps = (message,)
    elif required_pubmed_failed:
        gaps = (
            f"required PubMed evidence was not accepted for query: {query}",
        )
    elif outcome is ProviderOutcome.EMPTY:
        gaps = (f"{provider} returned no records for query: {query}",)
    elif outcome is ProviderOutcome.DEGRADED:
        gaps = (f"{provider} enrichment is degraded for query: {query}",)
    return ResearchObservation(
        status=status,
        summary=f"Collected {len(hits)} {provider} hits for {query}.",
        findings=(
            ()
            if required_pubmed_failed
            else tuple(literature_hits_to_findings(hits, query=query))
        ),
        unresolved_gaps=gaps,
        provider=provider,
        raw_ref={
            "query": query,
            "provider_call": provider_call,
            "call_local_literature_quorum": (
                None if quorum is None else quorum.to_dict()
            ),
        },
    )


def _web_tool_enabled(adapter: object) -> bool:
    return callable(getattr(adapter, "web_search", None)) and callable(
        getattr(adapter, "fetch_url", None)
    )


@dataclass(frozen=True, slots=True)
class WebSearchTool:
    adapter: ResearchAdapter
    limiter_registry: LimiterRegistry | None = None
    name: str = "web.search"
    description: str = (
        "Search the web for a query and return normalized evidence sources."
    )
    args_schema: type[BaseModel] = WebSearchArgs

    def invoke(
        self, *, args: dict[str, object], context: ResearchToolContext
    ) -> ResearchToolResult:
        payload = WebSearchArgs.model_validate(args)
        search = getattr(self.adapter, "web_search")
        normalize = getattr(self.adapter, "normalize_search_response")
        unit = ResearchUnit(
            unit_id=f"web-search-{context.tool_call_iterations + 1}",
            topic=payload.topic,
            query=payload.query,
        )

        def _call() -> ResearchToolResult:
            result = normalize(
                unit=unit,
                response=search(
                    query=payload.query,
                    max_results=payload.max_results,
                    topic=payload.topic,
                    include_raw_content=payload.include_raw_content,
                ),
            )
            return _tool_result(
                self.name,
                ResearchObservation(
                    status=result.status,
                    summary=result.summary,
                    findings=result.findings,
                    unresolved_gaps=result.unresolved_gaps,
                    provider="web",
                    raw_ref={
                        "unit_id": result.unit_id,
                        "error_message": result.error_message,
                        "escalation_reason": result.escalation_reason,
                    },
                ),
            )

        if self.limiter_registry is None:
            return _call()
        return self.limiter_registry.sync_limiter("research_provider").run(_call)


@dataclass(frozen=True, slots=True)
class WebFetchTool:
    adapter: ResearchAdapter
    limiter_registry: LimiterRegistry | None = None
    name: str = "web.fetch"
    description: str = "Fetch and extract readable content from one web page URL."
    args_schema: type[BaseModel] = WebFetchArgs

    def invoke(
        self, *, args: dict[str, object], context: ResearchToolContext
    ) -> ResearchToolResult:
        payload = WebFetchArgs.model_validate(args)
        fetch = getattr(self.adapter, "fetch_url")
        normalize = getattr(self.adapter, "normalize_fetch_response")

        def _call() -> ResearchToolResult:
            result = normalize(
                url=payload.url,
                query=payload.query,
                response=fetch(
                    url=payload.url,
                    query=payload.query,
                    extract_depth=payload.extract_depth,
                    format=payload.format,
                    include_images=payload.include_images,
                ),
            )
            return _tool_result(
                self.name,
                ResearchObservation(
                    status=result.status,
                    summary=result.summary,
                    findings=result.findings,
                    unresolved_gaps=result.unresolved_gaps,
                    provider="web",
                    raw_ref={
                        "unit_id": result.unit_id,
                        "error_message": result.error_message,
                        "escalation_reason": result.escalation_reason,
                    },
                ),
            )

        if self.limiter_registry is None:
            return _call()
        return self.limiter_registry.sync_limiter("research_provider").run(_call)


@dataclass(frozen=True, slots=True)
class ThinkResearchTool:
    name: str = "think_tool"
    description: str = "Record strategic reflection about current research progress."
    args_schema: type[BaseModel] = ThinkToolArgs

    def invoke(
        self, *, args: dict[str, object], context: ResearchToolContext
    ) -> ResearchToolResult:
        del context
        payload = ThinkToolArgs.model_validate(args)
        return ResearchToolResult(
            tool_name=self.name,
            summary=f"Reflection recorded: {payload.reflection}",
            payload={"reflection": payload.reflection},
        )


@dataclass(frozen=True, slots=True)
class PubMedSearchTool:
    service: BioResearchService
    name: str = "pubmed.search"
    description: str = "Search PubMed for biomedical literature."
    args_schema: type[BaseModel] = ProviderSearchArgs

    def invoke(
        self, *, args: dict[str, object], context: ResearchToolContext
    ) -> ResearchToolResult:
        payload = ProviderSearchArgs.model_validate(args)
        return _tool_result(
            self.name,
            _literature_observation(
                self.service,
                provider="pubmed",
                query=payload.query,
                limit=payload.limit,
            ),
        )


@dataclass(frozen=True, slots=True)
class SemanticScholarSearchTool:
    service: BioResearchService
    name: str = "semantic_scholar.search"
    description: str = (
        "Search Semantic Scholar for literature and citation-backed evidence."
    )
    args_schema: type[BaseModel] = ProviderSearchArgs

    def invoke(
        self, *, args: dict[str, object], context: ResearchToolContext
    ) -> ResearchToolResult:
        payload = ProviderSearchArgs.model_validate(args)
        return _tool_result(
            self.name,
            _literature_observation(
                self.service,
                provider="semantic_scholar",
                query=payload.query,
                limit=payload.limit,
            ),
        )


@dataclass(frozen=True, slots=True)
class UniProtLookupTool:
    service: BioResearchService
    name: str = "uniprot.lookup"
    description: str = "Look up normalized UniProt protein metadata."
    args_schema: type[BaseModel] = UniProtLookupArgs

    def invoke(
        self, *, args: dict[str, object], context: ResearchToolContext
    ) -> ResearchToolResult:
        payload = UniProtLookupArgs.model_validate(args)
        record = self.service.lookup_uniprot(accession=payload.accession)
        return _tool_result(
            self.name,
            ResearchObservation.completed(
                summary=f"Loaded UniProt metadata for {payload.accession}.",
                findings=(
                    {
                        "summary": f"{record.name} ({record.accession})",
                        "query": payload.accession,
                        "confidence_label": "high",
                        "sources": [
                            {
                                "title": record.name,
                                "locator": record.locator,
                                "kind": "dataset",
                                "snippet": record.organism,
                            }
                        ],
                    },
                ),
                provider="uniprot",
                raw_ref={"record": record.to_dict()},
            ),
        )


@dataclass(frozen=True, slots=True)
class RcsbSearchTool:
    service: BioResearchService
    name: str = "rcsb_pdb.search"
    description: str = "Search RCSB PDB for structure records."
    args_schema: type[BaseModel] = ProviderSearchArgs

    def invoke(
        self, *, args: dict[str, object], context: ResearchToolContext
    ) -> ResearchToolResult:
        payload = ProviderSearchArgs.model_validate(args)
        hits = self.service.search_rcsb_pdb(query=payload.query, limit=payload.limit)
        return _tool_result(
            self.name,
            ResearchObservation.completed(
                summary=f"Collected {len(hits)} structure hits for {payload.query}.",
                findings=tuple(structure_hits_to_findings(hits, query=payload.query)),
                provider="rcsb_pdb",
            ),
        )


@dataclass(frozen=True, slots=True)
class InterProQueryTool:
    service: BioResearchService
    name: str = "interpro.query"
    description: str = "Fetch InterPro annotation records for a UniProt accession."
    args_schema: type[BaseModel] = InterProQueryArgs

    def invoke(
        self, *, args: dict[str, object], context: ResearchToolContext
    ) -> ResearchToolResult:
        payload = InterProQueryArgs.model_validate(args)
        record = self.service.query_interpro(
            accession=payload.accession, limit=payload.limit
        )
        summary = f"Loaded {len(record.entries)} InterPro annotations for {payload.accession}."
        return _tool_result(
            self.name,
            ResearchObservation.completed(
                summary=summary,
                findings=(
                    {
                        "summary": summary,
                        "query": payload.accession,
                        "confidence_label": "medium",
                        "sources": [
                            {
                                "title": f"InterPro annotations for {payload.accession}",
                                "locator": record.locator,
                                "kind": "dataset",
                                "snippet": None
                                if not record.entries
                                else str(record.entries[0].get("name") or ""),
                            }
                        ],
                    },
                ),
                provider="interpro",
                raw_ref={"record": record.to_dict()},
            ),
        )


@dataclass(frozen=True, slots=True)
class LimitedResearchTool:
    tool: ResearchTool
    limiter_registry: LimiterRegistry
    limiter_name: str = "research_provider"

    @property
    def name(self) -> str:
        return self.tool.name

    @property
    def description(self) -> str:
        return self.tool.description

    @property
    def args_schema(self) -> type[BaseModel]:
        return self.tool.args_schema

    def invoke(
        self, *, args: dict[str, object], context: ResearchToolContext
    ) -> ResearchToolResult:
        return self.limiter_registry.sync_limiter(self.limiter_name).run(
            lambda: self.tool.invoke(args=args, context=context)
        )


@dataclass(frozen=True, slots=True)
class StaticResearchToolProvider:
    tools: Sequence[ResearchTool]

    def list_tools(self, context: ResearchToolContext) -> Sequence[ResearchTool]:
        del context
        return list(self.tools)


@dataclass(frozen=True, slots=True)
class CompositeResearchToolProvider:
    providers: Sequence[ResearchToolProvider]
    tool_allowlist: tuple[str, ...] = ()

    def list_tools(self, context: ResearchToolContext) -> Sequence[ResearchTool]:
        seen: set[str] = set()
        allowlist = set(self.tool_allowlist)
        resolved: list[ResearchTool] = []
        for provider in self.providers:
            for tool in provider.list_tools(context):
                if allowlist and tool.name not in allowlist:
                    continue
                if tool.name in seen:
                    continue
                seen.add(tool.name)
                resolved.append(tool)
        return resolved


@dataclass(frozen=True, slots=True)
class DefaultResearchToolProvider:
    research_adapter: ResearchAdapter | None = None
    mcp_tools: Sequence[ResearchTool] = ()
    mcp_enabled: bool = False
    mcp_tool_allowlist: tuple[str, ...] = ()
    limiter_registry: LimiterRegistry | None = None

    def list_tools(self, context: ResearchToolContext) -> Sequence[ResearchTool]:
        providers: list[ResearchToolProvider] = [
            StaticResearchToolProvider([ThinkResearchTool()])
        ]
        if self.research_adapter is not None and _web_tool_enabled(
            self.research_adapter
        ):
            providers.append(
                StaticResearchToolProvider(
                    [
                        WebSearchTool(self.research_adapter, self.limiter_registry),
                        WebFetchTool(self.research_adapter, self.limiter_registry),
                    ]
                )
            )
        if self.mcp_enabled and self.mcp_tools:
            providers.append(
                StaticResearchToolProvider(
                    list(
                        _limited_tools(
                            _filtered_mcp_tools(
                                self.mcp_tools, self.mcp_tool_allowlist
                            ),
                            self.limiter_registry,
                        )
                    )
                )
            )
        return CompositeResearchToolProvider(providers).list_tools(context)


def build_bio_research_tools(service: BioResearchService) -> Sequence[ResearchTool]:
    return (
        PubMedSearchTool(service),
        SemanticScholarSearchTool(service),
        UniProtLookupTool(service),
        RcsbSearchTool(service),
        InterProQueryTool(service),
    )


def _filtered_mcp_tools(
    tools: Sequence[ResearchTool],
    allowlist: tuple[str, ...],
) -> Iterable[ResearchTool]:
    allowed = set(allowlist)
    if not allowed:
        yield from tools
        return
    for tool in tools:
        if tool.name in allowed:
            yield tool


def _limited_tools(
    tools: Iterable[ResearchTool],
    limiter_registry: LimiterRegistry | None,
) -> Iterable[ResearchTool]:
    if limiter_registry is None:
        yield from tools
        return
    for tool in tools:
        if isinstance(tool, LimitedResearchTool):
            yield tool
        else:
            yield LimitedResearchTool(tool, limiter_registry)


__all__ = [
    "CompositeResearchToolProvider",
    "DefaultResearchToolProvider",
    "build_bio_research_tools",
    "LimitedResearchTool",
    "StaticResearchToolProvider",
    "ThinkResearchTool",
    "ThinkToolArgs",
    "WebFetchArgs",
    "WebFetchTool",
    "WebSearchArgs",
    "WebSearchTool",
]
