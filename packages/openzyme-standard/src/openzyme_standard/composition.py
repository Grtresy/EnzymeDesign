from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import ClockPort
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import WorkspaceRevisionBackendPort
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import DistributionCompositionDocument
from openzyme_extension_spi import ExtensionManifestLocator
from openzyme_extension_spi import parse_distribution_composition_toml
from openzyme_extension_spi import read_located_component_manifest
from openzyme_kernel import ActivatedDistributionComposition
from openzyme_kernel import AuthorityKernelApplicationService
from openzyme_kernel import ControlledOperationKernelApplicationService
from openzyme_kernel import CapabilityRegistry
from openzyme_kernel import ExtensionBundleRegistry
from openzyme_kernel import DeploymentActivationCoordinator
from openzyme_kernel import DeploymentActivationGate
from openzyme_kernel import DeploymentActivationRequest
from openzyme_kernel import DeploymentSurface
from openzyme_kernel import DeploymentVerificationKind
from openzyme_kernel import KernelActivationIdentity
from openzyme_kernel import KernelPublicWorkspaceProjectionService
from openzyme_kernel import MountedExtensionSurfaces
from openzyme_kernel import MountedRuntimeToolSet
from openzyme_kernel import PublicationKernelApplicationService
from openzyme_kernel import PublicationManifestPolicyPort
from openzyme_kernel import ReadOnlyDeploymentVerification
from openzyme_kernel import RouteCatalog
from openzyme_kernel import SelectedManifestLocators
from openzyme_kernel import WorkspacePublicationCoordinator
from openzyme_kernel import activate_distribution_composition
from openzyme_kernel import mount_extension_surfaces
from openzyme_kernel import mount_runtime_tool_set
from openzyme_kernel import build_kernel_workspace_tool_runtimes
from openzyme_kernel import kernel_workspace_declared_tool_entries
from openzyme_kernel import select_distribution_manifest_locators
from openzyme_process_podman.manifest_locator import locate_component_manifest as podman_locator
from openzyme_runtime_llm.manifest_locator import locate_component_manifest as llm_locator
from openzyme_store_sqlite.manifest_locator import locate_component_manifest as sqlite_locator
from openzyme_store_sqlite import CompositeSQLiteStartupProof
from openzyme_store_sqlite import FreshInstallCompositionSeed
from openzyme_store_sqlite import MigrationSourceIdentity
from openzyme_store_sqlite import OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE
from openzyme_store_sqlite import SQLiteControlStore
from openzyme_store_sqlite import SQLiteKernelEntityCodec
from openzyme_store_sqlite import kernel_entity_codecs
from openzyme_store_sqlite import STORE_MIGRATIONS
from openzyme_store_sqlite import FreshInstallDeploymentProof
from openzyme_store_sqlite import SessionCompositionStateProof
from openzyme_store_sqlite import verify_fresh_install_deployment_read_only
from openzyme_store_sqlite import verify_session_composition_state_read_only
from openzyme_workspace_git_lfs.manifest_locator import (
    locate_component_manifest as git_lfs_locator,
)


STANDARD_ADAPTER_SLOTS = (
    "agent.turn",
    "kernel.store",
    "process.isolation",
    "workspace.backend",
)

# Every canonical entity read or written by the Plugin-free Kernel application
# surface needs one explicit existing-owner-table codec. This is a writer
# admission contract, not permission to fall back to a generic JSON truth table.
STANDARD_KERNEL_ENTITY_TYPES = (
    "agent_authority_lease",
    "agent_member",
    "agent_runtime_signal",
    "approval_request",
    "continuation",
    "controlled_operation",
    "conversation_message",
    "failure_observation",
    "inbox_message",
    "kernel_command_receipt",
    "lane",
    "memory",
    "project_repository_binding",
    "project_repository_binding_head",
    "protocol_record",
    "published_revision",
    "revision_path_verification",
    "runtime_continuation_intent",
    "runtime_outcome_consumption",
    "runtime_settlement_intent",
    "runtime_turn_command",
    "session",
    "session_capability_binding_revision",
    "session_composition_pin",
    "session_repository_binding_pin",
    "session_runtime_lease",
    "task",
    "task_evidence",
    "verified_workspace_checkpoint",
    "workspace_generation",
    "workspace_publication_intent",
    "workspace_runtime_binding",
)


