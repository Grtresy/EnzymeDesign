from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol
from typing import TypeAlias
from typing import runtime_checkable

from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ContinuationState
from openzyme_domain import MutationWriterKind
from openzyme_domain import SessionRuntimeLease

from .mutation_authority import MutationWriteAuthority
from .repositories import CoreRepositories


class SandboxHostAuthorityError(RuntimeError):
    """A sandbox Host call crossed or omitted an explicit owner boundary."""


def _require_identity(value: str, field_name: str) -> None:
    if not value or value.strip() != value:
        raise SandboxHostAuthorityError(
            f"sandbox Host authority requires a canonical {field_name}"
        )


@dataclass(frozen=True, slots=True)
class SessionTurnHostAuthority:
    session_id: str
    lease_token: str
    fencing_token: int

    def __post_init__(self) -> None:
        _require_identity(self.session_id, "session_id")
        _require_identity(self.lease_token, "lease_token")
        if self.fencing_token < 1:
            raise SandboxHostAuthorityError(
                "session-turn Host authority requires a positive fencing token"
            )

    @classmethod
    def from_lease(cls, lease: SessionRuntimeLease) -> SessionTurnHostAuthority:
        return cls(
            session_id=lease.session_id,
            lease_token=lease.lease_token,
            fencing_token=lease.fencing_token,
        )

    def matches(self, lease: SessionRuntimeLease) -> bool:
        return (
            self.session_id == lease.session_id
            and self.lease_token == lease.lease_token
            and self.fencing_token == lease.fencing_token
        )


@dataclass(frozen=True, slots=True)
class SandboxProcessHostAuthority:
    session_id: str
    sandbox_workspace_id: str
    sandbox_run_id: str
    process_epoch: int

    def __post_init__(self) -> None:
        _require_identity(self.session_id, "session_id")
        _require_identity(self.sandbox_workspace_id, "sandbox_workspace_id")
        _require_identity(self.sandbox_run_id, "sandbox_run_id")
        if self.process_epoch < 1:
            raise SandboxHostAuthorityError(
                "sandbox-process Host authority requires a positive process epoch"
            )


@dataclass(frozen=True, slots=True)
class DurableExecutionHostAuthority:
    session_id: str
    execution_id: str
    operation_id: str
    lease_token: str
    fencing_token: int
    state_version: int

    def __post_init__(self) -> None:
        _require_identity(self.session_id, "session_id")
        _require_identity(self.execution_id, "execution_id")
        _require_identity(self.operation_id, "operation_id")
        _require_identity(self.lease_token, "lease_token")
        if self.fencing_token < 1 or self.state_version < 1:
            raise SandboxHostAuthorityError(
                "durable-execution Host authority requires positive fence and state version"
            )

    @classmethod
    def from_execution(
        cls,
        execution: ControlledOperationExecution,
    ) -> DurableExecutionHostAuthority:
        if execution.lease_token is None:
            raise SandboxHostAuthorityError(
                "durable-execution Host authority requires a claimed execution lease"
            )
        return cls(
            session_id=execution.session_id,
            execution_id=execution.execution_id,
            operation_id=execution.operation_id,
            lease_token=execution.lease_token,
            fencing_token=execution.fencing_token,
            state_version=execution.state_version,
        )

    def matches(self, execution: ControlledOperationExecution) -> bool:
        return (
            self.session_id == execution.session_id
            and self.execution_id == execution.execution_id
            and self.operation_id == execution.operation_id
            and self.lease_token == execution.lease_token
            and self.fencing_token == execution.fencing_token
            and self.state_version == execution.state_version
        )


@dataclass(frozen=True, slots=True)
class ContinuationDeliveryHostAuthority:
    session_id: str
    continuation_id: str
    sandbox_run_id: str
    process_epoch: int
    delivery_generation: int
    lease_token: str
    fencing_token: int

    def __post_init__(self) -> None:
        _require_identity(self.session_id, "session_id")
        _require_identity(self.continuation_id, "continuation_id")
        _require_identity(self.sandbox_run_id, "sandbox_run_id")
        _require_identity(self.lease_token, "lease_token")
        if (
            self.process_epoch < 1
            or self.delivery_generation < 1
            or self.fencing_token < 1
        ):
            raise SandboxHostAuthorityError(
                "continuation-delivery Host authority requires positive epoch, generation, and fence"
            )

    @classmethod
    def from_continuation(
        cls,
        continuation: ContinuationState,
    ) -> ContinuationDeliveryHostAuthority:
        if continuation.process_epoch is None:
            raise SandboxHostAuthorityError(
                "continuation-delivery Host authority requires a process epoch"
            )
        if continuation.delivery_lease_token is None:
            raise SandboxHostAuthorityError(
                "continuation-delivery Host authority requires a claimed delivery lease"
            )
        return cls(
            session_id=continuation.session_id,
            continuation_id=continuation.continuation_id,
            sandbox_run_id=continuation.sandbox_run_id,
            process_epoch=continuation.process_epoch,
            delivery_generation=continuation.delivery_generation,
            lease_token=continuation.delivery_lease_token,
            fencing_token=continuation.delivery_fencing_token,
        )

    def matches(self, continuation: ContinuationState) -> bool:
        return (
            self.session_id == continuation.session_id
            and self.continuation_id == continuation.continuation_id
            and self.sandbox_run_id == continuation.sandbox_run_id
            and self.process_epoch == continuation.process_epoch
            and self.delivery_generation == continuation.delivery_generation
            and self.lease_token == continuation.delivery_lease_token
            and self.fencing_token == continuation.delivery_fencing_token
        )


