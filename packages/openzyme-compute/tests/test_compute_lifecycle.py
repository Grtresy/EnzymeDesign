from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import datetime

import pytest

from openzyme_compute import ComputeAdmissionProof
from openzyme_compute import ComputeExecutionApplicationService
from openzyme_compute import ComputeExecutionRequest
from openzyme_compute import ComputeLifecycleError
from openzyme_compute import ComputeRouteOutcome
from openzyme_compute import InMemoryComputeExecutionRepository
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import canonical_sha256_digest
from openzyme_execution_contracts import ExecutionResultReceipt
from openzyme_execution_contracts import ExecutionRouteIdentity
from openzyme_execution_contracts import ExecutionWorkloadSpec
from openzyme_execution_contracts import canonical_execution_wire_digest
from openzyme_extension_spi import ContinuationApplicationCommand
from openzyme_extension_spi import ControlledOperationApplicationCommand
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_kernel import ControlledOperationKernelApplicationService
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_kernel.testing import InMemoryControlStore


DIGEST = "sha256:" + "1" * 64


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


def _route() -> ExecutionRouteIdentity:
    return ExecutionRouteIdentity.from_dict(
        {
            "schema_version": "execution_route_identity@1",
            "route_id": "hpc-primary.revision-job",
            "target_id": "hpc-primary",
            "provider_id": "openzyme.hpc",
            "inventory_generation": 7,
            "inventory_digest": DIGEST,
            "qualification_digest": DIGEST,
        }
    )


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
        route=_route(),
        idempotency_key="submit_1",
        absolute_deadline="2026-08-20T12:00:00+00:00",
        created_at="2026-08-20T10:00:00+00:00",
    )


def _context(*, idempotency_key: str = "submit_1") -> KernelCommandContext:
    return KernelCommandContext(
        command_id="command_1",
        session_id="session_1",
        actor_id="member_1",
        owner_plugin_id="openzyme.compute",
        authority_lease_id="lease_1",
        authority_generation=2,
        authority_fence=3,
        expected_session_version=5,
        extension_bundle_digest=DIGEST,
        capability_binding_digest=DIGEST,
        idempotency_key=idempotency_key,
        correlation_id="correlation_1",
        workspace_generation=4,
        route_id="hpc-primary.revision-job",
    )


class ExactVerifier:
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


class DriftVerifier(ExactVerifier):
    def __init__(self, field_name: str, value: object) -> None:
        self.field_name = field_name
        self.value = value

    def verify(self, *, context, request) -> ComputeAdmissionProof:
        return replace(
            super().verify(context=context, request=request),
            **{self.field_name: self.value},
        )


