from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from typing import Sequence
from uuid import uuid4

from pydantic import BaseModel
from pydantic import Field

from openzyme_research import ResearchAdapter
from openzyme_research import ResearchUnit
from openzyme_research import BioResearchService
from openzyme_research import ResearchObservation
from openzyme_research import asset_manifest
from openzyme_research import literature_hits_to_findings
from openzyme_research import structure_hits_to_findings

from .seams import ResearchTool
from .seams import ResearchToolContext
from .seams import ResearchToolProvider
from .seams import ResearchToolResult


class SearchCollectArgs(BaseModel):
    query: str
    topic: str = "general evidence"


class ThinkToolArgs(BaseModel):
    reflection: str = Field(min_length=1)


class ProviderSearchArgs(BaseModel):
    query: str
    limit: int = Field(default=5, ge=1, le=20)


class UniProtLookupArgs(BaseModel):
    accession: str = Field(min_length=1)


class UniProtDownloadArgs(BaseModel):
    accession: str = Field(min_length=1)


class RcsbDownloadArgs(BaseModel):
    pdb_id: str = Field(min_length=1)
    format: str = Field(default="pdb")


class InterProQueryArgs(BaseModel):
    accession: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


def _stage_asset(asset: object) -> dict[str, object]:
    from openzyme_research import DownloadedResearchAsset

    staged = asset if isinstance(asset, DownloadedResearchAsset) else None
    if staged is None:
        raise TypeError("expected DownloadedResearchAsset")
    root = Path("/tmp/openzyme-deep-research-artifacts")
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{uuid4().hex[:12]}_{staged.filename}"
    target.write_bytes(staged.content)
    manifest = asset_manifest(staged)
    manifest["storage_uri"] = str(target)
    return manifest


def _tool_result(tool_name: str, observation: ResearchObservation) -> ResearchToolResult:
    payload = observation.to_dict()
    return ResearchToolResult(tool_name=tool_name, summary=payload["summary"], payload=payload)


@dataclass(frozen=True, slots=True)
class ResearchAdapterSearchTool:
    adapter: ResearchAdapter
    name: str = "search.collect"
    description: str = "Collect evidence for a research query and return normalized findings."
    args_schema: type[BaseModel] = SearchCollectArgs

    def invoke(self, *, args: dict[str, object], context: ResearchToolContext) -> ResearchToolResult:
        payload = SearchCollectArgs.model_validate(args)
        result = self.adapter.conduct(
            episode_id=context.episode_id,
            research_brief=context.research_brief,
            unit=ResearchUnit(
                unit_id=f"search-{context.tool_call_iterations + 1}",
                topic=payload.topic,
                query=payload.query,
            ),
        )
        return _tool_result(
            self.name,
            ResearchObservation(
                status=result.status,
                summary=result.summary,
                findings=result.findings,
                unresolved_gaps=result.unresolved_gaps,
                provider=self.name,
                raw_ref={
                    "unit_id": result.unit_id,
                    "error_message": result.error_message,
                    "escalation_reason": result.escalation_reason,
                },
            ),
        )


@dataclass(frozen=True, slots=True)
class ThinkResearchTool:
    name: str = "think_tool"
    description: str = "Record strategic reflection about current research progress."
    args_schema: type[BaseModel] = ThinkToolArgs

    def invoke(self, *, args: dict[str, object], context: ResearchToolContext) -> ResearchToolResult:
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

    def invoke(self, *, args: dict[str, object], context: ResearchToolContext) -> ResearchToolResult:
        payload = ProviderSearchArgs.model_validate(args)
        hits = self.service.search_pubmed(query=payload.query, limit=payload.limit)
        return _tool_result(
            self.name,
            ResearchObservation.completed(
                summary=f"Collected {len(hits)} PubMed hits for {payload.query}.",
                findings=tuple(literature_hits_to_findings(hits, query=payload.query)),
                provider="pubmed",
            ),
        )


@dataclass(frozen=True, slots=True)
class SemanticScholarSearchTool:
    service: BioResearchService
    name: str = "semantic_scholar.search"
    description: str = "Search Semantic Scholar for literature and citation-backed evidence."
    args_schema: type[BaseModel] = ProviderSearchArgs

    def invoke(self, *, args: dict[str, object], context: ResearchToolContext) -> ResearchToolResult:
        payload = ProviderSearchArgs.model_validate(args)
        hits = self.service.search_semantic_scholar(query=payload.query, limit=payload.limit)
        return _tool_result(
            self.name,
            ResearchObservation.completed(
                summary=f"Collected {len(hits)} Semantic Scholar hits for {payload.query}.",
                findings=tuple(literature_hits_to_findings(hits, query=payload.query)),
                provider="semantic_scholar",
            ),
        )


