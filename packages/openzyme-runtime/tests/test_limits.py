from __future__ import annotations

import asyncio
import threading
import time

from openzyme_runtime import LimiterRegistry


def test_async_limiter_caps_concurrent_provider_calls() -> None:
    async def run_test() -> int:
        registry = LimiterRegistry({"llm_provider": 2})
        limiter = registry.async_limiter("llm_provider")
        active = 0
        observed_max = 0
        lock = asyncio.Lock()

        async def operation() -> None:
            nonlocal active, observed_max
            async with lock:
                active += 1
                observed_max = max(observed_max, active)
            await asyncio.sleep(0.01)
            async with lock:
                active -= 1

        await asyncio.gather(*(limiter.run(operation) for _ in range(10)))
        return observed_max

    assert asyncio.run(run_test()) == 2


def test_sync_limiter_caps_concurrent_blocking_provider_calls() -> None:
    async def run_test() -> int:
        registry = LimiterRegistry({"research_provider": 3})
        limiter = registry.async_limiter("research_provider")
        active = 0
        observed_max = 0
        lock = threading.Lock()

        def blocking_operation() -> None:
            nonlocal active, observed_max
            with lock:
                active += 1
                observed_max = max(observed_max, active)
            try:
                time.sleep(0.01)
            finally:
                with lock:
                    active -= 1

        await asyncio.gather(*(limiter.run_sync(blocking_operation) for _ in range(10)))
        return observed_max

    assert asyncio.run(run_test()) == 3