class RecordingControlledOperations:
    def __init__(self) -> None:
        self.commands: list[ControlledOperationApplicationCommand] = []

    def execute(self, command: ControlledOperationApplicationCommand) -> KernelMutationReceipt:
        self.commands.append(command)
        certainty = ExternalEffectCertainty.NO_EFFECT
        if command.operation.value in {"observe", "reconcile"}:
            certainty = (
                ExternalEffectCertainty.DISPATCH_IN_DOUBT
                if command.operation.value == "reconcile"
                else (
                    ExternalEffectCertainty.TERMINAL_KNOWN
                    if command.payload.get("terminal_result_id") is not None
                    else ExternalEffectCertainty.EFFECT_KNOWN
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


class RecordingContinuations:
    def __init__(self) -> None:
        self.commands: list[ContinuationApplicationCommand] = []

    def execute(self, command: ContinuationApplicationCommand) -> KernelMutationReceipt:
        self.commands.append(command)
        return KernelMutationReceipt.create(
            command_id=command.context.command_id,
            service_id="continuation",
            operation=command.operation.value,
            mutation_applied=True,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        )


@dataclass
class RecordingRoute:
    dispatch_outcome: ComputeRouteOutcome
    observe_outcome: ComputeRouteOutcome | None = None
    cancel_error: ComputeLifecycleError | None = None
    dispatch_count: int = 0
    cancel_count: int = 0

    def dispatch(self, request: ComputeExecutionRequest) -> ComputeRouteOutcome:
        self.dispatch_count += 1
        return self.dispatch_outcome

    def observe(self, request, provider_handle) -> ComputeRouteOutcome:
        assert self.observe_outcome is not None
        return self.observe_outcome

    def cancel(self, request, provider_handle) -> ComputeRouteOutcome:
        self.cancel_count += 1
        if self.cancel_error is not None:
            raise self.cancel_error
        return self.dispatch_outcome


def _outcome(
    *,
    certainty: ExternalEffectCertainty = ExternalEffectCertainty.EFFECT_KNOWN,
    result: ExecutionResultReceipt | None = None,
) -> ComputeRouteOutcome:
    if result is not None:
        certainty = ExternalEffectCertainty.TERMINAL_KNOWN
    return ComputeRouteOutcome(
        route_id="hpc-primary.revision-job",
        operation_id="operation_1",
        provider_handle="provider_handle_1",
        receipt_digest=DIGEST,
        effect_certainty=certainty,
        mutation_applied=True if certainty is not ExternalEffectCertainty.DISPATCH_IN_DOUBT else None,
        terminal_result=result,
    )


def _service(route: RecordingRoute):
    operations = RecordingControlledOperations()
    continuations = RecordingContinuations()
    service = ComputeExecutionApplicationService(
        repository=InMemoryComputeExecutionRepository(),
        admission_verifier=ExactVerifier(),
        controlled_operations=operations,
        route=route,
        continuations=continuations,
    )
    return service, operations, continuations


def test_submit_binds_exact_revision_route_and_one_controlled_operation() -> None:
    route = RecordingRoute(_outcome())
    service, operations, _ = _service(route)

    record = service.submit(context=_context(), request=_request())

    assert route.dispatch_count == 1
    assert record.provider_handle == "provider_handle_1"
    assert [item.operation.value for item in operations.commands] == ["admit", "observe"]
    assert all(item.context.route_id == "hpc-primary.revision-job" for item in operations.commands)
    assert record.safe_projection()["publication_created"] is False
    assert record.safe_projection()["task_finished"] is False


def test_compute_uses_real_kernel_operation_truth_from_active_to_terminal() -> None:
    store = InMemoryControlStore(
        (
            KernelRecordSnapshot.create(
                entity_type="session",
                entity_id="session_1",
                state_version=5,
                payload={"status": "active"},
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_authority_lease",
                entity_id="lease_1",
                state_version=1,
                payload={
                    "session_id": "session_1",
                    "agent_member_id": "member_1",
                    "state": "active",
                    "generation": 2,
                    "fence": 3,
                    "expires_at": "2026-08-20T13:00:00+00:00",
                    "grants": [
                        {
                            "scope_id": "workspace_1",
                            "operations": ["external_compute"],
                        }
                    ],
                },
            ),
        )
    )
    controlled = ControlledOperationKernelApplicationService(
        store=store,
        reader=store,
        clock=DeterministicClock(datetime(2026, 8, 20, 10, tzinfo=UTC)),
        ids=DeterministicIdGenerator(),
    )
    route = RecordingRoute(_outcome())
    service = ComputeExecutionApplicationService(
        repository=InMemoryComputeExecutionRepository(),
        admission_verifier=ExactVerifier(),
        controlled_operations=controlled,
        route=route,
    )

    active = service.submit(context=_context(), request=_request())
    operation = store.read(
        entity_type="controlled_operation", entity_id="operation_1"
    )
    assert active.provider_handle == "provider_handle_1"
    assert operation is not None
    assert operation.payload["state"] == "active"

    result = ExecutionResultReceipt.from_dict(
        {
            "schema_version": "execution_result_receipt@1",
            "result_id": "result_1",
            "invocation_id": "invocation_1",
            "operation_id": "operation_1",
            "execution_id": "execution_1",
            "route_id": "hpc-primary.revision-job",
            "workload_digest": _workload().workload_digest,
            "state": "succeeded",
            "result_contract_digest": canonical_sha256_digest(
                _workload().result_contract.to_dict()
            ),
            "result_revision_id": None,
            "result_digest": DIGEST,
            "terminal_receipt_digest": DIGEST,
        }
    )
    route.observe_outcome = replace(
        _outcome(result=result),
        receipt_digest=canonical_sha256_digest({"phase": "terminal"}),
    )
    terminal = service.observe(context=_context(), execution_id="execution_1")
    operation = store.read(
        entity_type="controlled_operation", entity_id="operation_1"
    )

    assert terminal.result == result
    assert operation is not None
    assert operation.payload["state"] == "settled"
    assert operation.payload["terminal_receipt_digest"] == DIGEST
    assert route.dispatch_count == 1


def test_stale_or_omitted_route_fails_before_effect() -> None:
    route = RecordingRoute(_outcome())
    service, operations, _ = _service(route)

    with pytest.raises(ComputeLifecycleError) as error:
        service.submit(
            context=replace(_context(), route_id="hpc-secondary.revision-job"),
            request=_request(),
        )

    assert error.value.error_code == "compute_command_context_mismatch"
    assert route.dispatch_count == 0
    assert operations.commands == []


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("clean_observation_digest", "sha256:" + "2" * 64),
        ("lfs_closure_manifest_digest", "sha256:" + "3" * 64),
        ("inventory_generation", 8),
        ("authority_fence", 4),
    ],
)
def test_admission_proof_drift_rejects_dirty_lfs_inventory_or_authority_before_effect(
    field_name: str,
    value: object,
) -> None:
    route = RecordingRoute(_outcome())
    operations = RecordingControlledOperations()
    service = ComputeExecutionApplicationService(
        repository=InMemoryComputeExecutionRepository(),
        admission_verifier=DriftVerifier(field_name, value),
        controlled_operations=operations,
        route=route,
    )

    with pytest.raises(ComputeLifecycleError) as error:
        service.submit(context=_context(), request=_request())

    assert error.value.error_code == "compute_admission_proof_mismatch"
    assert route.dispatch_count == 0
    assert operations.commands == []


