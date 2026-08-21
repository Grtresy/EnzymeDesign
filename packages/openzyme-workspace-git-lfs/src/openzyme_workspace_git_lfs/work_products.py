from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
import fnmatch
import hashlib
from pathlib import PurePosixPath
import shlex
from typing import ContextManager
from typing import Protocol

from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import PublicationManifestEntry
from openzyme_contracts import PublicationManifestObjectKind
from openzyme_contracts import WorkspacePublicationManifest

from .lfs import GitLfsBindingPolicy
from .lfs import GitLfsClosureEntry
from .lfs import GitLfsClosureManifest
from .lfs import GitLfsClosureVerification
from .lfs import GitLfsGcCandidateReceipt
from .lfs import GitLfsObjectReadReceipt
from .lfs import GitLfsPathRepresentation
from .lfs import GitLfsPointer
from .lfs import GitLfsPrivateReachabilityReceipt
from .lfs import canonical_lfs_digest
from .repository_storage import DurableLfsObjectStore
from .repository_storage import LfsObjectMismatchError
from .repository_storage import RepositoryStorageError
from .sqlite_lfs_repository import GitLfsPolicyError
from .sqlite_lfs_repository import GitLfsRepository
from .sqlite_lfs_repository import GitLfsRepositoryError


class GitLfsWorkProductError(RuntimeError):
    error_code = "git_lfs_work_product_rejected"


class GitLfsPointerError(GitLfsWorkProductError):
    error_code = "git_lfs_pointer_invalid"


class GitLfsClosureError(GitLfsWorkProductError):
    error_code = "git_lfs_closure_invalid"


class GitLfsOversizedBlobError(GitLfsWorkProductError):
    error_code = "git_lfs_oversized_ordinary_blob"

    def __init__(self, violations: tuple[dict[str, object], ...]) -> None:
        self.violations = violations
        paths = ", ".join(str(item["path"]) for item in violations)
        super().__init__(f"oversized ordinary Git blobs: {paths}")


class GitLfsGitReader(Protocol):
    def read_blob(
        self,
        binding: ProjectRepositoryBinding,
        *,
        object_id: str,
        max_bytes: int,
    ) -> bytes: ...


class GitLfsRevisionReader(GitLfsGitReader, Protocol):
    def read_commit_tree(
        self,
        binding: ProjectRepositoryBinding,
        *,
        commit: str,
    ) -> str: ...

    def read_whole_tree_manifest(
        self,
        binding: ProjectRepositoryBinding,
        *,
        commit: str,
    ) -> WorkspacePublicationManifest: ...


class ProjectRepositoryBindingReader(Protocol):
    def get(self, binding_id: str) -> ProjectRepositoryBinding | None: ...


class GitLfsRepositoryBundle(Protocol):
    """Narrow UoW-owned view required by LFS retention mechanisms."""

    git_lfs: GitLfsRepository
    project_repository_bindings: ProjectRepositoryBindingReader

    def atomic(self, *, prefix: str) -> ContextManager[None]: ...


@dataclass(frozen=True, slots=True)
class PublicationManifestValidation:
    manifest: WorkspacePublicationManifest
    lfs_closure: GitLfsClosureManifest | None
    lfs_verification: GitLfsClosureVerification | None


@dataclass(frozen=True, slots=True)
class _AttributesRule:
    base_directory: str
    pattern: str
    filter_value: str | None

    def matches(self, path: str) -> bool:
        if self.base_directory:
            prefix = f"{self.base_directory}/"
            if not path.startswith(prefix):
                return False
            relative = path[len(prefix) :]
        else:
            relative = path
        if "/" in self.pattern:
            return fnmatch.fnmatchcase(relative, self.pattern)
        return fnmatch.fnmatchcase(PurePosixPath(relative).name, self.pattern)


