"""Bridge package for V3 capability engines."""

from openzyme_runtime import EngineRegistry

from .deep_research import DeepResearchEngine
from .deep_research import DeepResearchRunner
from .deep_research import DeepResearchRuntimeError
from .deep_research import DirectDeepResearchRunner
from .deep_research import GraphBackedDeepResearchRunner
from .deep_research import NativeDeepResearchRunner
from .deep_research import NormalizedResearchDossier
from .deep_research import ResearchEvidenceItem
from .deep_research import ResearchStartResult
from .deep_research import register_deep_research_tools
from .deep_research_contracts import EvidenceSynthesis
from .deep_research_contracts import EvidenceSynthesisItem
from .deep_research_contracts import IntakeClarification
from .deep_research_contracts import ResearchBriefDraft
from .deep_research_contracts import ResearchDossier
from .deep_research_contracts import ResearchSourceItem
from .deep_research_contracts import ResearchSupervisorAction
from .deep_research_contracts import ResearchTurnRecord
from .deep_research_contracts import ResearchUnitDraft
from .deep_research_contracts import ResearchUnitPlan


def build_engine_registry(*engines: object) -> EngineRegistry:
    registry = EngineRegistry()
    for engine in engines:
        registry.register(engine)  # type: ignore[arg-type]
    return registry

__all__ = [
    "build_engine_registry",
    "DeepResearchEngine",
    "DeepResearchRunner",
    "DeepResearchRuntimeError",
    "EvidenceSynthesis",
    "EvidenceSynthesisItem",
    "DirectDeepResearchRunner",
    "GraphBackedDeepResearchRunner",
    "IntakeClarification",
    "NativeDeepResearchRunner",
    "NormalizedResearchDossier",
    "ResearchBriefDraft",
    "ResearchDossier",
    "ResearchEvidenceItem",
    "ResearchSourceItem",
    "ResearchStartResult",
    "ResearchSupervisorAction",
    "ResearchTurnRecord",
    "ResearchUnitDraft",
    "ResearchUnitPlan",
    "register_deep_research_tools",
]
