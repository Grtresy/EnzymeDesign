from pathlib import Path
import asyncio
import sqlite3
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from datetime import timedelta

import pytest
import httpx

from enzymedesign_alphafold import build_alphafold_plugin_runtime_surfaces
from enzymedesign_aox import build_aox_plugin_runtime_surfaces
from enzymedesign_bio_providers import build_bio_provider_route_runtimes
from enzymedesign_docking_preprocess import build_preprocess_plugin_runtime_surfaces
from enzymedesign_distribution import activate_enzymedesign_composition
from enzymedesign_distribution import EnzymeDesignAdapterRuntimeBinding
from enzymedesign_distribution import EnzymeDesignAdapterRuntimeSet
from enzymedesign_distribution import EnzymeDesignOperationalAdapterSelection
from enzymedesign_distribution import EnzymeDesignPluginRuntimeSurfaceSet
from enzymedesign_distribution import EnzymeDesignFormalComputeApplicationBinding
from enzymedesign_distribution import ExactComputeRouteRouter
from enzymedesign_distribution import build_enzymedesign_application_runtime
from enzymedesign_distribution import build_enzymedesign_scientific_contributions
from enzymedesign_distribution import build_enzymedesign_fresh_install_seed
from enzymedesign_distribution import build_enzymedesign_formal_compute_application
from enzymedesign_distribution import build_enzymedesign_v2_host_app
from enzymedesign_distribution import FormalComputeSourceBinding
from enzymedesign_distribution import load_enzymedesign_composition
from enzymedesign_distribution import mount_enzymedesign_extension_surfaces
from enzymedesign_distribution import select_enzymedesign_component_locators
from enzymedesign_distribution import verify_enzymedesign_deployment_startup_read_only
from enzymedesign_hmmer import build_hmmer_plugin_runtime_surfaces
from enzymedesign_sequence_toolpack import build_sequence_plugin_runtimes
from enzymedesign_structure import build_structure_plugin_runtime_surfaces
from enzymedesign_vina import build_vina_plugin_runtime_surfaces
from openzyme_compute import build_compute_plugin_runtime_surfaces
from openzyme_compute import ComputeAdmissionProof
from openzyme_compute import ComputeExecutionApplicationService
from openzyme_compute import ComputeRouteOutcome
from openzyme_compute import InMemoryComputeExecutionRepository
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import EvidenceKind
from openzyme_contracts import EvidenceRef
from openzyme_contracts import GitObjectFormat
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import PrivateRefAdvanceKind
from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import PublicationManifestEntry
from openzyme_contracts import PublicationManifestObjectKind
from openzyme_contracts import RepositoryRefNamespacePolicy
from openzyme_contracts import RevisionCommitObservation
from openzyme_contracts import RevisionManifestObservation
from openzyme_contracts import RevisionPathVerificationReceipt
from openzyme_contracts import SessionRepositoryBindingPin
from openzyme_contracts import ResourceCapabilityFact
from openzyme_contracts import ResourceCapabilityKind
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import TargetInventoryBinding
from openzyme_contracts import ToolAffordanceState
from openzyme_contracts import ToolInvocation
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import VerifiedWorkspaceCheckpoint
from openzyme_contracts import WorkspaceFormalBoundary
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import WorkspaceGenerationStatus
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import WorkspacePublicationManifest
from openzyme_contracts import WorkspacePublicationRemoteReceipt
from openzyme_extension_spi import ControlledOperationCommandKind
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelEntityRef
from openzyme_extension_spi import KernelEntitySnapshot
from openzyme_extension_spi import KernelQueryContext
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_extension_spi import ToolDispatchBinding
from openzyme_extension_spi import CompositionManifestState
from openzyme_extension_spi import parse_distribution_composition_toml
from openzyme_contracts import SessionBootstrapAuthorization
from openzyme_contracts import SessionBootstrapAuthorityDecision
from openzyme_hpc import build_hpc_plugin_runtime_surfaces
from openzyme_hpc import InventoryGeneration
from openzyme_hpc import QualificationReceiptStatus
from openzyme_hpc import SoftwareQualificationReceipt
from openzyme_hpc import SQLiteTargetInventoryRepository
from openzyme_hpc import TargetCapabilityFact
from openzyme_hpc import TargetToolchainInventory
from openzyme_hpc_slurm import SlurmSchedulerAdapterFactory
from openzyme_host_api import HostSecurityPolicy
from openzyme_host_api import HostV2SessionBootstrapInvocation
from openzyme_kernel import KernelContractError
from openzyme_kernel import CapabilityRegistry
from openzyme_kernel import ExtensionBundleRegistry
from openzyme_kernel import CollaborationApplicationCommand
from openzyme_kernel import CollaborationCommandKind
from openzyme_kernel import MountedRuntimeCapabilityGateway
from openzyme_kernel import RuntimeToolScope
from openzyme_kernel import ToolAffordanceContext
from openzyme_kernel import resolve_tool_affordance_snapshot
from openzyme_kernel import subject_policy_digest
from openzyme_kernel import WorkspacePublicationCoordinator
from openzyme_kernel import WorkspacePublicationRequest
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_reporting import build_reporting_plugin_runtime_surfaces
from openzyme_research import build_research_plugin_runtime_surfaces
from openzyme_science import build_science_plugin_runtime_surfaces
from openzyme_science import SCIENCE_CLOSURE_EVIDENCE_CONTRACT_ID
from openzyme_science import SCIENCE_FINISH_VALIDATOR_ID
from openzyme_execution_contracts import ExecutionResultReceipt
from openzyme_runtime_spi import RuntimeToolRequest
from openzyme_store_sqlite import ENZYMEDESIGN_OWNER_SCHEMA_PROFILE
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration
from openzyme_store_sqlite import seed_fresh_install_composition_offline
from openzyme_store_sqlite import SQLiteRevisionPathVerificationQuery
from openzyme_store_sqlite import verify_composite_store_schema_read_only
from openzyme_kernel import DeploymentSurface


ROOT = Path(__file__).resolve().parents[3]
DIGEST = "sha256:" + "7" * 64


class _NoopApplication:
    def request(self, **kwargs):
        return {
            "state": "accepted",
            "workload_id": "workload-1",
            "workload_digest": DIGEST,
        }

    def invoke(self, **kwargs):
        return {"state": "accepted"}

    def invoke_route(self, **kwargs):
        return {"state": "accepted"}

    def contract_digest(self, renderer_id):
        return DIGEST


class _EmptyInventoryRepository:
    def get(self, target_id, generation):  # noqa: ANN001, ANN201
        del target_id, generation
        return None


class _IdleRuntimeAdapter:
    adapter_id = "test.runtime.idle"
    adapter_contract_digest = DIGEST

    def run_turn(self, command, capability_gateway):  # noqa: ANN001, ANN201
        del command, capability_gateway
        raise AssertionError("runtime turn was not expected during composition")


class _NoopSlurmBackend:
    def __getattr__(self, name):  # noqa: ANN001, ANN201
        raise AssertionError(f"Slurm backend operation was not expected: {name}")


class _EmptySchedulerCredentials:
    def resolve(self, occurrence_id):  # noqa: ANN001, ANN201
        del occurrence_id
        return None


class _FormalSourceBindings:
    def resolve(self, *, invocation, dispatch, workload):  # noqa: ANN001, ANN201
        del invocation, dispatch
        source = workload.inputs[0]
        return FormalComputeSourceBinding(
            session_version=1,
            workspace_id="workspace-formal-1",
            workspace_generation=1,
            source_revision_id=source.revision_id,
            source_ref=f"refs/openzyme/public/{source.revision_id}",
            source_commit=source.commit,
            source_tree=source.tree,
            lfs_closure_manifest_digest=DIGEST,
            clean_observation_digest=DIGEST,
        )


