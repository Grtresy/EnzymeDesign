from __future__ import annotations

from pathlib import Path

from enzyme_host_runtime.execution import ExecutionResult
from enzyme_host_runtime.execution import RoutedExecutionAdapter
from enzyme_host_runtime.execution import StepExecutor
from enzyme_host_runtime.planning import AgentAction
from enzyme_host_runtime.planning import AgentWorkflowOrchestrator
from enzyme_host_runtime.planning import HeuristicAgentAdapter
from enzyme_host_runtime.planning import ToolAction
from enzyme_host_runtime.planning.models import new_object_id
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


class _ExplodingPreprocessExecutor(StepExecutor):
    def supports(self, tool: str) -> bool:
        return tool == "prepare_receptor"

    def run_step(self, project_root: Path, episode_id: str, step) -> ExecutionResult:
        raise RuntimeError("missing input file")


class _HpcAdapter(HeuristicAgentAdapter):
    def propose_candidate_actions(self, *, state):
        return [
            AgentAction(
                action_id=new_object_id("action"),
                kind="tool",
                title="Run docking",
                rationale="Needs HPC execution",
                tool_action=ToolAction(tool="vina", inputs={"receptor_pdbqt": "a", "ligand_pdbqt": "b"}, risk_level="high"),
            )
        ]


def _build_client(
    tmp_path: Path,
    *,
    executor: StepExecutor | None = None,
    workflow: AgentWorkflowOrchestrator | None = None,
) -> TestClient:
    runtime = HostRuntime(
        executor=RoutedExecutionAdapter([executor or _FakePreprocessExecutor()]),
        workflow=workflow,
    )
    runtime.init_project(tmp_path, "demo-project")
    project_root = tmp_path / "demo-project"
    app = create_app(project_root=project_root, runtime=runtime)
    return TestClient(app)


def test_web_host_agent_flow_can_start_execute_and_report(tmp_path: Path) -> None:
    client = _build_client(tmp_path)

    response = client.get("/")
    assert response.status_code == 200

    response = client.post("/episodes", data={"goal": "improve binding"}, follow_redirects=True)
    assert response.status_code == 200
    assert "0001" in response.text

    response = client.post("/workflow/start", follow_redirects=True)
    assert response.status_code == 200
    assert "Main Timeline" in response.text
    assert 'data-kind="summary"' in response.text
    assert "Open Structure Workbench" not in response.text
    assert "Technical Explanation" in response.text
    assert "Trace / Debug / Raw State / Report" in response.text

    response = client.post("/workflow/execute", follow_redirects=False)
    assert response.status_code == 303
    assert "run_id=local-run-1" in response.headers["location"]

    payload = client.get("/api/status").json()
    assert payload["runs"][0]["run_id"] == "local-run-1"
    assert payload["execution_evidence"]["observation_count"] == 1
    assert payload["agent_state"]["termination_status"] == "completed"
    assert payload["agent_backend"]["backend"] == "heuristic"
    assert "capability_inspected" in [item["event_type"] for item in payload["workflow_audit"]]

    response = client.post("/report", follow_redirects=True)
    assert response.status_code == 200
    assert "Report Preview" in response.text


def test_web_host_can_switch_episode(tmp_path: Path) -> None:
    client = _build_client(tmp_path)

    client.post("/episodes", data={"goal": "episode one"}, follow_redirects=True)
    client.post("/episodes", data={"goal": "episode two"}, follow_redirects=True)
    response = client.post("/episodes/switch", data={"episode_id": "0001"}, follow_redirects=True)

    assert response.status_code == 200
    assert "<strong>0001</strong>" in response.text


