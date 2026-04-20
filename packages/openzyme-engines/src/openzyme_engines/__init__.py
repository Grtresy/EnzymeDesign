"""Bridge package for V3 capability engines."""

from .deep_research import DeepResearchEngine
from .deep_research import DeepResearchRunner
from .deep_research import GraphBackedDeepResearchRunner
from .deep_research import NormalizedResearchDossier
from .deep_research import ResearchEvidenceItem
from .deep_research import ResearchStartResult
from .deep_research import register_deep_research_tools

__all__ = [
    "DeepResearchEngine",
    "DeepResearchRunner",
    "GraphBackedDeepResearchRunner",
    "NormalizedResearchDossier",
    "ResearchEvidenceItem",
    "ResearchStartResult",
    "register_deep_research_tools",
]