@dataclass(frozen=True, slots=True)
class RevisionGitAttributes:
    rules: tuple[_AttributesRule, ...]

    @classmethod
    def read(
        cls,
        *,
        binding: ProjectRepositoryBinding,
        manifest: WorkspacePublicationManifest,
        git_reader: GitLfsGitReader,
    ) -> RevisionGitAttributes:
        rules: list[_AttributesRule] = []
        attribute_entries = tuple(
            entry
            for entry in manifest.entries
            if entry.path == ".gitattributes" or entry.path.endswith("/.gitattributes")
        )
        for entry in attribute_entries:
            if (
                entry.object_kind is not PublicationManifestObjectKind.BLOB
                or entry.mode not in {"100644", "100755"}
            ):
                raise GitLfsClosureError(
                    f"{entry.path} must be a regular Git blob"
                )
            try:
                value = git_reader.read_blob(
                    binding,
                    object_id=entry.object_id,
                    max_bytes=1024 * 1024,
                )
            except (FileNotFoundError, RepositoryStorageError) as exc:
                raise GitLfsClosureError(
                    f"cannot read revision attributes at {entry.path}"
                ) from exc
            rules.extend(_parse_attributes_file(entry.path, value))
        return cls(tuple(rules))

    def filter_for(self, path: str) -> str | None:
        value: str | None = None
        for rule in self.rules:
            if rule.matches(path):
                value = rule.filter_value
        return value