class _FormalAdmissionVerifier:
    def verify(self, *, context, request):  # noqa: ANN001, ANN201
        return ComputeAdmissionProof(
            session_id=request.session_id,
            owner_agent_member_id=request.owner_agent_member_id,
            authority_lease_id=request.authority_lease_id,
            authority_generation=request.authority_generation,
            authority_fence=request.authority_fence,
            workspace_id=request.workspace_id,
            workspace_generation=request.workspace_generation,
            source_revision_id=request.source_revision_id,
            clean_observation_digest=request.clean_observation_digest,
            lfs_closure_manifest_digest=request.lfs_closure_manifest_digest,
            route_id=request.route.route_id,
            inventory_generation=request.route.inventory_generation,
            capability_binding_digest=context.capability_binding_digest,
            proof_digest=DIGEST,
        )


class _FormalControlledOperations:
    def __init__(self):
        self.operations = []

    def execute(self, command):  # noqa: ANN001, ANN201
        self.operations.append(command.operation)
        certainty = (
            ExternalEffectCertainty.NO_EFFECT
            if command.operation is ControlledOperationCommandKind.ADMIT
            else ExternalEffectCertainty.EFFECT_KNOWN
        )
        return KernelMutationReceipt.create(
            command_id=command.context.command_id,
            service_id="controlled_operation",
            operation=command.operation.value,
            mutation_applied=True,
            effect_certainty=certainty,
            result={"fallback_performed": False},
        )


class _DeclaredFormalRunnerPort:
    def __init__(self):
        self.requests = []

    def dispatch(self, request):  # noqa: ANN001, ANN201
        self.requests.append(request)
        return ComputeRouteOutcome(
            route_id=request.route.route_id,
            operation_id=request.operation_id,
            provider_handle=f"handle-{request.execution_id}",
            receipt_digest=DIGEST,
            effect_certainty=ExternalEffectCertainty.EFFECT_KNOWN,
            mutation_applied=True,
        )

    def observe(self, request, provider_handle):  # noqa: ANN001, ANN201
        raise AssertionError((request, provider_handle))

    def cancel(self, request, provider_handle):  # noqa: ANN001, ANN201
        raise AssertionError((request, provider_handle))


class _ProductFormalRunnerPort:
    """The only replaced external Port in the product-level non-live proof."""

    def __init__(self) -> None:
        self.requests = []
        self.observe_calls = 0

    def dispatch(self, request):  # noqa: ANN001, ANN201
        self.requests.append(request)
        return ComputeRouteOutcome(
            route_id=request.route.route_id,
            operation_id=request.operation_id,
            provider_handle=f"product-handle-{request.execution_id}",
            receipt_digest=canonical_sha256_digest(
                {"phase": "dispatched", "execution_id": request.execution_id}
            ),
            effect_certainty=ExternalEffectCertainty.EFFECT_KNOWN,
            mutation_applied=True,
        )

    def observe(self, request, provider_handle):  # noqa: ANN001, ANN201
        self.observe_calls += 1
        assert provider_handle == f"product-handle-{request.execution_id}"
        result_contract_digest = canonical_sha256_digest(
            request.workload.result_contract.to_dict()
        )
        result_digest = canonical_sha256_digest(
            {
                "execution_id": request.execution_id,
                "workload_digest": request.workload.workload_digest,
                "state": "succeeded",
            }
        )
        terminal_digest = canonical_sha256_digest(
            {"result_digest": result_digest, "provider_handle": provider_handle}
        )
        result = ExecutionResultReceipt.from_dict(
            {
                "schema_version": "execution_result_receipt@1",
                "result_id": f"result-{request.execution_id}",
                "invocation_id": request.invocation_id,
                "operation_id": request.operation_id,
                "execution_id": request.execution_id,
                "route_id": request.route.route_id,
                "workload_digest": request.workload.workload_digest,
                "state": "succeeded",
                "result_contract_digest": result_contract_digest,
                "result_revision_id": None,
                "result_digest": result_digest,
                "terminal_receipt_digest": terminal_digest,
            }
        )
        return ComputeRouteOutcome(
            route_id=request.route.route_id,
            operation_id=request.operation_id,
            provider_handle=provider_handle,
            receipt_digest=canonical_sha256_digest(
                {"phase": "terminal", "execution_id": request.execution_id}
            ),
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            mutation_applied=True,
            terminal_result=result,
        )

    def cancel(self, request, provider_handle):  # noqa: ANN001, ANN201
        raise AssertionError((request, provider_handle))


class _AcceptedScienceEvidenceReader:
    def __init__(self) -> None:
        self.calls = []

    def validate_closure(self, **facts):  # noqa: ANN003, ANN201
        self.calls.append(facts)
        return True, ()


class _StaticRuntimeScopeProvider:
    def __init__(self, scope) -> None:  # noqa: ANN001
        self.scope = scope

    def get(self, command_id):  # noqa: ANN001, ANN201
        return self.scope if command_id == self.scope.command_id else None


class _ProductRevisionBackend:
    """Deterministic Git-shaped Adapter fake used only at the declared I/O Port."""

    def __init__(self, manifest: WorkspacePublicationManifest) -> None:
        self.manifest = manifest
        self.receipt = None
        self.dispatch_count = 0

    def observe_commit(self, binding, *, commit):  # noqa: ANN001, ANN201
        return RevisionCommitObservation.create(
            repository_binding_id=binding.binding_id,
            repository_binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            commit=commit,
            tree="b" * 40,
            parent_commits=(binding.default_base_commit,),
            observed_at="2026-08-22T00:00:00+00:00",
        )

    def observe_manifest(self, binding, *, commit):  # noqa: ANN001, ANN201
        return RevisionManifestObservation.create(
            repository_binding_id=binding.binding_id,
            repository_binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            commit=commit,
            tree="b" * 40,
            manifest=self.manifest,
            observed_at="2026-08-22T00:00:00+00:00",
        )

    def dispatch_publication(self, binding, intent, dispatch):  # noqa: ANN001, ANN201
        self.dispatch_count += 1
        self.receipt = WorkspacePublicationRemoteReceipt.create(
            receipt_id=dispatch.receipt_id,
            intent_id=intent.intent_id,
            publication_id=intent.publication_id,
            execution_id=dispatch.execution_id,
            execution_dispatch_generation=dispatch.dispatch_generation,
            execution_fencing_token=dispatch.fencing_token,
            internal_git_service_id=binding.internal_git_service_id,
            repository_binding_id=binding.binding_id,
            repository_binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            publication_ref=intent.publication_ref,
            expected_previous_commit=None,
            new_commit=intent.expected_head_commit,
            new_tree=intent.expected_tree,
            server_observed_commit=intent.expected_head_commit,
            observed_at="2026-08-22T00:00:00+00:00",
        )
        return self.receipt

    def reconcile_publication(self, binding, intent, dispatch):  # noqa: ANN001, ANN201
        del binding, intent, dispatch
        return self.receipt

    def observe_publication(self, binding, intent, receipt):  # noqa: ANN001, ANN201
        del binding, intent
        return receipt


class _ManifestPolicy:
    def validate(self, **facts):  # noqa: ANN003, ANN201
        return type("ManifestValidation", (), {"manifest": facts["manifest"]})()


class _BootstrapAuthority:
    def issue(self, **facts):  # noqa: ANN003, ANN201
        issued_at = datetime(2026, 8, 22, tzinfo=UTC)
        return SessionBootstrapAuthorization.create(
            authorization_id="enzymedesign-bootstrap-authorization",
            operator_actor_id=facts["actor_id"],
            project_id=facts["project_id"],
            session_id=facts["session_id"],
            root_authority_lease_digest=facts["root_authority_lease_digest"],
            session_composition_pin_digest=facts["session_composition_pin_digest"],
            extension_bundle_digest=facts["extension_bundle_digest"],
            capability_binding_digest=facts["capability_binding_digest"],
            generation=1,
            fence=1,
            issued_at=issued_at.isoformat(),
            expires_at=(issued_at + timedelta(minutes=5)).isoformat(),
        )

    def verify(self, authorization, *, now_iso):  # noqa: ANN001, ANN201
        del now_iso
        return SessionBootstrapAuthorityDecision(
            allowed=True,
            authorization_id=authorization.authorization_id,
            authorization_digest=authorization.authorization_digest,
        )


