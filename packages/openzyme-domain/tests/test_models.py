from openzyme_domain import APPROVAL_EXTENSION_TARGETS
from openzyme_domain import CORE_ENTITY_NAMES
from openzyme_domain import DECISION_EXTENSION_TARGETS
from openzyme_domain import DESIGN_EXTENSION_TARGETS
from openzyme_domain import EPISODE_EXTENSION_TARGETS
from openzyme_domain import ArtifactKind
from openzyme_domain import ArtifactRecord
from openzyme_domain import EvidenceRecord
from openzyme_domain import Episode
from openzyme_domain import EpisodeStatus
from openzyme_domain import RESEARCH_EXTENSION_TARGETS
from openzyme_domain import ReportRecord
from openzyme_domain import ReportStatus
from openzyme_domain import RunStatus
from openzyme_domain import SourceRef
from openzyme_domain import SourceRefKind
from openzyme_domain import UnresolvedGapRecord


def test_core_entity_names_are_stable() -> None:
    assert CORE_ENTITY_NAMES == (
        "Project",
        "Episode",
        "Decision",
        "Approval",
        "Run",
        "ArtifactRecord",
        "ReportRecord",
    )


def test_episode_create_uses_stable_status_enum() -> None:
    episode = Episode.create(
        episode_id="ep_001",
        project_id="proj_001",
        objective="Design a new enzyme workflow",
    )

    assert episode.status is EpisodeStatus.DRAFT
    assert episode.to_dict()["status"] == "draft"
    assert episode.project_id == "proj_001"


def test_terminal_status_sets_are_explicit() -> None:
    assert EpisodeStatus.ACTIVE.is_terminal is False
    assert EpisodeStatus.COMPLETED.is_terminal is True
    assert RunStatus.RUNNING.is_terminal is False
    assert RunStatus.SUCCEEDED.is_terminal is True
    assert ReportStatus.READY.is_terminal is False
    assert ReportStatus.PUBLISHED.is_terminal is True


def test_phase_c_extension_boundaries_reuse_phase_a_ids() -> None:
    assert EPISODE_EXTENSION_TARGETS == frozenset({"Episode"})
    assert DECISION_EXTENSION_TARGETS == frozenset({"Episode", "Decision"})
    assert APPROVAL_EXTENSION_TARGETS == frozenset({"Episode", "Approval"})


def test_research_records_use_normalized_serializable_fields() -> None:
    evidence = EvidenceRecord(
        evidence_id="ev_001",
        episode_id="ep_001",
        summary="Two thermostable homologs retain catalytic activity above 60C.",
        query="thermostable homolog catalase",
        confidence_label="high",
        created_at="2026-04-11T12:00:00+00:00",
    )
    source_ref = SourceRef(
        source_ref_id="src_001",
        evidence_id=evidence.evidence_id,
        episode_id=evidence.episode_id,
        title="Thermostable catalase study",
        locator="https://example.org/paper",
        kind=SourceRefKind.PAPER,
        created_at="2026-04-11T12:01:00+00:00",
    )
    gap = UnresolvedGapRecord(
        gap_id="gap_001",
        episode_id=evidence.episode_id,
        summary="No structure-backed comparison for the top homologs yet.",
        created_at="2026-04-11T12:02:00+00:00",
    )

    assert evidence.to_dict()["query"] == "thermostable homolog catalase"
    assert source_ref.to_dict()["kind"] == "paper"
    assert gap.to_dict()["summary"].startswith("No structure-backed")
    assert "EvidenceRecord" in RESEARCH_EXTENSION_TARGETS


def test_design_extensions_use_artifact_manifests_as_work_objects() -> None:
    artifact = ArtifactRecord(
        artifact_id="art_design_001",
        episode_id="ep_001",
        kind=ArtifactKind.OTHER,
        storage_uri="artifact://design-option/art_design_001",
        created_at="2026-04-11T12:00:00+00:00",
        title="Thermostable scaffold A",
        description="Prioritize scaffold A with the highest evidence support.",
        tags=("design-option",),
        metadata={"semantic_type": "design_option", "supporting_evidence_ids": ["ev_001", "ev_002"]},
    )

    assert artifact.to_dict()["metadata"]["semantic_type"] == "design_option"
    assert artifact.to_dict()["tags"] == ["design-option"]
    assert DESIGN_EXTENSION_TARGETS == frozenset({"Episode", "ArtifactRecord", "Decision"})


def test_report_records_expose_report_review_summary_fields() -> None:
    report = ReportRecord(
        report_id="rep_001",
        episode_id="ep_001",
        run_id="run_001",
        status=ReportStatus.READY,
        title="Final report",
        summary="Execution completed successfully.",
        stage_summary="Research, design, execution, and report review are complete.",
        created_at="2026-04-11T12:00:00+00:00",
        updated_at="2026-04-11T12:01:00+00:00",
        artifact_id="art_001",
    )

    payload = report.to_dict()
    assert payload["status"] == "ready"
    assert payload["summary"].startswith("Execution completed")
    assert payload["artifact_id"] == "art_001"
