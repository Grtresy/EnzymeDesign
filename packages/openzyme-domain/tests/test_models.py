from openzyme_domain import APPROVAL_EXTENSION_TARGETS
from openzyme_domain import CORE_ENTITY_NAMES
from openzyme_domain import DECISION_EXTENSION_TARGETS
from openzyme_domain import EPISODE_EXTENSION_TARGETS
from openzyme_domain import Episode
from openzyme_domain import EpisodeStatus
from openzyme_domain import ReportStatus
from openzyme_domain import RunStatus


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