def _operational_selection(
    *, revision_backend=None  # noqa: ANN001
) -> EnzymeDesignOperationalAdapterSelection:
    return EnzymeDesignOperationalAdapterSelection(
        runtime_adapter=_IdleRuntimeAdapter(),
        workspace_mounts=object(),  # type: ignore[arg-type]
        process_isolation=object(),  # type: ignore[arg-type]
        revision_backend=revision_backend or object(),  # type: ignore[arg-type]
        slurm_factory=SlurmSchedulerAdapterFactory(),
        slurm_backend=_NoopSlurmBackend(),  # type: ignore[arg-type]
        slurm_credential_resolver=_EmptySchedulerCredentials(),
    )


def _runtime_surface_set(
    *,
    formal_application=None,  # noqa: ANN001
    science_evidence_reader=None,  # noqa: ANN001
) -> EnzymeDesignPluginRuntimeSurfaceSet:
    application = _NoopApplication()
    formal_application = formal_application or application
    science_evidence_reader = science_evidence_reader or application
    return EnzymeDesignPluginRuntimeSurfaceSet(
        compute=build_compute_plugin_runtime_surfaces(
            tool_application=application,
            projection_application=application,
            worker_application=application,
        ),
        hpc=build_hpc_plugin_runtime_surfaces(
            workspace_application=application,
            route_application=application,
            projection_application=application,
            worker_application=application,
        ),
        reporting=build_reporting_plugin_runtime_surfaces(
            tool_application=application,
            renderer_catalog=application,
            http_application=application,
            projection_application=application,
            worker_application=application,
            evidence_reader=application,
        ),
        research=build_research_plugin_runtime_surfaces(
            repository=application,
            service=application,
        ),
        science=build_science_plugin_runtime_surfaces(
            tool_application=application,
            http_application=application,
            projection_application=application,
            worker_application=application,
            evidence_reader=science_evidence_reader,
        ),
        bio_provider_routes=build_bio_provider_route_runtimes(application),
        hmmer=build_hmmer_plugin_runtime_surfaces(
            application=formal_application,
            route_application=application,
        ),
        sequence_tools=build_sequence_plugin_runtimes(application=application),
        aox=build_aox_plugin_runtime_surfaces(route_application=application),
        alphafold=build_alphafold_plugin_runtime_surfaces(
            application=application,
            route_application=application,
        ),
        preprocess=build_preprocess_plugin_runtime_surfaces(application=application),
        structure=build_structure_plugin_runtime_surfaces(
            application=application,
            route_application=application,
        ),
        vina=build_vina_plugin_runtime_surfaces(
            application=formal_application,
            route_application=application,
        ),
    )


def _adapter_runtime_set(
    operational_selection: EnzymeDesignOperationalAdapterSelection,
) -> EnzymeDesignAdapterRuntimeSet:
    composition = activate_enzymedesign_composition()
    return EnzymeDesignAdapterRuntimeSet(
        bindings=tuple(
            EnzymeDesignAdapterRuntimeBinding(
                slot_id=item.selection.slot_id,
                target_id=item.selection.target_id,
                component_id=item.manifest.identity.component_id,
                manifest_digest=item.manifest.manifest_digest,
                runtime=(
                    operational_selection.slurm_factory
                    if item.selection.slot_id == "hpc.scheduler"
                    else object()
                ),
            )
            for item in composition.adapters
        )
    )


def _activated_startup():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(
        connection,
        profile=ENZYMEDESIGN_OWNER_SCHEMA_PROFILE,
    )
    install_store_schema_for_offline_migration(connection)
    schema = verify_composite_store_schema_read_only(
        connection,
        owner_schema_profile=ENZYMEDESIGN_OWNER_SCHEMA_PROFILE,
    )
    seed = build_enzymedesign_fresh_install_seed(
        schema_proof=schema,
        installed_wheel_set_digest="sha256:" + "4" * 64,
        host_build_digest="sha256:" + "5" * 64,
        client_build_digest="sha256:" + "6" * 64,
        epoch_id="enzymedesign-runtime-mount-1",
        sequence=1,
        activated_by_actor_id="operator-1",
        activated_at="2026-08-22T00:00:00+00:00",
    )
    seed_fresh_install_composition_offline(connection, seed)
    startup = verify_enzymedesign_deployment_startup_read_only(
        connection,
        seed=seed,
        observed_installed_wheel_set_digest="sha256:" + "4" * 64,
        verified_at="2026-08-22T00:01:00+00:00",
    )
    return connection, startup


def _seed_kernel_record(
    runtime,
    *,
    session_id: str,
    session_version: int,
    actor_id: str,
    lease: AgentAuthorityLease,
    label: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, object],
) -> None:
    unit = runtime.store.begin(
        UnitOfWorkRequest(
            unit_of_work_id=f"uow-product-{label}",
            command_id=f"command-product-{label}",
            session_id=session_id,
            actor_id=actor_id,
            authority_lease_id=lease.lease_id,
            authority_generation=lease.generation,
            authority_fence=lease.fence,
            expected_session_version=session_version,
            idempotency_key=f"product-{label}",
            command_digest=canonical_sha256_digest({"product_seed": label}),
        )
    )
    unit.stage(
        KernelStateMutation.create(
            mutation_id=f"mutation-product-{label}",
            kind=KernelMutationKind.CREATE,
            entity_type=entity_type,
            entity_id=entity_id,
            expected_state_version=None,
            payload=payload,
        )
    )
    unit.commit()


def _publish_product_inventory(
    connection: sqlite3.Connection,
) -> tuple[SQLiteTargetInventoryRepository, TargetToolchainInventory]:
    repository = SQLiteTargetInventoryRepository(connection)
    observed_at = "2026-08-22T00:00:00+00:00"
    valid_until = "2026-09-01T00:00:00+00:00"
    receipts = tuple(
        SoftwareQualificationReceipt.create(
            receipt_id=f"qualification-{suffix}",
            qualification_spec_id=f"enzymedesign.{suffix}.qualification@1",
            qualification_spec_digest=canonical_sha256_digest(
                {"qualification": suffix}
            ),
            target_id="hpc-primary",
            environment_digest=canonical_sha256_digest(
                {"environment": "hpc-primary"}
            ),
            capability_id=capability_id,
            observed_version=version,
            version_query_receipt_digest=canonical_sha256_digest(
                {"version_query": suffix}
            ),
            smoke_input_digest=canonical_sha256_digest({"smoke_input": suffix}),
            smoke_result_digest=canonical_sha256_digest({"smoke_result": suffix}),
            expected_result_schema_digest=canonical_sha256_digest(
                {"result_schema": suffix}
            ),
            status=QualificationReceiptStatus.PASSED,
            observed_at=observed_at,
            valid_until=valid_until,
        )
        for suffix, capability_id, version in (
            ("hmmer", "software.hmmer", "3.4"),
            ("vina", "software.autodock-vina", "1.2.5"),
        )
    )
    inventory = TargetToolchainInventory.create(
        target_id="hpc-primary",
        generation=1,
        target_profile_digest=canonical_sha256_digest(
            {"target_profile": "hpc-primary"}
        ),
        facts=(
            TargetCapabilityFact(
                capability_id="software.hmmer",
                kind=ResourceCapabilityKind.SOFTWARE,
                contract_version="1",
                version="3.4",
                operations=("hmmbuild", "hmmsearch"),
                environment_digest=receipts[0].environment_digest,
                qualification_digest=receipts[0].receipt_digest,
                implementation_digest=canonical_sha256_digest(
                    {"binary": "hmmer-3.4"}
                ),
            ),
            TargetCapabilityFact(
                capability_id="software.autodock-vina",
                kind=ResourceCapabilityKind.SOFTWARE,
                contract_version="1",
                version="1.2.5",
                operations=("dock", "score"),
                environment_digest=receipts[1].environment_digest,
                qualification_digest=receipts[1].receipt_digest,
                implementation_digest=canonical_sha256_digest(
                    {"binary": "vina-1.2.5"}
                ),
            ),
        ),
        qualification_receipt_digests=tuple(
            item.receipt_digest for item in receipts
        ),
        valid_until=valid_until,
        created_at=observed_at,
    )
    repository.publish(
        inventory,
        InventoryGeneration.create(
            target_id=inventory.target_id,
            generation=inventory.generation,
            previous_inventory_digest=None,
            inventory_digest=inventory.inventory_digest,
            published_by_actor_id="operator-1",
            published_at=observed_at,
        ),
        receipts,
        expected_previous_digest=None,
    )
    return repository, inventory


