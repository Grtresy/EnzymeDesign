from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
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
from openzyme_kernel import RuntimeContinuationDeliveryKernelApplicationService
from openzyme_kernel import RuntimeContinuationDeliveryWorker
from openzyme_kernel import RuntimeTurnCoordinator
from openzyme_kernel import SessionBootstrapKernelApplicationService
from openzyme_kernel import TaskKernelApplicationService
from openzyme_kernel import WorkspaceProvisioningKernelApplicationService
from openzyme_kernel import WorkspaceProvisioningWorker
from openzyme_kernel import build_kernel_workspace_tool_runtimes
from openzyme_kernel.collaboration_tools import CollaborationToolApplications
from openzyme_kernel.runtime_command_application import (
    RuntimeCommandKernelApplicationService,
)
from openzyme_kernel.tool_exposure import ControlStoreCommandToolExpansionStore
from openzyme_process_podman import PodmanWorkspaceMountResolver
from openzyme_extension_spi import WorkspaceProvisionerPort
from openzyme_runtime_spi import AgentRuntimeAdapter
from openzyme_runtime_spi import ProcessIsolationPort
from openzyme_store_sqlite import SQLiteControlStore
from openzyme_store_sqlite import SQLiteWorkspaceOperationLedger

from .composition import StandardDeploymentStartup
from .composition import StandardPluginFreeCapabilityRegistryResolver
from .composition import activate_standard_composition
from .composition import build_standard_kernel_control_store
from .composition import mount_standard_kernel_workspace_tool_set
from .coordination_routes import StandardKernelCoordinationRouteApplication
from .coordination_routes import build_standard_coordination_route_applications
from .host_gateway import StandardHostKernelCommandGateway
from .host_gateway import StandardSessionBootstrapAuthorityPort
from .host_gateway import StandardWorkspaceBootstrapDefaults
from .operational_routes import StandardKernelOperationalRouteApplication
from .operational_routes import StandardRuntimeDrainApplication
from .operational_routes import build_standard_operational_route_applications
from .factories import StandardLocalWorkspaceRuntimeAdapters
from .factories import StandardLocalWorkspaceRuntimeFactory
from .runtime_admission import StandardKernelRuntimeAdmissionSource
from .runtime_drain import StandardBoundedRuntimeDrainApplication
from .runtime_command_worker import StandardRuntimeCommandContextFactory
from .runtime_command_worker import StandardRuntimeCommandExecutor
from .runtime_command_worker import StandardRuntimeCommandWorker
from .workflow_registry import StandardExplicitEmptyWorkflowRegistry
from .workspace_context import StandardLocalWorkspaceToolContextResolver
from .workspace_provisioning_worker import StandardWorkspaceProvisioningWorker


@dataclass(frozen=True, slots=True)
class StandardKernelApplicationRuntime:
    """Real Plugin-free Standard Kernel application graph behind generic Host."""

    store: SQLiteControlStore
    bootstrap: SessionBootstrapKernelApplicationService
    coordination: StandardKernelCoordinationRouteApplication
    provisioning_worker: StandardWorkspaceProvisioningWorker
    runtime_worker: StandardRuntimeCommandWorker
    gateway: StandardHostKernelCommandGateway


