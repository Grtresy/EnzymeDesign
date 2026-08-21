from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openzyme_contracts import ClockPort
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import WorkspaceRevisionBackendPort
from openzyme_kernel import AgentAuthorityLeaseKernelApplicationService
from openzyme_kernel import ApprovalKernelApplicationService
from openzyme_kernel import AuthorityKernelApplicationService
from openzyme_kernel import CollaborationKernelApplicationService
from openzyme_kernel import ControlStoreRuntimeOutcomeRepository
from openzyme_kernel import ControlledOperationKernelApplicationService
from openzyme_kernel import ExtensionBundleRegistry
from openzyme_kernel import FinishValidatorRegistry
from openzyme_kernel import LocalWorkspaceToolContextResolver
from openzyme_kernel import MessageIngressKernelApplicationService
from openzyme_kernel import MountedRuntimeCapabilityGateway
from openzyme_kernel import ProtocolKernelApplicationService
from openzyme_kernel import PublicationKernelApplicationService
from openzyme_kernel import RuntimeCoordinationKernelApplicationService
from openzyme_kernel import RuntimeTurnCoordinator
from openzyme_kernel import SessionBootstrapKernelApplicationService
from openzyme_kernel import TaskKernelApplicationService
from openzyme_kernel import build_kernel_workspace_tool_runtimes
from openzyme_process_podman import PodmanWorkspaceMountResolver
from openzyme_runtime_spi import AgentRuntimeAdapter
from openzyme_runtime_spi import ProcessIsolationPort
from openzyme_store_sqlite import SQLiteControlStore

from .composition import StandardDeploymentStartup
from .composition import StandardPluginFreeCapabilityRegistryResolver
from .composition import activate_standard_composition
from .composition import build_standard_kernel_control_store
from .composition import mount_standard_kernel_workspace_tool_set
from .coordination_routes import StandardKernelCoordinationRouteApplication
from .coordination_routes import build_standard_coordination_route_applications
from .host_gateway import StandardHostKernelCommandGateway
from .host_gateway import StandardSessionBootstrapAuthorityPort
from .operational_routes import StandardKernelOperationalRouteApplication
from .operational_routes import StandardRuntimeDrainApplication
from .operational_routes import build_standard_operational_route_applications
from .factories import StandardLocalWorkspaceRuntimeAdapters
from .factories import StandardLocalWorkspaceRuntimeFactory
from .runtime_admission import StandardKernelRuntimeAdmissionSource
from .runtime_drain import StandardBoundedRuntimeDrainApplication
from .workspace_context import StandardLocalWorkspaceToolContextResolver


@dataclass(frozen=True, slots=True)
class StandardKernelApplicationRuntime:
    """Real Plugin-free Standard Kernel application graph behind generic Host."""

    store: SQLiteControlStore
    bootstrap: SessionBootstrapKernelApplicationService
    coordination: StandardKernelCoordinationRouteApplication
    gateway: StandardHostKernelCommandGateway


@dataclass(frozen=True, slots=True)
class StandardOperationalRuntimePorts:
    """Exact selected Adapter applications needed by effectful Standard routes."""

    runtime_drain: StandardRuntimeDrainApplication
    workspace: StandardLocalWorkspaceRuntimeAdapters
    workspace_context: LocalWorkspaceToolContextResolver
    revision_backend: WorkspaceRevisionBackendPort


@dataclass(frozen=True, slots=True)
class StandardOperationalAdapterSelection:
    """Exact effect implementations selected by the Standard Distribution."""

    runtime_adapter: AgentRuntimeAdapter
    workspace_mounts: PodmanWorkspaceMountResolver
    process_isolation: ProcessIsolationPort
    revision_backend: WorkspaceRevisionBackendPort
    workspace_provider_id: str = "openzyme.workspace.git-lfs"
    podman_binary: str = "/usr/bin/podman"


def build_standard_operational_runtime_ports(
    *,
    store: SQLiteControlStore,
    startup: StandardDeploymentStartup,
    clock: ClockPort,
    ids: IdGeneratorPort,
    selection: StandardOperationalAdapterSelection,
) -> StandardOperationalRuntimePorts:
    """Compose selected Adapters behind Kernel semantic and authority owners.

    Construction performs no model, Podman, filesystem, Git or network effect.
    The runtime Adapter receives only an admitted command and capability gateway,
    never a repository or mutable Kernel service.
    """

    active = startup.gate.active_epoch
    if active is None:
        raise RuntimeError("Standard deployment epoch is not active")
    composition = activate_standard_composition()
    authority = AuthorityKernelApplicationService(reader=store, clock=clock)
    controlled_operations = ControlledOperationKernelApplicationService(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
    )
    workspace = StandardLocalWorkspaceRuntimeFactory(
        mount_resolver=selection.workspace_mounts,
        process_isolation=selection.process_isolation,
        authority=authority,
        controlled_operations=controlled_operations,
        workspace_provider_id=selection.workspace_provider_id,
        podman_binary=selection.podman_binary,
    ).build()
    workspace_context = StandardLocalWorkspaceToolContextResolver(store)
    mounted = mount_standard_kernel_workspace_tool_set(
        startup=startup,
        coordinator=workspace.coordinator,
        context_resolver=workspace_context,
    )
    extension_registry = ExtensionBundleRegistry.create(
        composition.plugins,
        activation_epoch=active.sequence,
    )
    admissions = StandardKernelRuntimeAdmissionSource(
        records=store,
        startup=startup,
        declared_catalog=composition.declared_tool_catalog,
        extension_registry=extension_registry,
        capability_registries=StandardPluginFreeCapabilityRegistryResolver(
            extension_registry=extension_registry,
            route_catalog=composition.route_catalog,
        ),
        runtime_adapter_id=selection.runtime_adapter.adapter_id,
        runtime_adapter_contract_digest=(
            selection.runtime_adapter.adapter_contract_digest
        ),
    )
    outcomes = ControlStoreRuntimeOutcomeRepository(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
    )
    runtime_drain = StandardBoundedRuntimeDrainApplication(
        coordination=RuntimeCoordinationKernelApplicationService(
            store=store,
            reader=store,
            clock=clock,
            ids=ids,
        ),
        turns=RuntimeTurnCoordinator(
            adapter=selection.runtime_adapter,
            outcomes=outcomes,
        ),
        outcomes=outcomes,
        records=store,
        admissions=admissions,
        capability_gateway=MountedRuntimeCapabilityGateway(
            scopes=admissions,
            runtimes=mounted.tools,
        ),
        clock=clock,
        ids=ids,
    )
    return StandardOperationalRuntimePorts(
        runtime_drain=runtime_drain,
        workspace=workspace,
        workspace_context=workspace_context,
        revision_backend=selection.revision_backend,
    )