def _seed_product_source(
    runtime,
    *,
    session_id: str,
    session_version: int,
    member_id: str,
    lease: AgentAuthorityLease,
    backend: _ProductRevisionBackend,
) -> tuple[str, dict[str, str]]:
    base = "c" * 40
    commit = "a" * 40
    tree = "b" * 40
    workspace_id = "workspace-product-1"
    binding = ProjectRepositoryBinding.create(
        binding_id="repository-binding-product-1",
        project_id="project-product-cross-layer-1",
        binding_version=1,
        repository_id="repository-product-1",
        internal_git_service_id="git-product-1",
        internal_git_endpoint="https://git.internal.example/product-1",
        lfs_service_id="lfs-product-1",
        lfs_endpoint="https://lfs.internal.example/product-1",
        upstream_identity="upstream-product-1",
        upstream_url="https://example.org/product/repository.git",
        object_format=GitObjectFormat.SHA1,
        default_base_ref="refs/heads/main",
        default_base_commit=base,
        ref_namespace_policy=RepositoryRefNamespacePolicy(
            private_prefix="refs/openzyme/private",
            publication_prefix="refs/openzyme/publications",
            historical_prefix="refs/openzyme/historical",
        ),
        repository_policy_version="repository-policy-product-1",
        repository_policy_digest=canonical_sha256_digest(
            {"repository_policy": "product"}
        ),
        created_at="2026-08-22T00:00:00+00:00",
        created_by="operator-1",
    )
    pin = SessionRepositoryBindingPin(
        session_id=session_id,
        project_id=binding.project_id,
        binding_id=binding.binding_id,
        binding_version=binding.binding_version,
        repository_id=binding.repository_id,
        resolved_base_commit=binding.default_base_commit,
        binding_canonical_digest=binding.canonical_digest,
        pinned_at="2026-08-22T00:00:00+00:00",
    )
    generation = WorkspaceGeneration(
        workspace_id=workspace_id,
        workspace_kind=WorkspaceKind.AGENT_LOCAL,
        session_id=session_id,
        owner_member_id=member_id,
        generation=1,
        state_version=1,
        status=WorkspaceGenerationStatus.READY,
        provider_id="openzyme.workspace.git-lfs",
        target_id="local:host",
        created_at="2026-08-22T00:00:00+00:00",
        updated_at="2026-08-22T00:00:00+00:00",
        root_identity_digest=canonical_sha256_digest(
            {"workspace_root": workspace_id}
        ),
        transition_receipt_digest=canonical_sha256_digest(
            {"workspace_ready": workspace_id}
        ),
        controlled_operation_id="workspace-operation-product-1",
    )
    checkpoint = VerifiedWorkspaceCheckpoint.create(
        checkpoint_id="checkpoint-product-1",
        boundary=WorkspaceFormalBoundary.PUBLICATION,
        workspace_id=workspace_id,
        session_id=session_id,
        agent_member_id=member_id,
        agent_id=member_id,
        workspace_generation=1,
        repository_binding_id=binding.binding_id,
        repository_binding_version=binding.binding_version,
        repository_id=binding.repository_id,
        commit=commit,
        tree=tree,
        private_ref=f"refs/openzyme/private/{session_id}/{member_id}",
        prior_commit=base,
        advance_kind=PrivateRefAdvanceKind.FAST_FORWARD,
        remote_observed_at="2026-08-22T00:00:00+00:00",
        verified_at="2026-08-22T00:00:00+00:00",
    )
    for label, entity_type, entity_id, payload in (
        ("repository-binding", "project_repository_binding", binding.binding_id, binding.to_dict()),
        ("repository-pin", "session_repository_binding_pin", session_id, pin.to_dict()),
        ("workspace-generation", "workspace_generation", workspace_id, generation.to_dict()),
        ("workspace-runtime", "workspace_runtime_binding", workspace_id, generation.runtime_binding().to_dict()),
        ("checkpoint", "verified_workspace_checkpoint", checkpoint.checkpoint_id, checkpoint.to_dict()),
    ):
        _seed_kernel_record(
            runtime,
            session_id=session_id,
            session_version=session_version,
            actor_id=member_id,
            lease=lease,
            label=label,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
        )
    context = KernelCommandContext(
        command_id="command-product-publish",
        session_id=session_id,
        actor_id=member_id,
        owner_plugin_id="openzyme.kernel",
        authority_lease_id=lease.lease_id,
        authority_generation=lease.generation,
        authority_fence=lease.fence,
        expected_session_version=session_version,
        extension_bundle_digest=runtime.composition.plugins.extension_bundle_digest,
        capability_binding_digest=runtime.store.list_for_session(
            entity_type="session_capability_binding_revision",
            session_id=session_id,
            max_items=4,
        )[0].payload["binding_digest"],
        idempotency_key="product-publication-1",
        correlation_id="correlation-product-publication-1",
        workspace_generation=1,
        route_id="openzyme.workspace.git-lfs",
    )
    intent, outcome = WorkspacePublicationCoordinator(
        reader=runtime.store,
        authority=runtime.authority,
        publications=runtime.publications,
        controlled_operations=runtime.controlled_operations,
        revision_backend=backend,
        manifest_policy=_ManifestPolicy(),
    ).prepare_and_publish(
        context=context,
        request=WorkspacePublicationRequest(
            idempotency_key="product-publication-1",
            workspace_id=workspace_id,
            workspace_generation=1,
            expected_head_commit=commit,
            expected_tree=tree,
            declared_base_commit=base,
            checkpoint_id=checkpoint.checkpoint_id,
            repository_binding_version=1,
        ),
        created_at="2026-08-22T00:00:00+00:00",
    )
    assert outcome.state.value == "materialized"
    content_digests = {
        entry.path: canonical_sha256_digest({"content": entry.path})
        for entry in backend.manifest.entries
    }
    for index, entry in enumerate(backend.manifest.entries, start=1):
        receipt = RevisionPathVerificationReceipt.create(
            ref_id=f"revision-path-product-{index}",
            publication_id=intent.publication_id,
            repository_binding_id=binding.binding_id,
            repository_binding_version=binding.binding_version,
            commit=commit,
            tree=tree,
            path=entry.path,
            object_id=entry.object_id,
            actual_size_bytes=entry.size_bytes,
            actual_content_digest=content_digests[entry.path],
            lfs_oid=entry.lfs_oid,
            lfs_size_bytes=entry.lfs_size_bytes,
            verified_at="2026-08-22T00:00:00+00:00",
        )
        _seed_kernel_record(
            runtime,
            session_id=session_id,
            session_version=session_version,
            actor_id=member_id,
            lease=lease,
            label=f"revision-path-{index}",
            entity_type="revision_path_verification",
            entity_id=receipt.ref_id,
            payload={
                "schema_version": "revision_path_verification_receipt@1",
                **receipt.identity_payload,
                "verification_digest": receipt.verification_digest,
            },
        )
    return intent.publication_id, content_digests


def test_packaged_distribution_exactly_matches_repository_manifest() -> None:
    packaged = load_enzymedesign_composition()
    repository = parse_distribution_composition_toml(
        (ROOT / "distributions/enzymedesign/openzyme-composition.toml").read_bytes()
    )

    assert packaged == repository
    assert "openzyme.standard" not in {
        item.plugin_id for item in packaged.manifest.plugins
    }
    assert "enzymedesign.bio-providers" in packaged.manifest.required_plugin_ids


