"""Bridge package for V3 capability engines."""

from openzyme_core import EngineRegistry

from .deep_research import DeepResearchEngine
from .deep_research import DeepResearchRunner
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
from .execution import DefaultExecutionRequestCompiler
from .execution import DefaultExecutionResultParser
from .execution import DefaultPreprocessAdapter
from .execution import ExecutionEngine
from .execution import ExecutionHandoff
from .execution import ExecutionOutcome
from .execution import ExecutionParsedResult
from .execution import ExecutionStartResult
from .execution import ExecutionStatusSnapshot
from .execution import PreprocessArtifactDraft
from .execution import PreprocessResult
from .execution import register_execution_tools
from .podman_sandbox import DEFAULT_SANDBOX_IMAGE
from .podman_sandbox import PodmanPipelineSandboxRunner
from .podman_sandbox import PodmanSandboxPreflight


def build_engine_registry(*engines: object) -> EngineRegistry:
    registry = EngineRegistry()
    for engine in engines:
        registry.register(engine)  # type: ignore[arg-type]
    return registry

__all__ = [
    "build_engine_registry",
    "DefaultExecutionRequestCompiler",
    "DefaultExecutionResultParser",
    "DefaultPreprocessAdapter",
    "DeepResearchEngine",
    "DeepResearchRunner",
    "EvidenceSynthesis",
    "EvidenceSynthesisItem",
    "ExecutionEngine",
    "ExecutionHandoff",
    "ExecutionOutcome",
    "ExecutionParsedResult",
    "ExecutionStartResult",
    "ExecutionStatusSnapshot",
    "DEFAULT_SANDBOX_IMAGE",
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
    "PreprocessArtifactDraft",
    "PreprocessResult",
    "PodmanPipelineSandboxRunner",
    "PodmanSandboxPreflight",
    "register_deep_research_tools",
    "register_execution_tools",
]
