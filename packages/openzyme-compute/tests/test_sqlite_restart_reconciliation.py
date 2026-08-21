from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from types import SimpleNamespace
import sqlite3

import pytest

from openzyme_compute import ComputeAdmissionProof
from openzyme_compute import ComputeExecutionApplicationService
from openzyme_compute import ComputeExecutionRequest
from openzyme_compute import ComputeLifecycleError
from openzyme_compute import ComputeRouteOutcome
from openzyme_compute import ComputeTransactionParticipant
from openzyme_compute import ExtensionStateComputeExecutionRepository
from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import WorkspaceGenerationStatus
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import canonical_sha256_digest
from openzyme_execution_contracts import ExecutionResultReceipt
from openzyme_execution_contracts import ExecutionRouteIdentity
from openzyme_execution_contracts import ExecutionWorkloadSpec
from openzyme_execution_contracts import canonical_execution_wire_digest
from openzyme_extension_spi import AuthorityDecision
from openzyme_extension_spi import ControlledOperationApplicationCommand
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_kernel import ContinuationKernelApplicationService
from openzyme_kernel import ExtensionStateKernelApplicationService
from openzyme_kernel import MountedExtensionSurfaces
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_store_sqlite import ENZYMEDESIGN_OWNER_SCHEMA_PROFILE
from openzyme_store_sqlite import SQLiteControlStore
from openzyme_store_sqlite import SQLiteExtensionStateProjectionQuery
from openzyme_store_sqlite import SQLiteExtensionTransactionCoordinator
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration
from openzyme_store_sqlite import kernel_entity_codecs


DIGEST = "sha256:" + "1" * 64
ACTIVE_ROUTE_RECEIPT = canonical_sha256_digest({"route": "active"})
TERMINAL_ROUTE_RECEIPT = canonical_sha256_digest({"route": "terminal"})


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(
        connection,
        profile=ENZYMEDESIGN_OWNER_SCHEMA_PROFILE,
    )
    install_store_schema_for_offline_migration(connection)
    return connection


def _seed_continuation_authority(connection: sqlite3.Connection) -> SQLiteControlStore:
    store = SQLiteControlStore(connection, codecs=kernel_entity_codecs())
    now = "2026-08-22T10:00:00+00:00"
    lease = AgentAuthorityLease.create(
        lease_id="lease_1",
        session_id="session_1",
        agent_member_id="member_1",
        grants=(
            AuthorityGrant.create(
                grant_id="grant_continuation_1",
                scope_id="compute-result-execution_1",
                operations=("continuation.register",),
                generation=2,
                fence=3,
            ),
        ),
        generation=2,
        fence=3,
        state=AgentAuthorityLeaseState.ACTIVE,
        issued_at=now,
        expires_at=None,
        agent_id="agent_1",
        workspace_generation=4,
        policy_digest=DIGEST,
        idempotency_key="lease_seed_1",
        updated_at=now,
    )
    payloads = (
        (
            "session",
            "session_1",
            {
                "session_id": "session_1",
                "project_id": "project_1",
                "title": "Compute restart qualification",
                "objective": "Recover one exact formal execution",
                "status": "active",
                "created_at": now,
                "updated_at": now,
            },
        ),
        (
            "agent_member",
            "member_1",
            {
                "agent_member_id": "member_1",
                "agent_id": "agent_1",
                "session_id": "session_1",
                "parent_agent_id": None,
                "lane_id": None,
                "name": "Compute owner",
                "role": "executor",
                "status": "active",
                "process_epoch": 1,
                "active_authority_lease_id": lease.lease_id,
                "workspace_generation": 4,
                "owned_task_ids": ["task_1"],
                "retirement_reason": None,
                "terminal_proof_digest": None,
                "retirement_settled": False,
                "retired_at": None,
                "created_at": now,
                "updated_at": now,
            },
        ),
        (
            "workspace_generation",
            "workspace_1",
            WorkspaceGeneration(
                workspace_id="workspace_1",
                workspace_kind=WorkspaceKind.AGENT_LOCAL,
                session_id="session_1",
                owner_member_id="member_1",
                generation=4,
                state_version=1,
                status=WorkspaceGenerationStatus.READY,
                provider_id="openzyme.workspace.git-lfs",
                target_id="local:host",
                created_at=now,
                updated_at=now,
                root_identity_digest=DIGEST,
                transition_receipt_digest=DIGEST,
                controlled_operation_id="workspace_provision_1",
            ).to_dict(),
        ),
        ("agent_authority_lease", lease.lease_id, lease.to_dict()),
    )
    for index, (entity_type, entity_id, payload) in enumerate(payloads, start=1):
        unit = store.begin(
            UnitOfWorkRequest(
                unit_of_work_id=f"uow_seed_compute_{index}",
                command_id=f"command_seed_compute_{index}",
                session_id="session_1",
                actor_id="member_1",
                authority_lease_id="lease_1",
                authority_generation=2,
                authority_fence=3,
                expected_session_version=1,
                idempotency_key=f"seed_compute_{index}",
                command_digest=canonical_sha256_digest(
                    {"seed_compute": index}
                ),
            )
        )
        unit.stage(
            KernelStateMutation.create(
                mutation_id=f"mutation_seed_compute_{index}",
                kind=KernelMutationKind.CREATE,
                entity_type=entity_type,
                entity_id=entity_id,
                expected_state_version=None,
                payload=payload,
            )
        )
        unit.commit()
    return store


