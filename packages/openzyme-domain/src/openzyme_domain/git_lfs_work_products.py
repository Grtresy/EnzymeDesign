from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import fnmatch
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit


GIT_LFS_BINDING_POLICY_SCHEMA_VERSION = "git_lfs_binding_policy@1"
GIT_LFS_CLOSURE_MANIFEST_SCHEMA_VERSION = "git_lfs_closure_manifest@1"
GIT_LFS_CLOSURE_VERIFICATION_SCHEMA_VERSION = "git_lfs_closure_verification@1"
GIT_LFS_OBJECT_READ_RECEIPT_SCHEMA_VERSION = "git_lfs_object_read_receipt@1"
GIT_LFS_PRIVATE_REACHABILITY_RECEIPT_SCHEMA_VERSION = (
    "git_lfs_private_reachability_receipt@1"
)
GIT_LFS_UPLOAD_SESSION_SCHEMA_VERSION = "git_lfs_upload_session@1"
GIT_LFS_GC_CANDIDATE_RECEIPT_SCHEMA_VERSION = "git_lfs_gc_candidate_receipt@1"
GIT_LFS_POINTER_VERSION = "https://git-lfs.github.com/spec/v1"


class GitLfsPathRepresentation(StrEnum):
    LFS_REQUIRED = "lfs_required"
    ORDINARY_ALLOWED = "ordinary_allowed"


class GitLfsUploadStatus(StrEnum):
    RESERVED = "reserved"
    COMMITTED = "committed"
    ABORTED = "aborted"


class GitLfsRetentionClass(StrEnum):
    PUBLISHED = "published"
    PRIVATE = "private"


