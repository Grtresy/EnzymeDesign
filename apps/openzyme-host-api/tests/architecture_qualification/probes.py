from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from datetime import timedelta
import hashlib
import sqlite3
from typing import Any

from openzyme_core import ControlledOperationResultArtifactRef
from openzyme_core import ControlledOperationExecutionLeaseService
from openzyme_core import ContinuationDeliveryHostAuthority
from openzyme_core import DURABLE_RESULT_ENVELOPE_MAX_BYTES
from openzyme_core import DurableExecutionHostAuthority
from openzyme_core import RuntimeWriteFencingError
from openzyme_core import OptimisticStateConflictError
from openzyme_core import SandboxHostAuthorityError
from openzyme_core import SandboxProcessHostAuthority
from openzyme_core import SessionTurnHostAuthority
from openzyme_core import controlled_operation_artifact_set_digest
from openzyme_domain import ArtifactKind
from openzyme_domain import MutationWriterKind
from openzyme_host_api.architecture_qualification import canonical_json_bytes
from openzyme_core.reliability_repositories import (
    ControlledOperationExecutionRepository,
)

from .composition import ProductionComposition
from .external_ports import ControlledExternalPortError
from .external_ports import QualificationDurableRouteAdapter


@dataclass(frozen=True, slots=True)
class AuthorityCompositionProbe:
    process_authority_succeeded: bool
    stale_turn_authority_rejected: bool
    caller_authority_rejected: bool
    launching_fencing_token: int
    continuation_fencing_token: int
    persisted_objective: str


@dataclass(frozen=True, slots=True)
class IdentitySemanticsProbe:
    member_set_digest_forward: str
    member_set_digest_reverse: str
    ordered_digest_forward: str
    ordered_digest_reverse: str
    duplicate_member_rejected: bool


@dataclass(frozen=True, slots=True)
class ExecutionDeliveryAuthorityProbe:
    execution_authority_succeeded: bool
    stale_execution_authority_rejected: bool
    delivery_authority_succeeded: bool
    mixed_delivery_authority_rejected: bool
    execution_fencing_token: int
    delivery_fencing_token: int


@dataclass(frozen=True, slots=True)
class BulkIdentityProbe:
    artifact_count: int
    artifact_set_digest: str
    compact_envelope_size: int
    expanded_identity_size: int
    owner_limit: int


def prepare_backend_handle_for_probe(
    composition: ProductionComposition,
    *,
    execution_id: str,
) -> str:
    with composition.dependencies.v3_repository_scope(mode="read") as repositories:
        execution = repositories.controlled_operation_executions.get(execution_id)
        request = (
            repositories.controlled_operation_dispatch_requests.get_by_execution_id(
                execution_id
            )
        )
    if execution is None or request is None:
        raise RuntimeError("qualification dispatch identity is absent")
    adapter = composition.dependencies.v3_durable_route_adapters[
        execution.route_policy_id
    ]
    return adapter.prepare_dispatch(
        replace(execution, dispatch_generation=execution.dispatch_generation + 1),
        request,
    )


def probe_supervisor_database_busy(
    composition: ProductionComposition,
    *,
    supervisor: Any,
    monkeypatch: Any,
) -> tuple[tuple[Any, ...], bool]:
    original = ControlledOperationExecutionRepository.list_claimable

    def database_busy(self: object, *, now_iso: str, limit: int) -> None:
        del self, now_iso, limit
        raise sqlite3.OperationalError("database is locked")

    with monkeypatch.context() as scoped:
        scoped.setattr(
            ControlledOperationExecutionRepository,
            "list_claimable",
            database_busy,
        )
        outcomes = composition.run_manual_durable_tick(supervisor)
    return (
        outcomes,
        ControlledOperationExecutionRepository.list_claimable is original,
    )


