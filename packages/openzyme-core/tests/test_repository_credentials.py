from __future__ import annotations

from dataclasses import replace
from datetime import UTC
from datetime import datetime
from datetime import timedelta
import base64
import hashlib
import hmac
import json
from pathlib import Path
import subprocess

import pytest

from openzyme_core import ActiveCapabilityLeaseAssertion
from openzyme_core import CoreRepositories
from openzyme_core import DurableRepositoryRootManager
from openzyme_core import GitRefAclValidator
from openzyme_core import GitRefUpdate
from openzyme_core import HOST_PUBLICATION_REF_OWNER
from openzyme_core import MIGRATION_HISTORICAL_REF_OWNER
from openzyme_core import RepositoryCredentialBroker
from openzyme_core import RepositoryCredentialExpiredError
from openzyme_core import RepositoryCredentialProtocol
from openzyme_core import RepositoryCredentialRejectedError
from openzyme_core import RepositoryOwnerRefService
from openzyme_core import RepositoryRefAclError
from openzyme_core import RepositoryRefOwnerRejectedError
from openzyme_core import RepositoryPrivateNamespaceRetentionService
from openzyme_core import RepositoryRootBoundary
from openzyme_core import RepositoryStorageError
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import private_ref_prefix
from openzyme_domain import GitObjectFormat
from openzyme_domain import ProjectRepositoryBinding
from openzyme_domain import RepositoryRefClass
from openzyme_domain import RepositoryRefNamespacePolicy
from openzyme_domain import Session
from openzyme_domain import SessionRepositoryBindingPin
from openzyme_runtime import RepositoryServiceSettings


NOW = datetime(2026, 8, 15, 16, 0, tzinfo=UTC)


def _settings(root: Path) -> RepositoryServiceSettings:
    git_root = root / "git"
    lfs_root = root / "lfs"
    backup_root = root / "backup"
    for path in (git_root, lfs_root, backup_root):
        path.mkdir(parents=True)
        path.chmod(0o700)
    key = root / "token.key"
    key.write_bytes(b"c1-test-signing-key" * 4)
    key.chmod(0o600)
    return RepositoryServiceSettings(
        https_origin="https://localhost:8443",
        bare_repository_root=git_root,
        lfs_object_root=lfs_root,
        backup_root=backup_root,
        credential_signing_key_file=key,
        tls_certificate_file=root / "tls.crt",
        tls_private_key_file=root / "tls.key",
        binding_inventory_file=root / "bindings.json",
        git_executable=Path("/usr/bin/git"),
        git_lfs_executable=Path("/usr/bin/false"),
        git_http_backend=Path("/usr/lib/git-core/git-http-backend"),
        credential_ttl_seconds=300,
    )


def _source_history(root: Path) -> tuple[Path, str, str]:
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
        (
            "/usr/bin/git",
            "-C",
            str(source),
            "config",
            "user.email",
            "c1@example.test",
        ),
        check=True,
    )
    readme = source / "README.md"
    readme.write_text("one\n", encoding="utf-8")
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
    readme.write_text("two\n", encoding="utf-8")
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
        binding_id="binding_credentials_v1",
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
        created_at="2026-08-15T15:55:00+00:00",
        created_by="operator:c1",
    )


def _pin(connection, binding: ProjectRepositoryBinding) -> SessionRepositoryBindingPin:
    repositories = CoreRepositories.from_connection(connection)
    repositories.project_repository_bindings.add(binding)
    session = Session.create(
        "sess_credentials",
        binding.project_id,
        "Credentials",
        "Exercise exact repository capability scopes",
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
        pinned_at=NOW.isoformat(),
    )
    repositories.session_repository_binding_pins.add(pin)
    connection.execute(
        """
        INSERT INTO repository_private_namespace_records (
            namespace_id, binding_id, binding_version, session_id,
            agent_member_id, workspace_generation, namespace_prefix,
            status, retention_deadline, opened_at, closed_at, retired_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, NULL, NULL)
        """,
        (
            "namespace_credentials_default",
            binding.binding_id,
            binding.binding_version,
            session.session_id,
            "executor_01",
            2,
            private_ref_prefix(
                binding,
                session_id=session.session_id,
                agent_member_id="executor_01",
                workspace_generation=2,
            ),
            "2026-08-16T16:00:00+00:00",
            "2026-08-15T15:59:00+00:00",
        ),
    )
    connection.execute(
        """
        INSERT INTO repository_private_namespace_holds (
            hold_id, namespace_id, hold_kind, owner_ref, created_at, released_at
        ) VALUES (?, ?, 'active_capability_lease', ?, ?, NULL)
        """,
        (
            "hold_credentials_default",
            "namespace_credentials_default",
            "lease_c1_001",
            "2026-08-15T15:59:00+00:00",
        ),
    )
    connection.commit()
    return pin


