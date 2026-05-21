from __future__ import annotations

import asyncio
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Callable

from openzyme_domain.control_plane import utc_now_iso
from openzyme_runtime import llm_debug_context

from .v3_service import V3HostApiService


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
    build_service: Callable[[], V3HostApiService]
    notifier: RuntimeSignalNotifier
    enabled: bool
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

    def start(self) -> None:
        if not self.enabled:
            self.disabled_reason = "disabled by configuration"
            return
        service = self.build_service()
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
        service = self.build_service()
        if service.model_factory is None:
            self.disabled_reason = "model_factory unavailable"
            self.last_outcomes = []
            return ()
        remaining = max(0, self.max_signals_per_tick)
        outcomes: list[dict[str, Any]] = []
        try:
            session_ids = service.repositories.runtime_signals.list_claimable_session_ids()
            for session_id in session_ids:
                if remaining <= 0:
                    break
                with llm_debug_context(
                    request_path="background:v3-runtime",
                    session_id=session_id,
                    actor="scheduler",
                ):
                    session_outcomes = await service.run_background_runtime_once(
                        session_id=session_id,
                        worker_id=self.worker_id,
                        max_signals=remaining,
                        max_steps_per_agent=self.max_steps_per_agent,
                    )
                outcomes.extend(session_outcomes)
                remaining -= len(session_outcomes)
        except Exception as exc:
            self.last_error = str(exc)
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


__all__ = ["RuntimeSignalNotifier", "V3BackgroundRuntimeService"]