def test_distribution_selects_exact_plugins_adapters_and_drivers() -> None:
    selected = select_enzymedesign_component_locators()

    assert len(selected.selected) == 30
    assert selected.ignored_component_ids == ()
    assert "enzymedesign.bio-provider-http" in {
        item.component_id for item in selected.selected
    }
    assert "enzymedesign.aox.executor" in {
        item.component_id for item in selected.selected
    }


def test_distribution_builds_exact_active_catalogs_without_live_probes() -> None:
    document = load_enzymedesign_composition()
    activated = activate_enzymedesign_composition()

    assert document.manifest_state is CompositionManifestState.ACTIVE
    assert activated.distribution_id == "enzymedesign"
    assert len(activated.adapters) == 8
    assert len(activated.plugins.activations) == 14
    assert len(activated.drivers) == 8
    assert len(activated.declared_tool_catalog.entries) == 37
    assert {
        entry.contract.tool_name
        for entry in activated.declared_tool_catalog.entries
        if entry.owner_component_id == "openzyme.kernel"
    } == {
        "workspace.status",
        "workspace.fs.read",
        "workspace.fs.list",
        "workspace.fs.mutate",
        "workspace.exec",
    }


def test_hpc_workspace_tool_requires_exact_qualified_remote_helper_fact() -> None:
    composition = activate_enzymedesign_composition()
    extension_registry = ExtensionBundleRegistry.create(
        composition.plugins,
        activation_epoch=1,
    )
    binding = SessionCapabilityBindingRevision.create(
        binding_id="binding-helper-1",
        session_id="session-helper-1",
        revision=1,
        extension_bundle_digest=composition.plugins.extension_bundle_digest,
        route_catalog_digest=composition.route_catalog.catalog_digest,
        inventory_bindings=(
            TargetInventoryBinding(
                target_id="hpc-primary",
                inventory_generation=7,
                inventory_digest=DIGEST,
                qualification_valid_until="2026-09-01T00:00:00+00:00",
            ),
        ),
        created_by_actor_id="operator-helper-1",
        created_at="2026-08-22T00:00:00+00:00",
    )
    lease = AgentAuthorityLease.create(
        lease_id="lease-helper-1",
        session_id=binding.session_id,
        agent_member_id="member-helper-1",
        grants=(
            AuthorityGrant.create(
                grant_id="grant-helper-1",
                scope_id=binding.session_id,
                operations=("hpc.workspace.process.exec",),
                generation=1,
                fence=1,
            ),
        ),
        generation=1,
        fence=1,
        state=AgentAuthorityLeaseState.ACTIVE,
        issued_at="2026-08-22T00:00:00+00:00",
        expires_at="2026-09-01T00:00:00+00:00",
    )

    def snapshot(*, include_helper: bool):
        resources = (
            (
                ResourceCapabilityFact(
                    capability_id="software.openzyme-workspace-runtime",
                    kind=ResourceCapabilityKind.SOFTWARE,
                    target_id="hpc-primary",
                    inventory_generation=7,
                    qualification_digest=DIGEST,
                    environment_digest=DIGEST,
                    inventory_digest=DIGEST,
                    operations=(),
                    version="1.0.0",
                ),
            )
            if include_helper
            else ()
        )
        context = ToolAffordanceContext(
            session_id=binding.session_id,
            agent_member_id=lease.agent_member_id,
            turn_id="turn-helper-1",
            declared_catalog=composition.declared_tool_catalog,
            capability_binding=binding,
            capability_registry=CapabilityRegistry.create(
                extension_bundle=extension_registry,
                binding=binding,
                route_catalog=composition.route_catalog,
                resource_facts=resources,
            ),
            authority_lease=lease,
            workspace_generation=1,
            workspace_ready=True,
            health_observation_digest=DIGEST,
            observed_at="2026-08-22T00:01:00+00:00",
            subject_role="executor",
            task_id="task-helper-1",
            subject_policy_digest=subject_policy_digest(
                session_id=binding.session_id,
                agent_member_id=lease.agent_member_id,
                subject_role="executor",
                task_id="task-helper-1",
                decisions=(),
            ),
        )
        return resolve_tool_affordance_snapshot(
            context,
            snapshot_id=(
                "snapshot-helper-present"
                if include_helper
                else "snapshot-helper-missing"
            ),
            created_at="2026-08-22T00:01:00+00:00",
        )

    absent = next(
        item
        for item in snapshot(include_helper=False).affordances
        if item.tool_name == "hpc.workspace.exec"
    )
    qualified = next(
        item
        for item in snapshot(include_helper=True).affordances
        if item.tool_name == "hpc.workspace.exec"
    )

    assert absent.state is ToolAffordanceState.BLOCKED_QUALIFICATION
    assert absent.blockers[0].code == "software_requirement_unsatisfied"
    assert qualified.state is ToolAffordanceState.AVAILABLE
    assert qualified.route_ids == ("hpc-primary.workspace-runtime",)


def test_enzymedesign_fresh_seed_binds_selected_plugin_schema_and_catalogs() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(
        connection,
        profile=ENZYMEDESIGN_OWNER_SCHEMA_PROFILE,
    )
    install_store_schema_for_offline_migration(connection)
    schema = verify_composite_store_schema_read_only(
        connection,
        owner_schema_profile=ENZYMEDESIGN_OWNER_SCHEMA_PROFILE,
    )
    seed = build_enzymedesign_fresh_install_seed(
        schema_proof=schema,
        installed_wheel_set_digest="sha256:" + "4" * 64,
        host_build_digest="sha256:" + "5" * 64,
        client_build_digest="sha256:" + "6" * 64,
        epoch_id="enzymedesign-fresh-1",
        sequence=1,
        activated_by_actor_id="operator-1",
        activated_at="2026-08-20T00:00:00+00:00",
    )

    proof = seed_fresh_install_composition_offline(connection, seed)

    assert proof.receipt.distribution_id == "enzymedesign"
    assert proof.receipt.owner_schema_profile_id == (
        ENZYMEDESIGN_OWNER_SCHEMA_PROFILE.profile_id
    )
    assert proof.schema.composition is not None
    assert proof.schema.composition.verified_catalog_count == 7
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM scientific_attempt_records"
        ).fetchone()[0]
        == 0
    )

    before = connection.total_changes
    startup = verify_enzymedesign_deployment_startup_read_only(
        connection,
        seed=seed,
        observed_installed_wheel_set_digest="sha256:" + "4" * 64,
        verified_at="2026-08-20T00:01:00+00:00",
    )
    assert startup.gate.active_epoch == seed.activation_epoch
    assert startup.session_composition_proof.verified_session_count == 0
    assert startup.gate.require_active(DeploymentSurface.RUNTIME)
    assert connection.total_changes == before


def test_distribution_owns_aox_workflow_and_finalization_registration() -> None:
    contributions = build_enzymedesign_scientific_contributions()
    contract = contributions.workflow_contract_registry.contracts[0]

    assert (
        contributions.workflow_contract_registry.resolve(
            workflow_id=contract.workflow_id,
            workflow_contract_digest=contract.digest,
        )
        is contract
    )
    assert type(contributions.finalization_handler).__name__ == (
        "AoxScientificDeliverableRequestHandler"
    )


def test_distribution_mounts_every_manifest_declared_runtime_surface_exactly() -> None:
    connection, startup = _activated_startup()
    try:
        mounted = mount_enzymedesign_extension_surfaces(
            startup=startup,
            composition=activate_enzymedesign_composition(),
            surfaces=_runtime_surface_set(),
        )
    finally:
        connection.close()

    assert len(mounted.tools) == 32
    assert len(mounted.capability_routes) == 13
    assert len(mounted.http_routes) == 2
    assert len(mounted.projections) == 5
    assert len(mounted.workers) == 5
    assert len(mounted.finish_validators) == 2
    assert len(mounted.transaction_participants) == 3


