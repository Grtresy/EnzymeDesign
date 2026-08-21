"""Closed Git/LFS bearer claims owned by the workspace Adapter contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from openzyme_contracts import RepositoryRefClass

from .ref_policy import RepositoryCredentialProtocol


REPOSITORY_CREDENTIAL_SCHEMA_VERSION = "repository_credential@1"


class RepositoryCredentialError(RuntimeError):
    error_code = "repository_credential_error"


class RepositoryCredentialRejectedError(RepositoryCredentialError):
    error_code = "repository_credential_rejected"


class RepositoryCredentialExpiredError(RepositoryCredentialError):
    error_code = "repository_credential_expired"


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
    def from_payload(cls, payload: dict[str, Any]) -> RepositoryCredentialClaims:
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
        return f"sha256:{hashlib.sha256(_canonical_json(self.to_payload())).hexdigest()}"


@dataclass(frozen=True, slots=True)
class IssuedRepositoryCredential:
    token: str
    claims: RepositoryCredentialClaims


__all__ = [
    "IssuedRepositoryCredential",
    "REPOSITORY_CREDENTIAL_SCHEMA_VERSION",
    "RepositoryCredentialClaims",
    "RepositoryCredentialError",
    "RepositoryCredentialExpiredError",
    "RepositoryCredentialRejectedError",
]
