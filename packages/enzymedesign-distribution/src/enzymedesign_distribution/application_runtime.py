from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Protocol

from openzyme_contracts import ClockPort
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import WorkspaceRevisionBackendPort
from openzyme_contracts import canonical_sha256_digest
from openzyme_compute import ExtensionStateComputeExecutionRepository
from openzyme_host_api import FileWorkspaceV2HostSurface
from openzyme_host_api import HostSecurityPolicy
from openzyme_host_api import HostV2Dependencies
from openzyme_host_api import create_v2_app
from openzyme_hpc import SQLiteSchedulerOccurrenceLedger
from openzyme_hpc import TargetToolchainInventory
from openzyme_hpc_slurm import SchedulerOccurrenceCredentialResolver
from openzyme_hpc_slurm import SlurmBackend
from openzyme_hpc_slurm import SlurmSchedulerAdapter
from openzyme_hpc_slurm import SlurmSchedulerAdapterFactory
from openzyme_kernel import ActivatedDistributionComposition
from openzyme_kernel import AgentAuthorityLeaseKernelApplicationService
from openzyme_kernel import ApprovalKernelApplicationService
from openzyme_kernel import AuthorityKernelApplicationService
from openzyme_kernel import CapabilityRegistry
from openzyme_kernel import CollaborationKernelApplicationService
from openzyme_kernel import ControlStoreRuntimeOutcomeRepository
from openzyme_kernel import ControlledOperationKernelApplicationService
from openzyme_kernel import ContinuationKernelApplicationService
from openzyme_kernel import DeploymentSurface
from openzyme_kernel import ExtensionBundleRegistry
from openzyme_kernel import ExtensionStateKernelApplicationService
from openzyme_kernel import FinishValidatorRegistry
from openzyme_kernel import KernelContractError
from openzyme_kernel import KernelPublicWorkspaceProjectionService
from openzyme_kernel import MessageIngressKernelApplicationService
from openzyme_kernel import MountedExtensionSurfaces
from openzyme_kernel import MountedRuntimeCapabilityGateway
from openzyme_kernel import MountedRuntimeToolSet
from openzyme_kernel import ProtocolKernelApplicationService
from openzyme_kernel import PublicationKernelApplicationService
from openzyme_kernel import RuntimeCoordinationKernelApplicationService
from openzyme_kernel import RuntimeTurnCoordinator
from openzyme_kernel import SessionBootstrapKernelApplicationService
from openzyme_kernel import SessionCompositionGuard
from openzyme_kernel import TaskKernelApplicationService
from openzyme_kernel import WorkspaceOperationCoordinator
from openzyme_kernel import build_kernel_workspace_tool_runtimes
from openzyme_kernel import mount_runtime_tool_set
from openzyme_process_podman import PodmanWorkspaceFilesystemAdapter
from openzyme_process_podman import PodmanWorkspaceMountResolver
from openzyme_process_podman import PodmanWorkspaceProcessAdapter
from openzyme_runtime_spi import AgentRuntimeAdapter
from openzyme_runtime_spi import ProcessIsolationPort
from openzyme_store_sqlite import SQLiteControlStore
from openzyme_store_sqlite import SQLiteExtensionStateProjectionQuery
from openzyme_store_sqlite import SQLiteExtensionTransactionCoordinator
from openzyme_store_sqlite import SQLiteWorkspaceOperationLedger
from openzyme_store_sqlite import SQLiteRevisionPathVerificationQuery
from openzyme_store_sqlite import kernel_entity_codecs

from .composition import EnzymeDesignDeploymentStartup
from .composition import activate_enzymedesign_composition
from .coordination_routes import EnzymeDesignKernelCoordinationRouteApplication
from .coordination_routes import build_enzymedesign_coordination_route_applications
from .host_gateway import EnzymeDesignHostKernelCommandGateway
from .host_gateway import EnzymeDesignSessionBootstrapAuthorityPort
from .operational_routes import EnzymeDesignKernelOperationalRouteApplication
from .operational_routes import build_enzymedesign_operational_route_applications
from .runtime_admission import EnzymeDesignKernelRuntimeAdmissionSource
from .runtime_drain import EnzymeDesignBoundedRuntimeDrainApplication
from .runtime_mount import EnzymeDesignPluginRuntimeSurfaceSet
from .runtime_mount import mount_enzymedesign_extension_surfaces
from .session_composition_reader import EnzymeDesignSessionCompositionReader
from .workspace_context import EnzymeDesignLocalWorkspaceToolContextResolver


