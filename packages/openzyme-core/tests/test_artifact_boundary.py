from __future__ import annotations

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
            "derivation_contract_id": "aox_sequence_length_join@1",
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
        "derivation_contract_id": "aox_sequence_length_join@1",
    }

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
                "derivation_contract_id": "aox_sequence_length_join@1",
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
                "derivation_contract_id": "aox_sequence_length_join@1",
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