class StandardKernelStoreReadinessError(RuntimeError):
    """The selected SQLite Adapter cannot serve the exact Kernel surface."""

    error_code = "standard_kernel_store_codec_incomplete"

    def __init__(self, *, missing_entity_types: tuple[str, ...]) -> None:
        self.missing_entity_types = missing_entity_types
        self.mutation_applied = False
        self.writer_enabled = False
        self.fallback_performed = False
        super().__init__(
            "Plugin-free Standard Kernel Store codec closure is incomplete; "
            f"missing_entity_types={list(missing_entity_types)!r}; "
            "mutation_applied=false; writer_enabled=false; fallback_performed=false"
        )


@dataclass(frozen=True, slots=True)
class StandardKernelStoreCodecCoverage:
    required_entity_types: tuple[str, ...]
    available_entity_types: tuple[str, ...]
    missing_entity_types: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.missing_entity_types

    @property
    def coverage_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "schema_version": "openzyme_standard_kernel_store_codec_coverage@1",
                "required_entity_types": list(self.required_entity_types),
                "available_entity_types": list(self.available_entity_types),
                "missing_entity_types": list(self.missing_entity_types),
                "ready": self.ready,
            }
        )


def standard_kernel_entity_codecs() -> tuple[SQLiteKernelEntityCodec, ...]:
    """Return only implemented production codecs; never synthesize placeholders."""

    return kernel_entity_codecs()


def inspect_standard_kernel_store_codec_coverage(
    codecs: tuple[SQLiteKernelEntityCodec, ...] | None = None,
) -> StandardKernelStoreCodecCoverage:
    selected = standard_kernel_entity_codecs() if codecs is None else codecs
    available = tuple(sorted(codec.entity_type for codec in selected))
    if len(available) != len(set(available)):
        raise ValueError("Standard Kernel entity codec identities must be unique")
    unexpected = sorted(set(available).difference(STANDARD_KERNEL_ENTITY_TYPES))
    if unexpected:
        raise ValueError(
            "Standard Kernel entity codec catalog contains undeclared types: "
            f"{unexpected!r}"
        )
    return StandardKernelStoreCodecCoverage(
        required_entity_types=STANDARD_KERNEL_ENTITY_TYPES,
        available_entity_types=available,
        missing_entity_types=tuple(
            sorted(set(STANDARD_KERNEL_ENTITY_TYPES).difference(available))
        ),
    )


def build_standard_kernel_control_store(
    connection: Any,
    *,
    startup: "StandardDeploymentStartup",
    codecs: tuple[SQLiteKernelEntityCodec, ...] | None = None,
) -> SQLiteControlStore:
    """Open the real Standard writer only after activation and codec closure."""

    startup.gate.require_active(DeploymentSurface.REPOSITORY_WRITER)
    selected = standard_kernel_entity_codecs() if codecs is None else codecs
    coverage = inspect_standard_kernel_store_codec_coverage(selected)
    if not coverage.ready:
        raise StandardKernelStoreReadinessError(
            missing_entity_types=coverage.missing_entity_types,
        )
    return SQLiteControlStore(connection, codecs=selected)


@dataclass(frozen=True, slots=True)
class StandardPluginFreeCapabilityRegistryResolver:
    """Resolve Standard's exact empty-Plugin capability graph per Session."""

    extension_registry: ExtensionBundleRegistry
    route_catalog: RouteCatalog

    def resolve(
        self,
        binding: SessionCapabilityBindingRevision,
    ) -> CapabilityRegistry:
        return CapabilityRegistry.create(
            extension_bundle=self.extension_registry,
            binding=binding,
            route_catalog=self.route_catalog,
            resource_facts=(),
        )


