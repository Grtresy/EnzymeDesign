from __future__ import annotations

import pytest

from openzyme_core import ControlledOperationExecutionLeaseService
from openzyme_core import CoreRepositories
from openzyme_core import OptimisticStateConflictError
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import RetryEligibility
from openzyme_domain import Session


NOW = "2026-08-18T00:00:00+00:00"


def _repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:", check_same_thread=False)
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    repositories.sessions.save(
        Session.create(
            session_id="session_1",
            project_id="project_1",
            title="Workspace execution authority",
            objective="Prove one worker and monotonic fencing",
        )
    )
    operation = ControlledOperation(
        operation_id="operation_1",
        session_id="session_1",
        logical_operation_key="workspace-job:execution_1",
        operation_digest="sha256:" + "1" * 64,
        params_digest="sha256:" + "2" * 64,
        backend_category="hpc",
        status=ControlledOperationStatus.RUNNING,
        route_policy_id="workspace_revision_execution@1",
        selected_backend="workspace_revision_job",
        created_at=NOW,
        updated_at=NOW,
    )
    repositories.controlled_operations.save(operation)
    repositories.controlled_operation_executions.add(
        ControlledOperationExecution(
            execution_id="execution_1",
            operation_id=operation.operation_id,
            session_id=operation.session_id,
            owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
            operation_digest=operation.operation_digest,
            approval_digest=None,
            route_policy_id="workspace_revision_execution@1",
            selected_backend="workspace_revision_job",
            adapter_policy_id="workspace_revision_execution_adapter@1",
            input_identity_digest="sha256:" + "3" * 64,
            expected_output_contract_digest="sha256:" + "4" * 64,
            runtime_identity_digest="sha256:" + "5" * 64,
            lifecycle_state=ControlledOperationExecutionLifecycle.READY,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
            dispatch_generation=0,
            state_version=1,
            fencing_token=0,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    return repositories


def test_duplicate_worker_is_rejected_and_expiry_advances_fence() -> None:
    repositories = _repositories()
    leases = ControlledOperationExecutionLeaseService(repositories)

    first = leases.claim(
        "execution_1",
        worker_id="worker-1",
        lease_seconds=30,
        now_iso=NOW,
    )
    assert first is not None
    assert first.lease_owner == "worker-1"
    assert first.fencing_token == 1

    duplicate = leases.claim(
        "execution_1",
        worker_id="worker-2",
        lease_seconds=30,
        now_iso="2026-08-18T00:00:10+00:00",
    )
    assert duplicate is None

    replacement = leases.claim(
        "execution_1",
        worker_id="worker-2",
        lease_seconds=30,
        now_iso="2026-08-18T00:00:31+00:00",
    )
    assert replacement is not None
    assert replacement.lease_owner == "worker-2"
    assert replacement.fencing_token == 2


def test_stale_worker_callback_cannot_release_replacement_lease() -> None:
    repositories = _repositories()
    leases = ControlledOperationExecutionLeaseService(repositories)
    first = leases.claim(
        "execution_1",
        worker_id="worker-1",
        lease_seconds=30,
        now_iso=NOW,
    )
    assert first is not None and first.lease_token is not None
    replacement = leases.claim(
        "execution_1",
        worker_id="worker-2",
        lease_seconds=30,
        now_iso="2026-08-18T00:00:31+00:00",
    )
    assert replacement is not None

    with pytest.raises(
        OptimisticStateConflictError,
        match="lease is no longer authoritative",
    ):
        leases.release(
            first.execution_id,
            lease_token=first.lease_token,
            fencing_token=first.fencing_token,
            expected_state_version=first.state_version,
            now_iso="2026-08-18T00:00:32+00:00",
        )

    current = repositories.controlled_operation_executions.get("execution_1")
    assert current is not None
    assert current.lease_owner == "worker-2"
    assert current.lease_token == replacement.lease_token
    assert current.fencing_token == replacement.fencing_token