def probe_stale_execution_lease_release(
    composition: ProductionComposition,
    *,
    execution_id: str,
    session_id: str,
    stale_claim: Mapping[str, object],
) -> bool:
    try:
        with composition.dependencies.v3_mutation_writer_scope(
            session_id=session_id,
            owner_kind=MutationWriterKind.CONTROLLED_OPERATION,
            owner_ref="qualification:stale-pre-dispatch-release",
        ):
            with composition.dependencies.v3_repository_scope(
                mode="connection"
            ) as repositories:
                ControlledOperationExecutionLeaseService(repositories).release(
                    execution_id,
                    lease_token=str(stale_claim["lease_token"]),
                    fencing_token=int(stale_claim["fencing_token"]),
                    expected_state_version=int(stale_claim["state_version"]),
                )
    except OptimisticStateConflictError:
        return True
    return False


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def decode_controlled_observation(
    composition: ProductionComposition,
    *,
    execution_id: str,
    response: dict[str, object],
) -> dict[str, object]:
    """Decode a controlled port response against the persisted execution identity."""

    with composition.dependencies.v3_repository_scope(mode="read") as repositories:
        execution = repositories.controlled_operation_executions.get(execution_id)
    if execution is None:
        raise RuntimeError("qualification execution is absent")
    adapter = composition.dependencies.v3_durable_route_adapters.get(
        execution.route_policy_id
    )
    if not isinstance(adapter, QualificationDurableRouteAdapter):
        raise RuntimeError("qualification execution lost its controlled adapter")
    observation = adapter._observation(response, execution=execution)  # noqa: SLF001
    materialized = observation.materialized_result
    return {
        "backend_handle_ref": observation.backend_handle_ref,
        "effect_certainty": observation.effect_certainty.value,
        "kind": observation.kind.value,
        "materialized_envelope": (
            None
            if materialized is None
            else dict(materialized.bounded_result_envelope)
        ),
        "retry_eligibility": observation.retry_eligibility.value,
        "terminal_outcome": (
            None
            if observation.terminal_outcome is None
            else observation.terminal_outcome.value
        ),
    }


def controlled_observation_rejection_code(
    composition: ProductionComposition,
    *,
    execution_id: str,
    response: dict[str, object],
) -> str | None:
    try:
        decode_controlled_observation(
            composition,
            execution_id=execution_id,
            response=response,
        )
    except ControlledExternalPortError as exc:
        return exc.error_code
    return None


def probe_authority_composition(
    composition: ProductionComposition,
    *,
    session_id: str,
) -> AuthorityCompositionProbe:
    """Exercise typed turn/process authority against the real Host binding."""

    launching_owner = "qualification:launching-turn"
    with composition.dependencies.v3_mutation_writer_scope(
        session_id=session_id,
        owner_kind=MutationWriterKind.RUNTIME_COMMAND,
        owner_ref=launching_owner,
    ):
        with composition.dependencies.v3_repository_scope(
            mode="connection"
        ) as repositories:
            acquired = repositories.session_runtime_leases.acquire(
                session_id=session_id,
                owner_id=launching_owner,
                mode="test",
                lease_seconds=60,
            )
            if not acquired.acquired or acquired.lease is None:
                raise RuntimeError("qualification could not acquire launching lease")
            launching_lease = acquired.lease
            registry = composition.dependencies.build_v3_engine_registry(
                repositories,
                launching_lease,
            )
            binding = composition.dependencies.build_v3_sandbox_host_binding(
                registry,
                launching_lease,
            )

    continuation_owner = "qualification:continuation-turn"
    with composition.dependencies.v3_mutation_writer_scope(
        session_id=session_id,
        owner_kind=MutationWriterKind.RUNTIME_COMMAND,
        owner_ref=continuation_owner,
    ):
        with composition.dependencies.v3_repository_scope(
            mode="connection"
        ) as repositories:
            released = repositories.session_runtime_leases.release(
                session_id=session_id,
                owner_id=launching_owner,
                lease_token=launching_lease.lease_token,
            )
            if released is None:
                raise RuntimeError("qualification could not retire launching lease")
            replacement = repositories.session_runtime_leases.acquire(
                session_id=session_id,
                owner_id=continuation_owner,
                mode="test",
                lease_seconds=60,
            )
            if not replacement.acquired or replacement.lease is None:
                raise RuntimeError("qualification could not acquire continuation lease")
            continuation_lease = replacement.lease

    expected_objective = "continued under typed sandbox-process authority"
    with binding.context_factory(
        SandboxProcessHostAuthority(
            session_id=session_id,
            sandbox_workspace_id="sw_authority_composition",
            sandbox_run_id="srun_authority_composition",
            process_epoch=3,
        )
    ) as process_context:
        session = process_context.repositories.sessions.get(session_id)
        if session is None:
            raise RuntimeError("qualification session disappeared")
        process_context.repositories.sessions.save(
            replace(session, objective=expected_objective)
        )

    stale_rejected = False
    try:
        with binding.context_factory(
            SessionTurnHostAuthority.from_lease(launching_lease)
        ):
            pass
    except (RuntimeWriteFencingError, SandboxHostAuthorityError):
        stale_rejected = True

    caller_rejected = False
    try:
        with binding.context_factory(  # type: ignore[arg-type]
            {
                "fencing_token": continuation_lease.fencing_token,
                "lease_token": continuation_lease.lease_token,
                "session_id": session_id,
            }
        ):
            pass
    except SandboxHostAuthorityError:
        caller_rejected = True

    with composition.dependencies.v3_repository_scope(mode="read") as repositories:
        persisted = repositories.sessions.get(session_id)
    if persisted is None:
        raise RuntimeError("qualification session disappeared after authority probe")
    return AuthorityCompositionProbe(
        process_authority_succeeded=persisted.objective == expected_objective,
        stale_turn_authority_rejected=stale_rejected,
        caller_authority_rejected=caller_rejected,
        launching_fencing_token=launching_lease.fencing_token,
        continuation_fencing_token=continuation_lease.fencing_token,
        persisted_objective=persisted.objective,
    )


