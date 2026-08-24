from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import canonical_sha256_digest
from enzymedesign_alphafold.manifest_locator import (
    locate_component_manifest as alphafold_locator,
)
from enzymedesign_alphafold.manifest_locator import (
    locate_hpc_driver_manifest as alphafold_hpc_locator,
)
from enzymedesign_aox.manifest_locator import locate_component_manifest as aox_locator
from enzymedesign_aox import AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY
from enzymedesign_aox import AoxScientificDeliverableRequestHandler
from enzymedesign_aox_executor import AoxExecutorCalculationReceiptValidator
from enzymedesign_aox_executor.manifest_locator import (
    locate_component_manifest as aox_executor_locator,
)
from enzymedesign_bio_provider_adapters.manifest_locator import (
    locate_component_manifest as bio_http_locator,
)
from enzymedesign_bio_providers.manifest_locator import (
    locate_component_manifest as bio_provider_locator,
)
from enzymedesign_docking_preprocess.manifest_locator import (
    locate_component_manifest as preprocess_locator,
)
from enzymedesign_hmmer.manifest_locator import (
    locate_component_manifest as hmmer_locator,
)
from enzymedesign_hmmer.manifest_locator import (
    locate_hpc_driver_manifest as hmmer_hpc_locator,
)
from enzymedesign_hmmer.manifest_locator import (
    locate_local_driver_manifest as hmmer_local_locator,
)
from enzymedesign_sequence_toolpack.manifest_locator import (
    locate_component_manifest as sequence_locator,
)
from enzymedesign_structure.manifest_locator import (
    locate_component_manifest as structure_locator,
)
from enzymedesign_structure.manifest_locator import (
    locate_hpc_driver_manifest as fpocket_hpc_locator,
)
from enzymedesign_structure.manifest_locator import (
    locate_local_driver_manifest as fpocket_local_locator,
)
from enzymedesign_vina.manifest_locator import locate_component_manifest as vina_locator
from enzymedesign_vina.manifest_locator import (
    locate_hpc_driver_manifest as vina_hpc_locator,
)
from enzymedesign_vina.manifest_locator import (
    locate_local_driver_manifest as vina_local_locator,
)
from openzyme_compute.manifest_locator import (
    locate_component_manifest as compute_locator,
)
from openzyme_extension_spi import DistributionCompositionDocument
from openzyme_extension_spi import ExtensionManifestLocator
from openzyme_extension_spi import parse_distribution_composition_toml
from openzyme_extension_spi import read_located_component_manifest
from openzyme_hpc.manifest_locator import locate_component_manifest as hpc_locator
from openzyme_hpc_slurm.manifest_locator import (
    locate_component_manifest as slurm_locator,
)
from openzyme_hpc_ssh.manifest_locator import locate_component_manifest as ssh_locator
from openzyme_kernel import ActivatedDistributionComposition
from openzyme_kernel import DeploymentActivationCoordinator
from openzyme_kernel import DeploymentActivationGate
from openzyme_kernel import DeploymentActivationRequest
from openzyme_kernel import DeploymentVerificationKind
from openzyme_kernel import KernelActivationIdentity
from openzyme_kernel import ReadOnlyDeploymentVerification
from openzyme_kernel import SelectedManifestLocators
from openzyme_kernel import activate_distribution_composition
from openzyme_kernel import kernel_workspace_declared_tool_entries
from openzyme_kernel import select_distribution_manifest_locators
from openzyme_kernel.collaboration_tools import (
    kernel_collaboration_declared_tool_entries,
)
from openzyme_process_podman.manifest_locator import (
    locate_component_manifest as podman_locator,
)
from openzyme_reporting.manifest_locator import (
    locate_component_manifest as reporting_locator,
)
from openzyme_research.manifest_locator import (
    locate_component_manifest as research_locator,
)
from openzyme_research_tavily.manifest_locator import (
    locate_component_manifest as tavily_locator,
)
from openzyme_runtime_llm.manifest_locator import (
    locate_component_manifest as llm_locator,
)
from openzyme_science.manifest_locator import (
    locate_component_manifest as science_locator,
)
from openzyme_science import ScientificDeliverableRequestHandler
from openzyme_science import ScientificWorkflowContractRegistry
from openzyme_science_research.manifest_locator import (
    locate_component_manifest as science_research_locator,
)
from openzyme_store_sqlite.manifest_locator import (
    locate_component_manifest as sqlite_locator,
)
from openzyme_store_sqlite import CompositeSQLiteStartupProof
from openzyme_store_sqlite import ENZYMEDESIGN_OWNER_SCHEMA_PROFILE
from openzyme_store_sqlite import FreshInstallCompositionSeed
from openzyme_store_sqlite import FreshInstallDeploymentProof
from openzyme_store_sqlite import MigrationSourceIdentity
from openzyme_store_sqlite import SessionCompositionStateProof
from openzyme_store_sqlite import STORE_MIGRATIONS
from openzyme_store_sqlite import verify_fresh_install_deployment_read_only
from openzyme_store_sqlite import verify_session_composition_state_read_only
from openzyme_workspace_git_lfs.manifest_locator import (
    locate_component_manifest as git_lfs_locator,
)


@dataclass(frozen=True, slots=True)
class EnzymeDesignScientificContributions:
    workflow_contract_registry: ScientificWorkflowContractRegistry
    finalization_handler: ScientificDeliverableRequestHandler


@dataclass(frozen=True, slots=True)
class EnzymeDesignDeploymentStartup:
    gate: DeploymentActivationGate
    deployment_proof: FreshInstallDeploymentProof
    session_composition_proof: SessionCompositionStateProof
    verifications: tuple[ReadOnlyDeploymentVerification, ...]

    @property
    def proof_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "schema_version": "enzymedesign_deployment_startup@1",
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
                "plugin_runtime_mounted": False,
                "writer_enabled": False,
            }
        )


