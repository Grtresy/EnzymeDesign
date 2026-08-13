from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
from typing import Any

from openzyme_core import CoreRepositories
from openzyme_core import EngineDocumentRecord
from openzyme_core import ScientificAttemptError
from openzyme_core import canonical_digest
from openzyme_domain.control_plane import utc_now_iso
from openzyme_pipeline import aox_reference

from .aox_cutover_evidence import FAULT_ARTIFACT_BYTE_FLIP_ID
from .aox_public_product_closure import FAULT_INJECTION_RECEIPT_DOCUMENT_KIND


FAULT_INJECTION_CLAIM_DOCUMENT_KIND = "aox_fault_injection_claim"
FAULT_INJECTION_CLAIM_SCHEMA_ID = "aox_fault_injection_claim@1"
FAULT_INJECTION_RECEIPT_SCHEMA_ID = "aox_fault_injection_receipt@1"
FAULT_TARGET_RELATIVE_PATH = "aox_hmm/AOX_ref21.fasta"
FAULT_EXPECTED_CONSUMER_TOOL_ID = "bio_tools.mafft"


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _document_identity(*, session_id: str, attempt_id: str, artifact_id: str) -> str:
    return canonical_digest(
        {
            "session_id": session_id,
            "attempt_id": attempt_id,
            "artifact_id": artifact_id,
            "injection_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
        }
    ).removeprefix("sha256:")[:32]


def aox_fault_injection_request_digest(
    *,
    session_id: str,
    attempt_id: str,
    artifact_id: str,
    idempotency_key: str,
) -> str:
    return canonical_digest(
        {
            "session_id": session_id,
            "attempt_id": attempt_id,
            "artifact_id": artifact_id,
            "idempotency_key": idempotency_key,
        }
    )


def observe_authority_bound_aox_reference_byte_flip(
    repositories: CoreRepositories,
    *,
    session_id: str,
    attempt_id: str,
    artifact_id: str,
    actor_ref: str,
    idempotency_key: str,
) -> tuple[str, dict[str, Any] | None]:
    """Read the exact durable fault owner without touching its capability."""

    identity = _document_identity(
        session_id=session_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
    )
    claim = repositories.engine_documents.get(f"aox_fault_claim_{identity}")
    receipt = repositories.engine_documents.get(f"aox_fault_receipt_{identity}")
    expected_request_digest = aox_fault_injection_request_digest(
        session_id=session_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        idempotency_key=idempotency_key,
    )
    if receipt is not None:
        payload = dict(receipt.payload)
        if not all(
            (
                payload.get("schema_id") == FAULT_INJECTION_RECEIPT_SCHEMA_ID,
                payload.get("session_id") == session_id,
                payload.get("attempt_id") == attempt_id,
                payload.get("target_artifact_id") == artifact_id,
                payload.get("actor_ref") == actor_ref,
                payload.get("idempotency_key") == idempotency_key,
                payload.get("request_digest") == expected_request_digest,
            )
        ):
            raise ScientificAttemptError(
                "aox_fault_injection_observation_drift",
                "durable AOX fault receipt differs from the exact request identity",
            )
        return "terminal", payload
    if claim is not None:
        payload = dict(claim.payload)
        if not all(
            (
                payload.get("schema_id") == FAULT_INJECTION_CLAIM_SCHEMA_ID,
                payload.get("session_id") == session_id,
                payload.get("attempt_id") == attempt_id,
                payload.get("target_artifact_id") == artifact_id,
                payload.get("actor_ref") == actor_ref,
                payload.get("idempotency_key") == idempotency_key,
                payload.get("request_digest") == expected_request_digest,
            )
        ):
            raise ScientificAttemptError(
                "aox_fault_injection_observation_drift",
                "durable AOX fault claim differs from the exact request identity",
            )
        return "claimed", None
    return "unobserved", None


def _target_path(
    *, storage_uri: str, blob_root: Path | None
) -> tuple[Path, os.stat_result]:
    if blob_root is None or not storage_uri or "://" in storage_uri:
        raise ScientificAttemptError(
            "aox_fault_target_storage_invalid",
            "exact AOX fault injection requires configured local sealed blob storage",
        )
    path = Path(storage_uri).expanduser().absolute()
    root = blob_root.expanduser().resolve(strict=True)
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ScientificAttemptError(
            "aox_fault_target_storage_invalid",
            "exact AOX fault target is not a readable sealed file",
        ) from exc
    if not all(
        (
            stat.S_ISREG(metadata.st_mode),
            not stat.S_ISLNK(metadata.st_mode),
            resolved == path,
            root in path.parents,
            metadata.st_size > 0,
        )
    ):
        raise ScientificAttemptError(
            "aox_fault_target_storage_invalid",
            "exact AOX fault target must be one non-empty real file under the blob root",
        )
    return path, metadata


