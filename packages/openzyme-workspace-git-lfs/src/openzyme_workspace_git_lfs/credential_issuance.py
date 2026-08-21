"""Repository credential token and issuance-ledger mechanisms.

This module persists and verifies an already-authorized Git/LFS credential
scope.  It does not inspect or grant Kernel authority, leases, Session pins, or
private namespace ownership.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import sqlite3
from typing import Callable
from uuid import uuid4

from openzyme_contracts import RepositoryRefClass

from .credential_claims import IssuedRepositoryCredential
from .credential_claims import RepositoryCredentialClaims
from .credential_claims import RepositoryCredentialExpiredError
from .credential_claims import RepositoryCredentialRejectedError
from .credential_material import HmacRepositoryCredentialMaterialAdapter
from .credential_material import RepositoryCredentialMaterialError
from .ref_policy import RepositoryCredentialProtocol


def _new_repository_credential_id() -> str:
    return f"repository_credential_{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class RepositoryCredentialIssueRequest:
    """Exact scope admitted by the Kernel-facing application service."""

    binding_id: str
    binding_version: int
    repository_id: str
    session_id: str
    agent_member_id: str
    workspace_generation: int
    capability_lease_id: str
    protocols: tuple[RepositoryCredentialProtocol, ...]
    ref_classes: tuple[RepositoryRefClass, ...]
    issued_at: str
    expires_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "binding_id",
            "repository_id",
            "session_id",
            "agent_member_id",
            "capability_lease_id",
            "issued_at",
            "expires_at",
        ):
            value = getattr(self, field_name)
            if not value or value != value.strip():
                raise ValueError(f"{field_name} must not be empty or padded")
        if self.binding_version <= 0 or self.workspace_generation <= 0:
            raise ValueError("binding version and workspace generation must be positive")
        if not self.protocols or len(set(self.protocols)) != len(self.protocols):
            raise ValueError("protocols must be non-empty and unique")
        if not self.ref_classes or len(set(self.ref_classes)) != len(self.ref_classes):
            raise ValueError("ref classes must be non-empty and unique")
        issued = datetime.fromisoformat(self.issued_at)
        expires = datetime.fromisoformat(self.expires_at)
        if issued.tzinfo is None or expires.tzinfo is None or expires <= issued:
            raise ValueError("credential issue interval must be timezone-aware and positive")


@dataclass(slots=True)
class RepositoryCredentialIssuanceStore:
    """Adapter-owned token/ledger mechanism with caller-owned transaction."""

    connection: sqlite3.Connection
    material: HmacRepositoryCredentialMaterialAdapter
    credential_id_factory: Callable[[], str] = _new_repository_credential_id

    def issue(
        self,
        request: RepositoryCredentialIssueRequest,
    ) -> IssuedRepositoryCredential:
        claims = RepositoryCredentialClaims(
            credential_id=self.credential_id_factory(),
            binding_id=request.binding_id,
            binding_version=request.binding_version,
            repository_id=request.repository_id,
            session_id=request.session_id,
            agent_member_id=request.agent_member_id,
            workspace_generation=request.workspace_generation,
            capability_lease_id=request.capability_lease_id,
            protocols=request.protocols,
            ref_classes=request.ref_classes,
            issued_at=request.issued_at,
            expires_at=request.expires_at,
        )
        try:
            token = self.material.issue_token(
                envelope_prefix="ozrepo1",
                claims_payload=claims.to_payload(),
            )
        except RepositoryCredentialMaterialError as exc:
            raise RepositoryCredentialRejectedError(str(exc)) from exc
        self.connection.execute(
            """
            INSERT INTO repository_credential_issuance_records (
                credential_id,
                token_digest,
                binding_id,
                binding_version,
                repository_id,
                session_id,
                agent_member_id,
                workspace_generation,
                capability_lease_id,
                protocols_json,
                ref_classes_json,
                claims_digest,
                issued_at,
                expires_at,
                revoked_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                claims.credential_id,
                self.material.token_digest(token),
                claims.binding_id,
                claims.binding_version,
                claims.repository_id,
                claims.session_id,
                claims.agent_member_id,
                claims.workspace_generation,
                claims.capability_lease_id,
                json.dumps([item.value for item in claims.protocols]),
                json.dumps([item.value for item in claims.ref_classes]),
                claims.claims_digest,
                claims.issued_at,
                claims.expires_at,
            ),
        )
        return IssuedRepositoryCredential(token=token, claims=claims)

    def authenticate(
        self,
        token: str,
        *,
        protocol: RepositoryCredentialProtocol,
        repository_id: str,
        now: datetime,
    ) -> RepositoryCredentialClaims:
        try:
            raw_payload = self.material.authenticate_token(
                token,
                envelope_prefix="ozrepo1",
            )
        except RepositoryCredentialMaterialError as exc:
            raise RepositoryCredentialRejectedError(str(exc)) from exc
        claims = RepositoryCredentialClaims.from_payload(raw_payload)
        row = self.connection.execute(
            """
            SELECT claims_digest, revoked_at
            FROM repository_credential_issuance_records
            WHERE credential_id = ? AND token_digest = ?
            """,
            (claims.credential_id, self.material.token_digest(token)),
        ).fetchone()
        if row is None:
            raise RepositoryCredentialRejectedError(
                "repository bearer credential has no issuance record"
            )
        if row["claims_digest"] != claims.claims_digest:
            raise RepositoryCredentialRejectedError(
                "repository bearer credential claims do not match issuance"
            )
        if row["revoked_at"] is not None:
            raise RepositoryCredentialRejectedError(
                "repository bearer credential has been revoked"
            )
        expires_at = datetime.fromisoformat(claims.expires_at)
        if expires_at.tzinfo is None or expires_at.astimezone(UTC) <= now.astimezone(UTC):
            raise RepositoryCredentialExpiredError(
                "repository bearer credential has expired; request a new credential"
            )
        if claims.repository_id != repository_id:
            raise RepositoryCredentialRejectedError(
                "repository bearer credential audience does not match repository"
            )
        if protocol not in claims.protocols:
            raise RepositoryCredentialRejectedError(
                "repository bearer credential does not authorize this protocol"
            )
        return claims

    def revoke(self, credential_id: str, *, revoked_at: str) -> None:
        cursor = self.connection.execute(
            """
            UPDATE repository_credential_issuance_records
            SET revoked_at = ?
            WHERE credential_id = ? AND revoked_at IS NULL
            """,
            (revoked_at, credential_id),
        )
        if cursor.rowcount != 1:
            raise RepositoryCredentialRejectedError(
                f"active credential {credential_id!r} does not exist"
            )


__all__ = [
    "RepositoryCredentialIssueRequest",
    "RepositoryCredentialIssuanceStore",
]
