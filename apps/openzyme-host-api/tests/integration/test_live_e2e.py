from __future__ import annotations

import signal

import pytest
from fastapi.testclient import TestClient

from openzyme_graph.supervisor import build_v2_supervisor_graph
from openzyme_host_api.app import HostApiDependencies
from openzyme_host_api.app import create_app
from openzyme_host_api.foundation import build_configured_foundation


pytestmark = [pytest.mark.integration, pytest.mark.live_e2e, pytest.mark.slow]


class LiveE2ETestTimeoutError(TimeoutError):
    """Raised when the live E2E test exceeds its local timeout budget."""


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
        raise LiveE2ETestTimeoutError("live_e2e test exceeded its local timeout budget.")


def _log_phase(message: str) -> None:
    print(f"[live_e2e] {message}", flush=True)


def _raise_for_status_with_body(response, *, step: str) -> None:
    if response.is_success:
        return
    pytest.fail(
        f"{step} failed with HTTP {response.status_code}: {response.text}",
        pytrace=False,
    )


def test_live_supervisor_e2e_reaches_report(tmp_path) -> None:
    _log_phase("building configured foundation")
    foundation = build_configured_foundation(sqlite_db_path=tmp_path / "live-e2e.sqlite3")
    _log_phase("creating FastAPI test client")
    client = TestClient(
        create_app(
            HostApiDependencies(
                foundation=foundation,
                graph_builder=build_v2_supervisor_graph,
            )
        )
    )

    try:
        with _AlarmTimeout(300):
            _log_phase("creating episode")
            created = client.post(
                "/commands/create_episode",
                json={
                    "project_id": "proj_001",
                    "objective": "Research, design, execute, and report on a thermostable enzyme candidate",
                },
            )
            _raise_for_status_with_body(created, step="create_episode")
            episode_id = created.json()["episode_id"]
            _log_phase(f"episode created: {episode_id}")

            _log_phase("loading first pending actions")
            first_pending = client.get(f"/episodes/{episode_id}/pending-actions")
            _raise_for_status_with_body(first_pending, step="load_first_pending_actions")
            first_actions = first_pending.json()
            assert first_actions
            _log_phase(f"first approval ready: {first_actions[0]['approval_id']}")

            _log_phase("approving design phase")
            approved_design = client.post(
                "/commands/resolve_approval",
                json={
                    "episode_id": episode_id,
                    "approval_id": first_actions[0]["approval_id"],
                    "decision": "approved",
                },
            )
            _raise_for_status_with_body(approved_design, step="approve_design")
            _log_phase("design approval submitted")

            _log_phase("loading final workspace")
            workspace = client.get(f"/episodes/{episode_id}/workspace")
            _raise_for_status_with_body(workspace, step="load_final_workspace")
            payload = workspace.json()
            _log_phase(
                "final workflow state: "
                f"{payload['workflow']['current_phase']} / {payload['workflow']['status']}"
            )

            assert payload["workflow"]["status"] == "completed"
            assert payload["workflow"]["current_phase"] == "report_review"
            assert payload["report"] is not None
            assert payload["runs"]
            assert payload["artifacts"]
    finally:
        _log_phase("closing FastAPI test client")
        client.close()