@dataclass(frozen=True, slots=True)
class EnzymeDesignAdapterRuntimeBinding:
    """One exact selected Adapter implementation and its constructed runtime."""

    slot_id: str
    component_id: str
    manifest_digest: str
    runtime: object
    target_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("slot_id", "component_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{field_name} must be one non-empty identifier")
        if not self.manifest_digest.startswith("sha256:"):
            raise ValueError("manifest_digest must be one sha256 digest")
        if self.runtime is None:
            raise ValueError("selected Adapter runtime must be constructed")

    @property
    def binding_key(self) -> tuple[str, str | None]:
        return self.slot_id, self.target_id


@dataclass(frozen=True, slots=True)
class EnzymeDesignAdapterRuntimeSet:
    """Runtime objects for all and only Adapters selected by the Distribution."""

    bindings: tuple[EnzymeDesignAdapterRuntimeBinding, ...]

    def validate(
        self,
        composition: ActivatedDistributionComposition,
    ) -> None:
        observed = {binding.binding_key: binding for binding in self.bindings}
        if len(observed) != len(self.bindings):
            raise KernelContractError(
                "enzymedesign_adapter_runtime_collision",
                "selected Adapter runtime bindings are not unique",
            )
        expected = {
            (item.selection.slot_id, item.selection.target_id): item
            for item in composition.adapters
        }
        if set(observed) != set(expected):
            raise KernelContractError(
                "enzymedesign_adapter_runtime_set_incomplete",
                "constructed Adapter runtimes differ from the exact selected set",
                details={
                    "missing": [
                        _adapter_key(key) for key in sorted(set(expected) - set(observed))
                    ],
                    "unexpected": [
                        _adapter_key(key) for key in sorted(set(observed) - set(expected))
                    ],
                },
            )
        drifted = tuple(
            _adapter_key(key)
            for key, binding in sorted(observed.items())
            if (
                binding.component_id != expected[key].manifest.identity.component_id
                or binding.manifest_digest != expected[key].manifest.manifest_digest
            )
        )
        if drifted:
            raise KernelContractError(
                "enzymedesign_adapter_runtime_identity_drift",
                "constructed Adapter runtime identity differs from its selection",
                details={"bindings": list(drifted)},
            )

    def require_runtime(
        self,
        *,
        slot_id: str,
        target_id: str | None = None,
    ) -> object:
        matches = tuple(
            binding.runtime
            for binding in self.bindings
            if binding.binding_key == (slot_id, target_id)
        )
        if len(matches) != 1:
            raise KernelContractError(
                "enzymedesign_adapter_runtime_unavailable",
                "the exact selected Adapter runtime is unavailable",
                details={"slot_id": slot_id, "target_id": target_id},
            )
        return matches[0]

    @property
    def runtime_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "schema_version": "enzymedesign_adapter_runtime_set@1",
                "bindings": [
                    {
                        "slot_id": item.slot_id,
                        "target_id": item.target_id,
                        "component_id": item.component_id,
                        "manifest_digest": item.manifest_digest,
                    }
                    for item in sorted(
                        self.bindings,
                        key=lambda binding: (
                            binding.slot_id,
                            binding.target_id or "",
                        ),
                    )
                ],
            }
        )


class EnzymeDesignTargetInventoryQueryPort(Protocol):
    """Read one exact adopted target inventory without probing the target."""

    def get(
        self,
        target_id: str,
        generation: int,
    ) -> TargetToolchainInventory | None: ...


