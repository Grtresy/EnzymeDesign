from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from openzyme_core import ArtifactBoundaryService
from openzyme_core import ArtifactBoundaryError
from openzyme_core import CoreRepositories
from openzyme_core import SandboxWorkspaceService
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import sandbox_image_record
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import SandboxWorkspaceRecord
from openzyme_domain import Session
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SessionStatus
from openzyme_runtime import FASTA_ZERO_RECORDS_VALIDATION_PROFILE
from openzyme_runtime.artifact_boundary import RegisterResult


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _digest(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _seed_session(repositories: CoreRepositories, *, session_id: str = "sess_s08") -> Session:
    session = Session(
        session_id=session_id,
        project_id="proj_001",
        title="S08",
        objective="Sandbox artifact boundary",
        status=SessionStatus.ACTIVE,
        created_at="2026-05-28T00:00:00+00:00",
        updated_at="2026-05-28T00:00:00+00:00",
    )
    repositories.sessions.save(session)
    return session


def _seed_executor(
    repositories: CoreRepositories,
    session: Session,
    *,
    agent_id: str = "agent:executor:boundary",
    member_id: str = "member_executor",
) -> AgentMember:
    agent = AgentMember(
        agent_id=agent_id,
        session_id=session.session_id,
        lane_id=None,
        task_id=None,
        name="executor",
        role="executor",
        status=AgentMemberStatus.IDLE,
        parent_agent_id=None,
        created_at="2026-05-28T00:01:00+00:00",
        updated_at="2026-05-28T00:01:00+00:00",
        member_id=member_id,
    )
    repositories.agents.save(agent)
    saved = repositories.agents.get(session.session_id, agent_id)
    assert saved is not None
    return saved


def _seed_workspace(
    repositories: CoreRepositories,
    tmp_path: Path,
    *,
    session_id: str = "sess_s08",
) -> tuple[Session, SandboxWorkspaceRecord, Path]:
    session = _seed_session(repositories, session_id=session_id)
    agent = _seed_executor(repositories, session)
    assert agent.member_id is not None
    repositories.sandbox_images.save(
        sandbox_image_record(
            image_ref="localhost/openzyme-pipeline-sandbox@sha256:s08",
            image_digest="sha256:s08",
        )
    )
    workspace_root = tmp_path / "workspaces"
    workspace = SandboxWorkspaceService(
        repositories,
        workspace_root=workspace_root,
    ).create_or_get(session_id=session.session_id, agent_member_id=agent.member_id)
    return session, workspace, workspace_root


def _save_input_artifact(
    repositories: CoreRepositories,
    tmp_path: Path,
    *,
    session_id: str,
    artifact_id: str = "art_input",
    relative_path: str = "inputs/protein.fasta",
    content: str = ">seq\nMSEQ\n",
) -> SessionArtifactRecord:
    storage_path = tmp_path / "seed-artifacts" / artifact_id / Path(relative_path).name
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_text(content, encoding="utf-8")
    artifact = SessionArtifactRecord(
        artifact_id=artifact_id,
        session_id=session_id,
        task_id=None,
        lane_id=None,
        invocation_id=None,
        run_id=None,
        kind=ArtifactKind.SEQUENCE,
        storage_uri=str(storage_path),
        relative_path=relative_path,
        title=Path(relative_path).name,
        description=None,
        metadata={"format": "fasta", "content_digest": _digest(content)},
        created_at="2026-05-28T00:02:00+00:00",
    )
    repositories.artifacts.save(artifact)
    return artifact


def _service(
    repositories: CoreRepositories,
    *,
    workspace_root: Path,
    blob_store_root: Path,
) -> ArtifactBoundaryService:
    return ArtifactBoundaryService(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=blob_store_root,
    )


def _registration_result_for_control_payload(
    *,
    content_digest: str | None,
    tree_digest: str | None,
    metadata: dict[str, object],
) -> RegisterResult:
    artifact = SessionArtifactRecord(
        artifact_id="art_control_payload",
        session_id="sess_control_payload",
        task_id=None,
        lane_id=None,
        invocation_id=None,
        run_id=None,
        kind=ArtifactKind.RESULT,
        storage_uri="/tmp/sealed-control-payload",
        relative_path="output/result",
        title="result",
        description=None,
        metadata=metadata,
        created_at="2026-05-28T00:02:00+00:00",
    )
    return RegisterResult(
        artifact=artifact,
        content_digest=content_digest,
        tree_digest=tree_digest,
        validation={},
        reused=False,
    )


def test_registration_control_payload_accepts_exact_file_and_tree_identities() -> None:
    file_digest = _digest("file")
    file_payload = _registration_result_for_control_payload(
        content_digest=file_digest,
        tree_digest=None,
        metadata={
            "content_digest": file_digest,
            "sealed_digest": file_digest,
        },
    ).to_control_payload()
    assert file_payload["content_digest"] == file_digest
    assert file_payload["tree_digest"] is None

    tree_digest = _digest("tree")
    tree_payload = _registration_result_for_control_payload(
        content_digest=None,
        tree_digest=tree_digest,
        metadata={
            "tree_digest": tree_digest,
            "sealed_digest": tree_digest,
        },
    ).to_control_payload()
    assert tree_payload["content_digest"] is None
    assert tree_payload["tree_digest"] == tree_digest


@pytest.mark.parametrize(
    ("content_digest", "tree_digest", "metadata"),
    [
        (
            _digest("file"),
            _digest("tree"),
            {
                "content_digest": _digest("file"),
                "tree_digest": _digest("tree"),
                "sealed_digest": _digest("file"),
            },
        ),
        (None, None, {"sealed_digest": _digest("file")}),
        (
            _digest("file"),
            None,
            {
                "content_digest": _digest("file"),
                "sealed_digest": _digest("other"),
            },
        ),
        (
            _digest("file"),
            None,
            {
                "content_digest": _digest("file"),
                "tree_digest": _digest("tree"),
                "sealed_digest": _digest("file"),
            },
        ),
        (
            _digest("file"),
            "not-a-tree-digest",
            {
                "content_digest": _digest("file"),
                "sealed_digest": _digest("file"),
            },
        ),
        (
            "not-a-content-digest",
            _digest("tree"),
            {
                "tree_digest": _digest("tree"),
                "sealed_digest": _digest("tree"),
            },
        ),
        (
            "not-a-content-digest",
            None,
            {
                "content_digest": "not-a-content-digest",
                "sealed_digest": "not-a-content-digest",
            },
        ),
    ],
)
def test_registration_control_payload_rejects_inconsistent_digest_identity(
    content_digest: str | None,
    tree_digest: str | None,
    metadata: dict[str, object],
) -> None:
    result = _registration_result_for_control_payload(
        content_digest=content_digest,
        tree_digest=tree_digest,
        metadata=metadata,
    )

    with pytest.raises(
        ArtifactBoundaryError,
        match="artifact registration response",
    ) as error:
        result.to_control_payload()

    assert error.value.error_code == "artifact_registration_response_invalid"


def test_materialize_copies_authorized_artifact_into_workspace_input(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    _save_input_artifact(repositories, tmp_path, session_id=session.session_id)
    service = _service(repositories, workspace_root=workspace_root, blob_store_root=tmp_path / "blobs")

    first = service.materialize(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        artifact_id="art_input",
    )
    second = service.materialize(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        artifact_id="art_input",
    )

    assert first.path == "/workspace/input/art_input/inputs/protein.fasta"
    materialized_path = workspace_root / workspace.sandbox_workspace_id / "input" / "art_input" / "inputs" / "protein.fasta"
    assert materialized_path.read_text(encoding="utf-8") == ">seq\nMSEQ\n"
    assert second.reused is True
    saved_record = repositories.artifact_materializations.get(first.materialization_id)
    assert saved_record is not None
    assert saved_record["artifact_digest"] == _digest(">seq\nMSEQ\n")
    refreshed = repositories.sandbox_workspaces.get(workspace.sandbox_workspace_id)
    assert refreshed is not None
    assert refreshed.materialized_input_artifact_ids == ("art_input",)
    assert "storage_uri" not in json.dumps(first.to_payload())

    readonly = service.materialize(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        artifact_id="art_input",
        target="/workspace/input/readonly/protein.fasta",
        mode="copy",
    )
    readonly_reuse = service.materialize(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        artifact_id="art_input",
        target="/workspace/input/readonly/protein.fasta",
        mode="readonly",
    )
    readonly_path = workspace_root / workspace.sandbox_workspace_id / "input" / "readonly" / "protein.fasta"
    assert readonly.path == readonly_reuse.path
    assert readonly_reuse.reused is True
    assert readonly_path.stat().st_mode & 0o222 == 0

    materialized_path.write_text("changed\n", encoding="utf-8")
    with pytest.raises(ArtifactBoundaryError) as conflict:
        service.materialize(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            artifact_id="art_input",
        )
    assert conflict.value.error_code == "artifact_materialization_conflict"


def test_read_sealed_file_is_session_bound_bounded_and_digest_verified(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, _, workspace_root = _seed_workspace(repositories, tmp_path)
    artifact = _save_input_artifact(
        repositories,
        tmp_path,
        session_id=session.session_id,
    )
    service = _service(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )

    content, digest = service.read_sealed_file(
        session_id=session.session_id,
        artifact_id=artifact.artifact_id,
    )
    assert content == b">seq\nMSEQ\n"
    assert digest == _digest(">seq\nMSEQ\n")

    with pytest.raises(ArtifactBoundaryError) as scope_error:
        service.read_sealed_file(
            session_id="sess_other",
            artifact_id=artifact.artifact_id,
        )
    assert scope_error.value.error_code == "artifact_scope_forbidden"
    with pytest.raises(ArtifactBoundaryError) as bound_error:
        service.read_sealed_file(
            session_id=session.session_id,
            artifact_id=artifact.artifact_id,
            max_bytes=1,
        )
    assert bound_error.value.error_code == "artifact_export_too_large"

    Path(artifact.storage_uri).write_text(">seq\nTAMPERED\n", encoding="utf-8")
    with pytest.raises(ArtifactBoundaryError) as digest_error:
        service.read_sealed_file(
            session_id=session.session_id,
            artifact_id=artifact.artifact_id,
        )
    assert digest_error.value.error_code == "artifact_blob_digest_mismatch"


def test_materialize_rejects_cross_session_artifact_and_escape_target(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    other = _seed_session(repositories, session_id="sess_other")
    _save_input_artifact(repositories, tmp_path, session_id=other.session_id, artifact_id="art_other")
    _save_input_artifact(repositories, tmp_path, session_id=session.session_id, artifact_id="art_input")
    service = _service(repositories, workspace_root=workspace_root, blob_store_root=tmp_path / "blobs")

    with pytest.raises(ArtifactBoundaryError, match="artifact is not available"):
        service.materialize(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            artifact_id="art_other",
        )
    with pytest.raises(ArtifactBoundaryError) as exc_info:
        service.materialize(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            artifact_id="art_input",
            target="/workspace/input/../escape.txt",
        )
    assert exc_info.value.error_code == "artifact_materialize_target_forbidden"


def test_materialize_rejects_artifact_storage_that_no_longer_matches_declared_digest(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    artifact = _save_input_artifact(
        repositories,
        tmp_path,
        session_id=session.session_id,
    )
    service = _service(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )

    Path(artifact.storage_uri).write_text(">seq\nTAMPERED\n", encoding="utf-8")

    with pytest.raises(ArtifactBoundaryError) as exc_info:
        service.materialize(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            artifact_id=artifact.artifact_id,
        )

    assert exc_info.value.error_code == "artifact_blob_digest_mismatch"
    assert exc_info.value.details["expected_digest"] == _digest(">seq\nMSEQ\n")
    assert not (
        workspace_root
        / workspace.sandbox_workspace_id
        / "input"
        / artifact.artifact_id
    ).exists()
    refreshed = repositories.sandbox_workspaces.get(workspace.sandbox_workspace_id)
    assert refreshed is not None
    assert refreshed.materialized_input_artifact_ids == ()
    assert repositories.artifact_blob_gc.list_pending()[0]["reason"] == "artifact_blob_digest_mismatch"


def test_register_requires_source_snapshot(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    output = workspace_root / workspace.sandbox_workspace_id / "output" / "result.csv"
    output.write_text("id,score\nA,1\n", encoding="utf-8")
    service = _service(repositories, workspace_root=workspace_root, blob_store_root=tmp_path / "blobs")

    with pytest.raises(ArtifactBoundaryError) as exc_info:
        service.register(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            path="/workspace/output/result.csv",
            kind="result",
            format="csv",
            metadata={"required_columns": ["id", "score"]},
        )

    assert exc_info.value.error_code == "source_snapshot_required"
    assert repositories.artifacts.list_by_session(session.session_id) == []


@pytest.mark.parametrize("invalid_kind", ("model", "", None, False))
def test_register_rejects_invalid_artifact_kind_with_typed_error(
    tmp_path: Path,
    invalid_kind: object,
) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )

    with pytest.raises(ArtifactBoundaryError) as exc_info:
        service.register(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            path="/workspace/output/AOX_ref.hmm",
            kind=invalid_kind,  # type: ignore[arg-type]
            format="hmm",
        )

    assert exc_info.value.error_code == "artifact_kind_invalid"
    assert exc_info.value.details == {
        "allowed_values": [
            "code",
            "log",
            "sequence",
            "structure",
            "report",
            "research_dossier",
            "result",
            "cache",
            "other",
        ]
    }
    assert exc_info.value.hint == (
        "Use exactly one of: code, log, sequence, structure, report, "
        "research_dossier, result, cache, other."
    )
    assert exc_info.value.retryable is False
    assert repositories.artifacts.list_by_session(session.session_id) == []


def test_external_provider_seal_rejects_invalid_artifact_kind_before_writing(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, _, _ = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories,
        workspace_root=tmp_path / "workspaces",
        blob_store_root=tmp_path / "blobs",
    )

    with pytest.raises(ArtifactBoundaryError) as exc_info:
        service.seal_external_bytes(
            session_id=session.session_id,
            content=b"{\"ok\": true}\n",
            filename="provider.json",
            kind="model",
            format="json",
            title="Provider response",
            provider="test-provider",
            provenance={
                "request_digest": _digest("request"),
                "retrieved_at": "2026-07-19T00:00:00+00:00",
            },
        )

    assert exc_info.value.error_code == "artifact_kind_invalid"
    assert exc_info.value.retryable is False
    assert repositories.artifacts.list_by_session(session.session_id) == []
    assert not (tmp_path / "blobs").exists()


def test_register_rejects_explicit_non_source_snapshot_artifact(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    input_artifact = _save_input_artifact(
        repositories,
        tmp_path,
        session_id=session.session_id,
    )
    output = workspace_root / workspace.sandbox_workspace_id / "output" / "result.csv"
    output.write_text("id,score\nA,1\n", encoding="utf-8")
    service = _service(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )

    with pytest.raises(ArtifactBoundaryError) as exc_info:
        service.register(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            path="/workspace/output/result.csv",
            kind="result",
            format="csv",
            metadata={"required_columns": ["id", "score"]},
            source_snapshot_artifact_id=input_artifact.artifact_id,
        )

    assert exc_info.value.error_code == "source_snapshot_unavailable"
    assert not any(
        artifact.relative_path == "result.csv"
        for artifact in repositories.artifacts.list_by_session(session.session_id)
    )


def test_register_fallback_prefers_latest_source_snapshot_over_command_summary(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    workspace_path = workspace_root / workspace.sandbox_workspace_id
    source = workspace_path / "src" / "main.py"
    source.write_text("print('v1')\n", encoding="utf-8")
    output = workspace_path / "output" / "result.csv"
    output.write_text("id,score\nA,1\n", encoding="utf-8")
    service = _service(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )
    prior_snapshot = service.snapshot_code(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        paths="/workspace/src",
        entrypoint="/workspace/src/main.py",
    )
    source.write_text("print('v2')\n", encoding="utf-8")
    current_snapshot = service.snapshot_code(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        paths="/workspace/src",
        entrypoint="/workspace/src/main.py",
    )
    refreshed = repositories.sandbox_workspaces.get(workspace.sandbox_workspace_id)
    assert refreshed is not None
    repositories.sandbox_workspaces.save(
        replace(
            refreshed,
            last_command_summary={
                "source_snapshot_artifact_id": prior_snapshot.artifact.artifact_id,
            },
        )
    )

    registered = service.register(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        path="/workspace/output/result.csv",
        kind="result",
        format="csv",
        metadata={"required_columns": ["id", "score"]},
    )

    assert (
        dict(registered.artifact.metadata or {})["source_snapshot_artifact_id"]
        == current_snapshot.artifact.artifact_id
    )


def test_snapshot_code_then_register_seals_output_and_keeps_duplicate_paths(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    workspace_path = workspace_root / workspace.sandbox_workspace_id
    source = workspace_path / "src" / "main.py"
    source.write_text("print('v1')\n", encoding="utf-8")
    output = workspace_path / "output" / "result.csv"
    output.write_text("id,score\nA,1\n", encoding="utf-8")
    service = _service(repositories, workspace_root=workspace_root, blob_store_root=tmp_path / "blobs")

    snapshot = service.snapshot_code(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        paths="/workspace/src",
        entrypoint="/workspace/src/main.py",
        metadata={"purpose": "test"},
    )
    first = service.register(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        path="/workspace/output/result.csv",
        kind="result",
        format="csv",
        metadata={"required_columns": ["id", "score"]},
    )
    idempotent = service.register(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        path="/workspace/output/result.csv",
        kind="result",
        format="csv",
        metadata={"required_columns": ["id", "score"]},
    )
    output.write_text("id,score\nB,2\n", encoding="utf-8")
    second = service.register(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        path="/workspace/output/result.csv",
        kind="result",
        format="csv",
        metadata={"required_columns": ["id", "score"]},
    )

    assert snapshot.artifact.kind is ArtifactKind.CODE
    assert snapshot.source_tree_digest.startswith("sha256:")
    assert first.artifact.artifact_id == idempotent.artifact.artifact_id
    assert idempotent.reused is True
    assert second.artifact.artifact_id != first.artifact.artifact_id
    assert first.artifact.relative_path == "result.csv"
    assert second.artifact.relative_path == "result.csv"
    assert str(workspace_path / "output") not in first.artifact.storage_uri
    assert Path(first.artifact.storage_uri).read_text(encoding="utf-8") == "id,score\nA,1\n"
    assert Path(second.artifact.storage_uri).read_text(encoding="utf-8") == "id,score\nB,2\n"
    records = [
        artifact
        for artifact in repositories.artifacts.list_by_session(session.session_id)
        if artifact.relative_path == "result.csv"
    ]
    assert len(records) == 2
    assert dict(first.artifact.metadata or {})["source_snapshot_artifact_id"] == snapshot.artifact.artifact_id
    assert "storage_uri" not in json.dumps(first.to_payload())


def test_read_registration_draft_prevalidates_without_persisting_artifact(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    workspace_path = workspace_root / workspace.sandbox_workspace_id
    source = workspace_path / "src" / "main.py"
    source.write_text("print('ready')\n", encoding="utf-8")
    output = workspace_path / "output" / "result.csv"
    content = "id,score\nA,1\n"
    output.write_text(content, encoding="utf-8")
    service = _service(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )
    snapshot = service.snapshot_code(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        paths="/workspace/src",
        entrypoint="/workspace/src/main.py",
        metadata={"purpose": "r65-prevalidation"},
    )
    artifact_ids_before = {
        artifact.artifact_id
        for artifact in repositories.artifacts.list_by_session(session.session_id)
    }

    draft = service.read_registration_draft(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        path="/workspace/output/result.csv",
        kind="result",
        format="csv",
        metadata={"required_columns": ["id", "score"]},
        source_snapshot_artifact_id=snapshot.artifact.artifact_id,
    )

    assert draft.public_path == "/workspace/output/result.csv"
    assert draft.relative_path == "result.csv"
    assert draft.content == content.encode("utf-8")
    assert draft.content_digest == _digest(content)
    assert draft.kind is ArtifactKind.RESULT
    assert draft.metadata == {
        "format": "csv",
        "required_columns": ["id", "score"],
    }
    assert draft.validation["status"] == "passed"
    assert draft.source_snapshot_artifact_id == snapshot.artifact.artifact_id
    assert draft.source_tree_digest == snapshot.source_tree_digest
    assert {
        artifact.artifact_id
        for artifact in repositories.artifacts.list_by_session(session.session_id)
    } == artifact_ids_before


def test_snapshot_code_empty_paths_reports_empty_selection_without_committing(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    source = workspace_root / workspace.sandbox_workspace_id / "src" / "main.py"
    source.write_text("print('ready')\n", encoding="utf-8")
    service = _service(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )

    with pytest.raises(ArtifactBoundaryError) as exc_info:
        service.snapshot_code(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            paths=[],
            entrypoint="/workspace/src/main.py",
        )

    assert exc_info.value.error_code == "source_snapshot_empty"
    assert exc_info.value.hint == (
        "Ensure the selected source paths contain at least one eligible regular file "
        "under /workspace/src. Omit paths to select the whole source tree; an empty "
        "paths list selects no files."
    )
    assert repositories.artifacts.list_by_session(session.session_id) == []


def test_large_registration_metadata_sidecar_persists_full_catalog_metadata_and_returns_bounded_control_payload(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    workspace_path = workspace_root / workspace.sandbox_workspace_id
    (workspace_path / "src" / "main.py").write_text(
        "print('register')\n",
        encoding="utf-8",
    )
    (workspace_path / "output" / "result.csv").write_text(
        "id,score\nA,1\n",
        encoding="utf-8",
    )
    service = _service(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )
    service.snapshot_code(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        paths="/workspace/src",
        entrypoint="/workspace/src/main.py",
    )
    identity_mappings = [
        {
            "requested_accession": f"A{index:05d}",
            "primary_accession": f"A{index:05d}",
            "padding": "x" * 480,
        }
        for index in range(10_000)
    ]
    metadata = {
        "contract_id": "aox_sequence_length_join@2",
        "identity_mappings": identity_mappings,
    }
    sidecar_bytes = json.dumps(
        metadata,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    assert len(sidecar_bytes) > 4 * 1024 * 1024
    sidecar_digest = f"sha256:{hashlib.sha256(sidecar_bytes).hexdigest()}"
    sidecar_path = (
        workspace_path
        / "work"
        / ".openzyme"
        / "artifact-metadata"
        / f"{sidecar_digest[7:]}.json"
    )
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_bytes(sidecar_bytes)

    registered = service.register(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        path="/workspace/output/result.csv",
        kind="result",
        format="csv",
        metadata_sidecar={
            "schema_id": "artifact_registration_metadata_sidecar@1",
            "path": (
                "/workspace/work/.openzyme/artifact-metadata/"
                f"{sidecar_digest[7:]}.json"
            ),
            "content_digest": sidecar_digest,
            "size_bytes": len(sidecar_bytes),
        },
    )

    persisted_metadata = dict(registered.artifact.metadata or {})
    assert persisted_metadata["identity_mappings"] == identity_mappings
    control_payload = registered.to_control_payload()
    serialized_control = json.dumps(control_payload, sort_keys=True)
    assert len(serialized_control.encode("utf-8")) < 32 * 1024
    assert "identity_mappings" not in serialized_control
    assert "x" * 128 not in serialized_control
    assert control_payload["schema_id"] == "artifact_registration_response@2"
    assert set(control_payload["artifact"]) == {"artifact_id", "metadata"}
    assert control_payload["validation"]["schema_id"] == (
        "artifact_registration_validation_summary@1"
    )
    assert (
        control_payload["artifact"]["metadata"]["sealed_digest"]
        == registered.content_digest
    )

    oversized_context = replace(
        registered.artifact,
        session_id="s" * (5 * 1024 * 1024),
        task_id="t" * (5 * 1024 * 1024),
        lane_id="l" * (5 * 1024 * 1024),
    )
    bounded_context_payload = replace(
        registered,
        artifact=oversized_context,
    ).to_control_payload()
    assert set(bounded_context_payload["artifact"]) == {"artifact_id", "metadata"}
    assert len(json.dumps(bounded_context_payload).encode("utf-8")) < 32 * 1024


def test_registration_response_bounds_maximal_required_columns(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    workspace_path = workspace_root / workspace.sandbox_workspace_id
    (workspace_path / "src" / "main.py").write_text(
        "print('register')\n",
        encoding="utf-8",
    )
    columns = [f"column_{index:04d}" for index in range(4_096)]
    (workspace_path / "output" / "wide.csv").write_text(
        ",".join(columns) + "\n" + ",".join("1" for _ in columns) + "\n",
        encoding="utf-8",
    )
    service = _service(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )
    service.snapshot_code(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        paths="/workspace/src",
        entrypoint="/workspace/src/main.py",
    )

    registered = service.register(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        path="/workspace/output/wide.csv",
        kind="result",
        format="csv",
        metadata={"required_columns": columns},
    )

    control_payload = registered.to_control_payload()
    validation = dict(control_payload["validation"])
    assert validation["required_columns_count"] == 4_096
    assert "required_columns" not in validation
    assert str(validation["required_columns_digest"]).startswith("sha256:")
    assert len(json.dumps(control_payload).encode("utf-8")) < 32 * 1024
    assert dict(registered.artifact.metadata or {})["validation"][
        "required_columns"
    ] == columns


def test_registration_rejects_large_caller_owned_digest_before_artifact_mutation(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    workspace_path = workspace_root / workspace.sandbox_workspace_id
    (workspace_path / "src" / "main.py").write_text(
        "print('register')\n",
        encoding="utf-8",
    )
    (workspace_path / "output" / "result.csv").write_text(
        "id\n1\n",
        encoding="utf-8",
    )
    service = _service(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )
    service.snapshot_code(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        paths="/workspace/src",
        entrypoint="/workspace/src/main.py",
    )
    artifacts_before = repositories.artifacts.list_by_session(session.session_id)
    metadata = {"tree_digest": "x" * (5 * 1024 * 1024)}
    payload = json.dumps(
        metadata,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    sidecar = (
        workspace_path
        / "work"
        / ".openzyme"
        / "artifact-metadata"
        / f"{digest[7:]}.json"
    )
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_bytes(payload)

    with pytest.raises(ArtifactBoundaryError) as error:
        service.register(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            path="/workspace/output/result.csv",
            kind="result",
            format="csv",
            metadata_sidecar={
                "schema_id": "artifact_registration_metadata_sidecar@1",
                "path": (
                    "/workspace/work/.openzyme/artifact-metadata/"
                    f"{digest[7:]}.json"
                ),
                "content_digest": digest,
                "size_bytes": len(payload),
            },
        )

    assert error.value.error_code == "artifact_registration_metadata_reserved"
    assert error.value.details == {"reserved_fields": ["tree_digest"]}
    assert repositories.artifacts.list_by_session(session.session_id) == artifacts_before


def test_registration_rejects_unbounded_inline_metadata_and_required_columns_before_mutation(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    workspace_path = workspace_root / workspace.sandbox_workspace_id
    (workspace_path / "src" / "main.py").write_text(
        "print('register')\n",
        encoding="utf-8",
    )
    (workspace_path / "output" / "result.csv").write_text(
        "id\n1\n",
        encoding="utf-8",
    )
    service = _service(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )
    service.snapshot_code(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        paths="/workspace/src",
        entrypoint="/workspace/src/main.py",
    )
    artifacts_before = repositories.artifacts.list_by_session(session.session_id)

    with pytest.raises(ArtifactBoundaryError) as inline_error:
        service.register(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            path="/workspace/output/result.csv",
            kind="result",
            format="csv",
            metadata={"padding": "x" * (256 * 1024)},
        )
    assert inline_error.value.error_code == (
        "artifact_registration_metadata_inline_too_large"
    )

    with pytest.raises(ArtifactBoundaryError) as columns_error:
        service.register(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            path="/workspace/output/result.csv",
            kind="result",
            format="csv",
            metadata={
                "required_columns": [
                    f"column_{index}" for index in range(4_097)
                ]
            },
        )
    assert columns_error.value.error_code == "artifact_validation_failed"
    assert repositories.artifacts.list_by_session(session.session_id) == artifacts_before


def test_registration_metadata_sidecar_digest_mismatch_has_no_artifact_mutation(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    workspace_path = workspace_root / workspace.sandbox_workspace_id
    (workspace_path / "src" / "main.py").write_text(
        "print('register')\n",
        encoding="utf-8",
    )
    (workspace_path / "output" / "result.csv").write_text(
        "id,score\nA,1\n",
        encoding="utf-8",
    )
    service = _service(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )
    service.snapshot_code(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        paths="/workspace/src",
        entrypoint="/workspace/src/main.py",
    )
    expected_bytes = b'{"identity_mappings":["A"]}'
    expected_digest = f"sha256:{hashlib.sha256(expected_bytes).hexdigest()}"
    sidecar_path = (
        workspace_path
        / "work"
        / ".openzyme"
        / "artifact-metadata"
        / f"{expected_digest[7:]}.json"
    )
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_bytes(b'{"identity_mappings":["tampered"]}')
    artifacts_before = repositories.artifacts.list_by_session(session.session_id)

    with pytest.raises(ArtifactBoundaryError) as error:
        service.register(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            path="/workspace/output/result.csv",
            kind="result",
            format="csv",
            metadata_sidecar={
                "schema_id": "artifact_registration_metadata_sidecar@1",
                "path": (
                    "/workspace/work/.openzyme/artifact-metadata/"
                    f"{expected_digest[7:]}.json"
                ),
                "content_digest": expected_digest,
                "size_bytes": sidecar_path.stat().st_size,
            },
        )

    assert error.value.error_code == (
        "artifact_registration_metadata_sidecar_digest_mismatch"
    )
    assert repositories.artifacts.list_by_session(session.session_id) == artifacts_before


def test_registration_metadata_sidecar_rejects_ambiguous_or_unsafe_bindings(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    workspace_path = workspace_root / workspace.sandbox_workspace_id
    service = _service(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )
    sidecar_root = workspace_path / "work" / ".openzyme" / "artifact-metadata"
    sidecar_root.mkdir(parents=True, exist_ok=True)

    canonical = b'{"a":1,"b":2}'
    canonical_digest = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    canonical_path = sidecar_root / f"{canonical_digest[7:]}.json"
    canonical_path.write_bytes(canonical)
    descriptor = {
        "schema_id": "artifact_registration_metadata_sidecar@1",
        "path": (
            "/workspace/work/.openzyme/artifact-metadata/"
            f"{canonical_digest[7:]}.json"
        ),
        "content_digest": canonical_digest,
        "size_bytes": len(canonical),
    }

    with pytest.raises(ArtifactBoundaryError) as ambiguous:
        service.resolve_registration_metadata(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            metadata={"inline": True},
            metadata_sidecar=descriptor,
        )
    assert ambiguous.value.error_code == (
        "artifact_registration_metadata_sidecar_invalid"
    )

    with pytest.raises(ArtifactBoundaryError) as wrong_path:
        service.resolve_registration_metadata(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            metadata_sidecar={
                **descriptor,
                "path": f"/workspace/work/{canonical_digest[7:]}.json",
            },
        )
    assert wrong_path.value.error_code == (
        "artifact_registration_metadata_sidecar_invalid"
    )

    with pytest.raises(ArtifactBoundaryError) as alias_path:
        service.resolve_registration_metadata(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            metadata_sidecar={
                **descriptor,
                "path": (
                    "/workspace/work/.openzyme/artifact-metadata/./"
                    f"{canonical_digest[7:]}.json"
                ),
            },
        )
    assert alias_path.value.error_code == (
        "artifact_registration_metadata_sidecar_invalid"
    )

    noncanonical = b'{"b":2, "a":1}'
    noncanonical_digest = f"sha256:{hashlib.sha256(noncanonical).hexdigest()}"
    noncanonical_path = sidecar_root / f"{noncanonical_digest[7:]}.json"
    noncanonical_path.write_bytes(noncanonical)
    with pytest.raises(ArtifactBoundaryError) as noncanonical_error:
        service.resolve_registration_metadata(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            metadata_sidecar={
                "schema_id": "artifact_registration_metadata_sidecar@1",
                "path": (
                    "/workspace/work/.openzyme/artifact-metadata/"
                    f"{noncanonical_digest[7:]}.json"
                ),
                "content_digest": noncanonical_digest,
                "size_bytes": len(noncanonical),
            },
        )
    assert noncanonical_error.value.error_code == (
        "artifact_registration_metadata_sidecar_noncanonical"
    )

    symlink_payload = b'{"symlink":true}'
    symlink_digest = f"sha256:{hashlib.sha256(symlink_payload).hexdigest()}"
    symlink_target = workspace_path / "work" / "metadata-target.json"
    symlink_target.write_bytes(symlink_payload)
    symlink_path = sidecar_root / f"{symlink_digest[7:]}.json"
    symlink_path.symlink_to(symlink_target)
    with pytest.raises(ArtifactBoundaryError) as symlink_error:
        service.resolve_registration_metadata(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            metadata_sidecar={
                "schema_id": "artifact_registration_metadata_sidecar@1",
                "path": (
                    "/workspace/work/.openzyme/artifact-metadata/"
                    f"{symlink_digest[7:]}.json"
                ),
                "content_digest": symlink_digest,
                "size_bytes": len(symlink_payload),
            },
        )
    assert symlink_error.value.error_code == (
        "artifact_registration_metadata_sidecar_invalid"
    )

    with pytest.raises(ArtifactBoundaryError) as oversized:
        service.resolve_registration_metadata(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            metadata_sidecar={
                **descriptor,
                "size_bytes": 32 * 1024 * 1024 + 1,
            },
        )
    assert oversized.value.error_code == (
        "artifact_registration_metadata_sidecar_too_large"
    )


@pytest.mark.parametrize(
    "payload",
    [
        b'{"a":1,"a":1}',
        b'{"value":NaN}',
    ],
)
def test_registration_metadata_sidecar_rejects_ambiguous_json(
    tmp_path: Path,
    payload: bytes,
) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    workspace_path = workspace_root / workspace.sandbox_workspace_id
    service = _service(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    sidecar_path = (
        workspace_path
        / "work"
        / ".openzyme"
        / "artifact-metadata"
        / f"{digest[7:]}.json"
    )
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_bytes(payload)

    with pytest.raises(ArtifactBoundaryError) as error:
        service.resolve_registration_metadata(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            metadata_sidecar={
                "schema_id": "artifact_registration_metadata_sidecar@1",
                "path": (
                    "/workspace/work/.openzyme/artifact-metadata/"
                    f"{digest[7:]}.json"
                ),
                "content_digest": digest,
                "size_bytes": len(payload),
            },
        )

    assert error.value.error_code == "artifact_registration_metadata_sidecar_invalid"


def test_registration_metadata_sidecar_rejects_symlinked_parent_directory(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    workspace_path = workspace_root / workspace.sandbox_workspace_id
    service = _service(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )
    payload = b'{"safe":true}'
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    outside = tmp_path / "outside"
    metadata_root = outside / "artifact-metadata"
    metadata_root.mkdir(parents=True)
    (metadata_root / f"{digest[7:]}.json").write_bytes(payload)
    (workspace_path / "work" / ".openzyme").symlink_to(outside)

    with pytest.raises(ArtifactBoundaryError) as error:
        service.resolve_registration_metadata(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            metadata_sidecar={
                "schema_id": "artifact_registration_metadata_sidecar@1",
                "path": (
                    "/workspace/work/.openzyme/artifact-metadata/"
                    f"{digest[7:]}.json"
                ),
                "content_digest": digest,
                "size_bytes": len(payload),
            },
        )

    assert error.value.error_code == "artifact_registration_metadata_sidecar_invalid"


def test_registration_metadata_sidecar_rejects_symlinked_workspace_leaf(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    workspace_path = workspace_root / workspace.sandbox_workspace_id
    service = _service(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )
    payload = b'{"safe":true}'
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    relocated_workspace = tmp_path / "relocated-workspace"
    workspace_path.rename(relocated_workspace)
    sidecar_root = (
        relocated_workspace / "work" / ".openzyme" / "artifact-metadata"
    )
    sidecar_root.mkdir(parents=True)
    (sidecar_root / f"{digest[7:]}.json").write_bytes(payload)
    workspace_path.symlink_to(relocated_workspace, target_is_directory=True)

    with pytest.raises(ArtifactBoundaryError) as error:
        service.resolve_registration_metadata(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            metadata_sidecar={
                "schema_id": "artifact_registration_metadata_sidecar@1",
                "path": (
                    "/workspace/work/.openzyme/artifact-metadata/"
                    f"{digest[7:]}.json"
                ),
                "content_digest": digest,
                "size_bytes": len(payload),
            },
        )

    assert error.value.error_code == "artifact_registration_metadata_sidecar_invalid"


def test_register_rejects_tampered_existing_content_addressed_blob(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    workspace_path = workspace_root / workspace.sandbox_workspace_id
    (workspace_path / "src" / "main.py").write_text("print('v1')\n", encoding="utf-8")
    output = workspace_path / "output" / "result.csv"
    output.write_text("id,score\nA,1\n", encoding="utf-8")
    service = _service(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )
    service.snapshot_code(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        paths="/workspace/src",
        entrypoint="/workspace/src/main.py",
    )
    registered = service.register(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        path="/workspace/output/result.csv",
        kind="result",
        format="csv",
        metadata={"required_columns": ["id", "score"]},
    )
    sealed_path = Path(registered.artifact.storage_uri)
    sealed_path.chmod(0o644)
    sealed_path.write_text("id,score\nTAMPERED,999\n", encoding="utf-8")

    with pytest.raises(ArtifactBoundaryError) as exc_info:
        service.register(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            path="/workspace/output/result.csv",
            kind="result",
            format="csv",
            metadata={"required_columns": ["id", "score"]},
        )

    assert exc_info.value.error_code == "artifact_blob_digest_mismatch"
    result_artifacts = [
        artifact
        for artifact in repositories.artifacts.list_by_session(session.session_id)
        if artifact.relative_path == "result.csv"
    ]
    assert [artifact.artifact_id for artifact in result_artifacts] == [
        registered.artifact.artifact_id
    ]


def test_snapshot_code_rejects_tampered_existing_snapshot_blob(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    source = workspace_root / workspace.sandbox_workspace_id / "src" / "main.py"
    source.write_text("print('v1')\n", encoding="utf-8")
    service = _service(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )
    first = service.snapshot_code(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        paths="/workspace/src",
        entrypoint="/workspace/src/main.py",
    )
    sealed_source = Path(first.artifact.storage_uri) / "main.py"
    sealed_source.chmod(0o644)
    sealed_source.write_text("print('tampered')\n", encoding="utf-8")

    with pytest.raises(ArtifactBoundaryError) as exc_info:
        service.snapshot_code(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            paths="/workspace/src",
            entrypoint="/workspace/src/main.py",
        )

    assert exc_info.value.error_code == "artifact_blob_digest_mismatch"


def test_register_directory_records_tree_digest_and_file_manifest(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    workspace_path = workspace_root / workspace.sandbox_workspace_id
    (workspace_path / "src" / "main.py").write_text("print('v1')\n", encoding="utf-8")
    output_dir = workspace_path / "output" / "tables"
    output_dir.mkdir(parents=True)
    (output_dir / "nodes.csv").write_text("id,label\nn1,AOX\n", encoding="utf-8")
    (output_dir / "edges.csv").write_text("source,target\nn1,n2\n", encoding="utf-8")
    service = _service(repositories, workspace_root=workspace_root, blob_store_root=tmp_path / "blobs")
    service.snapshot_code(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        paths="/workspace/src",
        entrypoint="/workspace/src/main.py",
    )

    registered = service.register(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        path="/workspace/output/tables",
        kind="result",
        format="text",
    )

    metadata = dict(registered.artifact.metadata or {})
    assert registered.tree_digest is not None
    assert metadata["tree_digest"] == registered.tree_digest
    assert {item["relative_path"] for item in metadata["file_manifest"]} == {
        "edges.csv",
        "nodes.csv",
    }
    assert Path(registered.artifact.storage_uri).is_dir()


def test_register_validators_are_host_owned_and_cannot_be_weakened(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    workspace_path = workspace_root / workspace.sandbox_workspace_id
    (workspace_path / "src" / "main.py").write_text("print('v1')\n", encoding="utf-8")
    bad_csv = workspace_path / "output" / "nodes.csv"
    bad_csv.write_text("node_id,label\nn1,AOX\n", encoding="utf-8")
    service = _service(repositories, workspace_root=workspace_root, blob_store_root=tmp_path / "blobs")
    service.snapshot_code(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        paths="/workspace/src",
        entrypoint="/workspace/src/main.py",
    )

    with pytest.raises(ArtifactBoundaryError) as missing_column:
        service.register(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            path="/workspace/output/nodes.csv",
            kind="result",
            format="csv",
            metadata={"required_columns": ["node_id", "label", "score"]},
        )
    assert missing_column.value.error_code == "artifact_validation_failed"

    unknown = workspace_path / "output" / "unknown.dat"
    unknown.write_text("content\n", encoding="utf-8")
    with pytest.raises(ArtifactBoundaryError) as missing_validator:
        service.register(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            path="/workspace/output/unknown.dat",
            kind="result",
            format="unknown",
        )
    assert missing_validator.value.error_code == "artifact_validator_missing"

    bad_fasta = workspace_path / "output" / "bad.fasta"
    bad_fasta.write_text("not a fasta\n", encoding="utf-8")
    with pytest.raises(ArtifactBoundaryError) as bad_fasta_error:
        service.register(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            path="/workspace/output/bad.fasta",
            kind="sequence",
            format="fasta",
            metadata={"required_columns": []},
        )
    assert bad_fasta_error.value.error_code == "artifact_validation_failed"


def test_register_accepts_only_typed_exact_zero_byte_empty_fasta(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    workspace_path = workspace_root / workspace.sandbox_workspace_id
    (workspace_path / "src" / "main.py").write_text(
        "print('v1')\n", encoding="utf-8"
    )
    empty_fasta = workspace_path / "output" / "target.fasta"
    empty_fasta.write_bytes(b"")
    service = _service(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    )
    service.snapshot_code(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        paths="/workspace/src",
        entrypoint="/workspace/src/main.py",
    )

    with pytest.raises(ArtifactBoundaryError) as untyped_empty:
        service.register(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            path="/workspace/output/target.fasta",
            kind="sequence",
            format="fasta",
        )
    assert untyped_empty.value.error_code == "artifact_validation_failed"

    registered = service.register(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        path="/workspace/output/target.fasta",
        kind="sequence",
        format="fasta",
        validation_profile=FASTA_ZERO_RECORDS_VALIDATION_PROFILE,
        metadata={
            "empty_result_reason": "no_candidates_after_length_filter",
            "derivation_contract_id": "aox_sequence_length_join@2",
        },
    )

    assert registered.content_digest == _digest("")
    assert Path(registered.artifact.storage_uri).read_bytes() == b""
    assert registered.validation == {
        "status": "passed",
        "format": "fasta",
        "required_columns": [],
        "validation_profile": FASTA_ZERO_RECORDS_VALIDATION_PROFILE,
        "empty_result_reason": "no_candidates_after_length_filter",
        "derivation_contract_id": "aox_sequence_length_join@2",
    }

    artifacts_before_oversized_contract = repositories.artifacts.list_by_session(
        session.session_id
    )
    with pytest.raises(ArtifactBoundaryError) as oversized_contract:
        service.register(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            path="/workspace/output/target.fasta",
            kind="sequence",
            format="fasta",
            validation_profile=FASTA_ZERO_RECORDS_VALIDATION_PROFILE,
            metadata={
                "empty_result_reason": "no_candidates_after_length_filter",
                "derivation_contract_id": f"{'a' * 256}@1",
            },
        )
    assert oversized_contract.value.error_code == "artifact_validation_failed"
    assert (
        repositories.artifacts.list_by_session(session.session_id)
        == artifacts_before_oversized_contract
    )

    sentinel = workspace_path / "output" / "sentinel.fasta"
    sentinel.write_text(">EMPTY\nX\n", encoding="utf-8")
    with pytest.raises(ArtifactBoundaryError) as metadata_spoof:
        service.register(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            path="/workspace/output/sentinel.fasta",
            kind="sequence",
            format="fasta",
            metadata={
                "validation_profile": FASTA_ZERO_RECORDS_VALIDATION_PROFILE,
                "empty_result_reason": "no_candidates_after_length_filter",
                "derivation_contract_id": "aox_sequence_length_join@2",
            },
        )
    assert metadata_spoof.value.error_code == "artifact_validation_failed"

    with pytest.raises(ArtifactBoundaryError) as nonempty_claim:
        service.register(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            path="/workspace/output/sentinel.fasta",
            kind="sequence",
            format="fasta",
            validation_profile=FASTA_ZERO_RECORDS_VALIDATION_PROFILE,
            metadata={
                "empty_result_reason": "no_candidates_after_length_filter",
                "derivation_contract_id": "aox_sequence_length_join@2",
            },
        )
    assert nonempty_claim.value.error_code == "artifact_validation_failed"


def test_register_commit_failure_does_not_expose_artifact_and_enqueues_gc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories = _build_repositories()
    session, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    workspace_path = workspace_root / workspace.sandbox_workspace_id
    (workspace_path / "src" / "main.py").write_text("print('v1')\n", encoding="utf-8")
    output = workspace_path / "output" / "result.csv"
    output.write_text("id,score\nA,1\n", encoding="utf-8")
    service = _service(repositories, workspace_root=workspace_root, blob_store_root=tmp_path / "blobs")
    service.snapshot_code(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        paths="/workspace/src",
        entrypoint="/workspace/src/main.py",
    )

    def fail_commit(_repository: object, _artifact: SessionArtifactRecord) -> None:
        raise RuntimeError("forced commit failure")

    monkeypatch.setattr(type(repositories.artifacts), "commit_immutable", fail_commit)
    with pytest.raises(ArtifactBoundaryError) as exc_info:
        service.register(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            path="/workspace/output/result.csv",
            kind="result",
            format="csv",
            metadata={"required_columns": ["id", "score"]},
        )

    assert exc_info.value.error_code == "artifact_commit_failed"
    assert repositories.artifact_blob_gc.list_pending()[0]["reason"] == "artifact_commit_failed"
    registered = [
        artifact
        for artifact in repositories.artifacts.list_by_session(session.session_id)
        if artifact.relative_path == "result.csv"
    ]
    assert registered == []