def _lease(**overrides: object) -> ActiveCapabilityLeaseAssertion:
    values: dict[str, object] = {
        "lease_id": "lease_c1_001",
        "session_id": "sess_credentials",
        "agent_member_id": "executor_01",
        "workspace_generation": 2,
        "expires_at": (NOW + timedelta(minutes=10)).isoformat(),
    }
    values.update(overrides)
    return ActiveCapabilityLeaseAssertion(**values)  # type: ignore[arg-type]


def _broker(
    connection, settings: RepositoryServiceSettings
) -> RepositoryCredentialBroker:
    return RepositoryCredentialBroker(
        connection=connection,
        signing_key_path=settings.credential_signing_key_file,
        credential_ttl_seconds=settings.credential_ttl_seconds,
    )


def test_credential_binds_pin_lease_protocol_repository_and_generation(
    tmp_path: Path,
) -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    settings = _settings(tmp_path / "service")
    binding = _binding("1" * 40)
    pin = _pin(connection, binding)
    broker = _broker(connection, settings)

    issued = broker.issue(
        binding=binding,
        pin=pin,
        lease=_lease(),
        protocols=(
            RepositoryCredentialProtocol.GIT_READ,
            RepositoryCredentialProtocol.GIT_WRITE,
        ),
        ref_classes=(RepositoryRefClass.READ, RepositoryRefClass.PRIVATE),
        now=NOW,
    )
    claims = broker.authenticate(
        issued.token,
        protocol=RepositoryCredentialProtocol.GIT_WRITE,
        repository_id=binding.repository_id,
        now=NOW,
    )

    assert claims.binding_id == pin.binding_id
    assert claims.workspace_generation == 2
    assert claims.capability_lease_id == "lease_c1_001"
    assert private_ref_prefix(
        binding,
        session_id=claims.session_id,
        agent_member_id=claims.agent_member_id,
        workspace_generation=claims.workspace_generation,
    ) == ("refs/openzyme/private/s-onsxg427mnzgkzdfnz2gsylmom/a-mv4gky3vorxxexzqge/g2")

    with pytest.raises(RepositoryCredentialRejectedError, match="audience"):
        broker.authenticate(
            issued.token,
            protocol=RepositoryCredentialProtocol.GIT_READ,
            repository_id="foreign_repo",
            now=NOW,
        )
    with pytest.raises(RepositoryCredentialRejectedError, match="protocol"):
        broker.authenticate(
            issued.token,
            protocol=RepositoryCredentialProtocol.LFS_READ,
            repository_id=binding.repository_id,
            now=NOW,
        )


def test_expiry_tamper_revocation_and_reissue_fail_explicitly(tmp_path: Path) -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    settings = _settings(tmp_path / "service")
    binding = _binding("1" * 40)
    pin = _pin(connection, binding)
    broker = _broker(connection, settings)
    arguments = {
        "binding": binding,
        "pin": pin,
        "lease": _lease(),
        "protocols": (RepositoryCredentialProtocol.LFS_READ,),
        "ref_classes": (RepositoryRefClass.READ,),
        "now": NOW,
    }
    first = broker.issue(**arguments)  # type: ignore[arg-type]
    second = broker.issue(**arguments)  # type: ignore[arg-type]

    assert second.token != first.token
    with pytest.raises(RepositoryCredentialExpiredError, match="request a new"):
        broker.authenticate(
            first.token,
            protocol=RepositoryCredentialProtocol.LFS_READ,
            repository_id=binding.repository_id,
            now=NOW + timedelta(minutes=6),
        )
    envelope = first.token.split(".")
    tampered = ".".join((envelope[0], envelope[1][:-1] + "A", envelope[2]))
    with pytest.raises(RepositoryCredentialRejectedError, match="signature"):
        broker.authenticate(
            tampered,
            protocol=RepositoryCredentialProtocol.LFS_READ,
            repository_id=binding.repository_id,
            now=NOW,
        )
    broker.revoke(first.claims.credential_id, revoked_at=NOW.isoformat())
    with pytest.raises(RepositoryCredentialRejectedError, match="revoked"):
        broker.authenticate(
            first.token,
            protocol=RepositoryCredentialProtocol.LFS_READ,
            repository_id=binding.repository_id,
            now=NOW,
        )


