from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from openzyme_core import AOX_SCIENTIFIC_FILE_ROLES
from openzyme_core import ScientificFileDeliverableError
from openzyme_domain import PublicationManifestEntry
from openzyme_domain import PublicationManifestObjectKind
from openzyme_domain import PublishedRevision
from openzyme_domain import WorkspacePublicationManifest
from openzyme_host_api import aox_file_bundle_finalizer as finalizer_module
from openzyme_host_api.aox_file_bundle_finalizer import AoxFileBundleFinalizationError
from openzyme_host_api.aox_file_bundle_finalizer import AoxFileBundleFinalizer
from openzyme_host_api.file_workspace_control_gateway import (
    FileWorkspaceControlGatewayError,
)
from openzyme_host_api.file_workspace_control_gateway import (
    HostFileWorkspaceControlGateway,
)
from openzyme_pipeline import aox_candidate
from openzyme_pipeline.aox_finalization import finalization_calculation_receipt


DIGEST = "sha256:" + "a" * 64


def _git_blob_oid(content: bytes) -> str:
    return hashlib.sha1(
        f"blob {len(content)}\0".encode() + content,
        usedforsecurity=False,
    ).hexdigest()


def _aox_files(*, empty: bool = False) -> dict[str, bytes]:
    reason = "no_candidates_after_exact_filters"
    empty_file = json.dumps(
        {
            "schema_id": "aox_conditional_empty_file@1",
            "calculation_id": "aox_empty_fixture@1",
            "empty_result_reason": reason,
            "source_output_digest": DIGEST,
            "source_receipt_digest": DIGEST,
        },
        sort_keys=True,
    ).encode()
    files: dict[str, bytes] = {}
    for entry in AOX_SCIENTIFIC_FILE_ROLES:
        if entry.format_contract_id in {"fasta@1", "aligned_fasta@1"}:
            files[entry.path] = empty_file if empty else b">sequence_1\nACDE\n"
        elif entry.format_contract_id == "csv@1":
            files[entry.path] = b"record_id\n"
        elif entry.format_contract_id == "hmmer3@1":
            files[entry.path] = b"HMMER3/f [fixture]\n//\n"
        elif entry.format_contract_id == "aox_execution_summary@1":
            payload: dict[str, object] = {"candidate_count": 0 if empty else 1}
            if empty:
                payload["empty_result"] = {
                    "schema_id": "aox_conditional_empty_result@1",
                    "reason": reason,
                    "receipt_digest": DIGEST,
                }
            files[entry.path] = json.dumps(payload, sort_keys=True).encode()
        else:
            files[entry.path] = b"{}\n"
    return files


class _PublishedRevisionRepository:
    def __init__(self, revision: PublishedRevision) -> None:
        self.revision = revision

    def get(self, publication_id: str) -> PublishedRevision | None:
        return self.revision if publication_id == self.revision.publication_id else None


class _Reader:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.reads: list[dict[str, object]] = []

    def read_git_blob(self, *, path: str, **identity: object) -> bytes:
        self.reads.append({"path": path, **identity})
        return self.files[path]

    def read_lfs_object(self, **_: object) -> bytes:
        raise AssertionError("AOX fixture does not use Git LFS")


class _Record:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def to_dict(self) -> dict[str, object]:
        return dict(self.payload)


def _fixture(files: dict[str, bytes]) -> tuple[object, _Reader]:
    manifest = WorkspacePublicationManifest.create(
        tuple(
            PublicationManifestEntry(
                path=path,
                mode="100644",
                object_kind=PublicationManifestObjectKind.BLOB,
                object_id=_git_blob_oid(content),
                size_bytes=len(content),
            )
            for path, content in sorted(files.items())
        )
    )
    revision = PublishedRevision.create(
        publication_id="publication_1",
        intent_id="intent_1",
        project_id="project_1",
        session_id="session_1",
        repository_binding_id="binding_1",
        repository_binding_version=1,
        repository_id="repository_1",
        commit="1" * 40,
        tree="2" * 40,
        git_parent_commits=("3" * 40,),
        declared_base_commit="3" * 40,
        parent_publication_id=None,
        publisher_agent_member_id="member_1",
        publisher_agent_id="agent_1",
        publisher_workspace_id="workspace_1",
        publisher_workspace_generation=1,
        publication_ref="refs/openzyme/publications/publication_1",
        manifest=manifest,
        repository_policy_version="policy@1",
        repository_policy_digest=DIGEST,
        controlled_execution_id="publication_execution_1",
        remote_receipt_id="publication_receipt_1",
        supersedes_publication_id=None,
        created_at="2026-08-18T00:00:00+00:00",
    )
    repositories = SimpleNamespace(
        published_revisions=_PublishedRevisionRepository(revision)
    )
    return repositories, _Reader(files)


def _calculation_receipts() -> list[dict[str, object]]:
    candidate = aox_candidate.CandidateFilterResult(
        target_input_digest="sha256:" + "1" * 64,
        scoring_input_digest="sha256:" + "2" * 64,
        targets=(),
        candidates=(),
    )
    return [candidate.calculation_receipt(), finalization_calculation_receipt()]


def _adoptions() -> dict[str, str]:
    return {
        entry.role: f"adoption_{index}"
        for index, entry in enumerate(AOX_SCIENTIFIC_FILE_ROLES)
    }


