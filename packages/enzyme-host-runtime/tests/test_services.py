from __future__ import annotations

from pathlib import Path

import pytest

from enzyme_host_runtime.execution import ExecutionResult
from enzyme_host_runtime.execution import RoutedExecutionAdapter
from enzyme_host_runtime.execution import StepExecutor
from enzyme_host_runtime.memory_client import MemoryClient
from enzyme_host_runtime.plan_runtime import PlanStep
from enzyme_host_runtime.plan_runtime import load_confirmed_plan
from enzyme_host_runtime.plan_runtime import select_steps
from enzyme_host_runtime.planning import HeuristicAgentAdapter
from enzyme_host_runtime.planning import AgentWorkflowOrchestrator
from enzyme_host_runtime.services import HostRuntime
from enzyme_host_runtime.services import RunRequest
from enzyme_host_runtime.workspace import allocate_episode_id
from enzyme_host_runtime.workspace import init_project
from enzyme_host_runtime.workspace import set_current_episode


def _project(tmp_path: Path):
    context = init_project(tmp_path, "demo-project")
    memory = MemoryClient(context)
    episode_id = allocate_episode_id(context.root)
    memory.create_episode(episode_id, "improve binding")
    set_current_episode(context.root, episode_id)
    return context, memory, episode_id


def test_confirm_plan_updates_canonical_state(tmp_path: Path) -> None:
    context, memory, episode_id = _project(tmp_path)
    runtime = HostRuntime()

    confirmed = runtime.confirm_plan(
        context.root,
        plan={
            "steps": [
                {"id": "pocket_1", "tool": "fpocket", "inputs": {"pdb": "data/inputs/target.pdb"}}
            ]
        },
    )

    assert confirmed["_meta"]["confirmed_at"]
    state = memory.load_state(episode_id)
    assert state["plan"]["status"] == "confirmed"
    assert state["plan"]["step_count"] == 1


def test_load_confirmed_plan_requires_steps(tmp_path: Path) -> None:
    _context, memory, episode_id = _project(tmp_path)
    memory.confirm_plan(episode_id, {"steps": []})

    with pytest.raises(RuntimeError):
        load_confirmed_plan(memory, episode_id)


def test_resume_selects_first_incomplete_step(tmp_path: Path) -> None:
    _context, memory, episode_id = _project(tmp_path)
    memory.confirm_plan(
        episode_id,
        {
            "steps": [
                {"id": "step_1", "tool": "fpocket", "params": {"structure_path": "a.pdb"}},
                {"id": "step_2", "tool": "fpocket", "params": {"structure_path": "b.pdb"}},
                {"id": "step_3", "tool": "fpocket", "params": {"structure_path": "c.pdb"}},
            ]
        },
    )
    memory.save_state(
        episode_id,
        {
            "status": "running",
            "plan": {"status": "confirmed"},
            "steps": {
                "step_1": {"status": "completed", "run_id": "run-1"},
                "step_2": {"status": "failed", "run_id": "run-2"},
            },
            "runs": [],
        },
    )

    selected = select_steps(
        load_confirmed_plan(memory, episode_id),
        memory.load_state(episode_id),
        step_id=None,
        resume=True,
    )

    assert [step.step_id for step in selected] == ["step_2", "step_3"]


def test_step_mode_rejects_completed_step_without_force(tmp_path: Path) -> None:
    _context, memory, episode_id = _project(tmp_path)
    memory.confirm_plan(
        episode_id,
        {"steps": [{"id": "step_1", "tool": "fpocket", "params": {"structure_path": "a.pdb"}}]},
    )
    memory.save_state(
        episode_id,
        {
            "status": "completed",
            "plan": {"status": "confirmed"},
            "steps": {"step_1": {"status": "completed", "run_id": "run-1"}},
            "runs": [],
        },
    )

    with pytest.raises(RuntimeError):
        select_steps(
            load_confirmed_plan(memory, episode_id),
            memory.load_state(episode_id),
            step_id="step_1",
            resume=False,
        )


