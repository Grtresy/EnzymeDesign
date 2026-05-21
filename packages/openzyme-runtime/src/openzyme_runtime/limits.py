from __future__ import annotations

import asyncio
from contextvars import ContextVar
import threading
from collections.abc import Awaitable
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from typing import TypeVar


T = TypeVar("T")
_HELD_ASYNC_LIMITERS: ContextVar[frozenset[str]] = ContextVar(
    "_HELD_ASYNC_LIMITERS",
    default=frozenset(),
)


@dataclass(slots=True)
class AsyncConcurrencyLimiter:
    name: str
    max_concurrency: int
    _semaphore: asyncio.Semaphore = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        self._semaphore = asyncio.Semaphore(self.max_concurrency)

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        held = _HELD_ASYNC_LIMITERS.get()
        if self.name in held:
            return await operation()
        async with self._semaphore:
            token = _HELD_ASYNC_LIMITERS.set(held | {self.name})
            try:
                return await operation()
            finally:
                _HELD_ASYNC_LIMITERS.reset(token)

    async def run_sync(self, operation: Callable[[], T]) -> T:
        held = _HELD_ASYNC_LIMITERS.get()
        if self.name in held:
            return await asyncio.to_thread(operation)
        async with self._semaphore:
            token = _HELD_ASYNC_LIMITERS.set(held | {self.name})
            try:
                return await asyncio.to_thread(operation)
            finally:
                _HELD_ASYNC_LIMITERS.reset(token)


@dataclass(slots=True)
class SyncConcurrencyLimiter:
    name: str
    max_concurrency: int
    _semaphore: threading.BoundedSemaphore = field(init=False, repr=False)
    _local: threading.local = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        self._semaphore = threading.BoundedSemaphore(self.max_concurrency)
        self._local = threading.local()

    def run(self, operation: Callable[[], T]) -> T:
        depth = int(getattr(self._local, "depth", 0))
        if depth > 0:
            return operation()
        with self._semaphore:
            self._local.depth = depth + 1
            try:
                return operation()
            finally:
                self._local.depth = depth


@dataclass(slots=True)
class LimiterRegistry:
    limits: dict[str, int]
    _async_limiters: dict[str, AsyncConcurrencyLimiter] = field(init=False, repr=False)
    _sync_limiters: dict[str, SyncConcurrencyLimiter] = field(init=False, repr=False)
    _registry_lock: threading.Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        for name, value in self.limits.items():
            if int(value) <= 0:
                raise ValueError(f"limit {name!r} must be positive")
        self._async_limiters: dict[str, AsyncConcurrencyLimiter] = {}
        self._sync_limiters: dict[str, SyncConcurrencyLimiter] = {}
        self._registry_lock = threading.Lock()

    def async_limiter(self, name: str) -> AsyncConcurrencyLimiter:
        with self._registry_lock:
            if name not in self._async_limiters:
                self._async_limiters[name] = AsyncConcurrencyLimiter(
                    name=name,
                    max_concurrency=self._limit_for(name),
                )
            return self._async_limiters[name]

    def sync_limiter(self, name: str) -> SyncConcurrencyLimiter:
        with self._registry_lock:
            if name not in self._sync_limiters:
                self._sync_limiters[name] = SyncConcurrencyLimiter(
                    name=name,
                    max_concurrency=self._limit_for(name),
                )
            return self._sync_limiters[name]

    def _limit_for(self, name: str) -> int:
        return int(self.limits.get(name, self.limits.get("*", 1)))


DEFAULT_PROVIDER_LIMITS = {
    "agent": 1,
    "session": 1,
    "global": 4,
    "llm_provider": 2,
    "research_provider": 2,
    "execution_provider": 1,
}


__all__ = [
    "AsyncConcurrencyLimiter",
    "DEFAULT_PROVIDER_LIMITS",
    "LimiterRegistry",
    "SyncConcurrencyLimiter",
]
