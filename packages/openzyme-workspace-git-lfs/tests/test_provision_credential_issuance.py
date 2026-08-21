from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3

import pytest

from openzyme_workspace_git_lfs import HmacRepositoryCredentialMaterialAdapter
from openzyme_workspace_git_lfs import RepositoryCredentialProtocol
from openzyme_workspace_git_lfs import RepositoryCredentialRejectedError
from openzyme_workspace_git_lfs import RepositoryProvisionCredentialIssueRequest
from openzyme_workspace_git_lfs import RepositoryProvisionCredentialIssuanceStore


def _store(tmp_path: Path) -> RepositoryProvisionCredentialIssuanceStore:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE repository_provision_credential_records (
            credential_id TEXT PRIMARY KEY,
            token_digest TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            binding_id TEXT NOT NULL,
            binding_version INTEGER NOT NULL,
            repository_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            agent_member_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            workspace_generation INTEGER NOT NULL,
            capability_lease_id TEXT NOT NULL,
            protocols_json TEXT NOT NULL,
            claims_digest TEXT NOT NULL,
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT
        )
        """
    )
    connection.commit()
    key = tmp_path / "repository-provision-credential.key"
    key.write_bytes(b"p" * 32)
    key.chmod(0o600)
    return RepositoryProvisionCredentialIssuanceStore(
        connection=connection,
        material=HmacRepositoryCredentialMaterialAdapter(key),
        credential_id_factory=lambda: "provision-credential-1",
    )


def _request() -> RepositoryProvisionCredentialIssueRequest:
    return RepositoryProvisionCredentialIssueRequest(
        workspace_id="workspace-1",
        binding_id="binding-1",
        binding_version=1,
        repository_id="repository-1",
        session_id="session-1",
        agent_member_id="member-1",
        agent_id="agent-1",
        workspace_generation=2,
        capability_lease_id="lease-1",
        issued_at="2026-08-20T00:00:00+00:00",
        expires_at="2026-08-20T00:05:00+00:00",
    )


def test_provision_issuance_is_read_only_and_caller_transaction_owned(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    issued = store.issue(_request())

    assert store.connection.in_transaction is True
    authenticated = store.authenticate(
        issued.token,
        protocol=RepositoryCredentialProtocol.LFS_READ,
        repository_id="repository-1",
        now=datetime(2026, 8, 20, 0, 1, tzinfo=UTC),
    )
    assert authenticated == issued.claims

    with pytest.raises(RepositoryCredentialRejectedError, match="cannot authorize"):
        store.authenticate(
            issued.token,
            protocol=RepositoryCredentialProtocol.GIT_WRITE,
            repository_id="repository-1",
            now=datetime(2026, 8, 20, 0, 1, tzinfo=UTC),
        )


def test_provision_issuance_revocation_has_no_fallback(tmp_path: Path) -> None:
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
