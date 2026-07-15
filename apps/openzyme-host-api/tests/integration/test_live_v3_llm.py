from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from openzyme_runtime.live_testing import LiveStageTimeout
from openzyme_runtime.live_testing import derive_live_stage_timeout_seconds
from openzyme_host_api import HostApiDependencies
from openzyme_host_api import HostSecurityPolicy
from openzyme_host_api import create_app
from openzyme_host_api.evals import run_v3_live_evals
from openzyme_host_api.foundation import build_configured_foundation
from openzyme_host_api.foundation import apply_live_llm_test_budget
from openzyme_runtime import get_settings


pytestmark = [pytest.mark.integration, pytest.mark.live_llm]


class LiveV3LlmTimeoutError(TimeoutError):
    """Raised when the live V3 LLM smoke test exceeds the local timeout budget."""


def _poll_v3_background_workspace(
    client: TestClient,
    *,
    session_id: str,
    timeout_seconds: float,
) -> tuple[dict[str, object], str, dict[str, object]]:
    deadline = time.monotonic() + timeout_seconds
    workspace: dict[str, object] = {}
    event_text = ""
    runtime_status: dict[str, object] = {}
    while time.monotonic() < deadline:
        workspace_response = client.get(f"/v3/sessions/{session_id}/workspace")
        assert workspace_response.status_code == 200, {
            "step": "get_v3_workspace",
            "body": workspace_response.text,
            "workspace": workspace,
            "runtime_status": client.get("/debug/v3-runtime").json(),
            "events": event_text[-1000:],
        }
        workspace = workspace_response.json()
        runtime_response = client.get("/debug/v3-runtime")
        assert runtime_response.status_code == 200, runtime_response.text
        runtime_status = runtime_response.json()

        task_items = workspace["task_board"]["items"]
        assistant_messages = [
            message
            for message in workspace["conversation"]
            if message["role"] == "assistant"
        ]
        if task_items and assistant_messages:
            while time.monotonic() < deadline:
                events_response = client.get(
                    f"/v3/sessions/{session_id}/events?replay=1"
                )
                if events_response.status_code == 200:
                    event_text = events_response.text
                    return workspace, event_text, runtime_status
                assert events_response.status_code == 200, {
                    "step": "get_v3_events",
                    "body": events_response.text,
                    "workspace": workspace,
                    "runtime_status": runtime_status,
                    "events": event_text[-1000:],
                }
            return workspace, event_text, runtime_status
        time.sleep(0.2)
    raise AssertionError(
        {
            "workspace": workspace,
            "runtime_status": runtime_status,
            "events": event_text[-1000:],
        }
    )


def test_live_v3_message_loop_can_create_a_task_via_real_llm() -> None:
    settings = apply_live_llm_test_budget(get_settings())
    foundation = build_configured_foundation(
        settings=settings,
    )
    app = create_app(
        HostApiDependencies(
            foundation=foundation,
            security_policy=HostSecurityPolicy(
                deployment_profile="local-dev",
                principals_by_digest={},
                debug_enabled=True,
            ),
            v3_background_runtime_enabled=True,
        )
    )

    message_timeout_seconds = derive_live_stage_timeout_seconds(
        provider_timeout_seconds=settings.llm.timeout,
        attempts=settings.llm.max_retries + 1,
        buffer_seconds=45,
        minimum_seconds=90,
    )
    with TestClient(app) as client:
        created = client.post(
            "/v3/sessions",
            json={
                "session_id": "sess_live_v3_llm",
                "project_id": "proj_001",
                "objective": "Use the top-level LLM loop to capture user work as a task.",
            },
        )
        assert created.status_code == 200

        with LiveStageTimeout(
            "posting live V3 message through real LLM",
            message_timeout_seconds,
            timeout_type=LiveV3LlmTimeoutError,
        ):
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
            assert response.json()["outputs"] == []
            workspace, event_text, runtime_status = _poll_v3_background_workspace(
                client,
                session_id="sess_live_v3_llm",
                timeout_seconds=message_timeout_seconds,
            )

    task_items = workspace["task_board"]["items"]
    assert any(
        item["task"]["subject"] == "Capture design goals"
        and item["task"]["description"] == "Extract the user design goals into a tracked task."
        for item in task_items
    )
    assert "event: tool.completed" in event_text
    assert "event: signal.claimed" in event_text
    assert "event: signal.completed" in event_text
    assert runtime_status["worker_id"] == "host-api:background-runtime"
    assert any(
        message["role"] == "assistant" for message in workspace["conversation"]
    )


def test_live_v3_eval_generates_design_task_plan() -> None:
    settings = apply_live_llm_test_budget(get_settings())
    eval_timeout_seconds = derive_live_stage_timeout_seconds(
        provider_timeout_seconds=settings.llm.timeout,
        attempts=settings.llm.max_retries + 1,
        buffer_seconds=60,
        minimum_seconds=120,
    )
    with LiveStageTimeout(
        "running live V3 eval design task plan",
        eval_timeout_seconds,
        timeout_type=LiveV3LlmTimeoutError,
    ):
        summary = run_v3_live_evals(
            upload_results=get_settings().test.upload_langsmith,
        )

    assert summary["scenario_count"] == 1
    assert summary["failed"] == 0
    result = summary["results"][0]
    assert result["scenario_id"] == "v3_live_design_task_plan"
    assert summary["passed"] == 1
    assert result["task_count"] >= 3
    assert {"Extract design goals", "Run execution screen", "Draft final report"} <= set(result["subjects"])