def test_step_mode_allows_completed_step_with_force(tmp_path: Path) -> None:
    _context, memory, episode_id = _project(tmp_path)
    memory.confirm_plan(
        episode_id,
        {"steps": [{"id": "step_1", "tool": "fpocket", "params": {"structure_path": "a.pdb"}}]},
    )
    memory.save_state(
        episode_id,
        {
            "status": "completed",
            "plan": {"status": "confirmed"},
            "steps": {"step_1": {"status": "completed", "run_id": "run-1"}},
            "runs": [],
        },
    )

    selected = select_steps(
        load_confirmed_plan(memory, episode_id),
        memory.load_state(episode_id),
        step_id="step_1",
        resume=False,
        force=True,
    )

    assert [step.step_id for step in selected] == ["step_1"]


def test_update_state_preserves_latest_fields(tmp_path: Path) -> None:
    _context, memory, episode_id = _project(tmp_path)
    memory.save_state(
        episode_id,
        {
            "status": "draft",
            "plan": {"status": "missing"},
            "steps": {},
            "runs": [],
            "note": {"source": "external"},
        },
    )

    updated = memory.update_state(
        episode_id,
        lambda current: {
            **current,
            "steps": {"step_1": {"status": "running"}},
        },
    )

    assert updated["note"] == {"source": "external"}
    assert updated["steps"]["step_1"]["status"] == "running"


class _FakePreprocessExecutor(StepExecutor):
    def supports(self, tool: str) -> bool:
        return tool == "prepare_receptor"

    def run_step(self, project_root: Path, episode_id: str, step: PlanStep) -> ExecutionResult:
        return ExecutionResult(
            run_id="local-demo-run",
            status="completed",
            manifest_payload={
                "backend": "local-preprocess",
                "tool": step.tool,
                "step_id": step.step_id,
                "status": "completed",
                "result": {"status": "completed", "output": {"output_path": "data/inputs/receptor.pdbqt"}},
                "output_refs": [{"path": "data/inputs/receptor.pdbqt", "kind": "output"}],
            },
        )


class _FakeHpcExecutor(StepExecutor):
    def supports(self, tool: str) -> bool:
        return tool == "vina"

    def run_step(self, project_root: Path, episode_id: str, step: PlanStep) -> ExecutionResult:
        return ExecutionResult(
            run_id="remote-demo-run",
            status="completed",
            manifest_payload={
                "backend": "mcp-hpc-tool-contracts",
                "tool": step.tool,
                "step_id": step.step_id,
                "status": "completed",
                "fetch": {
                    "status": "completed",
                    "normalized_artifacts": [{"local_path": "/tmp/docking.sdfqt"}],
                },
                "output_refs": [{"path": "/tmp/docking.sdfqt", "kind": "artifact"}],
            },
        )


def test_mixed_plan_execution_uses_both_backends_and_resume(tmp_path: Path) -> None:
    context, memory, episode_id = _project(tmp_path)
    memory.confirm_plan(
        episode_id,
        {
            "steps": [
                {"id": "prep_1", "tool": "prepare_receptor", "inputs": {"input": "data/inputs/receptor.pdb"}},
                {"id": "dock_1", "tool": "vina", "inputs": {"receptor_pdbqt": "data/inputs/receptor.pdbqt", "ligand_pdbqt": "data/inputs/ligand.pdbqt"}},
            ]
        },
    )

    runtime = HostRuntime(
        executor=RoutedExecutionAdapter([_FakePreprocessExecutor(), _FakeHpcExecutor()])
    )
    first_runs = runtime.run_plan(context.root, RunRequest(step_id="prep_1"))
    assert [item.run_id for item in first_runs] == ["local-demo-run"]

    resumed_runs = runtime.run_plan(context.root, RunRequest(resume=True))
    assert [item.run_id for item in resumed_runs] == ["remote-demo-run"]

    state = memory.load_state(episode_id)
    assert state["steps"]["prep_1"]["status"] == "completed"
    assert state["steps"]["dock_1"]["status"] == "completed"
    assert [run["run_id"] for run in state["runs"]] == ["local-demo-run", "remote-demo-run"]


