from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3

import pytest

from openzyme_contracts import RepositoryRefClass
from openzyme_workspace_git_lfs import HmacRepositoryCredentialMaterialAdapter
from openzyme_workspace_git_lfs import RepositoryCredentialIssueRequest
from openzyme_workspace_git_lfs import RepositoryCredentialIssuanceStore
from openzyme_workspace_git_lfs import RepositoryCredentialProtocol
from openzyme_workspace_git_lfs import RepositoryCredentialRejectedError


def _store(tmp_path: Path) -> RepositoryCredentialIssuanceStore:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE repository_credential_issuance_records (
            credential_id TEXT PRIMARY KEY,
            token_digest TEXT NOT NULL,
            binding_id TEXT NOT NULL,
            binding_version INTEGER NOT NULL,
            repository_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            agent_member_id TEXT NOT NULL,
            workspace_generation INTEGER NOT NULL,
            capability_lease_id TEXT NOT NULL,
            protocols_json TEXT NOT NULL,
            ref_classes_json TEXT NOT NULL,
            claims_digest TEXT NOT NULL,
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT
        )
        """
    )
    connection.commit()
    key = tmp_path / "repository-credential.key"
    key.write_bytes(b"k" * 32)
    key.chmod(0o600)
    return RepositoryCredentialIssuanceStore(
        connection=connection,
        material=HmacRepositoryCredentialMaterialAdapter(key),
        credential_id_factory=lambda: "credential-1",
    )


def _request() -> RepositoryCredentialIssueRequest:
    return RepositoryCredentialIssueRequest(
        binding_id="binding-1",
        binding_version=1,
        repository_id="repository-1",
        session_id="session-1",
        agent_member_id="member-1",
        workspace_generation=2,
        capability_lease_id="lease-1",
        protocols=(RepositoryCredentialProtocol.GIT_READ,),
        ref_classes=(RepositoryRefClass.READ,),
        issued_at="2026-08-20T00:00:00+00:00",
        expires_at="2026-08-20T00:05:00+00:00",
    )


def test_issuance_store_persists_authorized_scope_without_committing(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)

    issued = store.issue(_request())

    assert store.connection.in_transaction is True
    authenticated = store.authenticate(
        issued.token,
        protocol=RepositoryCredentialProtocol.GIT_READ,
        repository_id="repository-1",
        now=datetime(2026, 8, 20, 0, 1, tzinfo=UTC),
    )
    assert authenticated == issued.claims


def test_issuance_store_revokes_without_granting_fallback_authority(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    issued = store.issue(_request())
    store.revoke(issued.claims.credential_id, revoked_at="2026-08-20T00:01:00+00:00")

    with pytest.raises(RepositoryCredentialRejectedError, match="revoked"):
        store.authenticate(
            issued.token,
            protocol=RepositoryCredentialProtocol.GIT_READ,
            repository_id="repository-1",
            now=datetime(2026, 8, 20, 0, 2, tzinfo=UTC),
        )