class EnzymeDesignPostMountApplicationBinding(Protocol):
    """One exact product application that must bind before writer exposure."""

    binding_id: str

    @property
    def is_bound(self) -> bool: ...

    def bind(
        self,
        *,
        records: SQLiteControlStore,
        capability_registries: EnzymeDesignCapabilityRegistryResolver,
        path_verifications: SQLiteRevisionPathVerificationQuery,
        repository: ExtensionStateComputeExecutionRepository,
        controlled_operations: ControlledOperationKernelApplicationService,
        continuations: ContinuationKernelApplicationService,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class EnzymeDesignOperationalAdapterSelection:
    """Exact effect implementations selected for the product application graph."""

    runtime_adapter: AgentRuntimeAdapter
    workspace_mounts: PodmanWorkspaceMountResolver
    process_isolation: ProcessIsolationPort
    revision_backend: WorkspaceRevisionBackendPort
    slurm_factory: SlurmSchedulerAdapterFactory
    slurm_backend: SlurmBackend
    slurm_credential_resolver: SchedulerOccurrenceCredentialResolver
    workspace_provider_id: str = "openzyme.workspace.git-lfs"
    slurm_target_id: str = "hpc-primary"
    podman_binary: str = "/usr/bin/podman"


@dataclass(frozen=True, slots=True)
class EnzymeDesignLocalWorkspaceRuntimeAdapters:
    coordinator: WorkspaceOperationCoordinator
    filesystem: PodmanWorkspaceFilesystemAdapter
    process: PodmanWorkspaceProcessAdapter


@dataclass(frozen=True, slots=True)
class EnzymeDesignCapabilityRegistryResolver:
    extension_registry: ExtensionBundleRegistry
    composition: ActivatedDistributionComposition
    inventories: EnzymeDesignTargetInventoryQueryPort

    def resolve(
        self,
        binding: SessionCapabilityBindingRevision,
    ) -> CapabilityRegistry:
        resource_facts = []
        for adopted in binding.inventory_bindings:
            inventory = self.inventories.get(
                adopted.target_id,
                adopted.inventory_generation,
            )
            if inventory is None:
                raise KernelContractError(
                    "enzymedesign_adopted_inventory_missing",
                    "Session capability binding names an unavailable target inventory",
                    details={
                        "target_id": adopted.target_id,
                        "inventory_generation": adopted.inventory_generation,
                    },
                )
            if inventory.inventory_digest != adopted.inventory_digest:
                raise KernelContractError(
                    "enzymedesign_adopted_inventory_drift",
                    "Session capability binding inventory digest differs from storage",
                    details={"target_id": adopted.target_id},
                )
            resource_facts.extend(inventory.to_resource_facts())
        return CapabilityRegistry.create(
            extension_bundle=self.extension_registry,
            binding=binding,
            route_catalog=self.composition.route_catalog,
            resource_facts=tuple(resource_facts),
        )


@dataclass(frozen=True, slots=True)
class EnzymeDesignApplicationRuntime:
    """Verified product application graph behind the generic Host Adapter."""

    startup: EnzymeDesignDeploymentStartup
    composition: ActivatedDistributionComposition
    adapter_runtimes: EnzymeDesignAdapterRuntimeSet
    mounted_surfaces: MountedExtensionSurfaces
    store: SQLiteControlStore
    authority: AuthorityKernelApplicationService
    controlled_operations: ControlledOperationKernelApplicationService
    extension_registry: ExtensionBundleRegistry
    capability_registries: EnzymeDesignCapabilityRegistryResolver
    core_projection_provider: KernelPublicWorkspaceProjectionService
    workspace_surface: FileWorkspaceV2HostSurface
    finish_validators: FinishValidatorRegistry
    mounted_tools: MountedRuntimeToolSet
    workspace: EnzymeDesignLocalWorkspaceRuntimeAdapters
    extension_state: ExtensionStateKernelApplicationService
    compute_executions: ExtensionStateComputeExecutionRepository
    continuations: ContinuationKernelApplicationService
    publications: PublicationKernelApplicationService
    workspace_operation_ledger: SQLiteWorkspaceOperationLedger
    scheduler_occurrence_ledger: SQLiteSchedulerOccurrenceLedger
    slurm_scheduler: SlurmSchedulerAdapter
    bootstrap: SessionBootstrapKernelApplicationService
    coordination: EnzymeDesignKernelCoordinationRouteApplication
    gateway: EnzymeDesignHostKernelCommandGateway
    application_binding_ids: tuple[str, ...] = ()

    @property
    def proof_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "schema_version": "enzymedesign_application_runtime@1",
                "startup_proof_digest": self.startup.proof_digest,
                "activation_digest": self.mounted_surfaces.activation_digest,
                "runtime_mount_digest": self.mounted_surfaces.mount_digest,
                "adapter_runtime_digest": self.adapter_runtimes.runtime_digest,
                "extension_registry_digest": self.extension_registry.registry_digest,
                "application_binding_ids": list(self.application_binding_ids),
                "plugin_runtime_mounted": True,
                "writer_enabled": True,
                "fallback_performed": False,
            }
        )


