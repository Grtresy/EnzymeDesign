from __future__ import annotations

import asyncio
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from .agent_runtime import AgentRuntimeOutcome
from .agent_runtime import AgentRuntimeService
from .harness import SessionRuntimeContext


@dataclass(slots=True)
class AgentRuntimeScheduler:
    context: SessionRuntimeContext
    worker_id: str = "scheduler:local"
    lease_seconds: int = 300
    max_global_concurrency: int = 1
    max_session_concurrency: int = 1
    max_agent_concurrency: int = 1
    _shutdown_requested: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
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
    ) -> tuple[AgentRuntimeOutcome, ...]:
        if self.context.model_factory is None or max_signals <= 0:
            return ()
        global_limiter = asyncio.Semaphore(self.max_global_concurrency)
        session_limiter = asyncio.Semaphore(self.max_session_concurrency)
        agent_limiters: dict[str, asyncio.Semaphore] = {}

        async def run_signal(signal: Any) -> AgentRuntimeOutcome:
            agent_limiter = agent_limiters.setdefault(
                str(signal.agent_id),
                asyncio.Semaphore(self.max_agent_concurrency),
            )
            async with global_limiter:
                async with session_limiter:
                    async with agent_limiter:
                        return await asyncio.to_thread(
                            AgentRuntimeService(self.context).wake_agent,
                            signal,
                            max_steps=max_steps_per_agent,
                        )

        outcomes: list[AgentRuntimeOutcome] = []
        while len(outcomes) < max_signals and not self._shutdown_requested:
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
                )
                if signal is None:
                    break
                signals.append(signal)
            if not signals:
                break
            outcomes.extend(await asyncio.gather(*(run_signal(signal) for signal in signals)))
        return tuple(outcomes)

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
    ) -> tuple[AgentRuntimeOutcome, ...]:
        return asyncio.run(
            self.run_once(
                session_id,
                max_signals=max_signals,
                max_steps_per_agent=max_steps_per_agent,
                signal_ids=signal_ids,
            )
        )


__all__ = ["AgentRuntimeScheduler"]
