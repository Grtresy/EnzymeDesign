from openzyme_domain import Approval
from openzyme_domain import ApprovalStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import ArtifactRecord
from openzyme_domain import Episode
from openzyme_domain import EpisodeStatus
from openzyme_domain import Project
from openzyme_domain import Run
from openzyme_domain import RunStatus
from openzyme_runtime import OwnershipError
from openzyme_runtime import PhaseBRepositories
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import connect_sqlite


def test_phase_b_repositories_persist_canonical_records() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)

    project = Project.create("proj_001", "Catalase redesign")
    episode = Episode.create(
        episode_id="ep_001",
        project_id=project.project_id,
        objective="Improve thermal stability",
        status=EpisodeStatus.ACTIVE,
    )
    approval = Approval(
        approval_id="apr_001",
        episode_id=episode.episode_id,
        status=ApprovalStatus.PENDING,
        requested_action="Approve HPC run",
        created_at="2026-04-11T12:00:00+00:00",
    )
    run = Run(
        run_id="run_001",
        episode_id=episode.episode_id,
        approval_id=approval.approval_id,
        status=RunStatus.QUEUED,
        execution_mode="hpc",
        created_at="2026-04-11T12:01:00+00:00",
    )
    artifact = ArtifactRecord(
        artifact_id="art_001",
        episode_id=episode.episode_id,
        run_id=run.run_id,
        kind=ArtifactKind.RESULT,
        storage_uri="s3://bucket/results/run_001.json",
        created_at="2026-04-11T12:05:00+00:00",
    )

    repositories.projects.save(project)
    repositories.episodes.save(episode)
    repositories.approvals.save(approval)
    repositories.runs.save(run)
    repositories.artifact_records.save(artifact)

    assert repositories.projects.get(project.project_id) == project
    assert repositories.episodes.get(episode.episode_id) == episode
    assert repositories.approvals.list_pending_by_episode(episode.episode_id) == [approval]
    assert repositories.runs.list_by_episode(episode.episode_id) == [run]
    assert repositories.artifact_records.list_by_episode(episode.episode_id) == [artifact]


def test_repository_ownership_checks_reject_cross_episode_links() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)

    project = Project.create("proj_001", "Baseline project")
    repositories.projects.save(project)
    repositories.episodes.save(Episode.create("ep_a", project.project_id, "A"))
    repositories.episodes.save(Episode.create("ep_b", project.project_id, "B"))
    repositories.approvals.save(
        Approval(
            approval_id="apr_a",
            episode_id="ep_a",
            status=ApprovalStatus.PENDING,
            requested_action="Approve A",
            created_at="2026-04-11T12:00:00+00:00",
        )
    )

    try:
        repositories.runs.save(
            Run(
                run_id="run_b",
                episode_id="ep_b",
                approval_id="apr_a",
                status=RunStatus.QUEUED,
                execution_mode="hpc",
                created_at="2026-04-11T12:01:00+00:00",
            )
        )
    except OwnershipError as exc:
        assert "belongs to episode 'ep_a'" in str(exc)
    else:
        raise AssertionError("expected OwnershipError")


def test_artifact_links_must_match_run_episode() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)

    project = Project.create("proj_001", "Artifact link project")
    repositories.projects.save(project)
    repositories.episodes.save(Episode.create("ep_a", project.project_id, "A"))
    repositories.episodes.save(Episode.create("ep_b", project.project_id, "B"))
    repositories.runs.save(
        Run(
            run_id="run_a",
            episode_id="ep_a",
            status=RunStatus.RUNNING,
            execution_mode="hpc",
            created_at="2026-04-11T12:01:00+00:00",
        )
    )

    try:
        repositories.artifact_records.save(
            ArtifactRecord(
                artifact_id="art_b",
                episode_id="ep_b",
                run_id="run_a",
                kind=ArtifactKind.LOG,
                storage_uri="s3://bucket/logs/run_a.log",
                created_at="2026-04-11T12:05:00+00:00",
            )
        )
    except OwnershipError as exc:
        assert "belongs to episode 'ep_a'" in str(exc)
    else:
        raise AssertionError("expected OwnershipError")