def test_malformed_bearer_encoding_and_json_are_stable_rejections(
    tmp_path: Path,
) -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    settings = _settings(tmp_path / "service")
    broker = _broker(connection, settings)

    with pytest.raises(RepositoryCredentialRejectedError, match="encoding"):
        broker.authenticate(
            "ozrepo1.%.%",
            protocol=RepositoryCredentialProtocol.GIT_READ,
            repository_id="repo_openzyme",
            now=NOW,
        )
    with pytest.raises(RepositoryCredentialRejectedError, match="encoding"):
        broker.authenticate(
            "ozrepo1.é.%",
            protocol=RepositoryCredentialProtocol.GIT_READ,
            repository_id="repo_openzyme",
            now=NOW,
        )

    invalid_json = b"\xff"
    signature = hmac.new(
        settings.credential_signing_key_file.read_bytes(),
        invalid_json,
        hashlib.sha256,
    ).digest()

    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    with pytest.raises(RepositoryCredentialRejectedError, match="not valid JSON"):
        broker.authenticate(
            f"ozrepo1.{encode(invalid_json)}.{encode(signature)}",
            protocol=RepositoryCredentialProtocol.GIT_READ,
            repository_id="repo_openzyme",
            now=NOW,
        )

    binding = _binding("1" * 40)
    pin = _pin(connection, binding)
    issued = broker.issue(
        binding=binding,
        pin=pin,
        lease=_lease(),
        protocols=(RepositoryCredentialProtocol.GIT_READ,),
        ref_classes=(RepositoryRefClass.READ,),
        now=NOW,
    )
    claims = issued.claims.to_payload()
    claims["unexpected_claim"] = "must not be ignored"
    encoded_claims = json.dumps(
        claims,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    extra_claim_signature = hmac.new(
        settings.credential_signing_key_file.read_bytes(),
        encoded_claims,
        hashlib.sha256,
    ).digest()
    with pytest.raises(RepositoryCredentialRejectedError, match="schema is not closed"):
        broker.authenticate(
            f"ozrepo1.{encode(encoded_claims)}.{encode(extra_claim_signature)}",
            protocol=RepositoryCredentialProtocol.GIT_READ,
            repository_id=binding.repository_id,
            now=NOW,
        )


def test_write_credentials_require_open_namespace_and_active_lease_hold(
    tmp_path: Path,
) -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    settings = _settings(tmp_path / "service")
    binding = _binding("1" * 40)
    pin = _pin(connection, binding)
    broker = _broker(connection, settings)

    with pytest.raises(RepositoryCredentialRejectedError, match="namespace record"):
        broker.issue(
            binding=binding,
            pin=pin,
            lease=_lease(
                agent_member_id="executor_missing",
                workspace_generation=3,
            ),
            protocols=(RepositoryCredentialProtocol.GIT_WRITE,),
            ref_classes=(RepositoryRefClass.PRIVATE,),
            now=NOW,
        )

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
    retention = RepositoryPrivateNamespaceRetentionService(connection, roots)
    retention.open_namespace(
        binding=binding,
        pin=pin,
        agent_member_id="executor_no_hold",
        workspace_generation=4,
        retention_deadline="2026-08-16T16:00:00+00:00",
        opened_at="2026-08-15T15:59:00+00:00",
        namespace_id="namespace_credentials_no_hold",
    )
    with pytest.raises(RepositoryCredentialRejectedError, match="lease hold"):
        broker.issue(
            binding=binding,
            pin=pin,
            lease=_lease(
                agent_member_id="executor_no_hold",
                workspace_generation=4,
            ),
            protocols=(RepositoryCredentialProtocol.LFS_WRITE,),
            ref_classes=(RepositoryRefClass.PRIVATE,),
            now=NOW,
        )

    issued = broker.issue(
        binding=binding,
        pin=pin,
        lease=_lease(),
        protocols=(
            RepositoryCredentialProtocol.GIT_READ,
            RepositoryCredentialProtocol.GIT_WRITE,
        ),
        ref_classes=(RepositoryRefClass.READ, RepositoryRefClass.PRIVATE),
        now=NOW,
    )
    retention.close_namespace(
        "namespace_credentials_default",
        closed_at="2026-08-15T16:01:00+00:00",
    )
    with pytest.raises(RepositoryCredentialRejectedError, match="open"):
        broker.authenticate(
            issued.token,
            protocol=RepositoryCredentialProtocol.GIT_WRITE,
            repository_id=binding.repository_id,
            now=NOW,
        )
    assert (
        broker.authenticate(
            issued.token,
            protocol=RepositoryCredentialProtocol.GIT_READ,
            repository_id=binding.repository_id,
            now=NOW,
        ).credential_id
        == issued.claims.credential_id
    )


def test_credential_issuance_respects_owning_unit_of_work(tmp_path: Path) -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    settings = _settings(tmp_path / "service")
    binding = _binding("1" * 40)
    pin = _pin(connection, binding)
    repositories = CoreRepositories.from_connection(connection)

    with pytest.raises(RuntimeError, match="rollback issuance"):
        with repositories.atomic(prefix="credential_issuance"):
            _broker(connection, settings).issue(
                binding=binding,
                pin=pin,
                lease=_lease(),
                protocols=(RepositoryCredentialProtocol.GIT_READ,),
                ref_classes=(RepositoryRefClass.READ,),
                now=NOW,
            )
            raise RuntimeError("rollback issuance")

    assert (
        connection.execute(
            "SELECT COUNT(*) FROM repository_credential_issuance_records"
        ).fetchone()[0]
        == 0
    )


def test_agent_credential_rejects_host_owned_ref_classes_and_bad_lease(
    tmp_path: Path,
) -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    settings = _settings(tmp_path / "service")
    binding = _binding("1" * 40)
    pin = _pin(connection, binding)
    broker = _broker(connection, settings)

    for ref_class in (
        RepositoryRefClass.PUBLICATION,
        RepositoryRefClass.HISTORICAL,
    ):
        with pytest.raises(RepositoryCredentialRejectedError, match="Host-owned"):
            broker.issue(
                binding=binding,
                pin=pin,
                lease=_lease(),
                protocols=(RepositoryCredentialProtocol.GIT_WRITE,),
                ref_classes=(ref_class,),
                now=NOW,
            )
    with pytest.raises(RepositoryCredentialRejectedError, match="not active"):
        broker.issue(
            binding=binding,
            pin=pin,
            lease=_lease(expires_at=(NOW - timedelta(seconds=1)).isoformat()),
            protocols=(RepositoryCredentialProtocol.GIT_READ,),
            ref_classes=(RepositoryRefClass.READ,),
            now=NOW,
        )
    with pytest.raises(RepositoryCredentialRejectedError, match="session"):
        broker.issue(
            binding=binding,
            pin=pin,
            lease=_lease(session_id="other_session"),
            protocols=(RepositoryCredentialProtocol.GIT_READ,),
            ref_classes=(RepositoryRefClass.READ,),
            now=NOW,
        )


def test_ref_acl_allows_only_private_create_and_fast_forward(tmp_path: Path) -> None:
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
    source, first, second = _source_history(tmp_path)
    binding = _binding(second)
    roots.create_bare_repository(binding)
    roots.import_exact_commit_from_repository(
        binding,
        source_repository=source,
        source_commit=second,
    )
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    pin = _pin(connection, binding)
    claims = (
        _broker(connection, settings)
        .issue(
            binding=binding,
            pin=pin,
            lease=_lease(),
            protocols=(RepositoryCredentialProtocol.GIT_WRITE,),
            ref_classes=(RepositoryRefClass.PRIVATE,),
            now=NOW,
        )
        .claims
    )
    validator = GitRefAclValidator(roots)
    zero = "0" * 40
    own_prefix = private_ref_prefix(
        binding,
        session_id=claims.session_id,
        agent_member_id=claims.agent_member_id,
        workspace_generation=claims.workspace_generation,
    )
    own_ref = f"{own_prefix}/work"

    validator.validate_agent_updates(
        binding=binding,
        claims=claims,
        updates=(GitRefUpdate(zero, first, own_ref),),
    )
    validator.validate_agent_updates(
        binding=binding,
        claims=claims,
        updates=(GitRefUpdate(first, second, own_ref),),
    )
    with pytest.raises(RepositoryRefAclError, match="binding identity"):
        validator.validate_agent_updates(
            binding=binding,
            claims=replace(claims, binding_id="binding_other_v1"),
            updates=(GitRefUpdate(first, second, own_ref),),
        )
    for update, message in (
        (GitRefUpdate(second, first, own_ref), "fast-forward"),
        (GitRefUpdate(second, zero, own_ref), "deletion"),
        (
            GitRefUpdate(
                zero,
                second,
                f"{binding.ref_namespace_policy.private_prefix}/foreign/work",
            ),
            "outside",
        ),
    ):
        with pytest.raises(RepositoryRefAclError, match=message):
            validator.validate_agent_updates(
                binding=binding,
                claims=claims,
                updates=(update,),
            )
    for prefix in (
        binding.ref_namespace_policy.publication_prefix,
        binding.ref_namespace_policy.historical_prefix,
    ):
        for old_oid, new_oid in (
            (zero, second),
            (first, second),
            (second, zero),
        ):
            with pytest.raises(RepositoryRefAclError, match="outside"):
                validator.validate_agent_updates(
                    binding=binding,
                    claims=claims,
                    updates=(
                        GitRefUpdate(old_oid, new_oid, f"{prefix}/agent-forbidden"),
                    ),
                )

    validator.validate_publication_create(
        binding=binding,
        updates=(GitRefUpdate(zero, second, "refs/openzyme/publications/release-1"),),
    )
    with pytest.raises(RepositoryRefAclError, match="create-only"):
        validator.validate_publication_create(
            binding=binding,
            updates=(
                GitRefUpdate(
                    first,
                    second,
                    "refs/openzyme/publications/release-1",
                ),
            ),
        )
    with pytest.raises(RepositoryRefAclError, match="deletion"):
        validator.validate_publication_create(
            binding=binding,
            updates=(
                GitRefUpdate(
                    second,
                    zero,
                    "refs/openzyme/publications/release-1",
                ),
            ),
        )
    validator.validate_historical_update(
        binding=binding,
        updates=(GitRefUpdate(zero, second, "refs/openzyme/historical/import-1"),),
    )
    with pytest.raises(RepositoryRefAclError, match="deletion"):
        validator.validate_historical_update(
            binding=binding,
            updates=(
                GitRefUpdate(
                    second,
                    zero,
                    "refs/openzyme/historical/import-1",
                ),
            ),
        )


def test_owner_ref_service_enforces_distinct_owner_and_namespace_rules(
    tmp_path: Path,
) -> None:
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
    source, first, second = _source_history(tmp_path)
    binding = _binding(second)
    roots.create_bare_repository(binding)
    roots.import_exact_commit_from_repository(
        binding,
        source_repository=source,
        source_commit=second,
    )
    service = RepositoryOwnerRefService(roots)
    zero = "0" * binding.object_format.commit_hex_length
    publication_ref = f"{binding.ref_namespace_policy.publication_prefix}/release-1"
    historical_ref = f"{binding.ref_namespace_policy.historical_prefix}/import-1"

    service.create_publication_refs(
        binding=binding,
        owner=HOST_PUBLICATION_REF_OWNER,
        updates=(GitRefUpdate(zero, second, publication_ref),),
    )
    assert dict(
        roots.list_refs(
            binding,
            prefix=binding.ref_namespace_policy.publication_prefix,
        )
    ) == {publication_ref: second}

    with pytest.raises(RepositoryRefOwnerRejectedError, match="host-publication"):
        service.create_publication_refs(
            binding=binding,
            owner=MIGRATION_HISTORICAL_REF_OWNER,
            updates=(
                GitRefUpdate(
                    zero,
                    second,
                    f"{binding.ref_namespace_policy.publication_prefix}/wrong-owner",
                ),
            ),
        )
    for update, message in (
        (GitRefUpdate(second, first, publication_ref), "create-only"),
        (GitRefUpdate(second, zero, publication_ref), "deletion"),
        (
            GitRefUpdate(
                zero,
                second,
                f"{binding.ref_namespace_policy.historical_prefix}/wrong-namespace",
            ),
            "outside",
        ),
    ):
        with pytest.raises(RepositoryRefAclError, match=message):
            service.create_publication_refs(
                binding=binding,
                owner=HOST_PUBLICATION_REF_OWNER,
                updates=(update,),
            )

    service.update_historical_refs(
        binding=binding,
        owner=MIGRATION_HISTORICAL_REF_OWNER,
        updates=(GitRefUpdate(zero, first, historical_ref),),
    )
    service.update_historical_refs(
        binding=binding,
        owner=MIGRATION_HISTORICAL_REF_OWNER,
        updates=(GitRefUpdate(first, second, historical_ref),),
    )
    assert dict(
        roots.list_refs(
            binding,
            prefix=binding.ref_namespace_policy.historical_prefix,
        )
    ) == {historical_ref: second}

    with pytest.raises(RepositoryRefOwnerRejectedError, match="migration-historical"):
        service.update_historical_refs(
            binding=binding,
            owner=HOST_PUBLICATION_REF_OWNER,
            updates=(
                GitRefUpdate(
                    zero,
                    second,
                    f"{binding.ref_namespace_policy.historical_prefix}/wrong-owner",
                ),
            ),
        )
    for update, message in (
        (GitRefUpdate(second, first, historical_ref), "fast-forward"),
        (GitRefUpdate(second, zero, historical_ref), "deletion"),
        (
            GitRefUpdate(
                zero,
                second,
                f"{binding.ref_namespace_policy.publication_prefix}/wrong-namespace",
            ),
            "outside",
        ),
    ):
        with pytest.raises(RepositoryRefAclError, match=message):
            service.update_historical_refs(
                binding=binding,
                owner=MIGRATION_HISTORICAL_REF_OWNER,
                updates=(update,),
            )


def test_owner_ref_service_rejects_non_commit_ref_target(tmp_path: Path) -> None:
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
    source, _, commit = _source_history(tmp_path)
    binding = _binding(commit)
    repository = roots.create_bare_repository(binding)
    roots.import_exact_commit_from_repository(
        binding,
        source_repository=source,
        source_commit=commit,
    )
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

    with pytest.raises(RepositoryStorageError, match="not a commit object"):
        RepositoryOwnerRefService(roots).create_publication_refs(
            binding=binding,
            owner=HOST_PUBLICATION_REF_OWNER,
            updates=(
                GitRefUpdate(
                    zero,
                    blob,
                    f"{binding.ref_namespace_policy.publication_prefix}/blob",
                ),
            ),
        )


def test_owner_ref_service_applies_exact_updates_atomically(tmp_path: Path) -> None:
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
    source, first, second = _source_history(tmp_path)
    binding = _binding(second)
    roots.create_bare_repository(binding)
    roots.import_exact_commit_from_repository(
        binding,
        source_repository=source,
        source_commit=second,
    )
    service = RepositoryOwnerRefService(roots)
    zero = "0" * binding.object_format.commit_hex_length
    prefix = binding.ref_namespace_policy.historical_prefix
    first_ref = f"{prefix}/atomic-first"
    second_ref = f"{prefix}/atomic-second"
    service.update_historical_refs(
        binding=binding,
        owner=MIGRATION_HISTORICAL_REF_OWNER,
        updates=(
            GitRefUpdate(zero, first, first_ref),
            GitRefUpdate(zero, first, second_ref),
        ),
    )

    with pytest.raises(subprocess.CalledProcessError):
        service.update_historical_refs(
            binding=binding,
            owner=MIGRATION_HISTORICAL_REF_OWNER,
            updates=(
                GitRefUpdate(first, second, first_ref),
                GitRefUpdate(second, second, second_ref),
            ),
        )

    assert dict(roots.list_refs(binding, prefix=prefix)) == {
        first_ref: first,
        second_ref: first,
    }


def test_pin_scope_drift_is_rejected_before_issuance(tmp_path: Path) -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    settings = _settings(tmp_path / "service")
    binding = _binding("1" * 40)
    pin = _pin(connection, binding)

    with pytest.raises(RepositoryCredentialRejectedError, match="pin"):
        _broker(connection, settings).issue(
            binding=binding,
            pin=replace(pin, binding_canonical_digest=f"sha256:{'2' * 64}"),
            lease=_lease(),
            protocols=(RepositoryCredentialProtocol.GIT_READ,),
            ref_classes=(RepositoryRefClass.READ,),
            now=NOW,
        )
