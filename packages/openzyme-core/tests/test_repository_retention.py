from __future__ import annotations

from pathlib import Path
import sqlite3
import subprocess

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import DurableRepositoryRootManager
from openzyme_core import RepositoryPrivateNamespaceHoldKind
from openzyme_core import RepositoryPrivateNamespaceRetentionService
from openzyme_core import RepositoryPrivateNamespaceStatus
from openzyme_core import RepositoryRetentionError
from openzyme_core import RepositoryRootBoundary
from openzyme_core import RepositoryStorageError
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import GitObjectFormat
from openzyme_domain import ProjectRepositoryBinding
from openzyme_domain import RepositoryRefNamespacePolicy
from openzyme_domain import Session
from openzyme_domain import SessionRepositoryBindingPin
from openzyme_runtime import RepositoryServiceSettings


def _settings(root: Path) -> RepositoryServiceSettings:
    git_root = root / "git"
    lfs_root = root / "lfs"
    backup_root = root / "backup"
    for path in (git_root, lfs_root, backup_root):
        path.mkdir(parents=True)
        path.chmod(0o700)
    return RepositoryServiceSettings(
        https_origin="https://localhost:8443",
        bare_repository_root=git_root,
        lfs_object_root=lfs_root,
        backup_root=backup_root,
        credential_signing_key_file=root / "token.key",
        tls_certificate_file=root / "tls.crt",
        tls_private_key_file=root / "tls.key",
        binding_inventory_file=root / "bindings.json",
        git_executable=Path("/usr/bin/git"),
        git_lfs_executable=Path("/usr/bin/false"),
        git_http_backend=Path("/usr/lib/git-core/git-http-backend"),
    )


