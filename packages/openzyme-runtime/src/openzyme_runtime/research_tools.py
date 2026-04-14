from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from typing import Sequence

from pydantic import BaseModel
from pydantic import Field

from openzyme_research import ResearchAdapter
from openzyme_research import ResearchUnit

from .contracts import ResearchSourceItem
from .seams import ResearchTool
from .seams import ResearchToolContext
from .seams import ResearchToolProvider
from .seams import ResearchToolResult


class SearchCollectArgs(BaseModel):
    query: str
    topic: str = "general evidence"


class ThinkToolArgs(BaseModel):
    reflection: str = Field(min_length=1)


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
        return ResearchToolResult(
            tool_name=self.name,
            summary=result.summary,
            payload={
                "status": result.status,
                "unit_id": result.unit_id,
                "summary": result.summary,
                "findings": [
                    {
                        "summary": finding.summary,
                        "query": finding.query,
                        "confidence_label": finding.confidence_label,
                        "sources": [
                            ResearchSourceItem(
                                title=source.title,
                                locator=source.locator,
                                kind=source.kind.value,
                                snippet=source.snippet,
                            ).model_dump()
                            for source in finding.sources
                        ],
                    }
                    for finding in result.findings
                ],
                "unresolved_gaps": list(result.unresolved_gaps),
                "error_message": result.error_message,
                "escalation_reason": result.escalation_reason,
            },
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
    "ResearchAdapterSearchTool",
    "SearchCollectArgs",
    "StaticResearchToolProvider",
    "ThinkResearchTool",
    "ThinkToolArgs",
]
