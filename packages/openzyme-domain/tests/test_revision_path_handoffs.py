from __future__ import annotations

from dataclasses import replace

import pytest

from openzyme_domain import ControlledOperationResultRef
from openzyme_domain import ProtocolFileHandoff
from openzyme_domain import ReportRef
from openzyme_domain import RevisionPathEntryKind
from openzyme_domain import RevisionPathRef
from openzyme_domain import TaskEvidenceKind
from openzyme_domain import TaskEvidenceRef


SHA = f"sha256:{'a' * 64}"


def _path_ref() -> RevisionPathRef:
    return RevisionPathRef.create(
        ref_id="ref_1",
        publication_id="publication_1",
        project_id="project_1",
        session_id="session_1",
        repository_binding_id="binding_1",
        repository_binding_version=1,
        repository_id="repository_1",
        commit="b" * 40,
        tree="c" * 40,
        path="research/invocation/dossier.json",
        entry_kind=RevisionPathEntryKind.FILE,
        object_id="d" * 40,
        size_bytes=42,
        lfs_oid=None,
        lfs_size_bytes=None,
        path_manifest_digest=None,
        created_at="2026-08-17T00:00:00+00:00",
    )


def test_revision_path_ref_round_trips_without_type_coercion() -> None:
    ref = _path_ref()

    assert RevisionPathRef.from_dict(ref.to_dict()) == ref

    malformed = ref.to_dict()
    malformed["repository_binding_version"] = True
    with pytest.raises(ValueError, match="must be an integer"):
        RevisionPathRef.from_dict(malformed)

    malformed = ref.to_dict()
    malformed["ref_id"] = 7
    with pytest.raises(ValueError, match="must be a string"):
        RevisionPathRef.from_dict(malformed)


def test_revision_path_ref_rejects_traversal_and_identity_drift() -> None:
    with pytest.raises(ValueError, match="repository-relative"):
        replace(_path_ref(), path="../outside")
    with pytest.raises(ValueError, match="digest mismatch"):
        replace(_path_ref(), object_id="e" * 40)


def test_task_evidence_is_a_closed_nested_variant() -> None:
    path_ref = _path_ref()
    evidence = TaskEvidenceRef(
        kind=TaskEvidenceKind.REVISION_PATH,
        project_id=path_ref.project_id,
        session_id=path_ref.session_id,
        task_id="task_1",
        owner_id=path_ref.ref_id,
        owner_digest=path_ref.ref_digest,
        revision_path_ref=path_ref,
    )

    assert TaskEvidenceRef.from_dict(evidence.to_dict()) == evidence
    malformed = evidence.to_dict()
    malformed["report_ref"] = ReportRef.create(
        report_id="report_1",
        project_id="project_1",
        session_id="session_1",
        task_id="task_1",
        content_ref_id="ref_1",
        report_version=1,
        supersedes_report_id=None,
    ).to_dict()
    with pytest.raises(ValueError, match="another evidence variant"):
        TaskEvidenceRef.from_dict(malformed)

    missing_task = evidence.to_dict()
    missing_task["task_id"] = None
    with pytest.raises(ValueError, match="task_id must be a string"):
        TaskEvidenceRef.from_dict(missing_task)


def test_lfs_revision_path_ref_rejects_pointer_identity_drift() -> None:
    lfs_ref = RevisionPathRef.create(
        ref_id="lfs_ref_1",
        publication_id="publication_1",
        project_id="project_1",
        session_id="session_1",
        repository_binding_id="binding_1",
        repository_binding_version=1,
        repository_id="repository_1",
        commit="b" * 40,
        tree="c" * 40,
        path="research/invocation/large-result.bin",
        entry_kind=RevisionPathEntryKind.LFS_FILE,
        object_id="d" * 40,
        size_bytes=130,
        lfs_oid=SHA,
        lfs_size_bytes=10_000,
        path_manifest_digest=None,
        created_at="2026-08-17T00:00:00+00:00",
    )

    malformed = lfs_ref.to_dict()
    malformed["lfs_size_bytes"] = 9_999
    with pytest.raises(ValueError, match="digest mismatch"):
        RevisionPathRef.from_dict(malformed)


def test_report_and_controlled_result_variants_bind_canonical_owner_fields() -> None:
    report_ref = ReportRef.create(
        report_id="report_1",
        project_id="project_1",
        session_id="session_1",
        task_id="task_1",
        content_ref_id="ref_1",
        report_version=2,
        supersedes_report_id="report_0",
    )
    report_evidence = TaskEvidenceRef(
        kind=TaskEvidenceKind.REPORT,
        project_id="project_1",
        session_id="session_1",
        task_id="task_1",
        owner_id="report_1",
        owner_digest=report_ref.report_digest,
        report_ref=report_ref,
    )
    assert TaskEvidenceRef.from_dict(report_evidence.to_dict()) == report_evidence

    result_ref = ControlledOperationResultRef(
        result_handle_id="result_1",
        project_id="project_1",
        session_id="session_1",
        task_id="task_1",
        execution_id="execution_1",
        operation_id="operation_1",
        dispatch_generation=1,
        terminal_outcome="succeeded",
        result_digest=SHA,
    )
    result_evidence = TaskEvidenceRef(
        kind=TaskEvidenceKind.CONTROLLED_OPERATION_RESULT,
        project_id="project_1",
        session_id="session_1",
        task_id="task_1",
        owner_id="result_1",
        owner_digest=SHA,
        controlled_operation_result_ref=result_ref,
    )
    assert TaskEvidenceRef.from_dict(result_evidence.to_dict()) == result_evidence


def test_protocol_handoff_rejects_non_object_entries_without_filtering() -> None:
    handoff = ProtocolFileHandoff.create(
        handoff_id="handoff_1",
        project_id="project_1",
        session_id="session_1",
        producer_agent_id="agent:producer",
        recipient_agent_id="agent:recipient",
        purpose="review dossier",
        entries=(_path_ref(),),
        created_at="2026-08-17T00:01:00+00:00",
    )
    malformed = handoff.to_dict()
    malformed["entries"] = [handoff.entries[0].to_dict(), "ignored"]

    with pytest.raises(ValueError, match="only revision path objects"):
        ProtocolFileHandoff.from_dict(malformed)