@dataclass(slots=True)
class GitLfsPublicationManifestPolicyValidator:
    repositories: GitLfsRepository
    git_reader: GitLfsGitReader
    object_store: DurableLfsObjectStore

    def validate(
        self,
        *,
        binding: ProjectRepositoryBinding,
        commit: str,
        tree: str,
        manifest: WorkspacePublicationManifest,
        authorization_scope_digest: str,
    ) -> PublicationManifestValidation:
        policy = self.repositories.get_policy(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
        )
        if policy is None:
            raise GitLfsPolicyError(
                "publication binding has no exact versioned Git LFS policy"
            )
        _require_policy_matches_binding(policy, binding)
        attributes = RevisionGitAttributes.read(
            binding=binding,
            manifest=manifest,
            git_reader=self.git_reader,
        )
        endpoint_identity = canonical_lfs_digest(
            {
                "lfs_service_id": policy.lfs_service_id,
                "lfs_endpoint": policy.lfs_endpoint,
                "binding_id": policy.binding_id,
                "binding_version": policy.binding_version,
            }
        )
        now = datetime.now(tz=UTC).isoformat()
        closure_entries: list[GitLfsClosureEntry] = []
        enriched_entries: list[PublicationManifestEntry] = []
        violations: list[dict[str, object]] = []
        for entry in manifest.entries:
            if entry.object_kind is PublicationManifestObjectKind.COMMIT:
                if policy.rule_for_path(entry.path) is not None:
                    raise GitLfsClosureError(
                        f"submodule path {entry.path} cannot satisfy an LFS path rule"
                    )
                enriched_entries.append(entry)
                continue
            rule = policy.rule_for_path(entry.path)
            observed_filter = attributes.filter_for(entry.path)
            if entry.mode == "120000":
                if rule is not None or observed_filter == "lfs":
                    raise GitLfsClosureError(
                        f"symlink path {entry.path} cannot be represented by Git LFS"
                    )
                enriched_entries.append(entry)
                continue
            is_lfs = observed_filter == "lfs"
            if (
                rule is not None
                and rule.representation is GitLfsPathRepresentation.LFS_REQUIRED
                and not is_lfs
            ):
                raise GitLfsClosureError(
                    f"{entry.path} must be represented by a standard Git LFS pointer "
                    f"under rule {rule.rule_id}"
                )
            if is_lfs:
                try:
                    pointer_bytes = self.git_reader.read_blob(
                        binding,
                        object_id=entry.object_id,
                        max_bytes=1024,
                    )
                except (FileNotFoundError, RepositoryStorageError) as exc:
                    raise GitLfsClosureError(
                        f"Git LFS pointer blob is unreadable at {entry.path}"
                    ) from exc
                try:
                    pointer = GitLfsPointer.parse(pointer_bytes)
                except ValueError as exc:
                    raise GitLfsPointerError(
                        f"invalid Git LFS pointer at {entry.path}: {exc}"
                    ) from exc
                if pointer.size > policy.max_object_bytes:
                    raise GitLfsClosureError(
                        f"Git LFS object at {entry.path} exceeds the pinned object quota"
                    )
                if not self.repositories.has_object_metadata(
                    policy=policy,
                    oid=pointer.oid,
                    size_bytes=pointer.size,
                ):
                    raise GitLfsClosureError(
                        f"Git LFS object metadata is missing for {entry.path}"
                    )
                try:
                    self.object_store.verify(
                        binding.repository_id,
                        pointer.oid,
                        size=pointer.size,
                    )
                except (FileNotFoundError, LfsObjectMismatchError, RepositoryStorageError) as exc:
                    raise GitLfsClosureError(
                        f"Git LFS object is unreadable or corrupt at {entry.path}"
                    ) from exc
                receipt_id = _stable_id(
                    "lfs_read",
                    binding.binding_id,
                    str(binding.binding_version),
                    commit,
                    entry.path,
                    pointer.oid,
                    authorization_scope_digest,
                    now,
                )
                receipt = GitLfsObjectReadReceipt.create(
                    receipt_id=receipt_id,
                    binding_id=binding.binding_id,
                    binding_version=binding.binding_version,
                    repository_id=binding.repository_id,
                    lfs_endpoint_identity=endpoint_identity,
                    authorization_scope_digest=authorization_scope_digest,
                    oid=pointer.oid,
                    declared_size=pointer.size,
                    observed_size=pointer.size,
                    observed_sha256=pointer.oid,
                    observed_at=now,
                )
                self.repositories.add_object_read_receipt(receipt)
                closure_entries.append(
                    GitLfsClosureEntry(
                        path=entry.path,
                        mode=entry.mode,
                        pointer_blob_oid=entry.object_id,
                        lfs_oid=pointer.oid,
                        size_bytes=pointer.size,
                        object_read_receipt_id=receipt.receipt_id,
                    )
                )
                enriched_entries.append(
                    PublicationManifestEntry(
                        path=entry.path,
                        mode=entry.mode,
                        object_kind=entry.object_kind,
                        object_id=entry.object_id,
                        size_bytes=entry.size_bytes,
                        lfs_oid=f"sha256:{pointer.oid}",
                        lfs_size_bytes=pointer.size,
                    )
                )
                continue
            if (
                entry.size_bytes is not None
                and entry.size_bytes > policy.ordinary_blob_threshold_bytes
            ):
                violations.append(
                    {
                        "path": entry.path,
                        "blob_oid": entry.object_id,
                        "observed_size": entry.size_bytes,
                        "threshold": policy.ordinary_blob_threshold_bytes,
                        "rule": (
                            "ordinary_blob_threshold"
                            if rule is None
                            else rule.rule_id
                        ),
                    }
                )
            enriched_entries.append(entry)
        if violations:
            raise GitLfsOversizedBlobError(
                tuple(sorted(violations, key=lambda item: str(item["path"])))
            )
        candidate = GitLfsClosureManifest.create(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            commit=commit,
            tree=tree,
            policy_digest=policy.policy_digest,
            lfs_endpoint_identity=endpoint_identity,
            authorization_scope_digest=authorization_scope_digest,
            entries=tuple(closure_entries),
            verified_at=now,
        )
        cached = self.repositories.get_cached_closure(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            commit=commit,
            tree=tree,
            policy_digest=policy.policy_digest,
            lfs_endpoint_identity=endpoint_identity,
            authorization_scope_digest=authorization_scope_digest,
        )
        closure = candidate if cached is None else cached
        if cached is None:
            self.repositories.add_closure_manifest(candidate)
        elif cached.manifest_digest != candidate.manifest_digest:
            raise GitLfsClosureError(
                "fresh Git LFS closure differs from the exact cached identity"
            )
        verification = GitLfsClosureVerification.create(
            verification_id=_stable_id(
                "lfs_closure_verification",
                candidate.manifest_digest,
                authorization_scope_digest,
                now,
            ),
            manifest_digest=candidate.manifest_digest,
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            authorization_scope_digest=authorization_scope_digest,
            object_read_receipt_ids=tuple(
                entry.object_read_receipt_id for entry in candidate.entries
            ),
            observed_at=now,
        )
        self.repositories.add_closure_verification(
            verification,
            observed_closure=candidate,
        )
        return PublicationManifestValidation(
            manifest=WorkspacePublicationManifest.create(tuple(enriched_entries)),
            lfs_closure=closure,
            lfs_verification=verification,
        )


