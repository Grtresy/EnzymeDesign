from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import ContinuationDeliveryHostAuthority
from openzyme_core import DurableExecutionHostAuthority
from openzyme_core import MutationScopeService
from openzyme_core import MutationScopeError
from openzyme_core import MutationWriterTurnFactory
from openzyme_core import SandboxHostAuthorityError
from openzyme_core import SandboxHostCallContext
from openzyme_core import SandboxProcessHostAuthority
from openzyme_core import SessionTurnHostAuthority
from openzyme_core import apply_sqlite_migrations
from openzyme_core import bind_mutation_write_authority
from openzyme_core import connect_sqlite
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ContinuationDeliveryState
from openzyme_domain import ContinuationResumeStrategy
from openzyme_domain import ContinuationState
from openzyme_domain import ContinuationStateStatus
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import MutationScopeKind
from openzyme_domain import MutationWriterKind
from openzyme_domain import RetryEligibility
from openzyme_domain import Session


NOW = "2026-07-21T00:00:00+00:00"


def _repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _claimed_execution() -> ControlledOperationExecution:
    return ControlledOperationExecution(
        execution_id="exec_authority",
        operation_id="op_authority",
        session_id="sess_authority",
        owner_mode=ControlledOperationOwnerMode.DURABLE_ASYNC_V1,
        operation_digest="sha256:operation",
        approval_digest="sha256:approval",
        route_policy_id="fixture_v1",
        selected_backend="fixture",
        adapter_policy_id="fixture_adapter_v1",
        input_identity_digest="sha256:inputs",
        expected_output_contract_digest="sha256:outputs",
        runtime_identity_digest="sha256:runtime",
        lifecycle_state=ControlledOperationExecutionLifecycle.CLAIMED,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
        dispatch_generation=1,
        state_version=3,
        fencing_token=2,
        lease_owner="worker:exec",
        lease_token="lease_exec",
        lease_expires_at="2026-07-21T00:01:00+00:00",
        created_at=NOW,
        updated_at=NOW,
    )


def test_context_accepts_one_exact_sandbox_process_owner() -> None:
    repositories = _repositories()
    owner = SandboxProcessHostAuthority(
        session_id="sess_authority",
        sandbox_workspace_id="sw_authority",
        sandbox_run_id="srun_authority",
        process_epoch=7,
    )
    context = SandboxHostCallContext(repositories=repositories, owner=owner)

    assert context.session_id == "sess_authority"
    assert (
        context.require_sandbox_process(
            session_id="sess_authority",
            sandbox_workspace_id="sw_authority",
            sandbox_run_id="srun_authority",
            process_epoch=7,
        )
        == owner
    )

    with pytest.raises(SandboxHostAuthorityError, match="process identity"):
        context.require_sandbox_process(
            session_id="sess_authority",
            sandbox_workspace_id="sw_authority",
            sandbox_run_id="srun_authority",
            process_epoch=8,
        )


def test_context_rejects_mixed_or_cross_session_authority() -> None:
    repositories = _repositories()
    process = SandboxProcessHostAuthority(
        session_id="sess_authority",
        sandbox_workspace_id="sw_authority",
        sandbox_run_id="srun_authority",
        process_epoch=1,
    )
    session = SessionTurnHostAuthority(
        session_id="sess_authority",
        lease_token="lease_session",
        fencing_token=1,
    )

    with pytest.raises(SandboxHostAuthorityError, match="exactly one"):
        SandboxHostCallContext(
            repositories=repositories,
            owner=(process, session),  # type: ignore[arg-type]
        )

    context = SandboxHostCallContext(repositories=repositories, owner=process)
    with pytest.raises(SandboxHostAuthorityError, match="session boundary"):
        context.require_session("sess_other")


def test_durable_execution_context_requires_exact_claim_identity() -> None:
    repositories = _repositories()
    execution = _claimed_execution()
    owner = DurableExecutionHostAuthority.from_execution(execution)
    context = SandboxHostCallContext(repositories=repositories, owner=owner)

    assert context.require_execution(execution) == owner

    with pytest.raises(SandboxHostAuthorityError, match="does not match"):
        context.require_execution(replace(execution, fencing_token=3))
    with pytest.raises(SandboxHostAuthorityError, match="claimed execution lease"):
        DurableExecutionHostAuthority.from_execution(
            replace(execution, lease_token=None)
        )


