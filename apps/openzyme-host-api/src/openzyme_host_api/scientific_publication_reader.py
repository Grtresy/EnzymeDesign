from __future__ import annotations

from dataclasses import dataclass

from openzyme_core import CoreRepositories
from openzyme_core import DurableLfsObjectStore
from openzyme_core import DurableRepositoryRootManager
from openzyme_core import RepositoryStorageError
from openzyme_domain import ProjectRepositoryBinding


SCIENTIFIC_GIT_BLOB_MAX_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class DurableScientificPublicationReader:
    repositories: CoreRepositories
    roots: DurableRepositoryRootManager

    def read_git_blob(
        self,
        *,
        repository_binding_id: str,
        repository_binding_version: int,
        publication_ref: str,
        commit: str,
        path: str,
        object_id: str,
    ) -> bytes:
        binding = self._require_binding(
            repository_binding_id,
            repository_binding_version,
        )
        self._require_publication_ref(binding, publication_ref, commit)
        manifest = self.roots.read_whole_tree_manifest(binding, commit=commit)
        entries = [entry for entry in manifest.entries if entry.path == path]
        if len(entries) != 1 or entries[0].object_id != object_id:
            raise RepositoryStorageError(
                "scientific path does not match the immutable publication tree"
            )
        size = entries[0].size_bytes
        if size is None or size < 0 or size > SCIENTIFIC_GIT_BLOB_MAX_BYTES:
            raise RepositoryStorageError(
                "scientific Git blob is outside the bounded reader contract"
            )
        return self.roots.read_blob(
            binding,
            object_id=object_id,
            max_bytes=SCIENTIFIC_GIT_BLOB_MAX_BYTES,
        )

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
    ) -> bytes:
        del path
        binding = self._require_binding(
            repository_binding_id,
            repository_binding_version,
        )
        self._require_publication_ref(binding, publication_ref, commit)
        object_path = DurableLfsObjectStore(self.roots).verify(
            binding.repository_id,
            lfs_oid,
            size=declared_size,
        )
        return object_path.read_bytes()

    def _require_binding(
        self,
        binding_id: str,
        binding_version: int,
    ) -> ProjectRepositoryBinding:
        binding = self.repositories.project_repository_bindings.get(binding_id)
        if binding is None or binding.binding_version != binding_version:
            raise RepositoryStorageError(
                "scientific publication repository binding is absent or stale"
            )
        return binding

    def _require_publication_ref(
        self,
        binding: ProjectRepositoryBinding,
        publication_ref: str,
        commit: str,
    ) -> None:
        if self.roots.read_exact_ref(binding, ref_name=publication_ref) != commit:
            raise RepositoryStorageError(
                "scientific publication ref no longer resolves to the exact commit"
            )


__all__ = [
    "SCIENTIFIC_GIT_BLOB_MAX_BYTES",
    "DurableScientificPublicationReader",
]