def test_dispatch_in_doubt_is_reconciled_without_replacement() -> None:
    route = RecordingRoute(
        _outcome(certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT),
        observe_outcome=_outcome(),
    )
    service, operations, _ = _service(route)

    record = service.submit(context=_context(), request=_request())

    assert route.dispatch_count == 1
    assert record.provider_handle == "provider_handle_1"
    assert operations.commands[-1].operation.value == "reconcile"
    assert operations.commands[-1].payload["redispatch_performed"] is False


def test_lost_cancel_response_does_not_issue_replacement() -> None:
    route = RecordingRoute(_outcome())
    service, operations, _ = _service(route)
    service.submit(context=_context(), request=_request())
    route.cancel_error = ComputeLifecycleError(
        "compute_cancel_response_lost",
        "cancel may have reached provider",
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        diagnostic_id="diagnostic_1",
    )

    with pytest.raises(ComputeLifecycleError):
        service.cancel(context=_context(), execution_id="execution_1")

    assert route.cancel_count == 1
    assert [item.operation.value for item in operations.commands[-2:]] == [
        "cancel",
        "reconcile",
    ]
    assert operations.commands[-1].payload["redispatch_performed"] is False


def test_terminal_result_only_wakes_owner_and_never_finishes_task() -> None:
    workload = _workload()
    result = ExecutionResultReceipt.from_dict(
        {
            "schema_version": "execution_result_receipt@1",
            "result_id": "result_1",
            "invocation_id": "invocation_1",
            "operation_id": "operation_1",
            "execution_id": "execution_1",
            "route_id": "hpc-primary.revision-job",
            "workload_digest": workload.workload_digest,
            "state": "succeeded",
            "result_contract_digest": canonical_sha256_digest(
                workload.result_contract.to_dict()
            ),
            "result_revision_id": None,
            "result_digest": DIGEST,
            "terminal_receipt_digest": DIGEST,
        }
    )
    route = RecordingRoute(_outcome(result=result))
    service, _, continuations = _service(route)

    record = service.submit(context=_context(), request=_request())

    assert record.result == result
    assert len(continuations.commands) == 1
    assert continuations.commands[0].payload == {
        "source_ref": "compute-result:result_1",
        "source_digest": DIGEST,
        "recipient_actor_id": "member_1",
        "resume_strategy": "durable_runtime_signal",
    }
    assert record.safe_projection()["task_finished"] is False
    assert record.safe_projection()["publication_created"] is False