@dataclass(frozen=True, slots=True)
class StandardOperationalRuntimePorts:
    """Exact selected Adapter applications needed by effectful Standard routes."""

    runtime_drain: StandardRuntimeDrainApplication
    runtime_worker: StandardRuntimeCommandWorker
    provisioning_worker: StandardWorkspaceProvisioningWorker
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
    workspace_provisioner: WorkspaceProvisionerPort
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
    operation_ledger = SQLiteWorkspaceOperationLedger(store.connection, clock)
    workspace = StandardLocalWorkspaceRuntimeFactory(
        mount_resolver=selection.workspace_mounts,
        process_isolation=selection.process_isolation,
        authority=authority,
        controlled_operations=controlled_operations,
        operation_ledger=operation_ledger,
        workspace_provider_id=selection.workspace_provider_id,
        podman_binary=selection.podman_binary,
    ).build()
    workspace_context = StandardLocalWorkspaceToolContextResolver(store)
    extension_registry = ExtensionBundleRegistry.create(
        composition.plugins,
        activation_epoch=active.sequence,
    )
    workflow_registry = StandardExplicitEmptyWorkflowRegistry(clock=clock)
    admissions = StandardKernelRuntimeAdmissionSource(
        records=store,
        startup=startup,
        declared_catalog=composition.declared_tool_catalog,
        extension_registry=extension_registry,
        capability_registries=StandardPluginFreeCapabilityRegistryResolver(
            extension_registry=extension_registry,
            route_catalog=composition.route_catalog,
        ),
        workflow_registry_snapshot_digest=(workflow_registry.registry_snapshot_digest),
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
    collaboration = CollaborationKernelApplicationService(
        store=store,
        clock=clock,
        ids=ids,
    )
    tasks = TaskKernelApplicationService(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
        finish_validators=FinishValidatorRegistry.from_mounted(
            startup.mounted_surfaces.finish_validators
        ),
    )
    protocols = ProtocolKernelApplicationService(
        store=store,
        clock=clock,
        ids=ids,
    )
    approvals = ApprovalKernelApplicationService(
        store=store,
        clock=clock,
        ids=ids,
    )
    mounted = mount_standard_kernel_workspace_tool_set(
        startup=startup,
        coordinator=workspace.coordinator,
        context_resolver=workspace_context,
        collaboration_applications=CollaborationToolApplications(
            world=admissions,
            collaboration=collaboration,
            tasks=tasks,
            protocol=protocols,
            approvals=approvals,
        ),
        collaboration_context_resolver=admissions,
    )
    capability_gateway = MountedRuntimeCapabilityGateway(
        scopes=admissions,
        runtimes=mounted.tools,
        expansions=ControlStoreCommandToolExpansionStore(
            store=store,
            reader=store,
            clock=clock,
            ids=ids,
        ),
        clock=clock,
    )
    commands = RuntimeCommandKernelApplicationService(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
    )
    contexts = StandardRuntimeCommandContextFactory(records=store, ids=ids)
    runtime_worker = StandardRuntimeCommandWorker(
        application=commands,
        records=store,
        executor=StandardRuntimeCommandExecutor(
            coordination=RuntimeCoordinationKernelApplicationService(
                store=store,
                reader=store,
                clock=clock,
                ids=ids,
            ),
            continuations=RuntimeContinuationDeliveryWorker(
                application=(
                    RuntimeContinuationDeliveryKernelApplicationService(
                        store=store,
                        clock=clock,
                        ids=ids,
                    )
                ),
                records=store,
                ids=ids,
            ),
            turns=RuntimeTurnCoordinator(
                adapter=selection.runtime_adapter,
                outcomes=outcomes,
            ),
            outcomes=outcomes,
            records=store,
            admissions=admissions,
            capability_gateway=capability_gateway,
            contexts=contexts,
            clock=clock,
            ids=ids,
        ),
        contexts=contexts,
        clock=clock,
    )
    runtime_drain = StandardBoundedRuntimeDrainApplication(
        commands=commands,
        ids=ids,
    )
    return StandardOperationalRuntimePorts(
        runtime_drain=runtime_drain,
        runtime_worker=runtime_worker,
        provisioning_worker=StandardWorkspaceProvisioningWorker(
            worker=WorkspaceProvisioningWorker(
                application=WorkspaceProvisioningKernelApplicationService(
                    store=store,
                    reader=store,
                    clock=clock,
                    ids=ids,
                ),
                reader=store,
                ports={
                    selection.workspace_provisioner.adapter_binding_digest: (
                        selection.workspace_provisioner
                    )
                },
                clock=clock,
                ids=ids,
            ),
            records=store,
            clock=clock,
            ids=ids,
        ),
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
    bootstrap_defaults_by_project: Mapping[
        str,
        StandardWorkspaceBootstrapDefaults,
    ],
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
            reader=store,
            clock=clock,
            ids=ids,
            workflow_registry=StandardExplicitEmptyWorkflowRegistry(clock=clock),
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
            f"Standard Kernel route applications collided: {sorted(overlap)!r}"
        )
    route_applications.update(operational_routes)
    gateway = StandardHostKernelCommandGateway(
        deployment_epoch=active_epoch,
        bootstrap_service=bootstrap,
        bootstrap_authority=bootstrap_authority,
        clock=clock,
        ids=ids,
        route_applications=route_applications,
        bootstrap_defaults_by_project=bootstrap_defaults_by_project,
        workspace_provisioning=operational_ports.provisioning_worker,
    )
    return StandardKernelApplicationRuntime(
        store=store,
        bootstrap=bootstrap,
        coordination=coordination,
        provisioning_worker=operational_ports.provisioning_worker,
        runtime_worker=operational_ports.runtime_worker,
        gateway=gateway,
    )


__all__ = [
    "StandardKernelApplicationRuntime",
    "StandardOperationalAdapterSelection",
    "StandardOperationalRuntimePorts",
    "build_standard_kernel_application_runtime",
    "build_standard_operational_runtime_ports",
]
