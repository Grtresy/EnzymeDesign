import hashlib

import pytest

from openzyme_contracts import RevisionCommitObservation
from openzyme_contracts import RevisionPathEntryKind
from openzyme_contracts import RevisionPathReadReceipt
from openzyme_contracts import RevisionPathReadRequest
from openzyme_contracts import RevisionPathRef
from openzyme_contracts import RevisionPathVerificationReceipt
from openzyme_contracts import WorkspaceRevisionBackendPort
from openzyme_contracts import WorkspacePublicationDispatchIdentity


COMMIT = "a" * 40
TREE = "b" * 40
OBJECT = "c" * 40
DIGEST = "sha256:" + "d" * 64


def _revision_path_ref() -> RevisionPathRef:
    return RevisionPathRef.create(
        ref_id="ref-1",
        publication_id="publication-1",
        project_id="project-1",
        session_id="session-1",
        repository_binding_id="binding-1",
        repository_binding_version=1,
        repository_id="repository-1",
        commit=COMMIT,
        tree=TREE,
        path="results/model.hmm",
        entry_kind=RevisionPathEntryKind.FILE,
        object_id=OBJECT,
        size_bytes=3,
        lfs_oid=None,
        lfs_size_bytes=None,
        path_manifest_digest=None,
        created_at="2026-08-19T00:00:00Z",
    )


def test_revision_observation_and_verification_receipts_bind_exact_identity() -> None:
    observation = RevisionCommitObservation.create(
        repository_binding_id="binding-1",
        repository_binding_version=1,
        repository_id="repository-1",
        commit=COMMIT,
        tree=TREE,
        parent_commits=("e" * 40,),
        observed_at="2026-08-19T00:00:00Z",
    )
    assert observation.observation_digest.startswith("sha256:")

    receipt = RevisionPathVerificationReceipt.create(
        ref_id="ref-1",
        publication_id="publication-1",
        repository_binding_id="binding-1",
        repository_binding_version=1,
        commit=COMMIT,
        tree=TREE,
        path="results/model.hmm",
        object_id=OBJECT,
        actual_size_bytes=3,
        actual_content_digest=DIGEST,
        lfs_oid=None,
        lfs_size_bytes=None,
        verified_at="2026-08-19T00:00:01Z",
    )
    assert receipt.verification_digest.startswith("sha256:")


def test_revision_path_read_is_bounded_and_byte_verified() -> None:
    ref = _revision_path_ref()
    request = RevisionPathReadRequest(ref=ref, max_bytes=3)
    assert request.ref is ref

    payload = b"hmm"
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    receipt = RevisionPathReadReceipt(
        ref_id=ref.ref_id,
        publication_id=ref.publication_id,
        returned_bytes=payload,
        returned_bytes_digest=digest,
        actual_size_bytes=len(payload),
        actual_content_digest=digest,
        truncated=False,
        verified_at="2026-08-19T00:00:02Z",
    )
    assert receipt.returned_bytes == payload

    with pytest.raises(ValueError, match="returned byte digest mismatch"):
        RevisionPathReadReceipt(
            ref_id=ref.ref_id,
            publication_id=ref.publication_id,
            returned_bytes=payload,
            returned_bytes_digest=DIGEST,
            actual_size_bytes=len(payload),
            actual_content_digest=digest,
            truncated=False,
            verified_at="2026-08-19T00:00:02Z",
        )


def test_revision_backend_port_is_implementation_free_protocol() -> None:
    assert WorkspaceRevisionBackendPort._is_protocol is True


def test_publication_dispatch_identity_is_closed_and_fenced() -> None:
    dispatch = WorkspacePublicationDispatchIdentity(
        receipt_id="receipt-1",
        execution_id="execution-1",
        dispatch_generation=2,
        fencing_token=9,
    )
    assert dispatch.dispatch_generation == 2
    with pytest.raises(ValueError, match="fencing_token"):
        WorkspacePublicationDispatchIdentity(
            receipt_id="receipt-2",
            execution_id="execution-2",
            dispatch_generation=1,
            fencing_token=0,
        )


@pytest.mark.parametrize("max_bytes", [0, 1_048_577])
def test_revision_path_read_rejects_unbounded_limits(max_bytes: int) -> None:
    with pytest.raises(ValueError, match="max_bytes"):
        RevisionPathReadRequest(ref=_revision_path_ref(), max_bytes=max_bytes)
