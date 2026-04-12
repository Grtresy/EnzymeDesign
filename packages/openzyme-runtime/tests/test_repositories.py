from openzyme_domain import Approval
from openzyme_domain import ApprovalStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import ArtifactRecord
from openzyme_domain import CandidateRankingRecord
from openzyme_domain import CandidateRecord
from openzyme_domain import EvidenceRecord
from openzyme_domain import Episode
from openzyme_domain import EpisodeStatus
from openzyme_domain import Project
from openzyme_domain import ReportRecord
from openzyme_domain import ReportStatus
from openzyme_domain import ResearchSummaryRecord
from openzyme_domain import Run
from openzyme_domain import RunStatus
from openzyme_domain import SelectedCandidateRecord
from openzyme_domain import SourceRef
from openzyme_domain import SourceRefKind
from openzyme_domain import UnresolvedGapRecord
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


def test_research_repositories_persist_episode_scoped_evidence_outputs() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)

    project = Project.create("proj_001", "Research project")
    episode = Episode.create("ep_001", project.project_id, "Map thermostability evidence")
    evidence = EvidenceRecord(
        evidence_id="ev_001",
        episode_id=episode.episode_id,
        summary="A homolog family retains activity at 65C.",
        query="thermostable homolog catalase",
        confidence_label="high",
        created_at="2026-04-11T12:00:00+00:00",
    )
    source_ref = SourceRef(
        source_ref_id="src_001",
        evidence_id=evidence.evidence_id,
        episode_id=episode.episode_id,
        title="Catalase thermostability paper",
        locator="https://example.org/paper",
        kind=SourceRefKind.PAPER,
        created_at="2026-04-11T12:01:00+00:00",
    )
    summary = ResearchSummaryRecord(
        episode_id=episode.episode_id,
        summary="Public literature suggests at least one stable scaffold family.",
        created_at="2026-04-11T12:02:00+00:00",
        updated_at="2026-04-11T12:02:00+00:00",
    )
    gap = UnresolvedGapRecord(
        gap_id="gap_001",
        episode_id=episode.episode_id,
        summary="No structure-backed comparison yet.",
        created_at="2026-04-11T12:03:00+00:00",
    )

    repositories.projects.save(project)
    repositories.episodes.save(episode)
    repositories.evidence_records.save(evidence)
    repositories.source_refs.save(source_ref)
    repositories.research_summaries.save(summary)
    repositories.unresolved_gaps.save(gap)

    assert repositories.evidence_records.list_by_episode(episode.episode_id) == [evidence]
    assert repositories.source_refs.list_by_evidence(evidence.evidence_id) == [source_ref]
    assert repositories.research_summaries.get_by_episode(episode.episode_id) == summary
    assert repositories.unresolved_gaps.list_by_episode(episode.episode_id) == [gap]


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


def test_source_ref_links_must_match_evidence_episode() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)

    project = Project.create("proj_001", "Research ownership project")
    repositories.projects.save(project)
    repositories.episodes.save(Episode.create("ep_a", project.project_id, "A"))
    repositories.episodes.save(Episode.create("ep_b", project.project_id, "B"))
    repositories.evidence_records.save(
        EvidenceRecord(
            evidence_id="ev_a",
            episode_id="ep_a",
            summary="Evidence A",
            query="query A",
            created_at="2026-04-11T12:00:00+00:00",
        )
    )

    try:
        repositories.source_refs.save(
            SourceRef(
                source_ref_id="src_b",
                evidence_id="ev_a",
                episode_id="ep_b",
                title="Wrong episode source",
                locator="https://example.org/wrong",
                kind=SourceRefKind.WEB_PAGE,
                created_at="2026-04-11T12:01:00+00:00",
            )
        )
    except OwnershipError as exc:
        assert "belongs to episode 'ep_a'" in str(exc)
    else:
        raise AssertionError("expected OwnershipError")


