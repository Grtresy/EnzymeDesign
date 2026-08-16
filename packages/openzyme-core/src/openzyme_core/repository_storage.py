from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import TYPE_CHECKING
from typing import BinaryIO

from openzyme_domain import GitObjectFormat
from openzyme_domain import PublicationManifestEntry
from openzyme_domain import PublicationManifestObjectKind
from openzyme_domain import ProjectRepositoryBinding
from openzyme_domain import WorkspacePublicationManifest
from openzyme_domain import require_repository_path
from openzyme_runtime import RepositoryServiceSettings

if TYPE_CHECKING:
    from .repository_credentials import GitRefUpdate


class RepositoryStorageError(RuntimeError):
    error_code = "repository_storage_error"


class RepositoryRootRejectedError(RepositoryStorageError):
    error_code = "repository_durable_root_rejected"


class RepositoryIdentityMismatchError(RepositoryStorageError):
    error_code = "repository_identity_mismatch"


class RepositoryBaseCommitError(RepositoryStorageError):
    error_code = "repository_base_commit_unavailable"


class LfsObjectMismatchError(RepositoryStorageError):
    error_code = "lfs_object_mismatch"


@dataclass(frozen=True, slots=True)
class RepositoryRootBoundary:
    host_checkout: Path
    process_cwd: Path
    temporary_roots: tuple[Path, ...] = (Path("/tmp"), Path("/var/tmp"))

    @classmethod
    def production(
        cls,
        *,
        host_checkout: Path,
        process_cwd: Path,
    ) -> "RepositoryRootBoundary":
        return cls(
            host_checkout=host_checkout.resolve(strict=True),
            process_cwd=process_cwd.resolve(strict=True),
        )


def _is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _safe_repository_id(repository_id: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", repository_id) is None:
        raise RepositoryIdentityMismatchError(
            "repository_id must be a filesystem-safe service identity"
        )
    return repository_id


@dataclass(frozen=True, slots=True)
class DurableRootFact:
    kind: str
    path: Path
    path_digest: str
    device: int
    inode: int
    owner_uid: int
    owner_gid: int
    mode: int

    def to_private_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "path": str(self.path),
            "path_digest": self.path_digest,
            "device": self.device,
            "inode": self.inode,
            "owner_uid": self.owner_uid,
            "owner_gid": self.owner_gid,
            "mode": f"{self.mode:04o}",
        }

    def to_safe_dict(self) -> dict[str, object]:
        private = self.to_private_dict()
        private.pop("path")
        return private


