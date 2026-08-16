from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
import hashlib
from typing import Callable
from typing import Protocol

from openzyme_domain import PublicationManifestEntry
from openzyme_domain import PublicationManifestObjectKind
from openzyme_domain import ScientificDeliverableBundle
from openzyme_domain import ScientificDeliverableRef
from openzyme_domain import ScientificDeliverableValidationReceipt
from openzyme_domain import ScientificFileStorage
from openzyme_domain import ScientificSelectionState
from openzyme_domain import canonical_scientific_deliverable_digest
from openzyme_domain import normalize_scientific_path

from .mutation_authority import current_mutation_write_authority
from .repositories import CoreRepositories


class ScientificFileDeliverableError(RuntimeError):
    error_code = "scientific_file_deliverable_rejected"


class ScientificPublishedByteReader(Protocol):
    """Read exact immutable objects without consulting an ambient checkout."""

    def read_git_blob(
        self,
        *,
        repository_binding_id: str,
        repository_binding_version: int,
        publication_ref: str,
        commit: str,
        path: str,
        object_id: str,
    ) -> bytes: ...

    def read_lfs_object(
        self,
        *,
        repository_binding_id: str,
        repository_binding_version: int,
        publication_ref: str,
        commit: str,
        path: str,
        lfs_oid: str,
        declared_size: int,
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class ResolvedScientificFile:
    publication_id: str
    path: str
    manifest_entry: PublicationManifestEntry
    storage: ScientificFileStorage
    actual_bytes: bytes
    content_digest: str


@dataclass(frozen=True, slots=True)
class ScientificRoleRequirement:
    scientific_role: str
    path: str
    format_contract_id: str
    format_contract_digest: str
    producer_adoption_id: str
    validate_bytes: Callable[[bytes], None]


@dataclass(frozen=True, slots=True)
class ScientificDeliverableFinalizationResult:
    refs: tuple[ScientificDeliverableRef, ...]
    bundle: ScientificDeliverableBundle
    receipt: ScientificDeliverableValidationReceipt


def _git_blob_oid(content: bytes, *, hex_length: int) -> str:
    preimage = f"blob {len(content)}\0".encode() + content
    if hex_length == 40:
        return hashlib.sha1(preimage, usedforsecurity=False).hexdigest()
    if hex_length == 64:
        return hashlib.sha256(preimage).hexdigest()
    raise ScientificFileDeliverableError("unsupported Git object format")


def _stable_id(prefix: str, digest: str) -> str:
    return f"{prefix}_{digest.removeprefix('sha256:')[:32]}"


@dataclass(slots=True)
class ScientificPublishedFileResolver:
    repositories: CoreRepositories
    reader: ScientificPublishedByteReader

    def resolve(self, *, publication_id: str, path: str) -> ResolvedScientificFile:
        normalized_path = normalize_scientific_path(path)
        revision = self.repositories.published_revisions.get(publication_id)
        if revision is None:
            raise ScientificFileDeliverableError("unknown immutable publication")
        entry = next(
            (item for item in revision.manifest.entries if item.path == normalized_path),
            None,
        )
        if (
            entry is None
            or entry.object_kind is not PublicationManifestObjectKind.BLOB
            or entry.mode not in {"100644", "100755"}
        ):
            raise ScientificFileDeliverableError(
                "scientific path is not an ordinary file in the exact publication tree"
            )
        pointer_bytes = self.reader.read_git_blob(
            repository_binding_id=revision.repository_binding_id,
            repository_binding_version=revision.repository_binding_version,
            publication_ref=revision.publication_ref,
            commit=revision.commit,
            path=normalized_path,
            object_id=entry.object_id,
        )
        if _git_blob_oid(pointer_bytes, hex_length=len(entry.object_id)) != entry.object_id:
            raise ScientificFileDeliverableError("published Git blob bytes drifted")
        if entry.size_bytes is not None and len(pointer_bytes) != entry.size_bytes:
            raise ScientificFileDeliverableError("published Git blob size drifted")

        if entry.lfs_oid is None:
            storage = ScientificFileStorage.GIT_BLOB
            actual_bytes = pointer_bytes
        else:
            if entry.lfs_size_bytes is None:
                raise ScientificFileDeliverableError("incomplete Git LFS manifest identity")
            storage = ScientificFileStorage.GIT_LFS
            actual_bytes = self.reader.read_lfs_object(
                repository_binding_id=revision.repository_binding_id,
                repository_binding_version=revision.repository_binding_version,
                publication_ref=revision.publication_ref,
                commit=revision.commit,
                path=normalized_path,
                lfs_oid=entry.lfs_oid,
                declared_size=entry.lfs_size_bytes,
            )
            if len(actual_bytes) != entry.lfs_size_bytes:
                raise ScientificFileDeliverableError("Git LFS actual size drifted")
            if "sha256:" + hashlib.sha256(actual_bytes).hexdigest() != entry.lfs_oid:
                raise ScientificFileDeliverableError("Git LFS actual bytes drifted")
        return ResolvedScientificFile(
            publication_id=publication_id,
            path=normalized_path,
            manifest_entry=entry,
            storage=storage,
            actual_bytes=actual_bytes,
            content_digest="sha256:" + hashlib.sha256(actual_bytes).hexdigest(),
        )


@dataclass(slots=True)
class ScientificDeliverableFinalizationService:
    repositories: CoreRepositories
    resolver: ScientificPublishedFileResolver
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def finalize(
        self,
        *,
        publication_id: str,
        attempt_id: str,
        selection_id: str,
        actor_ref: str,
        execution_fencing_token: int,
        contract_id: str,
        contract_digest: str,
        requirements: tuple[ScientificRoleRequirement, ...],
    ) -> ScientificDeliverableFinalizationResult:
        if not requirements:
            raise ScientificFileDeliverableError("scientific role manifest is empty")
        roles = tuple(item.scientific_role for item in requirements)
        paths = tuple(item.path for item in requirements)
        if len(set(roles)) != len(roles) or len(set(paths)) != len(paths):
            raise ScientificFileDeliverableError("scientific roles and paths must be unique")
        authority = current_mutation_write_authority()
        if authority is None or authority.writer_fencing_token != execution_fencing_token:
            raise ScientificFileDeliverableError("scientific finalization authority is fenced")

        revision = self.repositories.published_revisions.get(publication_id)
        attempt = self.repositories.scientific_attempts.get(attempt_id)
        selection = self.repositories.scientific_selections.get(selection_id)
        resolved_head = self.repositories.scientific_selections.resolve_head(attempt_id)
        if (
            revision is None
            or attempt is None
            or selection is None
            or selection.attempt_id != attempt_id
            or selection.state is not ScientificSelectionState.SEALED
            or resolved_head is None
            or resolved_head.head.selection_id != selection_id
        ):
            raise ScientificFileDeliverableError(
                "publication, attempt, or sealed selection identity is not current"
            )

        resolved = tuple(
            self.resolver.resolve(publication_id=publication_id, path=item.path)
            for item in requirements
        )
        for requirement, file in zip(requirements, resolved, strict=True):
            requirement.validate_bytes(file.actual_bytes)
        adoptions = tuple(
            self.repositories.scientific_deliverables.get_adoption(
                item.producer_adoption_id
            )
            for item in requirements
        )
        if any(
            adoption is None
            or adoption.attempt_id != attempt_id
            or adoption.selection_id != selection_id
            or adoption.workflow_role != requirement.scientific_role
            for adoption, requirement in zip(adoptions, requirements, strict=True)
        ):
            raise ScientificFileDeliverableError("producer adoption chain is not exact")

        preimage = {
            "schema_version": "scientific_deliverable_validation_preimage@1",
            "publication_digest": revision.revision_digest,
            "attempt_id": attempt_id,
            "attempt_state_version": attempt.state_version,
            "selection_id": selection_id,
            "selection_revision": selection.revision,
            "selection_adoption_digest": selection.adoption_digest,
            "actor_ref": actor_ref,
            "execution_fencing_token": execution_fencing_token,
            "contract_id": contract_id,
            "contract_digest": contract_digest,
            "entries": [
                {
                    "role": requirement.scientific_role,
                    "path": file.path,
                    "format_contract_id": requirement.format_contract_id,
                    "format_contract_digest": requirement.format_contract_digest,
                    "content_digest": file.content_digest,
                    "object_id": file.manifest_entry.object_id,
                    "lfs_oid": file.manifest_entry.lfs_oid,
                    "producer_adoption_digest": adoption.adoption_digest,
                }
                for requirement, file, adoption in zip(
                    requirements,
                    resolved,
                    adoptions,
                    strict=True,
                )
                if adoption is not None
            ],
        }
        validation_preimage_digest = canonical_scientific_deliverable_digest(preimage)
        created_at = self.now().isoformat()
        refs = tuple(
            ScientificDeliverableRef.create(
                ref_id=_stable_id(
                    "scientific_ref",
                    canonical_scientific_deliverable_digest(
                        {**preimage["entries"][index], "publication_id": publication_id}
                    ),
                ),
                project_id=revision.project_id,
                session_id=revision.session_id,
                repository_binding_id=revision.repository_binding_id,
                repository_binding_version=revision.repository_binding_version,
                repository_policy_digest=revision.repository_policy_digest,
                publication_id=revision.publication_id,
                publication_digest=revision.revision_digest,
                publication_ref=revision.publication_ref,
                published_commit=revision.commit,
                published_tree=revision.tree,
                path=file.path,
                storage=file.storage,
                git_blob_oid=(
                    file.manifest_entry.object_id
                    if file.storage is ScientificFileStorage.GIT_BLOB
                    else None
                ),
                lfs_oid=file.manifest_entry.lfs_oid,
                lfs_declared_size=file.manifest_entry.lfs_size_bytes,
                actual_size=len(file.actual_bytes),
                content_digest=file.content_digest,
                scientific_role=requirement.scientific_role,
                format_contract_id=requirement.format_contract_id,
                format_contract_digest=requirement.format_contract_digest,
                deliverable_contract_id=contract_id,
                deliverable_contract_digest=contract_digest,
                producer_operation_id=adoption.operation_id,
                producer_execution_id=adoption.execution_id,
                producer_result_id=adoption.result_id,
                producer_result_digest=adoption.result_digest,
                attempt_id=attempt_id,
                attempt_state_version=attempt.state_version,
                selection_id=selection_id,
                selection_revision=selection.revision,
                producer_adoption_id=adoption.adoption_id,
                selection_adoption_digest=selection.adoption_digest,
                publisher_workspace_id=revision.publisher_workspace_id,
                publisher_workspace_generation=revision.publisher_workspace_generation,
                publisher_agent_member_id=revision.publisher_agent_member_id,
                created_at=created_at,
                supersedes_ref_id=None,
            )
            for index, (requirement, file, adoption) in enumerate(
                zip(requirements, resolved, adoptions, strict=True)
            )
            if adoption is not None
        )
        role_manifest_digest = canonical_scientific_deliverable_digest(
            [
                {"role": ref.scientific_role, "path": ref.path, "ref_digest": ref.ref_digest}
                for ref in sorted(refs, key=lambda item: item.scientific_role)
            ]
        )
        bundle_id = _stable_id("scientific_bundle", validation_preimage_digest)
        bundle = ScientificDeliverableBundle.create(
            bundle_id=bundle_id,
            project_id=revision.project_id,
            session_id=revision.session_id,
            attempt_id=attempt_id,
            selection_id=selection_id,
            publication_id=publication_id,
            publication_digest=revision.revision_digest,
            contract_id=contract_id,
            contract_digest=contract_digest,
            ref_ids=tuple(ref.ref_id for ref in refs),
            role_manifest_digest=role_manifest_digest,
            validation_preimage_digest=validation_preimage_digest,
            created_at=created_at,
        )
        receipt = ScientificDeliverableValidationReceipt.create(
            receipt_id=_stable_id("scientific_receipt", bundle.bundle_digest),
            bundle_id=bundle.bundle_id,
            bundle_digest=bundle.bundle_digest,
            publication_id=publication_id,
            publication_digest=revision.revision_digest,
            attempt_id=attempt_id,
            attempt_state_version=attempt.state_version,
            selection_id=selection_id,
            selection_revision=selection.revision,
            actor_ref=actor_ref,
            execution_fencing_token=execution_fencing_token,
            validation_preimage_digest=validation_preimage_digest,
            verified_ref_digests=tuple(ref.ref_digest for ref in refs),
            created_at=created_at,
        )

        with self.repositories.atomic(prefix="scientific_file_deliverable_finalize"):
            current_attempt = self.repositories.scientific_attempts.get(attempt_id)
            current_selection = self.repositories.scientific_selections.get(selection_id)
            current_head = self.repositories.scientific_selections.resolve_head(attempt_id)
            current_revision = self.repositories.published_revisions.get(publication_id)
            current_authority = current_mutation_write_authority()
            if (
                current_attempt != attempt
                or current_selection != selection
                or current_revision != revision
                or current_head != resolved_head
                or current_authority != authority
            ):
                raise ScientificFileDeliverableError(
                    "scientific finalization facts drifted before commit"
                )
            stored_refs = tuple(
                self.repositories.scientific_deliverables.add_ref(ref) for ref in refs
            )
            stored_bundle = self.repositories.scientific_deliverables.add_bundle(
                bundle,
                refs=stored_refs,
            )
            stored_receipt = self.repositories.scientific_deliverables.add_receipt(receipt)
        return ScientificDeliverableFinalizationResult(
            refs=stored_refs,
            bundle=stored_bundle,
            receipt=stored_receipt,
        )


__all__ = [
    "ResolvedScientificFile",
    "ScientificDeliverableFinalizationResult",
    "ScientificDeliverableFinalizationService",
    "ScientificFileDeliverableError",
    "ScientificPublishedByteReader",
    "ScientificPublishedFileResolver",
    "ScientificRoleRequirement",
]
