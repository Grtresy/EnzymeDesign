from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from typing import Protocol

from enzymedesign_hmmer import HMMER_BUILD_TOOL
from enzymedesign_hmmer import HMMER_DRIVER_REQUEST_CONTRACT_DIGEST
from enzymedesign_hmmer import HMMER_PLUGIN_ID
from enzymedesign_hmmer import HMMER_SEARCH_TOOL
from enzymedesign_hmmer import HmmerDriver
from enzymedesign_hmmer import locate_hpc_driver_manifest as locate_hmmer_hpc_driver
from enzymedesign_hmmer import locate_local_driver_manifest as locate_hmmer_local_driver
from enzymedesign_vina import VINA_DOCK_TOOL
from enzymedesign_vina import VINA_DRIVER_REQUEST_CONTRACT_DIGEST
from enzymedesign_vina import VINA_PLUGIN_ID
from enzymedesign_vina import VinaDriver
from enzymedesign_vina import locate_hpc_driver_manifest as locate_vina_hpc_driver
from enzymedesign_vina import locate_local_driver_manifest as locate_vina_local_driver
from openzyme_compute import ComputeExecutionApplicationService
from openzyme_compute import ComputeAdmissionProof
from openzyme_compute import ComputeExecutionRepository
from openzyme_compute import ComputeExecutionRequest
from openzyme_compute import ComputeRouteOutcome
from openzyme_compute import ComputeRoutePort
from openzyme_contracts import ClockPort
from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import KernelRecordQueryPort
from openzyme_contracts import PublishedRevision
from openzyme_contracts import RevisionPathVerificationReceipt
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import ToolInvocation
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import WorkspaceGenerationStatus
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import json_compatible
from openzyme_contracts.identity import JsonValue
from openzyme_execution_contracts import ExecutionRouteIdentity
from openzyme_execution_contracts import ExecutionWorkloadSpec
from openzyme_extension_spi import DriverInvocationRequest
from openzyme_extension_spi import ContinuationApplicationService
from openzyme_extension_spi import ControlledOperationApplicationService
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import SubordinateDriver
from openzyme_extension_spi import ToolDispatchBinding
from openzyme_extension_spi import read_located_component_manifest


@dataclass(frozen=True, slots=True)
class FormalComputeSourceBinding:
    """Canonical immutable source/workspace facts for one formal invocation."""

    session_version: int
    workspace_id: str
    workspace_generation: int
    source_revision_id: str
    source_ref: str
    source_commit: str
    source_tree: str
    lfs_closure_manifest_digest: str
    clean_observation_digest: str


class FormalComputeSourceBindingResolver(Protocol):
    """Resolve canonical facts without accepting caller-supplied private locators."""

    def resolve(
        self,
        *,
        invocation: ToolInvocation,
        dispatch: ToolDispatchBinding,
        workload: ExecutionWorkloadSpec,
    ) -> FormalComputeSourceBinding: ...


class FormalComputeCapabilityRegistryResolver(Protocol):
    """Resolve the exact Session-pinned capability graph without live probing."""

    def resolve(self, binding: SessionCapabilityBindingRevision): ...  # noqa: ANN201


class FormalComputeRevisionPathVerificationQuery(Protocol):
    def list_for_publication(
        self,
        publication_id: str,
        *,
        max_items: int = 1_000,
    ) -> tuple[RevisionPathVerificationReceipt, ...]: ...