def build_enzymedesign_scientific_contributions() -> (
    EnzymeDesignScientificContributions
):
    return EnzymeDesignScientificContributions(
        workflow_contract_registry=AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY,
        finalization_handler=AoxScientificDeliverableRequestHandler(
            AoxExecutorCalculationReceiptValidator()
        ),
    )


def load_enzymedesign_composition() -> DistributionCompositionDocument:
    resource = files("enzymedesign_distribution").joinpath("openzyme-composition.toml")
    document = parse_distribution_composition_toml(resource.read_bytes())
    if document.manifest.identity.component_id != "enzymedesign":
        raise RuntimeError("packaged EnzymeDesign Distribution identity drifted")
    return document


def enzymedesign_component_locators() -> tuple[ExtensionManifestLocator, ...]:
    return (
        alphafold_locator(),
        alphafold_hpc_locator(),
        aox_locator(),
        aox_executor_locator(),
        bio_http_locator(),
        bio_provider_locator(),
        preprocess_locator(),
        hmmer_locator(),
        hmmer_hpc_locator(),
        hmmer_local_locator(),
        sequence_locator(),
        structure_locator(),
        fpocket_hpc_locator(),
        fpocket_local_locator(),
        vina_locator(),
        vina_hpc_locator(),
        vina_local_locator(),
        compute_locator(),
        hpc_locator(),
        slurm_locator(),
        ssh_locator(),
        podman_locator(),
        reporting_locator(),
        research_locator(),
        tavily_locator(),
        llm_locator(),
        science_locator(),
        science_research_locator(),
        sqlite_locator(),
        git_lfs_locator(),
    )


def select_enzymedesign_component_locators() -> SelectedManifestLocators:
    return select_distribution_manifest_locators(
        load_enzymedesign_composition(),
        enzymedesign_component_locators(),
    )


def activate_enzymedesign_composition() -> ActivatedDistributionComposition:
    """Build exact EnzymeDesign catalogs without probing Providers or HPC."""

    document = load_enzymedesign_composition()
    selection = select_enzymedesign_component_locators()
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
        kernel_tools=tuple(
            sorted(
                (
                    *kernel_collaboration_declared_tool_entries(),
                    *kernel_workspace_declared_tool_entries(),
                ),
                key=lambda item: item.contract.tool_name,
            )
        ),
    )


def build_enzymedesign_fresh_install_seed(
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
    """Bind exact EnzymeDesign catalogs to its selected owner schema profile."""

    composition = activate_enzymedesign_composition()
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
        raise RuntimeError("EnzymeDesign deployment catalog payload identity drifted")
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
    return FreshInstallCompositionSeed(
        schema_proof=schema_proof,
        owner_schema_profile=ENZYMEDESIGN_OWNER_SCHEMA_PROFILE,
        activation_epoch=epoch,
        catalog_payloads=catalog_payloads,
        migration_sources=(
            MigrationSourceIdentity(
                owner_component_id="openzyme.store.sqlite",
                migration_id=ENZYMEDESIGN_OWNER_SCHEMA_PROFILE.profile_id,
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
        ),
        installed_wheel_set_digest=installed_wheel_set_digest,
        table_owner_manifest_digest=schema_proof.owner_schema.table_owner_manifest_digest,
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
            verifier_id="enzymedesign.fresh-bootstrap-verifier",
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


def verify_enzymedesign_deployment_startup_read_only(
    connection: Any,
    *,
    seed: FreshInstallCompositionSeed,
    observed_installed_wheel_set_digest: str,
    verified_at: str,
) -> EnzymeDesignDeploymentStartup:
    """Re-authorize one persisted EnzymeDesign epoch without mounting Plugins."""

    composition = activate_enzymedesign_composition()
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
    )
    gate = DeploymentActivationGate()
    DeploymentActivationCoordinator(gate).reactivate_persisted(
        composition=composition,
        persisted_epoch=seed.activation_epoch,
        expected_wheel_set_digest=seed.installed_wheel_set_digest,
        verifications=proofs,
    )
    return EnzymeDesignDeploymentStartup(
        gate=gate,
        deployment_proof=deployment,
        session_composition_proof=sessions,
        verifications=proofs,
    )


def _current_startup_verifications(
    *,
    composition: ActivatedDistributionComposition,
    release: LayeredReleaseIdentity,
    observed_schema_digest: str,
    expected_wheel_set_digest: str,
    observed_wheel_set_digest: str,
    verified_at: str,
) -> tuple[ReadOnlyDeploymentVerification, ...]:
    return tuple(
        ReadOnlyDeploymentVerification.create(
            verification_id=f"startup-{kind.value}",
            verification_kind=kind,
            verifier_id="enzymedesign.startup-verifier",
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
        "plugins": [
            {
                "plugin_id": activation.plugin_id,
                "requirement_mode": activation.selection.requirement_mode.value,
                "presence": (
                    "present" if activation.manifest is not None else "inactive"
                ),
                "manifest_digest": (
                    activation.manifest.manifest_digest
                    if activation.manifest is not None
                    else activation.selection.manifest_digest
                ),
            }
            for activation in composition.plugins.activations
        ],
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
    "EnzymeDesignDeploymentStartup",
    "EnzymeDesignScientificContributions",
    "activate_enzymedesign_composition",
    "build_enzymedesign_fresh_install_seed",
    "build_enzymedesign_scientific_contributions",
    "enzymedesign_component_locators",
    "load_enzymedesign_composition",
    "select_enzymedesign_component_locators",
    "verify_enzymedesign_deployment_startup_read_only",
]
