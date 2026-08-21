from pathlib import Path

import pytest

from openzyme_workspace_git_lfs import HmacRepositoryCredentialMaterialAdapter
from openzyme_workspace_git_lfs import RepositoryCredentialMaterialError


def _adapter(tmp_path: Path) -> HmacRepositoryCredentialMaterialAdapter:
    key = tmp_path / "repository-credential.key"
    key.write_bytes(b"k" * 32)
    key.chmod(0o600)
    return HmacRepositoryCredentialMaterialAdapter(key)


def test_material_round_trip_preserves_closed_claims_bytes(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    claims = {
        "schema_version": "repository_credential@1",
        "credential_id": "credential-1",
        "session_id": "session-1",
    }

    token = adapter.issue_token(envelope_prefix="ozrepo1", claims_payload=claims)

    assert token.startswith("ozrepo1.")
    assert adapter.authenticate_token(token, envelope_prefix="ozrepo1") == claims
    assert adapter.token_digest(token).startswith("sha256:")


def test_material_rejects_tamper_without_fallback(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    token = adapter.issue_token(
        envelope_prefix="ozrepo1",
        claims_payload={"schema_version": "repository_credential@1"},
    )
    prefix, payload, signature = token.split(".")
    tampered = f"{prefix}.{payload}.{signature[:-1]}A"

    with pytest.raises(RepositoryCredentialMaterialError, match="signature"):
        adapter.authenticate_token(tampered, envelope_prefix="ozrepo1")


def test_material_rejects_non_private_key_file(tmp_path: Path) -> None:
    key = tmp_path / "repository-credential.key"
    key.write_bytes(b"k" * 32)
    key.chmod(0o644)
    adapter = HmacRepositoryCredentialMaterialAdapter(key)

    with pytest.raises(RepositoryCredentialMaterialError, match="mode 0600"):
        adapter.issue_token(
            envelope_prefix="ozrepo1",
            claims_payload={"schema_version": "repository_credential@1"},
        )


def test_material_does_not_accept_another_envelope(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    token = adapter.issue_token(
        envelope_prefix="ozrepo1",
        claims_payload={"schema_version": "repository_credential@1"},
    )

    with pytest.raises(RepositoryCredentialMaterialError, match="invalid envelope"):
        adapter.authenticate_token(token, envelope_prefix="ozprovision1")