def test_continuation_context_requires_exact_delivery_lease_and_fence() -> None:
    repositories = _repositories()
    continuation = ContinuationState(
        continuation_id="continuation_authority",
        session_id="sess_authority",
        operation_id="op_authority",
        sandbox_run_id="srun_authority",
        approval_id="approval_authority",
        status=ContinuationStateStatus.CLAIMED,
        created_at=NOW,
        updated_at=NOW,
        sandbox_workspace_id="sw_authority",
        process_epoch=7,
        resume_strategy=ContinuationResumeStrategy.ATTACHED_PROCESS,
        delivery_state=ContinuationDeliveryState.CLAIMED,
        delivery_generation=2,
        delivery_lease_token="lease_delivery",
        delivery_fencing_token=3,
    )
    owner = ContinuationDeliveryHostAuthority.from_continuation(continuation)
    context = SandboxHostCallContext(repositories=repositories, owner=owner)

    assert context.require_continuation(continuation) == owner
    with pytest.raises(SandboxHostAuthorityError, match="does not match"):
        context.require_continuation(
            replace(continuation, delivery_fencing_token=4)
        )
    with pytest.raises(SandboxHostAuthorityError, match="claimed delivery lease"):
        ContinuationDeliveryHostAuthority.from_continuation(
            replace(continuation, delivery_lease_token=None)
        )


def test_child_mutation_writer_is_derived_from_context_authority() -> None:
    repositories = _repositories()
    session = Session.create(
        session_id="sess_authority",
        project_id="proj_authority",
        title="Authority",
        objective="Keep Host authorities distinct",
    )
    repositories.sessions.save(session)
    service = MutationScopeService(repositories, now=lambda: NOW)
    scope = service.open_scope(
        session_id=session.session_id,
        scope_kind=MutationScopeKind.ATTEMPT,
        scope_ref="attempt:authority",
    )
    root = service.register_writer(
        scope_id=scope.scope_id,
        owner_kind=MutationWriterKind.SANDBOX_PROCESS,
        owner_ref="sandbox:srun_authority",
        process_epoch=7,
        trusted_root=True,
    )
    root_authority = service.authority_for_writer(root.writer_id)
    factory = MutationWriterTurnFactory(
        repository_scope_factory=lambda: _static_repository_scope(repositories)
    )
    context = SandboxHostCallContext(
        repositories=repositories,
        owner=SandboxProcessHostAuthority(
            session_id=session.session_id,
            sandbox_workspace_id="sw_authority",
            sandbox_run_id="srun_authority",
            process_epoch=7,
        ),
        mutation_authority=root_authority,
        mutation_writer_scope_factory=factory.open,
    )

    with bind_mutation_write_authority(root_authority):
        with context.child_mutation_writer(
            owner_kind=MutationWriterKind.ARTIFACT_PUBLISHER,
            owner_ref="fetch:declared-outputs",
            process_epoch=7,
        ) as child_authority:
            assert child_authority is not None
            child = repositories.mutation_writers.get(child_authority.writer_id)
            assert child is not None
            assert child.parent_writer_id == root.writer_id
            assert child.owner_kind is MutationWriterKind.ARTIFACT_PUBLISHER

    retired = repositories.mutation_writers.get(str(child.writer_id))
    assert retired is not None
    assert retired.state.is_terminal

    service.begin_freeze(scope.scope_id)
    with bind_mutation_write_authority(root_authority):
        with pytest.raises(MutationScopeError, match="frozen"):
            with context.child_mutation_writer(
                owner_kind=MutationWriterKind.ARTIFACT_PUBLISHER,
                owner_ref="fetch:after-freeze",
                process_epoch=7,
            ):
                pass


def test_production_sandbox_host_path_has_no_weak_scope_escape_hatch() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    sandbox_runtime = (
        repository_root
        / "packages/openzyme-core/src/openzyme_core/sandbox_runtime.py"
    ).read_text(encoding="utf-8")
    teammates = (
        repository_root / "packages/openzyme-core/src/openzyme_core/teammates.py"
    ).read_text(encoding="utf-8")
    execution = (
        repository_root
        / "packages/openzyme-engines/src/openzyme_engines/execution.py"
    ).read_text(encoding="utf-8")
    host_gateway = (
        repository_root
        / "apps/openzyme-host-api/src/openzyme_host_api/sandbox_host_gateway.py"
    ).read_text(encoding="utf-8")

    assert "SandboxHpcFetchExecutor" not in sandbox_runtime
    assert "Callable[...," not in sandbox_runtime
    assert "sandbox_process_repository_scope_factory" not in execution
    assert "repositories: Any | None" not in execution
    assert "repository_scope_factory" not in execution
    assert 'getattr(self.engine, "repository_scope_factory"' not in host_gateway
    assert 'hasattr(self.engine, "repository_scope_factory")' not in host_gateway
    assert 'getattr(execution_engine, "execute_sandbox_adapter_operation"' not in teammates
    assert 'getattr(execution_engine, "fetch_sandbox_hpc_outputs"' not in teammates


@contextmanager
def _static_repository_scope(
    repositories: CoreRepositories,
) -> Iterator[CoreRepositories]:
    yield repositories