def _workload() -> ExecutionWorkloadSpec:
    payload: dict[str, object] = {
        "schema_version": "execution_workload_spec@1",
        "workload_id": "workload_1",
        "workload_contract": "enzymedesign.hmmer.search@1",
        "entry_point": "enzymedesign.hmmer.search@1",
        "argv": ["hmmsearch", "model.hmm", "proteins.fasta"],
        "cwd": "analysis/hmmer",
        "resource_policy_digest": DIGEST,
        "environment_policy_digest": DIGEST,
        "inputs": [
            {
                "revision_id": "revision_1",
                "commit": "a" * 40,
                "tree": "b" * 40,
                "path": "inputs/proteins.fasta",
                "content_digest": DIGEST,
            }
        ],
        "result_contract": {
            "contract_id": "enzymedesign.hmmer.result@1",
            "schema_digest": DIGEST,
            "result_root": "results/hmmer",
        },
        "capability_requirements": [
            {
                "capability_id": "software.hmmer",
                "version_spec": ">=3.3,<4",
                "operations": ["hmmsearch"],
            }
        ],
    }
    payload["workload_digest"] = canonical_execution_wire_digest(payload)
    return ExecutionWorkloadSpec.from_dict(payload)


def _request() -> ComputeExecutionRequest:
    return ComputeExecutionRequest.create(
        invocation_id="invocation_1",
        execution_id="execution_1",
        operation_id="operation_1",
        session_id="session_1",
        task_id="task_1",
        owner_agent_member_id="member_1",
        authority_lease_id="lease_1",
        authority_generation=2,
        authority_fence=3,
        workspace_id="workspace_1",
        workspace_generation=4,
        source_revision_id="revision_1",
        source_ref="refs/openzyme/public/revision_1",
        source_commit="a" * 40,
        source_tree="b" * 40,
        lfs_closure_manifest_digest=DIGEST,
        clean_observation_digest=DIGEST,
        workload=_workload(),
        route=ExecutionRouteIdentity.from_dict(
            {
                "schema_version": "execution_route_identity@1",
                "route_id": "hpc-primary.revision-job",
                "target_id": "hpc-primary",
                "provider_id": "openzyme.hpc",
                "inventory_generation": 7,
                "inventory_digest": DIGEST,
                "qualification_digest": DIGEST,
            }
        ),
        idempotency_key="submit_1",
        absolute_deadline="2026-08-22T12:00:00+00:00",
        created_at="2026-08-22T10:00:00+00:00",
    )


def _context() -> KernelCommandContext:
    return KernelCommandContext(
        command_id="command_1",
        session_id="session_1",
        actor_id="member_1",
        owner_plugin_id="openzyme.compute",
        authority_lease_id="lease_1",
        authority_generation=2,
        authority_fence=3,
        expected_session_version=1,
        extension_bundle_digest=DIGEST,
        capability_binding_digest=DIGEST,
        idempotency_key="submit_1",
        correlation_id="correlation_1",
        workspace_generation=4,
        route_id="hpc-primary.revision-job",
    )


class _AdmissionVerifier:
    def verify(self, *, context, request) -> ComputeAdmissionProof:
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


class _Authority:
    def authorize(self, request):
        allowed = request.expected_generation == 2 and request.expected_fence == 3
        return AuthorityDecision(
            allowed=allowed,
            operation=request.operation,
            scope_id=request.scope_id,
            authority_lease_id=request.context.authority_lease_id,
            generation=request.expected_generation,
            fence=request.expected_fence,
            denial_code=None if allowed else "authority_fence_stale",
        )


