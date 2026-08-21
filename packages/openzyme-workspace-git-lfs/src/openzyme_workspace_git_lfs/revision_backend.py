"""Local Git/LFS implementation of the Git-shaped revision backend Port.

Repository and LFS roots are Adapter-private configuration.  All subprocesses use
exact argv and no shell; returned contracts never contain a filesystem locator.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import subprocess

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import PrivateRefAdvanceKind
from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import PublicationNamespaceObservation
from openzyme_contracts import PublicationManifestEntry
from openzyme_contracts import PublicationManifestObjectKind
from openzyme_contracts import PublishedRevision
from openzyme_contracts import RemotePrivateRefObservation
from openzyme_contracts import RevisionCommitObservation
from openzyme_contracts import RevisionManifestObservation
from openzyme_contracts import RevisionPathEntryKind
from openzyme_contracts import RevisionPathReadReceipt
from openzyme_contracts import RevisionPathReadRequest
from openzyme_contracts import RevisionPathRef
from openzyme_contracts import RevisionPathVerificationReceipt
from openzyme_contracts import WorkspaceCheckpointProofInput
from openzyme_contracts import WorkspacePublicationDispatchIdentity
from openzyme_contracts import WorkspacePublicationIntent
from openzyme_contracts import WorkspacePublicationManifest
from openzyme_contracts import WorkspacePublicationRemoteReceipt

from .lfs import GIT_LFS_POINTER_VERSION, GitLfsPointer


_ZERO_SHA1 = "0" * 40
_ZERO_SHA256 = "0" * 64
_MAX_GIT_STDERR_BYTES = 4096


class GitRevisionBackendError(RuntimeError):
    """Typed, fail-closed Adapter failure with explicit effect semantics."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        effect_certainty: ExternalEffectCertainty = ExternalEffectCertainty.NO_EFFECT,
        mutation_applied: bool = False,
        retry_allowed: bool = False,
        private_detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.effect_certainty = effect_certainty
        self.mutation_applied = mutation_applied
        self.fallback_performed = False
        self.retry_allowed = retry_allowed
        self.private_detail = private_detail


@dataclass(frozen=True, slots=True)
class GitRepositoryLocation:
    """Adapter-private physical location for one logical repository."""

    repository_id: str
    bare_repository_root: Path
    lfs_object_root: Path | None = None

    def __post_init__(self) -> None:
        if not self.repository_id or any(char.isspace() for char in self.repository_id):
            raise ValueError("repository_id must be an exact identifier")
        if not self.bare_repository_root.is_absolute():
            raise ValueError("bare_repository_root must be absolute")
        if self.lfs_object_root is not None and not self.lfs_object_root.is_absolute():
            raise ValueError("lfs_object_root must be absolute")


class GitRepositoryLocator:
    """Explicit repository-id map; endpoints and caller paths are never locators."""

    def __init__(self, locations: tuple[GitRepositoryLocation, ...]) -> None:
        self._locations = {item.repository_id: item for item in locations}
        if len(self._locations) != len(locations):
            raise ValueError("repository locations must have unique repository ids")

    def resolve(self, binding: ProjectRepositoryBinding) -> GitRepositoryLocation:
        location = self._locations.get(binding.repository_id)
        if location is None:
            raise GitRevisionBackendError(
                "git_repository_not_configured",
                "The pinned repository has no configured Git Adapter location",
            )
        root = location.bare_repository_root
        if not root.is_dir() or not (root / "HEAD").is_file():
            raise GitRevisionBackendError(
                "git_repository_not_ready",
                "The configured Git repository is not a ready bare repository",
            )
        return location


@dataclass(frozen=True, slots=True)
class _TreeEntry:
    path: str
    mode: str
    object_kind: str
    object_id: str
    size_bytes: int | None