def test_distribution_rejects_one_missing_product_route_before_mount() -> None:
    connection, startup = _activated_startup()
    surfaces = _runtime_surface_set()
    incomplete_hmmer = replace(
        surfaces.hmmer,
        capability_routes=surfaces.hmmer.capability_routes[:1],
    )
    try:
        with pytest.raises(KernelContractError) as caught:
            mount_enzymedesign_extension_surfaces(
                startup=startup,
                composition=activate_enzymedesign_composition(),
                surfaces=replace(surfaces, hmmer=incomplete_hmmer),
            )
    finally:
        connection.close()

    assert caught.value.code == "plugin_runtime_surface_incomplete"
    assert caught.value.details["plugin_id"] == "enzymedesign.hmmer"


def test_application_runtime_mounts_exact_product_before_enabling_writer() -> None:
    connection, startup = _activated_startup()
    operational_selection = _operational_selection()
    try:
        runtime = build_enzymedesign_application_runtime(
            connection,
            startup=startup,
            surfaces=_runtime_surface_set(),
            adapter_runtimes=_adapter_runtime_set(operational_selection),
            inventories=_EmptyInventoryRepository(),
            clock=DeterministicClock(datetime(2026, 8, 22, tzinfo=UTC)),
            ids=DeterministicIdGenerator(),
            bootstrap_authority=_BootstrapAuthority(),
            operational_selection=operational_selection,
        )
        app = build_enzymedesign_v2_host_app(
            runtime=runtime,
            security_policy=HostSecurityPolicy.from_settings(None),
        )
        bootstrap_receipt = runtime.gateway.bootstrap(
            HostV2SessionBootstrapInvocation(
                session_id="session-product-runtime-1",
                actor_id="operator-1",
                idempotency_key="bootstrap-product-runtime-1",
                correlation_id="correlation-product-runtime-1",
                payload={
                    "session_id": "session-product-runtime-1",
                    "project_id": "project-product-runtime-1",
                    "title": "Product runtime",
                    "objective": "Prove exact EnzymeDesign composition",
                },
            )
        )
        stored_session = runtime.store.read(
            entity_type="session",
            entity_id="session-product-runtime-1",
        )
        root_leases = runtime.store.list_for_session(
            entity_type="agent_authority_lease",
            session_id="session-product-runtime-1",
            max_items=4,
        )
        missing_execution = runtime.compute_executions.get(
            "session-product-runtime-1",
            "execution-not-created",
        )
    finally:
        connection.close()

    assert runtime.store.provider_id == "openzyme.store.sqlite"
    assert len(runtime.adapter_runtimes.bindings) == 8
    assert len(runtime.mounted_surfaces.tools) == 32
    assert len(runtime.mounted_tools.tools) == 37
    assert runtime.proof_digest.startswith("sha256:")
    assert bootstrap_receipt.mutation_applied is True
    assert stored_session is not None
    assert len(root_leases) == 1
    assert {
        "extension.state.mutate",
        "external_compute",
    }.issubset(set(root_leases[0].payload["grants"][0]["operations"]))
    assert missing_execution is None
    assert runtime.slurm_scheduler.ledger is runtime.scheduler_occurrence_ledger
    assert app.state.enzymedesign_runtime is runtime
    mounted_paths = {route.path for route in app.routes}
    assert {
        contribution.path for _, contribution in runtime.mounted_surfaces.http_routes
    }.issubset(mounted_paths)


def test_application_runtime_rejects_missing_adapter_before_writer_enablement() -> None:
    connection, startup = _activated_startup()
    operational_selection = _operational_selection()
    adapters = _adapter_runtime_set(operational_selection)
    before = connection.total_changes
    try:
        with pytest.raises(KernelContractError) as caught:
            build_enzymedesign_application_runtime(
                connection,
                startup=startup,
                surfaces=_runtime_surface_set(),
                adapter_runtimes=replace(adapters, bindings=adapters.bindings[:-1]),
                inventories=_EmptyInventoryRepository(),
                clock=DeterministicClock(datetime(2026, 8, 22, tzinfo=UTC)),
                ids=DeterministicIdGenerator(),
                bootstrap_authority=_BootstrapAuthority(),
                operational_selection=operational_selection,
            )
        assert connection.total_changes == before
    finally:
        connection.close()

    assert caught.value.code == "enzymedesign_adapter_runtime_set_incomplete"


@pytest.mark.parametrize(
    ("product", "tool_name", "route_id", "driver_id", "arguments", "expected_argv"),
    (
        (
            "hmmer",
            "enzymedesign.hmmer.search",
            "enzymedesign.hmmer.hpc-primary@1",
            "enzymedesign.hmmer.hpc",
            {
                "workload_id": "workload-hmmer-formal",
                "cwd": "analysis/hmmer",
                "resource_policy_digest": DIGEST,
                "environment_policy_digest": DIGEST,
                "result_root": "results/hmmer",
                "output_path": "results/hmmer/hits.tbl",
                "inputs": [
                    {
                        "revision_id": "revision-formal-1",
                        "commit": "a" * 40,
                        "tree": "b" * 40,
                        "path": "inputs/model.hmm",
                        "content_digest": DIGEST,
                    },
                    {
                        "revision_id": "revision-formal-1",
                        "commit": "a" * 40,
                        "tree": "b" * 40,
                        "path": "inputs/proteins.fasta",
                        "content_digest": DIGEST,
                    },
                ],
            },
            (
                "hmmsearch",
                "--noali",
                "--tblout",
                "results/hmmer/hits.tbl",
                "inputs/model.hmm",
                "inputs/proteins.fasta",
            ),
        ),
        (
            "vina",
            "enzymedesign.vina.dock",
            "enzymedesign.vina.hpc-primary@1",
            "enzymedesign.vina.hpc",
            {
                "workload_id": "workload-vina-formal",
                "cwd": "analysis/vina",
                "resource_policy_digest": DIGEST,
                "environment_policy_digest": DIGEST,
                "result_root": "results/vina",
                "poses_path": "results/vina/poses.pdbqt",
                "score_path": "results/vina/vina.log",
                "inputs": [
                    {
                        "revision_id": "revision-formal-1",
                        "commit": "a" * 40,
                        "tree": "b" * 40,
                        "path": "inputs/receptor.pdbqt",
                        "content_digest": DIGEST,
                    },
                    {
                        "revision_id": "revision-formal-1",
                        "commit": "a" * 40,
                        "tree": "b" * 40,
                        "path": "inputs/ligand.pdbqt",
                        "content_digest": DIGEST,
                    },
                    {
                        "revision_id": "revision-formal-1",
                        "commit": "a" * 40,
                        "tree": "b" * 40,
                        "path": "inputs/vina.conf",
                        "content_digest": DIGEST,
                    },
                ],
            },
            (
                "vina",
                "--receptor",
                "inputs/receptor.pdbqt",
                "--ligand",
                "inputs/ligand.pdbqt",
                "--config",
                "inputs/vina.conf",
                "--out",
                "results/vina/poses.pdbqt",
                "--log",
                "results/vina/vina.log",
            ),
        ),
    ),
)
def test_formal_product_tools_compile_driver_and_enter_compute_lifecycle(
    product,
    tool_name,
    route_id,
    driver_id,
    arguments,
    expected_argv,
) -> None:
    runner = _DeclaredFormalRunnerPort()
    operations = _FormalControlledOperations()
    application = build_enzymedesign_formal_compute_application(
        compute=ComputeExecutionApplicationService(
            repository=InMemoryComputeExecutionRepository(),
            admission_verifier=_FormalAdmissionVerifier(),
            controlled_operations=operations,
            route=runner,
        ),
        source_bindings=_FormalSourceBindings(),
        clock=DeterministicClock(datetime(2026, 8, 22, tzinfo=UTC)),
    )
    surfaces = (
        build_hmmer_plugin_runtime_surfaces(
            application=application,
            route_application=_NoopApplication(),
        )
        if product == "hmmer"
        else build_vina_plugin_runtime_surfaces(
            application=application,
            route_application=_NoopApplication(),
        )
    )
    runtime = next(
        item for item in surfaces.tools if item.contract.tool_name == tool_name
    )
    invocation = ToolInvocation(
        call_id=f"call-{product}-formal",
        tool_name=tool_name,
        arguments={
            **arguments,
            "route_id": route_id,
            "affordance_snapshot_digest": DIGEST,
        },
        session_id="session-formal-1",
        agent_member_id="member-formal-1",
        task_id="task-formal-1",
        route_id=route_id,
        affordance_snapshot_digest=DIGEST,
    )
    result = runtime.invoke_admitted(
        invocation,
        ToolDispatchBinding(
            tool_name=tool_name,
            tool_contract_digest=runtime.contract.contract_digest,
            affordance_snapshot_digest=DIGEST,
            capability_binding_digest=DIGEST,
            extension_bundle_digest=DIGEST,
            authority_lease_id="lease-formal-1",
            authority_lease_digest=DIGEST,
            authority_generation=2,
            authority_fence=3,
            workspace_generation=1,
            route_id=route_id,
            route_digest=DIGEST,
            provider_component_id=f"enzymedesign.{product}",
            driver_id=driver_id,
            target_id="hpc-primary",
            inventory_generation=7,
            inventory_digest=DIGEST,
            qualification_digest=DIGEST,
            capability_proof_digest=DIGEST,
        ),
    )

    assert result.ok is True
    assert result.payload["formal_compute_requested"] is True
    assert result.payload["raw_shell"] is False
    assert result.payload["fallback_performed"] is False
    assert result.payload["task_finished"] is False
    assert result.payload["execution_id"].startswith("execution-")
    assert len(runner.requests) == 1
    assert tuple(runner.requests[0].workload.argv) == expected_argv
    assert runner.requests[0].route.route_id == route_id
    assert operations.operations == [
        ControlledOperationCommandKind.ADMIT,
        ControlledOperationCommandKind.OBSERVE,
    ]