def canonical_lfs_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _require_identifier(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be an exact non-empty identifier")


def _require_digest(value: str, field_name: str) -> None:
    if re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")


def _require_oid(value: str, field_name: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field_name} must be a lowercase sha256 object id")


def _require_positive(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _require_non_negative(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def require_repository_path(value: str) -> str:
    if (
        not value
        or value.startswith("/")
        or value.endswith("/")
        or "\\" in value
        or "\x00" in value
        or any(part in {"", ".", "..", ".git"} for part in value.split("/"))
    ):
        raise ValueError("path must be a canonical repository-relative path")
    return value


@dataclass(frozen=True, slots=True)
class GitLfsPathRule:
    rule_id: str
    pattern: str
    representation: GitLfsPathRepresentation

    def __post_init__(self) -> None:
        _require_identifier(self.rule_id, "rule_id")
        if (
            not self.pattern
            or self.pattern.startswith("/")
            or "\\" in self.pattern
            or "\x00" in self.pattern
            or ".." in self.pattern.split("/")
        ):
            raise ValueError("LFS path rule pattern is not repository-relative")
        if not isinstance(self.representation, GitLfsPathRepresentation):
            raise TypeError("representation must be a GitLfsPathRepresentation")

    def matches(self, path: str) -> bool:
        require_repository_path(path)
        return fnmatch.fnmatchcase(path, self.pattern)

    def to_dict(self) -> dict[str, str]:
        return {
            "rule_id": self.rule_id,
            "pattern": self.pattern,
            "representation": self.representation.value,
        }


@dataclass(frozen=True, slots=True)
class GitLfsBindingPolicy:
    binding_id: str
    binding_version: int
    repository_id: str
    lfs_service_id: str
    lfs_endpoint: str
    object_format: str
    path_rules: tuple[GitLfsPathRule, ...]
    ordinary_blob_threshold_bytes: int
    max_object_bytes: int
    max_workspace_bytes: int
    max_repository_bytes: int
    published_retention_class: GitLfsRetentionClass
    private_retention_class: GitLfsRetentionClass
    private_retention_seconds: int
    policy_version: str
    policy_digest: str
    created_at: str
    created_by: str
    schema_version: str = GIT_LFS_BINDING_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != GIT_LFS_BINDING_POLICY_SCHEMA_VERSION:
            raise ValueError("unsupported Git LFS binding policy schema")
        for field_name in (
            "binding_id",
            "repository_id",
            "lfs_service_id",
            "policy_version",
            "created_at",
            "created_by",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_positive(self.binding_version, "binding_version")
        parsed = urlsplit(self.lfs_endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("lfs_endpoint must be a credential-free HTTPS endpoint")
        if self.object_format != "sha256":
            raise ValueError("Git LFS object format must be sha256")
        rule_ids = tuple(rule.rule_id for rule in self.path_rules)
        if rule_ids != tuple(sorted(set(rule_ids))):
            raise ValueError("Git LFS path rules must have unique sorted rule ids")
        _require_positive(
            self.ordinary_blob_threshold_bytes,
            "ordinary_blob_threshold_bytes",
        )
        _require_positive(self.max_object_bytes, "max_object_bytes")
        _require_positive(self.max_workspace_bytes, "max_workspace_bytes")
        _require_positive(self.max_repository_bytes, "max_repository_bytes")
        if not (
            self.max_object_bytes
            <= self.max_workspace_bytes
            <= self.max_repository_bytes
        ):
            raise ValueError("Git LFS quotas must be monotonically non-decreasing")
        if self.published_retention_class is not GitLfsRetentionClass.PUBLISHED:
            raise ValueError("published objects require the published retention class")
        if self.private_retention_class is not GitLfsRetentionClass.PRIVATE:
            raise ValueError("private objects require the private retention class")
        _require_positive(self.private_retention_seconds, "private_retention_seconds")
        _require_digest(self.policy_digest, "policy_digest")
        if self.policy_digest != canonical_lfs_digest(self.payload):
            raise ValueError("Git LFS policy digest does not match canonical payload")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "binding_id": self.binding_id,
            "binding_version": self.binding_version,
            "repository_id": self.repository_id,
            "lfs_service_id": self.lfs_service_id,
            "lfs_endpoint": self.lfs_endpoint,
            "object_format": self.object_format,
            "path_rules": [rule.to_dict() for rule in self.path_rules],
            "ordinary_blob_threshold_bytes": self.ordinary_blob_threshold_bytes,
            "max_object_bytes": self.max_object_bytes,
            "max_workspace_bytes": self.max_workspace_bytes,
            "max_repository_bytes": self.max_repository_bytes,
            "published_retention_class": self.published_retention_class.value,
            "private_retention_class": self.private_retention_class.value,
            "private_retention_seconds": self.private_retention_seconds,
            "policy_version": self.policy_version,
            "created_at": self.created_at,
            "created_by": self.created_by,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload, "policy_digest": self.policy_digest}

    @classmethod
    def create(cls, **values: Any) -> GitLfsBindingPolicy:
        ordered_rules = tuple(sorted(values["path_rules"], key=lambda item: item.rule_id))
        normalized = {**values, "path_rules": ordered_rules}
        payload = {
            "schema_version": GIT_LFS_BINDING_POLICY_SCHEMA_VERSION,
            **normalized,
            "path_rules": [rule.to_dict() for rule in ordered_rules],
            "published_retention_class": normalized[
                "published_retention_class"
            ].value,
            "private_retention_class": normalized["private_retention_class"].value,
        }
        return cls(**normalized, policy_digest=canonical_lfs_digest(payload))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> GitLfsBindingPolicy:
        expected = {
            "schema_version",
            "binding_id",
            "binding_version",
            "repository_id",
            "lfs_service_id",
            "lfs_endpoint",
            "object_format",
            "path_rules",
            "ordinary_blob_threshold_bytes",
            "max_object_bytes",
            "max_workspace_bytes",
            "max_repository_bytes",
            "published_retention_class",
            "private_retention_class",
            "private_retention_seconds",
            "policy_version",
            "policy_digest",
            "created_at",
            "created_by",
        }
        if set(payload) != expected:
            raise ValueError("Git LFS policy payload has an invalid closed schema")
        raw_rules = payload["path_rules"]
        if not isinstance(raw_rules, list):
            raise TypeError("Git LFS path_rules must be a list")
        rules: list[GitLfsPathRule] = []
        for item in raw_rules:
            if not isinstance(item, dict) or set(item) != {
                "rule_id",
                "pattern",
                "representation",
            }:
                raise ValueError("Git LFS path rule has an invalid closed schema")
            rules.append(
                GitLfsPathRule(
                    rule_id=str(item["rule_id"]),
                    pattern=str(item["pattern"]),
                    representation=GitLfsPathRepresentation(
                        str(item["representation"])
                    ),
                )
            )
        integer_fields = (
            "binding_version",
            "ordinary_blob_threshold_bytes",
            "max_object_bytes",
            "max_workspace_bytes",
            "max_repository_bytes",
            "private_retention_seconds",
        )
        for field_name in integer_fields:
            value = payload[field_name]
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"Git LFS {field_name} must be an integer")
        return cls(
            binding_id=str(payload["binding_id"]),
            binding_version=payload["binding_version"],
            repository_id=str(payload["repository_id"]),
            lfs_service_id=str(payload["lfs_service_id"]),
            lfs_endpoint=str(payload["lfs_endpoint"]),
            object_format=str(payload["object_format"]),
            path_rules=tuple(rules),
            ordinary_blob_threshold_bytes=payload[
                "ordinary_blob_threshold_bytes"
            ],
            max_object_bytes=payload["max_object_bytes"],
            max_workspace_bytes=payload["max_workspace_bytes"],
            max_repository_bytes=payload["max_repository_bytes"],
            published_retention_class=GitLfsRetentionClass(
                str(payload["published_retention_class"])
            ),
            private_retention_class=GitLfsRetentionClass(
                str(payload["private_retention_class"])
            ),
            private_retention_seconds=payload["private_retention_seconds"],
            policy_version=str(payload["policy_version"]),
            policy_digest=str(payload["policy_digest"]),
            created_at=str(payload["created_at"]),
            created_by=str(payload["created_by"]),
            schema_version=str(payload["schema_version"]),
        )

    def rule_for_path(self, path: str) -> GitLfsPathRule | None:
        matches = tuple(rule for rule in self.path_rules if rule.matches(path))
        return None if not matches else matches[-1]


@dataclass(frozen=True, slots=True)
class GitLfsPointer:
    oid: str
    size: int
    version: str = GIT_LFS_POINTER_VERSION

    def __post_init__(self) -> None:
        if self.version != GIT_LFS_POINTER_VERSION:
            raise ValueError("unsupported Git LFS pointer version")
        _require_oid(self.oid, "oid")
        _require_non_negative(self.size, "size")

    @classmethod
    def parse(cls, value: bytes) -> GitLfsPointer:
        if len(value) > 1024 or b"\x00" in value:
            raise ValueError("Git LFS pointer exceeds the canonical text boundary")
        try:
            text = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Git LFS pointer must be UTF-8 text") from exc
        if not text.endswith("\n") or "\r" in text:
            raise ValueError("Git LFS pointer must use canonical LF lines")
        lines = text.splitlines()
        if len(lines) != 3 or lines[0] != f"version {GIT_LFS_POINTER_VERSION}":
            raise ValueError("Git LFS pointer has an invalid closed grammar")
        oid_prefix = "oid sha256:"
        size_prefix = "size "
        if not lines[1].startswith(oid_prefix) or not lines[2].startswith(size_prefix):
            raise ValueError("Git LFS pointer has an invalid closed grammar")
        oid = lines[1][len(oid_prefix) :]
        raw_size = lines[2][len(size_prefix) :]
        if not raw_size.isdigit() or (len(raw_size) > 1 and raw_size.startswith("0")):
            raise ValueError("Git LFS pointer size must be canonical decimal")
        return cls(oid=oid, size=int(raw_size))

    def to_bytes(self) -> bytes:
        return (
            f"version {self.version}\n"
            f"oid sha256:{self.oid}\n"
            f"size {self.size}\n"
        ).encode("ascii")


@dataclass(frozen=True, slots=True)
class GitLfsClosureEntry:
    path: str
    mode: str
    pointer_blob_oid: str
    lfs_oid: str
    size_bytes: int
    object_read_receipt_id: str

    def __post_init__(self) -> None:
        require_repository_path(self.path)
        if self.mode not in {"100644", "100755"}:
            raise ValueError("Git LFS closure accepts only regular file modes")
        if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", self.pointer_blob_oid) is None:
            raise ValueError("pointer_blob_oid must be a Git object id")
        _require_oid(self.lfs_oid, "lfs_oid")
        _require_non_negative(self.size_bytes, "size_bytes")
        _require_identifier(self.object_read_receipt_id, "object_read_receipt_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "mode": self.mode,
            "pointer_blob_oid": self.pointer_blob_oid,
            "lfs_oid": f"sha256:{self.lfs_oid}",
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class GitLfsClosureManifest:
    binding_id: str
    binding_version: int
    repository_id: str
    commit: str
    tree: str
    policy_digest: str
    lfs_endpoint_identity: str
    authorization_scope_digest: str
    entries: tuple[GitLfsClosureEntry, ...]
    manifest_digest: str
    verified_at: str
    schema_version: str = GIT_LFS_CLOSURE_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != GIT_LFS_CLOSURE_MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported Git LFS closure manifest schema")
        for field_name in (
            "binding_id",
            "repository_id",
            "lfs_endpoint_identity",
            "verified_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_positive(self.binding_version, "binding_version")
        if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", self.commit) is None:
            raise ValueError("commit must be a Git object id")
        if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", self.tree) is None:
            raise ValueError("tree must be a Git object id")
        _require_digest(self.policy_digest, "policy_digest")
        _require_digest(self.authorization_scope_digest, "authorization_scope_digest")
        paths = tuple(entry.path for entry in self.entries)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("Git LFS closure paths must be unique and sorted")
        _require_digest(self.manifest_digest, "manifest_digest")
        if self.manifest_digest != canonical_lfs_digest(self.payload):
            raise ValueError("Git LFS closure digest does not match canonical payload")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "binding_id": self.binding_id,
            "binding_version": self.binding_version,
            "repository_id": self.repository_id,
            "commit": self.commit,
            "tree": self.tree,
            "policy_digest": self.policy_digest,
            "lfs_endpoint_identity": self.lfs_endpoint_identity,
            "authorization_scope_digest": self.authorization_scope_digest,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def create(cls, **values: Any) -> GitLfsClosureManifest:
        entries = tuple(sorted(values["entries"], key=lambda item: item.path))
        normalized = {**values, "entries": entries}
        payload = {
            "schema_version": GIT_LFS_CLOSURE_MANIFEST_SCHEMA_VERSION,
            "binding_id": normalized["binding_id"],
            "binding_version": normalized["binding_version"],
            "repository_id": normalized["repository_id"],
            "commit": normalized["commit"],
            "tree": normalized["tree"],
            "policy_digest": normalized["policy_digest"],
            "lfs_endpoint_identity": normalized["lfs_endpoint_identity"],
            "authorization_scope_digest": normalized[
                "authorization_scope_digest"
            ],
            "entries": [entry.to_dict() for entry in entries],
        }
        return cls(**normalized, manifest_digest=canonical_lfs_digest(payload))


@dataclass(frozen=True, slots=True)
class GitLfsClosureVerification:
    verification_id: str
    manifest_digest: str
    binding_id: str
    binding_version: int
    repository_id: str
    authorization_scope_digest: str
    object_read_receipt_ids: tuple[str, ...]
    observed_at: str
    verification_digest: str
    schema_version: str = GIT_LFS_CLOSURE_VERIFICATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != GIT_LFS_CLOSURE_VERIFICATION_SCHEMA_VERSION:
            raise ValueError("unsupported Git LFS closure verification schema")
        for field_name in (
            "verification_id",
            "binding_id",
            "repository_id",
            "observed_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_positive(self.binding_version, "binding_version")
        _require_digest(self.manifest_digest, "manifest_digest")
        _require_digest(
            self.authorization_scope_digest,
            "authorization_scope_digest",
        )
        if self.object_read_receipt_ids != tuple(
            sorted(set(self.object_read_receipt_ids))
        ):
            raise ValueError("object-read receipt ids must be unique and sorted")
        for receipt_id in self.object_read_receipt_ids:
            _require_identifier(receipt_id, "object_read_receipt_id")
        _require_digest(self.verification_digest, "verification_digest")
        if self.verification_digest != canonical_lfs_digest(self.payload):
            raise ValueError("Git LFS closure verification digest mismatch")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "verification_id": self.verification_id,
            "manifest_digest": self.manifest_digest,
            "binding_id": self.binding_id,
            "binding_version": self.binding_version,
            "repository_id": self.repository_id,
            "authorization_scope_digest": self.authorization_scope_digest,
            "object_read_receipt_ids": list(self.object_read_receipt_ids),
            "observed_at": self.observed_at,
        }

    @classmethod
    def create(cls, **values: Any) -> GitLfsClosureVerification:
        receipt_ids = tuple(sorted(set(values["object_read_receipt_ids"])))
        normalized = {**values, "object_read_receipt_ids": receipt_ids}
        payload = {
            "schema_version": GIT_LFS_CLOSURE_VERIFICATION_SCHEMA_VERSION,
            **normalized,
            "object_read_receipt_ids": list(receipt_ids),
        }
        return cls(
            **normalized,
            verification_digest=canonical_lfs_digest(payload),
        )


@dataclass(frozen=True, slots=True)
class GitLfsObjectReadReceipt:
    receipt_id: str
    binding_id: str
    binding_version: int
    repository_id: str
    lfs_endpoint_identity: str
    authorization_scope_digest: str
    oid: str
    declared_size: int
    observed_size: int
    observed_sha256: str
    observed_at: str
    receipt_digest: str
    schema_version: str = GIT_LFS_OBJECT_READ_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != GIT_LFS_OBJECT_READ_RECEIPT_SCHEMA_VERSION:
            raise ValueError("unsupported Git LFS object-read receipt schema")
        for field_name in (
            "receipt_id",
            "binding_id",
            "repository_id",
            "lfs_endpoint_identity",
            "observed_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_positive(self.binding_version, "binding_version")
        _require_digest(self.authorization_scope_digest, "authorization_scope_digest")
        _require_oid(self.oid, "oid")
        _require_non_negative(self.declared_size, "declared_size")
        _require_non_negative(self.observed_size, "observed_size")
        _require_oid(self.observed_sha256, "observed_sha256")
        if self.declared_size != self.observed_size or self.oid != self.observed_sha256:
            raise ValueError("object-read receipt must prove exact size and digest")
        _require_digest(self.receipt_digest, "receipt_digest")
        if self.receipt_digest != canonical_lfs_digest(self.payload):
            raise ValueError("object-read receipt digest mismatch")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "binding_id": self.binding_id,
            "binding_version": self.binding_version,
            "repository_id": self.repository_id,
            "lfs_endpoint_identity": self.lfs_endpoint_identity,
            "authorization_scope_digest": self.authorization_scope_digest,
            "oid": self.oid,
            "declared_size": self.declared_size,
            "observed_size": self.observed_size,
            "observed_sha256": self.observed_sha256,
            "observed_at": self.observed_at,
        }

    @classmethod
    def create(cls, **values: Any) -> GitLfsObjectReadReceipt:
        payload = {
            "schema_version": GIT_LFS_OBJECT_READ_RECEIPT_SCHEMA_VERSION,
            **values,
        }
        return cls(**values, receipt_digest=canonical_lfs_digest(payload))


@dataclass(frozen=True, slots=True)
class GitLfsUploadSession:
    upload_session_id: str
    binding_id: str
    binding_version: int
    repository_id: str
    session_id: str
    agent_member_id: str
    workspace_generation: int
    credential_id: str
    oid: str
    declared_size: int
    reserved_bytes: int
    status: GitLfsUploadStatus
    created_at: str
    expires_at: str
    completed_at: str | None = None
    schema_version: str = GIT_LFS_UPLOAD_SESSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != GIT_LFS_UPLOAD_SESSION_SCHEMA_VERSION:
            raise ValueError("unsupported Git LFS upload-session schema")
        for field_name in (
            "upload_session_id",
            "binding_id",
            "repository_id",
            "session_id",
            "agent_member_id",
            "credential_id",
            "created_at",
            "expires_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_positive(self.binding_version, "binding_version")
        _require_positive(self.workspace_generation, "workspace_generation")
        _require_oid(self.oid, "oid")
        _require_non_negative(self.declared_size, "declared_size")
        if self.reserved_bytes != self.declared_size:
            raise ValueError("upload reservation must equal declared object size")
        if self.status is GitLfsUploadStatus.RESERVED and self.completed_at is not None:
            raise ValueError("reserved upload session must not be completed")
        if self.status is not GitLfsUploadStatus.RESERVED and self.completed_at is None:
            raise ValueError("terminal upload session requires completed_at")


@dataclass(frozen=True, slots=True)
class GitLfsPrivateReachabilityReceipt:
    receipt_id: str
    binding_id: str
    binding_version: int
    repository_id: str
    namespace_id: str
    workspace_generation: int
    terminal_refs_digest: str
    terminal_commits_digest: str
    reachable_oids: tuple[str, ...]
    retirement_receipt_id: str
    created_at: str
    reachability_digest: str
    schema_version: str = GIT_LFS_PRIVATE_REACHABILITY_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != GIT_LFS_PRIVATE_REACHABILITY_RECEIPT_SCHEMA_VERSION:
            raise ValueError("unsupported Git LFS private-reachability schema")
        for field_name in (
            "receipt_id",
            "binding_id",
            "repository_id",
            "namespace_id",
            "retirement_receipt_id",
            "created_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_positive(self.binding_version, "binding_version")
        _require_positive(self.workspace_generation, "workspace_generation")
        _require_digest(self.terminal_refs_digest, "terminal_refs_digest")
        _require_digest(self.terminal_commits_digest, "terminal_commits_digest")
        if self.reachable_oids != tuple(sorted(set(self.reachable_oids))):
            raise ValueError("reachable Git LFS OIDs must be unique and sorted")
        for oid in self.reachable_oids:
            _require_oid(oid, "reachable_oid")
        _require_digest(self.reachability_digest, "reachability_digest")
        if self.reachability_digest != canonical_lfs_digest(self.payload):
            raise ValueError("private Git LFS reachability digest mismatch")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "binding_id": self.binding_id,
            "binding_version": self.binding_version,
            "repository_id": self.repository_id,
            "namespace_id": self.namespace_id,
            "workspace_generation": self.workspace_generation,
            "terminal_refs_digest": self.terminal_refs_digest,
            "terminal_commits_digest": self.terminal_commits_digest,
            "reachable_oids": list(self.reachable_oids),
            "retirement_receipt_id": self.retirement_receipt_id,
            "created_at": self.created_at,
        }

    @classmethod
    def create(cls, **values: Any) -> GitLfsPrivateReachabilityReceipt:
        reachable_oids = tuple(sorted(set(values["reachable_oids"])))
        normalized = {**values, "reachable_oids": reachable_oids}
        payload = {
            "schema_version": GIT_LFS_PRIVATE_REACHABILITY_RECEIPT_SCHEMA_VERSION,
            **normalized,
            "reachable_oids": list(reachable_oids),
        }
        return cls(
            **normalized,
            reachability_digest=canonical_lfs_digest(payload),
        )


@dataclass(frozen=True, slots=True)
class GitLfsGcCandidateReceipt:
    receipt_id: str
    binding_id: str
    binding_version: int
    repository_id: str
    policy_digest: str
    reachability_digest: str
    retirement_receipts_digest: str
    candidate_oids: tuple[str, ...]
    dry_run: bool
    created_at: str
    receipt_digest: str
    schema_version: str = GIT_LFS_GC_CANDIDATE_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != GIT_LFS_GC_CANDIDATE_RECEIPT_SCHEMA_VERSION:
            raise ValueError("unsupported Git LFS GC candidate receipt schema")
        for field_name in ("receipt_id", "binding_id", "repository_id", "created_at"):
            _require_identifier(getattr(self, field_name), field_name)
        _require_positive(self.binding_version, "binding_version")
        for field_name in (
            "policy_digest",
            "reachability_digest",
            "retirement_receipts_digest",
        ):
            _require_digest(getattr(self, field_name), field_name)
        if self.candidate_oids != tuple(sorted(set(self.candidate_oids))):
            raise ValueError("GC candidate OIDs must be unique and sorted")
        for oid in self.candidate_oids:
            _require_oid(oid, "candidate_oid")
        if not self.dry_run:
            raise ValueError("candidate receipt must be produced in dry-run mode")
        _require_digest(self.receipt_digest, "receipt_digest")
        if self.receipt_digest != canonical_lfs_digest(self.payload):
            raise ValueError("GC candidate receipt digest mismatch")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "binding_id": self.binding_id,
            "binding_version": self.binding_version,
            "repository_id": self.repository_id,
            "policy_digest": self.policy_digest,
            "reachability_digest": self.reachability_digest,
            "retirement_receipts_digest": self.retirement_receipts_digest,
            "candidate_oids": list(self.candidate_oids),
            "dry_run": self.dry_run,
            "created_at": self.created_at,
        }

    @classmethod
    def create(cls, **values: Any) -> GitLfsGcCandidateReceipt:
        oids = tuple(sorted(set(values["candidate_oids"])))
        normalized = {**values, "candidate_oids": oids, "dry_run": True}
        payload = {
            "schema_version": GIT_LFS_GC_CANDIDATE_RECEIPT_SCHEMA_VERSION,
            **normalized,
            "candidate_oids": list(oids),
        }
        return cls(**normalized, receipt_digest=canonical_lfs_digest(payload))


__all__ = [
    "GIT_LFS_BINDING_POLICY_SCHEMA_VERSION",
    "GIT_LFS_CLOSURE_MANIFEST_SCHEMA_VERSION",
    "GIT_LFS_CLOSURE_VERIFICATION_SCHEMA_VERSION",
    "GIT_LFS_GC_CANDIDATE_RECEIPT_SCHEMA_VERSION",
    "GIT_LFS_OBJECT_READ_RECEIPT_SCHEMA_VERSION",
    "GIT_LFS_PRIVATE_REACHABILITY_RECEIPT_SCHEMA_VERSION",
    "GIT_LFS_POINTER_VERSION",
    "GIT_LFS_UPLOAD_SESSION_SCHEMA_VERSION",
    "GitLfsBindingPolicy",
    "GitLfsClosureEntry",
    "GitLfsClosureManifest",
    "GitLfsClosureVerification",
    "GitLfsGcCandidateReceipt",
    "GitLfsObjectReadReceipt",
    "GitLfsPathRepresentation",
    "GitLfsPathRule",
    "GitLfsPointer",
    "GitLfsPrivateReachabilityReceipt",
    "GitLfsRetentionClass",
    "GitLfsUploadSession",
    "GitLfsUploadStatus",
    "canonical_lfs_digest",
    "require_repository_path",
]