class _SessionGuard:
    def require(self, **_):
        return None


class _Clock:
    def now_iso(self) -> str:
        return "2026-08-22T10:00:00+00:00"


class _SessionRepository:
    pin = SimpleNamespace(
        release_identity=SimpleNamespace(extension_bundle_digest=DIGEST)
    )
    binding = SimpleNamespace(binding_digest=DIGEST)

    def get_pin(self, session_id: str):
        return self.pin if session_id == "session_1" else None

    def latest_capability_binding(self, session_id: str):
        return self.binding if session_id == "session_1" else None


class _ControlledOperations:
    def __init__(self) -> None:
        self.commands: list[ControlledOperationApplicationCommand] = []

    def execute(
        self, command: ControlledOperationApplicationCommand
    ) -> KernelMutationReceipt:
        self.commands.append(command)
        terminal = command.payload.get("terminal_result_id") is not None
        certainty = (
            ExternalEffectCertainty.TERMINAL_KNOWN
            if terminal
            else (
                ExternalEffectCertainty.EFFECT_KNOWN
                if command.operation.value == "observe"
                else ExternalEffectCertainty.NO_EFFECT
            )
        )
        return KernelMutationReceipt.create(
            command_id=command.context.command_id,
            service_id="controlled_operation",
            operation=command.operation.value,
            mutation_applied=True,
            effect_certainty=certainty,
            result={"fallback_performed": False},
        )


@dataclass
class _ExternalOccurrence:
    dispatch_count: int = 0
    terminal: bool = False


@dataclass
class _Route:
    occurrence: _ExternalOccurrence

    def dispatch(self, request: ComputeExecutionRequest) -> ComputeRouteOutcome:
        self.occurrence.dispatch_count += 1
        return ComputeRouteOutcome(
            route_id=request.route.route_id,
            operation_id=request.operation_id,
            provider_handle="provider_handle_1",
            receipt_digest=ACTIVE_ROUTE_RECEIPT,
            effect_certainty=ExternalEffectCertainty.EFFECT_KNOWN,
            mutation_applied=True,
        )

    def observe(
        self,
        request: ComputeExecutionRequest,
        provider_handle: str,
    ) -> ComputeRouteOutcome:
        assert provider_handle == "provider_handle_1"
        result = None
        certainty = ExternalEffectCertainty.EFFECT_KNOWN
        receipt = ACTIVE_ROUTE_RECEIPT
        if self.occurrence.terminal:
            certainty = ExternalEffectCertainty.TERMINAL_KNOWN
            receipt = TERMINAL_ROUTE_RECEIPT
            result = ExecutionResultReceipt.from_dict(
                {
                    "schema_version": "execution_result_receipt@1",
                    "result_id": "result_1",
                    "invocation_id": request.invocation_id,
                    "operation_id": request.operation_id,
                    "execution_id": request.execution_id,
                    "route_id": request.route.route_id,
                    "workload_digest": request.workload.workload_digest,
                    "state": "succeeded",
                    "result_contract_digest": canonical_sha256_digest(
                        request.workload.result_contract.to_dict()
                    ),
                    "result_revision_id": None,
                    "result_digest": DIGEST,
                    "terminal_receipt_digest": DIGEST,
                }
            )
        return ComputeRouteOutcome(
            route_id=request.route.route_id,
            operation_id=request.operation_id,
            provider_handle=provider_handle,
            receipt_digest=receipt,
            effect_certainty=certainty,
            mutation_applied=True,
            terminal_result=result,
        )

    def cancel(self, request, provider_handle):
        raise AssertionError("cancel is outside this restart proof")


