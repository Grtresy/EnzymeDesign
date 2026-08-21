from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
import re
from typing import Protocol

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_contracts.identity import JsonValue
from openzyme_execution_contracts import ExecutionResultReceipt
from openzyme_execution_contracts import ExecutionRouteIdentity
from openzyme_execution_contracts import ExecutionWorkloadSpec
from openzyme_extension_spi import ContinuationApplicationCommand
from openzyme_extension_spi import ContinuationApplicationService
from openzyme_extension_spi import ContinuationCommandKind
from openzyme_extension_spi import ControlledOperationApplicationCommand
from openzyme_extension_spi import ControlledOperationApplicationService
from openzyme_extension_spi import ControlledOperationCommandKind
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelMutationReceipt


COMPUTE_EXECUTION_REQUEST_SCHEMA = "openzyme_compute_execution_request@1"
COMPUTE_EXECUTION_RECORD_SCHEMA = "openzyme_compute_execution_record@1"
COMPUTE_RESULT_PROJECTION_SCHEMA = "openzyme.compute@1"
_GIT_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


class ComputeLifecycleError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        effect_certainty: ExternalEffectCertainty = ExternalEffectCertainty.NO_EFFECT,
        mutation_applied: bool | None = None,
        diagnostic_id: str | None = None,
    ) -> None:
        if effect_certainty is ExternalEffectCertainty.NO_EFFECT:
            mutation_applied = False
        elif effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
            mutation_applied = None
        elif mutation_applied is None:
            raise ValueError("known Compute effect requires mutation_applied fact")
        self.error_code = error_code
        self.effect_certainty = effect_certainty
        self.mutation_applied = mutation_applied
        self.diagnostic_id = diagnostic_id
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ComputeExecutionRequest:
    invocation_id: str
    execution_id: str
    operation_id: str
    session_id: str
    task_id: str | None
    owner_agent_member_id: str
    authority_lease_id: str
    authority_generation: int
    authority_fence: int
    workspace_id: str
    workspace_generation: int
    source_revision_id: str
    source_ref: str
    source_commit: str
    source_tree: str
    lfs_closure_manifest_digest: str
    clean_observation_digest: str
    workload: ExecutionWorkloadSpec
    route: ExecutionRouteIdentity
    idempotency_key: str
    absolute_deadline: str
    created_at: str
    request_digest: str
    schema_version: str = COMPUTE_EXECUTION_REQUEST_SCHEMA

    @classmethod
    def create(cls, **values: object) -> ComputeExecutionRequest:
        provisional = cls(
            **values,
            request_digest="sha256:" + "0" * 64,
        )
        return replace(
            provisional,
            request_digest=canonical_sha256_digest(provisional.identity_payload),
        )

    @classmethod
    def from_dict(cls, value: object) -> ComputeExecutionRequest:
        fields = {
            "schema_version",
            "invocation_id",
            "execution_id",
            "operation_id",
            "session_id",
            "task_id",
            "owner_agent_member_id",
            "authority_lease_id",
            "authority_generation",
            "authority_fence",
            "workspace_id",
            "workspace_generation",
            "source_revision_id",
            "source_ref",
            "source_commit",
            "source_tree",
            "lfs_closure_manifest_digest",
            "clean_observation_digest",
            "workload",
            "route",
            "idempotency_key",
            "absolute_deadline",
            "created_at",
            "request_digest",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("Compute execution request fields are closed")
        data = dict(value)
        return cls(
            schema_version=str(data["schema_version"]),
            invocation_id=str(data["invocation_id"]),
            execution_id=str(data["execution_id"]),
            operation_id=str(data["operation_id"]),
            session_id=str(data["session_id"]),
            task_id=(str(data["task_id"]) if data["task_id"] is not None else None),
            owner_agent_member_id=str(data["owner_agent_member_id"]),
            authority_lease_id=str(data["authority_lease_id"]),
            authority_generation=int(data["authority_generation"]),
            authority_fence=int(data["authority_fence"]),
            workspace_id=str(data["workspace_id"]),
            workspace_generation=int(data["workspace_generation"]),
            source_revision_id=str(data["source_revision_id"]),
            source_ref=str(data["source_ref"]),
            source_commit=str(data["source_commit"]),
            source_tree=str(data["source_tree"]),
            lfs_closure_manifest_digest=str(data["lfs_closure_manifest_digest"]),
            clean_observation_digest=str(data["clean_observation_digest"]),
            workload=ExecutionWorkloadSpec.from_dict(data["workload"]),
            route=ExecutionRouteIdentity.from_dict(data["route"]),
            idempotency_key=str(data["idempotency_key"]),
            absolute_deadline=str(data["absolute_deadline"]),
            created_at=str(data["created_at"]),
            request_digest=str(data["request_digest"]),
        )

    def __post_init__(self) -> None:
        if self.schema_version != COMPUTE_EXECUTION_REQUEST_SCHEMA:
            raise ValueError("unsupported Compute execution request schema")
        for field_name in (
            "invocation_id",
            "execution_id",
            "operation_id",
            "session_id",
            "owner_agent_member_id",
            "authority_lease_id",
            "workspace_id",
            "source_revision_id",
            "idempotency_key",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.task_id is not None:
            require_identifier(self.task_id, field_name="task_id")
        for field_name in (
            "authority_generation",
            "authority_fence",
            "workspace_generation",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        if not self.source_ref.startswith("refs/"):
            raise ValueError("source_ref must be an exact Git ref")
        if _GIT_OID.fullmatch(self.source_commit) is None:
            raise ValueError("source_commit must be an exact Git object id")
        if _GIT_OID.fullmatch(self.source_tree) is None:
            raise ValueError("source_tree must be an exact Git object id")
        for field_name in ("absolute_deadline", "created_at"):
            try:
                parsed = datetime.fromisoformat(getattr(self, field_name))
            except ValueError as exc:
                raise ValueError(f"{field_name} must be ISO-8601") from exc
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError(f"{field_name} must include an explicit timezone")
        for field_name in (
            "lfs_closure_manifest_digest",
            "clean_observation_digest",
            "request_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if self.route.route_id == "" or not self.workload.inputs:
            raise ValueError("Compute request requires an explicit route and revision input")
        if any(
            item.revision_id != self.source_revision_id
            or item.commit != self.source_commit
            or item.tree != self.source_tree
            for item in self.workload.inputs
        ):
            raise ValueError("workload inputs must bind the exact admitted revision")
        if self.request_digest != "sha256:" + "0" * 64 and self.request_digest != canonical_sha256_digest(
            self.identity_payload
        ):
            raise ValueError("Compute execution request digest mismatch")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "invocation_id": self.invocation_id,
            "execution_id": self.execution_id,
            "operation_id": self.operation_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "owner_agent_member_id": self.owner_agent_member_id,
            "authority_lease_id": self.authority_lease_id,
            "authority_generation": self.authority_generation,
            "authority_fence": self.authority_fence,
            "workspace_id": self.workspace_id,
            "workspace_generation": self.workspace_generation,
            "source_revision_id": self.source_revision_id,
            "source_ref": self.source_ref,
            "source_commit": self.source_commit,
            "source_tree": self.source_tree,
            "lfs_closure_manifest_digest": self.lfs_closure_manifest_digest,
            "clean_observation_digest": self.clean_observation_digest,
            "workload": self.workload.to_dict(),
            "route": self.route.to_dict(),
            "idempotency_key": self.idempotency_key,
            "absolute_deadline": self.absolute_deadline,
            "created_at": self.created_at,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "request_digest": self.request_digest}


@dataclass(frozen=True, slots=True)
class ComputeAdmissionProof:
    session_id: str
    owner_agent_member_id: str
    authority_lease_id: str
    authority_generation: int
    authority_fence: int
    workspace_id: str
    workspace_generation: int
    source_revision_id: str
    clean_observation_digest: str
    lfs_closure_manifest_digest: str
    route_id: str
    inventory_generation: int
    capability_binding_digest: str
    proof_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "session_id",
            "owner_agent_member_id",
            "authority_lease_id",
            "workspace_id",
            "source_revision_id",
            "route_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "authority_generation",
            "authority_fence",
            "workspace_generation",
            "inventory_generation",
        ):
            if getattr(self, field_name) < 1:
                raise ValueError(f"{field_name} must be positive")
        for field_name in (
            "clean_observation_digest",
            "lfs_closure_manifest_digest",
            "capability_binding_digest",
            "proof_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)


class ComputeAdmissionVerifier(Protocol):
    def verify(
        self,
        *,
        context: KernelCommandContext,
        request: ComputeExecutionRequest,
    ) -> ComputeAdmissionProof: ...


@dataclass(frozen=True, slots=True)
class ComputeRouteOutcome:
    route_id: str
    operation_id: str
    provider_handle: str | None
    receipt_digest: str
    effect_certainty: ExternalEffectCertainty
    mutation_applied: bool | None
    terminal_result: ExecutionResultReceipt | None = None
    diagnostic_id: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.route_id, field_name="route_id")
        require_identifier(self.operation_id, field_name="operation_id")
        if self.provider_handle is not None:
            require_identifier(self.provider_handle, field_name="provider_handle")
        require_digest(self.receipt_digest, field_name="receipt_digest")


class ComputeRoutePort(Protocol):
    def dispatch(self, request: ComputeExecutionRequest) -> ComputeRouteOutcome: ...

    def observe(
        self,
        request: ComputeExecutionRequest,
        provider_handle: str,
    ) -> ComputeRouteOutcome: ...

    def cancel(
        self,
        request: ComputeExecutionRequest,
        provider_handle: str,
    ) -> ComputeRouteOutcome: ...


@dataclass(frozen=True, slots=True)
class ComputeExecutionRecord:
    request: ComputeExecutionRequest
    admission_proof_digest: str
    controlled_operation_admission_receipt_digest: str
    provider_handle: str | None = None
    route_receipt_digest: str | None = None
    result: ExecutionResultReceipt | None = None
    state_version: int = 1

    def __post_init__(self) -> None:
        require_digest(self.admission_proof_digest, field_name="admission_proof_digest")
        require_digest(
            self.controlled_operation_admission_receipt_digest,
            field_name="controlled_operation_admission_receipt_digest",
        )
        if self.provider_handle is not None:
            require_identifier(self.provider_handle, field_name="provider_handle")
        if self.route_receipt_digest is not None:
            require_digest(self.route_receipt_digest, field_name="route_receipt_digest")
        if self.state_version < 1:
            raise ValueError("state_version must be positive")

    def safe_projection(self) -> dict[str, JsonValue]:
        return {
            "schema_version": COMPUTE_EXECUTION_RECORD_SCHEMA,
            "invocation_id": self.request.invocation_id,
            "execution_id": self.request.execution_id,
            "operation_id": self.request.operation_id,
            "session_id": self.request.session_id,
            "task_id": self.request.task_id,
            "owner_agent_member_id": self.request.owner_agent_member_id,
            "workspace_id": self.request.workspace_id,
            "workspace_generation": self.request.workspace_generation,
            "source_revision_id": self.request.source_revision_id,
            "workload_id": self.request.workload.workload_id,
            "workload_digest": self.request.workload.workload_digest,
            "route_id": self.request.route.route_id,
            "target_id": self.request.route.target_id,
            "inventory_generation": self.request.route.inventory_generation,
            "provider_handle": self.provider_handle,
            "result_id": self.result.result_id if self.result else None,
            "result_state": self.result.state if self.result else None,
            "result_digest": self.result.result_digest if self.result else None,
            "state_version": self.state_version,
            "publication_created": False,
            "scientific_evidence_created": False,
            "task_finished": False,
        }


class ComputeExecutionRepository(Protocol):
    def get(self, execution_id: str) -> ComputeExecutionRecord | None: ...

    def save_once(self, record: ComputeExecutionRecord) -> ComputeExecutionRecord: ...

    def bind_route_outcome(
        self,
        execution_id: str,
        *,
        expected_state_version: int,
        outcome: ComputeRouteOutcome,
    ) -> ComputeExecutionRecord: ...


class InMemoryComputeExecutionRepository:
    def __init__(self) -> None:
        self._records: dict[str, ComputeExecutionRecord] = {}

    def get(self, execution_id: str) -> ComputeExecutionRecord | None:
        return self._records.get(execution_id)

    def save_once(self, record: ComputeExecutionRecord) -> ComputeExecutionRecord:
        existing = self._records.get(record.request.execution_id)
        if existing is not None:
            if existing != record:
                raise ComputeLifecycleError(
                    "compute_execution_identity_conflict",
                    "execution identity already belongs to a different request",
                )
            return existing
        self._records[record.request.execution_id] = record
        return record

    def bind_route_outcome(
        self,
        execution_id: str,
        *,
        expected_state_version: int,
        outcome: ComputeRouteOutcome,
    ) -> ComputeExecutionRecord:
        current = self._records[execution_id]
        if current.state_version != expected_state_version:
            raise ComputeLifecycleError(
                "compute_execution_state_stale",
                "Compute execution state changed before settlement",
            )
        if current.route_receipt_digest == outcome.receipt_digest:
            if (
                outcome.route_id != current.request.route.route_id
                or outcome.operation_id != current.request.operation_id
                or outcome.provider_handle not in {None, current.provider_handle}
                or outcome.terminal_result != current.result
            ):
                raise ComputeLifecycleError(
                    "compute_route_receipt_identity_conflict",
                    "route receipt identity was reused for a different outcome",
                    effect_certainty=outcome.effect_certainty,
                    mutation_applied=outcome.mutation_applied,
                )
            return current
        if outcome.route_id != current.request.route.route_id or outcome.operation_id != current.request.operation_id:
            raise ComputeLifecycleError(
                "compute_route_outcome_identity_mismatch",
                "route outcome belongs to another operation or route",
                effect_certainty=outcome.effect_certainty,
                mutation_applied=outcome.mutation_applied,
            )
        if current.provider_handle is not None and outcome.provider_handle not in {
            None,
            current.provider_handle,
        }:
            raise ComputeLifecycleError(
                "compute_provider_handle_replaced",
                "provider handle replacement is forbidden",
                effect_certainty=outcome.effect_certainty,
                mutation_applied=outcome.mutation_applied,
            )
        result = outcome.terminal_result or current.result
        if result is not None:
            _validate_terminal_result(current.request, outcome.provider_handle or current.provider_handle, result)
        updated = replace(
            current,
            provider_handle=outcome.provider_handle or current.provider_handle,
            route_receipt_digest=outcome.receipt_digest,
            result=result,
            state_version=current.state_version + 1,
        )
        self._records[execution_id] = updated
        return updated


@dataclass(slots=True)
class ComputeExecutionApplicationService:
    repository: ComputeExecutionRepository
    admission_verifier: ComputeAdmissionVerifier
    controlled_operations: ControlledOperationApplicationService
    route: ComputeRoutePort
    continuations: ContinuationApplicationService | None = None

    def submit(
        self,
        *,
        context: KernelCommandContext,
        request: ComputeExecutionRequest,
    ) -> ComputeExecutionRecord:
        self._validate_context(context, request)
        proof = self.admission_verifier.verify(context=context, request=request)
        _validate_proof(context, request, proof)
        admission_receipt = self.controlled_operations.execute(
            ControlledOperationApplicationCommand(
                context=_phase_context(
                    context,
                    request=request,
                    phase="controlled-admit",
                    identity_digest=request.request_digest,
                ),
                operation=ControlledOperationCommandKind.ADMIT,
                operation_id=request.operation_id,
                intent_digest=request.request_digest,
                payload=_safe_operation_payload(request, phase="admit"),
            )
        )
        _validate_kernel_receipt(
            admission_receipt,
            operation=ControlledOperationCommandKind.ADMIT,
            certainty=ExternalEffectCertainty.NO_EFFECT,
        )
        record = self.repository.save_once(
            ComputeExecutionRecord(
                request=request,
                admission_proof_digest=proof.proof_digest,
                controlled_operation_admission_receipt_digest=(
                    admission_receipt.receipt_digest
                ),
            )
        )
        if record.provider_handle is not None or record.result is not None:
            return record
        try:
            outcome = self.route.dispatch(request)
        except ComputeLifecycleError as exc:
            self._settle_failure(context, request, exc)
            raise
        return self._settle_outcome(context, record, outcome)

    def observe(
        self,
        *,
        context: KernelCommandContext,
        execution_id: str,
    ) -> ComputeExecutionRecord:
        record = self._require_record(context, execution_id)
        if record.result is not None:
            return record
        if record.provider_handle is None:
            raise ComputeLifecycleError(
                "compute_provider_handle_unavailable",
                "dispatch is unresolved; observe must reconcile the original identity",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            )
        outcome = self.route.observe(record.request, record.provider_handle)
        return self._settle_outcome(context, record, outcome)

    def cancel(
        self,
        *,
        context: KernelCommandContext,
        execution_id: str,
    ) -> ComputeExecutionRecord:
        record = self._require_record(context, execution_id)
        if record.result is not None:
            return record
        if record.provider_handle is None:
            raise ComputeLifecycleError(
                "compute_provider_handle_unavailable",
                "cannot issue cancellation without the original opaque provider handle",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            )
        cancel_intent = canonical_sha256_digest(
            {
                "operation_id": record.request.operation_id,
                "execution_id": record.request.execution_id,
                "route_id": record.request.route.route_id,
                "provider_handle": record.provider_handle,
                "action": "cancel",
            }
        )
        receipt = self.controlled_operations.execute(
            ControlledOperationApplicationCommand(
                context=_phase_context(
                    context,
                    request=record.request,
                    phase="controlled-cancel",
                    identity_digest=cancel_intent,
                ),
                operation=ControlledOperationCommandKind.CANCEL,
                operation_id=record.request.operation_id,
                intent_digest=cancel_intent,
                payload={
                    **_safe_operation_payload(record.request, phase="cancel"),
                    "provider_handle": record.provider_handle,
                    "redispatch_performed": False,
                },
            )
        )
        _validate_kernel_receipt(
            receipt,
            operation=ControlledOperationCommandKind.CANCEL,
            certainty=ExternalEffectCertainty.NO_EFFECT,
        )
        try:
            outcome = self.route.cancel(record.request, record.provider_handle)
        except ComputeLifecycleError as exc:
            self._settle_failure(context, record.request, exc)
            raise
        return self._settle_outcome(context, record, outcome)

    def _settle_outcome(
        self,
        context: KernelCommandContext,
        record: ComputeExecutionRecord,
        outcome: ComputeRouteOutcome,
    ) -> ComputeExecutionRecord:
        command_kind = (
            ControlledOperationCommandKind.RECONCILE
            if outcome.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            else ControlledOperationCommandKind.OBSERVE
        )
        receipt = self.controlled_operations.execute(
            ControlledOperationApplicationCommand(
                context=_phase_context(
                    context,
                    request=record.request,
                    phase=f"controlled-{command_kind.value}",
                    identity_digest=outcome.receipt_digest,
                ),
                operation=command_kind,
                operation_id=record.request.operation_id,
                intent_digest=record.request.request_digest,
                payload={
                    **_safe_operation_payload(record.request, phase=command_kind.value),
                    "route_receipt_digest": outcome.receipt_digest,
                    "provider_handle": outcome.provider_handle,
                    "result_handle": outcome.provider_handle,
                    "terminal_result_id": (
                        outcome.terminal_result.result_id
                        if outcome.terminal_result is not None
                        else None
                    ),
                    "terminal_receipt_digest": (
                        outcome.terminal_result.terminal_receipt_digest
                        if outcome.terminal_result is not None
                        else None
                    ),
                    "effect_certainty": outcome.effect_certainty.value,
                    "mutation_applied": outcome.mutation_applied,
                    "fallback_performed": False,
                    "redispatch_performed": False,
                },
            )
        )
        _validate_kernel_receipt(
            receipt,
            operation=command_kind,
            certainty=outcome.effect_certainty,
        )
        updated = self.repository.bind_route_outcome(
            record.request.execution_id,
            expected_state_version=record.state_version,
            outcome=outcome,
        )
        if outcome.terminal_result is not None and self.continuations is not None:
            self.continuations.execute(
                ContinuationApplicationCommand(
                    context=_phase_context(
                        context,
                        request=record.request,
                        phase="continuation-register",
                        identity_digest=outcome.terminal_result.result_digest,
                    ),
                    operation=ContinuationCommandKind.REGISTER,
                    continuation_id=f"compute-result-{record.request.execution_id}",
                    source_version=updated.state_version,
                    payload={
                        "source_ref": (
                            "compute-result:"
                            f"{outcome.terminal_result.result_id}"
                        ),
                        "source_digest": outcome.terminal_result.result_digest,
                        "recipient_actor_id": record.request.owner_agent_member_id,
                        "resume_strategy": "durable_runtime_signal",
                    },
                )
            )
        return updated

    def _settle_failure(
        self,
        context: KernelCommandContext,
        request: ComputeExecutionRequest,
        error: ComputeLifecycleError,
    ) -> None:
        command_kind = (
            ControlledOperationCommandKind.RECONCILE
            if error.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            else ControlledOperationCommandKind.OBSERVE
        )
        self.controlled_operations.execute(
            ControlledOperationApplicationCommand(
                context=_phase_context(
                    context,
                    request=request,
                    phase=f"controlled-{command_kind.value}-failure",
                    identity_digest=canonical_sha256_digest(
                        {
                            "request_digest": request.request_digest,
                            "error_code": error.error_code,
                            "diagnostic_id": error.diagnostic_id,
                        }
                    ),
                ),
                operation=command_kind,
                operation_id=request.operation_id,
                intent_digest=request.request_digest,
                payload={
                    **_safe_operation_payload(request, phase=command_kind.value),
                    "error_code": error.error_code,
                    "diagnostic_id": error.diagnostic_id,
                    "effect_certainty": error.effect_certainty.value,
                    "mutation_applied": error.mutation_applied,
                    "fallback_performed": False,
                    "redispatch_performed": False,
                },
            )
        )

    def _require_record(
        self,
        context: KernelCommandContext,
        execution_id: str,
    ) -> ComputeExecutionRecord:
        record = self.repository.get(execution_id)
        if record is None:
            raise ComputeLifecycleError(
                "compute_execution_not_found",
                "Compute execution does not exist",
            )
        self._validate_context(context, record.request)
        return record

    @staticmethod
    def _validate_context(
        context: KernelCommandContext,
        request: ComputeExecutionRequest,
    ) -> None:
        if (
            context.owner_plugin_id != "openzyme.compute"
            or context.session_id != request.session_id
            or context.actor_id != request.owner_agent_member_id
            or context.authority_lease_id != request.authority_lease_id
            or context.authority_generation != request.authority_generation
            or context.authority_fence != request.authority_fence
            or context.workspace_generation != request.workspace_generation
            or context.route_id != request.route.route_id
            or context.idempotency_key != request.idempotency_key
        ):
            raise ComputeLifecycleError(
                "compute_command_context_mismatch",
                "Compute command does not bind the exact owner, authority, workspace and route",
            )


def _validate_proof(
    context: KernelCommandContext,
    request: ComputeExecutionRequest,
    proof: ComputeAdmissionProof,
) -> None:
    if (
        proof.session_id,
        proof.owner_agent_member_id,
        proof.authority_lease_id,
        proof.authority_generation,
        proof.authority_fence,
        proof.workspace_id,
        proof.workspace_generation,
        proof.source_revision_id,
        proof.clean_observation_digest,
        proof.lfs_closure_manifest_digest,
        proof.route_id,
        proof.inventory_generation,
        proof.capability_binding_digest,
    ) != (
        request.session_id,
        request.owner_agent_member_id,
        request.authority_lease_id,
        request.authority_generation,
        request.authority_fence,
        request.workspace_id,
        request.workspace_generation,
        request.source_revision_id,
        request.clean_observation_digest,
        request.lfs_closure_manifest_digest,
        request.route.route_id,
        request.route.inventory_generation,
        context.capability_binding_digest,
    ):
        raise ComputeLifecycleError(
            "compute_admission_proof_mismatch",
            "authority, revision, LFS, workspace, inventory or route changed before admission",
        )


def _safe_operation_payload(
    request: ComputeExecutionRequest,
    *,
    phase: str,
) -> dict[str, JsonValue]:
    return {
        "phase": phase,
        "invocation_id": request.invocation_id,
        "execution_id": request.execution_id,
        "session_id": request.session_id,
        "owner_agent_member_id": request.owner_agent_member_id,
        "workspace_id": request.workspace_id,
        "authority_operation": "external_compute",
        "scope_id": request.workspace_id,
        "workspace_generation": request.workspace_generation,
        "source_revision_id": request.source_revision_id,
        "source_commit": request.source_commit,
        "source_tree": request.source_tree,
        "lfs_closure_manifest_digest": request.lfs_closure_manifest_digest,
        "clean_observation_digest": request.clean_observation_digest,
        "deadline": request.absolute_deadline,
        "workload_id": request.workload.workload_id,
        "workload_digest": request.workload.workload_digest,
        "route_id": request.route.route_id,
        "target_id": request.route.target_id,
        "inventory_generation": request.route.inventory_generation,
        "inventory_digest": request.route.inventory_digest,
        "qualification_digest": request.route.qualification_digest,
        "fallback_performed": False,
    }


def _phase_context(
    context: KernelCommandContext,
    *,
    request: ComputeExecutionRequest,
    phase: str,
    identity_digest: str,
) -> KernelCommandContext:
    require_digest(identity_digest, field_name="identity_digest")
    suffix = identity_digest.removeprefix("sha256:")
    return replace(
        context,
        command_id=f"{request.operation_id}.{phase}.{suffix}",
        idempotency_key=(
            f"{request.idempotency_key}.{phase}.{suffix}"
        ),
    )


def _validate_kernel_receipt(
    receipt: KernelMutationReceipt,
    *,
    operation: ControlledOperationCommandKind,
    certainty: ExternalEffectCertainty,
) -> None:
    if (
        receipt.service_id != "controlled_operation"
        or receipt.operation != operation.value
        or receipt.effect_certainty is not certainty
        or receipt.fallback_performed
        or not receipt.mutation_applied
    ):
        raise ComputeLifecycleError(
            "compute_controlled_operation_receipt_mismatch",
            "Kernel ControlledOperation receipt does not match the Compute phase",
            effect_certainty=certainty,
            mutation_applied=(
                None
                if certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
                else certainty is not ExternalEffectCertainty.NO_EFFECT
            ),
        )


def _validate_terminal_result(
    request: ComputeExecutionRequest,
    provider_handle: str | None,
    result: ExecutionResultReceipt,
) -> None:
    expected_result_contract_digest = canonical_sha256_digest(
        request.workload.result_contract.to_dict()
    )
    if (
        provider_handle is None
        or result.invocation_id != request.invocation_id
        or result.operation_id != request.operation_id
        or result.execution_id != request.execution_id
        or result.route_id != request.route.route_id
        or result.workload_digest != request.workload.workload_digest
        or result.result_contract_digest != expected_result_contract_digest
    ):
        raise ComputeLifecycleError(
            "compute_terminal_result_identity_mismatch",
            "terminal result does not bind the exact invocation, operation, route and contract",
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            mutation_applied=True,
        )


__all__ = [
    "COMPUTE_EXECUTION_RECORD_SCHEMA",
    "COMPUTE_EXECUTION_REQUEST_SCHEMA",
    "COMPUTE_RESULT_PROJECTION_SCHEMA",
    "ComputeAdmissionProof",
    "ComputeAdmissionVerifier",
    "ComputeExecutionApplicationService",
    "ComputeExecutionRecord",
    "ComputeExecutionRepository",
    "ComputeExecutionRequest",
    "ComputeLifecycleError",
    "ComputeRouteOutcome",
    "ComputeRoutePort",
    "InMemoryComputeExecutionRepository",
]
