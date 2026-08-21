from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from collections.abc import Mapping
from enum import StrEnum
import hashlib
import json
import re
from typing import Any
from typing import Protocol
from urllib.parse import urlsplit


PROJECT_REPOSITORY_BINDING_SCHEMA_VERSION = "project_repository_binding@1"
SESSION_REPOSITORY_BINDING_PIN_SCHEMA_VERSION = "session_repository_binding_pin@1"


class GitObjectFormat(StrEnum):
    SHA1 = "sha1"
    SHA256 = "sha256"

    @property
    def commit_hex_length(self) -> int:
        return 40 if self is self.SHA1 else 64


class RepositoryBindingLifecycleStatus(StrEnum):
    REGISTERED = "registered"
    ACTIVE = "active"
    RETIRED = "retired"


class SessionRepositoryBindingStatus(StrEnum):
    PINNED = "pinned"
    REPOSITORY_BINDING_REQUIRED = "repository_binding_required"


class RepositoryRefClass(StrEnum):
    READ = "read"
    PRIVATE = "private"
    PUBLICATION = "publication"
    HISTORICAL = "historical"
    RETENTION = "retention"


class RepositoryBindingDriftKind(StrEnum):
    BINDING_IDENTITY = "binding_identity"
    INTERNAL_REMOTE = "internal_remote"
    UPSTREAM_ORIGIN = "upstream_origin"
    OBJECT_FORMAT = "object_format"
    DEFAULT_BASE = "default_base"
    REF_NAMESPACE_POLICY = "ref_namespace_policy"
    LFS_IDENTITY = "lfs_identity"
    REPOSITORY_POLICY = "repository_policy"
    CANONICAL_DIGEST = "canonical_digest"


class RepositoryBindingMechanismError(RuntimeError):
    """Adapter-side binding verification failed before canonical mutation."""

    error_code = "repository_binding_mechanism_failed"


class RepositoryBindingEndpointMismatchError(RepositoryBindingMechanismError):
    error_code = "repository_binding_endpoint_mismatch"


