from __future__ import annotations

import asyncio
from dataclasses import dataclass
from dataclasses import field
import inspect
import threading
from typing import Any
from typing import Callable
from typing import ContextManager
from typing import Protocol
from contextlib import contextmanager

from openzyme_domain.control_plane import utc_now_iso
from openzyme_runtime import llm_debug_context
from openzyme_runtime import sanitize_public_diagnostic_text

from .v3_service import V3HostApiService


def _run_background_runtime_once_in_worker(
    open_service: Callable[[], ContextManager[V3HostApiService]],
    *,
    session_id: str,
    worker_id: str,
    max_signals: int,
    max_steps_per_agent: int,
) -> list[dict[str, Any]]:
    # The provider-backed service (and its SQLite connection) must be created
    # inside this worker thread, not captured from the event-loop thread.
    with open_service() as service:
        result = service.run_background_runtime_once(
            session_id=session_id,
            worker_id=worker_id,
            max_signals=max_signals,
            max_steps_per_agent=max_steps_per_agent,
        )
        if inspect.isawaitable(result):
            return asyncio.run(result)
        return result


class DurableWorkWorker(Protocol):
    def run_once(self) -> object: ...


@dataclass(slots=True)
class V3DurableWorkCoordinator:
    """Round-robin independent durable worker kinds within one worker slot."""

    workers: tuple[DurableWorkWorker, ...]
    _cursor: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if not self.workers:
            raise ValueError("durable work coordinator requires at least one worker")

    def run_once(self) -> object:
        last_outcome: object | None = None
        last_non_idle_outcome: object | None = None
        for offset in range(len(self.workers)):
            index = (self._cursor + offset) % len(self.workers)
            outcome = self.workers[index].run_once()
            last_outcome = outcome
            action = str(getattr(outcome, "action", ""))
            if action != "idle":
                last_non_idle_outcome = outcome
            if action not in {"idle", "claim_raced", "not_claimable"}:
                self._cursor = (index + 1) % len(self.workers)
                return outcome
        self._cursor = (self._cursor + 1) % len(self.workers)
        if last_outcome is None:  # guarded by __post_init__
            raise RuntimeError("durable work coordinator has no worker outcome")
        if last_non_idle_outcome is not None:
            return last_non_idle_outcome
        return last_outcome


def _run_durable_work_once_in_worker(
    worker_factory: Callable[[str], DurableWorkWorker],
    *,
    worker_id: str,
) -> dict[str, Any]:
    outcome = worker_factory(worker_id).run_once()
    field_names = (
        "execution_id",
        "command_id",
        "continuation_id",
        "action",
        "semantic_progress",
        "status",
        "delivery_state",
        "lifecycle_state",
        "state_version",
        "effect_certainty",
        "retry_eligibility",
    )
    serialized = {
        field_name: getattr(outcome, field_name)
        for field_name in field_names
        if hasattr(outcome, field_name)
    }
    if "action" not in serialized:
        raise TypeError("durable worker outcome omitted action")
    if type(serialized.get("semantic_progress")) is not bool:
        raise TypeError("durable worker outcome omitted typed semantic_progress")
    return serialized


