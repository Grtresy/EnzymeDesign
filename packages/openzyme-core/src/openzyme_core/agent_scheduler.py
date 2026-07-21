from __future__ import annotations

import asyncio
from contextlib import suppress
from contextlib import AbstractContextManager
from contextlib import nullcontext
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from datetime import UTC
from datetime import datetime
import sqlite3
import time
from typing import Any
from typing import Callable

from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import SessionRuntimeLease
from openzyme_domain import SessionRuntimeLeaseMode
from openzyme_domain import MutationWriterKind
from openzyme_domain.control_plane import utc_now_iso
from openzyme_runtime import classify_llm_provider_error
from openzyme_runtime import sanitize_public_diagnostic_text

from .agent_runtime import AgentRuntimeOutcome
from .agent_runtime import AgentRuntimeService
from .engines import EngineRegistry
from .repositories import CoreRepositories
from .harness import SessionRuntimeContext
from .harness import SessionRuntimeSnapshot


_SESSION_LEASE_HEARTBEAT_RETRY_DELAYS_SECONDS = (0.05, 0.1, 0.25)


def _is_transient_sqlite_contention(exc: BaseException) -> bool:
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    error_code = getattr(exc, "sqlite_errorcode", None)
    if isinstance(error_code, int) and error_code & 0xFF in {
        sqlite3.SQLITE_BUSY,
        sqlite3.SQLITE_LOCKED,
    }:
        return True
    message = str(exc).casefold()
    return any(
        marker in message
        for marker in (
            "database is busy",
            "database is locked",
            "database table is locked",
            "database schema is locked",
        )
    )


def _seconds_until(expires_at: str) -> float:
    deadline = datetime.fromisoformat(expires_at)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    return max(0.0, (deadline - datetime.now(tz=UTC)).total_seconds())


class SessionRuntimeLeaseLockedError(RuntimeError):
    def __init__(
        self,
        *,
        session_id: str,
        active_lease: SessionRuntimeLease,
        retry_after_seconds: int | None,
    ) -> None:
        self.session_id = session_id
        self.active_lease = active_lease
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            "session runtime lease is already held by "
            f"{active_lease.owner_id!r} until {active_lease.expires_at}"
        )