def build_standard_kernel_public_projection_provider(
    connection: Any,
    *,
    startup: "StandardDeploymentStartup",
    clock: ClockPort,
) -> KernelPublicWorkspaceProjectionService:
    """Build the real Plugin-free `file_workspace_public@2` Core provider."""

    startup.gate.require_active(DeploymentSurface.HTTP_ROUTE)
    active_epoch = startup.gate.active_epoch
    if active_epoch is None:  # defensive; require_active already rejects this
        raise RuntimeError("Standard deployment epoch is not active")
    composition = activate_standard_composition()
    release = active_epoch.release_identity
    if (
        release.extension_bundle_digest
        != composition.plugins.extension_bundle_digest
        or release.declared_tool_catalog_digest
        != composition.declared_tool_catalog.catalog_digest
        or release.route_catalog_digest != composition.route_catalog.catalog_digest
    ):
        raise RuntimeError("Standard public projection catalogs drifted from activation")
    coverage = inspect_standard_kernel_store_codec_coverage()
    if not coverage.ready:
        raise StandardKernelStoreReadinessError(
            missing_entity_types=coverage.missing_entity_types,
        )
    reader = SQLiteControlStore(connection, codecs=standard_kernel_entity_codecs())
    extension_registry = ExtensionBundleRegistry.create(
        composition.plugins,
        activation_epoch=active_epoch.sequence,
    )
    return KernelPublicWorkspaceProjectionService(
        reader=reader,
        declared_catalog=composition.declared_tool_catalog,
        capability_registries=StandardPluginFreeCapabilityRegistryResolver(
            extension_registry=extension_registry,
            route_catalog=composition.route_catalog,
        ),
        extension_bundle_digest=release.extension_bundle_digest,
        clock=clock,
    )


@dataclass(frozen=True, slots=True)
class StandardDeploymentStartup:
    gate: DeploymentActivationGate
    deployment_proof: FreshInstallDeploymentProof
    session_composition_proof: SessionCompositionStateProof
    verifications: tuple[ReadOnlyDeploymentVerification, ...]
    mounted_surfaces: MountedExtensionSurfaces

    @property
    def proof_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "schema_version": "openzyme_standard_deployment_startup@1",
                "activation_digest": (
                    self.gate.active_epoch.activation_digest
                    if self.gate.active_epoch is not None
                    else None
                ),
                "deployment_proof_digest": self.deployment_proof.proof_digest,
                "session_composition_proof_digest": (
                    self.session_composition_proof.proof_digest
                ),
                "verification_digests": [
                    item.verification_digest for item in self.verifications
                ],
                "mutation_applied": False,
                "plugin_runtime_mounted": True,
                "runtime_mount_digest": self.mounted_surfaces.mount_digest,
                "writer_enabled": False,
            }
        )


@dataclass(frozen=True, slots=True)
class StandardKernelPublicationRuntime:
    """Exact Standard composition behind the Kernel publication boundary."""

    store: SQLiteControlStore
    authority: AuthorityKernelApplicationService
    publications: PublicationKernelApplicationService
    controlled_operations: ControlledOperationKernelApplicationService
    coordinator: WorkspacePublicationCoordinator


def build_standard_kernel_publication_runtime(
    connection: Any,
    *,
    startup: StandardDeploymentStartup,
    clock: ClockPort,
    ids: IdGeneratorPort,
    revision_backend: WorkspaceRevisionBackendPort,
    manifest_policy: PublicationManifestPolicyPort,
) -> StandardKernelPublicationRuntime:
    """Compose publication only after the exact Standard epoch is active.

    Construction performs no Git/LFS observation or mutation. The returned
    coordinator remains the sole semantic writer, while the selected revision
    backend and manifest policy retain mechanism ownership.
    """

    startup.gate.require_active(DeploymentSurface.REPOSITORY_WRITER)
    startup.gate.require_active(DeploymentSurface.RUNTIME)
    startup.gate.require_active(DeploymentSurface.EXTERNAL_EFFECT)
    if manifest_policy is None:
        raise ValueError("Standard publication requires an exact manifest policy")
    store = build_standard_kernel_control_store(connection, startup=startup)
    authority = AuthorityKernelApplicationService(reader=store, clock=clock)
    publications = PublicationKernelApplicationService(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
        revision_backend=revision_backend,
    )
    controlled_operations = ControlledOperationKernelApplicationService(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
    )
    coordinator = WorkspacePublicationCoordinator(
        reader=store,
        authority=authority,
        publications=publications,
        controlled_operations=controlled_operations,
        revision_backend=revision_backend,
        manifest_policy=manifest_policy,
    )
    return StandardKernelPublicationRuntime(
        store=store,
        authority=authority,
        publications=publications,
        controlled_operations=controlled_operations,
        coordinator=coordinator,
    )