def test_web_host_can_submit_feedback_for_pending_interrupt(tmp_path: Path) -> None:
    client = _build_client(tmp_path, executor=_ExplodingPreprocessExecutor())

    client.post("/episodes", data={"goal": "episode one"}, follow_redirects=True)
    client.post("/workflow/start", follow_redirects=True)
    response = client.post("/workflow/execute", follow_redirects=False)
    assert response.status_code == 400
    home = client.get("/")
    assert "Main Timeline" in home.text
    assert 'data-kind="interrupt"' in home.text
    assert "Suggested response" in home.text

    snapshot = client.get("/api/status").json()
    interrupt = snapshot["pending_interrupts"][-1]
    interrupt_id = interrupt["interrupt_id"]
    assert snapshot["stop_reason"] == "needs_input"
    assert snapshot["next_step_suggestion"]

    response = client.post(
        "/workflow/feedback",
        data={
            "interrupt_id": interrupt_id,
            "content": "retry the preparation",
            "kind": "clarification",
            "state_version": interrupt["active_state_version"],
            "resume_token": interrupt["resume_token"],
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    updated = client.get("/api/status").json()
    assert updated["agent_state"]["human_feedback"][-1]["content"] == "retry the preparation"
    assert updated["agent_state"]["selected_action"] is not None


def test_web_host_displays_and_resolves_approval_gate(tmp_path: Path) -> None:
    client = _build_client(
        tmp_path,
        workflow=AgentWorkflowOrchestrator(adapter=_HpcAdapter()),
    )

    client.post("/episodes", data={"goal": "episode one"}, follow_redirects=True)
    response = client.post("/workflow/start", follow_redirects=True)
    assert response.status_code == 200
    assert "Main Timeline" in response.text
    assert 'data-kind="approval_gate"' in response.text
    assert "这是高成本或远程计算动作" in response.text

    snapshot = client.get("/api/status").json()
    gate_id = snapshot["approval_gates"][-1]["gate_id"]
    action_id = snapshot["agent_state"]["selected_action"]["action_id"]
    interrupt = next(item for item in snapshot["pending_interrupts"] if item.get("gate_id") == gate_id)
    assert snapshot["stop_reason"] == "awaiting_approval"
    assert snapshot["plain_language_explanation"]
    assert gate_id in response.text
    assert f'action="/workflow/gates/{gate_id}/approve"' in response.text

    response = client.post(
        f"/workflow/gates/{gate_id}/approve",
        data={
            "state_version": interrupt["active_state_version"],
            "resume_token": interrupt["resume_token"],
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Execute Approved Action" in response.text
    assert "Execute Selected Action" not in response.text
    assert "Continue Workflow" not in response.text

    updated = client.get("/api/status").json()
    assert any(item["status"] == "approved" for item in updated["approval_gates"])
    assert updated["agent_state"]["selected_action"]["action_id"] == action_id


def test_web_host_hides_continue_after_gate_rejection_blocks_workflow(tmp_path: Path) -> None:
    client = _build_client(
        tmp_path,
        workflow=AgentWorkflowOrchestrator(adapter=_HpcAdapter()),
    )

    client.post("/episodes", data={"goal": "episode one"}, follow_redirects=True)
    client.post("/workflow/start", follow_redirects=True)

    snapshot = client.get("/api/status").json()
    gate_id = snapshot["approval_gates"][-1]["gate_id"]
    interrupt = next(item for item in snapshot["pending_interrupts"] if item.get("gate_id") == gate_id)

    response = client.post(
        f"/workflow/gates/{gate_id}/reject",
        data={
            "state_version": interrupt["active_state_version"],
            "resume_token": interrupt["resume_token"],
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Blocked" in response.text
    assert "Continue Workflow" not in response.text
    assert "Open Structure Workbench" not in response.text

    updated = client.get("/api/status").json()
    assert updated["stop_reason"] == "blocked"


def test_web_host_hides_continue_when_workflow_budget_is_exhausted(tmp_path: Path) -> None:
    client = _build_client(
        tmp_path,
        workflow=AgentWorkflowOrchestrator(
            adapter=HeuristicAgentAdapter(),
            max_decision_rounds=0,
        ),
    )

    client.post("/episodes", data={"goal": "episode one"}, follow_redirects=True)
    response = client.post("/workflow/start", follow_redirects=True)

    assert response.status_code == 200
    assert "Max Turns Exceeded" in response.text
    assert "Continue Workflow" not in response.text

    updated = client.get("/api/status").json()
    assert updated["stop_reason"] == "max_turns_exceeded"


def test_web_host_reconstructs_same_timeline_from_canonical_state_on_refresh(tmp_path: Path) -> None:
    client = _build_client(
        tmp_path,
        workflow=AgentWorkflowOrchestrator(adapter=_HpcAdapter()),
    )

    client.post("/episodes", data={"goal": "episode one"}, follow_redirects=True)
    client.post("/workflow/start", follow_redirects=True)

    snapshot = client.get("/api/status").json()
    gate_id = snapshot["approval_gates"][-1]["gate_id"]
    action_id = snapshot["agent_state"]["selected_action"]["action_id"]

    first = client.get("/")
    second = client.get("/")

    for response in (first, second):
        assert response.status_code == 200
        assert "Main Timeline" in response.text
        assert 'data-kind="summary"' in response.text
        assert 'data-kind="approval_gate"' in response.text
        assert 'data-kind="workbench_slot"' not in response.text
        assert gate_id in response.text
        assert action_id in response.text


def test_web_host_keeps_debug_area_secondary_to_main_timeline(tmp_path: Path) -> None:
    client = _build_client(tmp_path)

    client.post("/episodes", data={"goal": "episode one"}, follow_redirects=True)
    response = client.post("/workflow/start", follow_redirects=True)

    assert response.status_code == 200
    assert "Trace / Debug / Raw State / Report" in response.text
    assert "Technical Explanation" in response.text
    assert response.text.index("Main Timeline") < response.text.index("Trace / Debug / Raw State / Report")
    assert "Workflow Controls" in response.text


def test_web_host_refreshes_on_stale_feedback_submission(tmp_path: Path) -> None:
    client = _build_client(tmp_path, executor=_ExplodingPreprocessExecutor())

    client.post("/episodes", data={"goal": "episode one"}, follow_redirects=True)
    client.post("/workflow/start", follow_redirects=True)
    response = client.post("/workflow/execute", follow_redirects=False)
    assert response.status_code == 400

    snapshot = client.get("/api/status").json()
    interrupt = snapshot["pending_interrupts"][-1]
    form = {
        "interrupt_id": interrupt["interrupt_id"],
        "content": "retry the preparation",
        "kind": "clarification",
        "state_version": interrupt["active_state_version"],
        "resume_token": interrupt["resume_token"],
    }

    first = client.post("/workflow/feedback", data=form, follow_redirects=True)
    assert first.status_code == 200

    second = client.post("/workflow/feedback", data=form, follow_redirects=True)
    assert second.status_code == 200
    assert "Workflow state was stale" in second.text