def build_standard_kernel_application_runtime(
    connection: Any,
    *,
    startup: StandardDeploymentStartup,
    clock: ClockPort,
    ids: IdGeneratorPort,
    bootstrap_authority: StandardSessionBootstrapAuthorityPort,
    operational_ports: StandardOperationalRuntimePorts | None = None,
    operational_selection: StandardOperationalAdapterSelection | None = None,
) -> StandardKernelApplicationRuntime:
    """Compose actual Kernel services; perform no workspace or external effect."""

    if (operational_ports is None) == (operational_selection is None):
        raise ValueError(
            "Standard requires exactly one operational Port graph or Adapter selection"
        )
    active_epoch = startup.gate.active_epoch
    if active_epoch is None:
        raise RuntimeError("Standard deployment epoch is not active")
    store = build_standard_kernel_control_store(connection, startup=startup)
    if operational_selection is not None:
        operational_ports = build_standard_operational_runtime_ports(
            store=store,
            startup=startup,
            clock=clock,
            ids=ids,
            selection=operational_selection,
        )
    assert operational_ports is not None
    bootstrap = SessionBootstrapKernelApplicationService(
        store=store,
        clock=clock,
        ids=ids,
        authority_verifier=bootstrap_authority,
    )
    protocols = ProtocolKernelApplicationService(
        store=store,
        clock=clock,
        ids=ids,
    )
    coordination = StandardKernelCoordinationRouteApplication(
        collaboration=CollaborationKernelApplicationService(
            store=store,
            clock=clock,
            ids=ids,
        ),
        tasks=TaskKernelApplicationService(
            store=store,
            reader=store,
            clock=clock,
            ids=ids,
            finish_validators=FinishValidatorRegistry.from_mounted(
                startup.mounted_surfaces.finish_validators
            ),
        ),
        protocols=protocols,
        approvals=ApprovalKernelApplicationService(
            store=store,
            clock=clock,
            ids=ids,
        ),
        authority_leases=AgentAuthorityLeaseKernelApplicationService(
            store=store,
            reader=store,
            clock=clock,
            ids=ids,
        ),
        message_ingress=MessageIngressKernelApplicationService(
            store=store,
            clock=clock,
            ids=ids,
        ),
        ids=ids,
    )
    workspace_runtimes = {
        runtime.tool_name: runtime
        for runtime in build_kernel_workspace_tool_runtimes(
            coordinator=operational_ports.workspace.coordinator,
            context_resolver=operational_ports.workspace_context,
        )
    }
    operational = StandardKernelOperationalRouteApplication(
        runtime_drain=operational_ports.runtime_drain,
        workspace_tools={
            name: workspace_runtimes[name]
            for name in ("workspace.fs.mutate", "workspace.exec")
        },
        publications=PublicationKernelApplicationService(
            store=store,
            reader=store,
            clock=clock,
            ids=ids,
            revision_backend=operational_ports.revision_backend,
        ),
        protocols=protocols,
        ids=ids,
    )
    route_applications = build_standard_coordination_route_applications(coordination)
    operational_routes = build_standard_operational_route_applications(operational)
    overlap = set(route_applications).intersection(operational_routes)
    if overlap:
        raise RuntimeError(
            "Standard Kernel route applications collided: "
            f"{sorted(overlap)!r}"
        )
    route_applications.update(operational_routes)
    gateway = StandardHostKernelCommandGateway(
        deployment_epoch=active_epoch,
        bootstrap_service=bootstrap,
        bootstrap_authority=bootstrap_authority,
        clock=clock,
        ids=ids,
        route_applications=route_applications,
    )
    return StandardKernelApplicationRuntime(
        store=store,
        bootstrap=bootstrap,
        coordination=coordination,
        gateway=gateway,
    )


__all__ = [
    "StandardKernelApplicationRuntime",
    "StandardOperationalAdapterSelection",
    "StandardOperationalRuntimePorts",
    "build_standard_kernel_application_runtime",
    "build_standard_operational_runtime_ports",
]