SandboxHostOwnerAuthority: TypeAlias = (
    SessionTurnHostAuthority
    | SandboxProcessHostAuthority
    | DurableExecutionHostAuthority
    | ContinuationDeliveryHostAuthority
)


@runtime_checkable
class SandboxMutationWriterScopeFactory(Protocol):
    def __call__(
        self,
        *,
        session_id: str,
        owner_kind: MutationWriterKind,
        owner_ref: str,
        process_epoch: int | None = None,
    ) -> AbstractContextManager[MutationWriteAuthority | None]: ...


@dataclass(frozen=True, slots=True)
class SandboxHostCallContext:
    repositories: CoreRepositories
    owner: SandboxHostOwnerAuthority
    mutation_authority: MutationWriteAuthority | None = None
    mutation_writer_scope_factory: SandboxMutationWriterScopeFactory | None = None

    def __post_init__(self) -> None:
        if type(self.owner) not in {
            SessionTurnHostAuthority,
            SandboxProcessHostAuthority,
            DurableExecutionHostAuthority,
            ContinuationDeliveryHostAuthority,
        }:
            raise SandboxHostAuthorityError(
                "sandbox Host context requires exactly one supported owner authority"
            )

    @property
    def session_id(self) -> str:
        return self.owner.session_id

    def require_session(self, session_id: str) -> None:
        if session_id != self.session_id:
            raise SandboxHostAuthorityError(
                "sandbox Host call crossed its owner session boundary"
            )

    def require_sandbox_process(
        self,
        *,
        session_id: str,
        sandbox_workspace_id: str,
        sandbox_run_id: str,
        process_epoch: int,
    ) -> SandboxProcessHostAuthority:
        owner = self.owner
        if not isinstance(owner, SandboxProcessHostAuthority):
            raise SandboxHostAuthorityError(
                "sandbox callback requires sandbox-process Host authority"
            )
        expected = SandboxProcessHostAuthority(
            session_id=session_id,
            sandbox_workspace_id=sandbox_workspace_id,
            sandbox_run_id=sandbox_run_id,
            process_epoch=process_epoch,
        )
        if owner != expected:
            raise SandboxHostAuthorityError(
                "sandbox callback process identity does not match its Host context"
            )
        return owner

    def require_execution(
        self,
        execution: ControlledOperationExecution,
    ) -> DurableExecutionHostAuthority:
        owner = self.owner
        if not isinstance(owner, DurableExecutionHostAuthority) or not owner.matches(
            execution
        ):
            raise SandboxHostAuthorityError(
                "durable callback execution identity does not match its Host context"
            )
        return owner

    def require_continuation(
        self,
        continuation: ContinuationState,
    ) -> ContinuationDeliveryHostAuthority:
        owner = self.owner
        if not isinstance(
            owner, ContinuationDeliveryHostAuthority
        ) or not owner.matches(continuation):
            raise SandboxHostAuthorityError(
                "continuation delivery identity does not match its Host context"
            )
        return owner

    @contextmanager
    def child_mutation_writer(
        self,
        *,
        owner_kind: MutationWriterKind,
        owner_ref: str,
        process_epoch: int | None = None,
    ) -> Iterator[MutationWriteAuthority | None]:
        factory = self.mutation_writer_scope_factory
        if factory is None:
            yield None
            return
        with factory(
            session_id=self.session_id,
            owner_kind=owner_kind,
            owner_ref=owner_ref,
            process_epoch=process_epoch,
        ) as authority:
            if authority is None:
                yield None
                return
            with self.repositories.mutation_write_authority(authority):
                yield authority


@runtime_checkable
class SandboxHostCallContextFactory(Protocol):
    def __call__(
        self,
        owner: SandboxHostOwnerAuthority,
    ) -> AbstractContextManager[SandboxHostCallContext]: ...


@runtime_checkable
class SandboxHostGateway(Protocol):
    def execute_adapter_operation(
        self,
        *,
        operation: ControlledOperation,
        envelope: dict[str, object],
        context: SandboxHostCallContext,
    ) -> dict[str, object]: ...

    def fetch_hpc_outputs(
        self,
        *,
        params: dict[str, object],
        context: SandboxHostCallContext,
    ) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class SandboxHostBinding:
    gateway: SandboxHostGateway
    context_factory: SandboxHostCallContextFactory


__all__ = [
    "ContinuationDeliveryHostAuthority",
    "DurableExecutionHostAuthority",
    "SandboxHostAuthorityError",
    "SandboxHostBinding",
    "SandboxHostCallContext",
    "SandboxHostCallContextFactory",
    "SandboxHostGateway",
    "SandboxHostOwnerAuthority",
    "SandboxMutationWriterScopeFactory",
    "SandboxProcessHostAuthority",
    "SessionTurnHostAuthority",
]
