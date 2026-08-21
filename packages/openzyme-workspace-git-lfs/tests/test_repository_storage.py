from dataclasses import dataclass
import hashlib
from io import BytesIO
import os
from pathlib import Path
import subprocess

import pytest

from openzyme_contracts import GitObjectFormat
from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import RepositoryRefNamespacePolicy
from openzyme_workspace_git_lfs import DurableLfsObjectStore
from openzyme_workspace_git_lfs import DurableRepositoryRootManager
from openzyme_workspace_git_lfs import LfsObjectMismatchError
from openzyme_workspace_git_lfs import RepositoryIdentityMismatchError
from openzyme_workspace_git_lfs import RepositoryRootBoundary
from openzyme_workspace_git_lfs import RepositoryRootRejectedError


@dataclass(frozen=True, slots=True)
class RepositoryServiceSettings:
    bare_repository_root: Path
    lfs_object_root: Path
    backup_root: Path
    git_executable: Path


def _settings(root: Path) -> RepositoryServiceSettings:
    git_root = root / "git"
    lfs_root = root / "lfs"
    backup_root = root / "backup"
    for path in (git_root, lfs_root, backup_root):
        path.mkdir(parents=True)
        path.chmod(0o700)
    return RepositoryServiceSettings(
        bare_repository_root=git_root,
        lfs_object_root=lfs_root,
        backup_root=backup_root,
        git_executable=Path("/usr/bin/git"),
    )


def _boundary(root: Path) -> RepositoryRootBoundary:
    checkout = root / "checkout"
    cwd = root / "cwd"
    checkout.mkdir()
    cwd.mkdir()
    return RepositoryRootBoundary(
        host_checkout=checkout,
        process_cwd=cwd,
        temporary_roots=(),
    )


