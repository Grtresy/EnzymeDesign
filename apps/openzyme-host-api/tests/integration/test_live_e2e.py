from __future__ import annotations

from dataclasses import replace
import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openzyme_core import CoreRepositories
from openzyme_core import apply_sqlite_migrations as apply_v3_sqlite_migrations
from openzyme_core import connect_sqlite as connect_v3_sqlite
from openzyme_host_api.app import HostApiDependencies
from openzyme_host_api.app import create_app
from openzyme_host_api.foundation import apply_live_llm_test_budget
from openzyme_host_api.foundation import build_configured_foundation
from openzyme_runtime import get_settings
from openzyme_runtime.live_testing import LiveStageTimeout
from openzyme_runtime.live_testing import derive_live_graph_timeout_seconds
from openzyme_runtime.live_testing import log_live_phase


pytestmark = [pytest.mark.integration, pytest.mark.live_e2e, pytest.mark.slow]


class LiveE2ETestTimeoutError(TimeoutError):
    """Raised when the full live E2E gate exceeds its local timeout budget."""


def _raise_for_status_with_body(response, *, step: str) -> None:
    if response.is_success:
        return
    pytest.fail(
        f"{step} failed with HTTP {response.status_code}: {response.text}",
        pytrace=False,
    )


def _build_v3_repositories() -> CoreRepositories:
    connection = connect_v3_sqlite(":memory:")
    apply_v3_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _poll_until_product_path_quiescent(
    client: TestClient,
    *,
    session_id: str,
    timeout_seconds: float,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    latest_workspace: dict[str, Any] | None = None
    latest_events = ""
    latest_runtime: dict[str, Any] = {}
    cycle = 0
    while time.monotonic() < deadline:
        cycle += 1
        log_live_phase(f"polling V3 background runtime cycle {cycle}")
        workspace_response = client.get(f"/v3/sessions/{session_id}/workspace")
        if workspace_response.status_code != 200:
            runtime_response = client.get("/debug/v3-runtime")
            assert workspace_response.status_code == 200, {
                "step": "get_v3_workspace",
                "body": workspace_response.text,
                "workspace": latest_workspace,
                "runtime_status": runtime_response.json()
                if runtime_response.status_code == 200
                else runtime_response.text,
                "events": latest_events[-1000:],
            }
        workspace = workspace_response.json()
        latest_workspace = workspace
        events_response = client.get(f"/v3/sessions/{session_id}/events?replay=1")
        _raise_for_status_with_body(events_response, step="get_v3_events")
        latest_events = events_response.text
        runtime_response = client.get("/debug/v3-runtime")
        _raise_for_status_with_body(runtime_response, step="get_v3_runtime_debug")
        latest_runtime = runtime_response.json()

        approvals = workspace["pending_approvals"]
        if approvals:
            approval = approvals[0]
            log_live_phase(f"approving V3 approval {approval['approval_id']}")
            resolved = client.post(
                f"/v3/approvals/{approval['approval_id']}/resolve",
                json={"decision": "approved", "actor_ref": "live_e2e"},
            )
            _raise_for_status_with_body(resolved, step="resolve_v3_approval")
            time.sleep(1.0)
            continue

        if workspace["reports"] and workspace["artifacts"] and any(
            item.get("status") == "succeeded"
            for item in workspace["capabilities"].get("execution", [])
        ):
            return workspace, latest_events, latest_runtime
        time.sleep(1.0)

    assert latest_workspace is not None
    return latest_workspace, latest_events, latest_runtime


def _workspace_failure_summary(workspace: dict[str, Any]) -> str:
    capabilities = workspace.get("capabilities") or {}
    return json.dumps(
        {
            "tasks": [
                item.get("task", {})
                for item in (workspace.get("task_board") or {}).get("items", [])
            ],
            "artifacts": workspace.get("artifacts", []),
            "deep_research": capabilities.get("deep_research", []),
            "execution": capabilities.get("execution", []),
            "reports": workspace.get("reports", []),
            "pending_approvals": workspace.get("pending_approvals", []),
        },
        sort_keys=True,
        indent=2,
    )


def _succeeded_capability(workspace: dict[str, Any], capability: str) -> dict[str, Any]:
    for item in (workspace.get("capabilities") or {}).get(capability, []):
        if item.get("status") == "succeeded":
            return item
    raise AssertionError(_workspace_failure_summary(workspace))


def test_live_v3_master_message_e2e_reaches_report(tmp_path) -> None:
    log_live_phase("loading live E2E settings")
    settings = apply_live_llm_test_budget(get_settings())
    tuned_settings = replace(
        settings,
        llm=replace(
            settings.llm,
            timeout=max(settings.llm.timeout, 120.0),
            max_tokens=max(settings.llm.max_tokens or 0, 512),
            structured_output_max_attempts=max(
                settings.llm.structured_output_max_attempts or 0,
                2,
            ),
        ),
        research=replace(
            settings.research,
            max_units=1,
            allow_clarification=False,
            max_research_iterations=1,
            max_react_tool_calls=1,
            max_concurrent_research_units=1,
        ),
    )
    e2e_timeout_seconds = derive_live_graph_timeout_seconds(
        llm_timeout_seconds=tuned_settings.llm.timeout,
        structured_attempts=tuned_settings.llm.structured_output_max_attempts,
        tavily_timeout_seconds=tuned_settings.research.tavily_timeout_seconds,
        expected_llm_call_budget=16,
        expected_tavily_budget=1,
        buffer_seconds=240,
        minimum_seconds=300,
    )
    foundation = build_configured_foundation(
        sqlite_db_path=tmp_path / "live-v3-e2e.sqlite3",
        settings=tuned_settings,
    )
    v3_repositories = _build_v3_repositories()
    session_id = "sess_live_v3_e2e"
    with TestClient(
        create_app(
            HostApiDependencies(
                foundation=foundation,
                v3_repositories=v3_repositories,
                v3_background_runtime_enabled=True,
            )
        )
    ) as client:
        with LiveStageTimeout(
            "running full V3 live E2E from one master message",
            e2e_timeout_seconds,
            timeout_type=LiveE2ETestTimeoutError,
        ):
            log_live_phase("creating V3 session")
            created = client.post(
                "/v3/sessions",
                json={
                    "session_id": session_id,
                    "project_id": "proj_001",
                    "objective": (
                        "Use live web research to identify enzyme engineering "
                        "evidence and a real RCSB PDB structure, download the "
                        "structure as an execution-ready artifact, run HPC/fpocket "
                        "against that artifact, and publish the final report."
                    ),
                    "title": "Full live V3 E2E",
                },
            )
            _raise_for_status_with_body(created, step="create_v3_session")

            log_live_phase("sending the single master user message")
            first_turn = client.post(
                f"/v3/sessions/{session_id}/messages",
                json={
                    "message": (
                        "Run the complete V3 workflow end to end: delegate live "
                        "web research first, identify an enzyme with a real RCSB "
                        "PDB structure, download that structure as a workspace "
                        "artifact, run HPC/fpocket only against that real artifact, "
                        "get approval if required, and publish the final report. "
                        "If web research or a valid execution artifact is missing, "
                        "surface the failure instead of writing a report."
                    ),
                },
            )
            _raise_for_status_with_body(first_turn, step="post_v3_message")
            workspace, event_text, runtime_status = _poll_until_product_path_quiescent(
                client,
                session_id=session_id,
                timeout_seconds=e2e_timeout_seconds,
            )

    assert workspace["reports"], _workspace_failure_summary(workspace)
    assert workspace["reports"][0]["status"] in {"ready", "published"}
    assert workspace["artifacts"], _workspace_failure_summary(workspace)
    assert "deep_research" in workspace["capabilities"], _workspace_failure_summary(
        workspace
    )
    research_capability = workspace["capabilities"]["deep_research"][0]
    assert research_capability["status"] == "succeeded"
    assert research_capability["canonical_summary"]["summary"]
    assert research_capability["evidence"]
    assert research_capability["source_refs"]
    assert "execution" in workspace["capabilities"]
    execution_capability = _succeeded_capability(workspace, "execution")
    assert execution_capability["runs"]
    assert any(
        item["task"]["kind"] == "research" for item in workspace["task_board"]["items"]
    )
    assert any(
        item["task"]["kind"] == "execution" for item in workspace["task_board"]["items"]
    )
    assert any(
        item["task"]["kind"] in {"reporting", "report"}
        for item in workspace["task_board"]["items"]
    ), _workspace_failure_summary(workspace)
    assert runtime_status["enabled"] is True
    assert runtime_status["running"] is True
    assert runtime_status["worker_id"] == "host-api:background-runtime"
    assert "event: signal.queued" in event_text
    assert "event: signal.claimed" in event_text
    assert "event: signal.completed" in event_text
    assert {"master", "researcher", "executor", "reporter"} <= {
        item["agent"]["role"] for item in workspace["delegation"]["agents"]
    }
    assert any(
        item["agent"]["role"] != "master"
        and item["agent"]["runtime_state"] in {"idle", "failed"}
        for item in workspace["delegation"]["agents"]
    )