@dataclass(frozen=True, slots=True)
class CanonicalFormalComputeSourceBindingResolver:
    """Resolve formal source facts only from immutable Kernel records.

    The tool payload may name a revision/path, but it cannot manufacture the
    publication, clean workspace identity, or verified content digest.  Every
    input must have one canonical ``RevisionPathVerificationReceipt``.
    """

    records: KernelRecordQueryPort
    path_verifications: FormalComputeRevisionPathVerificationQuery

    def resolve(
        self,
        *,
        invocation: ToolInvocation,
        dispatch: ToolDispatchBinding,
        workload: ExecutionWorkloadSpec,
    ) -> FormalComputeSourceBinding:
        session = self.records.read(entity_type="session", entity_id=invocation.session_id)
        if session is None:
            raise ValueError("formal Compute Session is absent")
        revision_ids = {item.revision_id for item in workload.inputs}
        if len(revision_ids) != 1:
            raise ValueError("formal Compute inputs must share one PublishedRevision")
        revision_id = next(iter(revision_ids))
        revision_record = self.records.read(
            entity_type="published_revision",
            entity_id=revision_id,
        )
        try:
            revision = (
                None
                if revision_record is None
                else PublishedRevision.from_dict(dict(revision_record.payload))
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("formal Compute PublishedRevision is invalid") from exc
        if (
            revision is None
            or revision.session_id != invocation.session_id
            or any(
                item.commit != revision.commit or item.tree != revision.tree
                for item in workload.inputs
            )
        ):
            raise ValueError("formal Compute source revision is absent or stale")
        manifest_paths = {item.path for item in revision.manifest.entries}
        if any(item.path not in manifest_paths for item in workload.inputs):
            raise ValueError("formal Compute source path is absent from the published tree")

        verifications = self.path_verifications.list_for_publication(
            revision.publication_id,
            max_items=1_000,
        )
        for source_input in workload.inputs:
            matches = tuple(
                item
                for item in verifications
                if item.publication_id == revision.publication_id
                and item.commit == revision.commit
                and item.tree == revision.tree
                and item.path == source_input.path
                and item.actual_content_digest == source_input.content_digest
            )
            if len(matches) != 1:
                raise ValueError(
                    "formal Compute source requires one exact verified revision path"
                )

        workspace_records = self.records.list_for_session(
            entity_type="workspace_runtime_binding",
            session_id=invocation.session_id,
            max_items=64,
        )
        try:
            workspaces = tuple(
                WorkspaceRuntimeBinding.from_dict(dict(item.payload))
                for item in workspace_records
                if item.payload.get("owner_member_id") == invocation.agent_member_id
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("formal Compute workspace binding is invalid") from exc
        if len(workspaces) != 1:
            raise ValueError("formal Compute owner requires one exact workspace")
        workspace = workspaces[0]
        generation_record = self.records.read(
            entity_type="workspace_generation",
            entity_id=workspace.workspace_id,
        )
        try:
            generation = (
                None
                if generation_record is None
                else WorkspaceGeneration.from_dict(dict(generation_record.payload))
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("formal Compute workspace generation is invalid") from exc
        if (
            generation is None
            or generation.status is not WorkspaceGenerationStatus.READY
            or generation.generation != workspace.generation
            or generation.root_identity_digest != workspace.root_identity_digest
            or workspace.generation != dispatch.workspace_generation
        ):
            raise ValueError("formal Compute workspace generation is not exactly ready")
        lfs_closure_digest = canonical_sha256_digest(
            {
                "schema_version": "openzyme_published_lfs_closure@1",
                "publication_id": revision.publication_id,
                "entries": [
                    {
                        "path": item.path,
                        "lfs_oid": item.lfs_oid,
                        "lfs_size_bytes": item.lfs_size_bytes,
                    }
                    for item in revision.manifest.entries
                    if item.lfs_oid is not None
                ],
            }
        )
        return FormalComputeSourceBinding(
            session_version=session.state_version,
            workspace_id=workspace.workspace_id,
            workspace_generation=workspace.generation,
            source_revision_id=revision.publication_id,
            source_ref=revision.publication_ref,
            source_commit=revision.commit,
            source_tree=revision.tree,
            lfs_closure_manifest_digest=lfs_closure_digest,
            clean_observation_digest=revision.revision_digest,
        )


@dataclass(frozen=True, slots=True)
class CanonicalFormalComputeAdmissionVerifier:
    """Revalidate authority, workspace, revision and adopted route at submit."""

    records: KernelRecordQueryPort
    capability_registries: FormalComputeCapabilityRegistryResolver
    clock: ClockPort

    def verify(
        self,
        *,
        context: KernelCommandContext,
        request: ComputeExecutionRequest,
    ) -> ComputeAdmissionProof:
        lease_record = self.records.read(
            entity_type="agent_authority_lease",
            entity_id=request.authority_lease_id,
        )
        try:
            lease = (
                None
                if lease_record is None
                else AgentAuthorityLease.from_dict(dict(lease_record.payload))
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("formal Compute authority lease is invalid") from exc
        if (
            lease is None
            or lease.session_id != request.session_id
            or lease.agent_member_id != request.owner_agent_member_id
            or lease.generation != request.authority_generation
            or lease.fence != request.authority_fence
            or not (
                lease.allows("external_compute", scope_id=request.workspace_id)
                or lease.allows("external_compute", scope_id=request.session_id)
            )
        ):
            raise ValueError("formal Compute authority is absent or stale")
        if lease.expires_at is not None:
            expires_at = datetime.fromisoformat(lease.expires_at.replace("Z", "+00:00"))
            now = datetime.fromisoformat(self.clock.now_iso().replace("Z", "+00:00"))
            if expires_at <= now:
                raise ValueError("formal Compute authority lease expired")

        revision_record = self.records.read(
            entity_type="published_revision",
            entity_id=request.source_revision_id,
        )
        workspace_record = self.records.read(
            entity_type="workspace_generation",
            entity_id=request.workspace_id,
        )
        if revision_record is None or workspace_record is None:
            raise ValueError("formal Compute canonical source or workspace is absent")
        revision = PublishedRevision.from_dict(dict(revision_record.payload))
        workspace = WorkspaceGeneration.from_dict(dict(workspace_record.payload))
        if (
            revision.session_id != request.session_id
            or revision.commit != request.source_commit
            or revision.tree != request.source_tree
            or revision.revision_digest != request.clean_observation_digest
            or workspace.session_id != request.session_id
            or workspace.owner_member_id != request.owner_agent_member_id
            or workspace.generation != request.workspace_generation
            or workspace.status is not WorkspaceGenerationStatus.READY
        ):
            raise ValueError("formal Compute canonical source or workspace changed")

        binding_records = self.records.list_for_session(
            entity_type="session_capability_binding_revision",
            session_id=request.session_id,
            max_items=64,
        )
        bindings = tuple(
            SessionCapabilityBindingRevision.from_dict(dict(item.payload))
            for item in binding_records
        )
        if not bindings:
            raise ValueError("formal Compute Session capability binding is absent")
        latest_revision = max(item.revision for item in bindings)
        latest = tuple(item for item in bindings if item.revision == latest_revision)
        if len(latest) != 1 or latest[0].binding_digest != context.capability_binding_digest:
            raise ValueError("formal Compute Session capability binding is stale")
        registry = self.capability_registries.resolve(latest[0])
        routes = tuple(
            route
            for route in registry.route_refs
            if route.route_id == request.route.route_id
        )
        if len(routes) != 1:
            raise ValueError("formal Compute route is absent or ambiguous")
        route = routes[0]
        if (
            route.target_id != request.route.target_id
            or route.provider_component_id != request.route.provider_id
            or route.inventory_generation != request.route.inventory_generation
            or route.inventory_digest != request.route.inventory_digest
            or route.capability_proof_digest != request.route.qualification_digest
        ):
            raise ValueError("formal Compute route proof changed before dispatch")
        proof_digest = canonical_sha256_digest(
            {
                "schema_version": "enzymedesign_formal_compute_admission_proof@1",
                "request_digest": request.request_digest,
                "authority_lease_digest": lease.lease_digest,
                "capability_binding_digest": latest[0].binding_digest,
                "route_digest": route.route_digest,
                "workspace_state_version": workspace.state_version,
                "published_revision_digest": revision.revision_digest,
            }
        )
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
            capability_binding_digest=latest[0].binding_digest,
            proof_digest=proof_digest,
        )


@dataclass(frozen=True, slots=True)
class ExactComputeRouteRouter:
    """Route a Compute occurrence only to its explicitly selected external Port."""

    routes: Mapping[str, ComputeRoutePort]

    def __post_init__(self) -> None:
        if not self.routes:
            raise ValueError("formal Compute route router cannot be empty")
        if any(not route_id or route is None for route_id, route in self.routes.items()):
            raise ValueError("formal Compute routes require exact IDs and Ports")

    def dispatch(self, request: ComputeExecutionRequest) -> ComputeRouteOutcome:
        return self._route(request).dispatch(request)

    def observe(
        self,
        request: ComputeExecutionRequest,
        provider_handle: str,
    ) -> ComputeRouteOutcome:
        return self._route(request).observe(request, provider_handle)

    def cancel(
        self,
        request: ComputeExecutionRequest,
        provider_handle: str,
    ) -> ComputeRouteOutcome:
        return self._route(request).cancel(request, provider_handle)

    def _route(self, request: ComputeExecutionRequest) -> ComputeRoutePort:
        route = self.routes.get(request.route.route_id)
        if route is None:
            raise ValueError("formal Compute route is not mounted; fallback is forbidden")
        return route


@dataclass(frozen=True, slots=True)
class FormalComputeDriverBinding:
    driver: SubordinateDriver
    request_contract_digest: str


@dataclass(slots=True)
class EnzymeDesignFormalComputeToolApplication:
    """Product bridge from an admitted scientific tool to Compute lifecycle.

    Drivers only compile the typed workload.  The injected Compute service owns
    admission, ControlledOperation truth, the selected runner Port and settlement.
    This bridge never imports an SSH, Slurm or HPC implementation and never chooses
    a replacement route.
    """

    compute: ComputeExecutionApplicationService
    source_bindings: FormalComputeSourceBindingResolver
    clock: ClockPort
    drivers: Mapping[str, FormalComputeDriverBinding]
    maximum_duration: timedelta = timedelta(hours=4)

    def request(
        self,
        *,
        invocation: ToolInvocation,
        dispatch: ToolDispatchBinding,
    ) -> Mapping[str, JsonValue]:
        self._validate_dispatch(invocation, dispatch)
        assert dispatch.driver_id is not None
        binding = self.drivers.get(dispatch.driver_id)
        if binding is None:
            raise ValueError("formal Compute route names an unmounted subordinate Driver")
        owning_plugin_id, payload = _driver_payload(invocation)
        if binding.driver.manifest.owning_plugin_id != owning_plugin_id:
            raise ValueError("formal Compute Driver belongs to another Product Plugin")
        compiled = binding.driver.compile(
            DriverInvocationRequest(
                driver_id=dispatch.driver_id,
                owning_plugin_id=owning_plugin_id,
                route_id=dispatch.route_id or "",
                tool_name=invocation.tool_name,
                tool_contract_digest=dispatch.tool_contract_digest,
                request_contract_digest=binding.request_contract_digest,
                payload=payload,
            )
        )
        workload = ExecutionWorkloadSpec.from_dict(json_compatible(compiled.workload))
        source = self.source_bindings.resolve(
            invocation=invocation,
            dispatch=dispatch,
            workload=workload,
        )
        if source.workspace_generation != dispatch.workspace_generation:
            raise ValueError("formal Compute workspace generation changed after admission")
        if any(
            item.revision_id != source.source_revision_id
            or item.commit != source.source_commit
            or item.tree != source.source_tree
            for item in workload.inputs
        ):
            raise ValueError(
                "formal Compute inputs must share the exact admitted PublishedRevision"
            )
        assert dispatch.route_id is not None
        assert dispatch.target_id is not None
        assert dispatch.provider_component_id is not None
        assert dispatch.inventory_generation is not None
        assert dispatch.inventory_digest is not None
        assert dispatch.qualification_digest is not None
        route = ExecutionRouteIdentity(
            route_id=dispatch.route_id,
            target_id=dispatch.target_id,
            provider_id=dispatch.provider_component_id,
            inventory_generation=dispatch.inventory_generation,
            inventory_digest=dispatch.inventory_digest,
            qualification_digest=dispatch.qualification_digest,
        )
        identity = canonical_sha256_digest(
            {
                "call_id": invocation.call_id,
                "tool_name": invocation.tool_name,
                "tool_contract_digest": dispatch.tool_contract_digest,
                "workload_digest": workload.workload_digest,
                "route_digest": dispatch.route_digest,
                "authority_lease_digest": dispatch.authority_lease_digest,
                "source_revision_id": source.source_revision_id,
            }
        ).removeprefix("sha256:")
        now = datetime.fromisoformat(self.clock.now_iso())
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("formal Compute clock must provide an aware timestamp")
        execution_id = f"execution-{identity[:32]}"
        operation_id = f"operation-{identity[32:64]}"
        idempotency_key = f"formal-{invocation.call_id}"
        request = ComputeExecutionRequest.create(
            invocation_id=invocation.call_id,
            execution_id=execution_id,
            operation_id=operation_id,
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            owner_agent_member_id=invocation.agent_member_id,
            authority_lease_id=dispatch.authority_lease_id,
            authority_generation=dispatch.authority_generation,
            authority_fence=dispatch.authority_fence,
            workspace_id=source.workspace_id,
            workspace_generation=source.workspace_generation,
            source_revision_id=source.source_revision_id,
            source_ref=source.source_ref,
            source_commit=source.source_commit,
            source_tree=source.source_tree,
            lfs_closure_manifest_digest=source.lfs_closure_manifest_digest,
            clean_observation_digest=source.clean_observation_digest,
            workload=workload,
            route=route,
            idempotency_key=idempotency_key,
            absolute_deadline=(now + self.maximum_duration).isoformat(),
            created_at=now.isoformat(),
        )
        record = self.compute.submit(
            context=KernelCommandContext(
                command_id=f"formal-compute-{identity}",
                session_id=invocation.session_id,
                actor_id=invocation.agent_member_id,
                owner_plugin_id="openzyme.compute",
                authority_lease_id=dispatch.authority_lease_id,
                authority_generation=dispatch.authority_generation,
                authority_fence=dispatch.authority_fence,
                expected_session_version=source.session_version,
                extension_bundle_digest=dispatch.extension_bundle_digest,
                capability_binding_digest=dispatch.capability_binding_digest,
                idempotency_key=idempotency_key,
                correlation_id=f"formal-compute-{invocation.call_id}",
                workspace_generation=source.workspace_generation,
                route_id=dispatch.route_id,
            ),
            request=request,
        )
        return {
            "execution_id": record.request.execution_id,
            "operation_id": record.request.operation_id,
            "workload_id": record.request.workload.workload_id,
            "workload_digest": record.request.workload.workload_digest,
            "state": "terminal" if record.result is not None else "admitted",
        }

    @staticmethod
    def _validate_dispatch(
        invocation: ToolInvocation,
        dispatch: ToolDispatchBinding,
    ) -> None:
        if (
            invocation.route_id is None
            or invocation.affordance_snapshot_digest is None
            or invocation.arguments.get("route_id") != invocation.route_id
            or invocation.arguments.get("affordance_snapshot_digest")
            != invocation.affordance_snapshot_digest
            or dispatch.route_id != invocation.route_id
            or dispatch.affordance_snapshot_digest
            != invocation.affordance_snapshot_digest
            or dispatch.driver_id is None
            or dispatch.target_id is None
            or dispatch.inventory_generation is None
            or dispatch.inventory_digest is None
            or dispatch.qualification_digest is None
        ):
            raise ValueError("formal Compute invocation lost its exact affordance or route")


@dataclass(slots=True)
class EnzymeDesignFormalComputeApplicationBinding:
    """One-shot composition binding for the mounted HMMER/Vina runtimes.

    Plugin runtimes are materialized before the Kernel-owned durable services can
    be constructed.  This narrow holder breaks that construction cycle without
    creating an ambient service locator: the Distribution binds it exactly once
    before returning an enabled writer graph, and an unbound invocation fails
    closed with no external effect.
    """

    route: ComputeRoutePort
    clock: ClockPort
    binding_id: str = "enzymedesign.formal-compute-application@1"
    _application: EnzymeDesignFormalComputeToolApplication | None = None

    @property
    def is_bound(self) -> bool:
        return self._application is not None

    def bind(
        self,
        *,
        records: KernelRecordQueryPort,
        capability_registries: FormalComputeCapabilityRegistryResolver,
        path_verifications: FormalComputeRevisionPathVerificationQuery,
        repository: ComputeExecutionRepository,
        controlled_operations: ControlledOperationApplicationService,
        continuations: ContinuationApplicationService,
    ) -> None:
        if self._application is not None:
            raise ValueError("formal Compute application binding is immutable")
        compute = ComputeExecutionApplicationService(
            repository=repository,
            admission_verifier=CanonicalFormalComputeAdmissionVerifier(
                records=records,
                capability_registries=capability_registries,
                clock=self.clock,
            ),
            controlled_operations=controlled_operations,
            route=self.route,
            continuations=continuations,
        )
        self._application = build_enzymedesign_formal_compute_application(
            compute=compute,
            source_bindings=CanonicalFormalComputeSourceBindingResolver(
                records=records,
                path_verifications=path_verifications,
            ),
            clock=self.clock,
        )

    def request(
        self,
        *,
        invocation: ToolInvocation,
        dispatch: ToolDispatchBinding,
    ) -> Mapping[str, JsonValue]:
        if self._application is None:
            raise ValueError("formal Compute application is not bound")
        return self._application.request(invocation=invocation, dispatch=dispatch)

    def observe(
        self,
        *,
        context: KernelCommandContext,
        execution_id: str,
    ):
        if self._application is None:
            raise ValueError("formal Compute application is not bound")
        return self._application.compute.observe(
            context=context,
            execution_id=execution_id,
        )


def build_enzymedesign_formal_compute_application(
    *,
    compute: ComputeExecutionApplicationService,
    source_bindings: FormalComputeSourceBindingResolver,
    clock: ClockPort,
) -> EnzymeDesignFormalComputeToolApplication:
    """Load the exact manifest-selected HMMER/Vina Drivers without ambient discovery."""

    drivers: dict[str, FormalComputeDriverBinding] = {}
    for locator, factory, request_digest in (
        (
            locate_hmmer_hpc_driver(),
            HmmerDriver,
            HMMER_DRIVER_REQUEST_CONTRACT_DIGEST,
        ),
        (
            locate_hmmer_local_driver(),
            HmmerDriver,
            HMMER_DRIVER_REQUEST_CONTRACT_DIGEST,
        ),
        (
            locate_vina_hpc_driver(),
            VinaDriver,
            VINA_DRIVER_REQUEST_CONTRACT_DIGEST,
        ),
        (
            locate_vina_local_driver(),
            VinaDriver,
            VINA_DRIVER_REQUEST_CONTRACT_DIGEST,
        ),
    ):
        manifest = read_located_component_manifest(locator)
        driver = factory(manifest)  # type: ignore[arg-type]
        drivers[manifest.identity.component_id] = FormalComputeDriverBinding(
            driver=driver,
            request_contract_digest=request_digest,
        )
    return EnzymeDesignFormalComputeToolApplication(
        compute=compute,
        source_bindings=source_bindings,
        clock=clock,
        drivers=drivers,
    )


def _driver_payload(
    invocation: ToolInvocation,
) -> tuple[str, dict[str, JsonValue]]:
    payload = {
        key: value
        for key, value in invocation.arguments.items()
        if key not in {"route_id", "affordance_snapshot_digest"}
    }
    if invocation.tool_name == HMMER_BUILD_TOOL:
        return HMMER_PLUGIN_ID, {"operation": "build", **payload}
    if invocation.tool_name == HMMER_SEARCH_TOOL:
        return HMMER_PLUGIN_ID, {"operation": "search", **payload}
    if invocation.tool_name == VINA_DOCK_TOOL:
        return VINA_PLUGIN_ID, payload
    raise ValueError("formal Compute bridge received an unsupported Product tool")


__all__ = [
    "CanonicalFormalComputeAdmissionVerifier",
    "CanonicalFormalComputeSourceBindingResolver",
    "EnzymeDesignFormalComputeApplicationBinding",
    "EnzymeDesignFormalComputeToolApplication",
    "ExactComputeRouteRouter",
    "FormalComputeDriverBinding",
    "FormalComputeSourceBinding",
    "FormalComputeSourceBindingResolver",
    "FormalComputeRevisionPathVerificationQuery",
    "FormalComputeCapabilityRegistryResolver",
    "build_enzymedesign_formal_compute_application",
]