class LocalGitRevisionBackend:
    """Git CLI and filesystem-backed LFS Adapter for a local repository service."""

    def __init__(
        self,
        *,
        locator: GitRepositoryLocator,
        now: Callable[[], str] | None = None,
    ) -> None:
        self._locator = locator
        self._now = now or (lambda: datetime.now(UTC).isoformat())

    def observe_private_ref(
        self,
        binding: ProjectRepositoryBinding,
        proof: WorkspaceCheckpointProofInput,
    ) -> RemotePrivateRefObservation:
        self._require_binding(proof.repository_binding_id, proof.repository_binding_version, binding)
        location = self._locator.resolve(binding)
        observed = self._rev_parse(location, proof.private_ref)
        if observed != proof.commit:
            raise GitRevisionBackendError(
                "private_ref_commit_mismatch",
                "The private ref no longer names the checkpoint commit",
            )
        prior = proof.remote_observation.prior_commit
        advance = proof.remote_observation.advance_kind
        if advance is PrivateRefAdvanceKind.CREATE:
            if prior is not None:
                raise GitRevisionBackendError(
                    "private_ref_observation_invalid",
                    "A create observation cannot contain a prior commit",
                )
        else:
            if prior is None or not self._is_ancestor(location, prior, observed):
                raise GitRevisionBackendError(
                    "private_ref_not_fast_forward",
                    "The private ref advance is not the declared fast-forward",
                )
        # The caller's observation is the frozen proof identity.  The Adapter
        # verifies it against Git but does not replace its timestamp or mint a
        # second competing receipt.
        return proof.remote_observation

    def observe_commit(
        self,
        binding: ProjectRepositoryBinding,
        *,
        commit: str,
    ) -> RevisionCommitObservation:
        location = self._locator.resolve(binding)
        output = self._git(location, "show", "-s", "--format=%T%n%P", commit)
        lines = output.decode("ascii").splitlines()
        if not lines:
            raise GitRevisionBackendError(
                "git_commit_observation_invalid",
                "Git did not return a commit tree observation",
            )
        return RevisionCommitObservation.create(
            repository_binding_id=binding.binding_id,
            repository_binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            commit=commit,
            tree=lines[0],
            parent_commits=tuple(lines[1].split()) if len(lines) > 1 else (),
            observed_at=self._now(),
        )

    def observe_manifest(
        self,
        binding: ProjectRepositoryBinding,
        *,
        commit: str,
    ) -> RevisionManifestObservation:
        location = self._locator.resolve(binding)
        commit_observation = self.observe_commit(binding, commit=commit)
        entries = tuple(
            self._publication_entry(location, item)
            for item in self._list_tree(location, commit, recursive=True)
        )
        if not entries:
            raise GitRevisionBackendError(
                "git_publication_tree_empty",
                "An empty Git tree cannot be published",
            )
        manifest = WorkspacePublicationManifest.create(entries)
        return RevisionManifestObservation.create(
            repository_binding_id=binding.binding_id,
            repository_binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            commit=commit,
            tree=commit_observation.tree,
            manifest=manifest,
            observed_at=self._now(),
        )

    def dispatch_publication(
        self,
        binding: ProjectRepositoryBinding,
        intent: WorkspacePublicationIntent,
        dispatch: WorkspacePublicationDispatchIdentity,
    ) -> WorkspacePublicationRemoteReceipt:
        self._require_intent_binding(binding, intent)
        location = self._locator.resolve(binding)
        commit = self.observe_commit(binding, commit=intent.expected_head_commit)
        manifest = self.observe_manifest(binding, commit=intent.expected_head_commit)
        if commit.tree != intent.expected_tree or manifest.manifest != intent.manifest:
            raise GitRevisionBackendError(
                "publication_source_identity_mismatch",
                "The exact commit/tree/manifest differs from the frozen publication intent",
            )
        if self._optional_rev_parse(location, intent.publication_ref) is not None:
            raise GitRevisionBackendError(
                "publication_ref_integrity_conflict",
                "The immutable publication ref already exists",
            )
        zero = _ZERO_SHA256 if len(intent.expected_head_commit) == 64 else _ZERO_SHA1
        try:
            self._git(
                location,
                "update-ref",
                intent.publication_ref,
                intent.expected_head_commit,
                zero,
            )
        except GitRevisionBackendError as exc:
            observed = self._optional_rev_parse(location, intent.publication_ref)
            if observed == intent.expected_head_commit:
                # The exact create-only effect is independently known after response loss.
                pass
            elif observed is None:
                raise GitRevisionBackendError(
                    "publication_ref_create_rejected",
                    "The immutable publication ref was not created",
                    private_detail=exc.private_detail,
                ) from exc
            else:
                raise GitRevisionBackendError(
                    "publication_ref_integrity_conflict",
                    "The immutable publication ref already names another commit",
                    private_detail=exc.private_detail,
                ) from exc
        observed = self._rev_parse(location, intent.publication_ref)
        if observed != intent.expected_head_commit:
            raise GitRevisionBackendError(
                "publication_ref_observation_mismatch",
                "The publication ref does not name the frozen commit",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            )
        return self._publication_receipt(binding, intent, dispatch, observed=observed)

    def observe_publication(
        self,
        binding: ProjectRepositoryBinding,
        intent: WorkspacePublicationIntent,
        receipt: WorkspacePublicationRemoteReceipt,
    ) -> WorkspacePublicationRemoteReceipt:
        self._require_intent_binding(binding, intent)
        self._require_receipt_identity(binding, intent, receipt)
        location = self._locator.resolve(binding)
        observed = self._rev_parse(location, intent.publication_ref)
        commit = self.observe_commit(binding, commit=observed)
        if observed != intent.expected_head_commit or commit.tree != intent.expected_tree:
            raise GitRevisionBackendError(
                "publication_ref_integrity_conflict",
                "The publication ref does not match its terminal receipt",
            )
        return receipt

    def reconcile_publication(
        self,
        binding: ProjectRepositoryBinding,
        intent: WorkspacePublicationIntent,
        dispatch: WorkspacePublicationDispatchIdentity,
    ) -> WorkspacePublicationRemoteReceipt | None:
        """Observe the original create-only intent without redispatching it."""

        self._require_intent_binding(binding, intent)
        location = self._locator.resolve(binding)
        observed = self._optional_rev_parse(location, intent.publication_ref)
        if observed is None:
            return None
        commit = self.observe_commit(binding, commit=observed)
        if observed != intent.expected_head_commit or commit.tree != intent.expected_tree:
            raise GitRevisionBackendError(
                "publication_ref_integrity_conflict",
                "The publication ref differs from the frozen create-only intent",
                effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            )
        return self._publication_receipt(binding, intent, dispatch, observed=observed)

    def observe_publication_namespace(
        self,
        binding: ProjectRepositoryBinding,
    ) -> PublicationNamespaceObservation:
        location = self._locator.resolve(binding)
        prefix = binding.ref_namespace_policy.publication_prefix
        output = self._git(
            location,
            "for-each-ref",
            "--format=%(refname)%00%(objectname)",
            f"{prefix}/",
        )
        refs: list[tuple[str, str]] = []
        for raw_line in output.splitlines():
            if not raw_line:
                continue
            parts = raw_line.decode("ascii").split("\x00")
            if len(parts) != 2:
                raise GitRevisionBackendError(
                    "publication_namespace_observation_invalid",
                    "Git returned an invalid publication namespace observation",
                )
            refs.append((parts[0], parts[1]))
        return PublicationNamespaceObservation.create(
            repository_binding_id=binding.binding_id,
            repository_binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            publication_ref_prefix=prefix,
            refs=tuple(sorted(refs)),
            observed_at=self._now(),
        )

    def verify_revision_path(
        self,
        binding: ProjectRepositoryBinding,
        revision: PublishedRevision,
        ref: RevisionPathRef,
    ) -> RevisionPathVerificationReceipt:
        self._require_revision_identity(binding, revision, ref)
        location = self._locator.resolve(binding)
        commit = self.observe_commit(binding, commit=ref.commit)
        if commit.tree != ref.tree:
            raise GitRevisionBackendError(
                "revision_tree_mismatch",
                "The revision commit no longer matches the referenced tree",
            )
        entry = self._exact_tree_entry(location, ref.commit, ref.path)
        self._require_ref_entry(ref, entry)
        content, lfs_pointer = self._entry_content(location, entry)
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        return RevisionPathVerificationReceipt.create(
            ref_id=ref.ref_id,
            publication_id=ref.publication_id,
            repository_binding_id=ref.repository_binding_id,
            repository_binding_version=ref.repository_binding_version,
            commit=ref.commit,
            tree=ref.tree,
            path=ref.path,
            object_id=ref.object_id,
            actual_size_bytes=len(content),
            actual_content_digest=digest,
            lfs_oid=(f"sha256:{lfs_pointer.oid}" if lfs_pointer else None),
            lfs_size_bytes=(lfs_pointer.size if lfs_pointer else None),
            verified_at=self._now(),
        )

    def read_revision_path(
        self,
        binding: ProjectRepositoryBinding,
        request: RevisionPathReadRequest,
    ) -> RevisionPathReadReceipt:
        ref = request.ref
        self._require_binding(ref.repository_binding_id, ref.repository_binding_version, binding)
        if ref.repository_id != binding.repository_id:
            raise GitRevisionBackendError(
                "revision_repository_mismatch",
                "The revision path belongs to another repository",
            )
        location = self._locator.resolve(binding)
        commit = self.observe_commit(binding, commit=ref.commit)
        if commit.tree != ref.tree:
            raise GitRevisionBackendError(
                "revision_tree_mismatch",
                "The revision commit no longer matches the referenced tree",
            )
        entry = self._exact_tree_entry(location, ref.commit, ref.path)
        self._require_ref_entry(ref, entry)
        content, _ = self._entry_content(location, entry)
        returned = content[: request.max_bytes]
        return RevisionPathReadReceipt(
            ref_id=ref.ref_id,
            publication_id=ref.publication_id,
            returned_bytes=returned,
            returned_bytes_digest="sha256:" + hashlib.sha256(returned).hexdigest(),
            actual_size_bytes=len(content),
            actual_content_digest="sha256:" + hashlib.sha256(content).hexdigest(),
            truncated=len(returned) < len(content),
            verified_at=self._now(),
        )

    @staticmethod
    def _require_binding(binding_id: str, version: int, binding: ProjectRepositoryBinding) -> None:
        if binding_id != binding.binding_id or version != binding.binding_version:
            raise GitRevisionBackendError(
                "repository_binding_mismatch",
                "The request does not match the exact repository binding",
            )

    def _require_intent_binding(
        self, binding: ProjectRepositoryBinding, intent: WorkspacePublicationIntent
    ) -> None:
        self._require_binding(
            intent.repository_binding_id, intent.repository_binding_version, binding
        )
        if intent.repository_id != binding.repository_id:
            raise GitRevisionBackendError(
                "publication_repository_mismatch",
                "The publication intent belongs to another repository",
            )

    @staticmethod
    def _require_receipt_identity(
        binding: ProjectRepositoryBinding,
        intent: WorkspacePublicationIntent,
        receipt: WorkspacePublicationRemoteReceipt,
    ) -> None:
        if (
            receipt.intent_id != intent.intent_id
            or receipt.publication_id != intent.publication_id
            or receipt.repository_binding_id != binding.binding_id
            or receipt.repository_binding_version != binding.binding_version
            or receipt.repository_id != binding.repository_id
            or receipt.internal_git_service_id != binding.internal_git_service_id
            or receipt.publication_ref != intent.publication_ref
            or receipt.new_commit != intent.expected_head_commit
            or receipt.new_tree != intent.expected_tree
        ):
            raise GitRevisionBackendError(
                "publication_receipt_identity_mismatch",
                "The supplied receipt does not belong to this publication intent",
            )

    @staticmethod
    def _require_revision_identity(
        binding: ProjectRepositoryBinding,
        revision: PublishedRevision,
        ref: RevisionPathRef,
    ) -> None:
        if (
            revision.repository_binding_id != binding.binding_id
            or revision.repository_binding_version != binding.binding_version
            or revision.repository_id != binding.repository_id
            or ref.publication_id != revision.publication_id
            or ref.repository_binding_id != binding.binding_id
            or ref.repository_binding_version != binding.binding_version
            or ref.repository_id != binding.repository_id
            or ref.commit != revision.commit
            or ref.tree != revision.tree
        ):
            raise GitRevisionBackendError(
                "revision_path_identity_mismatch",
                "The path reference does not match the immutable published revision",
            )
        expected = next(
            (entry for entry in revision.manifest.entries if entry.path == ref.path), None
        )
        if expected is None or expected.object_id != ref.object_id:
            raise GitRevisionBackendError(
                "revision_path_manifest_mismatch",
                "The path is absent from the published manifest",
            )

    @staticmethod
    def _require_ref_entry(ref: RevisionPathRef, entry: _TreeEntry) -> None:
        inferred = {
            "100644": RevisionPathEntryKind.FILE,
            "100755": RevisionPathEntryKind.FILE,
            "120000": RevisionPathEntryKind.SYMLINK,
            "160000": RevisionPathEntryKind.GITLINK,
            "040000": RevisionPathEntryKind.DIRECTORY,
        }.get(entry.mode)
        if inferred is None:
            raise GitRevisionBackendError(
                "revision_path_kind_unsupported", "The Git path mode is unsupported"
            )
        if ref.entry_kind is RevisionPathEntryKind.LFS_FILE:
            if inferred is not RevisionPathEntryKind.FILE:
                raise GitRevisionBackendError(
                    "revision_path_kind_mismatch", "The LFS path is not a regular file"
                )
        elif ref.entry_kind is not inferred:
            raise GitRevisionBackendError(
                "revision_path_kind_mismatch", "The Git path kind differs from the reference"
            )
        if entry.object_id != ref.object_id:
            raise GitRevisionBackendError(
                "revision_path_object_mismatch", "The Git object differs from the reference"
            )
        if entry.size_bytes != ref.size_bytes:
            raise GitRevisionBackendError(
                "revision_path_size_mismatch", "The Git object size differs from the reference"
            )

    def _publication_entry(
        self, location: GitRepositoryLocation, entry: _TreeEntry
    ) -> PublicationManifestEntry:
        object_kind = (
            PublicationManifestObjectKind.COMMIT
            if entry.object_kind == "commit"
            else PublicationManifestObjectKind.BLOB
        )
        lfs_pointer = None
        if entry.object_kind == "blob" and (entry.size_bytes or 0) <= 1024:
            raw = self._cat_blob(location, entry.object_id)
            if raw.startswith(f"version {GIT_LFS_POINTER_VERSION}\n".encode("ascii")):
                try:
                    lfs_pointer = GitLfsPointer.parse(raw)
                except ValueError as exc:
                    raise GitRevisionBackendError(
                        "git_lfs_pointer_invalid",
                        "A Git LFS pointer does not use the canonical closed grammar",
                    ) from exc
                self._read_lfs_object(location, lfs_pointer)
        return PublicationManifestEntry(
            path=entry.path,
            mode=entry.mode,
            object_kind=object_kind,
            object_id=entry.object_id,
            size_bytes=entry.size_bytes,
            lfs_oid=(f"sha256:{lfs_pointer.oid}" if lfs_pointer else None),
            lfs_size_bytes=(lfs_pointer.size if lfs_pointer else None),
        )

    def _entry_content(
        self, location: GitRepositoryLocation, entry: _TreeEntry
    ) -> tuple[bytes, GitLfsPointer | None]:
        if entry.object_kind != "blob":
            raise GitRevisionBackendError(
                "revision_path_not_readable",
                "Only immutable blob and LFS file bytes can be read",
            )
        raw = self._cat_blob(location, entry.object_id)
        if raw.startswith(f"version {GIT_LFS_POINTER_VERSION}\n".encode("ascii")):
            try:
                pointer = GitLfsPointer.parse(raw)
            except ValueError as exc:
                raise GitRevisionBackendError(
                    "git_lfs_pointer_invalid",
                    "A Git LFS pointer does not use the canonical closed grammar",
                ) from exc
            return self._read_lfs_object(location, pointer), pointer
        return raw, None

    def _read_lfs_object(
        self, location: GitRepositoryLocation, pointer: GitLfsPointer
    ) -> bytes:
        root = location.lfs_object_root
        if root is None:
            raise GitRevisionBackendError(
                "git_lfs_store_not_configured",
                "The repository has no configured LFS object store",
            )
        path = root / "objects" / pointer.oid[:2] / pointer.oid[2:4] / pointer.oid
        try:
            content = path.read_bytes()
        except FileNotFoundError as exc:
            raise GitRevisionBackendError(
                "git_lfs_object_missing",
                "A referenced Git LFS object is absent",
            ) from exc
        digest = hashlib.sha256(content).hexdigest()
        if len(content) != pointer.size or digest != pointer.oid:
            raise GitRevisionBackendError(
                "git_lfs_object_integrity_mismatch",
                "A referenced Git LFS object failed size or digest verification",
            )
        return content

    def _exact_tree_entry(
        self, location: GitRepositoryLocation, commit: str, path: str
    ) -> _TreeEntry:
        entries = self._list_tree(location, commit, recursive=False, path=path)
        exact = [entry for entry in entries if entry.path == path]
        if len(exact) != 1:
            raise GitRevisionBackendError(
                "revision_path_not_found", "The exact path is absent from the revision"
            )
        return exact[0]

    def _list_tree(
        self,
        location: GitRepositoryLocation,
        commit: str,
        *,
        recursive: bool,
        path: str | None = None,
    ) -> tuple[_TreeEntry, ...]:
        argv = ["ls-tree", "-z", "--long"]
        if recursive:
            argv.append("-r")
        argv.append(commit)
        if path is not None:
            argv.extend(("--", path))
        raw = self._git(location, *argv)
        result: list[_TreeEntry] = []
        for record in raw.split(b"\0"):
            if not record:
                continue
            try:
                header, raw_path = record.split(b"\t", 1)
                mode, kind, oid, size = header.decode("ascii").split()
                decoded_path = raw_path.decode("utf-8")
            except (UnicodeDecodeError, ValueError) as exc:
                raise GitRevisionBackendError(
                    "git_tree_observation_invalid",
                    "Git returned an invalid tree entry",
                ) from exc
            result.append(
                _TreeEntry(
                    path=decoded_path,
                    mode=mode,
                    object_kind=kind,
                    object_id=oid,
                    size_bytes=None if size == "-" else int(size),
                )
            )
        return tuple(result)

    def _cat_blob(self, location: GitRepositoryLocation, object_id: str) -> bytes:
        return self._git(location, "cat-file", "blob", object_id)

    def _publication_receipt(
        self,
        binding: ProjectRepositoryBinding,
        intent: WorkspacePublicationIntent,
        dispatch: WorkspacePublicationDispatchIdentity,
        *,
        observed: str,
    ) -> WorkspacePublicationRemoteReceipt:
        return WorkspacePublicationRemoteReceipt.create(
            receipt_id=dispatch.receipt_id,
            intent_id=intent.intent_id,
            publication_id=intent.publication_id,
            execution_id=dispatch.execution_id,
            execution_dispatch_generation=dispatch.dispatch_generation,
            execution_fencing_token=dispatch.fencing_token,
            internal_git_service_id=binding.internal_git_service_id,
            repository_binding_id=binding.binding_id,
            repository_binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            publication_ref=intent.publication_ref,
            expected_previous_commit=None,
            new_commit=intent.expected_head_commit,
            new_tree=intent.expected_tree,
            server_observed_commit=observed,
            observed_at=self._now(),
        )

    def _rev_parse(self, location: GitRepositoryLocation, ref: str) -> str:
        value = self._git(location, "rev-parse", "--verify", ref).decode("ascii").strip()
        if len(value) not in {40, 64}:
            raise GitRevisionBackendError(
                "git_ref_observation_invalid", "Git returned an invalid object identity"
            )
        return value

    def _optional_rev_parse(
        self, location: GitRepositoryLocation, ref: str
    ) -> str | None:
        command = self._run_git(location, "show-ref", "--verify", "--quiet", ref)
        if command.returncode == 1:
            return None
        if command.returncode != 0:
            raise self._command_error(location, command)
        return self._rev_parse(location, ref)

    def _is_ancestor(
        self, location: GitRepositoryLocation, ancestor: str, descendant: str
    ) -> bool:
        command = self._run_git(location, "merge-base", "--is-ancestor", ancestor, descendant)
        if command.returncode == 0:
            return True
        if command.returncode == 1:
            return False
        raise self._command_error(location, command)

    def _git(self, location: GitRepositoryLocation, *argv: str) -> bytes:
        command = self._run_git(location, *argv)
        if command.returncode != 0:
            raise self._command_error(location, command)
        return command.stdout

    @staticmethod
    def _run_git(
        location: GitRepositoryLocation, *argv: str
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                ("git", f"--git-dir={location.bare_repository_root}", *argv),
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitRevisionBackendError(
                "git_process_unavailable",
                "The Git Adapter process could not complete",
                private_detail=type(exc).__name__,
            ) from exc

    @staticmethod
    def _command_error(
        location: GitRepositoryLocation, command: subprocess.CompletedProcess[bytes]
    ) -> GitRevisionBackendError:
        detail = command.stderr[-_MAX_GIT_STDERR_BYTES:].decode("utf-8", errors="replace")
        detail = detail.replace(str(location.bare_repository_root), "<repository>")
        if location.lfs_object_root is not None:
            detail = detail.replace(str(location.lfs_object_root), "<lfs-store>")
        return GitRevisionBackendError(
            "git_command_failed",
            "The Git Adapter command failed",
            private_detail=f"returncode={command.returncode}; stderr={detail}",
        )


__all__ = [
    "GitRepositoryLocation",
    "GitRepositoryLocator",
    "GitRevisionBackendError",
    "LocalGitRevisionBackend",
]