@dataclass(slots=True)
class GitLfsGarbageCollector:
    repositories: GitLfsRepositoryBundle
    object_store: DurableLfsObjectStore

    def dry_run(
        self,
        *,
        binding_id: str,
        binding_version: int,
        created_at: str | None = None,
    ) -> GitLfsGcCandidateReceipt:
        policy = self.repositories.git_lfs.get_policy(
            binding_id=binding_id,
            binding_version=binding_version,
        )
        if policy is None:
            raise GitLfsPolicyError("GC requires an exact immutable Git LFS policy")
        observed_at = created_at or datetime.now(tz=UTC).isoformat()
        receipt = self.repositories.git_lfs.compute_gc_candidate(
            policy=policy,
            receipt_id=_stable_id(
                "lfs_gc_candidate",
                binding_id,
                str(binding_version),
                observed_at,
            ),
            created_at=observed_at,
        )
        return self.repositories.git_lfs.add_gc_candidate(receipt)

    def delete_exact_candidates(
        self,
        *,
        candidate_receipt_id: str,
        expected_receipt_digest: str,
        created_by: str,
        observed_at: str | None = None,
    ) -> str:
        candidate = self.repositories.git_lfs.get_gc_candidate(candidate_receipt_id)
        if candidate is None or candidate.receipt_digest != expected_receipt_digest:
            raise GitLfsRepositoryError(
                "GC delete requires the exact prior dry-run candidate receipt"
            )
        policy = self.repositories.git_lfs.get_policy(
            binding_id=candidate.binding_id,
            binding_version=candidate.binding_version,
        )
        if policy is None or policy.policy_digest != candidate.policy_digest:
            raise GitLfsPolicyError("GC policy changed after the dry-run receipt")
        now = observed_at or datetime.now(tz=UTC).isoformat()
        revalidated = self.repositories.git_lfs.compute_gc_candidate(
            policy=policy,
            receipt_id=_stable_id(
                "lfs_gc_revalidation",
                candidate.receipt_id,
                now,
            ),
            created_at=now,
        )
        if (
            revalidated.candidate_oids != candidate.candidate_oids
            or revalidated.reachability_digest != candidate.reachability_digest
            or revalidated.retirement_receipts_digest
            != candidate.retirement_receipts_digest
            or revalidated.policy_digest != candidate.policy_digest
        ):
            raise GitLfsRepositoryError(
                "Git LFS reachability, retirement, policy, or candidate set drifted; "
                "the whole GC batch was stopped"
            )
        exact_revalidation_digest = canonical_lfs_digest(
            {
                "candidate_receipt_digest": candidate.receipt_digest,
                "candidate_oids": list(candidate.candidate_oids),
                "reachability_digest": revalidated.reachability_digest,
                "retirement_receipts_digest": (
                    revalidated.retirement_receipts_digest
                ),
                "policy_digest": revalidated.policy_digest,
            }
        )
        deletion_receipt_id = _stable_id(
            "lfs_gc_deletion",
            candidate.receipt_id,
            expected_receipt_digest,
        )
        with self.repositories.atomic(prefix="git_lfs_gc_delete"):
            for oid in candidate.candidate_oids:
                size = self.repositories.git_lfs.object_size_for_gc(
                    binding_id=candidate.binding_id,
                    binding_version=candidate.binding_version,
                    oid=oid,
                )
                path = self.object_store.object_path(candidate.repository_id, oid)
                if path.is_file():
                    self.object_store.delete_exact(
                        candidate.repository_id,
                        oid,
                        size=size,
                    )
                elif path.exists():
                    raise GitLfsRepositoryError(
                        "GC candidate storage identity is not a regular file"
                    )
            return self.repositories.git_lfs.record_gc_deletion(
                candidate=candidate,
                deletion_receipt_id=deletion_receipt_id,
                exact_revalidation_digest=exact_revalidation_digest,
                deleted_at=now,
                created_by=created_by,
            )