def mount_standard_kernel_workspace_tool_set(
    *,
    startup: StandardDeploymentStartup,
    coordinator: Any,
    context_resolver: Any,
) -> MountedRuntimeToolSet:
    """Mount the exact five Kernel workspace runtimes after Standard activation.

    Extension surfaces remain empty in Plugin-free Standard.  This separate
    mount proves that Kernel base tools are executable without misclassifying
    the Kernel as a semantic Plugin.
    """

    composition = activate_standard_composition()
    return mount_runtime_tool_set(
        gate=startup.gate,
        catalog=composition.declared_tool_catalog,
        kernel_runtimes=build_kernel_workspace_tool_runtimes(
            coordinator=coordinator,
            context_resolver=context_resolver,
        ),
        extension_surfaces=startup.mounted_surfaces,
    )


def load_standard_composition() -> DistributionCompositionDocument:
    resource = files("openzyme_standard").joinpath("openzyme-composition.toml")
    document = parse_distribution_composition_toml(resource.read_bytes())
    if document.manifest.plugins:
        raise RuntimeError("OpenZyme Standard must not require semantic Plugins")
    observed_slots = tuple(sorted(item.slot_id for item in document.manifest.adapters))
    if observed_slots != STANDARD_ADAPTER_SLOTS:
        raise RuntimeError("OpenZyme Standard Adapter slot set drifted")
    return document


def standard_component_locators() -> tuple[ExtensionManifestLocator, ...]:
    return (
        llm_locator(),
        sqlite_locator(),
        podman_locator(),
        git_lfs_locator(),
    )


def select_standard_component_locators() -> SelectedManifestLocators:
    return select_distribution_manifest_locators(
        load_standard_composition(),
        standard_component_locators(),
    )


def activate_standard_composition() -> ActivatedDistributionComposition:
    """Build the exact Plugin-free Standard catalogs without starting a surface."""

    document = load_standard_composition()
    selection = select_standard_component_locators()
    manifests = {
        locator.component_id: read_located_component_manifest(locator)
        for locator in selection.selected
    }
    kernel = document.manifest.kernel
    return activate_distribution_composition(
        document,
        kernel_identity=KernelActivationIdentity(
            component_id=kernel.implementation_component_id,
            distribution_name="openzyme-kernel",
            distribution_version="0.1.0",
            contract_digest=kernel.contract_digest,
            manifest_digest=kernel.implementation_manifest_digest,
        ),
        located_manifests=manifests,
        kernel_tools=kernel_workspace_declared_tool_entries(),
    )


