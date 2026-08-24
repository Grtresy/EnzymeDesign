"""Explicit official Standard Distribution composition and product lifecycle."""

from .application_runtime import StandardKernelApplicationRuntime
from .application_runtime import StandardOperationalAdapterSelection
from .application_runtime import StandardOperationalRuntimePorts
from .application_runtime import build_standard_kernel_application_runtime
from .application_runtime import build_standard_operational_runtime_ports

from .composition import STANDARD_ADAPTER_SLOTS
from .composition import STANDARD_KERNEL_ENTITY_TYPES
from .composition import StandardDeploymentStartup
from .composition import StandardKernelStoreCodecCoverage
from .composition import StandardKernelStoreReadinessError
from .composition import StandardKernelPublicationRuntime
from .composition import StandardPluginFreeCapabilityRegistryResolver
from .composition import activate_standard_composition
from .composition import build_standard_fresh_install_seed
from .composition import build_standard_kernel_control_store
from .composition import build_standard_kernel_publication_runtime
from .composition import build_standard_kernel_public_projection_provider
from .composition import inspect_standard_kernel_store_codec_coverage
from .composition import load_standard_composition
from .composition import mount_standard_kernel_workspace_tool_set
from .composition import select_standard_component_locators
from .composition import standard_component_locators
from .composition import standard_kernel_entity_codecs
from .composition import verify_standard_deployment_startup_read_only
from .coordination_routes import STANDARD_COORDINATION_ROUTE_IDS
from .coordination_routes import StandardKernelCoordinationRouteApplication
from .coordination_routes import build_standard_coordination_route_applications
from .coordination_routes import build_standard_command_context
from .factories import StandardLocalWorkspaceAdapterFactory
from .factories import StandardLocalWorkspaceRuntimeAdapters
from .factories import StandardLocalWorkspaceRuntimeFactory
from .factories import StandardLlmAdapterFactory
from .factories import StandardRepositoryAdapterFactory
from .host_gateway import STANDARD_ROOT_AUTHORITY_OPERATIONS
from .host_gateway import StandardHostKernelCommandGateway
from .host_gateway import StandardHostRouteApplication
from .host_gateway import StandardSessionBootstrapAuthorityPort
from .host_gateway import StandardWorkspaceBootstrapDefaults
from .host_surface import build_standard_file_workspace_v2_host_surface
from .host_surface import build_standard_v2_host_app
from .launcher import STANDARD_LAUNCHER_SCHEMA_VERSION
from .launcher import StandardProductLauncherConfig
from .launcher import StandardProductLauncherError
from .launcher import compose_standard_product_from_config
from .launcher import load_standard_product_composition_factory
from .launcher import load_standard_product_launcher_config
from .launcher import serve_standard_product
from .lifecycle import StandardProductComposition
from .lifecycle import StandardProductCompositionFactoryPort
from .lifecycle import StandardProductLifecycle
from .lifecycle import StandardProductLifecycleError
from .lifecycle import StandardProductLifecycleState
from .lifecycle import StandardProductPreflightReceipt
from .lifecycle import StandardProductWorkerBounds
from .lifecycle import StandardProductWorkerTick
from .lifecycle import SystemUtcClock
from .lifecycle import UuidIdGenerator
from .lifecycle import preflight_standard_product_composition
from .operational_routes import STANDARD_OPERATIONAL_ROUTE_IDS
from .operational_routes import StandardKernelOperationalRouteApplication
from .operational_routes import StandardRuntimeDrainApplication
from .operational_routes import StandardWorkspaceToolRuntime
from .operational_routes import build_standard_operational_route_applications
from .runtime_drain import StandardBoundedRuntimeDrainApplication
from .runtime_admission import StandardKernelRuntimeAdmissionSource
from .runtime_command_worker import StandardRuntimeCommandContextFactory
from .runtime_command_worker import StandardRuntimeCommandExecutor
from .runtime_command_worker import StandardRuntimeCommandWorker
from .role_policies import STANDARD_RESIDENT_ROLES
from .role_policies import standard_subject_policy_decisions
from .role_policies import standard_subject_policy_decisions_by_role
from .role_policies import standard_tool_exposure_policies
from .workflow_registry import STANDARD_WORKFLOW_REGISTRY_ID
from .workflow_registry import STANDARD_WORKFLOW_REGISTRY_SNAPSHOT_DIGEST
from .workflow_registry import StandardExplicitEmptyWorkflowRegistry
from .workspace_context import StandardLocalWorkspaceToolContextResolver
from .workspace_provisioning_worker import StandardWorkspaceProvisioningWorker

