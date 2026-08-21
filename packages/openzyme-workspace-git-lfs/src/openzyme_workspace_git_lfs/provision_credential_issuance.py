"""Read-only provisioning credential token and ledger mechanisms."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import sqlite3
from typing import Callable
from uuid import uuid4

from .credential_claims import RepositoryCredentialExpiredError
from .credential_claims import RepositoryCredentialRejectedError
from .credential_material import HmacRepositoryCredentialMaterialAdapter
from .credential_material import RepositoryCredentialMaterialError
from .provision_credential_claims import IssuedRepositoryProvisionCredential
from .provision_credential_claims import REPOSITORY_PROVISION_PROTOCOLS
from .provision_credential_claims import RepositoryProvisionCredentialClaims
from .ref_policy import RepositoryCredentialProtocol


def _new_provision_credential_id() -> str:
    return f"repository_provision_credential_{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class RepositoryProvisionCredentialIssueRequest:
    workspace_id: str
    binding_id: str
    binding_version: int
    repository_id: str
    session_id: str
    agent_member_id: str
    agent_id: str
    workspace_generation: int
    capability_lease_id: str
    issued_at: str
    expires_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "workspace_id",
            "binding_id",
            "repository_id",
            "session_id",
            "agent_member_id",
            "agent_id",
            "capability_lease_id",
            "issued_at",
            "expires_at",
        ):
            value = getattr(self, field_name)
            if not value or value != value.strip():
                raise ValueError(f"{field_name} must not be empty or padded")
        if self.binding_version <= 0 or self.workspace_generation <= 0:
            raise ValueError("binding version and workspace generation must be positive")
        issued = datetime.fromisoformat(self.issued_at)
        expires = datetime.fromisoformat(self.expires_at)
        if issued.tzinfo is None or expires.tzinfo is None or expires <= issued:
            raise ValueError("provision credential interval must be timezone-aware and positive")


@dataclass(slots=True)
class RepositoryProvisionCredentialIssuanceStore:
    """Persist a pre-admitted provisioning scope without granting authority."""

    connection: sqlite3.Connection
    material: HmacRepositoryCredentialMaterialAdapter
    credential_id_factory: Callable[[], str] = _new_provision_credential_id

    def issue(
        self,
        request: RepositoryProvisionCredentialIssueRequest,
    ) -> IssuedRepositoryProvisionCredential:
        claims = RepositoryProvisionCredentialClaims(
            credential_id=self.credential_id_factory(),
            workspace_id=request.workspace_id,
            binding_id=request.binding_id,
            binding_version=request.binding_version,
            repository_id=request.repository_id,
            session_id=request.session_id,
            agent_member_id=request.agent_member_id,
            agent_id=request.agent_id,
            workspace_generation=request.workspace_generation,
            capability_lease_id=request.capability_lease_id,
            issued_at=request.issued_at,
            expires_at=request.expires_at,
        )
        try:
            token = self.material.issue_token(
                envelope_prefix="ozprovision1",
                claims_payload=claims.to_payload(),
            )
        except RepositoryCredentialMaterialError as exc:
            raise RepositoryCredentialRejectedError(str(exc)) from exc
        self.connection.execute(
            """
            INSERT INTO repository_provision_credential_records (
                credential_id,
                token_digest,
                workspace_id,
                binding_id,
                binding_version,
                repository_id,
                session_id,
                agent_member_id,
                agent_id,
                workspace_generation,
                capability_lease_id,
                protocols_json,
                claims_digest,
                issued_at,
                expires_at,
                revoked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                claims.credential_id,
                self.material.token_digest(token),
                claims.workspace_id,
                claims.binding_id,
                claims.binding_version,
                claims.repository_id,
                claims.session_id,
                claims.agent_member_id,
                claims.agent_id,
                claims.workspace_generation,
                claims.capability_lease_id,
                '["git_read","lfs_read"]',
                claims.claims_digest,
                claims.issued_at,
                claims.expires_at,
            ),
        )
        return IssuedRepositoryProvisionCredential(token=token, claims=claims)

    def authenticate(
        self,
        token: str,
        *,
        protocol: RepositoryCredentialProtocol,
        repository_id: str,
        now: datetime,
    ) -> RepositoryProvisionCredentialClaims:
        if protocol not in REPOSITORY_PROVISION_PROTOCOLS:
            raise RepositoryCredentialRejectedError(
                "provision credential cannot authorize repository writes"
            )
        try:
            raw = self.material.authenticate_token(
                token,
                envelope_prefix="ozprovision1",
            )
        except RepositoryCredentialMaterialError as exc:
            message = str(exc).replace(
                "repository bearer credential",
                "repository provision credential",
            )
            raise RepositoryCredentialRejectedError(message) from exc
        claims = RepositoryProvisionCredentialClaims.from_payload(raw)
        row = self.connection.execute(
            """
            SELECT claims_digest, revoked_at
            FROM repository_provision_credential_records
            WHERE credential_id = ? AND token_digest = ?
            """,
            (claims.credential_id, self.material.token_digest(token)),
        ).fetchone()
        if row is None or row["claims_digest"] != claims.claims_digest:
            raise RepositoryCredentialRejectedError(
                "repository provision credential is not canonical"
            )
        if row["revoked_at"] is not None:
            raise RepositoryCredentialRejectedError(
                "repository provision credential is revoked"
            )
        expires_at = datetime.fromisoformat(claims.expires_at)
        if expires_at.tzinfo is None or expires_at.astimezone(UTC) <= now.astimezone(UTC):
            raise RepositoryCredentialExpiredError(
                "repository provision credential expired"
            )
        if claims.repository_id != repository_id:
            raise RepositoryCredentialRejectedError(
                "repository provision credential audience mismatch"
            )
        return claims

    def revoke(self, credential_id: str, *, revoked_at: str) -> None:
        cursor = self.connection.execute(
            """
            UPDATE repository_provision_credential_records
            SET revoked_at = ?
            WHERE credential_id = ? AND revoked_at IS NULL
            """,
            (revoked_at, credential_id),
        )
        if cursor.rowcount != 1:
            raise RepositoryCredentialRejectedError(
                f"open provision credential {credential_id!r} does not exist"
            )


__all__ = [
    "RepositoryProvisionCredentialIssueRequest",
    "RepositoryProvisionCredentialIssuanceStore",
]
