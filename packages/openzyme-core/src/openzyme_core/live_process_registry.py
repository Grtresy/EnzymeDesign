from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import threading
import time
from typing import Any
from typing import Protocol

from openzyme_domain import ContinuationState


class LiveProcessRegistryConflictError(RuntimeError):
    """Raised when a mutable process handle does not match durable identity."""


@dataclass(frozen=True, slots=True)
class AttachedProcessIdentity:
    continuation_id: str
    operation_id: str
    execution_id: str
    session_id: str
    sandbox_run_id: str
    sandbox_workspace_id: str
    sandbox_runtime_identity: str
    process_epoch: int
    delivery_generation: int

    @classmethod
    def from_continuation(
        cls,
        continuation: ContinuationState,
        *,
        execution_id: str,
    ) -> "AttachedProcessIdentity":
        if not execution_id:
            raise ValueError("attached process execution_id is required")
        if not continuation.sandbox_workspace_id:
            raise ValueError("attached process sandbox_workspace_id is required")
        if not continuation.sandbox_runtime_identity:
            raise ValueError("attached process runtime identity is required")
        if continuation.process_epoch is None or continuation.process_epoch < 1:
            raise ValueError("attached process epoch is required")
        if continuation.delivery_generation < 1:
            raise ValueError("attached process delivery generation is required")
        return cls(
            continuation_id=continuation.continuation_id,
            operation_id=continuation.operation_id,
            execution_id=execution_id,
            session_id=continuation.session_id,
            sandbox_run_id=continuation.sandbox_run_id,
            sandbox_workspace_id=continuation.sandbox_workspace_id,
            sandbox_runtime_identity=continuation.sandbox_runtime_identity,
            process_epoch=continuation.process_epoch,
            delivery_generation=continuation.delivery_generation,
        )

    def same_process(self, other: "AttachedProcessIdentity") -> bool:
        return (
            self.session_id,
            self.sandbox_run_id,
            self.sandbox_workspace_id,
            self.sandbox_runtime_identity,
            self.process_epoch,
        ) == (
            other.session_id,
            other.sandbox_run_id,
            other.sandbox_workspace_id,
            other.sandbox_runtime_identity,
            other.process_epoch,
        )


@dataclass(frozen=True, slots=True)
class AttachedProcessDelivery:
    result_handle_id: str
    terminal_outcome: str
    result_digest: str
    bounded_result_envelope: dict[str, Any]


class AttachedProcessHandle(Protocol):
    def is_alive(self) -> bool: ...

    def bind_identity(self, identity: AttachedProcessIdentity) -> None: ...

    def deliver(
        self,
        identity: AttachedProcessIdentity,
        delivery: AttachedProcessDelivery,
    ) -> None: ...

    def request_stop(self, *, reason: str) -> None: ...

    def wait_stopped(self, *, timeout_seconds: float) -> bool: ...


@dataclass(frozen=True, slots=True)
class LiveProcessRegistryEntry:
    identity: AttachedProcessIdentity
    handle: AttachedProcessHandle


