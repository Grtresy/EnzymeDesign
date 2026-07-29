"""Deterministic source and toolchain identity for one test-gate invocation."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence

from .model import canonical_json_bytes, sha256_digest

DEFAULT_CONFIGURATION_PATHS = (
    "pyproject.toml",
    "pytest.ini",
    "apps/openzyme-web-ui/package.json",
    "scripts/test-affected-scope-map.json",
    "scripts/test-gate.toml",
    "scripts/test-resource-manifest.json",
    "scripts/check-mainline.sh",
    "scripts/check-v3-architecture-qualification.sh",
)
DEFAULT_LOCK_PATHS = (
    "uv.lock",
    "skills-lock.json",
    "apps/openzyme-web-ui/package-lock.json",
    "apps/openzyme-web-ui/npm-shrinkwrap.json",
    "apps/openzyme-web-ui/pnpm-lock.yaml",
    "apps/openzyme-web-ui/yarn.lock",
)
RELEVANT_UNTRACKED_ROOTS = frozenset(
    {
        ".agents",
        ".codex",
        ".github",
        "apps",
        "docs",
        "openspec",
        "packages",
        "scripts",
    }
)
RELEVANT_ROOT_FILES = frozenset(
    {
        ".python-version",
        "AGENTS.md",
        "README.md",
        "pyproject.toml",
        "pytest.ini",
        "skills-lock.json",
        "uv.lock",
    }
)
IGNORED_UNTRACKED_PARTS = frozenset(
    {
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
)


class SourceIdentityError(RuntimeError):
    """Raised when the current checkout cannot be identified exactly."""


@dataclass(frozen=True)
class FileIdentity:
    path: str
    kind: str
    mode: int | None
    size: int | None
    digest: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "kind": self.kind,
            "mode": self.mode,
            "size": self.size,
            "digest": self.digest,
        }


@dataclass(frozen=True)
class ToolchainIdentity:
    name: str
    executable: str | None
    version: str
    available: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "executable": self.executable,
            "version": self.version,
            "available": self.available,
        }


@dataclass(frozen=True)
class SourceIdentity:
    commit: str
    tracked_diff_digest: str
    tracked_dirty_paths: tuple[str, ...]
    relevant_untracked_sources: tuple[FileIdentity, ...]
    configurations: tuple[FileIdentity, ...]
    locks: tuple[FileIdentity, ...]
    toolchains: tuple[ToolchainIdentity, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "commit": self.commit,
            "tracked_diff_digest": self.tracked_diff_digest,
            "tracked_dirty_paths": list(self.tracked_dirty_paths),
            "relevant_untracked_sources": [
                item.as_dict() for item in self.relevant_untracked_sources
            ],
            "configurations": [item.as_dict() for item in self.configurations],
            "locks": [item.as_dict() for item in self.locks],
            "toolchains": [item.as_dict() for item in self.toolchains],
        }

    @property
    def digest(self) -> str:
        return sha256_digest(canonical_json_bytes(self.as_dict()))


def _run_git(repo_root: Path, *arguments: str) -> bytes:
    environment = dict(os.environ)
    environment["LC_ALL"] = "C"
    try:
        completed = subprocess.run(
            ("git", "-C", str(repo_root), *arguments),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceIdentityError(
            f"cannot execute git {' '.join(arguments)}: {exc}"
        ) from exc
    if completed.returncode != 0:
        stderr = completed.stderr[-2000:].decode("utf-8", errors="replace").strip()
        raise SourceIdentityError(
            f"git {' '.join(arguments)} failed with {completed.returncode}: {stderr}"
        )
    return completed.stdout


def _decode_nul_paths(data: bytes, *, context: str) -> tuple[str, ...]:
    if not data:
        return ()
    items = data.split(b"\0")
    if items[-1] == b"":
        items.pop()
    try:
        decoded = tuple(item.decode("utf-8") for item in items)
    except UnicodeDecodeError as exc:
        raise SourceIdentityError(f"{context} contains a non-UTF-8 path") from exc
    if len(decoded) != len(set(decoded)):
        raise SourceIdentityError(f"{context} contains duplicate paths")
    return tuple(sorted(decoded))


def is_relevant_untracked_path(path: str) -> bool:
    """Return whether an untracked path can affect repository validation."""

    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        return False
    if any(part in IGNORED_UNTRACKED_PARTS for part in pure.parts):
        return False
    if len(pure.parts) == 1:
        return pure.name in RELEVANT_ROOT_FILES
    return pure.parts[0] in RELEVANT_UNTRACKED_ROOTS


def _regular_file_digest(path: Path) -> tuple[int, int, str]:
    before = path.stat(follow_symlinks=False)
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise SourceIdentityError(f"cannot read source identity file {path}: {exc}") from exc
    after = path.stat(follow_symlinks=False)
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        stat.S_IMODE(before.st_mode),
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        stat.S_IMODE(after.st_mode),
    )
    if before_identity != after_identity:
        raise SourceIdentityError(f"source identity file changed while reading: {path}")
    return (
        stat.S_IMODE(after.st_mode),
        after.st_size,
        f"sha256:{digest.hexdigest()}",
    )


def _file_identity(repo_root: Path, relative_path: str) -> FileIdentity:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise SourceIdentityError(
            f"source identity path must be repository-relative: {relative_path!r}"
        )
    path = repo_root / relative_path
    if path.is_symlink():
        raise SourceIdentityError(
            "source identity refuses symlinks because their target content is "
            f"outside the closed manifest: {relative_path}"
        )
    if not path.exists():
        return FileIdentity(
            path=relative_path,
            kind="missing",
            mode=None,
            size=None,
            digest=None,
        )
    if not path.is_file():
        raise SourceIdentityError(
            f"source identity path is not a regular file or symlink: {path}"
        )
    mode, size, digest = _regular_file_digest(path)
    return FileIdentity(
        path=relative_path,
        kind="file",
        mode=mode,
        size=size,
        digest=digest,
    )


def _probe_command(name: str, arguments: Sequence[str]) -> ToolchainIdentity:
    executable = shutil.which(arguments[0])
    if executable is None:
        return ToolchainIdentity(
            name=name,
            executable=None,
            version="missing",
            available=False,
        )
    resolved = str(Path(executable).resolve())
    try:
        completed = subprocess.run(
            tuple(arguments),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            env={**os.environ, "LC_ALL": "C"},
        )
    except subprocess.TimeoutExpired:
        return ToolchainIdentity(
            name=name,
            executable=resolved,
            version="timeout",
            available=False,
        )
    except OSError as exc:
        return ToolchainIdentity(
            name=name,
            executable=resolved,
            version=f"os-error:{exc.errno}",
            available=False,
        )
    output = completed.stdout.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0:
        return ToolchainIdentity(
            name=name,
            executable=resolved,
            version=f"exit:{completed.returncode}:{output[-500:]}",
            available=False,
        )
    return ToolchainIdentity(
        name=name,
        executable=resolved,
        version=output,
        available=True,
    )


def probe_toolchains() -> tuple[ToolchainIdentity, ...]:
    """Capture Python, Node, uv, and npm executable/version identities."""

    python_version = " ".join(sys.version.split())
    python_identity = ToolchainIdentity(
        name="python",
        executable=str(Path(sys.executable).resolve()),
        version=f"{platform.python_implementation()} {python_version}",
        available=True,
    )
    return (
        python_identity,
        _probe_command("node", ("node", "--version")),
        _probe_command("uv", ("uv", "--version")),
        _probe_command("npm", ("npm", "--version")),
    )


def collect_source_identity(
    repo_root: Path,
    *,
    toolchains: Sequence[ToolchainIdentity] | None = None,
    configuration_paths: Sequence[str] = DEFAULT_CONFIGURATION_PATHS,
    lock_paths: Sequence[str] = DEFAULT_LOCK_PATHS,
) -> SourceIdentity:
    """Collect one deterministic checkout identity without consuming prior evidence."""

    try:
        resolved_root = repo_root.resolve(strict=True)
    except OSError as exc:
        raise SourceIdentityError(f"repository root does not exist: {repo_root}") from exc
    if not resolved_root.is_dir():
        raise SourceIdentityError(f"repository root is not a directory: {resolved_root}")

    commit_bytes = _run_git(resolved_root, "rev-parse", "--verify", "HEAD").strip()
    try:
        commit = commit_bytes.decode("ascii")
    except UnicodeDecodeError as exc:
        raise SourceIdentityError("git commit identity is not ASCII") from exc
    tracked_diff = _run_git(
        resolved_root,
        "diff",
        "--binary",
        "--no-ext-diff",
        "--no-textconv",
        "HEAD",
        "--",
    )
    tracked_dirty_paths = _decode_nul_paths(
        _run_git(
            resolved_root,
            "diff",
            "--name-only",
            "-z",
            "--no-renames",
            "HEAD",
            "--",
        ),
        context="tracked dirty path inventory",
    )
    untracked_paths = _decode_nul_paths(
        _run_git(
            resolved_root,
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        ),
        context="untracked path inventory",
    )
    relevant_untracked = tuple(
        _file_identity(resolved_root, path)
        for path in untracked_paths
        if is_relevant_untracked_path(path)
    )
    normalized_toolchains = tuple(
        probe_toolchains() if toolchains is None else toolchains
    )
    toolchain_names = tuple(item.name for item in normalized_toolchains)
    if toolchain_names != ("python", "node", "uv", "npm"):
        raise SourceIdentityError(
            "toolchain identities must be ordered exactly as python, node, uv, npm"
        )

    return SourceIdentity(
        commit=commit,
        tracked_diff_digest=sha256_digest(tracked_diff),
        tracked_dirty_paths=tracked_dirty_paths,
        relevant_untracked_sources=relevant_untracked,
        configurations=tuple(
            _file_identity(resolved_root, path)
            for path in sorted(set(configuration_paths))
        ),
        locks=tuple(
            _file_identity(resolved_root, path) for path in sorted(set(lock_paths))
        ),
        toolchains=normalized_toolchains,
    )