def build_enzymedesign_application_runtime(
    connection: Any,
    *,
    startup: EnzymeDesignDeploymentStartup,
    surfaces: EnzymeDesignPluginRuntimeSurfaceSet,
    adapter_runtimes: EnzymeDesignAdapterRuntimeSet,
    inventories: EnzymeDesignTargetInventoryQueryPort,
    clock: ClockPort,
    ids: IdGeneratorPort,
    bootstrap_authority: EnzymeDesignSessionBootstrapAuthorityPort,
    operational_selection: EnzymeDesignOperationalAdapterSelection,
    application_bindings: tuple[EnzymeDesignPostMountApplicationBinding, ...] = (),
) -> EnzymeDesignApplicationRuntime:
    """Build the writer graph only after proof, Adapter and Plugin closure pass."""

    runtime_authorization = startup.gate.require_active(DeploymentSurface.RUNTIME)
    active = startup.gate.validate_authorization(
        runtime_authorization,
        surface=DeploymentSurface.RUNTIME,
    )
    composition = activate_enzymedesign_composition()
    if (
        active.distribution_id != composition.distribution_id
        or active.distribution_manifest_digest
        != composition.distribution_manifest_digest
        or active.release_identity.extension_bundle_digest
        != composition.plugins.extension_bundle_digest
        or active.release_identity.declared_tool_catalog_digest
        != composition.declared_tool_catalog.catalog_digest
        or active.release_identity.route_catalog_digest
        != composition.route_catalog.catalog_digest
    ):
        raise KernelContractError(
            "enzymedesign_application_startup_drift",
            "application runtime composition differs from the verified startup",
        )
    adapter_runtimes.validate(composition)
    selected_scheduler_factory = adapter_runtimes.require_runtime(
        slot_id="hpc.scheduler",
        target_id=operational_selection.slurm_target_id,
    )
    if selected_scheduler_factory is not operational_selection.slurm_factory:
        raise KernelContractError(
            "enzymedesign_scheduler_factory_selection_drift",
            "the operational Slurm factory differs from the exact selected Adapter runtime",
            details={"target_id": operational_selection.slurm_target_id},
        )
    mounted = mount_enzymedesign_extension_surfaces(
        startup=startup,
        composition=composition,
        surfaces=surfaces,
    )
    extension_registry = ExtensionBundleRegistry.create(
        composition.plugins,
        activation_epoch=active.sequence,
    )
    capability_registries = EnzymeDesignCapabilityRegistryResolver(
        extension_registry=extension_registry,
        composition=composition,
        inventories=inventories,
    )

    # Constructing the selected writer is deliberately the final composition
    # step. Every proof and exact runtime surface check above is read-only.
    store = SQLiteControlStore(connection, codecs=kernel_entity_codecs())
    authority = AuthorityKernelApplicationService(reader=store, clock=clock)
    controlled_operations = ControlledOperationKernelApplicationService(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
    )
    continuations = ContinuationKernelApplicationService(
        store=store,
        clock=clock,
        ids=ids,
    )
    session_compositions = EnzymeDesignSessionCompositionReader(store)
    extension_state = ExtensionStateKernelApplicationService(
        composition=composition,
        mounted=mounted,
        session_repository=session_compositions,
        session_guard=SessionCompositionGuard(startup.gate),
        authority=authority,
        coordinator=SQLiteExtensionTransactionCoordinator(connection),
        clock=clock,
    )
    extension_namespaces = {
        manifest.state_namespace
        for manifest in composition.plugins.contributing_manifests
        if manifest.state_namespace is not None
    }
    compute_executions = ExtensionStateComputeExecutionRepository(
        mutations=extension_state,
        query=SQLiteExtensionStateProjectionQuery.create(
            connection,
            allowed_namespaces=extension_namespaces,
        ),
    )
    binding_ids = tuple(sorted(binding.binding_id for binding in application_bindings))
    if len(binding_ids) != len(set(binding_ids)):
        raise KernelContractError(
            "enzymedesign_application_binding_collision",
            "product application binding identities are not unique",
        )
    for binding in application_bindings:
        if binding.is_bound:
            raise KernelContractError(
                "enzymedesign_application_binding_reused",
                "product application bindings cannot cross application epochs",
                details={"binding_id": binding.binding_id},
            )
        binding.bind(
            records=store,
            capability_registries=capability_registries,
            path_verifications=SQLiteRevisionPathVerificationQuery(connection),
            repository=compute_executions,
            controlled_operations=controlled_operations,
            continuations=continuations,
        )
        if not binding.is_bound:
            raise KernelContractError(
                "enzymedesign_application_binding_incomplete",
                "product application binding did not close before writer enablement",
                details={"binding_id": binding.binding_id},
            )
    workspace_operation_ledger = SQLiteWorkspaceOperationLedger(connection, clock)
    scheduler_occurrence_ledger = SQLiteSchedulerOccurrenceLedger(connection, clock)
    slurm_scheduler = operational_selection.slurm_factory.build(
        backend=operational_selection.slurm_backend,
        credential_resolver=operational_selection.slurm_credential_resolver,
        ledger=scheduler_occurrence_ledger,
    )
    filesystem = PodmanWorkspaceFilesystemAdapter(
        mount_resolver=operational_selection.workspace_mounts,
        operation_ledger=workspace_operation_ledger,
        podman_binary=operational_selection.podman_binary,
    )
    process = PodmanWorkspaceProcessAdapter(
        isolation=operational_selection.process_isolation,
        mount_resolver=operational_selection.workspace_mounts,
        operation_ledger=workspace_operation_ledger,
    )
    workspace = EnzymeDesignLocalWorkspaceRuntimeAdapters(
        coordinator=WorkspaceOperationCoordinator(
            authority=authority,
            controlled_operations=controlled_operations,
            observation_ports={
                operational_selection.workspace_provider_id: filesystem
            },
            filesystem_ports={
                operational_selection.workspace_provider_id: filesystem
            },
            process_ports={operational_selection.workspace_provider_id: process},
        ),
        filesystem=filesystem,
        process=process,
    )
    workspace_context = EnzymeDesignLocalWorkspaceToolContextResolver(store)
    kernel_workspace_runtimes = build_kernel_workspace_tool_runtimes(
        coordinator=workspace.coordinator,
        context_resolver=workspace_context,
    )
    mounted_tools = mount_runtime_tool_set(
        gate=startup.gate,
        catalog=composition.declared_tool_catalog,
        kernel_runtimes=kernel_workspace_runtimes,
        extension_surfaces=mounted,
    )
    admissions = EnzymeDesignKernelRuntimeAdmissionSource(
        records=store,
        startup=startup,
        declared_catalog=composition.declared_tool_catalog,
        extension_registry=extension_registry,
        capability_registries=capability_registries,
        runtime_adapter_id=operational_selection.runtime_adapter.adapter_id,
        runtime_adapter_contract_digest=(
            operational_selection.runtime_adapter.adapter_contract_digest
        ),
    )
    outcomes = ControlStoreRuntimeOutcomeRepository(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
    )
    runtime_drain = EnzymeDesignBoundedRuntimeDrainApplication(
        coordination=RuntimeCoordinationKernelApplicationService(
            store=store,
            reader=store,
            clock=clock,
            ids=ids,
        ),
        turns=RuntimeTurnCoordinator(
            adapter=operational_selection.runtime_adapter,
            outcomes=outcomes,
        ),
        outcomes=outcomes,
        records=store,
        admissions=admissions,
        capability_gateway=MountedRuntimeCapabilityGateway(
            scopes=admissions,
            runtimes=mounted_tools.tools,
        ),
        clock=clock,
        ids=ids,
    )
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
    finish_validators = FinishValidatorRegistry.from_mounted(
        mounted.finish_validators
    )
    coordination = EnzymeDesignKernelCoordinationRouteApplication(
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
            finish_validators=finish_validators,
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
        runtime.tool_name: runtime for runtime in kernel_workspace_runtimes
    }
    publications = PublicationKernelApplicationService(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
        revision_backend=operational_selection.revision_backend,
    )
    operational = EnzymeDesignKernelOperationalRouteApplication(
        runtime_drain=runtime_drain,
        workspace_tools={
            name: workspace_runtimes[name]
            for name in ("workspace.fs.mutate", "workspace.exec")
        },
        publications=publications,
        protocols=protocols,
        ids=ids,
    )
    route_applications = build_enzymedesign_coordination_route_applications(
        coordination
    )
    operational_routes = build_enzymedesign_operational_route_applications(
        operational
    )
    overlap = set(route_applications).intersection(operational_routes)
    if overlap:
        raise KernelContractError(
            "enzymedesign_kernel_route_collision",
            "coordination and operational Kernel routes overlap",
            details={"route_ids": sorted(overlap)},
        )
    route_applications.update(operational_routes)
    gateway = EnzymeDesignHostKernelCommandGateway(
        deployment_epoch=active,
        bootstrap_service=bootstrap,
        bootstrap_authority=bootstrap_authority,
        clock=clock,
        ids=ids,
        route_applications=route_applications,
    )
    core_provider = KernelPublicWorkspaceProjectionService(
        reader=store,
        declared_catalog=composition.declared_tool_catalog,
        capability_registries=capability_registries,
        extension_bundle_digest=active.release_identity.extension_bundle_digest,
        clock=clock,
    )
    workspace_surface = FileWorkspaceV2HostSurface.from_mounted_surfaces(
        release=active.release_identity,
        core_provider=core_provider,
        mounted_surfaces=mounted,
    )
    return EnzymeDesignApplicationRuntime(
        startup=startup,
        composition=composition,
        adapter_runtimes=adapter_runtimes,
        mounted_surfaces=mounted,
        store=store,
        authority=authority,
        controlled_operations=controlled_operations,
        extension_registry=extension_registry,
        capability_registries=capability_registries,
        core_projection_provider=core_provider,
        workspace_surface=workspace_surface,
        finish_validators=finish_validators,
        mounted_tools=mounted_tools,
        workspace=workspace,
        extension_state=extension_state,
        compute_executions=compute_executions,
        continuations=continuations,
        publications=publications,
        workspace_operation_ledger=workspace_operation_ledger,
        scheduler_occurrence_ledger=scheduler_occurrence_ledger,
        slurm_scheduler=slurm_scheduler,
        bootstrap=bootstrap,
        coordination=coordination,
        gateway=gateway,
        application_binding_ids=binding_ids,
    )