def test_switch_episode_updates_active_context(tmp_path: Path) -> None:
    context, memory, first_episode_id = _project(tmp_path)
    second_episode_id = allocate_episode_id(context.root)
    memory.create_episode(second_episode_id, "optimize selectivity")
    runtime = HostRuntime()

    snapshot = runtime.switch_episode(context.root, second_episode_id)

    assert snapshot.episode_id == second_episode_id
    assert snapshot.available_episode_ids == [first_episode_id, second_episode_id]


def test_unsupported_tool_fails_before_step_is_marked_running(tmp_path: Path) -> None:
    context, memory, episode_id = _project(tmp_path)
    memory.confirm_plan(
        episode_id,
        {"steps": [{"id": "bad_1", "tool": "mystery_tool", "params": {}}]},
    )
    runtime = HostRuntime(executor=RoutedExecutionAdapter([_FakePreprocessExecutor(), _FakeHpcExecutor()]))

    with pytest.raises(RuntimeError):
        runtime.run_plan(context.root, RunRequest())

    state = memory.load_state(episode_id)
    assert state["status"] == "draft"
    assert state["steps"] == {}


class _ExplodingPreprocessExecutor(StepExecutor):
    def supports(self, tool: str) -> bool:
        return tool == "prepare_receptor"

    def run_step(self, project_root: Path, episode_id: str, step: PlanStep) -> ExecutionResult:
        raise RuntimeError("missing input file")


def test_execution_failure_marks_step_and_episode_failed(tmp_path: Path) -> None:
    context, memory, episode_id = _project(tmp_path)
    memory.confirm_plan(
        episode_id,
        {
            "steps": [
                {"id": "prep_1", "tool": "prepare_receptor", "inputs": {"input": "data/inputs/receptor.pdb"}}
            ]
        },
    )
    runtime = HostRuntime(executor=RoutedExecutionAdapter([_ExplodingPreprocessExecutor()]))

    with pytest.raises(RuntimeError):
        runtime.run_plan(context.root, RunRequest())

    state = memory.load_state(episode_id)
    assert state["status"] == "failed"
    assert state["steps"]["prep_1"]["status"] == "failed"
    assert state["steps"]["prep_1"]["error"] == "missing input file"


def test_start_agent_workflow_initializes_agent_state(tmp_path: Path) -> None:
    context, memory, episode_id = _project(tmp_path)
    runtime = HostRuntime()

    snapshot = runtime.start_agent_workflow(context.root)
    agent_state = memory.load_agent_state(episode_id, objective=memory.load_goal(episode_id))

    assert snapshot.agent_state["design_contract"]["summary"]
    assert agent_state.selected_action is not None
    assert agent_state.selected_action.kind == "tool"
    assert agent_state.pending_interrupts == []


def test_execute_selected_action_records_observation_and_completes_workflow(tmp_path: Path) -> None:
    context, memory, episode_id = _project(tmp_path)
    runtime = HostRuntime(executor=RoutedExecutionAdapter([_FakePreprocessExecutor()]))

    runtime.start_agent_workflow(context.root)
    snapshot = runtime.execute_selected_action(context.root)
    agent_state = memory.load_agent_state(episode_id, objective=memory.load_goal(episode_id))

    assert snapshot.execution_evidence["observation_count"] == 1
    assert agent_state.observations[-1].payload["status"] == "completed"
    assert agent_state.termination_status == "completed"
    assert memory.load_state(episode_id)["runs"][-1]["run_id"] == "local-demo-run"


