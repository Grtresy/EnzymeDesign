from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from collections.abc import Mapping
from typing import Any
from typing import Protocol

from openzyme_contracts import ClockPort
from openzyme_contracts import DeploymentActivationEpoch
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import WorkspaceRevisionBackendPort
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
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
from openzyme_kernel import CollaborationToolApplications
from openzyme_kernel import ControlStoreRuntimeOutcomeRepository
from openzyme_kernel import ControlledOperationKernelApplicationService
from openzyme_kernel import ContinuationKernelApplicationService
from openzyme_kernel import DeploymentSurface
from openzyme_kernel import ExtensionBundleRegistry
from openzyme_kernel import ExtensionStateKernelApplicationService
from openzyme_kernel import FinishValidatorRegistry
from openzyme_kernel import KernelContractError
from openzyme_kernel import ControlStoreCommandToolExpansionStore
from openzyme_kernel import KernelCapabilitiesInspectRuntime
from openzyme_kernel import KernelPublicWorkspaceProjectionService
from openzyme_kernel import MessageIngressKernelApplicationService
from openzyme_kernel import MountedExtensionSurfaces
from openzyme_kernel import MountedRuntimeCapabilityGateway
from openzyme_kernel import MountedRuntimeToolSet
from openzyme_kernel import ProtocolKernelApplicationService
from openzyme_kernel import PublicationKernelApplicationService
from openzyme_kernel import RuntimeCoordinationKernelApplicationService
from openzyme_kernel import RuntimeContinuationDeliveryKernelApplicationService
from openzyme_kernel import RuntimeContinuationDeliveryWorker
from openzyme_kernel import RuntimeTurnCoordinator
from openzyme_kernel import SessionBootstrapKernelApplicationService
from openzyme_kernel import SessionCompositionGuard
from openzyme_kernel import TaskKernelApplicationService
from openzyme_kernel import WorkspaceOperationCoordinator
from openzyme_kernel import WorkspaceProvisioningKernelApplicationService
from openzyme_kernel import WorkspaceProvisioningWorker
from openzyme_kernel import build_kernel_workspace_tool_runtimes
from openzyme_kernel import build_kernel_collaboration_tool_runtimes
from openzyme_kernel import kernel_collaboration_tool_specs
from openzyme_kernel import mount_runtime_tool_set
from openzyme_kernel.runtime_command_application import (
    RuntimeCommandKernelApplicationService,
)
from openzyme_process_podman import PodmanWorkspaceFilesystemAdapter
from openzyme_process_podman import PodmanWorkspaceMountResolver
from openzyme_process_podman import PodmanWorkspaceProcessAdapter
from openzyme_runtime_spi import AgentRuntimeAdapter
from openzyme_runtime_spi import ProcessIsolationPort
from openzyme_extension_spi import WorkspaceProvisionerPort
from openzyme_extension_spi import validate_workspace_provisioner_identity
from openzyme_store_sqlite import SQLiteControlStore
from openzyme_store_sqlite import SQLiteExtensionStateProjectionQuery
from openzyme_store_sqlite import SQLiteExtensionTransactionCoordinator
from openzyme_store_sqlite import SQLiteWorkspaceOperationLedger
from openzyme_store_sqlite import SQLiteRevisionPathVerificationQuery
from openzyme_store_sqlite import kernel_entity_codecs

from .composition import EnzymeDesignDeploymentStartup
from .composition import activate_enzymedesign_composition
from .collaboration_runtime import EnzymeDesignCollaborationToolContextResolver
from .collaboration_runtime import EnzymeDesignWorldInspectionApplication
from .coordination_routes import EnzymeDesignKernelCoordinationRouteApplication
from .coordination_routes import build_enzymedesign_coordination_route_applications
from .host_gateway import EnzymeDesignHostKernelCommandGateway
from .host_gateway import EnzymeDesignSessionBootstrapAuthorityPort
from .host_gateway import EnzymeDesignWorkspaceBootstrapDefaults
from .operational_routes import EnzymeDesignKernelOperationalRouteApplication
from .operational_routes import build_enzymedesign_operational_route_applications
from .qualification_admission import EnzymeDesignExternalQualificationAdmission
from .runtime_admission import EnzymeDesignKernelRuntimeAdmissionSource
from .runtime_drain import EnzymeDesignBoundedRuntimeDrainApplication
from .runtime_command import EnzymeDesignRuntimeCommandContextResolver
from .runtime_command import EnzymeDesignRuntimeCommandWorker
from .runtime_command import EnzymeDesignRuntimeDrainAdmissionApplication
from .runtime_mount import EnzymeDesignPluginRuntimeSurfaceSet
from .runtime_mount import mount_enzymedesign_extension_surfaces
from .session_composition_reader import EnzymeDesignSessionCompositionReader
from .workspace_context import EnzymeDesignLocalWorkspaceToolContextResolver
from .workspace_provisioning import EnzymeDesignWorkspaceProvisioningRunner
from .workspace_provisioning import (
    EnzymeDesignWorkspaceProvisioningLifecycleWorker,
)
from .workspace_provisioning import (
    EnzymeDesignWorkspaceProvisioningWorkerAuthority,
)
from .role_policies import enzymedesign_subject_policy_decisions_by_role
from .role_policies import enzymedesign_tool_exposure_policies
from .role_policies import ENZYMEDESIGN_RESIDENT_ROLES
from .workflow_registry import EnzymeDesignExactWorkflowRegistry
from .workflow_registry import ENZYMEDESIGN_WORKFLOW_REGISTRY_ID
from .workflow_registry import ENZYMEDESIGN_WORKFLOW_REGISTRY_SNAPSHOT_DIGEST


