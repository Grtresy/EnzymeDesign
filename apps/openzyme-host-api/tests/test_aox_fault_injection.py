from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import EngineDocumentRepository
from openzyme_core import MutationScopeService
from openzyme_core import ScientificAttemptError
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import MutationWriterKind
from openzyme_pipeline import aox_reference
from openzyme_host_api.aox_fault_injection import (
    FAULT_INJECTION_CLAIM_DOCUMENT_KIND,
)
from openzyme_host_api.aox_public_product_closure import (
    FAULT_INJECTION_RECEIPT_DOCUMENT_KIND,
)
from openzyme_host_api.aox_scientific_contract import (
    AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY,
)
from openzyme_host_api.v3_service import V3EventStore
from openzyme_host_api.v3_service import V3HostApiService


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _fault_service(
    tmp_path: Path,
) -> tuple[V3HostApiService, CoreRepositories, str, str, Path]:
    connection = connect_sqlite(":memory:", check_same_thread=False)
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    blob_root = tmp_path / "blobs"
    blob_root.mkdir()
    service = V3HostApiService(
        allow_unpinned_repository_sessions_for_tests=True,
        repositories=repositories,
        event_store=V3EventStore(repositories),
        artifact_blob_root=blob_root,
        scientific_workflow_contract_registry=(
            AOX_SCIENTIFIC_WORKFLOW_CONTRACT_REGISTRY
        ),
    )
    session_id = "sess_aox_exact_fault"
    lane_id = "lane_aox_exact_fault"
    task_id = "task_aox_exact_fault"
    actor_ref = "agent:aox-exact-fault-executor"
    service.create_session(
        project_id="aox-fault",
        objective="Prove one exact byte flip",
        session_id=session_id,
    )
    service.create_lane(
        {
            "session_id": session_id,
            "lane_id": lane_id,
            "name": "fault",
            "cwd": ".",
        }
    )
    service.create_task(
        {
            "session_id": session_id,
            "task_id": task_id,
            "subject": "AOX fault",
            "kind": "execution",
            "lane_id": lane_id,
            "assigned_ref": actor_ref,
        }
    )
    now = "2026-08-01T00:00:00+00:00"
    repositories.agents.save(
        AgentMember(
            agent_id=actor_ref,
            session_id=session_id,
            lane_id=lane_id,
            task_id=task_id,
            name="AOX exact fault executor",
            role="executor",
            status=AgentMemberStatus.ACTIVE,
            parent_agent_id="agent:master",
            created_at=now,
            updated_at=now,
            runtime_state="idle",
        )
    )
    service.claim_lane(lane_id, claimed_ref=actor_ref)
    grant = service.grant_scientific_attempt_authorization(
        {
            "task_id": task_id,
            "campaign_id": "campaign_aox_exact_fault",
            "workflow_id": "aox_blank_world",
            "root_ref": "attempts/aox-exact-fault",
            "grantor_kind": "operator",
            "allowed_scopes": ["fault"],
            "allowed_effect_classes": ["provider", "hpc"],
            "allowed_providers": ["provider:pinned"],
            "allowed_hpc_targets": ["hpc:pinned"],
            "max_attempts": 1,
            "max_micu": 100,
            "max_cost_microunits": 1_000,
            "max_wall_time_seconds": 600,
            "expires_at": "2099-01-01T00:00:00+00:00",
        },
        session_id=session_id,
        grantor_ref="user:local-dev",
        idempotency_key="grant-aox-exact-fault",
    )
    envelope_id = str(grant["record"]["envelope_id"])
    admission = service.scientific_attempt_control().request_authorized_attempt_admission(
        envelope_id=envelope_id,
        session_id=session_id,
        task_id=task_id,
        actor_ref=actor_ref,
        idempotency_key="create-aox-exact-fault",
    )
    assert repositories.scientific_attempts.list_by_session(session_id) == []
    service.finalize_pending_scientific_transitions(session_id=session_id)
    attempt = repositories.scientific_attempts.list_by_session(session_id)[0]
    assert attempt.admission_request_id == admission.admission_request_id
    assert attempt.created_by == actor_ref
    return service, repositories, session_id, attempt.attempt_id, blob_root


def _register_fault_target(
    *,
    repositories: CoreRepositories,
    session_id: str,
    attempt_id: str,
    blob_root: Path,
) -> tuple[str, Path, bytes]:
    records = "".join(
        f">{accession}\nA\n" for accession in aox_reference.HMM_REFERENCE_ACCESSIONS
    ).encode("ascii")
    content_digest = _digest(records)
    artifact_id = "artifact_aox_ref21_crash"
    blob_path = (
        blob_root / "sealed" / "files" / content_digest.removeprefix("sha256:")
    )
    blob_path.parent.mkdir(parents=True)
    blob_path.write_bytes(records)
    blob_path.chmod(0o400)
    attempt = repositories.scientific_attempts.get(attempt_id)
    assert attempt is not None
    with MutationScopeService(repositories).writer_turn(
        session_id=session_id,
        owner_kind=MutationWriterKind.ARTIFACT_PUBLISHER,
        owner_ref="fixture:aox-ref21-crash",
    ):
        repositories.artifacts.commit_immutable(
            SessionArtifactRecord(
                artifact_id=artifact_id,
                session_id=session_id,
                task_id=attempt.task_id,
                lane_id=attempt.lane_id,
                invocation_id=None,
                run_id=None,
                kind=ArtifactKind.SEQUENCE,
                storage_uri=str(blob_path),
                relative_path="aox_hmm/AOX_ref21.fasta",
                metadata={
                    "source": "sandbox_artifact_boundary",
                    "storage_model": "sealed_blob",
                    "format": "fasta",
                    "sealed_digest": content_digest,
                    "content_digest": content_digest,
                    "contract_id": aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID,
                    "contract_digest": (
                        aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
                    ),
                    "implementation_digest": (
                        aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
                    ),
                    "output_name": aox_reference.HMM_REFERENCE_SET_OUTPUT_NAME,
                    "output_digest": content_digest,
                    "selected_accessions": list(aox_reference.HMM_REFERENCE_ACCESSIONS),
                    "ncbi_reference_accessions": list(
                        aox_reference.NCBI_REFERENCE_ACCESSIONS
                    ),
                    "provider_request_ids": ["provider-request-exact14"],
                },
                created_at="2026-08-01T00:00:00+00:00",
            )
        )
    return artifact_id, blob_path, records