def inject_authority_bound_aox_reference_byte_flip(
    repositories: CoreRepositories,
    *,
    session_id: str,
    attempt_id: str,
    artifact_id: str,
    actor_ref: str,
    idempotency_key: str,
    blob_root: Path | None,
) -> dict[str, Any]:
    """Flip byte zero of the exact derived AOX HMM reference once.

    The immutable claim is persisted before touching the blob. A crash after
    that point burns the capability and therefore remains fail-closed.
    """

    attempt = repositories.scientific_attempts.get(attempt_id)
    if (
        attempt is None
        or attempt.session_id != session_id
        or attempt.scope.value != "fault"
        or attempt.status.value != "active"
    ):
        raise ScientificAttemptError(
            "aox_fault_authority_invalid",
            "exact AOX fault injection requires the active authority-bound fault attempt",
        )
    artifact = repositories.artifacts.get(artifact_id)
    metadata = {} if artifact is None else dict(artifact.metadata or {})
    expected_digest = str(
        metadata.get("sealed_digest") or metadata.get("content_digest") or ""
    )
    target_relative_path = str(
        metadata.get("catalog_relative_path") or (
            "" if artifact is None else artifact.relative_path
        )
    )
    if not all(
        (
            artifact is not None,
            artifact is not None and artifact.session_id == session_id,
            artifact is not None and artifact.task_id == attempt.task_id,
            artifact is not None and artifact.lane_id == attempt.lane_id,
            artifact is not None and artifact.kind.value == "sequence",
            target_relative_path == FAULT_TARGET_RELATIVE_PATH,
            metadata.get("source") == "sandbox_artifact_boundary",
            metadata.get("storage_model") == "sealed_blob",
            metadata.get("format") == "fasta",
            metadata.get("contract_id")
            == aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID,
            metadata.get("contract_digest")
            == aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST,
            metadata.get("implementation_digest")
            == aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST,
            metadata.get("output_name") == aox_reference.HMM_REFERENCE_SET_OUTPUT_NAME,
            metadata.get("output_digest") == expected_digest,
            metadata.get("selected_accessions")
            == list(aox_reference.HMM_REFERENCE_ACCESSIONS),
            metadata.get("ncbi_reference_accessions")
            == list(aox_reference.NCBI_REFERENCE_ACCESSIONS),
            isinstance(metadata.get("provider_request_ids"), list),
            bool(metadata.get("provider_request_ids")),
            expected_digest.startswith("sha256:") and len(expected_digest) == 71,
        )
    ):
        raise ScientificAttemptError(
            "aox_fault_target_contract_invalid",
            "fault target is not the exact derived AOX_ref21.fasta contract artifact",
        )
    identity = _document_identity(
        session_id=session_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
    )
    claim_id = f"aox_fault_claim_{identity}"
    receipt_id = f"aox_fault_receipt_{identity}"
    existing_receipt = repositories.engine_documents.get(receipt_id)
    if existing_receipt is not None:
        receipt = dict(existing_receipt.payload)
        if receipt.get("idempotency_key") != idempotency_key:
            raise ScientificAttemptError(
                "aox_fault_injection_idempotency_conflict",
                "exact AOX fault capability was already consumed by another request",
            )
        return receipt
    if repositories.engine_documents.get(claim_id) is not None:
        raise ScientificAttemptError(
            "aox_fault_injection_incomplete",
            "exact AOX fault claim was consumed without a complete receipt",
        )
    existing_consumers = [
        operation.operation_id
        for operation in repositories.controlled_operations.list_by_session(session_id)
        if artifact_id in operation.input_artifact_ids
    ]
    if existing_consumers:
        raise ScientificAttemptError(
            "aox_fault_target_already_consumed",
            "exact byte flip must precede the one pending MAFFT consumer",
        )
    path, path_metadata = _target_path(
        storage_uri=str(artifact.storage_uri),
        blob_root=blob_root,
    )
    expected_blob_path = (
        blob_root.expanduser().resolve(strict=True)
        / "sealed"
        / "files"
        / expected_digest.removeprefix("sha256:")
    )
    if path != expected_blob_path:
        raise ScientificAttemptError(
            "aox_fault_target_storage_invalid",
            "exact AOX fault target must use its content-addressed sealed-file path",
        )
    before = path.read_bytes()
    if _sha256(before) != expected_digest:
        raise ScientificAttemptError(
            "artifact_blob_digest_mismatch",
            "AOX fault target already differs from its sealed catalog digest",
        )
    try:
        lines = before.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise ScientificAttemptError(
            "aox_fault_target_contract_invalid",
            "exact AOX fault target must be canonical ASCII FASTA",
        ) from exc
    headers = [line[1:].split(maxsplit=1)[0] for line in lines if line.startswith(">")]
    sequence_lines = [line for line in lines if line and not line.startswith(">")]
    if (
        headers != list(aox_reference.HMM_REFERENCE_ACCESSIONS)
        or not sequence_lines
        or any(
            not line
            or any(character not in "ACDEFGHIKLMNPQRSTVWYBXZJUO" for character in line)
            for line in sequence_lines
        )
    ):
        raise ScientificAttemptError(
            "aox_fault_target_contract_invalid",
            "exact AOX fault target bytes do not reproduce the fixed HMM reference set",
        )
    request_digest = aox_fault_injection_request_digest(
        session_id=session_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        idempotency_key=idempotency_key,
    )
    claimed_at = utc_now_iso()
    claim_payload = {
        "schema_id": FAULT_INJECTION_CLAIM_SCHEMA_ID,
        "injection_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
        "session_id": session_id,
        "attempt_id": attempt_id,
        "campaign_id": attempt.campaign_id,
        "task_id": attempt.task_id,
        "lane_id": attempt.lane_id,
        "authority_envelope_id": attempt.envelope_id,
        "target_artifact_id": artifact_id,
        "target_relative_path": FAULT_TARGET_RELATIVE_PATH,
        "byte_offset": 0,
        "expected_consumer_tool_id": FAULT_EXPECTED_CONSUMER_TOOL_ID,
        "expected_content_digest": expected_digest,
        "actor_ref": actor_ref,
        "idempotency_key": idempotency_key,
        "request_digest": request_digest,
        "claimed_at": claimed_at,
    }
    claim = {**claim_payload, "claim_digest": canonical_digest(claim_payload)}
    repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id=claim_id,
            session_id=session_id,
            document_kind=FAULT_INJECTION_CLAIM_DOCUMENT_KIND,
            payload=claim,
            created_at=claimed_at,
            updated_at=claimed_at,
        )
    )
    descriptor: int | None = None
    original_mode = stat.S_IMODE(path_metadata.st_mode)
    try:
        path.chmod(original_mode | stat.S_IWUSR)
        descriptor = os.open(
            path,
            os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (
            path_metadata.st_dev,
            path_metadata.st_ino,
        ):
            raise ScientificAttemptError(
                "aox_fault_target_identity_drift",
                "AOX fault target identity changed after its claim",
            )
        first = os.pread(descriptor, 1, 0)
        if len(first) != 1:
            raise ScientificAttemptError(
                "aox_fault_target_storage_invalid",
                "AOX fault target has no byte zero",
            )
        os.pwrite(descriptor, bytes([first[0] ^ 0x01]), 0)
        os.fsync(descriptor)
    finally:
        if descriptor is not None:
            os.fchmod(descriptor, original_mode)
            os.close(descriptor)
        else:
            path.chmod(original_mode)
    after = path.read_bytes()
    after_digest = _sha256(after)
    if len(after) != len(before) or after_digest == expected_digest:
        raise ScientificAttemptError(
            "aox_fault_mutation_unproven",
            "exact AOX byte flip did not produce one distinct same-size blob",
        )
    injected_at = utc_now_iso()
    receipt_payload = {
        "schema_id": FAULT_INJECTION_RECEIPT_SCHEMA_ID,
        "injection_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
        "session_id": session_id,
        "attempt_id": attempt_id,
        "campaign_id": attempt.campaign_id,
        "task_id": attempt.task_id,
        "lane_id": attempt.lane_id,
        "authority_envelope_id": attempt.envelope_id,
        "target_artifact_id": artifact_id,
        "target_relative_path": FAULT_TARGET_RELATIVE_PATH,
        "byte_offset": 0,
        "expected_consumer_tool_id": FAULT_EXPECTED_CONSUMER_TOOL_ID,
        "expected_content_digest": expected_digest,
        "observed_before_digest": expected_digest,
        "observed_after_digest": after_digest,
        "size_bytes": len(before),
        "source_contract_id": metadata["contract_id"],
        "source_contract_digest": metadata["contract_digest"],
        "source_implementation_digest": metadata["implementation_digest"],
        "source_storage_model": "sealed_blob",
        "source_storage_path_contract": (
            "artifact_blob_root/sealed/files/{content_digest_hex}"
        ),
        "actor_ref": actor_ref,
        "idempotency_key": idempotency_key,
        "request_digest": request_digest,
        "claim_digest": claim["claim_digest"],
        "injected_at": injected_at,
    }
    receipt = {
        **receipt_payload,
        "receipt_digest": canonical_digest(receipt_payload),
    }
    repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id=receipt_id,
            session_id=session_id,
            document_kind=FAULT_INJECTION_RECEIPT_DOCUMENT_KIND,
            payload=receipt,
            created_at=injected_at,
            updated_at=injected_at,
        )
    )
    return receipt


__all__ = [
    "FAULT_EXPECTED_CONSUMER_TOOL_ID",
    "FAULT_INJECTION_CLAIM_DOCUMENT_KIND",
    "FAULT_INJECTION_CLAIM_SCHEMA_ID",
    "FAULT_INJECTION_RECEIPT_SCHEMA_ID",
    "FAULT_TARGET_RELATIVE_PATH",
    "aox_fault_injection_request_digest",
    "inject_authority_bound_aox_reference_byte_flip",
    "observe_authority_bound_aox_reference_byte_flip",
]