@dataclass(frozen=True, slots=True)
class EnzymeDesignAdapterRuntimeBinding:
    """One exact selected Adapter implementation and its constructed runtime."""

    slot_id: str
    component_id: str
    manifest_digest: str
    contract_digest: str
    build_digest: str
    runtime: object
    target_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("slot_id", "component_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{field_name} must be one non-empty identifier")
        for field_name in ("manifest_digest", "contract_digest", "build_digest"):
            if not getattr(self, field_name).startswith("sha256:"):
                raise ValueError(f"{field_name} must be one sha256 digest")
        if self.runtime is None:
            raise ValueError("selected Adapter runtime must be constructed")

    @property
    def binding_key(self) -> tuple[str, str | None]:
        return self.slot_id, self.target_id

    @property
    def binding_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "schema_version": "enzymedesign_adapter_runtime_binding@1",
                "slot_id": self.slot_id,
                "target_id": self.target_id,
                "component_id": self.component_id,
                "manifest_digest": self.manifest_digest,
                "contract_digest": self.contract_digest,
                "build_digest": self.build_digest,
            }
        )


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
                        _adapter_key(key)
                        for key in sorted(set(expected) - set(observed))
                    ],
                    "unexpected": [
                        _adapter_key(key)
                        for key in sorted(set(observed) - set(expected))
                    ],
                },
            )
        drifted = tuple(
            _adapter_key(key)
            for key, binding in sorted(observed.items())
            if (
                binding.component_id != expected[key].manifest.identity.component_id
                or binding.manifest_digest != expected[key].manifest.manifest_digest
                or binding.contract_digest
                != expected[key].manifest.identity.contract_digest
                or binding.build_digest != expected[key].manifest.identity.build_digest
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

    def derive_operational_selection(self) -> EnzymeDesignOperationalAdapterSelection:
        """Derive all effectful objects from the one validated runtime graph."""

        runtime_adapter = self.require_runtime(slot_id="agent.turn")
        runtime_binding = self.require_binding(slot_id="agent.turn")
        if (
            getattr(runtime_adapter, "adapter_id", None) != runtime_binding.component_id
            or getattr(runtime_adapter, "adapter_contract_digest", None)
            != runtime_binding.contract_digest
        ):
            raise KernelContractError(
                "enzymedesign_runtime_adapter_identity_drift",
                "the selected agent runtime does not expose its exact component contract",
            )
        podman = self.require_runtime(slot_id="process.isolation")
        if not isinstance(podman, EnzymeDesignPodmanOperationalRuntime):
            raise KernelContractError(
                "enzymedesign_process_runtime_shape_invalid",
                "the selected process Adapter lacks its exact operational graph",
            )
        slurm_binding = self.require_binding(
            slot_id="hpc.scheduler", target_id="hpc-primary"
        )
        slurm = slurm_binding.runtime
        if not isinstance(slurm, EnzymeDesignSlurmOperationalRuntime):
            raise KernelContractError(
                "enzymedesign_scheduler_runtime_shape_invalid",
                "the selected scheduler Adapter lacks its exact operational graph",
            )
        workspace_binding = self.require_binding(slot_id="workspace.backend")
        workspace_runtime = workspace_binding.runtime
        if not isinstance(
            workspace_runtime,
            EnzymeDesignWorkspaceOperationalRuntime,
        ):
            raise KernelContractError(
                "enzymedesign_workspace_runtime_shape_invalid",
                "the selected workspace Adapter lacks revision and provisioning mechanisms",
            )
        if (
            workspace_runtime.provisioner.provider_id != workspace_binding.component_id
            or workspace_runtime.provisioner.adapter_binding_digest
            != workspace_binding.binding_digest
        ):
            raise KernelContractError(
                "enzymedesign_workspace_provisioner_identity_drift",
                "the workspace provisioner differs from its selected Adapter binding",
            )
        return EnzymeDesignOperationalAdapterSelection(
            runtime_adapter=runtime_adapter,  # type: ignore[arg-type]
            workspace_mounts=podman.workspace_mounts,
            process_isolation=podman.process_isolation,
            revision_backend=workspace_runtime.revision_backend,
            workspace_provisioner=workspace_runtime.provisioner,
            workspace_adapter_binding_digest=workspace_binding.binding_digest,
            slurm_factory=slurm.factory,
            slurm_backend=slurm.backend,
            slurm_credential_resolver=slurm.credential_resolver,
            workspace_provider_id=workspace_binding.component_id,
            slurm_target_id=slurm_binding.target_id or "",
            podman_binary=podman.podman_binary,
        )

    def require_binding(
        self,
        *,
        slot_id: str,
        target_id: str | None = None,
    ) -> EnzymeDesignAdapterRuntimeBinding:
        matches = tuple(
            binding
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
                        "contract_digest": item.contract_digest,
                        "build_digest": item.build_digest,
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


@dataclass(frozen=True, slots=True)
class EnzymeDesignWorkspaceOperationalRuntime:
    """Selected workspace Adapter mechanisms behind one manifest binding."""

    revision_backend: WorkspaceRevisionBackendPort
    provisioner: WorkspaceProvisionerPort

    def __post_init__(self) -> None:
        validate_workspace_provisioner_identity(self.provisioner)


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
    """Derived effect graph; never accepted independently by composition root."""

    runtime_adapter: AgentRuntimeAdapter
    workspace_mounts: PodmanWorkspaceMountResolver
    process_isolation: ProcessIsolationPort
    revision_backend: WorkspaceRevisionBackendPort
    workspace_provisioner: WorkspaceProvisionerPort
    workspace_adapter_binding_digest: str
    slurm_factory: SlurmSchedulerAdapterFactory
    slurm_backend: SlurmBackend
    slurm_credential_resolver: SchedulerOccurrenceCredentialResolver
    workspace_provider_id: str = "openzyme.workspace.git-lfs"
    slurm_target_id: str = "hpc-primary"
    podman_binary: str = "/usr/bin/podman"
    external_qualification_admission: (
        EnzymeDesignExternalQualificationAdmission | None
    ) = None

    def __post_init__(self) -> None:
        validate_workspace_provisioner_identity(self.workspace_provisioner)
        if (
            self.workspace_provisioner.adapter_binding_digest
            != self.workspace_adapter_binding_digest
        ):
            raise ValueError(
                "workspace provisioner differs from selected Adapter binding digest"
            )

    def require_external_qualification(
        self,
        *,
        unit_digest: str,
        route_id: str,
        subject_id: str,
    ) -> object:
        if self.external_qualification_admission is None:
            raise KernelContractError(
                "blocked_qualification",
                "the operational runtime has no adopted external qualification set",
                details={
                    "unit_digest": unit_digest,
                    "route_id": route_id,
                    "subject_id": subject_id,
                    "fallback_performed": False,
                },
            )
        try:
            return self.external_qualification_admission.admit_occurrence(
                unit_digest=unit_digest,
                route_id=route_id,
                subject_id=subject_id,
            )
        except ExternalQualificationError as exc:
            raise KernelContractError(
                "blocked_qualification",
                str(exc),
                details={
                    "unit_digest": unit_digest,
                    "route_id": route_id,
                    "subject_id": subject_id,
                    "fallback_performed": False,
                },
            ) from exc


@dataclass(frozen=True, slots=True)
class EnzymeDesignPodmanOperationalRuntime:
    workspace_mounts: PodmanWorkspaceMountResolver
    process_isolation: ProcessIsolationPort
    podman_binary: str = "/usr/bin/podman"


@dataclass(frozen=True, slots=True)
class EnzymeDesignSlurmOperationalRuntime:
    factory: SlurmSchedulerAdapterFactory
    backend: SlurmBackend
    credential_resolver: SchedulerOccurrenceCredentialResolver


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
    workspace_provisioning: WorkspaceProvisioningKernelApplicationService
    workspace_provisioning_worker: WorkspaceProvisioningWorker
    workspace_provisioning_runner: EnzymeDesignWorkspaceProvisioningRunner
    workspace_provisioning_lifecycle_worker: (
        EnzymeDesignWorkspaceProvisioningLifecycleWorker
    )
    extension_state: ExtensionStateKernelApplicationService
    compute_executions: ExtensionStateComputeExecutionRepository
    continuations: ContinuationKernelApplicationService
    publications: PublicationKernelApplicationService
    workspace_operation_ledger: SQLiteWorkspaceOperationLedger
    scheduler_occurrence_ledger: SQLiteSchedulerOccurrenceLedger
    slurm_scheduler: SlurmSchedulerAdapter
    bootstrap: SessionBootstrapKernelApplicationService
    coordination: EnzymeDesignKernelCoordinationRouteApplication
    runtime_commands: RuntimeCommandKernelApplicationService
    runtime_worker: EnzymeDesignRuntimeCommandWorker
    gateway: EnzymeDesignHostKernelCommandGateway
    workflow_registry: EnzymeDesignExactWorkflowRegistry
    runtime_admission: EnzymeDesignKernelRuntimeAdmissionSource
    active_epoch_id: str
    active_release_digest: str
    activation_digest: str
    extension_bundle_digest: str
    declared_tool_catalog_digest: str
    adapter_runtime_digest: str
    workflow_registry_snapshot_digest: str
    role_policy_digest: str
    runtime_admission_identity_digest: str
    workspace_adapter_binding_digest: str
    application_binding_ids: tuple[str, ...] = ()
    external_qualification_admission: (
        EnzymeDesignExternalQualificationAdmission | None
    ) = None

    def __post_init__(self) -> None:
        self.validate_identity()

    def validate_identity(self) -> None:
        """Revalidate every frozen product identity against the runtime graph."""

        self.adapter_runtimes.validate(self.composition)
        active = _validate_enzymedesign_application_composition(
            startup=self.startup,
            composition=self.composition,
        )
        if (
            type(self.workflow_registry) is not EnzymeDesignExactWorkflowRegistry
            or type(self.runtime_admission)
            is not EnzymeDesignKernelRuntimeAdmissionSource
            or self.coordination.message_ingress.workflow_registry
            is not self.workflow_registry
            or self.runtime_worker.executor.admissions is not self.runtime_admission
            or self.runtime_admission.startup is not self.startup
            or self.runtime_admission.declared_catalog
            is not self.composition.declared_tool_catalog
            or self.runtime_admission.extension_registry is not self.extension_registry
        ):
            raise KernelContractError(
                "enzymedesign_application_runtime_identity_drift",
                "application runtime execution objects differ from its identity proof",
                details={"mutation_applied": False, "fallback_performed": False},
            )
        for field_name in (
            "active_release_digest",
            "activation_digest",
            "extension_bundle_digest",
            "declared_tool_catalog_digest",
            "adapter_runtime_digest",
            "workflow_registry_snapshot_digest",
            "role_policy_digest",
            "runtime_admission_identity_digest",
            "workspace_adapter_binding_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        workflow_registry_identity = (
            self.workflow_registry.distribution_id,
            self.workflow_registry.registry_id,
            self.workflow_registry.registry_snapshot_digest,
        )
        if workflow_registry_identity != (
            self.composition.distribution_id,
            ENZYMEDESIGN_WORKFLOW_REGISTRY_ID,
            ENZYMEDESIGN_WORKFLOW_REGISTRY_SNAPSHOT_DIGEST,
        ):
            raise KernelContractError(
                "enzymedesign_application_runtime_identity_drift",
                "application runtime workflow registry identity drifted",
                details={"mutation_applied": False, "fallback_performed": False},
            )
        expected_role_policy_digest = _enzymedesign_role_policy_digest(
            subject_policies=(self.runtime_admission.subject_policy_decisions_by_role),
            exposure_policies=self.runtime_admission.tool_exposure_policies,
        )
        expected_admission_identity_digest = (
            _enzymedesign_runtime_admission_identity_digest(
                admission=self.runtime_admission,
                role_policy_digest=expected_role_policy_digest,
            )
        )
        expected_workspace_binding_digest = self.adapter_runtimes.derive_operational_selection().workspace_adapter_binding_digest
        expected = (
            active.epoch_id,
            active.release_identity.release_digest,
            active.activation_digest,
            active.activation_digest,
            active.release_identity.extension_bundle_digest,
            active.release_identity.declared_tool_catalog_digest,
            self.adapter_runtimes.runtime_digest,
            ENZYMEDESIGN_WORKFLOW_REGISTRY_SNAPSHOT_DIGEST,
            expected_role_policy_digest,
            expected_admission_identity_digest,
            expected_workspace_binding_digest,
        )
        observed = (
            self.active_epoch_id,
            self.active_release_digest,
            self.activation_digest,
            self.mounted_surfaces.activation_digest,
            self.extension_bundle_digest,
            self.declared_tool_catalog_digest,
            self.adapter_runtime_digest,
            self.workflow_registry_snapshot_digest,
            self.role_policy_digest,
            self.runtime_admission_identity_digest,
            self.workspace_adapter_binding_digest,
        )
        if observed != expected:
            raise KernelContractError(
                "enzymedesign_application_runtime_identity_drift",
                "application runtime frozen identities differ from its active graph",
                details={"mutation_applied": False, "fallback_performed": False},
            )

    @property
    def proof_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "schema_version": "enzymedesign_application_runtime@2",
                "startup_proof_digest": self.startup.proof_digest,
                "active_epoch_id": self.active_epoch_id,
                "active_release_digest": self.active_release_digest,
                "activation_digest": self.activation_digest,
                "extension_bundle_digest": self.extension_bundle_digest,
                "declared_tool_catalog_digest": self.declared_tool_catalog_digest,
                "runtime_mount_digest": self.mounted_surfaces.mount_digest,
                "adapter_runtime_digest": self.adapter_runtime_digest,
                "extension_registry_digest": self.extension_registry.registry_digest,
                "workflow_registry_snapshot_digest": (
                    self.workflow_registry_snapshot_digest
                ),
                "role_policy_digest": self.role_policy_digest,
                "runtime_admission_identity_digest": (
                    self.runtime_admission_identity_digest
                ),
                "workspace_adapter_binding_digest": (
                    self.workspace_adapter_binding_digest
                ),
                "application_binding_ids": list(self.application_binding_ids),
                "external_qualification_admission_digest": (
                    None
                    if self.external_qualification_admission is None
                    else self.external_qualification_admission.admission_digest
                ),
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
    bootstrap_defaults_by_project: Mapping[
        str,
        EnzymeDesignWorkspaceBootstrapDefaults,
    ],
    workspace_worker_authority: EnzymeDesignWorkspaceProvisioningWorkerAuthority,
    external_qualification_admission: (
        EnzymeDesignExternalQualificationAdmission | None
    ) = None,
    application_bindings: tuple[EnzymeDesignPostMountApplicationBinding, ...] = (),
) -> EnzymeDesignApplicationRuntime:
    """Build the writer graph only after proof, Adapter and Plugin closure pass."""

    composition = activate_enzymedesign_composition()
    active = _validate_enzymedesign_application_composition(
        startup=startup,
        composition=composition,
        official_composition=composition,
    )
    adapter_runtimes.validate(composition)
    operational_selection = adapter_runtimes.derive_operational_selection()
    if not bootstrap_defaults_by_project:
        raise KernelContractError(
            "enzymedesign_workspace_bootstrap_defaults_missing",
            "application runtime requires explicit project workspace defaults",
        )
    drifted_defaults = tuple(
        sorted(
            project_id
            for project_id, defaults in bootstrap_defaults_by_project.items()
            if defaults.provider_id != operational_selection.workspace_provider_id
            or defaults.adapter_binding_digest
            != operational_selection.workspace_adapter_binding_digest
        )
    )
    if drifted_defaults:
        raise KernelContractError(
            "enzymedesign_workspace_bootstrap_adapter_drift",
            "project defaults differ from the exact selected workspace Adapter",
            details={
                "project_ids": list(drifted_defaults),
                "fallback_performed": False,
            },
        )
    operational_selection = replace(
        operational_selection,
        external_qualification_admission=external_qualification_admission,
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
    workflow_registry = EnzymeDesignExactWorkflowRegistry(clock=clock)
    subject_policies = enzymedesign_subject_policy_decisions_by_role(
        composition.declared_tool_catalog
    )
    exposure_policies = enzymedesign_tool_exposure_policies(
        composition.declared_tool_catalog,
        release_digest=active.release_identity.release_digest,
    )
    role_policy_digest = _enzymedesign_role_policy_digest(
        subject_policies=subject_policies,
        exposure_policies=exposure_policies,
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
            observation_ports={operational_selection.workspace_provider_id: filesystem},
            filesystem_ports={operational_selection.workspace_provider_id: filesystem},
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
    admissions = EnzymeDesignKernelRuntimeAdmissionSource(
        records=store,
        startup=startup,
        declared_catalog=composition.declared_tool_catalog,
        extension_registry=extension_registry,
        capability_registries=capability_registries,
        workflow_registry_snapshot_digest=(workflow_registry.registry_snapshot_digest),
        subject_policy_decisions_by_role=subject_policies,
        tool_exposure_policies=exposure_policies,
        runtime_adapter_id=operational_selection.runtime_adapter.adapter_id,
        runtime_adapter_contract_digest=(
            operational_selection.runtime_adapter.adapter_contract_digest
        ),
    )
    runtime_admission_identity_digest = _enzymedesign_runtime_admission_identity_digest(
        admission=admissions,
        role_policy_digest=role_policy_digest,
    )
    protocols = ProtocolKernelApplicationService(
        store=store,
        clock=clock,
        ids=ids,
    )
    finish_validators = FinishValidatorRegistry.from_mounted(mounted.finish_validators)
    collaboration_service = CollaborationKernelApplicationService(
        store=store,
        clock=clock,
        ids=ids,
    )
    tasks_service = TaskKernelApplicationService(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
        finish_validators=finish_validators,
    )
    approvals_service = ApprovalKernelApplicationService(
        store=store,
        clock=clock,
        ids=ids,
    )
    collaboration_context = EnzymeDesignCollaborationToolContextResolver(
        records=store,
        admissions=admissions,
        startup=startup,
    )
    collaboration_runtimes = build_kernel_collaboration_tool_runtimes(
        applications=CollaborationToolApplications(
            world=EnzymeDesignWorldInspectionApplication(
                records=store,
                admissions=admissions,
            ),
            collaboration=collaboration_service,
            tasks=tasks_service,
            protocol=protocols,
            approvals=approvals_service,
        ),
        context_resolver=collaboration_context,
    )
    capabilities_contract = next(
        spec
        for spec in kernel_collaboration_tool_specs()
        if spec.tool_name == "capabilities.inspect"
    )
    kernel_runtimes = (
        *collaboration_runtimes,
        KernelCapabilitiesInspectRuntime(contract=capabilities_contract),
        *kernel_workspace_runtimes,
    )
    mounted_tools = mount_runtime_tool_set(
        gate=startup.gate,
        catalog=composition.declared_tool_catalog,
        kernel_runtimes=kernel_runtimes,
        extension_surfaces=mounted,
    )
    expansions = ControlStoreCommandToolExpansionStore(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
    )
    outcomes = ControlStoreRuntimeOutcomeRepository(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
    )
    workspace_provisioning = WorkspaceProvisioningKernelApplicationService(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
    )
    workspace_provisioning_worker = WorkspaceProvisioningWorker(
        application=workspace_provisioning,
        reader=store,
        ports={
            operational_selection.workspace_adapter_binding_digest: (
                operational_selection.workspace_provisioner
            )
        },
        clock=clock,
        ids=ids,
    )
    workspace_provisioning_runner = EnzymeDesignWorkspaceProvisioningRunner(
        worker=workspace_provisioning_worker,
        records=store,
        authority=workspace_worker_authority,
        ids=ids,
    )
    workspace_provisioning_lifecycle_worker = (
        EnzymeDesignWorkspaceProvisioningLifecycleWorker(
            runner=workspace_provisioning_runner,
            records=store,
            clock=clock,
        )
    )
    runtime_drain = EnzymeDesignBoundedRuntimeDrainApplication(
        coordination=RuntimeCoordinationKernelApplicationService(
            store=store,
            reader=store,
            clock=clock,
            ids=ids,
        ),
        continuations=RuntimeContinuationDeliveryWorker(
            application=RuntimeContinuationDeliveryKernelApplicationService(
                store=store,
                clock=clock,
                ids=ids,
            ),
            records=store,
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
            expansions=expansions,
            clock=clock,
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
    runtime_commands = RuntimeCommandKernelApplicationService(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
    )
    runtime_worker = EnzymeDesignRuntimeCommandWorker(
        commands=runtime_commands,
        records=store,
        contexts=EnzymeDesignRuntimeCommandContextResolver(
            records=store,
            extension_bundle_digest=(active.release_identity.extension_bundle_digest),
            ids=ids,
        ),
        executor=runtime_drain,
        clock=clock,
        claim_owner="enzymedesign-runtime-worker",
    )
    coordination = EnzymeDesignKernelCoordinationRouteApplication(
        collaboration=collaboration_service,
        tasks=tasks_service,
        protocols=protocols,
        approvals=approvals_service,
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
            workflow_registry=workflow_registry,
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
        runtime_drain=EnzymeDesignRuntimeDrainAdmissionApplication(
            commands=runtime_commands,
            ids=ids,
        ),
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
    operational_routes = build_enzymedesign_operational_route_applications(operational)
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
        workspace_provisioning_reconciler=workspace_provisioning_runner,
        clock=clock,
        ids=ids,
        route_applications=route_applications,
        bootstrap_defaults_by_project=bootstrap_defaults_by_project,
    )
    core_provider = KernelPublicWorkspaceProjectionService(
        reader=store,
        declared_catalog=composition.declared_tool_catalog,
        capability_registries=capability_registries,
        extension_bundle_digest=active.release_identity.extension_bundle_digest,
        distribution_id=composition.distribution_id,
        adopted_release_digest=active.release_identity.release_digest,
        subject_policy_decisions_by_role=subject_policies,
        tool_exposure_policies=exposure_policies,
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
        workspace_provisioning=workspace_provisioning,
        workspace_provisioning_worker=workspace_provisioning_worker,
        workspace_provisioning_runner=workspace_provisioning_runner,
        workspace_provisioning_lifecycle_worker=(
            workspace_provisioning_lifecycle_worker
        ),
        extension_state=extension_state,
        compute_executions=compute_executions,
        continuations=continuations,
        publications=publications,
        workspace_operation_ledger=workspace_operation_ledger,
        scheduler_occurrence_ledger=scheduler_occurrence_ledger,
        slurm_scheduler=slurm_scheduler,
        bootstrap=bootstrap,
        coordination=coordination,
        runtime_commands=runtime_commands,
        runtime_worker=runtime_worker,
        gateway=gateway,
        workflow_registry=workflow_registry,
        runtime_admission=admissions,
        active_epoch_id=active.epoch_id,
        active_release_digest=active.release_identity.release_digest,
        activation_digest=active.activation_digest,
        extension_bundle_digest=active.release_identity.extension_bundle_digest,
        declared_tool_catalog_digest=(
            active.release_identity.declared_tool_catalog_digest
        ),
        adapter_runtime_digest=adapter_runtimes.runtime_digest,
        workflow_registry_snapshot_digest=(workflow_registry.registry_snapshot_digest),
        role_policy_digest=role_policy_digest,
        runtime_admission_identity_digest=runtime_admission_identity_digest,
        workspace_adapter_binding_digest=(
            operational_selection.workspace_adapter_binding_digest
        ),
        application_binding_ids=binding_ids,
        external_qualification_admission=external_qualification_admission,
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
                contribution for _, contribution in runtime.mounted_surfaces.http_routes
            ),
        )
    )
    app.state.enzymedesign_runtime = runtime
    return app


def _validate_enzymedesign_application_composition(
    *,
    startup: EnzymeDesignDeploymentStartup,
    composition: ActivatedDistributionComposition,
    official_composition: ActivatedDistributionComposition | None = None,
) -> DeploymentActivationEpoch:
    """Re-run the exact packaged manifest and active-release closure read-only."""

    runtime_authorization = startup.gate.require_active(DeploymentSurface.RUNTIME)
    active = startup.gate.validate_authorization(
        runtime_authorization,
        surface=DeploymentSurface.RUNTIME,
    )
    official = official_composition or activate_enzymedesign_composition()
    workspace_backends = tuple(
        binding
        for binding in composition.adapters
        if binding.selection.slot_id == "workspace.backend"
    )
    workspace_backend_digest = (
        workspace_backends[0].manifest.manifest_digest
        if len(workspace_backends) == 1
        else None
    )
    release = active.release_identity
    mismatches = {
        "official_composition": composition != official,
        "active_epoch_digest": not active.has_valid_digest(),
        "distribution_id": active.distribution_id != composition.distribution_id,
        "kernel_manifest_digest": (
            active.kernel_manifest_digest != composition.kernel_identity.manifest_digest
        ),
        "distribution_manifest_digest": (
            active.distribution_manifest_digest
            != composition.distribution_manifest_digest
        ),
        "composition_document_digest": (
            active.composition_document_digest
            != composition.composition_document_digest
        ),
        "composition_activation_digest": (
            active.composition_activation_digest != composition.activation_digest
        ),
        "driver_bundle_digest": (
            active.driver_bundle_digest != composition.driver_bundle_digest
        ),
        "http_route_catalog_digest": (
            active.http_route_catalog_digest
            != composition.http_route_catalog.catalog_digest
        ),
        "contribution_catalogs_digest": (
            active.contribution_catalogs_digest
            != composition.contribution_catalogs.catalogs_digest
        ),
        "kernel_contract_digest": (
            release.kernel_contract_digest
            != composition.kernel_identity.contract_digest
        ),
        "adapter_bundle_digest": (
            release.adapter_bundle_digest != composition.adapter_bundle_digest
        ),
        "extension_bundle_digest": (
            release.extension_bundle_digest
            != composition.plugins.extension_bundle_digest
        ),
        "declared_tool_catalog_digest": (
            release.declared_tool_catalog_digest
            != composition.declared_tool_catalog.catalog_digest
        ),
        "route_catalog_digest": (
            release.route_catalog_digest != composition.route_catalog.catalog_digest
        ),
        "projection_catalog_digest": (
            release.projection_catalog_digest
            != composition.contribution_catalogs.projection.catalog_digest
        ),
        "migration_catalog_digest": (
            release.migration_catalog_digest
            != composition.contribution_catalogs.migration.catalog_digest
        ),
        "workspace_backend_digest": (
            workspace_backend_digest is None
            or release.workspace_backend_digest != workspace_backend_digest
        ),
    }
    drifted = tuple(sorted(name for name, drifted in mismatches.items() if drifted))
    if drifted:
        raise KernelContractError(
            "enzymedesign_application_startup_drift",
            (
                "application runtime composition differs from packaged manifests "
                "or active release"
            ),
            details={
                "drifted_fields": list(drifted),
                "mutation_applied": False,
                "fallback_performed": False,
            },
        )
    return active


def _enzymedesign_runtime_admission_identity_digest(
    *,
    admission: EnzymeDesignKernelRuntimeAdmissionSource,
    role_policy_digest: str,
) -> str:
    """Bind the actual admission resolver, catalogs and complete role policy."""

    require_digest(role_policy_digest, field_name="role_policy_digest")
    if not admission.extension_registry.has_valid_digest():
        raise KernelContractError(
            "enzymedesign_application_runtime_identity_drift",
            "runtime admission extension registry identity drifted",
            details={"mutation_applied": False, "fallback_performed": False},
        )
    return canonical_sha256_digest(
        {
            "schema_version": "enzymedesign_runtime_admission_identity@1",
            "declared_tool_catalog_digest": admission.declared_catalog.catalog_digest,
            "extension_bundle_digest": (
                admission.extension_registry.extension_bundle_digest
            ),
            "extension_registry_digest": admission.extension_registry.registry_digest,
            "workflow_registry_snapshot_digest": (
                admission.workflow_registry_snapshot_digest
            ),
            "role_policy_digest": role_policy_digest,
            "runtime_adapter_id": admission.runtime_adapter_id,
            "runtime_adapter_contract_digest": (
                admission.runtime_adapter_contract_digest
            ),
        }
    )


def _adapter_key(key: tuple[str, str | None]) -> str:
    slot_id, target_id = key
    return slot_id if target_id is None else f"{slot_id}:{target_id}"


def _enzymedesign_role_policy_digest(
    *,
    subject_policies: Mapping[str, tuple[Any, ...]],
    exposure_policies: tuple[Any, ...],
) -> str:
    """Bind every adopted role's authority and exposure decisions exactly."""

    if tuple(subject_policies) != ENZYMEDESIGN_RESIDENT_ROLES:
        raise KernelContractError(
            "enzymedesign_application_role_policy_incomplete",
            "application role authority policy does not cover every resident role",
            details={"mutation_applied": False, "fallback_performed": False},
        )
    exposure_by_role = {policy.subject_role: policy for policy in exposure_policies}
    if (
        len(exposure_by_role) != len(exposure_policies)
        or tuple(exposure_by_role) != ENZYMEDESIGN_RESIDENT_ROLES
    ):
        raise KernelContractError(
            "enzymedesign_application_role_policy_incomplete",
            "application role exposure policy does not cover every resident role",
            details={"mutation_applied": False, "fallback_performed": False},
        )
    return canonical_sha256_digest(
        {
            "schema_version": "enzymedesign_complete_role_policy@1",
            "resident_roles": list(ENZYMEDESIGN_RESIDENT_ROLES),
            "subject_decisions": {
                role: [decision.to_dict() for decision in subject_policies[role]]
                for role in ENZYMEDESIGN_RESIDENT_ROLES
            },
            "exposure_policies": [
                {
                    "policy_id": exposure_by_role[role].policy_id,
                    "distribution_id": exposure_by_role[role].distribution_id,
                    "release_digest": exposure_by_role[role].release_digest,
                    "subject_role": role,
                    "decisions": [
                        decision.to_dict()
                        for decision in exposure_by_role[role].decisions
                    ],
                    "policy_digest": exposure_by_role[role].policy_digest,
                }
                for role in ENZYMEDESIGN_RESIDENT_ROLES
            ],
        }
    )


__all__ = [
    "EnzymeDesignAdapterRuntimeBinding",
    "EnzymeDesignAdapterRuntimeSet",
    "EnzymeDesignApplicationRuntime",
    "EnzymeDesignCapabilityRegistryResolver",
    "EnzymeDesignLocalWorkspaceRuntimeAdapters",
    "EnzymeDesignOperationalAdapterSelection",
    "EnzymeDesignPodmanOperationalRuntime",
    "EnzymeDesignSlurmOperationalRuntime",
    "EnzymeDesignTargetInventoryQueryPort",
    "build_enzymedesign_application_runtime",
    "build_enzymedesign_v2_host_app",
]
