from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from contextlib import nullcontext
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import replace
from typing import Iterator

from openzyme_core import ContinuationDeliveryHostAuthority
from openzyme_core import CoreRepositories
from openzyme_core import DurableExecutionHostAuthority
from openzyme_core import SandboxHostAuthorityError
from openzyme_core import SandboxHostCallContext
from openzyme_core import SandboxHostOwnerAuthority
from openzyme_core import SandboxMutationWriterScopeFactory
from openzyme_core import SandboxProcessHostAuthority
from openzyme_core import SessionTurnHostAuthority
from openzyme_domain import ControlledOperation
from openzyme_domain import MutationWriterKind
from openzyme_domain import SessionRuntimeLease
from openzyme_engines.execution import ExecutionEngine


@dataclass(frozen=True, slots=True)
class ExecutionEngineSandboxHostGateway:
    engine: ExecutionEngine

    def _bound_engine(self, context: SandboxHostCallContext) -> ExecutionEngine:
        if (
            self.engine.repositories is context.repositories
            and self.engine.sandbox_host_call_context_factory is None
        ):
            return self.engine
        return replace(
            self.engine,
            repositories=context.repositories,
            sandbox_host_call_context_factory=None,
        )

    @staticmethod
    def _validate_operation_owner(
        operation: ControlledOperation,
        context: SandboxHostCallContext,
    ) -> None:
        context.require_session(operation.session_id)
        owner = context.owner
        if isinstance(owner, SandboxProcessHostAuthority):
            context.require_sandbox_process(
                session_id=operation.session_id,
                sandbox_workspace_id=operation.sandbox_workspace_id,
                sandbox_run_id=operation.sandbox_run_id,
                process_epoch=owner.process_epoch,
            )
            return
        if isinstance(owner, DurableExecutionHostAuthority):
            if owner.operation_id != operation.operation_id:
                raise SandboxHostAuthorityError(
                    "durable Host context operation does not match the adapter call"
                )
            return
        if isinstance(owner, SessionTurnHostAuthority):
            return
        raise SandboxHostAuthorityError(
            "continuation delivery authority cannot execute a sandbox adapter"
        )

    def execute_adapter_operation(
        self,
        *,
        operation: ControlledOperation,
        envelope: dict[str, object],
        context: SandboxHostCallContext,
    ) -> dict[str, object]:
        self._validate_operation_owner(operation, context)
        result = self._bound_engine(context).execute_sandbox_adapter_operation(
            operation,
            dict(envelope),
        )
        return dict(result)

    def fetch_hpc_outputs(
        self,
        *,
        params: dict[str, object],
        context: SandboxHostCallContext,
    ) -> dict[str, object]:
        session_id = str(params.get("session_id") or "")
        context.require_session(session_id)
        if isinstance(context.owner, ContinuationDeliveryHostAuthority):
            raise SandboxHostAuthorityError(
                "continuation delivery authority cannot fetch sandbox outputs"
            )
        if isinstance(context.owner, SandboxProcessHostAuthority):
            context.require_sandbox_process(
                session_id=session_id,
                sandbox_workspace_id=str(params.get("sandbox_workspace_id") or ""),
                sandbox_run_id=context.owner.sandbox_run_id,
                process_epoch=context.owner.process_epoch,
            )
        result = self._bound_engine(context).fetch_sandbox_hpc_outputs(dict(params))
        return dict(result)


@dataclass(frozen=True, slots=True)
class HostSandboxCallContextFactory:
    repository_scope_factory: Callable[
        [], AbstractContextManager[CoreRepositories]
    ]
    mutation_writer_scope_factory: SandboxMutationWriterScopeFactory | None
    runtime_lease: SessionRuntimeLease | None

    @contextmanager
    def __call__(
        self,
        owner: SandboxHostOwnerAuthority,
    ) -> Iterator[SandboxHostCallContext]:
        repository_scope = self.repository_scope_factory
        if isinstance(owner, SessionTurnHostAuthority):
            lease = self.runtime_lease
            if lease is None or not owner.matches(lease):
                raise SandboxHostAuthorityError(
                    "session-turn Host context does not match the active runtime lease"
                )
            with repository_scope() as repositories:
                self._require_repositories(repositories)
                with repositories.runtime_write_fence(lease):
                    yield SandboxHostCallContext(
                        repositories=repositories,
                        owner=owner,
                        mutation_writer_scope_factory=(
                            self.mutation_writer_scope_factory
                        ),
                    )
            return

        if isinstance(owner, SandboxProcessHostAuthority):
            writer_factory = self.mutation_writer_scope_factory
            writer_scope = (
                nullcontext(None)
                if writer_factory is None
                else writer_factory(
                    session_id=owner.session_id,
                    owner_kind=MutationWriterKind.ENGINE_CALLBACK,
                    owner_ref=f"sandbox-control-server:{owner.sandbox_run_id}",
                    process_epoch=owner.process_epoch,
                )
            )
            with writer_scope as mutation_authority:
                with repository_scope() as repositories:
                    self._require_repositories(repositories)
                    authority_scope = (
                        nullcontext()
                        if mutation_authority is None
                        else repositories.mutation_write_authority(
                            mutation_authority
                        )
                    )
                    with authority_scope:
                        yield SandboxHostCallContext(
                            repositories=repositories,
                            owner=owner,
                            mutation_authority=mutation_authority,
                            mutation_writer_scope_factory=writer_factory,
                        )
            return

        if isinstance(owner, DurableExecutionHostAuthority):
            with repository_scope() as repositories:
                self._require_repositories(repositories)
                execution = repositories.controlled_operation_executions.get(
                    owner.execution_id
                )
                if execution is None or not owner.matches(execution):
                    raise SandboxHostAuthorityError(
                        "durable Host context does not match the claimed execution"
                    )
                with repositories.controlled_operation_write_fence(execution):
                    yield SandboxHostCallContext(
                        repositories=repositories,
                        owner=owner,
                        mutation_writer_scope_factory=(
                            self.mutation_writer_scope_factory
                        ),
                    )
            return

        if isinstance(owner, ContinuationDeliveryHostAuthority):
            with repository_scope() as repositories:
                self._require_repositories(repositories)
                continuation = repositories.continuation_states.get(
                    owner.continuation_id
                )
                if continuation is None or not owner.matches(continuation):
                    raise SandboxHostAuthorityError(
                        "continuation Host context does not match delivery authority"
                    )
                yield SandboxHostCallContext(
                    repositories=repositories,
                    owner=owner,
                    mutation_writer_scope_factory=self.mutation_writer_scope_factory,
                )
            return

        raise SandboxHostAuthorityError("unsupported sandbox Host owner authority")

    @staticmethod
    def _require_repositories(repositories: object) -> None:
        if not isinstance(repositories, CoreRepositories):
            raise SandboxHostAuthorityError(
                "sandbox Host context factory returned invalid repositories"
            )


__all__ = [
    "ExecutionEngineSandboxHostGateway",
    "HostSandboxCallContextFactory",
]
