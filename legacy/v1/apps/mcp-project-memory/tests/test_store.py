from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_project_memory.config import ProjectMemoryConfig
from mcp_project_memory.store import StaleStateError
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


def test_save_agent_state_exposes_canonical_agent_resources(store: ProjectMemoryStore) -> None:
    payload = store.save_agent_state(
        "demo",
        "ep1",
        {
            "state_version": 2,
            "status": "awaiting_feedback",
            "decision_trace": [{"entry_id": "trace-1", "kind": "selected_action"}],
            "human_feedback": [{"feedback_id": "feedback-1", "content": "retry"}],
            "approval_gates": [{"gate_id": "gate-1", "action_id": "action-1", "action_revision": 1}],
            "pending_interrupts": [{"interrupt_id": "interrupt-1", "kind": "approval_request"}],
            "session": {
                "session_id": "session-1",
                "active_state_version": 2,
                "resume_token": "resume-1",
                "updated_at": "2026-03-08T00:00:00+00:00",
            },
        },
    )

    assert payload["state_version"] == 2
    assert json.loads(store.read_resource_text("enzyme://project/demo/episode/ep1/agent-state"))["status"] == "awaiting_feedback"
    assert json.loads(store.read_resource_text("enzyme://project/demo/episode/ep1/decision-log"))[0]["entry_id"] == "trace-1"
    assert json.loads(store.read_resource_text("enzyme://project/demo/episode/ep1/feedback-log"))[0]["feedback_id"] == "feedback-1"
    assert json.loads(store.read_resource_text("enzyme://project/demo/episode/ep1/approval-gates"))[0]["gate_id"] == "gate-1"
    assert json.loads(store.read_resource_text("enzyme://project/demo/episode/ep1/interrupts"))[0]["interrupt_id"] == "interrupt-1"
    assert json.loads(store.read_resource_text("enzyme://project/demo/episode/ep1/session"))["resume_token"] == "resume-1"


def test_append_workflow_event_exposes_workflow_audit_resource(store: ProjectMemoryStore) -> None:
    event = store.append_workflow_event(
        "demo",
        "ep1",
        {
            "event_id": "workflow-event-1",
            "event_type": "capability_inspected",
            "state_version": 2,
            "refs": {"capability_id": "mcp-preprocess"},
        },
    )

    assert event["event_id"] == "workflow-event-1"
    payload = json.loads(store.read_resource_text("enzyme://project/demo/episode/ep1/workflow-audit"))
    assert payload[0]["event_type"] == "capability_inspected"
    assert payload[0]["refs"]["capability_id"] == "mcp-preprocess"


def test_submit_resume_rejects_stale_token(store: ProjectMemoryStore) -> None:
    store.save_agent_state(
        "demo",
        "ep1",
        {
            "state_version": 3,
            "session": {
                "session_id": "session-1",
                "active_state_version": 3,
                "resume_token": "resume-1",
                "updated_at": "2026-03-08T00:00:00+00:00",
            },
        },
    )

    accepted = store.submit_resume("demo", "ep1", state_version=3, resume_token="resume-1")
    assert accepted["status"] == "accepted"

    repeated = store.submit_resume("demo", "ep1", state_version=3, resume_token="resume-1")
    assert repeated["status"] == "already_consumed"

    with pytest.raises(StaleStateError):
        store.submit_resume("demo", "ep1", state_version=3, resume_token="resume-stale")


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
        store.ensure_episode_dir("demo", "..")

    with pytest.raises(ValueError):
        store.ensure_project_root("..")

    with pytest.raises(ValueError):
        store.import_experiment_results("demo", "ep1", {"score": 0.4}, experiment_id="..")

    with pytest.raises(ValueError):
        store.read_resource_text("enzyme://project/demo/episode/../state")


def test_indexed_ids_must_be_globally_unique_across_projects(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    config = ProjectMemoryConfig(
        projects={
            "demo": workspace / "demo",
            "other": workspace / "other",
        }
    )
    store = ProjectMemoryStore(config)

    store.write_run_manifest("demo", "ep1", "run-1", {"tool": "vina"})
    with pytest.raises(ValueError):
        store.write_run_manifest("other", "ep2", "run-1", {"tool": "gnina"})

    store.write_candidate_summary("demo", "ep1", "cand-1", {"status": "selected"})
    with pytest.raises(ValueError):
        store.write_candidate_summary("other", "ep2", "cand-1", {"status": "rejected"})

    store.import_experiment_results("demo", "ep1", {"score": 0.8}, experiment_id="exp-1")
    with pytest.raises(ValueError):
        store.import_experiment_results("other", "ep2", {"score": 0.3}, experiment_id="exp-1")


def test_duplicate_index_entries_fail_closed_on_read(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    config = ProjectMemoryConfig(
        projects={
            "demo": workspace / "demo",
            "other": workspace / "other",
        }
    )
    store = ProjectMemoryStore(config)

    demo_run = store.write_run_manifest("demo", "ep1", "run-1", {"tool": "vina"})
    other_root = store.ensure_project_root("other")
    other_run_path = other_root / "episodes" / "ep2" / "runs" / "run-1" / "manifest.json"
    other_run_path.parent.mkdir(parents=True, exist_ok=True)
    other_run_path.write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "project_id": "other",
                "episode_id": "ep2",
                "tool": "gnina",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (other_root / ".enzyme" / "indexes").mkdir(parents=True, exist_ok=True)
    (other_root / ".enzyme" / "indexes" / "runs.json").write_text(
        json.dumps(
            {
                "run-1": {
                    "run_id": "run-1",
                    "project_id": "other",
                    "episode_id": "ep2",
                    "path": "episodes/ep2/runs/run-1/manifest.json",
                    "tool": "gnina",
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert demo_run["tool"] == "vina"
    with pytest.raises(ValueError):
        store.read_resource_text("enzyme://run/run-1/manifest")
