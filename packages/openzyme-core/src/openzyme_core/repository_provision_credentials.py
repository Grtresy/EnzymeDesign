from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from datetime import timedelta
import base64
import binascii
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import stat
from uuid import uuid4

from openzyme_domain import AgentCapabilityLeaseStatus
from openzyme_domain import AgentGitWorkspaceStatus
from openzyme_domain import RepositoryRefClass

from .repositories import CoreRepositories
from .repositories import _commit
from .repository_credentials import RepositoryCredentialExpiredError
from .repository_credentials import RepositoryCredentialProtocol
from .repository_credentials import RepositoryCredentialRejectedError


REPOSITORY_PROVISION_CREDENTIAL_SCHEMA_VERSION = (
    "repository_provision_credential@1"
)
_PROVISION_PROTOCOLS = (
    RepositoryCredentialProtocol.GIT_READ,
    RepositoryCredentialProtocol.LFS_READ,
)


@dataclass(frozen=True, slots=True)
class RepositoryProvisionCredentialClaims:
    credential_id: str
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
    schema_version: str = REPOSITORY_PROVISION_CREDENTIAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REPOSITORY_PROVISION_CREDENTIAL_SCHEMA_VERSION:
            raise ValueError("unsupported repository provision credential schema")
        for field_name in (
            "credential_id",
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

    @property
    def protocols(self) -> tuple[RepositoryCredentialProtocol, ...]:
        return _PROVISION_PROTOCOLS

    @property
    def ref_classes(self) -> tuple[RepositoryRefClass, ...]:
        return (RepositoryRefClass.READ,)

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "credential_id": self.credential_id,
            "workspace_id": self.workspace_id,
            "binding_id": self.binding_id,
            "binding_version": self.binding_version,
            "repository_id": self.repository_id,
            "session_id": self.session_id,
            "agent_member_id": self.agent_member_id,
            "agent_id": self.agent_id,
            "workspace_generation": self.workspace_generation,
            "capability_lease_id": self.capability_lease_id,
            "protocols": [item.value for item in self.protocols],
            "ref_classes": [item.value for item in self.ref_classes],
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    @property
    def claims_digest(self) -> str:
        return _digest(_canonical_json(self.to_payload()))

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, object],
    ) -> RepositoryProvisionCredentialClaims:
        if payload.get("protocols") != ["git_read", "lfs_read"]:
            raise RepositoryCredentialRejectedError(
                "provision credential protocols are not read-only"
            )
        if payload.get("ref_classes") != ["read"]:
            raise RepositoryCredentialRejectedError(
                "provision credential ref class is not read-only"
            )

        def string(name: str) -> str:
            value = payload.get(name)
            if not isinstance(value, str):
                raise RepositoryCredentialRejectedError(
                    f"provision credential {name!r} must be a string"
                )
            return value

        def positive(name: str) -> int:
            value = payload.get(name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise RepositoryCredentialRejectedError(
                    f"provision credential {name!r} must be positive"
                )
            return value

        return cls(
            schema_version=string("schema_version"),
            credential_id=string("credential_id"),
            workspace_id=string("workspace_id"),
            binding_id=string("binding_id"),
            binding_version=positive("binding_version"),
            repository_id=string("repository_id"),
            session_id=string("session_id"),
            agent_member_id=string("agent_member_id"),
            agent_id=string("agent_id"),
            workspace_generation=positive("workspace_generation"),
            capability_lease_id=string("capability_lease_id"),
            issued_at=string("issued_at"),
            expires_at=string("expires_at"),
        )


@dataclass(frozen=True, slots=True)
class IssuedRepositoryProvisionCredential:
    token: str
    claims: RepositoryProvisionCredentialClaims


@dataclass(slots=True)
class RepositoryProvisionCredentialBroker:
    connection: sqlite3.Connection
    signing_key_path: Path
    credential_ttl_seconds: int

    def issue(
        self,
        *,
        workspace_id: str,
        now: datetime,
    ) -> IssuedRepositoryProvisionCredential:
        if self.credential_ttl_seconds <= 0:
            raise ValueError("credential_ttl_seconds must be positive")
        repositories = CoreRepositories.from_connection(self.connection)
        if repositories.in_managed_transaction:
            raise RepositoryCredentialRejectedError(
                "provision credential issuance must own its transaction"
            )
        with repositories.atomic(prefix="repository_provision_credential_issue"):
            workspace = repositories.agent_git_workspaces.get(workspace_id)
            if workspace is None or workspace.status is not AgentGitWorkspaceStatus.PROVISIONING:
                raise RepositoryCredentialRejectedError(
                    "provision credential requires an exact provisioning workspace"
                )
            lease = repositories.agent_capability_leases.get(
                workspace.capability_lease_id
            )
            if (
                lease is None
                or lease.status is not AgentCapabilityLeaseStatus.PENDING_WORKSPACE
                or lease.canonical_digest
                != workspace.capability_lease_intent_digest
            ):
                raise RepositoryCredentialRejectedError(
                    "provision credential requires the exact pending lease intent"
                )
            normalized_now = now.astimezone(UTC)
            expires_at = normalized_now + timedelta(
                seconds=self.credential_ttl_seconds
            )
            claims = RepositoryProvisionCredentialClaims(
                credential_id=f"repository_provision_credential_{uuid4().hex}",
                workspace_id=workspace.workspace_id,
                binding_id=workspace.repository_binding_id,
                binding_version=workspace.repository_binding_version,
                repository_id=workspace.repository_id,
                session_id=workspace.session_id,
                agent_member_id=workspace.agent_member_id,
                agent_id=workspace.agent_id,
                workspace_generation=workspace.workspace_generation,
                capability_lease_id=workspace.capability_lease_id,
                issued_at=normalized_now.isoformat(),
                expires_at=expires_at.isoformat(),
            )
            payload = _canonical_json(claims.to_payload())
            token = (
                f"ozprovision1.{_b64encode(payload)}."
                f"{_b64encode(hmac.new(self._signing_key(), payload, hashlib.sha256).digest())}"
            )
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
                    _digest(token.encode("ascii")),
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
            _commit(self.connection)
        return IssuedRepositoryProvisionCredential(token=token, claims=claims)

    def authenticate(
        self,
        token: str,
        *,
        protocol: RepositoryCredentialProtocol,
        repository_id: str,
        now: datetime,
    ) -> RepositoryProvisionCredentialClaims:
        if protocol not in _PROVISION_PROTOCOLS:
            raise RepositoryCredentialRejectedError(
                "provision credential cannot authorize repository writes"
            )
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != "ozprovision1":
            raise RepositoryCredentialRejectedError(
                "repository provision credential has an invalid envelope"
            )
        try:
            payload = _b64decode(parts[1])
            signature = _b64decode(parts[2])
        except (binascii.Error, ValueError) as exc:
            raise RepositoryCredentialRejectedError(
                "repository provision credential encoding is invalid"
            ) from exc
        expected = hmac.new(self._signing_key(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise RepositoryCredentialRejectedError(
                "repository provision credential signature is invalid"
            )
        try:
            raw = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RepositoryCredentialRejectedError(
                "repository provision credential payload is invalid"
            ) from exc
        if not isinstance(raw, dict):
            raise RepositoryCredentialRejectedError(
                "repository provision credential payload must be an object"
            )
        claims = RepositoryProvisionCredentialClaims.from_payload(raw)
        row = self.connection.execute(
            """
            SELECT *
            FROM repository_provision_credential_records
            WHERE credential_id = ? AND token_digest = ?
            """,
            (claims.credential_id, _digest(token.encode("ascii"))),
        ).fetchone()
        if row is None or row["claims_digest"] != claims.claims_digest:
            raise RepositoryCredentialRejectedError(
                "repository provision credential is not canonical"
            )
        if row["revoked_at"] is not None:
            raise RepositoryCredentialRejectedError(
                "repository provision credential is revoked"
            )
        normalized_now = now.astimezone(UTC)
        if datetime.fromisoformat(claims.expires_at).astimezone(UTC) <= normalized_now:
            raise RepositoryCredentialExpiredError(
                "repository provision credential expired"
            )
        if claims.repository_id != repository_id:
            raise RepositoryCredentialRejectedError(
                "repository provision credential audience mismatch"
            )
        repositories = CoreRepositories.from_connection(self.connection)
        workspace = repositories.agent_git_workspaces.get(claims.workspace_id)
        lease = repositories.agent_capability_leases.get(
            claims.capability_lease_id
        )
        if (
            workspace is None
            or workspace.status is not AgentGitWorkspaceStatus.PROVISIONING
            or workspace.repository_binding_id != claims.binding_id
            or workspace.repository_binding_version != claims.binding_version
            or workspace.repository_id != claims.repository_id
            or workspace.session_id != claims.session_id
            or workspace.agent_member_id != claims.agent_member_id
            or workspace.agent_id != claims.agent_id
            or workspace.workspace_generation != claims.workspace_generation
            or workspace.capability_lease_id != claims.capability_lease_id
            or lease is None
            or lease.status is not AgentCapabilityLeaseStatus.PENDING_WORKSPACE
            or lease.canonical_digest
            != workspace.capability_lease_intent_digest
        ):
            raise RepositoryCredentialRejectedError(
                "repository provision credential pending identity drifted"
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
        _commit(self.connection)

    def _signing_key(self) -> bytes:
        if self.signing_key_path.is_symlink():
            raise RepositoryCredentialRejectedError(
                "repository credential signing key must not be a symlink"
            )
        metadata = self.signing_key_path.stat()
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise RepositoryCredentialRejectedError(
                "repository credential signing key must be owner-only mode 0600"
            )
        key = self.signing_key_path.read_bytes()
        if len(key) < 32:
            raise RepositoryCredentialRejectedError(
                "repository credential signing key is too short"
            )
        return key


def _canonical_json(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(
        f"{value}{'=' * (-len(value) % 4)}",
        altchars=b"-_",
        validate=True,
    )


__all__ = [
    "IssuedRepositoryProvisionCredential",
    "REPOSITORY_PROVISION_CREDENTIAL_SCHEMA_VERSION",
    "RepositoryProvisionCredentialBroker",
    "RepositoryProvisionCredentialClaims",
]
