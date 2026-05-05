from __future__ import annotations

import signal

import pytest
from fastapi.testclient import TestClient

from openzyme_host_api import HostApiDependencies
from openzyme_host_api import create_app
from openzyme_host_api.evals import run_v3_live_evals
from openzyme_host_api.foundation import build_configured_foundation
from openzyme_graph.supervisor import build_v2_supervisor_graph
from openzyme_runtime import get_settings


pytestmark = [pytest.mark.integration, pytest.mark.live_llm]


class LiveV3LlmTimeoutError(TimeoutError):
    """Raised when the live V3 LLM smoke test exceeds the local timeout budget."""


class _AlarmTimeout:
    def __init__(self, seconds: int) -> None:
        self._seconds = seconds
        self._previous_handler = None

    def __enter__(self) -> "_AlarmTimeout":
        self._previous_handler = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, self._handle_timeout)
        signal.alarm(self._seconds)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        signal.alarm(0)
        if self._previous_handler is not None:
            signal.signal(signal.SIGALRM, self._previous_handler)
        return None

    @staticmethod
    def _handle_timeout(signum: int, frame: object | None) -> None:
        del signum, frame
        raise LiveV3LlmTimeoutError("live V3 LLM smoke test exceeded its local timeout budget.")


def test_live_v3_message_loop_can_create_a_task_via_real_llm(tmp_path) -> None:
    foundation = build_configured_foundation(sqlite_db_path=tmp_path / "live-v3-llm.sqlite3")
    client = TestClient(
        create_app(
            HostApiDependencies(
                foundation=foundation,
                graph_builder=build_v2_supervisor_graph,
            )
        )
    )

    created = client.post(
        "/v3/sessions",
        json={
            "session_id": "sess_live_v3_llm",
            "project_id": "proj_001",
            "objective": "Use the top-level LLM loop to capture user work as a task.",
        },
    )
    assert created.status_code == 200

    with _AlarmTimeout(90):
        response = client.post(
            "/v3/sessions/sess_live_v3_llm/messages",
            json={
                "message": (
                    "Call task.create exactly once to create a task with subject "
                    "'Capture design goals' and description 'Extract the user design goals into a tracked task.' "
                    "Then reply with one short confirmation sentence."
                )
            },
        )

    assert response.status_code == 200
    payload = response.json()
    task_items = payload["workspace"]["task_board"]["items"]
    assert task_items
    assert any(
        item["task"]["subject"] == "Capture design goals"
        and item["task"]["description"] == "Extract the user design goals into a tracked task."
        for item in task_items
    )
    assert any(event["event_type"] == "tool.completed" for event in payload["events"])
    assert payload["workspace"]["conversation"]
    assert payload["outputs"]


def test_live_v3_eval_generates_design_task_plan() -> None:
    with _AlarmTimeout(120):
        summary = run_v3_live_evals(
            upload_results=get_settings().test.upload_langsmith,
        )

    assert summary["scenario_count"] == 1
    assert summary["failed"] == 0
    result = summary["results"][0]
    assert result["scenario_id"] == "v3_live_design_task_plan"
    assert result["task_count"] >= 3
