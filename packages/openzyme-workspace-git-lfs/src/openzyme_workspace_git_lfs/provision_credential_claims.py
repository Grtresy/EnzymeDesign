"""Read-only clone/provision credential claims owned by the Git/LFS Adapter."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from openzyme_contracts import RepositoryRefClass

from .credential_claims import RepositoryCredentialRejectedError
from .ref_policy import RepositoryCredentialProtocol


REPOSITORY_PROVISION_CREDENTIAL_SCHEMA_VERSION = (
    "repository_provision_credential@1"
)
REPOSITORY_PROVISION_PROTOCOLS = (
    RepositoryCredentialProtocol.GIT_READ,
    RepositoryCredentialProtocol.LFS_READ,
)
_EXPECTED_FIELDS = {
    "schema_version",
    "credential_id",
    "workspace_id",
    "binding_id",
    "binding_version",
    "repository_id",
    "session_id",
    "agent_member_id",
    "agent_id",
    "workspace_generation",
    "capability_lease_id",
    "protocols",
    "ref_classes",
    "issued_at",
    "expires_at",
}


def _canonical_json(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class RepositoryProvisionCredentialClaims:
    """Exact read-only identity used only while provisioning one workspace."""

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
        return REPOSITORY_PROVISION_PROTOCOLS

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
        return f"sha256:{hashlib.sha256(_canonical_json(self.to_payload())).hexdigest()}"

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, object],
    ) -> RepositoryProvisionCredentialClaims:
        if set(payload) != _EXPECTED_FIELDS:
            raise RepositoryCredentialRejectedError(
                "repository provision credential claims schema is not closed"
            )
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

        try:
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
        except ValueError as exc:
            raise RepositoryCredentialRejectedError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class IssuedRepositoryProvisionCredential:
    token: str
    claims: RepositoryProvisionCredentialClaims


__all__ = [
    "IssuedRepositoryProvisionCredential",
    "REPOSITORY_PROVISION_CREDENTIAL_SCHEMA_VERSION",
    "REPOSITORY_PROVISION_PROTOCOLS",
    "RepositoryProvisionCredentialClaims",
]
