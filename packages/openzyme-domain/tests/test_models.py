from openzyme_domain import APPROVAL_EXTENSION_TARGETS
from openzyme_domain import CORE_ENTITY_NAMES
from openzyme_domain import DECISION_EXTENSION_TARGETS
from openzyme_domain import DESIGN_EXTENSION_TARGETS
from openzyme_domain import EPISODE_EXTENSION_TARGETS
from openzyme_domain import CandidateRankingRecord
from openzyme_domain import CandidateRecord
from openzyme_domain import EvidenceRecord
from openzyme_domain import Episode
from openzyme_domain import EpisodeStatus
from openzyme_domain import RESEARCH_EXTENSION_TARGETS
from openzyme_domain import ReportStatus
from openzyme_domain import RunStatus
from openzyme_domain import SelectedCandidateRecord
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
        objective="Design a new enzyme candidate",
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


def test_design_records_capture_candidate_traceability_and_selection() -> None:
    candidate = CandidateRecord(
        candidate_id="cand_001",
        episode_id="ep_001",
        title="Thermostable scaffold A",
        summary="Prioritize scaffold A with the highest evidence support.",
        supporting_evidence_ids=("ev_001", "ev_002"),
        created_at="2026-04-11T12:00:00+00:00",
    )
    ranking = CandidateRankingRecord(
        ranking_id="rank_001",
        episode_id="ep_001",
        candidate_id=candidate.candidate_id,
        rank=1,
        rationale="Most evidence-backed scaffold.",
        created_at="2026-04-11T12:01:00+00:00",
    )
    selected = SelectedCandidateRecord(
        episode_id="ep_001",
        candidate_id=candidate.candidate_id,
        rationale="Approved for execution handoff.",
        selected_at="2026-04-11T12:02:00+00:00",
    )

    assert candidate.to_dict()["supporting_evidence_ids"] == ["ev_001", "ev_002"]
    assert ranking.to_dict()["rank"] == 1
    assert selected.to_dict()["candidate_id"] == "cand_001"
    assert "CandidateRecord" in DESIGN_EXTENSION_TARGETS