@dataclass(slots=True)
class RuntimeSignalNotifier:
    _event: asyncio.Event | None = field(default=None, init=False)
    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False)
    wake_delay_seconds: float = 0.05
    notify_count: int = 0
    last_notified_session_id: str | None = None

    def bind(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._event = asyncio.Event()

    def notify(self, session_id: str | None = None) -> None:
        self.notify_count += 1
        self.last_notified_session_id = session_id
        if self._loop is None or self._event is None:
            return
        self._loop.call_soon_threadsafe(
            self._loop.call_later,
            self.wake_delay_seconds,
            self._event.set,
        )

    async def wait(self, timeout: float) -> bool:
        if self._event is None:
            await asyncio.sleep(timeout)
            return False
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except TimeoutError:
            return False
        self._event.clear()
        return True


@dataclass(slots=True)
class V3BackgroundRuntimeService:
    build_service: Callable[[], V3HostApiService] | None
    notifier: RuntimeSignalNotifier
    enabled: bool
    service_scope: Callable[[], ContextManager[V3HostApiService]] | None = None
    poll_interval_seconds: float = 2.0
    max_signals_per_tick: int = 3
    max_steps_per_agent: int = 8
    shutdown_timeout_seconds: float = 10.0
    worker_id: str = "host-api:background-runtime"
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _stop_event: asyncio.Event | None = field(default=None, init=False)
    _running: bool = field(default=False, init=False)
    disabled_reason: str | None = field(default=None, init=False)
    last_tick_at: str | None = field(default=None, init=False)
    tick_count: int = field(default=0, init=False)
    processed_signal_count: int = field(default=0, init=False)
    last_error: str | None = field(default=None, init=False)
    last_outcomes: list[dict[str, Any]] = field(default_factory=list, init=False)

    @contextmanager
    def _open_service(self):  # type: ignore[no-untyped-def]
        if self.service_scope is not None:
            with self.service_scope() as service:
                yield service
            return
        if self.build_service is None:
            raise RuntimeError(
                "V3 background runtime service factory is not configured"
            )
        # Compatibility path for unit-test fakes that own no external resources.
        yield self.build_service()

    def start(self) -> None:
        if not self.enabled:
            self.disabled_reason = "disabled by configuration"
            return
        with self._open_service() as service:
            if service.model_factory is None:
                self.disabled_reason = "model_factory unavailable"
                return
        self.disabled_reason = None
        self.notifier.bind()
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        if self._stop_event is not None:
            self._stop_event.set()
        self.notifier.notify()
        try:
            await asyncio.wait_for(self._task, timeout=self.shutdown_timeout_seconds)
        except TimeoutError:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        finally:
            self._task = None
            self._running = False

    async def _run_loop(self) -> None:
        self._running = True
        self.notifier.notify()
        try:
            while self._stop_event is None or not self._stop_event.is_set():
                await self.notifier.wait(self.poll_interval_seconds)
                if self._stop_event is not None and self._stop_event.is_set():
                    break
                await self.run_tick()
        finally:
            self._running = False

    async def run_tick(self) -> tuple[dict[str, Any], ...]:
        self.last_tick_at = utc_now_iso()
        self.tick_count += 1
        self.last_error = None
        remaining = max(0, self.max_signals_per_tick)
        outcomes: list[dict[str, Any]] = []
        try:
            with self._open_service() as service:
                if service.model_factory is None:
                    self.disabled_reason = "model_factory unavailable"
                    self.last_outcomes = []
                    return ()
                session_ids = (
                    service.repositories.runtime_signals.list_claimable_session_ids()
                )
            for session_id in session_ids:
                if remaining <= 0:
                    break
                with llm_debug_context(
                    request_path="background:v3-runtime",
                    session_id=session_id,
                    actor="scheduler",
                ):
                    session_outcomes = await asyncio.to_thread(
                        _run_background_runtime_once_in_worker,
                        self._open_service,
                        session_id=session_id,
                        worker_id=self.worker_id,
                        max_signals=remaining,
                        max_steps_per_agent=self.max_steps_per_agent,
                    )
                outcomes.extend(session_outcomes)
                remaining -= len(session_outcomes)
        except Exception as exc:
            self.last_error = sanitize_public_diagnostic_text(str(exc))
        self.processed_signal_count += len(outcomes)
        self.last_outcomes = outcomes[-20:]
        return tuple(outcomes)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": self._running,
            "disabled_reason": self.disabled_reason,
            "last_tick_at": self.last_tick_at,
            "tick_count": self.tick_count,
            "processed_signal_count": self.processed_signal_count,
            "last_error": self.last_error,
            "last_outcomes": self.last_outcomes,
            "worker_id": self.worker_id,
            "poll_interval_seconds": self.poll_interval_seconds,
            "max_signals_per_tick": self.max_signals_per_tick,
            "max_steps_per_agent": self.max_steps_per_agent,
        }