@dataclass(slots=True)
class GitLfsPrivateReachabilityFinalizer:
    repositories: GitLfsRepositoryBundle
    git_reader: GitLfsRevisionReader
    object_store: DurableLfsObjectStore

    def finalize(
        self,
        *,
        namespace_id: str,
        created_at: str | None = None,
    ) -> GitLfsPrivateReachabilityReceipt:
        existing = self.repositories.git_lfs.get_private_reachability_receipt(
            namespace_id
        )
        if existing is not None:
            return existing
        scope = self.repositories.git_lfs.private_namespace_retirement_scope(
            namespace_id
        )
        binding = self.repositories.project_repository_bindings.get(
            str(scope["binding_id"])
        )
        if (
            binding is None
            or binding.binding_version != scope["binding_version"]
            or binding.repository_id != scope["repository_id"]
        ):
            raise GitLfsPolicyError(
                "private reachability scope differs from its repository binding"
            )
        policy = self.repositories.git_lfs.get_policy(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
        )
        if policy is None:
            raise GitLfsPolicyError(
                "private reachability requires the exact immutable LFS policy"
            )
        _require_policy_matches_binding(policy, binding)
        terminal_commits = scope["terminal_commits"]
        if not isinstance(terminal_commits, list) or not all(
            isinstance(commit, str) for commit in terminal_commits
        ):
            raise GitLfsClosureError(
                "private retirement receipt has invalid terminal commits"
            )
        reachable_oids: set[str] = set()
        for commit in terminal_commits:
            expected_tree = self.git_reader.read_commit_tree(binding, commit=commit)
            manifest = self.git_reader.read_whole_tree_manifest(
                binding,
                commit=commit,
            )
            attributes = RevisionGitAttributes.read(
                binding=binding,
                manifest=manifest,
                git_reader=self.git_reader,
            )
            for entry in manifest.entries:
                if entry.object_kind is PublicationManifestObjectKind.COMMIT:
                    if policy.rule_for_path(entry.path) is not None:
                        raise GitLfsClosureError(
                            f"private submodule {entry.path} violates LFS policy"
                        )
                    continue
                rule = policy.rule_for_path(entry.path)
                observed_filter = attributes.filter_for(entry.path)
                if entry.mode == "120000":
                    if rule is not None or observed_filter == "lfs":
                        raise GitLfsClosureError(
                            f"private symlink {entry.path} violates LFS policy"
                        )
                    continue
                is_lfs = observed_filter == "lfs"
                if (
                    rule is not None
                    and rule.representation
                    is GitLfsPathRepresentation.LFS_REQUIRED
                    and not is_lfs
                ):
                    raise GitLfsClosureError(
                        f"private path {entry.path} is not represented by LFS"
                    )
                if not is_lfs:
                    continue
                pointer = GitLfsPointer.parse(
                    self.git_reader.read_blob(
                        binding,
                        object_id=entry.object_id,
                        max_bytes=1024,
                    )
                )
                if not self.repositories.git_lfs.has_object_metadata(
                    policy=policy,
                    oid=pointer.oid,
                    size_bytes=pointer.size,
                ):
                    raise GitLfsClosureError(
                        f"private LFS object metadata is missing for {entry.path}"
                    )
                self.object_store.verify(
                    binding.repository_id,
                    pointer.oid,
                    size=pointer.size,
                )
                reachable_oids.add(pointer.oid)
            if expected_tree != self.git_reader.read_commit_tree(
                binding,
                commit=commit,
            ):
                raise GitLfsClosureError(
                    "private terminal commit tree changed during reachability scan"
                )
        now = created_at or datetime.now(tz=UTC).isoformat()
        terminal_refs = scope["terminal_refs"]
        if not isinstance(terminal_refs, list):
            raise GitLfsClosureError(
                "private retirement receipt has invalid terminal refs"
            )
        receipt = GitLfsPrivateReachabilityReceipt.create(
            receipt_id=_stable_id(
                "lfs_private_reachability",
                namespace_id,
                str(scope["retirement_receipt_id"]),
            ),
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            namespace_id=namespace_id,
            workspace_generation=int(scope["workspace_generation"]),
            terminal_refs_digest=canonical_lfs_digest({"items": terminal_refs}),
            terminal_commits_digest=canonical_lfs_digest(
                {"items": terminal_commits}
            ),
            reachable_oids=tuple(reachable_oids),
            retirement_receipt_id=str(scope["retirement_receipt_id"]),
            created_at=now,
        )
        return self.repositories.git_lfs.add_private_reachability_receipt(receipt)


