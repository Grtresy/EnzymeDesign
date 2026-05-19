from __future__ import annotations

import pytest

from openzyme_runtime.live_testing import LiveStageTimeout
from openzyme_runtime.live_testing import LiveTimeoutError
from openzyme_runtime.live_testing import derive_live_graph_timeout_seconds
from openzyme_runtime.live_testing import derive_live_stage_timeout_seconds


def test_live_stage_timeout_raises_pytest_visible_timeout_before_hard_exit() -> None:
    timeout = LiveStageTimeout(
        "invoking live provider",
        60,
        hard_exit=False,
    )

    with pytest.raises(
        LiveTimeoutError,
        match="stuck while invoking live provider after 60s",
    ):
        with timeout:
            timeout._handle_timeout(0, None)


def test_live_stage_timeout_delays_hard_exit_until_after_grace(monkeypatch) -> None:
    scheduled: dict[str, float | bool] = {}

    def fake_dump_traceback_later(timeout, *, repeat, file, exit):
        del file
        scheduled["timeout"] = timeout
        scheduled["repeat"] = repeat
        scheduled["exit"] = exit

    monkeypatch.setattr(
        "openzyme_runtime.live_testing.faulthandler.dump_traceback_later",
        fake_dump_traceback_later,
    )
    monkeypatch.setattr(
        "openzyme_runtime.live_testing.faulthandler.cancel_dump_traceback_later",
        lambda: scheduled.setdefault("cancelled", True),
    )

    with LiveStageTimeout(
        "graph.invoke",
        240,
        hard_exit=True,
        hard_exit_grace_seconds=30,
    ):
        pass

    assert scheduled["timeout"] == 270
    assert scheduled["repeat"] is False
    assert scheduled["exit"] is True
    assert scheduled["cancelled"] is True


def test_derive_live_stage_timeout_respects_provider_timeout_and_attempts() -> None:
    assert (
        derive_live_stage_timeout_seconds(
            provider_timeout_seconds=240,
            attempts=2,
            buffer_seconds=30,
            minimum_seconds=60,
        )
        == 510
    )
    assert (
        derive_live_stage_timeout_seconds(
            provider_timeout_seconds=None,
            attempts=1,
            buffer_seconds=30,
            minimum_seconds=60,
        )
        == 60
    )


def test_derive_live_graph_timeout_uses_whole_graph_budget() -> None:
    assert (
        derive_live_graph_timeout_seconds(
            llm_timeout_seconds=240,
            structured_attempts=2,
            tavily_timeout_seconds=30,
            expected_llm_call_budget=8,
            expected_tavily_budget=2,
            buffer_seconds=60,
        )
        == 3960
    )
    assert (
        derive_live_graph_timeout_seconds(
            llm_timeout_seconds=45,
            structured_attempts=1,
            tavily_timeout_seconds=30,
            expected_llm_call_budget=1,
            expected_tavily_budget=1,
            buffer_seconds=30,
        )
        == 240
    )
