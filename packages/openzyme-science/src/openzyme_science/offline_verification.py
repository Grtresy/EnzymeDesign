from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from typing import Callable
from typing import Protocol

from openzyme_contracts import ControlledOperationExecutionLifecycle
from openzyme_contracts import ControlledOperationExecutionTerminalOutcome
from openzyme_contracts import ControlledOperationStatus
from openzyme_contracts import WorkspaceFormalBoundary
from .attempts import ScientificOperationDispositionKind
from .deliverables import ScientificFileStorage
from .deliverables import canonical_scientific_deliverable_digest
from .file_deliverables import ScientificDeliverableRepositoryView
from .file_deliverables import ScientificFileDeliverableError
from .file_deliverables import ScientificPublishedByteReader
from .file_deliverables import ScientificPublishedFileResolver


class ScientificOfflineVerificationError(ScientificFileDeliverableError):
    error_code = "scientific_offline_verification_blocked"


class FreshScientificPublicationReader(ScientificPublishedByteReader, Protocol):
    """Reader whose fetch proof starts from a caller-owned empty object cache."""

    def fresh_fetch(
        self,
        *,
        repository_binding_id: str,
        repository_binding_version: int,
        publication_ref: str,
        commit: str,
        tree: str,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class ScientificOfflineVerificationResult:
    receipt_id: str
    receipt_digest: str
    bundle_id: str
    bundle_digest: str
    publication_id: str
    fresh_fetch_proof_digest: str
    verified_ref_ids: tuple[str, ...]
    verified_content_digests: tuple[str, ...]
    attempt_id: str
    selection_id: str
    closure_id: str | None
    verified_at: str
    verification_digest: str
    schema_version: str = "scientific_offline_verification@1"

    @property
    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "receipt_digest": self.receipt_digest,
            "bundle_id": self.bundle_id,
            "bundle_digest": self.bundle_digest,
            "publication_id": self.publication_id,
            "fresh_fetch_proof_digest": self.fresh_fetch_proof_digest,
            "verified_ref_ids": list(self.verified_ref_ids),
            "verified_content_digests": list(self.verified_content_digests),
            "attempt_id": self.attempt_id,
            "selection_id": self.selection_id,
            "closure_id": self.closure_id,
            "verified_at": self.verified_at,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.payload, "verification_digest": self.verification_digest}