def build_standard_fresh_install_seed(
    *,
    schema_proof: CompositeSQLiteStartupProof,
    installed_wheel_set_digest: str,
    host_build_digest: str,
    client_build_digest: str,
    epoch_id: str,
    sequence: int,
    activated_by_actor_id: str,
    activated_at: str,
) -> FreshInstallCompositionSeed:
    """Bind the Plugin-free Standard composition to one empty target schema."""

    composition = activate_standard_composition()
    catalog_payloads = _deployment_catalog_payloads(composition)
    digests = {
        kind: canonical_sha256_digest(payload) for kind, payload in catalog_payloads
    }
    release = LayeredReleaseIdentity(
        kernel_contract_digest=composition.kernel_identity.contract_digest,
        core_schema_digest=schema_proof.complete_schema_manifest_digest,
        adapter_bundle_digest=composition.adapter_bundle_digest,
        extension_bundle_digest=composition.plugins.extension_bundle_digest,
        declared_tool_catalog_digest=composition.declared_tool_catalog.catalog_digest,
        route_catalog_digest=composition.route_catalog.catalog_digest,
        projection_catalog_digest=(
            composition.contribution_catalogs.projection.catalog_digest
        ),
        migration_catalog_digest=(
            composition.contribution_catalogs.migration.catalog_digest
        ),
        workspace_backend_digest=digests["workspace_backend"],
        host_build_digest=host_build_digest,
        client_build_digest=client_build_digest,
    )
    expected = {
        "adapter_bundle": release.adapter_bundle_digest,
        "extension_bundle": release.extension_bundle_digest,
        "declared_tool": release.declared_tool_catalog_digest,
        "route": release.route_catalog_digest,
        "projection": release.projection_catalog_digest,
        "migration": release.migration_catalog_digest,
        "workspace_backend": release.workspace_backend_digest,
    }
    if digests != expected:
        raise RuntimeError("Standard deployment catalog payload identity drifted")
    epoch = _create_verified_epoch(
        composition=composition,
        release=release,
        schema_proof=schema_proof,
        installed_wheel_set_digest=installed_wheel_set_digest,
        epoch_id=epoch_id,
        sequence=sequence,
        activated_by_actor_id=activated_by_actor_id,
        activated_at=activated_at,
    )
    migration_sources = (
        MigrationSourceIdentity(
            owner_component_id="openzyme.store.sqlite",
            migration_id=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE.profile_id,
            migration_digest=schema_proof.owner_schema.owner_migration_catalog_digest,
        ),
        *(
            MigrationSourceIdentity(
                owner_component_id=item.owner_component_id,
                migration_id=item.migration_id,
                migration_digest=item.sql_digest,
            )
            for item in STORE_MIGRATIONS
        ),
    )
    return FreshInstallCompositionSeed(
        schema_proof=schema_proof,
        owner_schema_profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
        activation_epoch=epoch,
        catalog_payloads=catalog_payloads,
        migration_sources=migration_sources,
        installed_wheel_set_digest=installed_wheel_set_digest,
        table_owner_manifest_digest=schema_proof.owner_schema.table_owner_manifest_digest,
    )


def verify_standard_deployment_startup_read_only(
    connection: Any,
    *,
    seed: FreshInstallCompositionSeed,
    observed_installed_wheel_set_digest: str,
    verified_at: str,
) -> StandardDeploymentStartup:
    """Re-authorize one persisted Standard epoch and mount its exact empty Plugin set."""

    composition = activate_standard_composition()
    deployment = verify_fresh_install_deployment_read_only(connection, seed=seed)
    sessions = verify_session_composition_state_read_only(
        connection,
        activation_epoch=seed.activation_epoch,
    )
    proofs = _current_startup_verifications(
        composition=composition,
        release=seed.activation_epoch.release_identity,
        observed_schema_digest=deployment.schema.complete_schema_manifest_digest,
        expected_wheel_set_digest=seed.installed_wheel_set_digest,
        observed_wheel_set_digest=observed_installed_wheel_set_digest,
        verified_at=verified_at,
        verifier_id="openzyme.standard.startup-verifier",
    )
    gate = DeploymentActivationGate()
    DeploymentActivationCoordinator(gate).reactivate_persisted(
        composition=composition,
        persisted_epoch=seed.activation_epoch,
        expected_wheel_set_digest=seed.installed_wheel_set_digest,
        verifications=proofs,
    )
    mounted = mount_extension_surfaces(
        gate=gate,
        composition=composition,
        runtime_bundles=(),
    )
    return StandardDeploymentStartup(
        gate=gate,
        deployment_proof=deployment,
        session_composition_proof=sessions,
        verifications=proofs,
        mounted_surfaces=mounted,
    )


def _create_verified_epoch(
    *,
    composition: ActivatedDistributionComposition,
    release: LayeredReleaseIdentity,
    schema_proof: CompositeSQLiteStartupProof,
    installed_wheel_set_digest: str,
    epoch_id: str,
    sequence: int,
    activated_by_actor_id: str,
    activated_at: str,
):
    proofs = tuple(
        ReadOnlyDeploymentVerification.create(
            verification_id=f"{epoch_id}-{kind.value}",
            verification_kind=kind,
            verifier_id="openzyme.standard.fresh-bootstrap-verifier",
            expected_digest=expected,
            observed_digest=observed,
            verified_at=activated_at,
        )
        for kind, expected, observed in (
            (
                DeploymentVerificationKind.COMPOSITION,
                composition.activation_digest,
                composition.activation_digest,
            ),
            (
                DeploymentVerificationKind.CORE_SCHEMA,
                release.core_schema_digest,
                schema_proof.complete_schema_manifest_digest,
            ),
            (
                DeploymentVerificationKind.INSTALLED_WHEELS,
                installed_wheel_set_digest,
                installed_wheel_set_digest,
            ),
        )
    )
    return DeploymentActivationCoordinator(DeploymentActivationGate()).activate(
        composition=composition,
        release_identity=release,
        request=DeploymentActivationRequest(
            epoch_id=epoch_id,
            sequence=sequence,
            expected_wheel_set_digest=installed_wheel_set_digest,
            activated_by_actor_id=activated_by_actor_id,
            activated_at=activated_at,
            verifications=proofs,
        ),
    )