def test_candidate_repositories_persist_rankings_and_selected_candidate() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)

    project = Project.create("proj_001", "Design project")
    episode = Episode.create("ep_001", project.project_id, "Design candidate selection")
    evidence = EvidenceRecord(
        evidence_id="ev_001",
        episode_id=episode.episode_id,
        summary="Evidence A",
        query="query A",
        created_at="2026-04-11T12:00:00+00:00",
    )
    candidate = CandidateRecord(
        candidate_id="cand_001",
        episode_id=episode.episode_id,
        title="Candidate A",
        summary="Highest-scoring design candidate.",
        supporting_evidence_ids=(evidence.evidence_id,),
        created_at="2026-04-11T12:01:00+00:00",
    )
    ranking = CandidateRankingRecord(
        ranking_id="rank_001",
        episode_id=episode.episode_id,
        candidate_id=candidate.candidate_id,
        rank=1,
        rationale="Most evidence-backed candidate.",
        created_at="2026-04-11T12:02:00+00:00",
    )
    selected = SelectedCandidateRecord(
        episode_id=episode.episode_id,
        candidate_id=candidate.candidate_id,
        rationale="Selected for execution handoff.",
        selected_at="2026-04-11T12:03:00+00:00",
    )

    repositories.projects.save(project)
    repositories.episodes.save(episode)
    repositories.evidence_records.save(evidence)
    repositories.candidates.save(candidate)
    repositories.candidate_rankings.save(ranking)
    repositories.selected_candidates.save(selected)

    assert repositories.candidates.list_by_episode(episode.episode_id) == [candidate]
    assert repositories.candidate_rankings.list_by_episode(episode.episode_id) == [ranking]
    assert repositories.selected_candidates.get_by_episode(episode.episode_id) == selected


def test_candidate_links_must_trace_to_same_episode_evidence() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)

    project = Project.create("proj_001", "Design ownership project")
    repositories.projects.save(project)
    repositories.episodes.save(Episode.create("ep_a", project.project_id, "A"))
    repositories.episodes.save(Episode.create("ep_b", project.project_id, "B"))
    repositories.evidence_records.save(
        EvidenceRecord(
            evidence_id="ev_a",
            episode_id="ep_a",
            summary="Evidence A",
            query="query A",
            created_at="2026-04-11T12:00:00+00:00",
        )
    )

    try:
        repositories.candidates.save(
            CandidateRecord(
                candidate_id="cand_b",
                episode_id="ep_b",
                title="Wrong episode candidate",
                summary="Should fail",
                supporting_evidence_ids=("ev_a",),
                created_at="2026-04-11T12:01:00+00:00",
            )
        )
    except OwnershipError as exc:
        assert "belongs to episode 'ep_a'" in str(exc)
    else:
        raise AssertionError("expected OwnershipError")


def test_report_repository_persists_episode_scoped_report_records() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)

    project = Project.create("proj_001", "Report project")
    episode = Episode.create("ep_001", project.project_id, "Finalize report")
    run = Run(
        run_id="run_001",
        episode_id=episode.episode_id,
        status=RunStatus.SUCCEEDED,
        execution_mode="demo",
        created_at="2026-04-11T12:00:00+00:00",
        completed_at="2026-04-11T12:01:00+00:00",
    )
    artifact = ArtifactRecord(
        artifact_id="art_report",
        episode_id=episode.episode_id,
        run_id=run.run_id,
        kind=ArtifactKind.REPORT,
        storage_uri="/tmp/report.md",
        created_at="2026-04-11T12:02:00+00:00",
    )
    report = ReportRecord(
        report_id="rep_001",
        episode_id=episode.episode_id,
        run_id=run.run_id,
        status=ReportStatus.READY,
        title="Final report",
        summary="Execution completed and the final report is ready.",
        stage_summary="Research, design, execution, and report review completed.",
        created_at="2026-04-11T12:03:00+00:00",
        updated_at="2026-04-11T12:03:00+00:00",
        artifact_id=artifact.artifact_id,
    )

    repositories.projects.save(project)
    repositories.episodes.save(episode)
    repositories.runs.save(run)
    repositories.artifact_records.save(artifact)
    repositories.reports.save(report)

    assert repositories.reports.get(report.report_id) == report
    assert repositories.reports.list_by_episode(episode.episode_id) == [report]


def test_report_links_must_match_episode_run_and_artifact() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)

    project = Project.create("proj_001", "Report ownership project")
    repositories.projects.save(project)
    repositories.episodes.save(Episode.create("ep_a", project.project_id, "A"))
    repositories.episodes.save(Episode.create("ep_b", project.project_id, "B"))
    repositories.runs.save(
        Run(
            run_id="run_a",
            episode_id="ep_a",
            status=RunStatus.SUCCEEDED,
            execution_mode="demo",
            created_at="2026-04-11T12:00:00+00:00",
        )
    )
    repositories.artifact_records.save(
        ArtifactRecord(
            artifact_id="art_a",
            episode_id="ep_a",
            run_id="run_a",
            kind=ArtifactKind.REPORT,
            storage_uri="/tmp/report.md",
            created_at="2026-04-11T12:01:00+00:00",
        )
    )

    try:
        repositories.reports.save(
            ReportRecord(
                report_id="rep_b",
                episode_id="ep_b",
                run_id="run_a",
                status=ReportStatus.READY,
                title="Wrong episode report",
                summary="Should fail",
                stage_summary="Should fail",
                created_at="2026-04-11T12:02:00+00:00",
                updated_at="2026-04-11T12:02:00+00:00",
                artifact_id="art_a",
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
