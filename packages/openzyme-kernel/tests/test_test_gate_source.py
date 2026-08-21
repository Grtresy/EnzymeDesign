from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.test_gate.source import (  # noqa: E402
    SourceIdentityError,
    ToolchainIdentity,
    collect_source_identity,
    is_relevant_untracked_path,
)


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ("git", "-C", str(repository), *arguments),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )


def _fixture_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.email", "test-gate@example.invalid")
    _git(repository, "config", "user.name", "Test Gate")
    (repository / "packages").mkdir()
    (repository / "scripts").mkdir()
    (repository / "apps/openzyme-web-ui").mkdir(parents=True)
    (repository / "packages/example.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repository / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    (repository / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (repository / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (repository / "scripts/test-gate.toml").write_text(
        'schema_id = "fixture@1"\n',
        encoding="utf-8",
    )
    (repository / "scripts/check-mainline.sh").write_text(
        "#!/usr/bin/env bash\n",
        encoding="utf-8",
    )
    (repository / "scripts/check-v3-architecture-qualification.sh").write_text(
        "#!/usr/bin/env bash\n",
        encoding="utf-8",
    )
    (repository / "apps/openzyme-web-ui/package.json").write_text(
        '{"name":"fixture"}\n',
        encoding="utf-8",
    )
    _git(repository, "add", ".")
    _git(repository, "commit", "--quiet", "-m", "fixture")
    return repository


def _fixed_toolchains() -> tuple[ToolchainIdentity, ...]:
    return (
        ToolchainIdentity("python", "/python", "Python fixture", True),
        ToolchainIdentity("node", "/node", "vfixture", True),
        ToolchainIdentity("uv", "/uv", "uv fixture", True),
        ToolchainIdentity("npm", "/npm", "fixture", True),
    )


def test_source_identity_is_deterministic_and_tracks_all_local_source_forms(
    tmp_path: Path,
) -> None:
    repository = _fixture_repository(tmp_path)
    initial = collect_source_identity(repository, toolchains=_fixed_toolchains())
    repeated = collect_source_identity(repository, toolchains=_fixed_toolchains())
    assert repeated == initial
    assert repeated.digest == initial.digest
    assert initial.tracked_dirty_paths == ()
    assert initial.relevant_untracked_sources == ()

    (repository / "packages/example.py").write_text("VALUE = 2\n", encoding="utf-8")
    tracked_dirty = collect_source_identity(
        repository,
        toolchains=_fixed_toolchains(),
    )
    assert tracked_dirty.digest != initial.digest
    assert tracked_dirty.tracked_dirty_paths == ("packages/example.py",)
    assert tracked_dirty.tracked_diff_digest != initial.tracked_diff_digest

    (repository / "scripts/new-check.py").write_text("CHECK = True\n", encoding="utf-8")
    (repository / "unrelated.bin").write_bytes(b"ignored root scratch")
    with_untracked = collect_source_identity(
        repository,
        toolchains=_fixed_toolchains(),
    )
    assert with_untracked.digest != tracked_dirty.digest
    assert [
        item.path for item in with_untracked.relevant_untracked_sources
    ] == ["scripts/new-check.py"]


def test_relevant_untracked_policy_is_explicit_and_fail_safe() -> None:
    assert is_relevant_untracked_path("apps/example/tests/test_api.py")
    assert is_relevant_untracked_path("packages/example/src/example.py")
    assert is_relevant_untracked_path("scripts/new-check.py")
    assert is_relevant_untracked_path("openspec/changes/example/spec.md")
    assert is_relevant_untracked_path("pyproject.toml")
    assert not is_relevant_untracked_path("scratch.bin")
    assert not is_relevant_untracked_path("apps/example/node_modules/cache.js")
    assert not is_relevant_untracked_path("../outside.py")


def test_source_identity_rejects_untracked_symlink_targets(tmp_path: Path) -> None:
    repository = _fixture_repository(tmp_path)
    external = tmp_path / "external.py"
    external.write_text("VALUE = 1\n", encoding="utf-8")
    (repository / "scripts/external.py").symlink_to(external)

    with pytest.raises(SourceIdentityError, match="refuses symlinks"):
        collect_source_identity(repository, toolchains=_fixed_toolchains())