@dataclass(slots=True)
class AgentRuntimeScheduler:
    context: SessionRuntimeContext
    worker_id: str = "scheduler:local"
    lease_seconds: int = 300
    session_lease_seconds: int = 300
    runtime_mode: SessionRuntimeLeaseMode | str = SessionRuntimeLeaseMode.TEST
    max_global_concurrency: int = 1
    max_session_concurrency: int = 1
    max_agent_concurrency: int = 1
    repository_scope_factory: (
        Callable[[], AbstractContextManager[CoreRepositories]] | None
    ) = None
    engine_registry_factory: (
        Callable[
            [CoreRepositories, SessionRuntimeLease | None],
            EngineRegistry,
        ]
        | None
    ) = None
    mutation_writer_scope_factory: (
        Callable[..., AbstractContextManager[object]] | None
    ) = None
    _shutdown_requested: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if self.session_lease_seconds <= 0:
            raise ValueError("session_lease_seconds must be positive")
        self.runtime_mode = SessionRuntimeLeaseMode(str(self.runtime_mode))
        if self.max_global_concurrency <= 0:
            raise ValueError("max_global_concurrency must be positive")
        if self.max_session_concurrency <= 0:
            raise ValueError("max_session_concurrency must be positive")
        if self.max_agent_concurrency <= 0:
            raise ValueError("max_agent_concurrency must be positive")

    async def run_once(
        self,
        session_id: str,
        *,
        max_signals: int = 3,
        max_steps_per_agent: int = 8,
        signal_ids: set[str] | None = None,
        auto_enqueue_ready_tasks: bool = False,
    ) -> tuple[AgentRuntimeOutcome, ...]:
        if max_signals <= 0:
            return ()
        if self.context.model_factory is None and not auto_enqueue_ready_tasks:
            return ()
        session_lease, owns_session_lease = self._acquire_session_lease(session_id)
        session_hold_started = time.monotonic()
        previous_session_lease = self.context.session_runtime_lease
        self.context.session_runtime_lease = session_lease
        heartbeat_task: asyncio.Task[None] | None = None
        if owns_session_lease:
            heartbeat_task = asyncio.create_task(
                self._maintain_session_lease(session_lease)
            )
        global_limiter = asyncio.Semaphore(self.max_global_concurrency)
        session_limiter = asyncio.Semaphore(self.max_session_concurrency)
        agent_limiters: dict[str, asyncio.Semaphore] = {}

        async def run_signal(signal: Any) -> AgentRuntimeOutcome:
            signal_hold_started = time.monotonic()
            agent_limiter = agent_limiters.setdefault(
                str(signal.agent_id),
                asyncio.Semaphore(self.max_agent_concurrency),
            )
            async with global_limiter:
                async with session_limiter:
                    async with agent_limiter:
                        try:
                            outcome = await asyncio.to_thread(
                                self._wake_signal_in_worker,
                                signal=signal,
                                max_steps=max_steps_per_agent,
                            )
                        except Exception as exc:
                            classification = classify_llm_provider_error(exc)
                            public_error = sanitize_public_diagnostic_text(str(exc))
                            failed = (
                                self.context.repositories.runtime_signals.fail(
                                    signal.signal_id,
                                    error_message=public_error,
                                    retryable=classification.retryable,
                                    expected_session_lease_token=session_lease.lease_token,
                                    expected_session_fencing_token=session_lease.fencing_token,
                                )
                                or self.context.repositories.runtime_signals.get(
                                    signal.signal_id
                                )
                                or signal
                            )
                            if failed.status.value == "claimed":
                                self.context.emit(
                                    "runtime.fencing_rejected",
                                    {
                                        "signal_id": signal.signal_id,
                                        "attempted_status": "failed",
                                        "session_fencing_token": (
                                            session_lease.fencing_token
                                        ),
                                        "worker_id": self.worker_id,
                                    },
                                )
                            agent = None
                            if failed.status.value != "claimed":
                                agent = self._release_agent_after_runtime_exception(
                                    signal
                                )
                            outcome = AgentRuntimeOutcome(
                                signal=failed,
                                task=None,
                                agent=agent
                                or self.context.repositories.agents.get(
                                    signal.session_id, signal.agent_id
                                ),
                                ok=False,
                                summary=public_error,
                                teammate_status=(
                                    "runtime_retry_scheduled"
                                    if failed.status.value == "pending"
                                    else "runtime_exception"
                                ),
                            )
            observer = self.context.reliability_shadow_observer
            if observer is not None:
                try:
                    observer.observe_runtime_authority_hold(
                        signal_id=str(signal.signal_id),
                        signal_hold_ms=int(
                            (time.monotonic() - signal_hold_started) * 1_000
                        ),
                        session_lease_hold_ms=int(
                            (time.monotonic() - session_hold_started) * 1_000
                        ),
                    )
                except Exception:
                    # Shadow telemetry is deliberately non-authoritative.
                    pass
            return outcome

        try:
            if auto_enqueue_ready_tasks:
                AgentRuntimeService(self.context).auto_enqueue_ready_tasks(session_id)
            if self.context.model_factory is None:
                return ()
            outcomes: list[AgentRuntimeOutcome] = []
            while len(outcomes) < max_signals and not self._shutdown_requested:
                if heartbeat_task is not None and heartbeat_task.done():
                    break
                claim_limit = min(
                    max_signals - len(outcomes),
                    self.max_global_concurrency,
                    self.max_session_concurrency,
                )
                signals = []
                for _ in range(claim_limit):
                    signal = self.context.repositories.runtime_signals.claim_next(
                        session_id=session_id,
                        claimed_by=self.worker_id,
                        lease_seconds=self.lease_seconds,
                        signal_ids=signal_ids,
                        session_lease_token=session_lease.lease_token,
                        session_fencing_token=session_lease.fencing_token,
                    )
                    if signal is None:
                        break
                    signals.append(signal)
                if not signals:
                    break
                outcomes.extend(
                    await asyncio.gather(*(run_signal(signal) for signal in signals))
                )
            return tuple(outcomes)
        finally:
            try:
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await heartbeat_task
            finally:
                self.context.session_runtime_lease = previous_session_lease
                if owns_session_lease:
                    self.context.repositories.session_runtime_leases.release(
                        session_id=session_id,
                        owner_id=self.worker_id,
                        lease_token=session_lease.lease_token,
                    )

    def _wake_signal_in_worker(
        self,
        *,
        signal: AgentRuntimeSignal,
        max_steps: int,
    ) -> AgentRuntimeOutcome:
        """Run one bounded turn with repositories owned by the worker thread.

        The scheduler claims signals and owns the session lease on its coordinator
        thread.  Agent execution is intentionally offloaded because provider calls
        are blocking.  A file-backed Host therefore supplies a scope factory so the
        worker never touches the coordinator's thread-affine SQLite connection.
        """

        writer_scope = (
            nullcontext(None)
            if self.mutation_writer_scope_factory is None
            else self.mutation_writer_scope_factory(
                session_id=signal.session_id,
                owner_kind=MutationWriterKind.AGENT_TURN,
                owner_ref=f"agent-turn:{signal.signal_id}",
            )
        )
        with writer_scope:
            return self._wake_signal_in_worker_scoped(
                signal=signal,
                max_steps=max_steps,
            )

    def _wake_signal_in_worker_scoped(
        self,
        *,
        signal: AgentRuntimeSignal,
        max_steps: int,
    ) -> AgentRuntimeOutcome:
        if self.repository_scope_factory is None:
            lease = self.context.session_runtime_lease
            if lease is None:
                return AgentRuntimeService(self.context).wake_agent(
                    signal,
                    max_steps=max_steps,
                )
            with self.context.repositories.runtime_write_fence(lease):
                return AgentRuntimeService(self.context).wake_agent(
                    signal,
                    max_steps=max_steps,
                )
        with self.repository_scope_factory() as repositories:
            engine_registry = self.context.engine_registry
            if self.engine_registry_factory is not None:
                engine_registry = self.engine_registry_factory(
                    repositories,
                    self.context.session_runtime_lease,
                )
            event_sink = self.context.event_sink
            scoped_sink_factory = getattr(event_sink, "for_repositories", None)
            if callable(scoped_sink_factory):
                event_sink = scoped_sink_factory(repositories)
            scoped_context = replace(
                self.context,
                repositories=repositories,
                snapshot=SessionRuntimeSnapshot.load(
                    repositories,
                    signal.session_id,
                ),
                engine_registry=engine_registry,
                event_sink=event_sink,
            )
            lease = scoped_context.session_runtime_lease
            if lease is None:
                return AgentRuntimeService(scoped_context).wake_agent(
                    signal,
                    max_steps=max_steps,
                )
            with repositories.runtime_write_fence(lease):
                return AgentRuntimeService(scoped_context).wake_agent(
                    signal,
                    max_steps=max_steps,
                )

    async def _maintain_session_lease(self, lease: SessionRuntimeLease) -> None:
        interval = max(0.25, min(self.session_lease_seconds / 3, 30.0))
        loop = asyncio.get_running_loop()
        lease_deadline = loop.time() + _seconds_until(lease.expires_at)
        while True:
            await asyncio.sleep(interval)
            retry_count = 0
            while True:
                if retry_count > 0 and loop.time() >= lease_deadline:
                    self.context.emit(
                        "runtime.lease_heartbeat_failed",
                        {
                            "session_id": lease.session_id,
                            "fencing_token": lease.fencing_token,
                            "worker_id": self.worker_id,
                            "error_type": "OperationalError",
                            "retry_count": retry_count,
                            "lease_deadline_expired": True,
                        },
                    )
                    return
                try:
                    heartbeat = self._heartbeat_session_lease(lease)
                    break
                except Exception as exc:
                    if not _is_transient_sqlite_contention(exc):
                        try:
                            self.context.emit(
                                "runtime.lease_heartbeat_failed",
                                {
                                    "session_id": lease.session_id,
                                    "fencing_token": lease.fencing_token,
                                    "worker_id": self.worker_id,
                                    "error_type": exc.__class__.__name__,
                                },
                            )
                        except Exception as emit_exc:
                            exc.add_note(
                                "heartbeat failure event emission also failed: "
                                f"{emit_exc.__class__.__name__}"
                            )
                        raise
                    remaining_seconds = lease_deadline - loop.time()
                    if remaining_seconds <= 0:
                        self.context.emit(
                            "runtime.lease_heartbeat_failed",
                            {
                                "session_id": lease.session_id,
                                "fencing_token": lease.fencing_token,
                                "worker_id": self.worker_id,
                                "error_type": exc.__class__.__name__,
                                "retry_count": retry_count,
                                "lease_deadline_expired": remaining_seconds <= 0,
                            },
                        )
                        return
                    retry_delay = min(
                        _SESSION_LEASE_HEARTBEAT_RETRY_DELAYS_SECONDS[
                            min(
                                retry_count,
                                len(_SESSION_LEASE_HEARTBEAT_RETRY_DELAYS_SECONDS) - 1,
                            )
                        ],
                        remaining_seconds,
                    )
                    retry_count += 1
                    await asyncio.sleep(retry_delay)
            if heartbeat is None:
                self.context.emit(
                    "runtime.lease_lost",
                    {
                        "session_id": lease.session_id,
                        "fencing_token": lease.fencing_token,
                        "worker_id": self.worker_id,
                    },
                )
                return
            lease_deadline = loop.time() + _seconds_until(heartbeat.expires_at)

    def _heartbeat_session_lease(
        self,
        lease: SessionRuntimeLease,
    ) -> SessionRuntimeLease | None:
        if self.repository_scope_factory is None:
            return self.context.repositories.session_runtime_leases.heartbeat(
                session_id=lease.session_id,
                owner_id=self.worker_id,
                lease_token=lease.lease_token,
                lease_seconds=self.session_lease_seconds,
            )
        with self.repository_scope_factory() as repositories:
            return repositories.session_runtime_leases.heartbeat(
                session_id=lease.session_id,
                owner_id=self.worker_id,
                lease_token=lease.lease_token,
                lease_seconds=self.session_lease_seconds,
            )

    async def run_forever(
        self,
        session_id: str,
        *,
        poll_interval_seconds: float = 0.25,
        max_signals_per_tick: int = 3,
        max_steps_per_agent: int = 8,
        stop_event: asyncio.Event | None = None,
        max_ticks: int | None = None,
    ) -> tuple[AgentRuntimeOutcome, ...]:
        outcomes: list[AgentRuntimeOutcome] = []
        ticks = 0
        while not self._shutdown_requested:
            if stop_event is not None and stop_event.is_set():
                break
            if max_ticks is not None and ticks >= max_ticks:
                break
            tick_outcomes = await self.run_once(
                session_id,
                max_signals=max_signals_per_tick,
                max_steps_per_agent=max_steps_per_agent,
            )
            outcomes.extend(tick_outcomes)
            ticks += 1
            if not tick_outcomes:
                await asyncio.sleep(poll_interval_seconds)
        return tuple(outcomes)

    def request_shutdown(self) -> None:
        self._shutdown_requested = True

    def run_once_sync(
        self,
        session_id: str,
        *,
        max_signals: int = 3,
        max_steps_per_agent: int = 8,
        signal_ids: set[str] | None = None,
        auto_enqueue_ready_tasks: bool = False,
    ) -> tuple[AgentRuntimeOutcome, ...]:
        return asyncio.run(
            self.run_once(
                session_id,
                max_signals=max_signals,
                max_steps_per_agent=max_steps_per_agent,
                signal_ids=signal_ids,
                auto_enqueue_ready_tasks=auto_enqueue_ready_tasks,
            )
        )

    def _acquire_session_lease(
        self, session_id: str
    ) -> tuple[SessionRuntimeLease, bool]:
        existing = self.context.session_runtime_lease
        if (
            existing is not None
            and self.context.repositories.session_runtime_leases.is_active(
                session_id=session_id,
                lease_token=existing.lease_token,
                fencing_token=existing.fencing_token,
            )
        ):
            return existing, False
        result = self.context.repositories.session_runtime_leases.acquire(
            session_id=session_id,
            owner_id=self.worker_id,
            mode=self.runtime_mode,
            lease_seconds=self.session_lease_seconds,
        )
        if result.acquired and result.lease is not None:
            return result.lease, True
        if result.active_lease is None:
            raise RuntimeError("session runtime lease acquisition failed")
        raise SessionRuntimeLeaseLockedError(
            session_id=session_id,
            active_lease=result.active_lease,
            retry_after_seconds=result.retry_after_seconds,
        )

    def _release_agent_after_runtime_exception(
        self, signal: AgentRuntimeSignal
    ) -> AgentMember | None:
        agent = self.context.repositories.agents.get(signal.session_id, signal.agent_id)
        if agent is None:
            return None
        now = utc_now_iso()
        updated = replace(
            agent,
            status=AgentMemberStatus.IDLE,
            task_id=signal.task_id if signal.task_id is not None else agent.task_id,
            lane_id=signal.lane_id if signal.lane_id is not None else agent.lane_id,
            updated_at=now,
            runtime_state="idle",
            current_correlation_id=(
                signal.correlation_id
                if signal.correlation_id is not None
                else agent.current_correlation_id
            ),
            wakeup_reason=signal.reason.value,
            last_active_at=now,
            idle_since=now,
        )
        self.context.repositories.agents.save(updated)
        self.context.emit(
            "agent.status_updated",
            {
                "agent_id": updated.agent_id,
                "status": updated.status.value,
                "task_id": updated.task_id,
                "lane_id": updated.lane_id,
                "wakeup_reason": updated.wakeup_reason,
            },
        )
        self.context.emit(
            "agent.idle",
            {
                "agent_id": updated.agent_id,
                "signal_id": signal.signal_id,
                "task_id": signal.task_id,
            },
        )
        return updated


__all__ = ["AgentRuntimeScheduler", "SessionRuntimeLeaseLockedError"]