def test_hpc_selected_action_creates_gate_and_interrupt(tmp_path: Path) -> None:
    context, memory, episode_id = _project(tmp_path)

    class _HpcAdapter(HeuristicAgentAdapter):
        def propose_candidate_actions(self, *, state):
            from enzyme_host_runtime.planning import AgentAction
            from enzyme_host_runtime.planning import ToolAction
            from enzyme_host_runtime.planning.models import new_object_id

            return [
                AgentAction(
                    action_id=new_object_id("action"),
                    kind="tool",
                    title="Run docking",
                    rationale="Needs HPC execution",
                    tool_action=ToolAction(tool="vina", inputs={"receptor_pdbqt": "a", "ligand_pdbqt": "b"}, risk_level="high"),
                )
            ]

    runtime = HostRuntime(
        executor=RoutedExecutionAdapter([_FakeHpcExecutor()]),
        workflow=AgentWorkflowOrchestrator(adapter=_HpcAdapter()),
    )
    snapshot = runtime.start_agent_workflow(context.root)
    agent_state = memory.load_agent_state(episode_id, objective=memory.load_goal(episode_id))

    assert snapshot.pending_interrupts
    assert snapshot.pending_interrupts[-1]["kind"] == "approval_request"
    assert agent_state.approval_gates[-1].status == "pending"


def test_feedback_can_resolve_interrupt_and_resume_workflow(tmp_path: Path) -> None:
    context, memory, episode_id = _project(tmp_path)
    runtime = HostRuntime(executor=RoutedExecutionAdapter([_ExplodingPreprocessExecutor()]))

    runtime.start_agent_workflow(context.root)
    with pytest.raises(RuntimeError):
        runtime.execute_selected_action(context.root)

    agent_state = memory.load_agent_state(episode_id, objective=memory.load_goal(episode_id))
    interrupt_id = agent_state.pending_interrupts[-1].interrupt_id
    runtime.submit_feedback(
        context.root,
        interrupt_id=interrupt_id,
        content="retry with the same preparation step",
        kind="clarification",
    )
    resumed = memory.load_agent_state(episode_id, objective=memory.load_goal(episode_id))

    assert resumed.human_feedback[-1].content == "retry with the same preparation step"
    assert all(item.status != "pending" for item in resumed.pending_interrupts)
    assert resumed.selected_action is not None


def test_stale_resume_token_is_rejected_after_feedback_resolution(tmp_path: Path) -> None:
    context, memory, episode_id = _project(tmp_path)

    class _HpcAdapter(HeuristicAgentAdapter):
        def propose_candidate_actions(self, *, state):
            from enzyme_host_runtime.planning import AgentAction
            from enzyme_host_runtime.planning import ToolAction
            from enzyme_host_runtime.planning.models import new_object_id

            return [
                AgentAction(
                    action_id=new_object_id("action"),
                    kind="tool",
                    title="Run docking",
                    rationale="Needs HPC execution",
                    tool_action=ToolAction(tool="vina", inputs={"receptor_pdbqt": "a", "ligand_pdbqt": "b"}, risk_level="high"),
                )
            ]

    runtime = HostRuntime(
        executor=RoutedExecutionAdapter([_FakeHpcExecutor()]),
        workflow=AgentWorkflowOrchestrator(adapter=_HpcAdapter()),
    )
    runtime.start_agent_workflow(context.root)
    initial = memory.load_agent_state(episode_id, objective=memory.load_goal(episode_id))
    interrupt = initial.pending_interrupts[-1]

    runtime.submit_feedback(
        context.root,
        interrupt_id=interrupt.interrupt_id,
        content="approved",
        kind="approval",
        expected_state_version=interrupt.active_state_version,
        resume_token=interrupt.resume_token,
    )

    with pytest.raises(ValueError):
        runtime.submit_feedback(
            context.root,
            interrupt_id=interrupt.interrupt_id,
            content="approved again",
            kind="approval",
            expected_state_version=interrupt.active_state_version,
            resume_token=interrupt.resume_token,
        )