def _current_startup_verifications(
    *,
    composition: ActivatedDistributionComposition,
    release: LayeredReleaseIdentity,
    observed_schema_digest: str,
    expected_wheel_set_digest: str,
    observed_wheel_set_digest: str,
    verified_at: str,
    verifier_id: str,
) -> tuple[ReadOnlyDeploymentVerification, ...]:
    return tuple(
        ReadOnlyDeploymentVerification.create(
            verification_id=f"startup-{kind.value}",
            verification_kind=kind,
            verifier_id=verifier_id,
            expected_digest=expected,
            observed_digest=observed,
            verified_at=verified_at,
        )
        for kind, expected, observed in (
            (
                DeploymentVerificationKind.COMPOSITION,
                composition.activation_digest,
                composition.activation_digest,
            ),
            (
                DeploymentVerificationKind.CORE_SCHEMA,
                release.core_schema_digest,
                observed_schema_digest,
            ),
            (
                DeploymentVerificationKind.INSTALLED_WHEELS,
                expected_wheel_set_digest,
                observed_wheel_set_digest,
            ),
        )
    )


def _deployment_catalog_payloads(
    composition: ActivatedDistributionComposition,
) -> tuple[tuple[str, object], ...]:
    extension_payload = {
        "distribution_id": composition.distribution_id,
        "distribution_manifest_digest": composition.distribution_manifest_digest,
        "plugins": [],
    }
    projection = composition.contribution_catalogs.projection
    migration = composition.contribution_catalogs.migration
    workspace = next(
        binding.manifest
        for binding in composition.adapters
        if binding.selection.slot_id == "workspace.backend"
    )
    return (
        ("adapter_bundle", [item.to_dict() for item in composition.adapters]),
        ("extension_bundle", extension_payload),
        (
            "declared_tool",
            {
                "schema_version": "openzyme_declared_tool_catalog@1",
                "entries": [
                    item.to_dict() for item in composition.declared_tool_catalog.entries
                ],
            },
        ),
        (
            "route",
            {
                "schema_version": "openzyme_route_catalog@1",
                "routes": [item.to_dict() for item in composition.route_catalog.routes],
            },
        ),
        (
            "projection",
            {
                "schema_version": "openzyme_contribution_catalog@1",
                "catalog_kind": projection.catalog_kind,
                "entries": [item.to_dict() for item in projection.entries],
            },
        ),
        (
            "migration",
            {
                "schema_version": "openzyme_contribution_catalog@1",
                "catalog_kind": migration.catalog_kind,
                "entries": [item.to_dict() for item in migration.entries],
            },
        ),
        ("workspace_backend", workspace.to_dict()),
    )


__all__ = [
    "STANDARD_ADAPTER_SLOTS",
    "STANDARD_KERNEL_ENTITY_TYPES",
    "StandardDeploymentStartup",
    "StandardKernelStoreCodecCoverage",
    "StandardKernelStoreReadinessError",
    "StandardKernelPublicationRuntime",
    "StandardPluginFreeCapabilityRegistryResolver",
    "activate_standard_composition",
    "build_standard_fresh_install_seed",
    "build_standard_kernel_control_store",
    "build_standard_kernel_publication_runtime",
    "build_standard_kernel_public_projection_provider",
    "inspect_standard_kernel_store_codec_coverage",
    "load_standard_composition",
    "mount_standard_kernel_workspace_tool_set",
    "select_standard_component_locators",
    "standard_component_locators",
    "standard_kernel_entity_codecs",
    "verify_standard_deployment_startup_read_only",
]