@dataclass(slots=True)
class ScientificOfflineVerifier:
    repositories: ScientificDeliverableRepositoryView
    reader: FreshScientificPublicationReader
    format_validators: dict[str, Callable[[bytes], None]]
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def verify(self, receipt_id: str) -> ScientificOfflineVerificationResult:
        receipt = self.repositories.scientific_deliverables.get_receipt(receipt_id)
        if receipt is None:
            raise ScientificOfflineVerificationError(
                "scientific validation receipt is unknown"
            )
        bundle = self.repositories.scientific_deliverables.get_bundle(
            receipt.bundle_id
        )
        refs = self.repositories.scientific_deliverables.list_refs_by_bundle(
            receipt.bundle_id
        )
        publication = self.repositories.published_revisions.get(
            receipt.publication_id
        )
        if (
            bundle is None
            or publication is None
            or bundle.bundle_digest != receipt.bundle_digest
            or bundle.publication_digest != receipt.publication_digest
            or tuple(sorted(ref.ref_digest for ref in refs))
            != receipt.verified_ref_digests
        ):
            raise ScientificOfflineVerificationError(
                "scientific receipt metadata does not close over one bundle"
            )
        fetch_proof = self.reader.fresh_fetch(
            repository_binding_id=publication.repository_binding_id,
            repository_binding_version=publication.repository_binding_version,
            publication_ref=publication.publication_ref,
            commit=publication.commit,
            tree=publication.tree,
        )
        _require_digest(fetch_proof, "fresh fetch proof")
        resolver = ScientificPublishedFileResolver(self.repositories, self.reader)
        resolved = tuple(
            resolver.resolve(publication_id=publication.publication_id, path=ref.path)
            for ref in refs
        )
        for ref, item in zip(refs, resolved, strict=True):
            validator = self.format_validators.get(ref.format_contract_id)
            if validator is None:
                raise ScientificOfflineVerificationError(
                    f"format contract is not installed: {ref.format_contract_id}"
                )
            validator(item.actual_bytes)
            if (
                item.content_digest != ref.content_digest
                or item.storage is not ref.storage
                or (
                    ref.storage is ScientificFileStorage.GIT_BLOB
                    and item.manifest_entry.object_id != ref.git_blob_oid
                )
                or item.manifest_entry.lfs_oid != ref.lfs_oid
                or item.manifest_entry.lfs_size_bytes != ref.lfs_declared_size
                or len(item.actual_bytes) != ref.actual_size
            ):
                raise ScientificOfflineVerificationError(
                    f"published scientific bytes drifted for {ref.ref_id}"
                )
            adoption = self.repositories.scientific_deliverables.get_adoption(
                ref.producer_adoption_id
            )
            if (
                adoption is None
                or adoption.selection_id != ref.selection_id
                or adoption.attempt_id != ref.attempt_id
                or adoption.operation_id != ref.producer_operation_id
                or adoption.execution_id != ref.producer_execution_id
                or adoption.result_id != ref.producer_result_id
                or adoption.result_digest != ref.producer_result_digest
            ):
                raise ScientificOfflineVerificationError(
                    f"scientific producer lineage drifted for {ref.ref_id}"
                )
            operation = self.repositories.controlled_operations.get(
                adoption.operation_id
            )
            execution = self.repositories.controlled_operation_executions.get(
                adoption.execution_id
            )
            result = self.repositories.workspace_revision_executions.get_result(
                adoption.result_id
            )
            request = (
                self.repositories.workspace_revision_executions.get_request_by_execution(
                    adoption.execution_id
                )
            )
            link = (
                self.repositories.workspace_revision_executions.get_result_revision_link(
                    adoption.result_id
                )
            )
            checkpoint = (
                None
                if link is None
                else self.repositories.verified_workspace_checkpoints.get(
                    link.checkpoint_id
                )
            )
            lfs_closure = (
                None
                if link is None
                else self.repositories.git_lfs.get_closure_manifest(
                    link.lfs_closure_manifest_digest
                )
            )
            disposition = next(
                (
                    item
                    for item in self.repositories.scientific_dispositions.list_by_selection(
                        adoption.selection_id
                    )
                    if item.operation_id == adoption.operation_id
                ),
                None,
            )
            publication_proof = self.repositories.git_lfs.get_publication_intent_proof(
                publication.intent_id
            )
            if (
                operation is None
                or operation.session_id != publication.session_id
                or operation.status is not ControlledOperationStatus.COMPLETED
                or execution is None
                or execution.operation_id != adoption.operation_id
                or execution.session_id != publication.session_id
                or execution.fencing_token != adoption.execution_fencing_token
                or execution.lifecycle_state
                is not ControlledOperationExecutionLifecycle.TERMINAL
                or execution.terminal_outcome
                is not ControlledOperationExecutionTerminalOutcome.SUCCEEDED
                or execution.result_handle_ref != adoption.result_id
                or execution.result_digest != adoption.result_digest
                or result is None
                or result.operation_id != adoption.operation_id
                or result.execution_id != adoption.execution_id
                or result.result_digest != adoption.result_digest
                or getattr(result.terminal_state, "value", result.terminal_state)
                != "succeeded"
                or request is None
                or request.scientific_basis is None
                or request.scientific_basis.attempt_id != adoption.attempt_id
                or link is None
                or checkpoint is None
                or lfs_closure is None
                or disposition is None
                or disposition.attempt_id != adoption.attempt_id
                or disposition.kind is not ScientificOperationDispositionKind.ADOPTED
                or disposition.workflow_role != adoption.workflow_role
                or disposition.actor_ref != adoption.actor_ref
                or checkpoint.boundary is not WorkspaceFormalBoundary.EXTERNAL_JOB
                or checkpoint.workspace_id != publication.publisher_workspace_id
                or checkpoint.workspace_generation
                != publication.publisher_workspace_generation
                or checkpoint.agent_member_id
                != publication.publisher_agent_member_id
                or checkpoint.repository_binding_id
                != publication.repository_binding_id
                or checkpoint.repository_binding_version
                != publication.repository_binding_version
                or checkpoint.commit != publication.commit
                or checkpoint.tree != publication.tree
                or link.workspace_id != checkpoint.workspace_id
                or link.result_commit != checkpoint.commit
                or link.result_tree != checkpoint.tree
                or link.linked_by_agent_member_id != checkpoint.agent_member_id
                or lfs_closure.manifest_digest
                != link.lfs_closure_manifest_digest
                or lfs_closure.commit != publication.commit
                or lfs_closure.tree != publication.tree
                or publication_proof is None
                or publication_proof.get("manifest_digest")
                != lfs_closure.manifest_digest
            ):
                raise ScientificOfflineVerificationError(
                    f"scientific producer result revision drifted for {ref.ref_id}"
                )
        role_manifest_digest = canonical_scientific_deliverable_digest(
            [
                {
                    "role": ref.scientific_role,
                    "path": ref.path,
                    "ref_digest": ref.ref_digest,
                }
                for ref in sorted(refs, key=lambda value: value.scientific_role)
            ]
        )
        if role_manifest_digest != bundle.role_manifest_digest:
            raise ScientificOfflineVerificationError(
                "scientific role manifest digest drifted"
            )
        selection = self.repositories.scientific_selections.get(bundle.selection_id)
        attempt = self.repositories.scientific_attempts.get(bundle.attempt_id)
        if (
            selection is None
            or attempt is None
            or selection.adoption_digest
            != refs[0].selection_adoption_digest
            or any(ref.selection_id != selection.selection_id for ref in refs)
            or any(ref.attempt_id != attempt.attempt_id for ref in refs)
        ):
            raise ScientificOfflineVerificationError(
                "scientific attempt or selection lineage drifted"
            )
        closure = self.repositories.scientific_attempt_closures.get_by_attempt(
            attempt.attempt_id
        )
        if closure is not None and closure.selection_id != selection.selection_id:
            raise ScientificOfflineVerificationError(
                "scientific closure does not bind the verified selection"
            )
        verified_at = self.now().isoformat()
        payload = {
            "schema_version": "scientific_offline_verification@1",
            "receipt_id": receipt.receipt_id,
            "receipt_digest": receipt.receipt_digest,
            "bundle_id": bundle.bundle_id,
            "bundle_digest": bundle.bundle_digest,
            "publication_id": publication.publication_id,
            "fresh_fetch_proof_digest": fetch_proof,
            "verified_ref_ids": [ref.ref_id for ref in refs],
            "verified_content_digests": [ref.content_digest for ref in refs],
            "attempt_id": attempt.attempt_id,
            "selection_id": selection.selection_id,
            "closure_id": None if closure is None else closure.closure_id,
            "verified_at": verified_at,
        }
        return ScientificOfflineVerificationResult(
            receipt_id=receipt.receipt_id,
            receipt_digest=receipt.receipt_digest,
            bundle_id=bundle.bundle_id,
            bundle_digest=bundle.bundle_digest,
            publication_id=publication.publication_id,
            fresh_fetch_proof_digest=fetch_proof,
            verified_ref_ids=tuple(ref.ref_id for ref in refs),
            verified_content_digests=tuple(ref.content_digest for ref in refs),
            attempt_id=attempt.attempt_id,
            selection_id=selection.selection_id,
            closure_id=None if closure is None else closure.closure_id,
            verified_at=verified_at,
            verification_digest=canonical_scientific_deliverable_digest(payload),
        )


def _require_digest(value: str, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ScientificOfflineVerificationError(
            f"{name} must be a canonical SHA-256 digest"
        )


__all__ = [
    "FreshScientificPublicationReader",
    "ScientificOfflineVerificationError",
    "ScientificOfflineVerificationResult",
    "ScientificOfflineVerifier",
]
