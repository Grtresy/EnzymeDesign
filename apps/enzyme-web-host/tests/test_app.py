from __future__ import annotations

import json
from pathlib import Path

from enzyme_host_runtime.execution import ExecutionResult
from enzyme_host_runtime.execution import RoutedExecutionAdapter
from enzyme_host_runtime.execution import StepExecutor
from enzyme_host_runtime.services import HostRuntime
from enzyme_web_host.app import create_app
from fastapi.testclient import TestClient


class _FakePreprocessExecutor(StepExecutor):
    def supports(self, tool: str) -> bool:
        return tool == "prepare_receptor"

    def run_step(self, project_root: Path, episode_id: str, step) -> ExecutionResult:
        return ExecutionResult(
            run_id="local-run-1",
            status="completed",
            manifest_payload={
                "backend": "local-preprocess",
                "tool": step.tool,
                "step_id": step.step_id,
                "status": "completed",
                "result": {"status": "completed", "output": {"output_path": "data/inputs/receptor.pdbqt"}},
            },
        )


def _build_client(tmp_path: Path) -> TestClient:
    runtime = HostRuntime(executor=RoutedExecutionAdapter([_FakePreprocessExecutor()]))
    runtime.init_project(tmp_path, "demo-project")
    project_root = tmp_path / "demo-project"
    app = create_app(project_root=project_root, runtime=runtime)
    return TestClient(app)


def test_web_host_flow_load_create_confirm_run_and_report(tmp_path: Path) -> None:
    client = _build_client(tmp_path)

    response = client.get("/")
    assert response.status_code == 200
    assert "No active episode" not in response.text

    response = client.post("/episodes", data={"goal": "improve binding"}, follow_redirects=True)
    assert response.status_code == 200
    assert "0001" in response.text

    plan = {
        "steps": [
            {
                "id": "prep_1",
                "tool": "prepare_receptor",
                "inputs": {"input": "data/inputs/receptor.pdb"},
            }
        ]
    }
    response = client.post(
        "/plan/confirm",
        data={"plan_json": json.dumps(plan)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "confirmed (1 steps)" in response.text

    response = client.post("/run", data={"action": "full", "step_id": ""}, follow_redirects=False)
    assert response.status_code == 303
    assert "run_id=local-run-1" in response.headers["location"]

    response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["episode_id"] == "0001"
    assert payload["runs"][0]["run_id"] == "local-run-1"

    response = client.get("/api/runs/local-run-1")
    assert response.status_code == 200
    assert response.json()["tool"] == "prepare_receptor"

    response = client.post("/report", follow_redirects=True)
    assert response.status_code == 200
    assert "Report Preview" in response.text

    report_response = client.get("/report")
    assert report_response.status_code == 200
    assert "Episode Report: 0001" in report_response.text


def test_web_host_can_switch_episode(tmp_path: Path) -> None:
    client = _build_client(tmp_path)

    client.post("/episodes", data={"goal": "episode one"}, follow_redirects=True)
    client.post("/episodes", data={"goal": "episode two"}, follow_redirects=True)

    response = client.post(
        "/episodes/switch",
        data={"episode_id": "0001"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "<strong>0001</strong>" in response.text


def test_web_host_returns_validation_error_for_run_without_confirmed_plan(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    client.post("/episodes", data={"goal": "episode one"}, follow_redirects=True)

    response = client.post("/run", data={"action": "full", "step_id": ""}, follow_redirects=False)

    assert response.status_code == 400
    assert "No confirmed plan" in response.json()["detail"]
