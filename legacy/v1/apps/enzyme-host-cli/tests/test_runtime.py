from __future__ import annotations

from pathlib import Path

import pytest

from enzyme_host_cli.execution import build_step_params
from enzyme_host_cli.memory_client import MemoryClient
from enzyme_host_cli.plan_runtime import PlanStep
from enzyme_host_cli.plan_runtime import load_confirmed_plan
from enzyme_host_cli.plan_runtime import select_steps
from enzyme_host_cli.workspace import allocate_episode_id
from enzyme_host_cli.workspace import init_project
from enzyme_host_cli.workspace import set_current_episode


def _project(tmp_path: Path):
    context = init_project(tmp_path, "demo-project")
    memory = MemoryClient(context)
    episode_id = allocate_episode_id(context.root)
    memory.create_episode(episode_id, "improve binding")
    set_current_episode(context.root, episode_id)
    return context, memory, episode_id


def test_confirm_plan_updates_canonical_state(tmp_path: Path) -> None:
    _context, memory, episode_id = _project(tmp_path)

    confirmed = memory.confirm_plan(
        episode_id,
        {
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


def test_build_step_params_maps_aliases_and_resolves_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    step = PlanStep(
        step_id="dock_1",
        tool="vina",
        payload={
            "id": "dock_1",
            "tool": "vina",
            "inputs": {
                "receptor_pdbqt": "data/inputs/receptor.pdbqt",
                "ligand_pdbqt": "data/inputs/ligand.pdbqt",
            },
            "params": {
                "center_x": 1,
                "center_y": 2,
                "center_z": 3,
                "size_x": 20,
                "size_y": 20,
                "size_z": 20,
            },
        },
    )

    params = build_step_params(project_root, step)

    assert params["receptor_path"] == str((project_root / "data/inputs/receptor.pdbqt").resolve())
    assert params["ligand_path"] == str((project_root / "data/inputs/ligand.pdbqt").resolve())
    assert params["center_x"] == 1
