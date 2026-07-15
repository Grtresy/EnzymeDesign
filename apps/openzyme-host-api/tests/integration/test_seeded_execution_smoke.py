from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openzyme_core import CoreRepositories
from openzyme_core import SQLiteRepositoryProvider
from openzyme_domain import ArtifactKind
from openzyme_domain import SessionArtifactRecord
from openzyme_host_api.app import HostApiDependencies
from openzyme_host_api.app import create_app
from openzyme_host_api.foundation import apply_live_llm_test_budget
from openzyme_host_api.foundation import build_configured_foundation
from openzyme_runtime import get_settings
from openzyme_runtime.live_testing import LiveStageTimeout
from openzyme_runtime.live_testing import derive_live_graph_timeout_seconds


pytestmark = [
    pytest.mark.integration,
    pytest.mark.seeded_live_smoke,
    pytest.mark.slow,
]


class SeededExecutionSmokeTimeoutError(TimeoutError):
    """Raised when the seeded V3 execution smoke exceeds its local timeout budget."""


def _log_phase(message: str) -> None:
    print(f"[seeded_execution_smoke] {message}", flush=True)


def _raise_for_status_with_body(response, *, step: str) -> None:
    if response.is_success:
        return
    pytest.fail(
        f"{step} failed with HTTP {response.status_code}: {response.text}",
        pytrace=False,
    )


def _seed_v3_structure_artifact(
    repositories: CoreRepositories,
    *,
    session_id: str,
) -> None:
    fixture_path = (
        Path(__file__).parents[2]
        / "src"
        / "openzyme_host_api"
        / "fixtures"
        / "fpocket"
        / "1ubq.pdb"
    ).resolve()
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="art_seeded_structure",
            session_id=session_id,
            task_id=None,
            lane_id=None,
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.STRUCTURE,
            storage_uri=str(fixture_path),
            relative_path="fixtures/fpocket/1ubq.pdb",
            title="1ubq.pdb",
            description="Seeded structure fixture for V3 live execution smoke.",
            metadata={
                "source": "seeded_live_smoke_fixture",
                "format": "pdb",
                "validation_profile": "fpocket_valid",
            },
            created_at="2026-04-20T12:00:03+00:00",
        )
    )


def _manual_debug_drain_until_report(
    client: TestClient,
    *,
    session_id: str,
    max_cycles: int = 8,
) -> dict[str, Any]:
    latest: dict[str, Any] | None = None
    for cycle in range(max_cycles):
        _log_phase(f"manual/debug draining V3 runtime cycle {cycle + 1}/{max_cycles}")
        drained = client.post(
            f"/v3/sessions/{session_id}/runtime/drain",
            json={
                "max_signals": 10,
                "max_steps_per_agent": 8,
            },
        )
        _raise_for_status_with_body(drained, step="manual_debug_runtime_drain")
        latest = drained.json()
        workspace = latest["workspace"]

        approvals = workspace["pending_approvals"]
        if approvals:
            approval = approvals[0]
            _log_phase(f"approving V3 approval {approval['approval_id']}")
            resolved = client.post(
                f"/v3/approvals/{approval['approval_id']}/resolve",
                json={"decision": "approved"},
            )
            _raise_for_status_with_body(resolved, step="resolve_v3_approval")
            continue

        if workspace["reports"] and workspace["artifacts"] and any(
            item.get("status") == "succeeded"
            for item in workspace["capabilities"].get("execution", [])
        ):
            return workspace

    assert latest is not None
    return latest["workspace"]


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


def test_seeded_v3_master_message_execution_smoke_reaches_report(tmp_path) -> None:
    settings = apply_live_llm_test_budget(get_settings())
    tuned_settings = replace(
        settings,
        llm=replace(
            settings.llm,
            max_tokens=max(settings.llm.max_tokens or 0, 512),
            max_retries=max(settings.llm.max_retries, 1),
        ),
        research=replace(
            settings.research,
            allow_clarification=False,
            max_research_iterations=1,
            max_react_tool_calls=1,
            max_concurrent_research_units=1,
        ),
    )
    e2e_timeout_seconds = derive_live_graph_timeout_seconds(
        llm_timeout_seconds=tuned_settings.llm.timeout,
        structured_attempts=tuned_settings.llm.max_retries + 1,
        tavily_timeout_seconds=tuned_settings.research.tavily_timeout_seconds,
        expected_llm_call_budget=14,
        expected_tavily_budget=1,
        buffer_seconds=180,
        minimum_seconds=300,
    )
    _log_phase("building configured foundation")
    foundation = build_configured_foundation(
        settings=tuned_settings,
    )
    v3_repository_provider = SQLiteRepositoryProvider(
        str(tmp_path / "seeded-execution.sqlite3")
    )
    observer_scope = v3_repository_provider.connection_scope()
    v3_repositories = observer_scope.__enter__().repositories
    _log_phase("creating FastAPI test client")
    client = TestClient(
        create_app(
            HostApiDependencies(
                foundation=foundation,
                v3_repository_provider=v3_repository_provider,
            )
        )
    )

    session_id = "sess_seeded_v3_smoke"
    try:
        with LiveStageTimeout(
            "running seeded V3 master-message smoke to report",
            e2e_timeout_seconds,
            timeout_type=SeededExecutionSmokeTimeoutError,
        ):
            _log_phase("creating V3 session")
            created = client.post(
                "/v3/sessions",
                json={
                    "session_id": session_id,
                    "project_id": "proj_001",
                    "objective": (
                        "Research, execute fpocket against the seeded structure "
                        "artifact, and publish a final V3 report."
                    ),
                    "title": "Seeded V3 execution smoke",
                },
            )
            _raise_for_status_with_body(created, step="create_v3_session")
            _seed_v3_structure_artifact(v3_repositories, session_id=session_id)

            _log_phase("sending the single master user message")
            first_turn = client.post(
                f"/v3/sessions/{session_id}/messages",
                json={
                    "message": (
                        "Run the complete V3 workflow using the existing structure "
                        "artifact art_seeded_structure for fpocket execution. "
                        "Delegate research first, run execution after approval if "
                        "required, and publish the final report."
                    ),
                },
            )
            _raise_for_status_with_body(first_turn, step="post_v3_message")
            workspace = _manual_debug_drain_until_report(client, session_id=session_id)

            _log_phase(
                "final V3 workspace: "
                f"reports={len(workspace['reports'])} "
                f"artifacts={len(workspace['artifacts'])}"
            )

            assert workspace["reports"], _workspace_failure_summary(workspace)
            assert workspace["reports"][0]["status"] in {"ready", "published"}
            assert workspace["artifacts"], _workspace_failure_summary(workspace)
            assert "execution" in workspace["capabilities"], _workspace_failure_summary(workspace)
            execution_capability = _succeeded_capability(workspace, "execution")
            assert execution_capability["runs"]
            assert "deep_research" in workspace["capabilities"], _workspace_failure_summary(workspace)
            research_capability = workspace["capabilities"]["deep_research"][0]
            assert research_capability["status"] == "succeeded"
            assert research_capability["canonical_summary"]["summary"]
            assert research_capability["evidence"]
            assert research_capability["source_refs"]
    finally:
        _log_phase("closing FastAPI test client")
        client.close()
        observer_scope.__exit__(None, None, None)
