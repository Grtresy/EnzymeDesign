import json
from pathlib import Path

from openzyme_host_api import COMMAND_SURFACE
from openzyme_host_api import HOST_UI_CLOSED_LOOP_FIELDS
from openzyme_host_api import QUERY_RESOURCES
from openzyme_host_api import STREAM_EVENT_TYPES
from openzyme_host_api import build_host_api_contract
from openzyme_host_api.contracts import validate_contract_alignment


def test_query_resources_cover_minimum_host_surface() -> None:
    assert QUERY_RESOURCES == (
        "projects",
        "episodes",
        "runs",
        "artifacts",
        "reports",
        "pending_actions",
    )


def test_command_surface_covers_minimum_closed_loop() -> None:
    assert COMMAND_SURFACE == (
        "create_episode",
        "resume_episode",
        "resolve_approval",
    )


def test_workflow_stream_events_are_workflow_aware() -> None:
    assert STREAM_EVENT_TYPES == (
        "workflow.phase_changed",
        "workflow.progress_updated",
        "workflow.summary_updated",
        "workflow.interrupt_pending",
        "workflow.approval_pending",
        "workflow.run_status_changed",
        "workflow.artifact_available",
        "workflow.evidence_updated",
        "workflow.candidate_updated",
        "workflow.selected_candidate_changed",
        "workflow.report_available",
    )


def test_host_api_contract_builds_projection_shapes() -> None:
    contract = build_host_api_contract()

    assert contract.workflow_projection.required_fields == (
        "episode_id",
        "current_phase",
        "progress",
        "summary",
        "pending_interrupt",
        "pending_approval",
    )
    assert "storage_uri" in contract.artifact_projection.required_fields
    assert "artifact_id" in contract.report_projection.required_fields
    assert contract.stream_events[0].source_stream_mode == "updates"
    assert "Projected" in contract.stream_events[0].notes


def test_minimum_web_loop_fields_are_recorded() -> None:
    assert HOST_UI_CLOSED_LOOP_FIELDS == (
        "episode_id",
        "current_phase",
        "progress",
        "pending_interrupt",
        "pending_approval",
        "runs",
        "artifacts",
        "report",
    )


def test_host_api_contract_reuses_prior_phase_a_contracts() -> None:
    validate_contract_alignment()


def test_web_ui_read_model_file_matches_minimum_closed_loop() -> None:
    read_model_path = (
        Path(__file__).resolve().parents[2]
        / "openzyme-web-ui"
        / "contracts"
        / "read_models.json"
    )

    payload = json.loads(read_model_path.read_text())
    assert tuple(payload["phase_b_closed_loop"]["required_fields"]) == HOST_UI_CLOSED_LOOP_FIELDS
    assert "current_phase" in payload["workflow_projection"]["required_fields"]
    assert "summary" in payload["workflow_projection"]["required_fields"]
    assert "research" in payload["phase_c_workspace"]["required_fields"]
    assert "design" in payload["phase_c_workspace"]["required_fields"]
