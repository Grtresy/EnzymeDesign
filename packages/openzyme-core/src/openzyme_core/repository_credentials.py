from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from enum import StrEnum
import base64
import binascii
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import stat
from typing import Any
from uuid import uuid4

from openzyme_domain import ProjectRepositoryBinding
from openzyme_domain import RepositoryRefClass
from openzyme_domain import SessionRepositoryBindingPin

from .repository_storage import DurableRepositoryRootManager
from .repositories import _commit


REPOSITORY_CREDENTIAL_SCHEMA_VERSION = "repository_credential@1"


class RepositoryCredentialProtocol(StrEnum):
    GIT_READ = "git_read"
    GIT_WRITE = "git_write"
    LFS_READ = "lfs_read"
    LFS_WRITE = "lfs_write"


class RepositoryCredentialError(RuntimeError):
    error_code = "repository_credential_error"


class RepositoryCredentialRejectedError(RepositoryCredentialError):
    error_code = "repository_credential_rejected"


class RepositoryCredentialExpiredError(RepositoryCredentialError):
    error_code = "repository_credential_expired"


class RepositoryRefAclError(RuntimeError):
    error_code = "repository_ref_acl_rejected"


def _parse_utc(value: str, *, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC)


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(
        f"{value}{padding}",
        altchars=b"-_",
        validate=True,
    )


