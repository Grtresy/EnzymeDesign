from __future__ import annotations

import pytest

from openzyme_workspace_git_lfs import RepositoryCredentialRejectedError
from openzyme_workspace_git_lfs import RepositoryProvisionCredentialClaims


def _claims() -> RepositoryProvisionCredentialClaims:
    return RepositoryProvisionCredentialClaims(
        credential_id="provision-credential-1",
        workspace_id="workspace-1",
        binding_id="binding-1",
        binding_version=2,
        repository_id="repository-1",
        session_id="session-1",
        agent_member_id="member-1",
        agent_id="agent-1",
        workspace_generation=3,
        capability_lease_id="lease-1",
        issued_at="2026-08-20T00:00:00+00:00",
        expires_at="2026-08-20T00:05:00+00:00",
    )


def test_provision_claims_round_trip_preserves_read_only_contract() -> None:
    claims = _claims()

    restored = RepositoryProvisionCredentialClaims.from_payload(claims.to_payload())

    assert restored == claims
    assert [item.value for item in restored.protocols] == ["git_read", "lfs_read"]
    assert [item.value for item in restored.ref_classes] == ["read"]
    assert restored.claims_digest == claims.claims_digest


def test_provision_claims_reject_unknown_fields() -> None:
    payload = _claims().to_payload()
    payload["remote_root"] = "/secret/root"

    with pytest.raises(RepositoryCredentialRejectedError, match="schema is not closed"):
        RepositoryProvisionCredentialClaims.from_payload(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("protocols", ["git_read", "git_write"], "not read-only"),
        ("ref_classes", ["private"], "not read-only"),
    ],
)
def test_provision_claims_reject_write_authority(
    field: str,
    value: list[str],
    message: str,
) -> None:
    payload = _claims().to_payload()
    payload[field] = value

    with pytest.raises(RepositoryCredentialRejectedError, match=message):
        RepositoryProvisionCredentialClaims.from_payload(payload)


def test_provision_claims_digest_changes_with_workspace_generation() -> None:
    claims = _claims()
    payload = claims.to_payload()
    payload["workspace_generation"] = 4

    rebound = RepositoryProvisionCredentialClaims.from_payload(payload)

    assert rebound.claims_digest != claims.claims_digest
