from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ai import ChatModelFactory
from .limits import LimiterRegistry
from .seams import ExecutionAdapter
from .seams import HpcCatalogProvider
from .seams import HpcExecutionRegistry
from .seams import ResearchAdapter
from .seams import ResearchToolProvider
from .settings import OpenZymeSettings


@dataclass(frozen=True, slots=True)
class RuntimeFoundation:
    execution_adapter: ExecutionAdapter | None = None
    hpc_catalog_provider: HpcCatalogProvider | None = None
    hpc_execution_registry: HpcExecutionRegistry | None = None
    research_adapter: ResearchAdapter | None = None
    research_tool_provider: ResearchToolProvider | None = None
    bio_research_service: Any | None = None
    model_factory: ChatModelFactory | None = None
    limiter_registry: LimiterRegistry | None = None
    settings: OpenZymeSettings | None = None


def validate_runtime_foundation_support() -> None:
    assert RuntimeFoundation is not None