def _require_identifier(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if normalized != value:
        raise ValueError(f"{field_name} must not contain surrounding whitespace")
    if any(character.isspace() for character in normalized):
        raise ValueError(f"{field_name} must not contain whitespace")
    return normalized


def _require_https_endpoint(value: str, field_name: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https":
        raise ValueError(f"{field_name} must use https")
    if not parsed.hostname:
        raise ValueError(f"{field_name} must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field_name} must not embed credentials")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{field_name} must not include query or fragment components")
    if parsed.path.endswith("/") and parsed.path != "/":
        raise ValueError(f"{field_name} must not end with a slash")
    return value


def _require_upstream_url(value: str) -> str:
    _require_identifier(value, "upstream_url")
    if (
        value.startswith(("/", "./", "../", "~/", "file:"))
        or value in {".", "..", "~"}
        or "\\" in value
    ):
        raise ValueError("upstream_url must not be a Host filesystem locator")
    if "://" in value:
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "ssh"} or not parsed.hostname:
            raise ValueError("upstream_url must identify an HTTPS or SSH remote")
        if parsed.password is not None or (
            parsed.scheme == "https" and parsed.username is not None
        ):
            raise ValueError("upstream_url must not embed credentials")
        return value
    if re.fullmatch(r"(?:[^/@:\s]+@)?[^/:\s]+:.+", value) is None:
        raise ValueError("upstream_url must identify an SSH remote")
    return value


def _require_ref(value: str, field_name: str) -> str:
    _require_identifier(value, field_name)
    if len(value.encode("utf-8")) > 1024:
        raise ValueError(f"{field_name} exceeds the repository ref length limit")
    if not value.startswith("refs/"):
        raise ValueError(f"{field_name} must be a fully qualified Git ref")
    if value.endswith(("/", ".")):
        raise ValueError(f"{field_name} has an invalid Git ref suffix")
    if ".." in value or "//" in value or "@{" in value:
        raise ValueError(f"{field_name} is not a valid Git ref namespace")
    if any(
        ord(character) < 0x20 or ord(character) == 0x7F or character in " ~^:?*[\\"
        for character in value
    ):
        raise ValueError(f"{field_name} contains a forbidden Git ref character")
    components = value.split("/")
    if any(
        component.startswith(".") or component.lower().endswith(".lock")
        for component in components
    ):
        raise ValueError(f"{field_name} contains an invalid Git ref component")
    return value


def _require_digest(value: str, field_name: str) -> str:
    prefix = "sha256:"
    if not value.startswith(prefix) or len(value) != len(prefix) + 64:
        raise ValueError(f"{field_name} must be a sha256 digest")
    try:
        int(value[len(prefix) :], 16)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a sha256 digest") from exc
    return value


def _require_commit(value: str, object_format: GitObjectFormat) -> str:
    if len(value) != object_format.commit_hex_length:
        raise ValueError(
            f"default_base_commit must contain {object_format.commit_hex_length} hex characters"
        )
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError("default_base_commit must be hexadecimal") from exc
    if value.lower() != value:
        raise ValueError("default_base_commit must use lowercase hexadecimal")
    return value


@dataclass(frozen=True, slots=True)
class RepositoryRefNamespacePolicy:
    private_prefix: str
    publication_prefix: str
    historical_prefix: str

    def __post_init__(self) -> None:
        prefixes = (
            _require_ref(self.private_prefix, "private_prefix"),
            _require_ref(self.publication_prefix, "publication_prefix"),
            _require_ref(self.historical_prefix, "historical_prefix"),
        )
        if len(set(prefixes)) != len(prefixes):
            raise ValueError("repository ref namespace prefixes must be distinct")
        for left in prefixes:
            for right in prefixes:
                if left != right and right.startswith(f"{left}/"):
                    raise ValueError(
                        "repository ref namespace prefixes must not overlap"
                    )

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProjectRepositoryBinding:
    binding_id: str
    project_id: str
    binding_version: int
    repository_id: str
    internal_git_service_id: str
    internal_git_endpoint: str
    lfs_service_id: str
    lfs_endpoint: str
    upstream_identity: str
    upstream_url: str
    object_format: GitObjectFormat
    default_base_ref: str
    default_base_commit: str
    ref_namespace_policy: RepositoryRefNamespacePolicy
    repository_policy_version: str
    repository_policy_digest: str
    canonical_digest: str
    created_at: str
    created_by: str
    schema_version: str = PROJECT_REPOSITORY_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PROJECT_REPOSITORY_BINDING_SCHEMA_VERSION:
            raise ValueError("unsupported ProjectRepositoryBinding schema_version")
        _require_identifier(self.binding_id, "binding_id")
        _require_identifier(self.project_id, "project_id")
        if self.binding_version <= 0:
            raise ValueError("binding_version must be positive")
        _require_identifier(self.repository_id, "repository_id")
        _require_identifier(self.internal_git_service_id, "internal_git_service_id")
        _require_https_endpoint(self.internal_git_endpoint, "internal_git_endpoint")
        _require_identifier(self.lfs_service_id, "lfs_service_id")
        _require_https_endpoint(self.lfs_endpoint, "lfs_endpoint")
        _require_identifier(self.upstream_identity, "upstream_identity")
        _require_upstream_url(self.upstream_url)
        if not isinstance(self.object_format, GitObjectFormat):
            raise TypeError("object_format must be a GitObjectFormat")
        _require_ref(self.default_base_ref, "default_base_ref")
        _require_commit(self.default_base_commit, self.object_format)
        if not isinstance(self.ref_namespace_policy, RepositoryRefNamespacePolicy):
            raise TypeError(
                "ref_namespace_policy must be a RepositoryRefNamespacePolicy"
            )
        _require_identifier(self.repository_policy_version, "repository_policy_version")
        _require_digest(self.repository_policy_digest, "repository_policy_digest")
        _require_digest(self.canonical_digest, "canonical_digest")
        _require_identifier(self.created_at, "created_at")
        _require_identifier(self.created_by, "created_by")
        expected = self.compute_canonical_digest(self.canonical_payload())
        if self.canonical_digest != expected:
            raise ValueError(
                "canonical_digest does not match repository binding payload"
            )

    @classmethod
    def create(
        cls,
        *,
        binding_id: str,
        project_id: str,
        binding_version: int,
        repository_id: str,
        internal_git_service_id: str,
        internal_git_endpoint: str,
        lfs_service_id: str,
        lfs_endpoint: str,
        upstream_identity: str,
        upstream_url: str,
        object_format: GitObjectFormat,
        default_base_ref: str,
        default_base_commit: str,
        ref_namespace_policy: RepositoryRefNamespacePolicy,
        repository_policy_version: str,
        repository_policy_digest: str,
        created_at: str,
        created_by: str,
    ) -> "ProjectRepositoryBinding":
        payload = {
            "schema_version": PROJECT_REPOSITORY_BINDING_SCHEMA_VERSION,
            "binding_id": binding_id,
            "project_id": project_id,
            "binding_version": binding_version,
            "repository_id": repository_id,
            "internal_git_service_id": internal_git_service_id,
            "internal_git_endpoint": internal_git_endpoint,
            "lfs_service_id": lfs_service_id,
            "lfs_endpoint": lfs_endpoint,
            "upstream_identity": upstream_identity,
            "upstream_url": upstream_url,
            "object_format": object_format.value,
            "default_base_ref": default_base_ref,
            "default_base_commit": default_base_commit,
            "ref_namespace_policy": ref_namespace_policy.to_dict(),
            "repository_policy_version": repository_policy_version,
            "repository_policy_digest": repository_policy_digest,
            "created_at": created_at,
            "created_by": created_by,
        }
        canonical_digest = cls.compute_canonical_digest(payload)
        return cls(
            binding_id=binding_id,
            project_id=project_id,
            binding_version=binding_version,
            repository_id=repository_id,
            internal_git_service_id=internal_git_service_id,
            internal_git_endpoint=internal_git_endpoint,
            lfs_service_id=lfs_service_id,
            lfs_endpoint=lfs_endpoint,
            upstream_identity=upstream_identity,
            upstream_url=upstream_url,
            object_format=object_format,
            default_base_ref=default_base_ref,
            default_base_commit=default_base_commit,
            ref_namespace_policy=ref_namespace_policy,
            repository_policy_version=repository_policy_version,
            repository_policy_digest=repository_policy_digest,
            canonical_digest=canonical_digest,
            created_at=created_at,
            created_by=created_by,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectRepositoryBinding":
        expected_keys = {
            "schema_version",
            "binding_id",
            "project_id",
            "binding_version",
            "repository_id",
            "internal_git_service_id",
            "internal_git_endpoint",
            "lfs_service_id",
            "lfs_endpoint",
            "upstream_identity",
            "upstream_url",
            "object_format",
            "default_base_ref",
            "default_base_commit",
            "ref_namespace_policy",
            "repository_policy_version",
            "repository_policy_digest",
            "canonical_digest",
            "created_at",
            "created_by",
        }
        if set(payload) != expected_keys:
            raise ValueError("repository binding payload has an invalid closed schema")
        ref_policy = payload["ref_namespace_policy"]
        if not isinstance(ref_policy, Mapping) or set(ref_policy) != {
            "private_prefix",
            "publication_prefix",
            "historical_prefix",
        }:
            raise ValueError("repository ref namespace policy has an invalid schema")
        if not isinstance(payload["binding_version"], int) or isinstance(
            payload["binding_version"], bool
        ):
            raise TypeError("repository binding_version must be an integer")

        def require_string(container: Mapping[str, Any], key: str) -> str:
            value = container[key]
            if not isinstance(value, str):
                raise TypeError(f"repository binding {key} must be a string")
            return value

        return cls(
            binding_id=require_string(payload, "binding_id"),
            project_id=require_string(payload, "project_id"),
            binding_version=payload["binding_version"],
            repository_id=require_string(payload, "repository_id"),
            internal_git_service_id=require_string(payload, "internal_git_service_id"),
            internal_git_endpoint=require_string(payload, "internal_git_endpoint"),
            lfs_service_id=require_string(payload, "lfs_service_id"),
            lfs_endpoint=require_string(payload, "lfs_endpoint"),
            upstream_identity=require_string(payload, "upstream_identity"),
            upstream_url=require_string(payload, "upstream_url"),
            object_format=GitObjectFormat(require_string(payload, "object_format")),
            default_base_ref=require_string(payload, "default_base_ref"),
            default_base_commit=require_string(payload, "default_base_commit"),
            ref_namespace_policy=RepositoryRefNamespacePolicy(
                private_prefix=require_string(ref_policy, "private_prefix"),
                publication_prefix=require_string(ref_policy, "publication_prefix"),
                historical_prefix=require_string(ref_policy, "historical_prefix"),
            ),
            repository_policy_version=require_string(
                payload, "repository_policy_version"
            ),
            repository_policy_digest=require_string(
                payload, "repository_policy_digest"
            ),
            canonical_digest=require_string(payload, "canonical_digest"),
            created_at=require_string(payload, "created_at"),
            created_by=require_string(payload, "created_by"),
            schema_version=require_string(payload, "schema_version"),
        )

    @staticmethod
    def compute_canonical_digest(payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "binding_id": self.binding_id,
            "project_id": self.project_id,
            "binding_version": self.binding_version,
            "repository_id": self.repository_id,
            "internal_git_service_id": self.internal_git_service_id,
            "internal_git_endpoint": self.internal_git_endpoint,
            "lfs_service_id": self.lfs_service_id,
            "lfs_endpoint": self.lfs_endpoint,
            "upstream_identity": self.upstream_identity,
            "upstream_url": self.upstream_url,
            "object_format": self.object_format.value,
            "default_base_ref": self.default_base_ref,
            "default_base_commit": self.default_base_commit,
            "ref_namespace_policy": self.ref_namespace_policy.to_dict(),
            "repository_policy_version": self.repository_policy_version,
            "repository_policy_digest": self.repository_policy_digest,
            "created_at": self.created_at,
            "created_by": self.created_by,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_payload(), "canonical_digest": self.canonical_digest}

    def safe_projection(
        self,
        *,
        lifecycle_status: RepositoryBindingLifecycleStatus,
        allowed_ref_classes: tuple[RepositoryRefClass, ...],
    ) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "binding_id": self.binding_id,
            "binding_version": self.binding_version,
            "repository_id": self.repository_id,
            "internal_git_service_id": self.internal_git_service_id,
            "lfs_service_id": self.lfs_service_id,
            "object_format": self.object_format.value,
            "default_base_commit": self.default_base_commit,
            "repository_policy_digest": self.repository_policy_digest,
            "lifecycle_status": lifecycle_status.value,
            "allowed_ref_classes": [item.value for item in allowed_ref_classes],
        }

    def drift_from(
        self,
        configured: "ProjectRepositoryBinding",
    ) -> tuple[RepositoryBindingDriftKind, ...]:
        drift: list[RepositoryBindingDriftKind] = []
        if (
            self.project_id,
            self.binding_id,
            self.binding_version,
        ) != (
            configured.project_id,
            configured.binding_id,
            configured.binding_version,
        ):
            drift.append(RepositoryBindingDriftKind.BINDING_IDENTITY)
        if (
            self.repository_id,
            self.internal_git_service_id,
            self.internal_git_endpoint,
        ) != (
            configured.repository_id,
            configured.internal_git_service_id,
            configured.internal_git_endpoint,
        ):
            drift.append(RepositoryBindingDriftKind.INTERNAL_REMOTE)
        if (self.upstream_identity, self.upstream_url) != (
            configured.upstream_identity,
            configured.upstream_url,
        ):
            drift.append(RepositoryBindingDriftKind.UPSTREAM_ORIGIN)
        if self.object_format is not configured.object_format:
            drift.append(RepositoryBindingDriftKind.OBJECT_FORMAT)
        if (self.default_base_ref, self.default_base_commit) != (
            configured.default_base_ref,
            configured.default_base_commit,
        ):
            drift.append(RepositoryBindingDriftKind.DEFAULT_BASE)
        if self.ref_namespace_policy != configured.ref_namespace_policy:
            drift.append(RepositoryBindingDriftKind.REF_NAMESPACE_POLICY)
        if (self.lfs_service_id, self.lfs_endpoint) != (
            configured.lfs_service_id,
            configured.lfs_endpoint,
        ):
            drift.append(RepositoryBindingDriftKind.LFS_IDENTITY)
        if (
            self.repository_policy_version,
            self.repository_policy_digest,
        ) != (
            configured.repository_policy_version,
            configured.repository_policy_digest,
        ):
            drift.append(RepositoryBindingDriftKind.REPOSITORY_POLICY)
        if self.canonical_digest != configured.canonical_digest:
            drift.append(RepositoryBindingDriftKind.CANONICAL_DIGEST)
        return tuple(drift)


@dataclass(frozen=True, slots=True)
class SessionRepositoryBindingPin:
    session_id: str
    project_id: str
    binding_id: str
    binding_version: int
    repository_id: str
    resolved_base_commit: str
    binding_canonical_digest: str
    pinned_at: str
    mapping_receipt_id: str | None = None
    schema_version: str = SESSION_REPOSITORY_BINDING_PIN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SESSION_REPOSITORY_BINDING_PIN_SCHEMA_VERSION:
            raise ValueError("unsupported SessionRepositoryBindingPin schema_version")
        _require_identifier(self.session_id, "session_id")
        _require_identifier(self.project_id, "project_id")
        _require_identifier(self.binding_id, "binding_id")
        if self.binding_version <= 0:
            raise ValueError("binding_version must be positive")
        _require_identifier(self.repository_id, "repository_id")
        if len(self.resolved_base_commit) not in {40, 64}:
            raise ValueError("resolved_base_commit must be an exact Git commit")
        try:
            int(self.resolved_base_commit, 16)
        except ValueError as exc:
            raise ValueError("resolved_base_commit must be hexadecimal") from exc
        _require_digest(self.binding_canonical_digest, "binding_canonical_digest")
        _require_identifier(self.pinned_at, "pinned_at")
        if self.mapping_receipt_id is not None:
            _require_identifier(self.mapping_receipt_id, "mapping_receipt_id")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SessionRepositoryBindingPin":
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(payload) != expected:
            raise ValueError("session repository binding pin has an invalid closed schema")
        for key in expected - {"binding_version", "mapping_receipt_id"}:
            if not isinstance(payload[key], str):
                raise TypeError(f"{key} must be a string")
        if not isinstance(payload["binding_version"], int) or isinstance(
            payload["binding_version"], bool
        ):
            raise TypeError("binding_version must be an integer")
        mapping_receipt_id = payload["mapping_receipt_id"]
        if mapping_receipt_id is not None and not isinstance(mapping_receipt_id, str):
            raise TypeError("mapping_receipt_id must be a string or null")
        return cls(**payload)


class RepositoryBindingMechanismPort(Protocol):
    """Mechanism-only boundary for the selected repository backend."""

    def verify_endpoint(self, binding: ProjectRepositoryBinding) -> None: ...

    def verify_registration(self, binding: ProjectRepositoryBinding) -> None: ...

    def activate(self, binding: ProjectRepositoryBinding) -> None: ...

    def verify_pinned(self, binding: ProjectRepositoryBinding) -> None: ...


__all__ = [
    "GitObjectFormat",
    "PROJECT_REPOSITORY_BINDING_SCHEMA_VERSION",
    "ProjectRepositoryBinding",
    "RepositoryBindingDriftKind",
    "RepositoryBindingLifecycleStatus",
    "RepositoryBindingEndpointMismatchError",
    "RepositoryBindingMechanismError",
    "RepositoryBindingMechanismPort",
    "RepositoryRefClass",
    "RepositoryRefNamespacePolicy",
    "SESSION_REPOSITORY_BINDING_PIN_SCHEMA_VERSION",
    "SessionRepositoryBindingPin",
    "SessionRepositoryBindingStatus",
]