def _history(root: Path) -> tuple[Path, str, str]:
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
        ("/usr/bin/git", "-C", str(source), "config", "user.email", "c1@test"),
        check=True,
    )
    content = source / "README.md"
    content.write_text("one\n", encoding="utf-8")
    subprocess.run(("/usr/bin/git", "-C", str(source), "add", "README.md"), check=True)
    subprocess.run(
        ("/usr/bin/git", "-C", str(source), "commit", "-m", "one"),
        check=True,
        capture_output=True,
    )
    first = subprocess.run(
        ("/usr/bin/git", "-C", str(source), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    content.write_text("two\n", encoding="utf-8")
    subprocess.run(("/usr/bin/git", "-C", str(source), "add", "README.md"), check=True)
    subprocess.run(
        ("/usr/bin/git", "-C", str(source), "commit", "-m", "two"),
        check=True,
        capture_output=True,
    )
    second = subprocess.run(
        ("/usr/bin/git", "-C", str(source), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return source, first, second


def _binding(commit: str) -> ProjectRepositoryBinding:
    return ProjectRepositoryBinding.create(
        binding_id="binding_retention_v1",
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
        created_at="2026-08-15T18:00:00+00:00",
        created_by="operator:c1",
    )


def _fixture(tmp_path: Path):
    settings = _settings(tmp_path / "service")
    checkout = tmp_path / "checkout"
    cwd = tmp_path / "cwd"
    checkout.mkdir()
    cwd.mkdir()
    roots = DurableRepositoryRootManager(
        settings,
        RepositoryRootBoundary(
            host_checkout=checkout,
            process_cwd=cwd,
            temporary_roots=(),
        ),
    )
    source, first, second = _history(tmp_path)
    binding = _binding(second)
    roots.create_bare_repository(binding)
    roots.import_exact_commit_from_repository(
        binding,
        source_repository=source,
        source_commit=second,
    )
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    repositories.project_repository_bindings.add(binding)
    session = Session.create(
        "sess_retention",
        "openzyme",
        "Retention",
        "Retire only a complete closed generation",
    )
    repositories.sessions.save(session)
    pin = SessionRepositoryBindingPin(
        session_id=session.session_id,
        project_id=binding.project_id,
        binding_id=binding.binding_id,
        binding_version=binding.binding_version,
        repository_id=binding.repository_id,
        resolved_base_commit=binding.default_base_commit,
        binding_canonical_digest=binding.canonical_digest,
        pinned_at="2026-08-15T18:01:00+00:00",
    )
    repositories.session_repository_binding_pins.add(pin)
    service = RepositoryPrivateNamespaceRetentionService(connection, roots)
    namespace = service.open_namespace(
        binding=binding,
        pin=pin,
        agent_member_id="agent:executor",
        workspace_generation=1,
        retention_deadline="2026-08-15T19:00:00+00:00",
        opened_at="2026-08-15T18:02:00+00:00",
        namespace_id="namespace_generation_1",
    )
    repository_path = roots.repository_path(binding.repository_id)
    subprocess.run(
        (
            "/usr/bin/git",
            "--git-dir",
            str(repository_path),
            "update-ref",
            f"{namespace.namespace_prefix}/checkpoint-1",
            first,
        ),
        check=True,
    )
    subprocess.run(
        (
            "/usr/bin/git",
            "--git-dir",
            str(repository_path),
            "update-ref",
            f"{namespace.namespace_prefix}/checkpoint-2",
            second,
        ),
        check=True,
    )
    return connection, roots, binding, service, namespace, first, second


def test_retirement_requires_closed_generation_deadline_and_no_holds(
    tmp_path: Path,
) -> None:
    _, _, binding, service, namespace, _, _ = _fixture(tmp_path)

    with pytest.raises(RepositoryRetentionError, match="closed"):
        service.retire_namespace(
            namespace.namespace_id,
            binding=binding,
            retired_at="2026-08-15T20:00:00+00:00",
            retention_owner_ref="retention:c1",
        )
    service.close_namespace(
        namespace.namespace_id,
        closed_at="2026-08-15T18:30:00+00:00",
    )
    with pytest.raises(RepositoryRetentionError, match="deadline"):
        service.retire_namespace(
            namespace.namespace_id,
            binding=binding,
            retired_at="2026-08-15T18:59:59+00:00",
            retention_owner_ref="retention:c1",
        )
    hold_id = service.add_hold(
        namespace.namespace_id,
        hold_kind=RepositoryPrivateNamespaceHoldKind.AUDIT_HOLD,
        owner_ref="audit:c1",
        created_at="2026-08-15T18:31:00+00:00",
    )
    with pytest.raises(RepositoryRetentionError, match="active retention holds"):
        service.retire_namespace(
            namespace.namespace_id,
            binding=binding,
            retired_at="2026-08-15T20:00:00+00:00",
            retention_owner_ref="retention:c1",
        )
    service.release_hold(hold_id, released_at="2026-08-15T19:30:00+00:00")


def test_receipt_is_durable_before_atomic_complete_generation_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, roots, binding, service, namespace, first, second = _fixture(tmp_path)
    service.close_namespace(
        namespace.namespace_id,
        closed_at="2026-08-15T18:30:00+00:00",
    )
    real_delete = DurableRepositoryRootManager.delete_exact_refs

    def assert_receipt_then_delete(
        root_manager: DurableRepositoryRootManager,
        candidate_binding: ProjectRepositoryBinding,
        refs: tuple[tuple[str, str], ...],
    ) -> None:
        receipt_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM repository_private_namespace_retirement_receipts
            WHERE namespace_id = ?
            """,
            (namespace.namespace_id,),
        ).fetchone()[0]
        assert receipt_count == 1
        real_delete(root_manager, candidate_binding, refs)

    monkeypatch.setattr(
        DurableRepositoryRootManager,
        "delete_exact_refs",
        assert_receipt_then_delete,
    )
    receipt = service.retire_namespace(
        namespace.namespace_id,
        binding=binding,
        retired_at="2026-08-15T20:00:00+00:00",
        retention_owner_ref="retention:c1",
        receipt_id="retirement_receipt_1",
    )

    assert receipt["terminal_commits"] == sorted([first, second])
    assert len(receipt["terminal_refs"]) == 2
    assert (
        roots.list_refs(
            binding,
            prefix=f"{namespace.namespace_prefix}/",
        )
        == ()
    )
    assert service.require_namespace(namespace.namespace_id).status is (
        RepositoryPrivateNamespaceStatus.RETIRED
    )
    with pytest.raises(sqlite3.IntegrityError, match="not retainable"):
        service.add_hold(
            namespace.namespace_id,
            hold_kind=RepositoryPrivateNamespaceHoldKind.LEGAL_HOLD,
            owner_ref="legal:c1",
            created_at="2026-08-15T20:01:00+00:00",
        )
    subprocess.run(
        (
            "/usr/bin/git",
            "--git-dir",
            str(roots.repository_path(binding.repository_id)),
            "update-ref",
            f"{namespace.namespace_prefix}/reappeared",
            second,
        ),
        check=True,
    )
    with pytest.raises(RepositoryRetentionError, match="reappeared"):
        service.retire_namespace(
            namespace.namespace_id,
            binding=binding,
            retired_at="2026-08-15T20:02:00+00:00",
            retention_owner_ref="retention:c1",
        )


def test_changed_or_partially_pruned_namespace_cannot_resume_retirement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, roots, binding, service, namespace, _, second = _fixture(tmp_path)
    service.close_namespace(
        namespace.namespace_id,
        closed_at="2026-08-15T18:30:00+00:00",
    )

    def fail_after_receipt(*args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        del args, kwargs
        raise RuntimeError("simulated deletion failure")

    monkeypatch.setattr(
        DurableRepositoryRootManager,
        "delete_exact_refs",
        fail_after_receipt,
    )
    with pytest.raises(RuntimeError, match="simulated deletion failure"):
        service.retire_namespace(
            namespace.namespace_id,
            binding=binding,
            retired_at="2026-08-15T20:00:00+00:00",
            retention_owner_ref="retention:c1",
            receipt_id="retirement_receipt_interrupted",
        )
    monkeypatch.undo()
    repository_path = roots.repository_path(binding.repository_id)
    subprocess.run(
        (
            "/usr/bin/git",
            "--git-dir",
            str(repository_path),
            "update-ref",
            "-d",
            f"{namespace.namespace_prefix}/checkpoint-1",
        ),
        check=True,
    )
    assert roots.list_refs(
        binding,
        prefix=f"{namespace.namespace_prefix}/",
    ) == ((f"{namespace.namespace_prefix}/checkpoint-2", second),)
    with pytest.raises(RepositoryRetentionError, match="changed"):
        service.retire_namespace(
            namespace.namespace_id,
            binding=binding,
            retired_at="2026-08-15T20:02:00+00:00",
            retention_owner_ref="retention:c1",
        )


def test_retirement_rejects_non_commit_terminal_ref(tmp_path: Path) -> None:
    _, roots, binding, service, namespace, _, _ = _fixture(tmp_path)
    repository = roots.repository_path(binding.repository_id)
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
    subprocess.run(
        (
            "/usr/bin/git",
            "--git-dir",
            str(repository),
            "update-ref",
            f"{namespace.namespace_prefix}/blob",
            blob,
        ),
        check=True,
    )
    service.close_namespace(
        namespace.namespace_id,
        closed_at="2026-08-15T18:30:00+00:00",
    )

    with pytest.raises(RepositoryStorageError, match="not a commit object"):
        service.retire_namespace(
            namespace.namespace_id,
            binding=binding,
            retired_at="2026-08-15T20:00:00+00:00",
            retention_owner_ref="retention:c1",
        )
