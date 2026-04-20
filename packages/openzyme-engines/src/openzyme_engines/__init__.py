"""Bridge package for V3 capability engines."""

from openzyme_core import EngineRegistry

from .deep_research import DeepResearchEngine
from .deep_research import DeepResearchRunner
from .deep_research import GraphBackedDeepResearchRunner
from .deep_research import NormalizedResearchDossier
from .deep_research import ResearchEvidenceItem
from .deep_research import ResearchStartResult
from .deep_research import register_deep_research_tools
from .execution import DefaultExecutionRequestCompiler
from .execution import DefaultExecutionResultParser
from .execution import ExecutionEngine
from .execution import ExecutionHandoff
from .execution import ExecutionOutcome
from .execution import ExecutionParsedResult
from .execution import ExecutionStartResult
from .execution import ExecutionStatusSnapshot
from .execution import register_execution_tools


def build_engine_registry(*engines: object) -> EngineRegistry:
    registry = EngineRegistry()
    for engine in engines:
        registry.register(engine)  # type: ignore[arg-type]
    return registry

__all__ = [
    "build_engine_registry",
    "DefaultExecutionRequestCompiler",
    "DefaultExecutionResultParser",
    "DeepResearchEngine",
    "DeepResearchRunner",
    "ExecutionEngine",
    "ExecutionHandoff",
    "ExecutionOutcome",
    "ExecutionParsedResult",
    "ExecutionStartResult",
    "ExecutionStatusSnapshot",
    "GraphBackedDeepResearchRunner",
    "NormalizedResearchDossier",
    "ResearchEvidenceItem",
    "ResearchStartResult",
    "register_deep_research_tools",
    "register_execution_tools",
]
