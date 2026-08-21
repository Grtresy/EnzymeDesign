from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from .identity import canonical_sha256_digest
from .identity import canonical_string_tuple
from .identity import require_digest
from .identity import require_identifier


AGENT_AUTHORITY_LEASE_SCHEMA_VERSION = "agent_authority_lease@1"
AUTHORITY_GRANT_SCHEMA_VERSION = "authority_grant@1"


class AgentAuthorityLeaseState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class AuthorityGrant:
    grant_id: str
    scope_id: str
    operations: tuple[str, ...]
    generation: int
    fence: int
    grant_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.grant_id, field_name="grant_id")
        require_identifier(self.scope_id, field_name="scope_id")
        object.__setattr__(
            self,
            "operations",
            canonical_string_tuple(
                self.operations,
                field_name="operations",
                allow_empty=False,
            ),
        )
        if self.generation < 1 or self.fence < 1:
            raise ValueError("authority generation and fence must be positive")
        require_digest(self.grant_digest, field_name="grant_digest")
        if self.grant_digest != canonical_sha256_digest(self.digest_payload()):
            raise ValueError("authority grant digest mismatch")

    @classmethod
    def create(
        cls,
        *,
        grant_id: str,
        scope_id: str,
        operations: tuple[str, ...],
        generation: int,
        fence: int,
    ) -> AuthorityGrant:
        canonical_operations = canonical_string_tuple(
            operations,
            field_name="operations",
            allow_empty=False,
        )
        payload = {
            "schema_version": AUTHORITY_GRANT_SCHEMA_VERSION,
            "grant_id": grant_id,
            "scope_id": scope_id,
            "operations": list(canonical_operations),
            "generation": generation,
            "fence": fence,
        }
        return cls(
            grant_id=grant_id,
            scope_id=scope_id,
            operations=canonical_operations,
            generation=generation,
            fence=fence,
            grant_digest=canonical_sha256_digest(payload),
        )

    def digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": AUTHORITY_GRANT_SCHEMA_VERSION,
            "grant_id": self.grant_id,
            "scope_id": self.scope_id,
            "operations": list(self.operations),
            "generation": self.generation,
            "fence": self.fence,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.digest_payload(), "grant_digest": self.grant_digest}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AuthorityGrant":
        expected = {
            "schema_version",
            "grant_id",
            "scope_id",
            "operations",
            "generation",
            "fence",
            "grant_digest",
        }
        if set(payload) != expected or payload.get("schema_version") != AUTHORITY_GRANT_SCHEMA_VERSION:
            raise ValueError("authority grant payload has an invalid closed schema")
        operations = payload["operations"]
        if not isinstance(operations, tuple | list) or any(
            not isinstance(item, str) for item in operations
        ):
            raise TypeError("authority grant operations must be a string array")
        return cls(
            grant_id=str(payload["grant_id"]),
            scope_id=str(payload["scope_id"]),
            operations=tuple(operations),
            generation=int(payload["generation"]),
            fence=int(payload["fence"]),
            grant_digest=str(payload["grant_digest"]),
        )