def test_real_product_composition_runs_hmmer_and_vina_through_one_pinned_graph() -> None:
    """Qualify the real non-live product graph with only declared I/O Ports faked."""

    connection, startup = _activated_startup()
    inventory_repository, inventory = _publish_product_inventory(connection)
    manifest = WorkspacePublicationManifest.create(
        tuple(
            PublicationManifestEntry(
                path=path,
                mode="100644",
                object_kind=PublicationManifestObjectKind.BLOB,
                object_id=f"{index:x}" * 40,
                size_bytes=16 + index,
            )
            for index, path in enumerate(
                (
                    "inputs/model.hmm",
                    "inputs/proteins.fasta",
                    "inputs/receptor.pdbqt",
                    "inputs/ligand.pdbqt",
                    "inputs/vina.conf",
                ),
                start=1,
            )
        )
    )
    revision_backend = _ProductRevisionBackend(manifest)
    runner = _ProductFormalRunnerPort()
    clock = DeterministicClock(datetime(2026, 8, 22, tzinfo=UTC))
    formal_binding = EnzymeDesignFormalComputeApplicationBinding(
        route=ExactComputeRouteRouter(
            {
                "enzymedesign.hmmer.hpc-primary@1": runner,
                "enzymedesign.vina.hpc-primary@1": runner,
            }
        ),
        clock=clock,
    )
    science_reader = _AcceptedScienceEvidenceReader()
    operational_selection = _operational_selection(
        revision_backend=revision_backend
    )
    runtime = build_enzymedesign_application_runtime(
        connection,
        startup=startup,
        surfaces=_runtime_surface_set(
            formal_application=formal_binding,
            science_evidence_reader=science_reader,
        ),
        adapter_runtimes=_adapter_runtime_set(operational_selection),
        inventories=inventory_repository,
        clock=clock,
        ids=DeterministicIdGenerator(),
        bootstrap_authority=_BootstrapAuthority(),
        operational_selection=operational_selection,
        application_bindings=(formal_binding,),
    )
    app = build_enzymedesign_v2_host_app(
        runtime=runtime,
        security_policy=HostSecurityPolicy.from_settings(None),
    )

    async def bootstrap_through_generic_host():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://enzymedesign.test",
        ) as client:
            return await client.post(
                "/v3/sessions",
                headers={
                    "Accept": FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
                    "OpenZyme-Workspace-Contract": "file_workspace_public@2",
                    "OpenZyme-Release-Digest": (
                        runtime.workspace_surface.release.release_digest
                    ),
                    "OpenZyme-Public-Contract-Digest": (
                        FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
                    ),
                    "Idempotency-Key": "bootstrap-product-cross-layer-1",
                    "X-Request-Id": "request-product-cross-layer-1",
                    "Content-Type": "application/json",
                },
                json={
                    "session_id": "session-product-cross-layer-1",
                    "project_id": "project-product-cross-layer-1",
                    "title": "EnzymeDesign product qualification",
                    "objective": "Run exact formal HMMER and Vina paths",
                },
            )

    response = asyncio.run(bootstrap_through_generic_host())
    assert response.status_code == 200, response.text
    session_id = "session-product-cross-layer-1"
    member_record = runtime.store.list_for_session(
        entity_type="agent_member",
        session_id=session_id,
        max_items=4,
    )[0]
    member_id = str(member_record.payload["agent_member_id"])
    lease_record = runtime.store.list_for_session(
        entity_type="agent_authority_lease",
        session_id=session_id,
        max_items=4,
    )[0]
    lease = AgentAuthorityLease.from_dict(dict(lease_record.payload))
    initial_binding = SessionCapabilityBindingRevision.from_dict(
        dict(
            runtime.store.list_for_session(
                entity_type="session_capability_binding_revision",
                session_id=session_id,
                max_items=4,
            )[0].payload
        )
    )
    runtime.coordination.collaboration.execute(
        CollaborationApplicationCommand(
            context=KernelCommandContext(
                command_id="command-product-task-create",
                session_id=session_id,
                actor_id=member_id,
                owner_plugin_id="openzyme.kernel",
                authority_lease_id=lease.lease_id,
                authority_generation=lease.generation,
                authority_fence=lease.fence,
                expected_session_version=1,
                extension_bundle_digest=initial_binding.extension_bundle_digest,
                capability_binding_digest=initial_binding.binding_digest,
                idempotency_key="product-task-create",
                correlation_id="correlation-product-task-create",
            ),
            operation=CollaborationCommandKind.CREATE_TASK,
            entity_id="task-product-cross-layer-1",
            payload={
                "subject": "Run formal product tools",
                "description": "Qualify HMMER and Vina without implicit completion",
                "owner_actor_id": member_id,
                "kind": "scientific",
                "finish_validator_ids": [SCIENCE_FINISH_VALIDATOR_ID],
            },
        )
    )
    binding = SessionCapabilityBindingRevision.create(
        binding_id="binding-product-cross-layer-2",
        session_id=session_id,
        revision=2,
        extension_bundle_digest=runtime.composition.plugins.extension_bundle_digest,
        route_catalog_digest=runtime.composition.route_catalog.catalog_digest,
        inventory_bindings=(
            TargetInventoryBinding(
                target_id=inventory.target_id,
                inventory_generation=inventory.generation,
                inventory_digest=inventory.inventory_digest,
                qualification_valid_until=inventory.valid_until,
            ),
        ),
        created_by_actor_id="operator-1",
        created_at="2026-08-22T00:00:00+00:00",
    )
    _seed_kernel_record(
        runtime,
        session_id=session_id,
        session_version=2,
        actor_id=member_id,
        lease=lease,
        label="capability-binding-2",
        entity_type="session_capability_binding_revision",
        entity_id=binding.binding_id,
        payload=binding.to_dict(),
    )
    publication_id, content_digests = _seed_product_source(
        runtime,
        session_id=session_id,
        session_version=2,
        member_id=member_id,
        lease=lease,
        backend=revision_backend,
    )
    stored_path_facts = {
        (
            item.publication_id,
            item.path,
            str(item.actual_content_digest),
        )
        for item in SQLiteRevisionPathVerificationQuery(
            connection
        ).list_for_publication(
            publication_id,
            max_items=16,
        )
    }
    assert stored_path_facts == {
        (publication_id, path, digest) for path, digest in content_digests.items()
    }

    registry = runtime.capability_registries.resolve(binding)
    affordance_context = ToolAffordanceContext(
        session_id=session_id,
        agent_member_id=member_id,
        turn_id="turn-product-cross-layer-1",
        declared_catalog=runtime.composition.declared_tool_catalog,
        capability_binding=binding,
        capability_registry=registry,
        authority_lease=lease,
        workspace_generation=1,
        workspace_ready=True,
        health_observation_digest=canonical_sha256_digest(
            {"health": "product-cross-layer-ready"}
        ),
        observed_at="2026-08-22T00:00:00+00:00",
        subject_role="master",
        task_id="task-product-cross-layer-1",
        subject_policy_digest=subject_policy_digest(
            session_id=session_id,
            agent_member_id=member_id,
            subject_role="master",
            task_id="task-product-cross-layer-1",
            decisions=(),
        ),
    )
    snapshot = resolve_tool_affordance_snapshot(
        affordance_context,
        snapshot_id="snapshot-product-cross-layer-1",
        created_at="2026-08-22T00:00:00+00:00",
    )
    affordances = {item.tool_name: item for item in snapshot.affordances}
    assert affordances["enzymedesign.hmmer.search"].state is ToolAffordanceState.AVAILABLE
    assert affordances["enzymedesign.vina.dock"].state is ToolAffordanceState.AVAILABLE
    scope = RuntimeToolScope(
        command_id="runtime-command-product-cross-layer-1",
        catalog=runtime.composition.declared_tool_catalog,
        snapshot=snapshot,
        current_context=affordance_context,
    )
    gateway = MountedRuntimeCapabilityGateway(
        scopes=_StaticRuntimeScopeProvider(scope),
        runtimes=runtime.mounted_tools.tools,
    )
    tool_cases = (
        (
            "hmmer",
            "enzymedesign.hmmer.search",
            "enzymedesign.hmmer.hpc-primary@1",
            {
                "workload_id": "workload-product-hmmer",
                "cwd": "analysis/hmmer",
                "resource_policy_digest": DIGEST,
                "environment_policy_digest": DIGEST,
                "result_root": "results/hmmer",
                "output_path": "results/hmmer/hits.tbl",
                "inputs": [
                    {
                        "revision_id": publication_id,
                        "commit": "a" * 40,
                        "tree": "b" * 40,
                        "path": path,
                        "content_digest": content_digests[path],
                    }
                    for path in ("inputs/model.hmm", "inputs/proteins.fasta")
                ],
            },
        ),
        (
            "vina",
            "enzymedesign.vina.dock",
            "enzymedesign.vina.hpc-primary@1",
            {
                "workload_id": "workload-product-vina",
                "cwd": "analysis/vina",
                "resource_policy_digest": DIGEST,
                "environment_policy_digest": DIGEST,
                "result_root": "results/vina",
                "poses_path": "results/vina/poses.pdbqt",
                "score_path": "results/vina/vina.log",
                "inputs": [
                    {
                        "revision_id": publication_id,
                        "commit": "a" * 40,
                        "tree": "b" * 40,
                        "path": path,
                        "content_digest": content_digests[path],
                    }
                    for path in (
                        "inputs/receptor.pdbqt",
                        "inputs/ligand.pdbqt",
                        "inputs/vina.conf",
                    )
                ],
            },
        ),
    )
    execution_ids = []
    for product, tool_name, route_id, arguments in tool_cases:
        call_id = f"call-product-{product}"
        result = gateway.invoke(
            command_id=scope.command_id,
            request=RuntimeToolRequest(
                request_id=f"request-product-{product}",
                invocation=ToolInvocation(
                    call_id=call_id,
                    tool_name=tool_name,
                    arguments={
                        **arguments,
                        "route_id": route_id,
                        "affordance_snapshot_digest": snapshot.snapshot_digest,
                    },
                    session_id=session_id,
                    agent_member_id=member_id,
                    task_id="task-product-cross-layer-1",
                    route_id=route_id,
                    affordance_snapshot_digest=snapshot.snapshot_digest,
                ),
                affordance_snapshot_digest=snapshot.snapshot_digest,
            ),
        )
        assert result.ok is True, (
            result.summary,
            result.error_code,
            result.payload,
        )
        execution_id = str(result.payload["execution_id"])
        execution_ids.append(execution_id)
        terminal = formal_binding.observe(
            context=KernelCommandContext(
                command_id=f"command-observe-product-{product}",
                session_id=session_id,
                actor_id=member_id,
                owner_plugin_id="openzyme.compute",
                authority_lease_id=lease.lease_id,
                authority_generation=lease.generation,
                authority_fence=lease.fence,
                expected_session_version=2,
                extension_bundle_digest=binding.extension_bundle_digest,
                capability_binding_digest=binding.binding_digest,
                idempotency_key=f"formal-{call_id}",
                correlation_id=f"formal-compute-{call_id}",
                workspace_generation=1,
                route_id=route_id,
            ),
            execution_id=execution_id,
        )
        assert terminal.result is not None
        assert terminal.result.state == "succeeded"
        assert terminal.safe_projection()["task_finished"] is False

    task_record = runtime.store.read(
        entity_type="task",
        entity_id="task-product-cross-layer-1",
    )
    assert task_record is not None
    evidence = EvidenceRef(
        evidence_id="evidence-product-science-closure-1",
        evidence_kind=EvidenceKind.EXTENSION,
        contract_id=SCIENCE_CLOSURE_EVIDENCE_CONTRACT_ID,
        owner_component_id="openzyme.science",
        project_id="project-product-cross-layer-1",
        session_id=session_id,
        task_id="task-product-cross-layer-1",
        subject_ref="closure-product-cross-layer-1",
        subject_digest=canonical_sha256_digest(
            {"closure": "product-cross-layer"}
        ),
        attributes={"execution_ids": execution_ids},
    )
    validation = runtime.finish_validators.validate(
        context=KernelQueryContext(
            session_id=session_id,
            actor_id=member_id,
            owner_plugin_id="openzyme.kernel",
            authority_lease_id=lease.lease_id,
            extension_bundle_digest=binding.extension_bundle_digest,
            capability_binding_digest=binding.binding_digest,
            correlation_id="correlation-product-science-validation",
        ),
        task=KernelEntitySnapshot(
            entity=KernelEntityRef(
                entity_kind="task",
                entity_id=task_record.entity_id,
                state_version=task_record.state_version,
                entity_digest=task_record.record_digest,
            ),
            payload=task_record.payload,
        ),
        evidence_refs=(evidence,),
        required_validator_ids=(SCIENCE_FINISH_VALIDATOR_ID,),
    )
    continuations = runtime.store.list_for_session(
        entity_type="continuation",
        session_id=session_id,
        max_items=8,
    )
    task_after = runtime.store.read(
        entity_type="task",
        entity_id="task-product-cross-layer-1",
    )

    assert runtime.application_binding_ids == (
        "enzymedesign.formal-compute-application@1",
    )
    assert formal_binding.is_bound is True
    assert len(runner.requests) == 2
    assert runner.observe_calls == 2
    assert {request.route.route_id for request in runner.requests} == {
        "enzymedesign.hmmer.hpc-primary@1",
        "enzymedesign.vina.hpc-primary@1",
    }
    assert revision_backend.dispatch_count == 1
    assert len(continuations) == 2
    assert {
        item.payload["recipient_actor_id"] for item in continuations
    } == {member_id}
    assert validation.accepted is True
    assert len(science_reader.calls) == 1
    assert task_after is not None
    assert task_after.payload["status"] == "todo"
    assert task_after.state_version == task_record.state_version
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