def build_enzymedesign_v2_host_app(
    *,
    runtime: EnzymeDesignApplicationRuntime,
    security_policy: HostSecurityPolicy,
):  # noqa: ANN201 - FastAPI remains owned by the generic delivery Adapter
    """Mount one verified EnzymeDesign runtime behind the generic @2 Host."""

    app = create_v2_app(
        HostV2Dependencies(
            security_policy=security_policy,
            workspace_surface=runtime.workspace_surface,
            command_gateway=runtime.gateway,
            http_routes=tuple(
                contribution
                for _, contribution in runtime.mounted_surfaces.http_routes
            ),
        )
    )
    app.state.enzymedesign_runtime = runtime
    return app


def _adapter_key(key: tuple[str, str | None]) -> str:
    slot_id, target_id = key
    return slot_id if target_id is None else f"{slot_id}:{target_id}"


__all__ = [
    "EnzymeDesignAdapterRuntimeBinding",
    "EnzymeDesignAdapterRuntimeSet",
    "EnzymeDesignApplicationRuntime",
    "EnzymeDesignCapabilityRegistryResolver",
    "EnzymeDesignLocalWorkspaceRuntimeAdapters",
    "EnzymeDesignOperationalAdapterSelection",
    "EnzymeDesignTargetInventoryQueryPort",
    "build_enzymedesign_application_runtime",
    "build_enzymedesign_v2_host_app",
]