@dataclass(frozen=True, slots=True)
class AgentAuthorityLease:
    lease_id: str
    session_id: str
    agent_member_id: str
    grants: tuple[AuthorityGrant, ...]
    generation: int
    fence: int
    state: AgentAuthorityLeaseState
    issued_at: str
    expires_at: str | None
    lease_digest: str
    agent_id: str | None = None
    workspace_generation: int | None = None
    parent_lease_id: str | None = None
    policy_digest: str | None = None
    idempotency_key: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.lease_id, field_name="lease_id")
        require_identifier(self.session_id, field_name="session_id")
        require_identifier(self.agent_member_id, field_name="agent_member_id")
        grant_ids = [grant.grant_id for grant in self.grants]
        if len(set(grant_ids)) != len(grant_ids):
            raise ValueError("grants must have unique grant_id values")
        object.__setattr__(
            self,
            "grants",
            tuple(sorted(self.grants, key=lambda grant: grant.grant_id)),
        )
        if self.generation < 1 or self.fence < 1:
            raise ValueError("lease generation and fence must be positive")
        if any(
            grant.generation != self.generation or grant.fence != self.fence
            for grant in self.grants
        ):
            raise ValueError("authority grants must match lease generation and fence")
        for field_name in (
            "agent_id",
            "parent_lease_id",
            "idempotency_key",
        ):
            value = getattr(self, field_name)
            if value is not None:
                require_identifier(value, field_name=field_name)
        if self.workspace_generation is not None and self.workspace_generation < 1:
            raise ValueError("workspace_generation must be positive")
        if self.policy_digest is not None:
            require_digest(self.policy_digest, field_name="policy_digest")
        require_digest(self.lease_digest, field_name="lease_digest")
        if self.lease_digest != canonical_sha256_digest(self.digest_payload()):
            raise ValueError("authority lease digest mismatch")

    @classmethod
    def create(
        cls,
        *,
        lease_id: str,
        session_id: str,
        agent_member_id: str,
        grants: tuple[AuthorityGrant, ...],
        generation: int,
        fence: int,
        state: AgentAuthorityLeaseState,
        issued_at: str,
        expires_at: str | None,
        agent_id: str | None = None,
        workspace_generation: int | None = None,
        parent_lease_id: str | None = None,
        policy_digest: str | None = None,
        idempotency_key: str | None = None,
        updated_at: str | None = None,
    ) -> AgentAuthorityLease:
        canonical_grants = tuple(sorted(grants, key=lambda grant: grant.grant_id))
        payload = {
            "schema_version": AGENT_AUTHORITY_LEASE_SCHEMA_VERSION,
            "lease_id": lease_id,
            "session_id": session_id,
            "agent_member_id": agent_member_id,
            "grants": [grant.to_dict() for grant in canonical_grants],
            "generation": generation,
            "fence": fence,
            "state": state.value,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "agent_id": agent_id,
            "workspace_generation": workspace_generation,
            "parent_lease_id": parent_lease_id,
            "policy_digest": policy_digest,
            "idempotency_key": idempotency_key,
            "updated_at": updated_at,
        }
        return cls(
            lease_id=lease_id,
            session_id=session_id,
            agent_member_id=agent_member_id,
            grants=canonical_grants,
            generation=generation,
            fence=fence,
            state=state,
            issued_at=issued_at,
            expires_at=expires_at,
            lease_digest=canonical_sha256_digest(payload),
            agent_id=agent_id,
            workspace_generation=workspace_generation,
            parent_lease_id=parent_lease_id,
            policy_digest=policy_digest,
            idempotency_key=idempotency_key,
            updated_at=updated_at,
        )

    @property
    def operations(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {operation for grant in self.grants for operation in grant.operations}
            )
        )

    def allows(self, operation: str, *, scope_id: str | None = None) -> bool:
        if self.state is not AgentAuthorityLeaseState.ACTIVE:
            return False
        return any(
            operation in grant.operations
            and (scope_id is None or scope_id == grant.scope_id)
            for grant in self.grants
        )

    def digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": AGENT_AUTHORITY_LEASE_SCHEMA_VERSION,
            "lease_id": self.lease_id,
            "session_id": self.session_id,
            "agent_member_id": self.agent_member_id,
            "grants": [grant.to_dict() for grant in self.grants],
            "generation": self.generation,
            "fence": self.fence,
            "state": self.state.value,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "agent_id": self.agent_id,
            "workspace_generation": self.workspace_generation,
            "parent_lease_id": self.parent_lease_id,
            "policy_digest": self.policy_digest,
            "idempotency_key": self.idempotency_key,
            "updated_at": self.updated_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.digest_payload(), "lease_digest": self.lease_digest}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AgentAuthorityLease":
        expected = {
            "schema_version",
            "lease_id",
            "session_id",
            "agent_member_id",
            "grants",
            "generation",
            "fence",
            "state",
            "issued_at",
            "expires_at",
            "agent_id",
            "workspace_generation",
            "parent_lease_id",
            "policy_digest",
            "idempotency_key",
            "updated_at",
            "lease_digest",
        }
        if set(payload) != expected or payload.get("schema_version") != AGENT_AUTHORITY_LEASE_SCHEMA_VERSION:
            raise ValueError("authority lease payload has an invalid closed schema")
        grants = payload["grants"]
        if not isinstance(grants, tuple | list) or any(
            not isinstance(item, Mapping) for item in grants
        ):
            raise TypeError("authority lease grants must be an object array")
        return cls(
            lease_id=str(payload["lease_id"]),
            session_id=str(payload["session_id"]),
            agent_member_id=str(payload["agent_member_id"]),
            grants=tuple(AuthorityGrant.from_dict(item) for item in grants),
            generation=int(payload["generation"]),
            fence=int(payload["fence"]),
            state=AgentAuthorityLeaseState(str(payload["state"])),
            issued_at=str(payload["issued_at"]),
            expires_at=(
                None if payload["expires_at"] is None else str(payload["expires_at"])
            ),
            lease_digest=str(payload["lease_digest"]),
            agent_id=None if payload["agent_id"] is None else str(payload["agent_id"]),
            workspace_generation=(
                None
                if payload["workspace_generation"] is None
                else int(payload["workspace_generation"])
            ),
            parent_lease_id=(
                None
                if payload["parent_lease_id"] is None
                else str(payload["parent_lease_id"])
            ),
            policy_digest=(
                None
                if payload["policy_digest"] is None
                else str(payload["policy_digest"])
            ),
            idempotency_key=(
                None
                if payload["idempotency_key"] is None
                else str(payload["idempotency_key"])
            ),
            updated_at=(
                None if payload["updated_at"] is None else str(payload["updated_at"])
            ),
        )


__all__ = [
    "AGENT_AUTHORITY_LEASE_SCHEMA_VERSION",
    "AUTHORITY_GRANT_SCHEMA_VERSION",
    "AgentAuthorityLease",
    "AgentAuthorityLeaseState",
    "AuthorityGrant",
]
