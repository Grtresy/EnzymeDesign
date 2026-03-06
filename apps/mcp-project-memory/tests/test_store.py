from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_project_memory.config import ProjectMemoryConfig
from mcp_project_memory.store import ProjectMemoryStore


@pytest.fixture
def store(tmp_path: Path) -> ProjectMemoryStore:
    project_root = tmp_path / "workspace" / "demo"
    config = ProjectMemoryConfig(projects={"demo": project_root})
    return ProjectMemoryStore(config)


def test_update_state_and_read_resource(store: ProjectMemoryStore) -> None:
    project_root = store.ensure_project_root("demo")
    (project_root / "enzyme.yaml").write_text("name: demo\n", encoding="utf-8")
    (project_root / "episodes" / "ep1" / "goal.md").parent.mkdir(parents=True, exist_ok=True)
    (project_root / "episodes" / "ep1" / "goal.md").write_text("# Goal\n", encoding="utf-8")

    payload = store.update_episode_state("demo", "ep1", {"stage": "design"})
    assert payload["stage"] == "design"

    text = store.read_resource_text("enzyme://project/demo/episode/ep1/state")
    assert json.loads(text)["stage"] == "design"


def test_import_and_archive_indexed_resources(store: ProjectMemoryStore) -> None:
    project_root = store.ensure_project_root("demo")
    episode_dir = store.ensure_episode_dir("demo", "ep1")
    (project_root / "enzyme.yaml").write_text("name: demo\n", encoding="utf-8")
    (episode_dir / "goal.md").write_text("# Goal\n", encoding="utf-8")
    store.update_episode_state("demo", "ep1", {"status": "running"})
    store.confirm_plan("demo", "ep1", {"steps": ["a", "b"]})
    store.save_structure_annotations("demo", "ep1", {"notes": ["keep chain A"]})
    store.write_run_manifest("demo", "ep1", "run-1", {"tool": "vina", "status": "done"})
    store.write_candidate_summary("demo", "ep1", "cand-1", {"status": "selected"})
    result = store.import_experiment_results(
        "demo",
        "ep1",
        {"score": 0.8},
        experiment_id="exp-1",
        candidate_ids=["cand-1"],
        run_ids=["run-1"],
    )
    assert result["experiment_id"] == "exp-1"

    manifest = store.archive_episode("demo", "ep1")
    assert manifest["archived"] is True
    assert manifest["run_refs"][0]["run_id"] == "run-1"
    assert manifest["experiment_refs"][0]["experiment_id"] == "exp-1"

    run_text = store.read_resource_text("enzyme://run/run-1/manifest")
    candidate_text = store.read_resource_text("enzyme://candidate/cand-1/summary")
    experiment_text = store.read_resource_text("enzyme://experiment/exp-1/result")
    assert json.loads(run_text)["tool"] == "vina"
    assert json.loads(candidate_text)["status"] == "selected"
    assert json.loads(experiment_text)["score"] == 0.8


def test_record_decision_writes_valid_jsonl_and_archive_reads_it(store: ProjectMemoryStore) -> None:
    episode_dir = store.ensure_episode_dir("demo", "ep1")
    decision = store.record_decision("demo", "ep1", "approve", "looks good", "alice")

    log_entries = store.read_decision_log("demo", "ep1")
    assert [entry["decision_id"] for entry in log_entries] == [decision["decision_id"]]

    manifest = store.archive_episode("demo", "ep1")
    assert manifest["decision_log"]["count"] == 1
    assert (episode_dir / "manifest.json").exists()


def test_import_experiment_results_generates_valid_id(store: ProjectMemoryStore) -> None:
    result = store.import_experiment_results("demo", "ep1", {"score": 0.5})

    assert result["experiment_id"].startswith("experiment-")
    text = store.read_resource_text(f"enzyme://experiment/{result['experiment_id']}/result")
    assert json.loads(text)["score"] == 0.5


def test_read_missing_resource_does_not_create_episode(store: ProjectMemoryStore) -> None:
    project_root = store.resolve_project_root("demo")

    with pytest.raises(FileNotFoundError):
        store.read_resource_text("enzyme://project/demo/episode/ghost/state")

    assert not project_root.exists()


def test_invalid_ids_and_unsupported_uri_are_rejected(store: ProjectMemoryStore) -> None:
    with pytest.raises(ValueError):
        store.ensure_episode_dir("demo", "../oops")

    with pytest.raises(ValueError):
        store.read_resource_text("enzyme://project/demo/episode/../state")