def test_aox_finalizer_validates_exact_17_role_published_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories, reader = _fixture(_aox_files())
    captured: dict[str, object] = {}

    class _FinalizationService:
        def __init__(self, **_: object) -> None:
            pass

        def finalize(self, **kwargs: object) -> object:
            captured.update(kwargs)
            requirements = kwargs["requirements"]
            assert isinstance(requirements, tuple)
            return SimpleNamespace(
                bundle=_Record({"bundle_id": "bundle_1"}),
                receipt=_Record({"receipt_id": "receipt_1"}),
                refs=tuple(
                    _Record({"scientific_role": requirement.scientific_role})
                    for requirement in requirements
                ),
            )

    monkeypatch.setattr(
        finalizer_module,
        "ScientificDeliverableFinalizationService",
        _FinalizationService,
    )

    result = AoxFileBundleFinalizer(repositories, reader).finalize(
        publication_id="publication_1",
        attempt_id="attempt_1",
        selection_id="selection_1",
        actor_ref="agent:scientist",
        execution_fencing_token=9,
        producer_adoption_ids_by_role=_adoptions(),
        calculation_receipts=_calculation_receipts(),
    )

    requirements = captured["requirements"]
    assert isinstance(requirements, tuple)
    assert len(requirements) == 17
    assert {item.scientific_role for item in requirements} == set(_adoptions())
    assert len(result["deliverables"]) == 17
    assert result["scientific_validation"]["role_count"] == 17
    assert result["task_transition_performed"] is False
    assert result["attempt_transition_performed"] is False
    assert result["campaign_decision_performed"] is False
    assert {str(item["path"]) for item in reader.reads} == set(_aox_files())
    assert {str(item["publication_ref"]) for item in reader.reads} == {
        "refs/openzyme/publications/publication_1"
    }
    assert {str(item["commit"]) for item in reader.reads} == {"1" * 40}


def test_aox_finalizer_accepts_contract_valid_empty_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories, reader = _fixture(_aox_files(empty=True))

    class _FinalizationService:
        def __init__(self, **_: object) -> None:
            pass

        def finalize(self, **_: object) -> object:
            return SimpleNamespace(
                bundle=_Record({"bundle_id": "bundle_empty"}),
                receipt=_Record({"receipt_id": "receipt_empty"}),
                refs=(),
            )

    monkeypatch.setattr(
        finalizer_module,
        "ScientificDeliverableFinalizationService",
        _FinalizationService,
    )

    result = AoxFileBundleFinalizer(repositories, reader).finalize(
        publication_id="publication_1",
        attempt_id="attempt_1",
        selection_id="selection_1",
        actor_ref="agent:scientist",
        execution_fencing_token=9,
        producer_adoption_ids_by_role=_adoptions(),
        calculation_receipts=_calculation_receipts(),
    )

    validation = result["scientific_validation"]
    assert validation["candidate_count"] == 0
    assert len(validation["typed_empty_paths"]) > 0


def test_aox_finalizer_rejects_missing_duplicate_role_and_malformed_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = _aox_files()
    repositories, reader = _fixture(files)
    finalizer = AoxFileBundleFinalizer(repositories, reader)

    missing = _adoptions()
    missing.pop(next(iter(missing)))
    with pytest.raises(AoxFileBundleFinalizationError, match="exact 17 roles"):
        finalizer.finalize(
            publication_id="publication_1",
            attempt_id="attempt_1",
            selection_id="selection_1",
            actor_ref="agent:scientist",
            execution_fencing_token=9,
            producer_adoption_ids_by_role=missing,
            calculation_receipts=_calculation_receipts(),
        )
    original_roles = finalizer_module.AOX_SCIENTIFIC_FILE_ROLES
    monkeypatch.setattr(
        finalizer_module,
        "AOX_SCIENTIFIC_FILE_ROLES",
        original_roles[:-1] + (original_roles[0],),
    )
    with pytest.raises(ScientificFileDeliverableError, match="exact ordered 17-role"):
        finalizer.finalize(
            publication_id="publication_1",
            attempt_id="attempt_1",
            selection_id="selection_1",
            actor_ref="agent:scientist",
            execution_fencing_token=9,
            producer_adoption_ids_by_role=_adoptions(),
            calculation_receipts=_calculation_receipts(),
        )
    monkeypatch.setattr(
        finalizer_module,
        "AOX_SCIENTIFIC_FILE_ROLES",
        original_roles,
    )

    malformed_files = _aox_files()
    malformed_files["aox_hmm/AOX_ref.hmm"] = b"not-hmmer\n"
    malformed_repositories, malformed_reader = _fixture(malformed_files)
    with pytest.raises(ScientificFileDeliverableError, match="HMMER3"):
        AoxFileBundleFinalizer(
            malformed_repositories,
            malformed_reader,
        ).finalize(
            publication_id="publication_1",
            attempt_id="attempt_1",
            selection_id="selection_1",
            actor_ref="agent:scientist",
            execution_fencing_token=9,
            producer_adoption_ids_by_role=_adoptions(),
            calculation_receipts=_calculation_receipts(),
        )


def test_scientific_finalize_gateway_rejects_artifact_era_request_fields() -> None:
    gateway = HostFileWorkspaceControlGateway(
        repositories=SimpleNamespace(),  # type: ignore[arg-type]
        roots=None,
        runner=None,
        scheduler_credential_issuer=None,
    )
    artifact_era_request: dict[str, object] = {
        "schema_version": "aox_scientific_file_finalize_request@1",
        "publication_id": "publication_1",
        "attempt_id": "attempt_1",
        "selection_id": "selection_1",
        "execution_fencing_token": 9,
        "producer_adoption_ids_by_role": _adoptions(),
        "calculation_receipts": _calculation_receipts(),
        "artifact_ids": ["legacy-artifact-1"],
    }

    with pytest.raises(
        FileWorkspaceControlGatewayError,
        match="scientific finalization request fields are closed",
    ):
        gateway._finalize(
            artifact_era_request,
            context=SimpleNamespace(),  # type: ignore[arg-type]
            authority=SimpleNamespace(),  # type: ignore[arg-type]
        )