@dataclass(slots=True)
class V3DurableWorkSupervisor:
    """Host-lifespan owner for bounded, execution-fenced durable work."""

    worker_factory: Callable[[str], DurableWorkWorker]
    notifier: RuntimeSignalNotifier
    enabled: bool
    poll_interval_seconds: float = 1.0
    max_concurrency: int = 2
    shutdown_timeout_seconds: float = 10.0
    worker_id_prefix: str = "host-api:durable-work"
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _stop_event: asyncio.Event | None = field(default=None, init=False)
    _running: bool = field(default=False, init=False)
    _accepting_work: bool = field(default=False, init=False)
    _active_worker_ids: set[str] = field(default_factory=set, init=False)
    _active_worker_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )
    _shutdown_incomplete: bool = field(default=False, init=False)
    disabled_reason: str | None = field(default=None, init=False)
    last_tick_at: str | None = field(default=None, init=False)
    tick_count: int = field(default=0, init=False)
    processed_count: int = field(default=0, init=False)
    database_busy_count: int = field(default=0, init=False)
    last_error: str | None = field(default=None, init=False)
    last_outcomes: list[dict[str, Any]] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if self.poll_interval_seconds <= 0:
            raise ValueError("durable work poll interval must be positive")
        if self.max_concurrency <= 0 or self.max_concurrency > 32:
            raise ValueError("durable work concurrency must be between 1 and 32")
        if self.shutdown_timeout_seconds <= 0:
            raise ValueError("durable work shutdown timeout must be positive")
        self._accepting_work = self.enabled

    def start(self) -> None:
        if not self.enabled:
            self.disabled_reason = "disabled by configuration"
            return
        self.disabled_reason = None
        if self._active_worker_count() > 0:
            raise RuntimeError("durable work supervisor still has active workers")
        self._accepting_work = True
        self._shutdown_incomplete = False
        self.notifier.bind()
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._accepting_work = False
        if self._task is None:
            return
        if self._stop_event is not None:
            self._stop_event.set()
        self.notifier.notify()
        try:
            await asyncio.wait_for(self._task, timeout=self.shutdown_timeout_seconds)
        except TimeoutError:
            self._shutdown_incomplete = self._active_worker_count() > 0
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        finally:
            self._task = None
            self._running = False
            if self._active_worker_count() == 0:
                self._shutdown_incomplete = False

    async def _run_loop(self) -> None:
        self._running = True
        self.notifier.notify()
        try:
            while self._stop_event is None or not self._stop_event.is_set():
                await self.notifier.wait(self.poll_interval_seconds)
                if self._stop_event is not None and self._stop_event.is_set():
                    break
                await self.run_tick()
        finally:
            self._accepting_work = False
            self._running = False

    async def run_tick(self) -> tuple[dict[str, Any], ...]:
        if not self._accepting_work:
            return ()
        self.last_tick_at = utc_now_iso()
        self.tick_count += 1
        self.last_error = None
        try:
            outcomes = await asyncio.gather(
                *(
                    asyncio.to_thread(
                        self._run_worker_slot,
                        worker_id=f"{self.worker_id_prefix}:{slot}",
                    )
                    for slot in range(self.max_concurrency)
                )
            )
        except Exception as exc:
            self.last_error = sanitize_public_diagnostic_text(str(exc))
            self.last_outcomes = []
            return ()
        observed = [outcome for outcome in outcomes if outcome.get("action") != "idle"]
        database_busy = [
            outcome for outcome in observed if outcome.get("action") == "database_busy"
        ]
        progressed = [outcome for outcome in observed if outcome["semantic_progress"]]
        self.processed_count += len(progressed)
        self.database_busy_count += len(database_busy)
        if database_busy:
            self.last_error = "durable database busy; retry deferred"
        self.last_outcomes = observed[-20:]
        if len(progressed) == self.max_concurrency:
            # Continue a bounded backlog promptly without recursively running work.
            self.notifier.notify()
        return tuple(observed)

    def _run_worker_slot(self, *, worker_id: str) -> dict[str, Any]:
        with self._active_worker_lock:
            if not self._accepting_work:
                return {
                    "execution_id": None,
                    "action": "idle",
                    "semantic_progress": False,
                    "lifecycle_state": None,
                    "state_version": None,
                    "effect_certainty": None,
                    "retry_eligibility": None,
                }
            self._active_worker_ids.add(worker_id)
        try:
            return _run_durable_work_once_in_worker(
                self.worker_factory,
                worker_id=worker_id,
            )
        finally:
            with self._active_worker_lock:
                self._active_worker_ids.discard(worker_id)
                if not self._accepting_work and not self._active_worker_ids:
                    self._shutdown_incomplete = False

    def _active_worker_count(self) -> int:
        with self._active_worker_lock:
            return len(self._active_worker_ids)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": self._running,
            "accepting_work": self._accepting_work,
            "active_worker_count": self._active_worker_count(),
            "shutdown_incomplete": self._shutdown_incomplete,
            "disabled_reason": self.disabled_reason,
            "last_tick_at": self.last_tick_at,
            "tick_count": self.tick_count,
            "processed_count": self.processed_count,
            "database_busy_count": self.database_busy_count,
            "last_error": self.last_error,
            "last_outcomes": self.last_outcomes,
            "worker_id_prefix": self.worker_id_prefix,
            "poll_interval_seconds": self.poll_interval_seconds,
            "max_concurrency": self.max_concurrency,
        }


__all__ = [
    "DurableWorkWorker",
    "RuntimeSignalNotifier",
    "V3BackgroundRuntimeService",
    "V3DurableWorkCoordinator",
    "V3DurableWorkSupervisor",
]
