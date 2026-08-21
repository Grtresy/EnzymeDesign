"""Pre-Session operator authority used only for atomic Session bootstrap."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from typing import Protocol

from .identity import canonical_sha256_digest
from .identity import require_digest
from .identity import require_identifier


SESSION_BOOTSTRAP_AUTHORIZATION_SCHEMA_VERSION = (
    "session_bootstrap_authorization@1"
)
SESSION_BOOTSTRAP_AUTHORIZATION_OPERATION = "session.bootstrap"


@dataclass(frozen=True, slots=True)
class SessionBootstrapAuthorization:
    """Opaque delivery-authority fact for creating the first Session lease."""

    authorization_id: str
    operator_actor_id: str
    project_id: str
    session_id: str
    root_authority_lease_digest: str
    session_composition_pin_digest: str
    extension_bundle_digest: str
    capability_binding_digest: str
    generation: int
    fence: int
    issued_at: str
    expires_at: str
    authorization_digest: str
    operation: str = SESSION_BOOTSTRAP_AUTHORIZATION_OPERATION

    def __post_init__(self) -> None:
        for field_name in (
            "authorization_id",
            "operator_actor_id",
            "project_id",
            "session_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.operation != SESSION_BOOTSTRAP_AUTHORIZATION_OPERATION:
            raise ValueError("bootstrap authorization operation is invalid")
        if self.generation < 1 or self.fence < 1:
            raise ValueError("bootstrap authority generation and fence must be positive")
        for field_name in (
            "root_authority_lease_digest",
            "session_composition_pin_digest",
            "extension_bundle_digest",
            "capability_binding_digest",
            "authorization_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if self.authorization_digest != canonical_sha256_digest(self.digest_payload()):
            raise ValueError("bootstrap authorization digest mismatch")

    @classmethod
    def create(
        cls,
        *,
        authorization_id: str,
        operator_actor_id: str,
        project_id: str,
        session_id: str,
        root_authority_lease_digest: str,
        session_composition_pin_digest: str,
        extension_bundle_digest: str,
        capability_binding_digest: str,
        generation: int,
        fence: int,
        issued_at: str,
        expires_at: str,
    ) -> SessionBootstrapAuthorization:
        payload = {
            "schema_version": SESSION_BOOTSTRAP_AUTHORIZATION_SCHEMA_VERSION,
            "authorization_id": authorization_id,
            "operator_actor_id": operator_actor_id,
            "project_id": project_id,
            "session_id": session_id,
            "operation": SESSION_BOOTSTRAP_AUTHORIZATION_OPERATION,
            "root_authority_lease_digest": root_authority_lease_digest,
            "session_composition_pin_digest": session_composition_pin_digest,
            "extension_bundle_digest": extension_bundle_digest,
            "capability_binding_digest": capability_binding_digest,
            "generation": generation,
            "fence": fence,
            "issued_at": issued_at,
            "expires_at": expires_at,
        }
        return cls(
            authorization_id=authorization_id,
            operator_actor_id=operator_actor_id,
            project_id=project_id,
            session_id=session_id,
            root_authority_lease_digest=root_authority_lease_digest,
            session_composition_pin_digest=session_composition_pin_digest,
            extension_bundle_digest=extension_bundle_digest,
            capability_binding_digest=capability_binding_digest,
            generation=generation,
            fence=fence,
            issued_at=issued_at,
            expires_at=expires_at,
            authorization_digest=canonical_sha256_digest(payload),
        )

    def digest_payload(self) -> dict[str, object]:
        return {
            "schema_version": SESSION_BOOTSTRAP_AUTHORIZATION_SCHEMA_VERSION,
            "authorization_id": self.authorization_id,
            "operator_actor_id": self.operator_actor_id,
            "project_id": self.project_id,
            "session_id": self.session_id,
            "operation": self.operation,
            "root_authority_lease_digest": self.root_authority_lease_digest,
            "session_composition_pin_digest": self.session_composition_pin_digest,
            "extension_bundle_digest": self.extension_bundle_digest,
            "capability_binding_digest": self.capability_binding_digest,
            "generation": self.generation,
            "fence": self.fence,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.digest_payload(), "authorization_digest": self.authorization_digest}

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> SessionBootstrapAuthorization:
        expected = {
            "schema_version",
            "authorization_id",
            "operator_actor_id",
            "project_id",
            "session_id",
            "operation",
            "root_authority_lease_digest",
            "session_composition_pin_digest",
            "extension_bundle_digest",
            "capability_binding_digest",
            "generation",
            "fence",
            "issued_at",
            "expires_at",
            "authorization_digest",
        }
        if (
            set(payload) != expected
            or payload.get("schema_version")
            != SESSION_BOOTSTRAP_AUTHORIZATION_SCHEMA_VERSION
        ):
            raise ValueError("bootstrap authorization payload has an invalid closed schema")
        return cls(
            authorization_id=str(payload["authorization_id"]),
            operator_actor_id=str(payload["operator_actor_id"]),
            project_id=str(payload["project_id"]),
            session_id=str(payload["session_id"]),
            operation=str(payload["operation"]),
            root_authority_lease_digest=str(payload["root_authority_lease_digest"]),
            session_composition_pin_digest=str(
                payload["session_composition_pin_digest"]
            ),
            extension_bundle_digest=str(payload["extension_bundle_digest"]),
            capability_binding_digest=str(payload["capability_binding_digest"]),
            generation=int(payload["generation"]),
            fence=int(payload["fence"]),
            issued_at=str(payload["issued_at"]),
            expires_at=str(payload["expires_at"]),
            authorization_digest=str(payload["authorization_digest"]),
        )


@dataclass(frozen=True, slots=True)
class SessionBootstrapAuthorityDecision:
    allowed: bool
    authorization_id: str
    authorization_digest: str
    denial_code: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.authorization_id, field_name="authorization_id")
        require_digest(self.authorization_digest, field_name="authorization_digest")
        if self.allowed == (self.denial_code is not None):
            raise ValueError("bootstrap authority decision is inconsistent")


class SessionBootstrapAuthorityVerifierPort(Protocol):
    """Verifies authenticated operator authority without inventing an Agent lease."""

    def verify(
        self,
        authorization: SessionBootstrapAuthorization,
        *,
        now_iso: str,
    ) -> SessionBootstrapAuthorityDecision: ...


__all__ = [
    "SESSION_BOOTSTRAP_AUTHORIZATION_OPERATION",
    "SESSION_BOOTSTRAP_AUTHORIZATION_SCHEMA_VERSION",
    "SessionBootstrapAuthorization",
    "SessionBootstrapAuthorityDecision",
    "SessionBootstrapAuthorityVerifierPort",
]