def probe_identity_semantics() -> IdentitySemanticsProbe:
    refs = tuple(
        ControlledOperationResultArtifactRef(
            artifact_id=f"artifact_{index}",
            kind=ArtifactKind.RESULT,
            relative_path=f"results/{index}.json",
            artifact_digest=_digest({"artifact": index}),
        )
        for index in range(3)
    )
    forward_ids = [ref.artifact_id for ref in refs]
    reverse_ids = list(reversed(forward_ids))
    duplicate_rejected = False
    try:
        controlled_operation_artifact_set_digest((refs[0], refs[0]))
    except ValueError:
        duplicate_rejected = True
    return IdentitySemanticsProbe(
        member_set_digest_forward=controlled_operation_artifact_set_digest(refs),
        member_set_digest_reverse=controlled_operation_artifact_set_digest(
            tuple(reversed(refs))
        ),
        ordered_digest_forward=_digest(forward_ids),
        ordered_digest_reverse=_digest(reverse_ids),
        duplicate_member_rejected=duplicate_rejected,
    )


def probe_execution_delivery_authority(
    composition: ProductionComposition,
    *,
    execution_id: str,
    delivery_continuation_id: str,
) -> ExecutionDeliveryAuthorityProbe:
    """Exercise durable execution and continuation delivery Host authorities."""

    with composition.dependencies.v3_mutation_writer_scope(
        session_id=_execution_session_id(composition, execution_id),
        owner_kind=MutationWriterKind.CONTROLLED_OPERATION,
        owner_ref=f"qualification:authority-claim:{execution_id}",
    ):
        with composition.dependencies.v3_repository_scope(
            mode="connection"
        ) as repositories:
            claimed_execution = ControlledOperationExecutionLeaseService(
                repositories
            ).claim(
                execution_id,
                worker_id="qualification:authority-execution",
                lease_seconds=60,
            )
            if claimed_execution is None:
                raise RuntimeError("qualification execution was not claimable")
            registry = composition.dependencies.build_v3_engine_registry(
                repositories,
                None,
            )
            binding = composition.dependencies.build_v3_sandbox_host_binding(
                registry,
                None,
            )

    execution_authority = DurableExecutionHostAuthority.from_execution(
        claimed_execution
    )
    execution_succeeded = False
    with binding.context_factory(execution_authority) as execution_context:
        operation = execution_context.repositories.controlled_operations.get(
            claimed_execution.operation_id
        )
        execution_succeeded = operation is not None

    with composition.dependencies.v3_mutation_writer_scope(
        session_id=claimed_execution.session_id,
        owner_kind=MutationWriterKind.CONTROLLED_OPERATION,
        owner_ref=f"qualification:authority-release:{execution_id}",
    ):
        with composition.dependencies.v3_repository_scope(
            mode="connection"
        ) as repositories:
            ControlledOperationExecutionLeaseService(repositories).release(
                execution_id,
                lease_token=str(claimed_execution.lease_token),
                fencing_token=claimed_execution.fencing_token,
                expected_state_version=claimed_execution.state_version,
            )

    stale_execution_rejected = False
    try:
        with binding.context_factory(execution_authority):
            pass
    except SandboxHostAuthorityError:
        stale_execution_rejected = True

    with composition.dependencies.v3_repository_scope(mode="read") as repositories:
        ready_continuation = repositories.continuation_deliveries.get(
            delivery_continuation_id
        )
    if ready_continuation is None:
        raise RuntimeError("qualification delivery continuation is absent")
    now = datetime.now(tz=UTC).replace(microsecond=0)
    now_iso = now.isoformat()
    expires_at = (now + timedelta(seconds=60)).isoformat()
    with composition.dependencies.v3_mutation_writer_scope(
        session_id=ready_continuation.session_id,
        owner_kind=MutationWriterKind.CONTINUATION_DELIVERY,
        owner_ref=(
            f"qualification:authority-delivery:{delivery_continuation_id}"
        ),
        process_epoch=ready_continuation.process_epoch,
    ):
        with composition.dependencies.v3_repository_scope(
            mode="connection"
        ) as repositories:
            claimed_delivery = repositories.continuation_deliveries.claim(
                delivery_continuation_id,
                expected_state_version=ready_continuation.state_version,
                delivery_generation=ready_continuation.delivery_generation,
                claim_owner="qualification:authority-delivery",
                lease_token="continuation_lease_qualification_authority",
                lease_expires_at=expires_at,
                now_iso=now_iso,
                updated_at=now_iso,
            )

    delivery_authority = ContinuationDeliveryHostAuthority.from_continuation(
        claimed_delivery
    )
    delivery_succeeded = False
    with binding.context_factory(delivery_authority) as delivery_context:
        persisted = delivery_context.repositories.continuation_states.get(
            delivery_continuation_id
        )
        if persisted is not None:
            delivery_context.require_continuation(persisted)
            delivery_succeeded = True

    mixed_delivery_rejected = False
    try:
        with binding.context_factory(
            replace(
                delivery_authority,
                fencing_token=delivery_authority.fencing_token + 1,
            )
        ):
            pass
    except SandboxHostAuthorityError:
        mixed_delivery_rejected = True

    return ExecutionDeliveryAuthorityProbe(
        execution_authority_succeeded=execution_succeeded,
        stale_execution_authority_rejected=stale_execution_rejected,
        delivery_authority_succeeded=delivery_succeeded,
        mixed_delivery_authority_rejected=mixed_delivery_rejected,
        execution_fencing_token=claimed_execution.fencing_token,
        delivery_fencing_token=claimed_delivery.delivery_fencing_token,
    )


