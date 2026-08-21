from __future__ import annotations

import pytest

from openzyme_contracts import RepositoryRefClass
from openzyme_workspace_git_lfs import REPOSITORY_CREDENTIAL_SCHEMA_VERSION
from openzyme_workspace_git_lfs import RepositoryCredentialClaims
from openzyme_workspace_git_lfs import RepositoryCredentialProtocol
from openzyme_workspace_git_lfs import RepositoryCredentialRejectedError


def _claims() -> RepositoryCredentialClaims:
    return RepositoryCredentialClaims(
        credential_id="credential-1",
        binding_id="binding-1",
        binding_version=2,
        repository_id="repository-1",
        session_id="session-1",
        agent_member_id="member-1",
        workspace_generation=3,
        capability_lease_id="lease-1",
        protocols=(
            RepositoryCredentialProtocol.GIT_READ,
            RepositoryCredentialProtocol.GIT_WRITE,
        ),
        ref_classes=(RepositoryRefClass.PRIVATE,),
        issued_at="2026-08-20T00:00:00+00:00",
        expires_at="2026-08-20T00:05:00+00:00",
    )


def test_closed_claims_round_trip_preserves_adapter_contract_identity() -> None:
    claims = _claims()

    restored = RepositoryCredentialClaims.from_payload(claims.to_payload())

    assert restored == claims
    assert restored.schema_version == REPOSITORY_CREDENTIAL_SCHEMA_VERSION
    assert restored.claims_digest == claims.claims_digest


def test_closed_claims_reject_unknown_fields_without_fallback() -> None:
    payload = _claims().to_payload()
    payload["ambient_authority"] = "all"

    with pytest.raises(RepositoryCredentialRejectedError, match="schema is not closed"):
        RepositoryCredentialClaims.from_payload(payload)


def test_closed_claims_reject_unknown_protocol() -> None:
    payload = _claims().to_payload()
    payload["protocols"] = ["git_read", "ssh"]

    with pytest.raises(RepositoryCredentialRejectedError):
        RepositoryCredentialClaims.from_payload(payload)


def test_claims_digest_changes_with_authority_binding() -> None:
    claims = _claims()
    payload = claims.to_payload()
    payload["capability_lease_id"] = "lease-2"

    rebound = RepositoryCredentialClaims.from_payload(payload)

    assert rebound.claims_digest != claims.claims_digest