def publication_authorization_scope_digest(
    *,
    binding_id: str,
    binding_version: int,
    session_id: str,
    agent_member_id: str,
    workspace_generation: int,
    capability_lease_id: str,
) -> str:
    return canonical_lfs_digest(
        {
            "binding_id": binding_id,
            "binding_version": binding_version,
            "session_id": session_id,
            "agent_member_id": agent_member_id,
            "workspace_generation": workspace_generation,
            "capability_lease_id": capability_lease_id,
            "authority": "publication_lfs_closure_read",
        }
    )


def _require_policy_matches_binding(
    policy: GitLfsBindingPolicy,
    binding: ProjectRepositoryBinding,
) -> None:
    if (
        policy.binding_id != binding.binding_id
        or policy.binding_version != binding.binding_version
        or policy.repository_id != binding.repository_id
        or policy.lfs_service_id != binding.lfs_service_id
        or policy.lfs_endpoint != binding.lfs_endpoint
        or policy.policy_version != binding.repository_policy_version
        or policy.policy_digest != binding.repository_policy_digest
    ):
        raise GitLfsPolicyError(
            "Git LFS policy differs from the immutable project repository binding"
        )


def _parse_attributes_file(
    repository_path: str,
    value: bytes,
) -> tuple[_AttributesRule, ...]:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GitLfsClosureError(
            f"{repository_path} must be UTF-8 for deterministic publication validation"
        ) from exc
    base_directory = str(PurePosixPath(repository_path).parent)
    if base_directory == ".":
        base_directory = ""
    rules: list[_AttributesRule] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            fields = shlex.split(stripped, posix=True)
        except ValueError as exc:
            raise GitLfsClosureError(
                f"{repository_path}:{line_number} has invalid attribute syntax"
            ) from exc
        if len(fields) < 2:
            raise GitLfsClosureError(
                f"{repository_path}:{line_number} has no attribute assignment"
            )
        pattern, *attributes = fields
        if (
            pattern.startswith(("/", "!"))
            or pattern.endswith("/")
            or "\\" in pattern
            or ".." in pattern.split("/")
        ):
            raise GitLfsClosureError(
                f"{repository_path}:{line_number} uses an unsupported path pattern"
            )
        filter_values = tuple(
            attribute
            for attribute in attributes
            if attribute == "filter"
            or attribute == "-filter"
            or attribute == "!filter"
            or attribute.startswith("filter=")
        )
        if not filter_values:
            continue
        if len(filter_values) != 1:
            raise GitLfsClosureError(
                f"{repository_path}:{line_number} assigns filter more than once"
            )
        raw_filter = filter_values[0]
        filter_value = "lfs" if raw_filter == "filter=lfs" else None
        if raw_filter.startswith("filter=") and raw_filter != "filter=lfs":
            raise GitLfsClosureError(
                f"{repository_path}:{line_number} uses an unsupported clean filter"
            )
        rules.append(
            _AttributesRule(
                base_directory=base_directory,
                pattern=pattern,
                filter_value=filter_value,
            )
        )
    return tuple(rules)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:32]}"


__all__ = [
    "GitLfsClosureError",
    "GitLfsGitReader",
    "GitLfsGarbageCollector",
    "GitLfsOversizedBlobError",
    "GitLfsPointerError",
    "GitLfsPublicationManifestPolicyValidator",
    "GitLfsPrivateReachabilityFinalizer",
    "GitLfsRevisionReader",
    "GitLfsWorkProductError",
    "PublicationManifestValidation",
    "RevisionGitAttributes",
    "publication_authorization_scope_digest",
]
