"""Provider-neutral Research Plugin contracts and runtime contributions."""

from .contracts import RESEARCH_INVOCATION_SCHEMA_VERSION
from .contracts import RESEARCH_PROVIDER_RECEIPT_SCHEMA_VERSION
from .contracts import RESEARCH_PROVIDER_DESCRIPTOR_SCHEMA_VERSION
from .contracts import RESEARCH_PROVIDER_CONTRACT_DIGEST
from .contracts import RESEARCH_REQUEST_SCHEMA_VERSION
from .contracts import ResearchEvidence
from .contracts import ResearchGap
from .contracts import ResearchInvocationRecord
from .contracts import ResearchInvocationStatus
from .contracts import ResearchProviderReceipt
from .contracts import ResearchProviderDescriptor
from .contracts import ResearchProviderKind
from .contracts import ResearchProviderRequest
from .contracts import ResearchProviderSource
from .contracts import ResearchRequest
from .contracts import ResearchSourceRef
from .contracts import ResearchSummary
from .contracts import ResearchSummaryStatus
from .contracts import ResearchUnitSpec
from .contracts import SourceRefKind
from .adapters import ResearchAdapter
from .adapters import ResearchFinding
from .adapters import ResearchSource
from .adapters import ResearchUnit
from .adapters import ResearchUnitResult
from .observations import ResearchFileManifest
from .observations import ResearchObservation
from .provider_runtime import BoundedCallableClient
from .provider_runtime import BoundedHttpClient
from .provider_runtime import ProviderAttempt
from .provider_runtime import ProviderCallResult
from .provider_runtime import ProviderFailure
from .provider_runtime import ProviderHttpResponse
from .provider_runtime import ProviderOutcome
from .provider_runtime import ProviderProvenance
from .provider_runtime import ProviderRequestError
from .provider_runtime import combine_provenance
from .provider_runtime import completed_result
from .provider_runtime import degraded_result
from .provider_runtime import failed_result
from .provider_runtime import provider_identity_digest
from .provider_runtime import provider_schema_error
from .provider_runtime import safe_public_locator
from .runtime import RESEARCH_START_TOOL_SPEC
from .runtime import RESEARCH_PROJECTION_CONTRACT_DIGEST
from .runtime import ResearchPluginRuntimeSurfaces
from .runtime import ResearchProjection
from .runtime import ResearchStartToolRuntime
from .runtime import ResearchWorker
from .runtime import build_research_plugin_runtime_surfaces
from .services import InMemoryResearchRepository
from .services import RESEARCH_PLUGIN_ID
from .services import RESEARCH_PROVIDER_CAPABILITY
from .services import RESEARCH_PROVIDER_CONTRACT
from .services import ResearchContextFactory
from .services import ResearchOrchestrationService
from .services import ResearchProviderPort
from .services import ResearchRepository

__all__ = [
    "BoundedCallableClient",
    "BoundedHttpClient",
    "InMemoryResearchRepository",
    "ProviderAttempt",
    "ProviderCallResult",
    "ProviderFailure",
    "ProviderHttpResponse",
    "ProviderOutcome",
    "ProviderProvenance",
    "ProviderRequestError",
    "RESEARCH_INVOCATION_SCHEMA_VERSION",
    "RESEARCH_PLUGIN_ID",
    "RESEARCH_PROVIDER_CAPABILITY",
    "RESEARCH_PROVIDER_CONTRACT",
    "RESEARCH_PROVIDER_CONTRACT_DIGEST",
    "RESEARCH_PROVIDER_DESCRIPTOR_SCHEMA_VERSION",
    "RESEARCH_PROVIDER_RECEIPT_SCHEMA_VERSION",
    "RESEARCH_REQUEST_SCHEMA_VERSION",
    "RESEARCH_PROJECTION_CONTRACT_DIGEST",
    "RESEARCH_START_TOOL_SPEC",
    "ResearchContextFactory",
    "ResearchAdapter",
    "ResearchEvidence",
    "ResearchFileManifest",
    "ResearchGap",
    "ResearchInvocationRecord",
    "ResearchInvocationStatus",
    "ResearchObservation",
    "ResearchPluginRuntimeSurfaces",
    "ResearchOrchestrationService",
    "ResearchProjection",
    "ResearchProviderPort",
    "ResearchProviderDescriptor",
    "ResearchProviderKind",
    "ResearchProviderReceipt",
    "ResearchProviderRequest",
    "ResearchProviderSource",
    "ResearchRepository",
    "ResearchRequest",
    "ResearchFinding",
    "ResearchSource",
    "ResearchSourceRef",
    "ResearchStartToolRuntime",
    "ResearchSummary",
    "ResearchSummaryStatus",
    "ResearchUnitSpec",
    "ResearchUnit",
    "ResearchUnitResult",
    "ResearchWorker",
    "SourceRefKind",
    "combine_provenance",
    "completed_result",
    "degraded_result",
    "failed_result",
    "provider_identity_digest",
    "provider_schema_error",
    "safe_public_locator",
    "build_research_plugin_runtime_surfaces",
]
