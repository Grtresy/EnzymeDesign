from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ai import ChatModelFactory
from .limits import LimiterRegistry
from .reliability import ReliabilityShadowObserver
from .seams import ResearchAdapter
from .seams import ResearchToolProvider
from .settings import OpenZymeSettings


@dataclass(frozen=True, slots=True)
class RuntimeFoundation:
    workspace_runner: Any | None = None
    research_adapter: ResearchAdapter | None = None
    research_tool_provider: ResearchToolProvider | None = None
    bio_research_service: Any | None = None
    model_factory: ChatModelFactory | None = None
    limiter_registry: LimiterRegistry | None = None
    settings: OpenZymeSettings | None = None
    reliability_shadow_observer: ReliabilityShadowObserver | None = None


def validate_runtime_foundation_support() -> None:
    assert RuntimeFoundation is not None