@dataclass(slots=True)
class LiveProcessRegistry:
    """Host-private, noncanonical registry for exact same-process delivery."""

    _lock: threading.RLock = field(
        default_factory=threading.RLock,
        init=False,
        repr=False,
    )
    _by_continuation: dict[str, LiveProcessRegistryEntry] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _by_run: dict[str, LiveProcessRegistryEntry] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def register(
        self,
        identity: AttachedProcessIdentity,
        handle: AttachedProcessHandle,
    ) -> LiveProcessRegistryEntry:
        if not handle.is_alive():
            raise LiveProcessRegistryConflictError(
                "attached process is not alive at registration"
            )
        with self._lock:
            existing_run = self._by_run.get(identity.sandbox_run_id)
            if existing_run is not None:
                if (
                    existing_run.handle is not handle
                    or not existing_run.identity.same_process(identity)
                ):
                    raise LiveProcessRegistryConflictError(
                        "sandbox run already has a different attached process epoch"
                    )
                return self._rebind_locked(identity, existing_run.handle)
            existing_continuation = self._by_continuation.get(identity.continuation_id)
            if existing_continuation is not None:
                if (
                    existing_continuation.handle is handle
                    and existing_continuation.identity == identity
                ):
                    return existing_continuation
                raise LiveProcessRegistryConflictError(
                    "continuation already has a different attached process"
                )
            handle.bind_identity(identity)
            entry = LiveProcessRegistryEntry(identity=identity, handle=handle)
            self._by_continuation[identity.continuation_id] = entry
            self._by_run[identity.sandbox_run_id] = entry
            return entry

    def rebind(self, identity: AttachedProcessIdentity) -> LiveProcessRegistryEntry:
        with self._lock:
            existing = self._by_run.get(identity.sandbox_run_id)
            if existing is None:
                raise LiveProcessRegistryConflictError(
                    "attached process is not registered for this sandbox run"
                )
            if not existing.identity.same_process(identity):
                raise LiveProcessRegistryConflictError(
                    "attached process identity changed while rebinding continuation"
                )
            if not existing.handle.is_alive():
                raise LiveProcessRegistryConflictError(
                    "attached process is no longer alive"
                )
            return self._rebind_locked(identity, existing.handle)

    def _rebind_locked(
        self,
        identity: AttachedProcessIdentity,
        handle: AttachedProcessHandle,
    ) -> LiveProcessRegistryEntry:
        for continuation_id, entry in tuple(self._by_continuation.items()):
            if (
                entry.identity.sandbox_run_id == identity.sandbox_run_id
                and continuation_id != identity.continuation_id
            ):
                self._by_continuation.pop(continuation_id, None)
        handle.bind_identity(identity)
        entry = LiveProcessRegistryEntry(identity=identity, handle=handle)
        self._by_continuation[identity.continuation_id] = entry
        self._by_run[identity.sandbox_run_id] = entry
        return entry

    def get(self, continuation_id: str) -> LiveProcessRegistryEntry | None:
        with self._lock:
            return self._by_continuation.get(continuation_id)

    def get_by_run(self, sandbox_run_id: str) -> LiveProcessRegistryEntry | None:
        with self._lock:
            return self._by_run.get(sandbox_run_id)

    def remove_run(
        self,
        sandbox_run_id: str,
        *,
        expected_process_epoch: int,
    ) -> LiveProcessRegistryEntry | None:
        with self._lock:
            existing = self._by_run.get(sandbox_run_id)
            if existing is None:
                return None
            if existing.identity.process_epoch != expected_process_epoch:
                raise LiveProcessRegistryConflictError(
                    "late process cleanup was fenced by a newer process epoch"
                )
            self._by_run.pop(sandbox_run_id, None)
            for continuation_id, entry in tuple(self._by_continuation.items()):
                if entry.handle is existing.handle:
                    self._by_continuation.pop(continuation_id, None)
            return existing

    def active_count(self) -> int:
        with self._lock:
            return len(self._by_run)

    def stop_all(self, *, reason: str, timeout_seconds: float = 10.0) -> bool:
        if timeout_seconds < 0 or timeout_seconds > 300:
            raise ValueError("live process stop timeout must be between 0 and 300 seconds")
        with self._lock:
            handles = tuple(
                {
                    id(entry.handle): entry.handle for entry in self._by_run.values()
                }.values()
            )
        stopped = True
        for handle in handles:
            try:
                handle.request_stop(reason=reason)
            except Exception:
                stopped = False
        deadline = time.monotonic() + timeout_seconds
        for handle in handles:
            remaining = max(0.0, deadline - time.monotonic())
            waiter = getattr(handle, "wait_stopped", None)
            try:
                if callable(waiter):
                    stopped = bool(waiter(timeout_seconds=remaining)) and stopped
                else:
                    while handle.is_alive() and time.monotonic() < deadline:
                        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
                    stopped = not handle.is_alive() and stopped
            except Exception:
                stopped = False
        with self._lock:
            for sandbox_run_id, entry in tuple(self._by_run.items()):
                if entry.handle.is_alive():
                    continue
                self._by_run.pop(sandbox_run_id, None)
                for continuation_id, continuation_entry in tuple(
                    self._by_continuation.items()
                ):
                    if continuation_entry.handle is entry.handle:
                        self._by_continuation.pop(continuation_id, None)
        return stopped and self.active_count() == 0


__all__ = [
    "AttachedProcessDelivery",
    "AttachedProcessHandle",
    "AttachedProcessIdentity",
    "LiveProcessRegistry",
    "LiveProcessRegistryConflictError",
    "LiveProcessRegistryEntry",
]