COMPONENT_ID = "openzyme.standard"
COMPONENT_KIND = "distribution"
MIGRATION_STATE = "target_distribution_activatable"

__all__ = [
    "COMPONENT_ID",
    "COMPONENT_KIND",
    "MIGRATION_STATE",
    "STANDARD_ADAPTER_SLOTS",
    "STANDARD_KERNEL_ENTITY_TYPES",
    "STANDARD_COORDINATION_ROUTE_IDS",
    "STANDARD_OPERATIONAL_ROUTE_IDS",
    "STANDARD_LAUNCHER_SCHEMA_VERSION",
    "STANDARD_RESIDENT_ROLES",
    "StandardDeploymentStartup",
    "StandardKernelStoreCodecCoverage",
    "StandardKernelStoreReadinessError",
    "StandardKernelPublicationRuntime",
    "StandardKernelCoordinationRouteApplication",
    "StandardKernelOperationalRouteApplication",
    "StandardKernelApplicationRuntime",
    "StandardOperationalAdapterSelection",
    "StandardOperationalRuntimePorts",
    "StandardPluginFreeCapabilityRegistryResolver",
    "StandardProductComposition",
    "StandardProductCompositionFactoryPort",
    "StandardProductLauncherConfig",
    "StandardProductLauncherError",
    "StandardProductLifecycle",
    "StandardProductLifecycleError",
    "StandardProductLifecycleState",
    "StandardProductPreflightReceipt",
    "StandardProductWorkerBounds",
    "StandardProductWorkerTick",
    "StandardLocalWorkspaceAdapterFactory",
    "StandardLocalWorkspaceRuntimeAdapters",
    "StandardLocalWorkspaceRuntimeFactory",
    "StandardLocalWorkspaceToolContextResolver",
    "StandardLlmAdapterFactory",
    "StandardRepositoryAdapterFactory",
    "StandardRuntimeDrainApplication",
    "StandardBoundedRuntimeDrainApplication",
    "StandardKernelRuntimeAdmissionSource",
    "StandardRuntimeCommandContextFactory",
    "StandardRuntimeCommandExecutor",
    "StandardRuntimeCommandWorker",
    "StandardWorkspaceToolRuntime",
    "StandardWorkspaceProvisioningWorker",
    "STANDARD_WORKFLOW_REGISTRY_ID",
    "STANDARD_WORKFLOW_REGISTRY_SNAPSHOT_DIGEST",
    "StandardExplicitEmptyWorkflowRegistry",
    "SystemUtcClock",
    "UuidIdGenerator",
    "STANDARD_ROOT_AUTHORITY_OPERATIONS",
    "StandardHostKernelCommandGateway",
    "StandardHostRouteApplication",
    "StandardSessionBootstrapAuthorityPort",
    "StandardWorkspaceBootstrapDefaults",
    "activate_standard_composition",
    "build_standard_fresh_install_seed",
    "build_standard_kernel_control_store",
    "build_standard_kernel_application_runtime",
    "build_standard_operational_runtime_ports",
    "build_standard_coordination_route_applications",
    "build_standard_command_context",
    "build_standard_operational_route_applications",
    "build_standard_kernel_publication_runtime",
    "build_standard_kernel_public_projection_provider",
    "build_standard_file_workspace_v2_host_surface",
    "build_standard_v2_host_app",
    "compose_standard_product_from_config",
    "inspect_standard_kernel_store_codec_coverage",
    "load_standard_composition",
    "load_standard_product_composition_factory",
    "load_standard_product_launcher_config",
    "mount_standard_kernel_workspace_tool_set",
    "select_standard_component_locators",
    "serve_standard_product",
    "standard_subject_policy_decisions",
    "standard_subject_policy_decisions_by_role",
    "standard_tool_exposure_policies",
    "standard_component_locators",
    "standard_kernel_entity_codecs",
    "preflight_standard_product_composition",
    "verify_standard_deployment_startup_read_only",
]
