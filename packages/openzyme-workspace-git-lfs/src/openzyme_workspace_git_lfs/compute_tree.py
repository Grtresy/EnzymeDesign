"""Credential-free Gitless compute-tree preparation from an immutable revision."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import PublicationManifestObjectKind
from openzyme_contracts import PublishedRevision
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier

from .revision_backend import GitRevisionBackendError
from .revision_backend import LocalGitRevisionBackend


GITLESS_COMPUTE_TREE_RECEIPT_SCHEMA_VERSION = "gitless_compute_tree_receipt@1"


@dataclass(frozen=True, slots=True)
class GitlessComputeTreeRequest:
    """Adapter-private request; destination_root is never serialized publicly."""

    preparation_id: str
    binding: ProjectRepositoryBinding
    revision: PublishedRevision
    destination_root: Path
    max_total_bytes: int

    def __post_init__(self) -> None:
        require_identifier(self.preparation_id, field_name="preparation_id")
        if not self.destination_root.is_absolute():
            raise ValueError("Gitless compute destination must be absolute")
        if not 1 <= self.max_total_bytes <= 68_719_476_736:
            raise ValueError("max_total_bytes must be between 1 and 68719476736")


@dataclass(frozen=True, slots=True)
class GitlessComputeTreeReceipt:
    preparation_id: str
    repository_binding_id: str
    repository_binding_version: int
    repository_id: str
    publication_id: str
    commit: str
    tree: str
    publication_manifest_digest: str
    materialized_tree_digest: str
    file_count: int
    total_bytes: int
    lfs_oids: tuple[str, ...]
    created_at: str
    receipt_digest: str
    schema_version: str = GITLESS_COMPUTE_TREE_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != GITLESS_COMPUTE_TREE_RECEIPT_SCHEMA_VERSION:
            raise ValueError("unsupported Gitless compute-tree receipt schema")
        for field_name in (
            "preparation_id",
            "repository_binding_id",
            "repository_id",
            "publication_id",
            "created_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.repository_binding_version < 1:
            raise ValueError("repository binding version must be positive")
        if self.file_count < 1 or self.total_bytes < 0:
            raise ValueError("Gitless compute-tree size facts are invalid")
        for field_name in (
            "publication_manifest_digest",
            "materialized_tree_digest",
            "receipt_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if self.lfs_oids != tuple(sorted(set(self.lfs_oids))):
            raise ValueError("Gitless compute-tree LFS OIDs must be unique and sorted")
        for oid in self.lfs_oids:
            require_digest(oid, field_name="lfs_oid")
        if self.receipt_digest != canonical_sha256_digest(self.digest_payload()):
            raise ValueError("Gitless compute-tree receipt digest mismatch")

    def digest_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "preparation_id": self.preparation_id,
            "repository_binding_id": self.repository_binding_id,
            "repository_binding_version": self.repository_binding_version,
            "repository_id": self.repository_id,
            "publication_id": self.publication_id,
            "commit": self.commit,
            "tree": self.tree,
            "publication_manifest_digest": self.publication_manifest_digest,
            "materialized_tree_digest": self.materialized_tree_digest,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "lfs_oids": list(self.lfs_oids),
            "created_at": self.created_at,
        }

    @classmethod
    def create(cls, **values: object) -> GitlessComputeTreeReceipt:
        normalized = {
            **values,
            "lfs_oids": tuple(sorted(set(values["lfs_oids"]))),
        }
        provisional = cls(
            **normalized,  # type: ignore[arg-type]
            receipt_digest=canonical_sha256_digest(
                {
                    "schema_version": GITLESS_COMPUTE_TREE_RECEIPT_SCHEMA_VERSION,
                    **{
                        key: list(value) if key == "lfs_oids" else value
                        for key, value in normalized.items()
                    },
                }
            ),
        )
        return provisional

    def to_safe_dict(self) -> dict[str, object]:
        return {**self.digest_payload(), "receipt_digest": self.receipt_digest}


@dataclass(slots=True)
class LocalGitlessComputeTreePreparer:
    revision_backend: LocalGitRevisionBackend

    def prepare(self, request: GitlessComputeTreeRequest) -> GitlessComputeTreeReceipt:
        destination = request.destination_root
        if destination.exists():
            raise GitRevisionBackendError(
                "gitless_compute_destination_exists",
                "Gitless compute preparation requires an absent destination",
            )
        if not destination.parent.is_dir():
            raise GitRevisionBackendError(
                "gitless_compute_parent_missing",
                "Gitless compute destination parent is absent",
            )
        entries = self._verified_entries(request)
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".openzyme-{request.preparation_id}-",
                dir=destination.parent,
            )
        )
        try:
            observed = self._write_entries(request, entries, staging)
            os.replace(staging, destination)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
        return self._receipt(request, observed)

    def observe(
        self,
        request: GitlessComputeTreeRequest,
        receipt: GitlessComputeTreeReceipt,
    ) -> GitlessComputeTreeReceipt:
        """Reconcile exact destination bytes without fetching or materializing again."""

        self._require_receipt_identity(request, receipt)
        if not request.destination_root.is_dir():
            raise GitRevisionBackendError(
                "gitless_compute_tree_absent",
                "Gitless compute-tree reconciliation found no destination",
            )
        entries = self._verified_entries(request)
        observed = self._observe_entries(request, entries, request.destination_root)
        current = self._receipt(request, observed)
        if current.materialized_tree_digest != receipt.materialized_tree_digest:
            raise GitRevisionBackendError(
                "gitless_compute_tree_integrity_mismatch",
                "Gitless compute-tree bytes differ from the durable receipt",
            )
        return receipt

    def _verified_entries(self, request: GitlessComputeTreeRequest):  # noqa: ANN202
        binding = request.binding
        revision = request.revision
        if (
            revision.repository_binding_id != binding.binding_id
            or revision.repository_binding_version != binding.binding_version
            or revision.repository_id != binding.repository_id
        ):
            raise GitRevisionBackendError(
                "gitless_compute_binding_mismatch",
                "Published revision differs from the repository binding",
            )
        commit = self.revision_backend.observe_commit(binding, commit=revision.commit)
        manifest = self.revision_backend.observe_manifest(binding, commit=revision.commit)
        if (
            commit.tree != revision.tree
            or manifest.manifest.manifest_digest != revision.manifest.manifest_digest
        ):
            raise GitRevisionBackendError(
                "gitless_compute_revision_drift",
                "Published revision commit/tree/manifest could not be reproduced",
            )
        location = self.revision_backend._locator.resolve(binding)  # noqa: SLF001
        entries = self.revision_backend._list_tree(  # noqa: SLF001
            location,
            revision.commit,
            recursive=True,
        )
        if len(entries) != len(revision.manifest.entries):
            raise GitRevisionBackendError(
                "gitless_compute_manifest_closure_mismatch",
                "Git tree entry count differs from the published manifest",
            )
        return entries

    def _write_entries(self, request, entries, root):  # noqa: ANN001, ANN202
        location = self.revision_backend._locator.resolve(request.binding)  # noqa: SLF001
        observed: list[dict[str, object]] = []
        total = 0
        lfs_oids: set[str] = set()
        expected = {entry.path: entry for entry in request.revision.manifest.entries}
        for entry in entries:
            declared = expected.get(entry.path)
            if (
                declared is None
                or declared.object_kind is PublicationManifestObjectKind.COMMIT
                or entry.object_kind != "blob"
                or entry.mode not in {"100644", "100755"}
                or declared.object_id != entry.object_id
                or declared.mode != entry.mode
            ):
                raise GitRevisionBackendError(
                    "gitless_compute_entry_unsupported",
                    "Gitless compute trees allow only exact regular published files",
                )
            content, pointer = self.revision_backend._entry_content(location, entry)  # noqa: SLF001
            if pointer is None:
                if declared.lfs_oid is not None or declared.lfs_size_bytes is not None:
                    raise GitRevisionBackendError(
                        "gitless_compute_lfs_identity_mismatch",
                        "Published LFS identity differs from materialized bytes",
                    )
            else:
                expected_oid = f"sha256:{pointer.oid}"
                if declared.lfs_oid != expected_oid or declared.lfs_size_bytes != pointer.size:
                    raise GitRevisionBackendError(
                        "gitless_compute_lfs_identity_mismatch",
                        "Published LFS identity differs from materialized bytes",
                    )
                lfs_oids.add(expected_oid)
            total += len(content)
            if total > request.max_total_bytes:
                raise GitRevisionBackendError(
                    "gitless_compute_tree_budget_exceeded",
                    "Gitless compute tree exceeds its frozen byte budget",
                )
            path = root.joinpath(*entry.path.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("xb") as handle:
                    handle.write(content)
            except (FileExistsError, IsADirectoryError) as exc:
                raise GitRevisionBackendError(
                    "gitless_compute_path_collision",
                    "Published paths collide during Gitless materialization",
                ) from exc
            os.chmod(path, 0o755 if entry.mode == "100755" else 0o644)
            observed.append(self._file_fact(entry.path, entry.mode, content))
        return observed, total, tuple(sorted(lfs_oids))

    def _observe_entries(self, request, entries, root):  # noqa: ANN001, ANN202
        expected = {entry.path: entry for entry in entries}
        observed_paths = tuple(
            sorted(
                path.relative_to(root).as_posix()
                for path in root.rglob("*")
                if path.is_file()
            )
        )
        if observed_paths != tuple(sorted(expected)) or (root / ".git").exists():
            raise GitRevisionBackendError(
                "gitless_compute_tree_closure_mismatch",
                "Gitless compute tree has missing, extra, or Git metadata paths",
            )
        observed: list[dict[str, object]] = []
        total = 0
        lfs_oids: set[str] = set()
        declared = {entry.path: entry for entry in request.revision.manifest.entries}
        for path_name in observed_paths:
            entry = expected[path_name]
            content = root.joinpath(*path_name.split("/")).read_bytes()
            total += len(content)
            published = declared[path_name]
            if published.lfs_oid is not None:
                lfs_oids.add(published.lfs_oid)
                if (
                    published.lfs_size_bytes != len(content)
                    or "sha256:" + hashlib.sha256(content).hexdigest()
                    != published.lfs_oid
                ):
                    raise GitRevisionBackendError(
                        "gitless_compute_lfs_identity_mismatch",
                        "Gitless LFS bytes failed published size/digest verification",
                    )
            observed.append(self._file_fact(path_name, entry.mode, content))
        if total > request.max_total_bytes:
            raise GitRevisionBackendError(
                "gitless_compute_tree_budget_exceeded",
                "Observed Gitless compute tree exceeds its frozen byte budget",
            )
        return observed, total, tuple(sorted(lfs_oids))

    def _receipt(self, request, observed):  # noqa: ANN001, ANN202
        files, total, lfs_oids = observed
        return GitlessComputeTreeReceipt.create(
            preparation_id=request.preparation_id,
            repository_binding_id=request.binding.binding_id,
            repository_binding_version=request.binding.binding_version,
            repository_id=request.binding.repository_id,
            publication_id=request.revision.publication_id,
            commit=request.revision.commit,
            tree=request.revision.tree,
            publication_manifest_digest=request.revision.manifest.manifest_digest,
            materialized_tree_digest=canonical_sha256_digest(
                {
                    "commit": request.revision.commit,
                    "tree": request.revision.tree,
                    "files": files,
                }
            ),
            file_count=len(files),
            total_bytes=total,
            lfs_oids=lfs_oids,
            created_at=self.revision_backend._now(),  # noqa: SLF001
        )

    @staticmethod
    def _file_fact(path: str, mode: str, content: bytes) -> dict[str, object]:
        return {
            "path": path,
            "mode": mode,
            "size_bytes": len(content),
            "content_digest": "sha256:" + hashlib.sha256(content).hexdigest(),
        }

    @staticmethod
    def _require_receipt_identity(
        request: GitlessComputeTreeRequest,
        receipt: GitlessComputeTreeReceipt,
    ) -> None:
        if (
            receipt.preparation_id != request.preparation_id
            or receipt.repository_binding_id != request.binding.binding_id
            or receipt.repository_binding_version != request.binding.binding_version
            or receipt.repository_id != request.binding.repository_id
            or receipt.publication_id != request.revision.publication_id
            or receipt.commit != request.revision.commit
            or receipt.tree != request.revision.tree
            or receipt.publication_manifest_digest
            != request.revision.manifest.manifest_digest
        ):
            raise GitRevisionBackendError(
                "gitless_compute_receipt_identity_mismatch",
                "Gitless compute-tree receipt belongs to another request",
            )


__all__ = [
    "GITLESS_COMPUTE_TREE_RECEIPT_SCHEMA_VERSION",
    "GitlessComputeTreeReceipt",
    "GitlessComputeTreeRequest",
    "LocalGitlessComputeTreePreparer",
]
