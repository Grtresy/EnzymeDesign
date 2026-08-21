"""Repository credential token material owned by the Git/LFS Adapter.

Authority admission, lease validation and the durable issuance/revocation ledger
remain outside this adapter.  The adapter only protects and verifies closed
claims bytes with an operator-selected key; possession of a token is never
treated as Kernel authority.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
from typing import Any


class RepositoryCredentialMaterialError(RuntimeError):
    error_code = "repository_credential_material_rejected"


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(
        f"{value}{padding}",
        altchars=b"-_",
        validate=True,
    )


@dataclass(frozen=True, slots=True)
class HmacRepositoryCredentialMaterialAdapter:
    signing_key_path: Path
    provider_id: str = "openzyme.workspace.git-lfs.hmac-credential-material@1"

    def issue_token(
        self,
        *,
        envelope_prefix: str,
        claims_payload: dict[str, Any],
    ) -> str:
        self._validate_envelope_prefix(envelope_prefix)
        payload_bytes = _canonical_json(claims_payload)
        signature = hmac.new(
            self._signing_key(), payload_bytes, hashlib.sha256
        ).digest()
        return (
            f"{envelope_prefix}.{_b64encode(payload_bytes)}."
            f"{_b64encode(signature)}"
        )

    def authenticate_token(
        self,
        token: str,
        *,
        envelope_prefix: str,
    ) -> dict[str, Any]:
        self._validate_envelope_prefix(envelope_prefix)
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != envelope_prefix:
            raise RepositoryCredentialMaterialError(
                "repository bearer credential has an invalid envelope"
            )
        try:
            payload_bytes = _b64decode(parts[1])
            signature = _b64decode(parts[2])
        except (binascii.Error, ValueError) as exc:
            raise RepositoryCredentialMaterialError(
                "repository bearer credential encoding is invalid"
            ) from exc
        expected = hmac.new(
            self._signing_key(), payload_bytes, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise RepositoryCredentialMaterialError(
                "repository bearer credential signature is invalid"
            )
        try:
            payload = json.loads(payload_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RepositoryCredentialMaterialError(
                "repository bearer credential payload is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise RepositoryCredentialMaterialError(
                "repository bearer credential payload must be an object"
            )
        return payload

    @staticmethod
    def token_digest(token: str) -> str:
        return f"sha256:{hashlib.sha256(token.encode('ascii')).hexdigest()}"

    @staticmethod
    def _validate_envelope_prefix(value: str) -> None:
        if not value or "." in value or any(character.isspace() for character in value):
            raise RepositoryCredentialMaterialError(
                "repository credential envelope prefix is invalid"
            )

    def _signing_key(self) -> bytes:
        if self.signing_key_path.is_symlink():
            raise RepositoryCredentialMaterialError(
                "repository credential signing key must not be a symlink"
            )
        try:
            metadata = self.signing_key_path.stat()
        except OSError as exc:
            raise RepositoryCredentialMaterialError(
                "repository credential signing key is unavailable"
            ) from exc
        if metadata.st_uid != os.geteuid():
            raise RepositoryCredentialMaterialError(
                "repository credential signing key has the wrong owner"
            )
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise RepositoryCredentialMaterialError(
                "repository credential signing key must have mode 0600"
            )
        try:
            key = self.signing_key_path.read_bytes()
        except OSError as exc:
            raise RepositoryCredentialMaterialError(
                "repository credential signing key is unreadable"
            ) from exc
        if len(key) < 32:
            raise RepositoryCredentialMaterialError(
                "repository credential signing key must contain at least 32 bytes"
            )
        return key


__all__ = [
    "HmacRepositoryCredentialMaterialAdapter",
    "RepositoryCredentialMaterialError",
]