@dataclass(slots=True)
class DurableRepositoryRootManager:
    settings: RepositoryServiceSettings
    boundary: RepositoryRootBoundary

    def preflight_roots(
        self,
    ) -> tuple[DurableRootFact, DurableRootFact, DurableRootFact]:
        facts = (
            self._root_fact("bare_git", self.settings.bare_repository_root),
            self._root_fact("lfs_objects", self.settings.lfs_object_root),
            self._root_fact("backup", self.settings.backup_root),
        )
        resolved = [fact.path for fact in facts]
        for left in resolved:
            for right in resolved:
                if left != right and (
                    _is_within(left, right) or _is_within(right, left)
                ):
                    raise RepositoryRootRejectedError(
                        "Git, LFS, and backup roots must not contain one another"
                    )
        for fact in facts:
            self._prove_writable(fact.path)
        return facts

    @staticmethod
    def _prove_writable(path: Path) -> None:
        with tempfile.NamedTemporaryFile(
            dir=path,
            prefix=".openzyme-preflight-",
            delete=False,
        ) as stream:
            probe = Path(stream.name)
            stream.write(b"openzyme repository durable-root preflight\n")
            stream.flush()
            os.fsync(stream.fileno())
        probe.unlink()
        directory_fd = os.open(path, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def _root_fact(self, kind: str, configured: Path) -> DurableRootFact:
        if not configured.is_absolute():
            raise RepositoryRootRejectedError(f"{kind} root must be absolute")
        if configured.is_symlink():
            raise RepositoryRootRejectedError(f"{kind} root must not be a symlink")
        resolved = configured.resolve(strict=True)
        if not resolved.is_dir():
            raise RepositoryRootRejectedError(
                f"{kind} root must be an existing directory"
            )
        forbidden = (
            self.boundary.host_checkout,
            self.boundary.process_cwd,
            *(root.resolve(strict=True) for root in self.boundary.temporary_roots),
        )
        for root in forbidden:
            if _is_within(resolved, root) or _is_within(root, resolved):
                raise RepositoryRootRejectedError(
                    f"{kind} root overlaps forbidden authority root {root}"
                )
        metadata = resolved.stat()
        mode = stat.S_IMODE(metadata.st_mode)
        if metadata.st_uid != os.geteuid():
            raise RepositoryRootRejectedError(
                f"{kind} root is not owned by the Host service uid"
            )
        if mode & 0o077:
            raise RepositoryRootRejectedError(
                f"{kind} root permissions must not grant group or other access"
            )
        path_digest = (
            f"sha256:{hashlib.sha256(str(resolved).encode('utf-8')).hexdigest()}"
        )
        return DurableRootFact(
            kind=kind,
            path=resolved,
            path_digest=path_digest,
            device=metadata.st_dev,
            inode=metadata.st_ino,
            owner_uid=metadata.st_uid,
            owner_gid=metadata.st_gid,
            mode=mode,
        )

    def repository_path(self, repository_id: str) -> Path:
        _safe_repository_id(repository_id)
        root = self._root_fact("bare_git", self.settings.bare_repository_root).path
        return root / f"{repository_id}.git"

    def create_bare_repository(self, binding: ProjectRepositoryBinding) -> Path:
        path = self.repository_path(binding.repository_id)
        if path.exists():
            self.verify_bare_repository(binding)
            return path
        self._run_git(
            "init",
            "--bare",
            f"--object-format={binding.object_format.value}",
            str(path),
        )
        path.chmod(0o700)
        self._run_git("--git-dir", str(path), "config", "http.receivepack", "true")
        self._run_git(
            "--git-dir",
            str(path),
            "config",
            "uploadpack.allowFilter",
            "true",
        )
        self._run_git(
            "--git-dir",
            str(path),
            "config",
            "receive.advertiseAtomic",
            "true",
        )
        self._run_git(
            "--git-dir",
            str(path),
            "config",
            "receive.denyDeletes",
            "true",
        )
        self._run_git(
            "--git-dir",
            str(path),
            "config",
            "receive.denyNonFastForwards",
            "true",
        )
        self._run_git(
            "--git-dir",
            str(path),
            "config",
            "openzyme.repositoryId",
            binding.repository_id,
        )
        self.install_pre_receive_hook(binding)
        self.verify_bare_repository(binding)
        return path

    def verify_bare_repository(self, binding: ProjectRepositoryBinding) -> Path:
        path = self.repository_path(binding.repository_id)
        if not path.is_dir():
            raise RepositoryStorageError(
                f"bare repository {binding.repository_id!r} does not exist"
            )
        if path.is_symlink():
            raise RepositoryRootRejectedError("bare repository must not be a symlink")
        metadata = path.stat()
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise RepositoryRootRejectedError(
                "bare repository ownership or permissions do not match Host authority"
            )
        bare = (
            self._run_git(
                "--git-dir",
                str(path),
                "rev-parse",
                "--is-bare-repository",
            )
            .stdout.decode("ascii")
            .strip()
        )
        if bare != "true":
            raise RepositoryIdentityMismatchError(
                f"repository {binding.repository_id!r} is not bare"
            )
        object_format = (
            self._run_git(
                "--git-dir",
                str(path),
                "rev-parse",
                "--show-object-format",
            )
            .stdout.decode("ascii")
            .strip()
        )
        if object_format != binding.object_format.value:
            raise RepositoryIdentityMismatchError(
                "bare repository object format does not match binding"
            )
        repository_id = (
            self._run_git(
                "--git-dir",
                str(path),
                "config",
                "--get",
                "openzyme.repositoryId",
            )
            .stdout.decode("utf-8")
            .strip()
        )
        if repository_id != binding.repository_id:
            raise RepositoryIdentityMismatchError(
                "bare repository service identity does not match binding"
            )
        self.verify_pre_receive_hook(binding)
        return path

    @staticmethod
    def _pre_receive_hook_bytes() -> bytes:
        return Path(__file__).with_name("repository_pre_receive_hook.sh").read_bytes()

    @classmethod
    def pre_receive_hook_digest(cls) -> str:
        return f"sha256:{hashlib.sha256(cls._pre_receive_hook_bytes()).hexdigest()}"

    def install_pre_receive_hook(self, binding: ProjectRepositoryBinding) -> Path:
        path = self.repository_path(binding.repository_id)
        hooks = path / "hooks"
        hooks.mkdir(mode=0o700, exist_ok=True)
        hook = hooks / "pre-receive"
        expected = self._pre_receive_hook_bytes()
        if hook.exists():
            if hook.is_symlink() or hook.read_bytes() != expected:
                raise RepositoryIdentityMismatchError(
                    "bare repository pre-receive hook drifted"
                )
            metadata = hook.stat()
            if (
                metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                raise RepositoryRootRejectedError(
                    "bare repository pre-receive hook ownership or permissions drifted"
                )
        else:
            with hook.open("xb") as stream:
                stream.write(expected)
                stream.flush()
                os.fsync(stream.fileno())
            hook.chmod(0o700)
        self._run_git(
            "--git-dir",
            str(path),
            "config",
            "openzyme.preReceiveHookDigest",
            self.pre_receive_hook_digest(),
        )
        self.verify_pre_receive_hook(binding)
        return hook

    def verify_pre_receive_hook(self, binding: ProjectRepositoryBinding) -> str:
        path = self.repository_path(binding.repository_id)
        hook = path / "hooks" / "pre-receive"
        if not hook.is_file() or hook.is_symlink():
            raise RepositoryIdentityMismatchError(
                "bare repository pre-receive hook is missing"
            )
        metadata = hook.stat()
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise RepositoryRootRejectedError(
                "bare repository pre-receive hook ownership or mode drifted"
            )
        digest = f"sha256:{hashlib.sha256(hook.read_bytes()).hexdigest()}"
        configured = (
            self._run_git(
                "--git-dir",
                str(path),
                "config",
                "--get",
                "openzyme.preReceiveHookDigest",
            )
            .stdout.decode("ascii")
            .strip()
        )
        if digest != self.pre_receive_hook_digest() or configured != digest:
            raise RepositoryIdentityMismatchError(
                "bare repository pre-receive hook digest drifted"
            )
        return digest

    def verify_exact_base(self, binding: ProjectRepositoryBinding) -> str:
        path = self.verify_bare_repository(binding)
        commit = self.verify_pinned_commit(binding)
        ref_commit = (
            self._run_git(
                "--git-dir",
                str(path),
                "rev-parse",
                f"{binding.default_base_ref}^{{commit}}",
            )
            .stdout.decode("ascii")
            .strip()
        )
        if ref_commit != binding.default_base_commit:
            raise RepositoryBaseCommitError(
                "binding default base ref does not resolve to the exact pinned commit"
            )
        return commit

    def verify_pinned_commit(self, binding: ProjectRepositoryBinding) -> str:
        path = self.verify_bare_repository(binding)
        commit = (
            self._run_git(
                "--git-dir",
                str(path),
                "rev-parse",
                f"{binding.default_base_commit}^{{commit}}",
            )
            .stdout.decode("ascii")
            .strip()
        )
        if commit != binding.default_base_commit:
            raise RepositoryBaseCommitError(
                "binding default base commit does not resolve exactly"
            )
        return commit

    def import_exact_commit_from_repository(
        self,
        binding: ProjectRepositoryBinding,
        *,
        source_repository: Path,
        source_commit: str,
    ) -> None:
        if not source_repository.is_absolute():
            raise ValueError("source_repository must be an explicit absolute path")
        if source_commit != binding.default_base_commit:
            raise RepositoryBaseCommitError(
                "operator import commit must equal binding default_base_commit"
            )
        path = self.verify_bare_repository(binding)
        self._run_git(
            "--git-dir",
            str(path),
            "fetch",
            "--no-tags",
            str(source_repository),
            f"{source_commit}:{binding.default_base_ref}",
        )
        self.set_default_head(binding)
        self.verify_exact_base(binding)

    def set_default_head(self, binding: ProjectRepositoryBinding) -> None:
        path = self.verify_bare_repository(binding)
        self._run_git(
            "--git-dir",
            str(path),
            "symbolic-ref",
            "HEAD",
            binding.default_base_ref,
        )

    def verify_default_head(self, binding: ProjectRepositoryBinding) -> str:
        path = self.verify_bare_repository(binding)
        default_head = (
            self._run_git(
                "--git-dir",
                str(path),
                "symbolic-ref",
                "HEAD",
            )
            .stdout.decode("utf-8")
            .strip()
        )
        if default_head != binding.default_base_ref:
            raise RepositoryBaseCommitError(
                "bare repository HEAD does not match active binding base ref"
            )
        return default_head

    def is_ancestor(
        self,
        binding: ProjectRepositoryBinding,
        *,
        ancestor: str,
        descendant: str,
        extra_env: dict[str, str] | None = None,
    ) -> bool:
        path = self.verify_bare_repository(binding)
        result = self._run_git(
            "--git-dir",
            str(path),
            "merge-base",
            "--is-ancestor",
            ancestor,
            descendant,
            check=False,
            extra_env=extra_env,
        )
        if result.returncode not in {0, 1}:
            raise RepositoryStorageError(
                result.stderr.decode("utf-8", errors="replace").strip()
                or "git merge-base failed"
            )
        return result.returncode == 0

    def list_refs(
        self,
        binding: ProjectRepositoryBinding,
        *,
        prefix: str,
    ) -> tuple[tuple[str, str], ...]:
        path = self.verify_bare_repository(binding)
        output = self._run_git(
            "--git-dir",
            str(path),
            "for-each-ref",
            "--format=%(refname)%00%(objectname)",
            prefix,
        ).stdout
        refs: list[tuple[str, str]] = []
        for line in output.splitlines():
            ref_bytes, separator, oid_bytes = line.partition(b"\x00")
            if separator != b"\x00":
                raise RepositoryStorageError(
                    "git for-each-ref returned malformed output"
                )
            refs.append((ref_bytes.decode("utf-8"), oid_bytes.decode("ascii")))
        return tuple(refs)

    def read_exact_ref(
        self,
        binding: ProjectRepositoryBinding,
        *,
        ref_name: str,
    ) -> str | None:
        if not ref_name.startswith("refs/") or "\x00" in ref_name:
            raise RepositoryStorageError("exact ref name is invalid")
        path = self.verify_bare_repository(binding)
        result = self._run_git(
            "--git-dir",
            str(path),
            "show-ref",
            "--verify",
            "--hash",
            ref_name,
            check=False,
        )
        if result.returncode == 1:
            return None
        if result.returncode != 0:
            raise RepositoryStorageError(
                result.stderr.decode("utf-8", errors="replace").strip()
                or "git show-ref failed"
            )
        object_id = result.stdout.decode("ascii").strip()
        if len(object_id) != binding.object_format.commit_hex_length:
            raise RepositoryStorageError("exact ref returned an invalid object id")
        return object_id

    def read_commit_tree(
        self,
        binding: ProjectRepositoryBinding,
        *,
        commit: str,
    ) -> str:
        self.require_commit_object(binding, commit)
        path = self.verify_bare_repository(binding)
        tree = (
            self._run_git(
                "--git-dir",
                str(path),
                "show",
                "-s",
                "--format=%T",
                commit,
            )
            .stdout.decode("ascii")
            .strip()
        )
        if len(tree) != binding.object_format.commit_hex_length:
            raise RepositoryStorageError("commit tree returned an invalid object id")
        return tree

    def read_commit_parents(
        self,
        binding: ProjectRepositoryBinding,
        *,
        commit: str,
    ) -> tuple[str, ...]:
        self.require_commit_object(binding, commit)
        path = self.verify_bare_repository(binding)
        output = self._run_git(
            "--git-dir",
            str(path),
            "show",
            "-s",
            "--format=%P",
            commit,
        ).stdout.decode("ascii").strip()
        parents = () if not output else tuple(output.split(" "))
        if any(
            len(parent) != binding.object_format.commit_hex_length
            for parent in parents
        ):
            raise RepositoryStorageError("commit parent list is malformed")
        return parents

    def read_whole_tree_manifest(
        self,
        binding: ProjectRepositoryBinding,
        *,
        commit: str,
    ) -> WorkspacePublicationManifest:
        self.require_commit_object(binding, commit)
        path = self.verify_bare_repository(binding)
        output = self._run_git(
            "--git-dir",
            str(path),
            "ls-tree",
            "-r",
            "-z",
            "-l",
            "--full-tree",
            commit,
        ).stdout
        entries: list[PublicationManifestEntry] = []
        for raw_entry in output.split(b"\x00"):
            if not raw_entry:
                continue
            metadata, separator, raw_path = raw_entry.partition(b"\t")
            fields = metadata.split()
            if separator != b"\t" or len(fields) != 4:
                raise RepositoryStorageError("git ls-tree returned malformed output")
            mode, object_kind, object_id, raw_size = fields
            try:
                repository_path = raw_path.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RepositoryStorageError(
                    "publication manifest requires UTF-8 repository paths"
                ) from exc
            kind = PublicationManifestObjectKind(object_kind.decode("ascii"))
            size_bytes = None if raw_size == b"-" else int(raw_size)
            entries.append(
                PublicationManifestEntry(
                    path=repository_path,
                    mode=mode.decode("ascii"),
                    object_kind=kind,
                    object_id=object_id.decode("ascii"),
                    size_bytes=size_bytes,
                )
            )
        return WorkspacePublicationManifest.create(tuple(entries))

    def read_blob(
        self,
        binding: ProjectRepositoryBinding,
        *,
        object_id: str,
        max_bytes: int,
    ) -> bytes:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        path = self.verify_bare_repository(binding)
        object_type = self._run_git(
            "--git-dir",
            str(path),
            "cat-file",
            "-t",
            object_id,
        ).stdout.strip()
        if object_type != b"blob":
            raise RepositoryStorageError("requested Git object is not a blob")
        size_bytes = int(
            self._run_git(
                "--git-dir",
                str(path),
                "cat-file",
                "-s",
                object_id,
            ).stdout.strip()
        )
        if size_bytes > max_bytes:
            raise RepositoryStorageError(
                "Git blob exceeds the bounded publication reader limit"
            )
        value = self._run_git(
            "--git-dir",
            str(path),
            "cat-file",
            "blob",
            object_id,
        ).stdout
        if len(value) != size_bytes:
            raise RepositoryStorageError("Git blob read returned an incomplete value")
        return value

    def read_directory_tree_object(
        self,
        *,
        binding: ProjectRepositoryBinding,
        commit: str,
        path: str,
    ) -> str:
        require_repository_path(path)
        self.require_commit_object(binding, commit)
        repository = self.verify_bare_repository(binding)
        result = self._run_git(
            "--git-dir",
            str(repository),
            "rev-parse",
            "--verify",
            f"{commit}:{path}^{{tree}}",
            check=False,
        )
        if result.returncode != 0:
            raise RepositoryStorageError(
                "publication directory path is absent or is not a Git tree"
            )
        object_id = result.stdout.decode("ascii").strip()
        if len(object_id) != binding.object_format.commit_hex_length:
            raise RepositoryStorageError(
                "publication directory tree object identity is malformed"
            )
        return object_id

    def create_publication_ref_if_absent(
        self,
        binding: ProjectRepositoryBinding,
        *,
        publication_id: str,
        ref_name: str,
        commit: str,
    ) -> str:
        expected_ref = (
            f"{binding.ref_namespace_policy.publication_prefix}/{publication_id}"
        )
        if ref_name != expected_ref:
            raise RepositoryStorageError(
                "publication ref is outside the exact Host-owned namespace"
            )
        self.require_commit_object(binding, commit)
        path = self.verify_bare_repository(binding)
        commands = b"".join(
            (
                b"start\x00",
                b"option no-deref\x00",
                f"create {ref_name}".encode("utf-8") + b"\x00",
                commit.encode("ascii") + b"\x00",
                b"prepare\x00",
                b"commit\x00",
            )
        )
        self._run_git(
            "--git-dir",
            str(path),
            "update-ref",
            "--stdin",
            "-z",
            input_bytes=commands,
        )
        observed = self.read_exact_ref(binding, ref_name=ref_name)
        if observed != commit:
            raise RepositoryStorageError(
                "created publication ref does not match the intended commit"
            )
        return observed

    def require_commit_object(
        self,
        binding: ProjectRepositoryBinding,
        object_id: str,
    ) -> str:
        path = self.verify_bare_repository(binding)
        result = self._run_git(
            "--git-dir",
            str(path),
            "cat-file",
            "-t",
            object_id,
            check=False,
        )
        if result.returncode != 0 or result.stdout.strip() != b"commit":
            raise RepositoryStorageError("repository ref target is not a commit object")
        return object_id

    def apply_exact_ref_updates(
        self,
        binding: ProjectRepositoryBinding,
        updates: tuple[GitRefUpdate, ...],
    ) -> None:
        if not updates:
            raise ValueError("at least one exact ref update is required")
        ref_names = tuple(update.ref_name for update in updates)
        if len(set(ref_names)) != len(ref_names):
            raise ValueError("an exact ref transaction cannot update a ref twice")
        if any("\x00" in ref_name for ref_name in ref_names):
            raise ValueError("an exact ref transaction cannot contain a NUL byte")
        zero_oid = "0" * binding.object_format.commit_hex_length
        if any(update.new_oid == zero_oid for update in updates):
            raise ValueError("exact ref updates do not authorize deletion")

        for object_id in {update.new_oid for update in updates}:
            self.require_commit_object(binding, object_id)

        path = self.verify_bare_repository(binding)
        commands = [b"start\x00"]
        for update in updates:
            commands.append(b"option no-deref\x00")
            if update.old_oid == zero_oid:
                commands.extend(
                    (
                        f"create {update.ref_name}".encode("utf-8") + b"\x00",
                        update.new_oid.encode("ascii") + b"\x00",
                    )
                )
            else:
                commands.extend(
                    (
                        f"update {update.ref_name}".encode("utf-8") + b"\x00",
                        update.new_oid.encode("ascii") + b"\x00",
                        update.old_oid.encode("ascii") + b"\x00",
                    )
                )
        commands.extend((b"prepare\x00", b"commit\x00"))
        self._run_git(
            "--git-dir",
            str(path),
            "update-ref",
            "--stdin",
            "-z",
            input_bytes=b"".join(commands),
        )

    def delete_exact_refs(
        self,
        binding: ProjectRepositoryBinding,
        refs: tuple[tuple[str, str], ...],
    ) -> None:
        if not refs:
            return
        path = self.verify_bare_repository(binding)
        commands = (
            "start\n"
            + "".join(f"delete {ref} {oid}\n" for ref, oid in refs)
            + "prepare\ncommit\n"
        ).encode("ascii")
        self._run_git(
            "--git-dir",
            str(path),
            "update-ref",
            "--stdin",
            input_bytes=commands,
        )

    def _run_git(
        self,
        *arguments: str,
        check: bool = True,
        input_bytes: bytes | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        environment = {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": os.defpath,
        }
        if extra_env is not None:
            environment.update(extra_env)
        return subprocess.run(
            (str(self.settings.git_executable), *arguments),
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=check,
            env=environment,
        )


def _require_lfs_oid(oid: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", oid) is None:
        raise LfsObjectMismatchError("Git LFS oid must be 64 lowercase hex characters")
    return oid


@dataclass(slots=True)
class DurableLfsObjectStore:
    root_manager: DurableRepositoryRootManager

    def repository_root(self, repository_id: str) -> Path:
        _safe_repository_id(repository_id)
        root = self.root_manager._root_fact(  # noqa: SLF001 - same storage boundary
            "lfs_objects",
            self.root_manager.settings.lfs_object_root,
        ).path
        repository_root = root / repository_id
        repository_root.mkdir(mode=0o700, exist_ok=True)
        if repository_root.is_symlink() or not repository_root.is_dir():
            raise RepositoryRootRejectedError(
                "LFS repository root must be a real directory"
            )
        metadata = repository_root.stat()
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise RepositoryRootRejectedError(
                "LFS repository root ownership or permissions drifted"
            )
        return repository_root

    def object_path(self, repository_id: str, oid: str) -> Path:
        _require_lfs_oid(oid)
        root = self.repository_root(repository_id)
        return root / "objects" / oid[:2] / oid[2:4] / oid

    def has_object(
        self, repository_id: str, oid: str, *, size: int | None = None
    ) -> bool:
        path = self.object_path(repository_id, oid)
        if not path.is_file():
            return False
        if size is not None and path.stat().st_size != size:
            raise LfsObjectMismatchError("stored Git LFS object size does not match")
        return True

    def put(
        self,
        repository_id: str,
        oid: str,
        *,
        size: int,
        source: BinaryIO,
    ) -> Path:
        _require_lfs_oid(oid)
        if size < 0:
            raise LfsObjectMismatchError("Git LFS object size must not be negative")
        destination = self.object_path(repository_id, oid)
        if destination.exists():
            self.verify(repository_id, oid, size=size)
            return destination
        incoming = self.repository_root(repository_id) / "incoming"
        incoming.mkdir(mode=0o700, exist_ok=True)
        digest = hashlib.sha256()
        bytes_written = 0
        with tempfile.NamedTemporaryFile(dir=incoming, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                temporary.write(chunk)
                digest.update(chunk)
                bytes_written += len(chunk)
            temporary.flush()
            os.fsync(temporary.fileno())
        if bytes_written != size or digest.hexdigest() != oid:
            temporary_path.unlink()
            raise LfsObjectMismatchError(
                "Git LFS upload oid or size does not match bytes"
            )
        return self.promote_incoming(
            repository_id,
            oid,
            size=size,
            incoming_path=temporary_path,
        )

    def promote_incoming(
        self,
        repository_id: str,
        oid: str,
        *,
        size: int,
        incoming_path: Path,
    ) -> Path:
        _require_lfs_oid(oid)
        incoming_root = self.repository_root(repository_id) / "incoming"
        if incoming_path.parent.resolve(strict=True) != incoming_root.resolve(
            strict=True
        ):
            raise RepositoryRootRejectedError(
                "Git LFS incoming file is outside the durable incoming root"
            )
        if not incoming_path.is_file() or incoming_path.is_symlink():
            raise RepositoryRootRejectedError("Git LFS incoming file is invalid")
        digest = hashlib.sha256()
        with incoming_path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        if incoming_path.stat().st_size != size or digest.hexdigest() != oid:
            incoming_path.unlink()
            raise LfsObjectMismatchError(
                "Git LFS upload oid or size does not match bytes"
            )
        destination = self.object_path(repository_id, oid)
        if destination.exists():
            incoming_path.unlink()
            self.verify(repository_id, oid, size=size)
            return destination
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.replace(incoming_path, destination)
        destination.chmod(0o600)
        directory_fd = os.open(destination.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        self.verify(repository_id, oid, size=size)
        return destination

    def verify(self, repository_id: str, oid: str, *, size: int) -> Path:
        path = self.object_path(repository_id, oid)
        if not path.is_file():
            raise FileNotFoundError(f"Git LFS object {oid} does not exist")
        if path.stat().st_size != size:
            raise LfsObjectMismatchError("Git LFS object size does not match")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        if digest.hexdigest() != oid:
            raise LfsObjectMismatchError("Git LFS object digest does not match")
        return path

    def delete_exact(self, repository_id: str, oid: str, *, size: int) -> None:
        path = self.verify(repository_id, oid, size=size)
        if path.is_symlink():
            raise RepositoryRootRejectedError("Git LFS object must not be a symlink")
        path.unlink()
        directory_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


__all__ = [
    "DurableLfsObjectStore",
    "DurableRepositoryRootManager",
    "DurableRootFact",
    "GitObjectFormat",
    "LfsObjectMismatchError",
    "RepositoryBaseCommitError",
    "RepositoryIdentityMismatchError",
    "RepositoryRootBoundary",
    "RepositoryRootRejectedError",
    "RepositoryStorageError",
]