def test_exact_fault_capability_flips_only_byte_zero_and_is_one_use(
    tmp_path: Path,
) -> None:
    service, repositories, session_id, attempt_id, blob_root = _fault_service(tmp_path)
    records = "".join(
        f">{accession}\nA\n" for accession in aox_reference.HMM_REFERENCE_ACCESSIONS
    ).encode("ascii")
    content_digest = _digest(records)
    artifact_id = "artifact_aox_ref21"
    blob_path = (
        blob_root / "sealed" / "files" / content_digest.removeprefix("sha256:")
    )
    blob_path.parent.mkdir(parents=True)
    blob_path.write_bytes(records)
    blob_path.chmod(0o400)
    attempt = repositories.scientific_attempts.get(attempt_id)
    assert attempt is not None
    with MutationScopeService(repositories).writer_turn(
        session_id=session_id,
        owner_kind=MutationWriterKind.ARTIFACT_PUBLISHER,
        owner_ref="fixture:aox-ref21",
    ):
        repositories.artifacts.commit_immutable(
            SessionArtifactRecord(
                artifact_id=artifact_id,
                session_id=session_id,
                task_id=attempt.task_id,
                lane_id=attempt.lane_id,
                invocation_id=None,
                run_id=None,
                kind=ArtifactKind.SEQUENCE,
                storage_uri=str(blob_path),
                relative_path="aox_hmm/AOX_ref21.fasta",
                metadata={
                    "source": "sandbox_artifact_boundary",
                    "storage_model": "sealed_blob",
                    "format": "fasta",
                    "sealed_digest": content_digest,
                    "content_digest": content_digest,
                    "contract_id": aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID,
                    "contract_digest": (
                        aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
                    ),
                    "implementation_digest": (
                        aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
                    ),
                    "output_name": aox_reference.HMM_REFERENCE_SET_OUTPUT_NAME,
                    "output_digest": content_digest,
                    "selected_accessions": list(aox_reference.HMM_REFERENCE_ACCESSIONS),
                    "ncbi_reference_accessions": list(
                        aox_reference.NCBI_REFERENCE_ACCESSIONS
                    ),
                    "provider_request_ids": ["provider-request-exact14"],
                },
                created_at="2026-08-01T00:00:00+00:00",
            )
        )

    receipt = service.inject_aox_reference_fault(
        session_id=session_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        actor_ref="user:local-dev",
        idempotency_key="fault-once",
    )

    mutated = blob_path.read_bytes()
    assert mutated[0] == records[0] ^ 0x01
    assert mutated[1:] == records[1:]
    assert receipt["observed_before_digest"] == content_digest
    assert receipt["observed_after_digest"] == _digest(mutated)
    assert stat_mode(blob_path) == 0o400
    assert (
        sum(
            document.document_kind == FAULT_INJECTION_CLAIM_DOCUMENT_KIND
            for document in repositories.engine_documents.list_by_session(session_id)
        )
        == 1
    )
    assert (
        service.inject_aox_reference_fault(
            session_id=session_id,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
            actor_ref="user:local-dev",
            idempotency_key="fault-once",
        )
        == receipt
    )
    with pytest.raises(ScientificAttemptError) as conflict:
        service.inject_aox_reference_fault(
            session_id=session_id,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
            actor_ref="user:local-dev",
            idempotency_key="fault-twice",
        )
    assert conflict.value.error_code == "aox_fault_injection_idempotency_conflict"


def test_exact_fault_claim_survives_post_mutation_receipt_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, repositories, session_id, attempt_id, blob_root = _fault_service(tmp_path)
    artifact_id, blob_path, records = _register_fault_target(
        repositories=repositories,
        session_id=session_id,
        attempt_id=attempt_id,
        blob_root=blob_root,
    )
    original_save = EngineDocumentRepository.save

    def fail_receipt(repository, document) -> None:
        if document.document_kind == FAULT_INJECTION_RECEIPT_DOCUMENT_KIND:
            raise RuntimeError("receipt persistence fault")
        original_save(repository, document)

    monkeypatch.setattr(EngineDocumentRepository, "save", fail_receipt)
    with pytest.raises(RuntimeError, match="receipt persistence fault"):
        service.inject_aox_reference_fault(
            session_id=session_id,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
            actor_ref="user:local-dev",
            idempotency_key="fault-crash",
        )

    documents = repositories.engine_documents.list_by_session(session_id)
    assert blob_path.read_bytes()[0] == records[0] ^ 0x01
    assert sum(
        document.document_kind == FAULT_INJECTION_CLAIM_DOCUMENT_KIND
        for document in documents
    ) == 1
    assert not any(
        document.document_kind == FAULT_INJECTION_RECEIPT_DOCUMENT_KIND
        for document in documents
    )
    with pytest.raises(ScientificAttemptError) as retry:
        service.inject_aox_reference_fault(
            session_id=session_id,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
            actor_ref="user:local-dev",
            idempotency_key="fault-crash",
        )
    assert retry.value.error_code == "aox_fault_injection_incomplete"


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777