def _require_string(payload: dict[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value:
        raise RepositoryCredentialRejectedError(
            f"credential claim {field_name!r} must be a non-empty string"
        )
    return value


def _require_positive_int(payload: dict[str, Any], field_name: str) -> int:
    value = payload.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RepositoryCredentialRejectedError(
            f"credential claim {field_name!r} must be a positive integer"
        )
    return value


def _require_string_list(payload: dict[str, Any], field_name: str) -> list[str]:
    value = payload.get(field_name)
    if not isinstance(value, list) or not value:
        raise RepositoryCredentialRejectedError(
            f"credential claim {field_name!r} must be a non-empty list"
        )
    if not all(isinstance(item, str) and item for item in value):
        raise RepositoryCredentialRejectedError(
            f"credential claim {field_name!r} must contain strings"
        )
    return value


@dataclass(frozen=True, slots=True)
class ActiveCapabilityLeaseAssertion:
    lease_id: str
    session_id: str
    agent_member_id: str
    workspace_generation: int
    expires_at: str

    def assert_active(self, *, now: datetime) -> None:
        if not self.lease_id:
            raise RepositoryCredentialRejectedError("capability lease id is required")
        if self.workspace_generation <= 0:
            raise RepositoryCredentialRejectedError(
                "capability lease workspace generation must be positive"
            )
        if _parse_utc(self.expires_at, field_name="capability lease expires_at") <= now:
            raise RepositoryCredentialRejectedError("capability lease is not active")


def private_ref_prefix(
    binding: ProjectRepositoryBinding,
    *,
    session_id: str,
    agent_member_id: str,
    workspace_generation: int,
) -> str:
    if workspace_generation <= 0:
        raise ValueError("workspace_generation must be positive")
    if not session_id or not agent_member_id:
        raise ValueError("session_id and agent_member_id must not be empty")

    def encode_component(value: str) -> str:
        encoded = base64.b32encode(value.encode("utf-8")).rstrip(b"=")
        return encoded.decode("ascii").lower()

    return (
        f"{binding.ref_namespace_policy.private_prefix}/"
        f"s-{encode_component(session_id)}/"
        f"a-{encode_component(agent_member_id)}/g{workspace_generation}"
    )


@dataclass(frozen=True, slots=True)
class RepositoryCredentialClaims:
    credential_id: str
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
    schema_version: str = REPOSITORY_CREDENTIAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REPOSITORY_CREDENTIAL_SCHEMA_VERSION:
            raise ValueError("unsupported repository credential schema version")
        for field_name in (
            "credential_id",
            "binding_id",
            "repository_id",
            "session_id",
            "agent_member_id",
            "capability_lease_id",
        ):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} must not be empty")
        if self.binding_version <= 0 or self.workspace_generation <= 0:
            raise ValueError(
                "binding version and workspace generation must be positive"
            )
        if not self.protocols or len(set(self.protocols)) != len(self.protocols):
            raise ValueError("protocols must be non-empty and unique")
        if not all(
            isinstance(item, RepositoryCredentialProtocol) for item in self.protocols
        ):
            raise TypeError(
                "protocols must contain RepositoryCredentialProtocol values"
            )
        if not self.ref_classes or len(set(self.ref_classes)) != len(self.ref_classes):
            raise ValueError("ref classes must be non-empty and unique")
        if not all(isinstance(item, RepositoryRefClass) for item in self.ref_classes):
            raise TypeError("ref_classes must contain RepositoryRefClass values")
        issued_at = _parse_utc(self.issued_at, field_name="issued_at")
        expires_at = _parse_utc(self.expires_at, field_name="expires_at")
        if expires_at <= issued_at:
            raise ValueError("credential expires_at must be later than issued_at")

    def to_payload(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "protocols": [item.value for item in self.protocols],
            "ref_classes": [item.value for item in self.ref_classes],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "RepositoryCredentialClaims":
        expected_fields = {
            "credential_id",
            "binding_id",
            "binding_version",
            "repository_id",
            "session_id",
            "agent_member_id",
            "workspace_generation",
            "capability_lease_id",
            "protocols",
            "ref_classes",
            "issued_at",
            "expires_at",
            "schema_version",
        }
        if set(payload) != expected_fields:
            raise RepositoryCredentialRejectedError(
                "repository credential claims schema is not closed"
            )
        schema_version = _require_string(payload, "schema_version")
        if schema_version != REPOSITORY_CREDENTIAL_SCHEMA_VERSION:
            raise RepositoryCredentialRejectedError(
                "unsupported repository credential schema version"
            )
        try:
            protocols = tuple(
                RepositoryCredentialProtocol(item)
                for item in _require_string_list(payload, "protocols")
            )
            ref_classes = tuple(
                RepositoryRefClass(item)
                for item in _require_string_list(payload, "ref_classes")
            )
            return cls(
                credential_id=_require_string(payload, "credential_id"),
                binding_id=_require_string(payload, "binding_id"),
                binding_version=_require_positive_int(payload, "binding_version"),
                repository_id=_require_string(payload, "repository_id"),
                session_id=_require_string(payload, "session_id"),
                agent_member_id=_require_string(payload, "agent_member_id"),
                workspace_generation=_require_positive_int(
                    payload, "workspace_generation"
                ),
                capability_lease_id=_require_string(payload, "capability_lease_id"),
                protocols=protocols,
                ref_classes=ref_classes,
                issued_at=_require_string(payload, "issued_at"),
                expires_at=_require_string(payload, "expires_at"),
                schema_version=schema_version,
            )
        except ValueError as exc:
            raise RepositoryCredentialRejectedError(str(exc)) from exc

    @property
    def claims_digest(self) -> str:
        return _digest_bytes(_canonical_json(self.to_payload()))


@dataclass(frozen=True, slots=True)
class IssuedRepositoryCredential:
    token: str
    claims: RepositoryCredentialClaims


@dataclass(slots=True)
class RepositoryCredentialBroker:
    connection: sqlite3.Connection
    signing_key_path: Path
    credential_ttl_seconds: int

    def _require_open_write_namespace(
        self,
        *,
        binding_id: str,
        binding_version: int,
        session_id: str,
        agent_member_id: str,
        workspace_generation: int,
        capability_lease_id: str,
        expected_prefix: str | None = None,
    ) -> None:
        namespace = self.connection.execute(
            """
            SELECT namespace_id, namespace_prefix, status
            FROM repository_private_namespace_records
            WHERE binding_id = ?
              AND binding_version = ?
              AND session_id = ?
              AND agent_member_id = ?
              AND workspace_generation = ?
            """,
            (
                binding_id,
                binding_version,
                session_id,
                agent_member_id,
                workspace_generation,
            ),
        ).fetchone()
        if namespace is None:
            raise RepositoryCredentialRejectedError(
                "repository writes require an exact private namespace record"
            )
        if namespace["status"] != "open":
            raise RepositoryCredentialRejectedError(
                "repository writes require an open private namespace"
            )
        if (
            expected_prefix is not None
            and namespace["namespace_prefix"] != expected_prefix
        ):
            raise RepositoryCredentialRejectedError(
                "private namespace prefix does not match the repository binding"
            )
        hold = self.connection.execute(
            """
            SELECT 1
            FROM repository_private_namespace_holds
            WHERE namespace_id = ?
              AND hold_kind = 'active_capability_lease'
              AND owner_ref = ?
              AND released_at IS NULL
            """,
            (namespace["namespace_id"], capability_lease_id),
        ).fetchone()
        if hold is None:
            raise RepositoryCredentialRejectedError(
                "repository writes require an active capability lease hold"
            )

    def _signing_key(self) -> bytes:
        if self.signing_key_path.is_symlink():
            raise RepositoryCredentialRejectedError(
                "repository credential signing key must not be a symlink"
            )
        metadata = self.signing_key_path.stat()
        if metadata.st_uid != os.geteuid():
            raise RepositoryCredentialRejectedError(
                "repository credential signing key has the wrong owner"
            )
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise RepositoryCredentialRejectedError(
                "repository credential signing key must have mode 0600"
            )
        key = self.signing_key_path.read_bytes()
        if len(key) < 32:
            raise RepositoryCredentialRejectedError(
                "repository credential signing key must contain at least 32 bytes"
            )
        return key

    def issue(
        self,
        *,
        binding: ProjectRepositoryBinding,
        pin: SessionRepositoryBindingPin,
        lease: ActiveCapabilityLeaseAssertion,
        protocols: tuple[RepositoryCredentialProtocol, ...],
        ref_classes: tuple[RepositoryRefClass, ...],
        now: datetime,
    ) -> IssuedRepositoryCredential:
        now = now.astimezone(UTC)
        lease.assert_active(now=now)
        if self.credential_ttl_seconds <= 0:
            raise ValueError("credential_ttl_seconds must be positive")
        if (
            pin.binding_id != binding.binding_id
            or pin.binding_version != binding.binding_version
            or pin.repository_id != binding.repository_id
            or pin.binding_canonical_digest != binding.canonical_digest
            or pin.resolved_base_commit != binding.default_base_commit
        ):
            raise RepositoryCredentialRejectedError(
                "session repository pin does not match the requested binding"
            )
        if lease.session_id != pin.session_id:
            raise RepositoryCredentialRejectedError(
                "capability lease session does not match repository pin"
            )
        if any(
            item
            in {
                RepositoryRefClass.PUBLICATION,
                RepositoryRefClass.HISTORICAL,
                RepositoryRefClass.RETENTION,
            }
            for item in ref_classes
        ):
            raise RepositoryCredentialRejectedError(
                "agent credentials cannot authorize Host-owned ref namespaces"
            )
        if any(
            item in protocols
            for item in (
                RepositoryCredentialProtocol.GIT_WRITE,
                RepositoryCredentialProtocol.LFS_WRITE,
            )
        ) and (RepositoryRefClass.PRIVATE not in ref_classes):
            raise RepositoryCredentialRejectedError(
                "repository write credentials require the private ref class"
            )
        if any(
            item in protocols
            for item in (
                RepositoryCredentialProtocol.GIT_WRITE,
                RepositoryCredentialProtocol.LFS_WRITE,
            )
        ):
            self._require_open_write_namespace(
                binding_id=binding.binding_id,
                binding_version=binding.binding_version,
                session_id=pin.session_id,
                agent_member_id=lease.agent_member_id,
                workspace_generation=lease.workspace_generation,
                capability_lease_id=lease.lease_id,
                expected_prefix=private_ref_prefix(
                    binding,
                    session_id=pin.session_id,
                    agent_member_id=lease.agent_member_id,
                    workspace_generation=lease.workspace_generation,
                ),
            )
        expires_at = min(
            now + timedelta(seconds=self.credential_ttl_seconds),
            _parse_utc(lease.expires_at, field_name="capability lease expires_at"),
        )
        claims = RepositoryCredentialClaims(
            credential_id=f"repository_credential_{uuid4().hex}",
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            session_id=pin.session_id,
            agent_member_id=lease.agent_member_id,
            workspace_generation=lease.workspace_generation,
            capability_lease_id=lease.lease_id,
            protocols=protocols,
            ref_classes=ref_classes,
            issued_at=now.isoformat(),
            expires_at=expires_at.isoformat(),
        )
        payload_bytes = _canonical_json(claims.to_payload())
        signature = hmac.new(
            self._signing_key(), payload_bytes, hashlib.sha256
        ).digest()
        token = f"ozrepo1.{_b64encode(payload_bytes)}.{_b64encode(signature)}"
        token_digest = _digest_bytes(token.encode("ascii"))
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
                token_digest,
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
        _commit(self.connection)
        return IssuedRepositoryCredential(token=token, claims=claims)

    def authenticate(
        self,
        token: str,
        *,
        protocol: RepositoryCredentialProtocol,
        repository_id: str,
        now: datetime,
    ) -> RepositoryCredentialClaims:
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != "ozrepo1":
            raise RepositoryCredentialRejectedError(
                "repository bearer credential has an invalid envelope"
            )
        try:
            payload_bytes = _b64decode(parts[1])
            signature = _b64decode(parts[2])
        except (binascii.Error, ValueError) as exc:
            raise RepositoryCredentialRejectedError(
                "repository bearer credential encoding is invalid"
            ) from exc
        expected = hmac.new(self._signing_key(), payload_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise RepositoryCredentialRejectedError(
                "repository bearer credential signature is invalid"
            )
        try:
            raw_payload = json.loads(payload_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RepositoryCredentialRejectedError(
                "repository bearer credential payload is not valid JSON"
            ) from exc
        if not isinstance(raw_payload, dict):
            raise RepositoryCredentialRejectedError(
                "repository bearer credential payload must be an object"
            )
        claims = RepositoryCredentialClaims.from_payload(raw_payload)
        row = self.connection.execute(
            """
            SELECT *
            FROM repository_credential_issuance_records
            WHERE credential_id = ? AND token_digest = ?
            """,
            (claims.credential_id, _digest_bytes(token.encode("ascii"))),
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
        now = now.astimezone(UTC)
        if _parse_utc(claims.expires_at, field_name="expires_at") <= now:
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
        if protocol in {
            RepositoryCredentialProtocol.GIT_WRITE,
            RepositoryCredentialProtocol.LFS_WRITE,
        }:
            self._require_open_write_namespace(
                binding_id=claims.binding_id,
                binding_version=claims.binding_version,
                session_id=claims.session_id,
                agent_member_id=claims.agent_member_id,
                workspace_generation=claims.workspace_generation,
                capability_lease_id=claims.capability_lease_id,
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
        _commit(self.connection)


@dataclass(frozen=True, slots=True)
class GitRefUpdate:
    old_oid: str
    new_oid: str
    ref_name: str

    def is_create(self, *, object_hex_length: int) -> bool:
        return self.old_oid == "0" * object_hex_length

    def is_delete(self, *, object_hex_length: int) -> bool:
        return self.new_oid == "0" * object_hex_length


@dataclass(slots=True)
class GitRefAclValidator:
    roots: DurableRepositoryRootManager

    def validate_agent_updates(
        self,
        *,
        binding: ProjectRepositoryBinding,
        claims: RepositoryCredentialClaims,
        updates: tuple[GitRefUpdate, ...],
    ) -> None:
        if (
            claims.binding_id != binding.binding_id
            or claims.binding_version != binding.binding_version
            or claims.repository_id != binding.repository_id
        ):
            raise RepositoryRefAclError(
                "credential binding identity does not match repository binding"
            )
        if RepositoryCredentialProtocol.GIT_WRITE not in claims.protocols:
            raise RepositoryRefAclError("credential does not authorize Git writes")
        if RepositoryRefClass.PRIVATE not in claims.ref_classes:
            raise RepositoryRefAclError("credential does not authorize private refs")
        expected_prefix = private_ref_prefix(
            binding,
            session_id=claims.session_id,
            agent_member_id=claims.agent_member_id,
            workspace_generation=claims.workspace_generation,
        )
        for update in updates:
            self._validate_oid_lengths(binding, update)
            if not update.ref_name.startswith(f"{expected_prefix}/"):
                raise RepositoryRefAclError(
                    "agent ref update is outside its exact private namespace"
                )
            if update.is_delete(
                object_hex_length=binding.object_format.commit_hex_length
            ):
                raise RepositoryRefAclError("agent ref deletion is forbidden")
            if update.is_create(
                object_hex_length=binding.object_format.commit_hex_length
            ):
                continue
            if not self.roots.is_ancestor(
                binding,
                ancestor=update.old_oid,
                descendant=update.new_oid,
            ):
                raise RepositoryRefAclError(
                    "agent private ref updates must be fast-forward"
                )

    def validate_publication_create(
        self,
        *,
        binding: ProjectRepositoryBinding,
        updates: tuple[GitRefUpdate, ...],
    ) -> None:
        prefix = binding.ref_namespace_policy.publication_prefix
        for update in updates:
            self._validate_oid_lengths(binding, update)
            if not update.ref_name.startswith(f"{prefix}/"):
                raise RepositoryRefAclError(
                    "publication update is outside the publication namespace"
                )
            if update.is_delete(
                object_hex_length=binding.object_format.commit_hex_length
            ):
                raise RepositoryRefAclError("publication ref deletion is forbidden")
            if not update.is_create(
                object_hex_length=binding.object_format.commit_hex_length
            ):
                raise RepositoryRefAclError("publication refs are create-only")

    def validate_historical_update(
        self,
        *,
        binding: ProjectRepositoryBinding,
        updates: tuple[GitRefUpdate, ...],
    ) -> None:
        prefix = binding.ref_namespace_policy.historical_prefix
        for update in updates:
            self._validate_oid_lengths(binding, update)
            if not update.ref_name.startswith(f"{prefix}/"):
                raise RepositoryRefAclError(
                    "historical update is outside the historical namespace"
                )
            if update.is_delete(
                object_hex_length=binding.object_format.commit_hex_length
            ):
                raise RepositoryRefAclError("historical ref deletion is forbidden")
            if update.is_create(
                object_hex_length=binding.object_format.commit_hex_length
            ):
                continue
            if not self.roots.is_ancestor(
                binding,
                ancestor=update.old_oid,
                descendant=update.new_oid,
            ):
                raise RepositoryRefAclError(
                    "historical ref updates must be fast-forward"
                )

    @staticmethod
    def _validate_oid_lengths(
        binding: ProjectRepositoryBinding,
        update: GitRefUpdate,
    ) -> None:
        expected = binding.object_format.commit_hex_length
        if len(update.old_oid) != expected or len(update.new_oid) != expected:
            raise RepositoryRefAclError("Git ref update object id length is invalid")
        for oid in (update.old_oid, update.new_oid):
            try:
                int(oid, 16)
            except ValueError as exc:
                raise RepositoryRefAclError(
                    "Git ref update object id is not hexadecimal"
                ) from exc


__all__ = [
    "ActiveCapabilityLeaseAssertion",
    "GitRefAclValidator",
    "GitRefUpdate",
    "IssuedRepositoryCredential",
    "REPOSITORY_CREDENTIAL_SCHEMA_VERSION",
    "RepositoryCredentialBroker",
    "RepositoryCredentialClaims",
    "RepositoryCredentialError",
    "RepositoryCredentialExpiredError",
    "RepositoryCredentialProtocol",
    "RepositoryCredentialRejectedError",
    "RepositoryRefAclError",
    "private_ref_prefix",
]