def _service(
    connection: sqlite3.Connection,
    occurrence: _ExternalOccurrence,
    *,
    continuation_store: SQLiteControlStore | None = None,
) -> tuple[ComputeExecutionApplicationService, _ControlledOperations]:
    participant = ComputeTransactionParticipant()
    plugin = SimpleNamespace(
        identity=SimpleNamespace(component_id="openzyme.compute"),
        transaction_participants=(
            SimpleNamespace(contribution_id=participant.participant_id),
        ),
    )
    composition = SimpleNamespace(
        plugins=SimpleNamespace(
            contributing_manifests=(plugin,),
            extension_bundle_digest=DIGEST,
        )
    )
    mounted = MountedExtensionSurfaces(
        epoch_id="epoch_1",
        activation_digest=DIGEST,
        tools=(),
        capability_routes=(),
        http_routes=(),
        projections=(),
        workers=(),
        finish_validators=(),
        transaction_participants=((participant.participant_id, participant),),
        mount_digest="sha256:" + "0" * 64,
    )
    mutations = ExtensionStateKernelApplicationService(
        composition=composition,
        mounted=mounted,
        session_repository=_SessionRepository(),
        session_guard=_SessionGuard(),
        authority=_Authority(),
        coordinator=SQLiteExtensionTransactionCoordinator(connection),
        clock=_Clock(),
    )
    repository = ExtensionStateComputeExecutionRepository(
        mutations=mutations,
        query=SQLiteExtensionStateProjectionQuery.create(
            connection,
            allowed_namespaces={"openzyme_compute"},
        ),
    )
    controlled = _ControlledOperations()
    return (
        ComputeExecutionApplicationService(
            repository=repository,
            admission_verifier=_AdmissionVerifier(),
            controlled_operations=controlled,
            route=_Route(occurrence),
            continuations=(
                None
                if continuation_store is None
                else ContinuationKernelApplicationService(
                    store=continuation_store,
                    clock=_Clock(),
                    ids=DeterministicIdGenerator(),
                )
            ),
        ),
        controlled,
    )


def test_compute_survives_restart_without_redispatch_and_settles_original_route() -> None:
    connection = _connection()
    continuation_store = _seed_continuation_authority(connection)
    occurrence = _ExternalOccurrence()

    first, first_operations = _service(
        connection,
        occurrence,
        continuation_store=continuation_store,
    )
    active = first.submit(context=_context(), request=_request())

    assert active.state_version == 2
    assert active.provider_handle == "provider_handle_1"
    assert occurrence.dispatch_count == 1
    assert [item.operation.value for item in first_operations.commands] == [
        "admit",
        "observe",
    ]

    restarted_store = SQLiteControlStore(connection, codecs=kernel_entity_codecs())
    restarted, restarted_operations = _service(
        connection,
        occurrence,
        continuation_store=restarted_store,
    )
    replay = restarted.submit(context=_context(), request=_request())

    assert replay == active
    assert occurrence.dispatch_count == 1
    assert [item.operation.value for item in restarted_operations.commands] == [
        "admit"
    ]

    occurrence.terminal = True
    terminal = restarted.observe(context=_context(), execution_id="execution_1")

    assert terminal.state_version == 3
    assert terminal.result is not None
    assert terminal.result.result_id == "result_1"
    assert occurrence.dispatch_count == 1
    continuation = restarted_store.read(
        entity_type="continuation",
        entity_id="compute-result-execution_1",
    )
    assert continuation is not None
    assert continuation.payload["source_ref"] == "compute-result:result_1"
    assert continuation.payload["state"] == "ready"

    after_second_restart_store = SQLiteControlStore(
        connection,
        codecs=kernel_entity_codecs(),
    )
    after_second_restart, _ = _service(
        connection,
        occurrence,
        continuation_store=after_second_restart_store,
    )
    recovered = after_second_restart.repository.get("session_1", "execution_1")
    assert recovered == terminal
    assert after_second_restart_store.read(
        entity_type="continuation",
        entity_id="compute-result-execution_1",
    ) == continuation
    assert connection.execute(
        """
        SELECT state_version
        FROM openzyme_store_extension_state_records
        WHERE namespace = 'openzyme_compute'
          AND entity_kind = 'execution'
          AND entity_id = 'execution_1'
        """
    ).fetchone() == (3,)


def test_reused_execution_identity_with_different_request_never_redispatches() -> None:
    connection = _connection()
    occurrence = _ExternalOccurrence()
    first, _ = _service(connection, occurrence)
    first.submit(context=_context(), request=_request())

    restarted, _ = _service(connection, occurrence)
    changed_without_digest = replace(
        _request(),
        absolute_deadline="2026-08-22T13:00:00+00:00",
        request_digest="sha256:" + "0" * 64,
    )
    changed = replace(
        changed_without_digest,
        request_digest=canonical_sha256_digest(changed_without_digest.identity_payload),
    )
    with pytest.raises(ComputeLifecycleError) as raised:
        restarted.submit(context=_context(), request=changed)

    assert raised.value.error_code == "compute_execution_identity_conflict"
    assert occurrence.dispatch_count == 1