def _source_repository(root: Path) -> tuple[Path, str]:
    source = root / "source"
    source.mkdir()
    subprocess.run(
        ("/usr/bin/git", "init", str(source)), check=True, capture_output=True
    )
    subprocess.run(
        ("/usr/bin/git", "-C", str(source), "config", "user.name", "C1 Test"),
        check=True,
    )
    subprocess.run(
        ("/usr/bin/git", "-C", str(source), "config", "user.email", "c1@example.test"),
        check=True,
    )
    (source / "README.md").write_text("repository service\n", encoding="utf-8")
    subprocess.run(("/usr/bin/git", "-C", str(source), "add", "README.md"), check=True)
    subprocess.run(
        ("/usr/bin/git", "-C", str(source), "commit", "-m", "seed"),
        check=True,
        capture_output=True,
    )
    commit = subprocess.run(
        ("/usr/bin/git", "-C", str(source), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return source, commit


def _binding(commit: str) -> ProjectRepositoryBinding:
    return ProjectRepositoryBinding.create(
        binding_id="binding_storage_v1",
        project_id="openzyme",
        binding_version=1,
        repository_id="repo_openzyme",
        internal_git_service_id="git_openzyme_local",
        internal_git_endpoint="https://localhost:8443/repositories/repo_openzyme.git",
        lfs_service_id="lfs_openzyme_local",
        lfs_endpoint="https://localhost:8443/repositories/repo_openzyme.git/info/lfs",
        upstream_identity="github_grtresy_enzymedesign",
        upstream_url="git@github.com:Grtresy/EnzymeDesign.git",
        object_format=GitObjectFormat.SHA1,
        default_base_ref="refs/heads/dev",
        default_base_commit=commit,
        ref_namespace_policy=RepositoryRefNamespacePolicy(
            private_prefix="refs/openzyme/private",
            publication_prefix="refs/openzyme/publications",
            historical_prefix="refs/openzyme/historical",
        ),
        repository_policy_version="repository-policy-v1",
        repository_policy_digest=f"sha256:{'1' * 64}",
        created_at="2026-08-15T14:30:00+00:00",
        created_by="operator:c1",
    )


def test_durable_root_manager_creates_bare_repo_and_resolves_exact_base(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "service")
    manager = DurableRepositoryRootManager(settings, _boundary(tmp_path))
    source, commit = _source_repository(tmp_path)
    binding = _binding(commit)

    facts = manager.preflight_roots()
    repository = manager.create_bare_repository(binding)
    manager.import_exact_commit_from_repository(
        binding,
        source_repository=source,
        source_commit=commit,
    )

    assert [fact.kind for fact in facts] == ["bare_git", "lfs_objects", "backup"]
    assert repository.name == "repo_openzyme.git"
    assert manager.verify_exact_base(binding) == commit
    assert manager.list_refs(binding, prefix="refs/heads") == (
        ("refs/heads/dev", commit),
    )


def test_production_boundary_rejects_tmp_and_checkout_roots(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "service")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    manager = DurableRepositoryRootManager(
        settings,
        RepositoryRootBoundary(
            host_checkout=checkout,
            process_cwd=checkout,
        ),
    )

    with pytest.raises(RepositoryRootRejectedError, match="forbidden authority root"):
        manager.preflight_roots()


def test_production_boundary_rejects_root_containing_checkout(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "service")
    checkout = settings.bare_repository_root / "checkout"
    checkout.mkdir()
    manager = DurableRepositoryRootManager(
        settings,
        RepositoryRootBoundary(
            host_checkout=checkout,
            process_cwd=tmp_path / "cwd",
            temporary_roots=(),
        ),
    )

    with pytest.raises(RepositoryRootRejectedError, match="overlaps"):
        manager.preflight_roots()


def test_hook_install_rejects_existing_permission_drift(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "service")
    manager = DurableRepositoryRootManager(settings, _boundary(tmp_path))
    _, commit = _source_repository(tmp_path)
    binding = _binding(commit)
    repository = manager.create_bare_repository(binding)
    hook = repository / "hooks" / "pre-receive"
    hook.chmod(0o750)

    with pytest.raises(RepositoryRootRejectedError, match="permissions drifted"):
        manager.install_pre_receive_hook(binding)

    assert hook.stat().st_mode & 0o777 == 0o750


def test_pre_receive_hook_rejects_non_commit_ref_target(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "service")
    manager = DurableRepositoryRootManager(settings, _boundary(tmp_path))
    _, commit = _source_repository(tmp_path)
    binding = _binding(commit)
    repository = manager.create_bare_repository(binding)
    manager.import_exact_commit_from_repository(
        binding,
        source_repository=tmp_path / "source",
        source_commit=commit,
    )
    hook = manager.install_pre_receive_hook(binding)
    blob = (
        subprocess.run(
            (
                "/usr/bin/git",
                "--git-dir",
                str(repository),
                "hash-object",
                "-w",
                "--stdin",
            ),
            input=b"not a commit\n",
            check=True,
            capture_output=True,
        )
        .stdout.decode("ascii")
        .strip()
    )
    zero = "0" * binding.object_format.commit_hex_length

    result = subprocess.run(
        (str(hook),),
        cwd=repository,
        env={
            "GIT_DIR": ".",
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": os.defpath,
            "OPENZYME_REPOSITORY_ACTOR_KIND": "agent",
            "OPENZYME_REPOSITORY_ID": binding.repository_id,
            "OPENZYME_BINDING_ID": binding.binding_id,
            "OPENZYME_BINDING_VERSION": str(binding.binding_version),
            "OPENZYME_OBJECT_FORMAT": binding.object_format.value,
            "OPENZYME_PRIVATE_REF_PREFIX": "refs/openzyme/private/session/agent/1",
            "OPENZYME_GIT_EXECUTABLE": str(settings.git_executable),
        },
        input=(f"{zero} {blob} refs/openzyme/private/session/agent/1/checkpoint\n"),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "ref target is not a commit object" in result.stderr


def test_lfs_store_uses_repository_scoped_atomic_oid_addressing(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "service")
    manager = DurableRepositoryRootManager(settings, _boundary(tmp_path))
    store = DurableLfsObjectStore(manager)
    content = b"OpenZyme Git LFS object\n"
    oid = hashlib.sha256(content).hexdigest()

    path = store.put(
        "repo_openzyme",
        oid,
        size=len(content),
        source=BytesIO(content),
    )

    assert path.read_bytes() == content
    assert settings.lfs_object_root in path.parents
    assert settings.bare_repository_root not in path.parents
    assert store.verify("repo_openzyme", oid, size=len(content)) == path


def test_lfs_store_rejects_oid_size_and_repository_scope_mismatch(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "service")
    store = DurableLfsObjectStore(
        DurableRepositoryRootManager(settings, _boundary(tmp_path))
    )
    content = b"wrong bytes"

    with pytest.raises(LfsObjectMismatchError, match="oid or size"):
        store.put(
            "repo_openzyme",
            "1" * 64,
            size=len(content),
            source=BytesIO(content),
        )
    with pytest.raises(RepositoryIdentityMismatchError, match="filesystem-safe"):
        store.object_path("../foreign", hashlib.sha256(content).hexdigest())


def test_lfs_store_rejects_existing_repository_root_permission_drift(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "service")
    store = DurableLfsObjectStore(
        DurableRepositoryRootManager(settings, _boundary(tmp_path))
    )
    repository_root = store.repository_root("repo_openzyme")
    repository_root.chmod(0o750)

    with pytest.raises(RepositoryRootRejectedError, match="permissions drifted"):
        store.repository_root("repo_openzyme")

    assert repository_root.stat().st_mode & 0o777 == 0o750