@dataclass(frozen=True, slots=True)
class UniProtLookupTool:
    service: BioResearchService
    name: str = "uniprot.lookup"
    description: str = "Look up normalized UniProt protein metadata."
    args_schema: type[BaseModel] = UniProtLookupArgs

    def invoke(self, *, args: dict[str, object], context: ResearchToolContext) -> ResearchToolResult:
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
class UniProtDownloadFastaTool:
    service: BioResearchService
    name: str = "uniprot.download_fasta"
    description: str = "Download FASTA sequence from UniProt."
    args_schema: type[BaseModel] = UniProtDownloadArgs

    def invoke(self, *, args: dict[str, object], context: ResearchToolContext) -> ResearchToolResult:
        payload = UniProtDownloadArgs.model_validate(args)
        asset = self.service.download_uniprot_fasta(accession=payload.accession)
        return _tool_result(
            self.name,
            ResearchObservation.completed(
                summary=f"Downloaded FASTA for {payload.accession}.",
                artifacts=(_stage_asset(asset),),
                provider="uniprot",
            ),
        )


@dataclass(frozen=True, slots=True)
class RcsbSearchTool:
    service: BioResearchService
    name: str = "rcsb_pdb.search"
    description: str = "Search RCSB PDB for structure records."
    args_schema: type[BaseModel] = ProviderSearchArgs

    def invoke(self, *, args: dict[str, object], context: ResearchToolContext) -> ResearchToolResult:
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
class RcsbDownloadStructureTool:
    service: BioResearchService
    name: str = "rcsb_pdb.download_structure"
    description: str = "Download a PDB or mmCIF structure file."
    args_schema: type[BaseModel] = RcsbDownloadArgs

    def invoke(self, *, args: dict[str, object], context: ResearchToolContext) -> ResearchToolResult:
        payload = RcsbDownloadArgs.model_validate(args)
        asset = self.service.download_rcsb_structure(pdb_id=payload.pdb_id, file_format=payload.format)
        return _tool_result(
            self.name,
            ResearchObservation.completed(
                summary=f"Downloaded structure file for {payload.pdb_id}.",
                artifacts=(_stage_asset(asset),),
                provider="rcsb_pdb",
            ),
        )


@dataclass(frozen=True, slots=True)
class InterProQueryTool:
    service: BioResearchService
    name: str = "interpro.query"
    description: str = "Fetch InterPro annotation records for a UniProt accession."
    args_schema: type[BaseModel] = InterProQueryArgs

    def invoke(self, *, args: dict[str, object], context: ResearchToolContext) -> ResearchToolResult:
        payload = InterProQueryArgs.model_validate(args)
        record = self.service.query_interpro(accession=payload.accession, limit=payload.limit)
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
                                "snippet": None if not record.entries else str(record.entries[0].get("name") or ""),
                            }
                        ],
                    },
                ),
                provider="interpro",
                raw_ref={"record": record.to_dict()},
            ),
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

    def list_tools(self, context: ResearchToolContext) -> Sequence[ResearchTool]:
        providers: list[ResearchToolProvider] = [StaticResearchToolProvider([ThinkResearchTool()])]
        if self.research_adapter is not None:
            providers.append(StaticResearchToolProvider([ResearchAdapterSearchTool(self.research_adapter)]))
        if self.mcp_enabled and self.mcp_tools:
            providers.append(
                StaticResearchToolProvider(
                    list(_filtered_mcp_tools(self.mcp_tools, self.mcp_tool_allowlist))
                )
            )
        return CompositeResearchToolProvider(providers).list_tools(context)


def build_bio_research_tools(service: BioResearchService) -> Sequence[ResearchTool]:
    return (
        PubMedSearchTool(service),
        SemanticScholarSearchTool(service),
        UniProtLookupTool(service),
        UniProtDownloadFastaTool(service),
        RcsbSearchTool(service),
        RcsbDownloadStructureTool(service),
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


__all__ = [
    "CompositeResearchToolProvider",
    "DefaultResearchToolProvider",
    "build_bio_research_tools",
    "ResearchAdapterSearchTool",
    "SearchCollectArgs",
    "StaticResearchToolProvider",
    "ThinkResearchTool",
    "ThinkToolArgs",
]
