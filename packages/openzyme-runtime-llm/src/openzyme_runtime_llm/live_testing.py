from __future__ import annotations

from types import FrameType
import faulthandler
import math
import signal
import sys
import time


class LiveTimeoutError(TimeoutError):
    """Raised when a live integration test exceeds a stage timeout."""


class LiveStageTimeout:
    def __init__(
        self,
        phase: str,
        seconds: float,
        *,
        timeout_type: type[TimeoutError] = LiveTimeoutError,
        hard_exit: bool = True,
        hard_exit_grace_seconds: float = 30.0,
    ) -> None:
        self._phase = phase
        self._seconds = float(seconds)
        self._timeout_type = timeout_type
        self._hard_exit = hard_exit
        self._hard_exit_grace_seconds = float(hard_exit_grace_seconds)
        self._previous_handler = None
        self._previous_timer: tuple[float, float] | None = None
        self._started_at: float | None = None
        self._scheduled_hard_exit = False

    def __enter__(self) -> "LiveStageTimeout":
        marker = (
            f"[live-timeout] start phase={self._phase!r} "
            f"timeout={self._seconds:g}s "
            f"hard_exit_grace={self._hard_exit_grace_seconds:g}s"
        )
        print(marker, file=sys.stderr, flush=True)
        print(
            marker,
            flush=True,
        )
        self._previous_handler = signal.getsignal(signal.SIGALRM)
        self._previous_timer = signal.getitimer(signal.ITIMER_REAL)
        self._started_at = time.monotonic()
        signal.signal(signal.SIGALRM, self._handle_timeout)
        signal.setitimer(signal.ITIMER_REAL, self._seconds)
        if self._hard_exit:
            faulthandler.dump_traceback_later(
                self._seconds + self._hard_exit_grace_seconds,
                repeat=False,
                file=sys.stderr,
                exit=True,
            )
            self._scheduled_hard_exit = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        signal.setitimer(signal.ITIMER_REAL, 0)
        if self._scheduled_hard_exit:
            faulthandler.cancel_dump_traceback_later()
        if self._previous_handler is not None:
            signal.signal(signal.SIGALRM, self._previous_handler)
        if self._previous_timer is not None:
            previous_delay, previous_interval = self._previous_timer
            if previous_delay > 0:
                elapsed = (
                    0.0
                    if self._started_at is None
                    else time.monotonic() - self._started_at
                )
                signal.setitimer(
                    signal.ITIMER_REAL,
                    max(0.001, previous_delay - elapsed),
                    previous_interval,
                )
        if exc_type is None:
            print(f"[live-timeout] finished phase={self._phase!r}", flush=True)
        return None

    def _handle_timeout(self, signum: int, frame: FrameType | None) -> None:
        del signum, frame
        raise self._timeout_type(
            f"stuck while {self._phase} after {self._seconds:g}s"
        )


def log_live_phase(message: str) -> None:
    print(f"[live] {message}", flush=True)


def derive_live_stage_timeout_seconds(
    *,
    provider_timeout_seconds: float | None,
    attempts: int = 1,
    buffer_seconds: float = 30.0,
    minimum_seconds: float = 60.0,
) -> int:
    timeout = 0.0 if provider_timeout_seconds is None else float(provider_timeout_seconds)
    return int(
        math.ceil(
            max(
                float(minimum_seconds),
                timeout * max(1, int(attempts)) + float(buffer_seconds),
            )
        )
    )


def derive_live_graph_timeout_seconds(
    *,
    llm_timeout_seconds: float | None,
    structured_attempts: int,
    tavily_timeout_seconds: float | None,
    expected_llm_call_budget: int,
    expected_tavily_budget: int,
    buffer_seconds: float,
    minimum_seconds: float = 240.0,
) -> int:
    llm_timeout = 0.0 if llm_timeout_seconds is None else float(llm_timeout_seconds)
    tavily_timeout = (
        0.0 if tavily_timeout_seconds is None else float(tavily_timeout_seconds)
    )
    budget = (
        llm_timeout * max(1, int(structured_attempts)) * expected_llm_call_budget
        + tavily_timeout * expected_tavily_budget
        + float(buffer_seconds)
    )
    return int(math.ceil(max(float(minimum_seconds), budget)))
