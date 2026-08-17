from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac

from openzyme_runtime import HostApiSettings


class HostAuthenticationError(ValueError):
    """Raised when a shared Host request has no valid bearer credential."""


@dataclass(frozen=True, slots=True)
class HostPrincipal:
    principal_id: str
    roles: frozenset[str]
    project_ids: frozenset[str]

    def __post_init__(self) -> None:
        agent_principal = self.principal_id.startswith("agent-member:") and len(
            self.principal_id
        ) > len("agent-member:")
        if agent_principal != (self.roles == frozenset({"agent"})):
            raise ValueError(
                "agent-member principals must have exactly the agent role"
            )
        if not agent_principal and (
            not self.principal_id.startswith("user:")
            or len(self.principal_id) <= len("user:")
        ):
            raise ValueError("user principals must have a non-empty user: identity")
        if not self.project_ids or "" in self.project_ids:
            raise ValueError("Host principals require non-empty project scope")

    def has_role(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))

    def can_access_project(self, project_id: str) -> bool:
        return "*" in self.project_ids or project_id in self.project_ids

    @property
    def agent_member_id(self) -> str | None:
        prefix = "agent-member:"
        if self.roles == frozenset({"agent"}) and self.principal_id.startswith(prefix):
            return self.principal_id.removeprefix(prefix)
        return None


@dataclass(frozen=True, slots=True)
class HostSecurityPolicy:
    deployment_profile: str
    principals_by_digest: dict[str, HostPrincipal]
    debug_enabled: bool

    def __post_init__(self) -> None:
        if self.deployment_profile not in {"local-dev", "shared"}:
            raise ValueError("Host security profile must be 'local-dev' or 'shared'")
        if self.deployment_profile == "shared" and not self.principals_by_digest:
            raise ValueError("shared Host security policy requires principals")

    @classmethod
    def from_settings(cls, settings: HostApiSettings | None) -> "HostSecurityPolicy":
        resolved = settings or HostApiSettings(
            bind_host="127.0.0.1",
            bind_port=8000,
        )
        return cls(
            deployment_profile=resolved.deployment_profile,
            principals_by_digest={
                item.token_sha256: HostPrincipal(
                    principal_id=item.principal_id,
                    roles=item.roles,
                    project_ids=item.project_ids,
                )
                for item in resolved.principals
            },
            debug_enabled=resolved.debug_enabled,
        )

    @property
    def shared(self) -> bool:
        return self.deployment_profile == "shared"

    def authenticate(self, authorization: str | None) -> HostPrincipal:
        if not self.shared:
            return HostPrincipal(
                principal_id="user:local-dev",
                roles=frozenset({"user", "operator", "admin"}),
                project_ids=frozenset({"*"}),
            )
        scheme, separator, token = (authorization or "").partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token.strip():
            raise HostAuthenticationError("Bearer authentication is required")
        digest = hashlib.sha256(token.strip().encode("utf-8")).hexdigest()
        principal: HostPrincipal | None = None
        # Compare every configured digest to avoid leaking which prefix matched.
        for candidate_digest, candidate in self.principals_by_digest.items():
            if hmac.compare_digest(digest, candidate_digest):
                principal = candidate
        if principal is None:
            raise HostAuthenticationError("Bearer authentication failed")
        return principal


__all__ = [
    "HostAuthenticationError",
    "HostPrincipal",
    "HostSecurityPolicy",
]
