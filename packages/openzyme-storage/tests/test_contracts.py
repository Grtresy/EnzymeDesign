from openzyme_storage import ARTIFACT_STORE_OBJECTS
from openzyme_storage import CHECKPOINT_STATE_FIELDS
from openzyme_storage import GRAPH_STATE_DEPENDENCY_EXPECTATIONS
from openzyme_storage import HOST_UI_DEPENDENCY_EXPECTATIONS
from openzyme_storage import RELATIONAL_ENTITY_RELATIONSHIPS
from openzyme_storage import RELATIONAL_RECORDS
from openzyme_storage import STABLE_IDENTIFIER_LINKS
from openzyme_storage import build_default_storage_contract


def test_relational_records_match_phase_a_contract() -> None:
    assert RELATIONAL_RECORDS == (
        "projects",
        "episodes",
        "decisions",
        "approvals",
        "runs",
        "artifact_records",
        "reports",
    )
    assert RELATIONAL_ENTITY_RELATIONSHIPS["episodes"] == ("projects",)
    assert RELATIONAL_ENTITY_RELATIONSHIPS["artifact_records"] == ("episodes", "runs")


def test_checkpoint_and_artifact_ownership_are_separated() -> None:
    assert "current_phase" in CHECKPOINT_STATE_FIELDS
    assert "pending_interrupt" in CHECKPOINT_STATE_FIELDS
    assert "logs" in ARTIFACT_STORE_OBJECTS
    assert "report_files" in ARTIFACT_STORE_OBJECTS


def test_stable_identifier_links_are_explicit() -> None:
    assert STABLE_IDENTIFIER_LINKS["episode_id"] == (
        "episodes",
        "decisions",
        "approvals",
        "runs",
        "artifact_records",
        "reports",
        "graph_thread",
    )
    assert "artifact_records" in STABLE_IDENTIFIER_LINKS["run_id"]


def test_dependency_expectations_are_recorded_for_later_changes() -> None:
    assert any("graph anchor" in item for item in GRAPH_STATE_DEPENDENCY_EXPECTATIONS)
    assert any("frontend read models" in item for item in HOST_UI_DEPENDENCY_EXPECTATIONS)


def test_default_storage_contract_builds_all_layers() -> None:
    contract = build_default_storage_contract()

    assert contract.relational_records == RELATIONAL_RECORDS
    assert contract.checkpoint_state_fields == CHECKPOINT_STATE_FIELDS
    assert contract.artifact_store_objects == ARTIFACT_STORE_OBJECTS