def _execution_session_id(
    composition: ProductionComposition,
    execution_id: str,
) -> str:
    with composition.dependencies.v3_repository_scope(mode="read") as repositories:
        execution = repositories.controlled_operation_executions.get(execution_id)
    if execution is None:
        raise RuntimeError("qualification execution is absent")
    return execution.session_id


def probe_bulk_identity_artifactization(
    *,
    artifact_count: int = 4_096,
) -> BulkIdentityProbe:
    if artifact_count < 1:
        raise ValueError("artifact_count must be positive")
    refs = tuple(
        ControlledOperationResultArtifactRef(
            artifact_id=f"artifact_bulk_{index:05d}",
            kind=ArtifactKind.RESULT,
            relative_path=f"bulk/{index:05d}/" + "identity-segment-" * 4 + ".json",
            artifact_digest=_digest({"bulk": index}),
        )
        for index in range(artifact_count)
    )
    artifact_set_digest = controlled_operation_artifact_set_digest(refs)
    reversed_digest = controlled_operation_artifact_set_digest(tuple(reversed(refs)))
    if reversed_digest != artifact_set_digest:
        raise AssertionError("bulk artifact identity became order-sensitive")
    compact = {
        "artifact_count": artifact_count,
        "artifact_set_digest": artifact_set_digest,
        "status": "succeeded",
    }
    expanded = [ref.identity() for ref in refs]
    return BulkIdentityProbe(
        artifact_count=artifact_count,
        artifact_set_digest=artifact_set_digest,
        compact_envelope_size=len(canonical_json_bytes(compact)),
        expanded_identity_size=len(canonical_json_bytes(expanded)),
        owner_limit=DURABLE_RESULT_ENVELOPE_MAX_BYTES,
    )


__all__ = [
    "AuthorityCompositionProbe",
    "BulkIdentityProbe",
    "ExecutionDeliveryAuthorityProbe",
    "IdentitySemanticsProbe",
    "controlled_observation_rejection_code",
    "decode_controlled_observation",
    "probe_authority_composition",
    "probe_bulk_identity_artifactization",
    "probe_execution_delivery_authority",
    "probe_identity_semantics",
    "prepare_backend_handle_for_probe",
    "probe_stale_execution_lease_release",
    "probe_supervisor_database_busy",
]
