from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit

from .repository_bindings import GitObjectFormat


AGENT_GIT_WORKSPACE_SCHEMA_VERSION = "agent_git_workspace@1"
AGENT_GIT_WORKSPACE_OBSERVATION_SCHEMA_VERSION = (
    "agent_git_workspace_observation@1"
)
AGENT_GIT_WORKSPACE_RESTORE_COMPARISON_SCHEMA_VERSION = (
    "agent_git_workspace_restore_comparison@1"
)


class AgentGitWorkspaceStatus(StrEnum):
    PROVISIONING = "provisioning"
    READY = "ready"
    BLOCKED = "blocked"
    FROZEN = "frozen"
    REPLACED = "replaced"


class AgentGitWorkspaceBlockerCode(StrEnum):
    MISSING_VOLUME = "missing_volume"
    CROSS_AGENT_VOLUME = "cross_agent_volume"
    CORRUPT_GIT_DIRECTORY = "corrupt_git_directory"
    SHARED_GIT_DIRECTORY = "shared_git_directory"
    REMOTE_IDENTITY_DRIFT = "remote_identity_drift"
    OBJECT_FORMAT_DRIFT = "object_format_drift"
    BASE_COMMIT_DRIFT = "base_commit_drift"
    GENERATION_DRIFT = "generation_drift"
    UNREADABLE_HEAD = "unreadable_head"
    POLICY_DRIFT = "policy_drift"
    LEASE_INTENT_MISMATCH = "lease_intent_mismatch"
    REPOSITORY_BINDING_DRIFT = "repository_binding_drift"
    IMAGE_UNQUALIFIED = "image_unqualified"
    CLONE_FAILED = "clone_failed"
    PERSISTENCE_FAILED = "persistence_failed"
    IDENTITY_DRIFT = "identity_drift"


class AgentGitDirectoryKind(StrEnum):
    INDEPENDENT = "independent"
    LINKED_WORKTREE = "linked_worktree"
    SHARED = "shared"
    MISSING = "missing"
    CORRUPT = "corrupt"


class AgentGitWorkspaceIdentityDriftKind(StrEnum):
    WORKSPACE = "workspace"
    OWNER = "owner"
    GENERATION = "generation"
    VOLUME = "volume"
    CLONE_ROOT = "clone_root"
    GIT_DIRECTORY = "git_directory"
    REMOTE_IDENTITY = "remote_identity"
    OBJECT_FORMAT = "object_format"
    BASE_COMMIT = "base_commit"
    HEAD = "head"
    HEAD_UNREADABLE = "head_unreadable"
    PRIVATE_NAMESPACE = "private_namespace"
    POLICY = "policy"


def canonical_workspace_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _require_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value != value.strip() or any(c.isspace() for c in value):
        raise ValueError(
            f"{field_name} must be a non-empty identifier without whitespace"
        )


def _require_digest(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")


def _require_positive_integer(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _require_https_endpoint(value: str, field_name: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            f"{field_name} must be a credential-free HTTPS service endpoint"
        )


def _require_logical_clone_root(value: str) -> None:
    if (
        value != "/workspace"
        and not value.startswith("/workspace/")
    ) or value.endswith("/"):
        raise ValueError(
            "clone_logical_root must be /workspace or a path below /workspace"
        )
    if ".." in value.split("/") or "\\" in value:
        raise ValueError("clone_logical_root must not escape its workspace volume")
    if any(character.isspace() for character in value):
        raise ValueError("clone_logical_root must not contain whitespace")


def _require_ref_namespace(value: str) -> None:
    _require_identifier(value, "private_ref_namespace")
    if not value.startswith("refs/") or value.endswith("/"):
        raise ValueError("private_ref_namespace must be a fully qualified Git prefix")
    if any(token in value for token in ("..", "//", "@{")):
        raise ValueError("private_ref_namespace is not a safe Git ref prefix")


def _require_commit(
    value: str | None,
    *,
    object_format: GitObjectFormat,
    field_name: str,
    required: bool,
) -> None:
    if value is None:
        if required:
            raise ValueError(f"{field_name} is required")
        return
    expected_length = object_format.commit_hex_length
    if re.fullmatch(rf"[0-9a-f]{{{expected_length}}}", value) is None:
        raise ValueError(
            f"{field_name} must be a lowercase {object_format.value} object id"
        )


@dataclass(frozen=True, slots=True)
class AgentGitWorkspace:
    workspace_id: str
    session_id: str
    agent_member_id: str
    agent_id: str
    workspace_generation: int
    reservation_id: str
    reservation_fingerprint: str
    capability_lease_id: str
    capability_lease_intent_digest: str
    repository_binding_id: str
    repository_binding_version: int
    repository_binding_digest: str
    repository_id: str
    internal_git_service_id: str
    internal_git_endpoint: str
    object_format: GitObjectFormat
    base_commit: str
    volume_id: str
    clone_logical_root: str
    image_ref: str
    image_manifest_digest: str
    image_qualification_digest: str
    private_ref_namespace: str
    repository_policy_version: str
    repository_policy_digest: str
    capability_policy_version: str
    capability_policy_digest: str
    status: AgentGitWorkspaceStatus
    state_version: int
    created_at: str
    updated_at: str
    workspace_identity_digest: str
    canonical_digest: str
    head_commit: str | None = None
    head_tree: str | None = None
    readiness_observation_digest: str | None = None
    ready_at: str | None = None
    blocker_code: AgentGitWorkspaceBlockerCode | None = None
    blocker_detail_digest: str | None = None
    blocked_at: str | None = None
    frozen_reason: str | None = None
    frozen_at: str | None = None
    replaced_by_generation: int | None = None
    replaced_at: str | None = None
    schema_version: str = AGENT_GIT_WORKSPACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_GIT_WORKSPACE_SCHEMA_VERSION:
            raise ValueError("unsupported AgentGitWorkspace schema_version")
        for field_name in (
            "workspace_id",
            "session_id",
            "agent_member_id",
            "agent_id",
            "reservation_id",
            "capability_lease_id",
            "repository_binding_id",
            "repository_id",
            "internal_git_service_id",
            "volume_id",
            "image_ref",
            "repository_policy_version",
            "capability_policy_version",
            "created_at",
            "updated_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_positive_integer(self.workspace_generation, "workspace_generation")
        _require_positive_integer(
            self.repository_binding_version,
            "repository_binding_version",
        )
        _require_positive_integer(self.state_version, "state_version")
        for value, field_name in (
            (self.reservation_fingerprint, "reservation_fingerprint"),
            (self.capability_lease_intent_digest, "capability_lease_intent_digest"),
            (self.repository_binding_digest, "repository_binding_digest"),
            (self.image_manifest_digest, "image_manifest_digest"),
            (self.image_qualification_digest, "image_qualification_digest"),
            (self.repository_policy_digest, "repository_policy_digest"),
            (self.capability_policy_digest, "capability_policy_digest"),
            (self.workspace_identity_digest, "workspace_identity_digest"),
            (self.canonical_digest, "canonical_digest"),
        ):
            _require_digest(value, field_name)
        _require_https_endpoint(
            self.internal_git_endpoint,
            "internal_git_endpoint",
        )
        if not isinstance(self.object_format, GitObjectFormat):
            raise TypeError("object_format must be a GitObjectFormat")
        if not isinstance(self.status, AgentGitWorkspaceStatus):
            raise TypeError("status must be an AgentGitWorkspaceStatus")
        _require_commit(
            self.base_commit,
            object_format=self.object_format,
            field_name="base_commit",
            required=True,
        )
        _require_commit(
            self.head_commit,
            object_format=self.object_format,
            field_name="head_commit",
            required=self.status is AgentGitWorkspaceStatus.READY,
        )
        _require_commit(
            self.head_tree,
            object_format=self.object_format,
            field_name="head_tree",
            required=self.status is AgentGitWorkspaceStatus.READY,
        )
        _require_logical_clone_root(self.clone_logical_root)
        if re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,127}", self.volume_id) is None:
            raise ValueError("volume_id must be one exact Podman named-volume identity")
        if re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", self.image_ref) is None:
            raise ValueError("image_ref must be an OCI digest-pinned ref")
        _require_ref_namespace(self.private_ref_namespace)
        self._validate_lifecycle()
        if self.workspace_identity_digest != canonical_workspace_digest(
            self.identity_payload()
        ):
            raise ValueError("workspace_identity_digest does not match identity")
        if self.canonical_digest != canonical_workspace_digest(
            self.canonical_payload()
        ):
            raise ValueError("canonical_digest does not match workspace payload")

    def _validate_lifecycle(self) -> None:
        blocker_values = (
            self.blocker_code,
            self.blocker_detail_digest,
            self.blocked_at,
        )
        blocker_absent = all(value is None for value in blocker_values)
        blocker_complete = all(value is not None for value in blocker_values)
        if blocker_complete:
            if not isinstance(self.blocker_code, AgentGitWorkspaceBlockerCode):
                raise TypeError("blocker_code must be an AgentGitWorkspaceBlockerCode")
            assert self.blocker_detail_digest is not None
            assert self.blocked_at is not None
            _require_digest(self.blocker_detail_digest, "blocker_detail_digest")
            _require_identifier(self.blocked_at, "blocked_at")
        readiness_values = (
            self.head_commit,
            self.head_tree,
            self.readiness_observation_digest,
            self.ready_at,
        )
        readiness_absent = all(value is None for value in readiness_values)
        readiness_complete = all(value is not None for value in readiness_values)
        if readiness_complete:
            assert self.readiness_observation_digest is not None
            assert self.ready_at is not None
            _require_digest(
                self.readiness_observation_digest,
                "readiness_observation_digest",
            )
            _require_identifier(self.ready_at, "ready_at")
        frozen_values = (self.frozen_reason, self.frozen_at)
        frozen_absent = all(value is None for value in frozen_values)
        frozen_complete = all(value is not None for value in frozen_values)
        if frozen_complete:
            assert self.frozen_reason is not None
            assert self.frozen_at is not None
            _require_identifier(self.frozen_reason, "frozen_reason")
            _require_identifier(self.frozen_at, "frozen_at")
        replacement_values = (self.replaced_by_generation, self.replaced_at)
        replacement_absent = all(value is None for value in replacement_values)
        replacement_complete = all(value is not None for value in replacement_values)
        if replacement_complete:
            assert self.replaced_by_generation is not None
            assert self.replaced_at is not None
            _require_positive_integer(
                self.replaced_by_generation,
                "replaced_by_generation",
            )
            if self.replaced_by_generation <= self.workspace_generation:
                raise ValueError("replacement generation must strictly increase")
            _require_identifier(self.replaced_at, "replaced_at")
        if self.status is AgentGitWorkspaceStatus.PROVISIONING:
            if self.state_version != 1 or not (
                blocker_absent
                and readiness_absent
                and frozen_absent
                and replacement_absent
            ):
                raise ValueError("provisioning workspace contains lifecycle facts")
        elif self.status is AgentGitWorkspaceStatus.READY:
            if not (
                readiness_complete
                and blocker_absent
                and frozen_absent
                and replacement_absent
            ):
                raise ValueError("ready workspace requires only readiness facts")
        elif self.status is AgentGitWorkspaceStatus.BLOCKED:
            if not (blocker_complete and frozen_absent and replacement_absent):
                raise ValueError("blocked workspace requires complete blocker facts")
            if not (readiness_absent or readiness_complete):
                raise ValueError("blocked workspace has partial readiness history")
        elif self.status is AgentGitWorkspaceStatus.FROZEN:
            if not (frozen_complete and replacement_absent):
                raise ValueError("frozen workspace requires complete frozen facts")
            if not (blocker_absent or blocker_complete):
                raise ValueError("frozen workspace has partial blocker history")
            if not (readiness_absent or readiness_complete):
                raise ValueError("frozen workspace has partial readiness history")
        elif not (
            frozen_complete
            and replacement_complete
            and (blocker_absent or blocker_complete)
            and (readiness_absent or readiness_complete)
        ):
            raise ValueError(
                "replaced workspace requires frozen and replacement history"
            )

    @classmethod
    def create(cls, **values: Any) -> AgentGitWorkspace:
        identity_payload = cls._identity_payload_from_values(values)
        workspace_identity_digest = canonical_workspace_digest(identity_payload)
        canonical_payload = cls._canonical_payload_from_values(
            values,
            workspace_identity_digest=workspace_identity_digest,
        )
        return cls(
            **values,
            workspace_identity_digest=workspace_identity_digest,
            canonical_digest=canonical_workspace_digest(canonical_payload),
        )

    @staticmethod
    def _identity_payload_from_values(values: dict[str, Any]) -> dict[str, Any]:
        object_format = values["object_format"]
        return {
            "schema_version": AGENT_GIT_WORKSPACE_SCHEMA_VERSION,
            "workspace_id": values["workspace_id"],
            "session_id": values["session_id"],
            "agent_member_id": values["agent_member_id"],
            "agent_id": values["agent_id"],
            "workspace_generation": values["workspace_generation"],
            "reservation_id": values["reservation_id"],
            "reservation_fingerprint": values["reservation_fingerprint"],
            "capability_lease_id": values["capability_lease_id"],
            "capability_lease_intent_digest": values[
                "capability_lease_intent_digest"
            ],
            "repository_binding_id": values["repository_binding_id"],
            "repository_binding_version": values["repository_binding_version"],
            "repository_binding_digest": values["repository_binding_digest"],
            "repository_id": values["repository_id"],
            "internal_git_service_id": values["internal_git_service_id"],
            "internal_git_endpoint": values["internal_git_endpoint"],
            "object_format": object_format.value,
            "base_commit": values["base_commit"],
            "volume_id": values["volume_id"],
            "clone_logical_root": values["clone_logical_root"],
            "image_ref": values["image_ref"],
            "image_manifest_digest": values["image_manifest_digest"],
            "image_qualification_digest": values["image_qualification_digest"],
            "private_ref_namespace": values["private_ref_namespace"],
            "repository_policy_version": values["repository_policy_version"],
            "repository_policy_digest": values["repository_policy_digest"],
            "capability_policy_version": values["capability_policy_version"],
            "capability_policy_digest": values["capability_policy_digest"],
            "created_at": values["created_at"],
        }

    @staticmethod
    def _canonical_payload_from_values(
        values: dict[str, Any],
        *,
        workspace_identity_digest: str,
    ) -> dict[str, Any]:
        payload = AgentGitWorkspace._identity_payload_from_values(values)
        status = values["status"]
        blocker_code = values.get("blocker_code")
        payload.update(
            {
                "status": status.value,
                "state_version": values["state_version"],
                "updated_at": values["updated_at"],
                "workspace_identity_digest": workspace_identity_digest,
                "head_commit": values.get("head_commit"),
                "head_tree": values.get("head_tree"),
                "readiness_observation_digest": values.get(
                    "readiness_observation_digest"
                ),
                "ready_at": values.get("ready_at"),
                "blocker_code": (
                    None if blocker_code is None else blocker_code.value
                ),
                "blocker_detail_digest": values.get("blocker_detail_digest"),
                "blocked_at": values.get("blocked_at"),
                "frozen_reason": values.get("frozen_reason"),
                "frozen_at": values.get("frozen_at"),
                "replaced_by_generation": values.get("replaced_by_generation"),
                "replaced_at": values.get("replaced_at"),
            }
        )
        return payload

    def identity_payload(self) -> dict[str, Any]:
        return self._identity_payload_from_values(
            {name: getattr(self, name) for name in self.__dataclass_fields__}
        )

    def canonical_payload(self) -> dict[str, Any]:
        return self._canonical_payload_from_values(
            {name: getattr(self, name) for name in self.__dataclass_fields__},
            workspace_identity_digest=self.workspace_identity_digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_payload(), "canonical_digest": self.canonical_digest}


@dataclass(frozen=True, slots=True)
class AgentGitWorkspaceObservation:
    workspace_id: str
    session_id: str
    agent_member_id: str
    agent_id: str
    workspace_generation: int
    volume_id: str
    clone_logical_root: str
    git_directory_kind: AgentGitDirectoryKind
    internal_git_service_id: str
    internal_git_endpoint: str
    repository_id: str
    object_format: GitObjectFormat
    base_commit: str
    head_commit: str | None
    head_tree: str | None
    head_readable: bool
    private_ref_namespace: str
    repository_policy_digest: str
    capability_policy_digest: str
    observed_at: str
    schema_version: str = AGENT_GIT_WORKSPACE_OBSERVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_GIT_WORKSPACE_OBSERVATION_SCHEMA_VERSION:
            raise ValueError("unsupported workspace observation schema_version")
        for field_name in (
            "workspace_id",
            "session_id",
            "agent_member_id",
            "agent_id",
            "volume_id",
            "internal_git_service_id",
            "repository_id",
            "observed_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_positive_integer(self.workspace_generation, "workspace_generation")
        _require_logical_clone_root(self.clone_logical_root)
        if not isinstance(self.git_directory_kind, AgentGitDirectoryKind):
            raise TypeError("git_directory_kind must be an AgentGitDirectoryKind")
        _require_https_endpoint(self.internal_git_endpoint, "internal_git_endpoint")
        if not isinstance(self.object_format, GitObjectFormat):
            raise TypeError("object_format must be a GitObjectFormat")
        _require_commit(
            self.base_commit,
            object_format=self.object_format,
            field_name="base_commit",
            required=True,
        )
        _require_commit(
            self.head_commit,
            object_format=self.object_format,
            field_name="head_commit",
            required=self.head_readable,
        )
        _require_commit(
            self.head_tree,
            object_format=self.object_format,
            field_name="head_tree",
            required=self.head_readable,
        )
        if not isinstance(self.head_readable, bool):
            raise TypeError("head_readable must be a bool")
        if not self.head_readable and (
            self.head_commit is not None or self.head_tree is not None
        ):
            raise ValueError("unreadable HEAD cannot carry a commit or tree")
        _require_ref_namespace(self.private_ref_namespace)
        _require_digest(self.repository_policy_digest, "repository_policy_digest")
        _require_digest(self.capability_policy_digest, "capability_policy_digest")

    @property
    def observation_digest(self) -> str:
        return canonical_workspace_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "agent_member_id": self.agent_member_id,
            "agent_id": self.agent_id,
            "workspace_generation": self.workspace_generation,
            "volume_id": self.volume_id,
            "clone_logical_root": self.clone_logical_root,
            "git_directory_kind": self.git_directory_kind.value,
            "internal_git_service_id": self.internal_git_service_id,
            "internal_git_endpoint": self.internal_git_endpoint,
            "repository_id": self.repository_id,
            "object_format": self.object_format.value,
            "base_commit": self.base_commit,
            "head_commit": self.head_commit,
            "head_tree": self.head_tree,
            "head_readable": self.head_readable,
            "private_ref_namespace": self.private_ref_namespace,
            "repository_policy_digest": self.repository_policy_digest,
            "capability_policy_digest": self.capability_policy_digest,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True, slots=True)
class AgentGitWorkspaceRestoreComparison:
    workspace_id: str
    workspace_identity_digest: str
    observation_digest: str
    drift: tuple[AgentGitWorkspaceIdentityDriftKind, ...]
    compared_at: str
    schema_version: str = AGENT_GIT_WORKSPACE_RESTORE_COMPARISON_SCHEMA_VERSION

    @property
    def matches(self) -> bool:
        return not self.drift


def compare_agent_git_workspace_identity(
    workspace: AgentGitWorkspace,
    observation: AgentGitWorkspaceObservation,
) -> AgentGitWorkspaceRestoreComparison:
    drift: list[AgentGitWorkspaceIdentityDriftKind] = []

    def note(kind: AgentGitWorkspaceIdentityDriftKind, matches: bool) -> None:
        if not matches and kind not in drift:
            drift.append(kind)

    note(
        AgentGitWorkspaceIdentityDriftKind.WORKSPACE,
        observation.workspace_id == workspace.workspace_id,
    )
    note(
        AgentGitWorkspaceIdentityDriftKind.OWNER,
        (
            observation.session_id,
            observation.agent_member_id,
            observation.agent_id,
        )
        == (workspace.session_id, workspace.agent_member_id, workspace.agent_id),
    )
    note(
        AgentGitWorkspaceIdentityDriftKind.GENERATION,
        observation.workspace_generation == workspace.workspace_generation,
    )
    note(
        AgentGitWorkspaceIdentityDriftKind.VOLUME,
        observation.volume_id == workspace.volume_id,
    )
    note(
        AgentGitWorkspaceIdentityDriftKind.CLONE_ROOT,
        observation.clone_logical_root == workspace.clone_logical_root,
    )
    note(
        AgentGitWorkspaceIdentityDriftKind.GIT_DIRECTORY,
        observation.git_directory_kind is AgentGitDirectoryKind.INDEPENDENT,
    )
    note(
        AgentGitWorkspaceIdentityDriftKind.REMOTE_IDENTITY,
        (
            observation.internal_git_service_id,
            observation.internal_git_endpoint,
            observation.repository_id,
        )
        == (
            workspace.internal_git_service_id,
            workspace.internal_git_endpoint,
            workspace.repository_id,
        ),
    )
    note(
        AgentGitWorkspaceIdentityDriftKind.OBJECT_FORMAT,
        observation.object_format is workspace.object_format,
    )
    note(
        AgentGitWorkspaceIdentityDriftKind.BASE_COMMIT,
        observation.base_commit == workspace.base_commit,
    )
    note(
        AgentGitWorkspaceIdentityDriftKind.HEAD_UNREADABLE,
        observation.head_readable,
    )
    # A ready workspace's HEAD is intentionally mutable agent-owned state. The
    # canonical record keeps the readiness HEAD as an audit fact, while current
    # HEAD/tree are projected through append-only state observations. Recovery
    # therefore proves readability here and must not mistake a normal local
    # commit for identity drift.
    note(
        AgentGitWorkspaceIdentityDriftKind.PRIVATE_NAMESPACE,
        observation.private_ref_namespace == workspace.private_ref_namespace,
    )
    note(
        AgentGitWorkspaceIdentityDriftKind.POLICY,
        (
            observation.repository_policy_digest,
            observation.capability_policy_digest,
        )
        == (
            workspace.repository_policy_digest,
            workspace.capability_policy_digest,
        ),
    )
    return AgentGitWorkspaceRestoreComparison(
        workspace_id=workspace.workspace_id,
        workspace_identity_digest=workspace.workspace_identity_digest,
        observation_digest=observation.observation_digest,
        drift=tuple(drift),
        compared_at=observation.observed_at,
    )


__all__ = [
    "AGENT_GIT_WORKSPACE_OBSERVATION_SCHEMA_VERSION",
    "AGENT_GIT_WORKSPACE_RESTORE_COMPARISON_SCHEMA_VERSION",
    "AGENT_GIT_WORKSPACE_SCHEMA_VERSION",
    "AgentGitDirectoryKind",
    "AgentGitWorkspace",
    "AgentGitWorkspaceBlockerCode",
    "AgentGitWorkspaceIdentityDriftKind",
    "AgentGitWorkspaceObservation",
    "AgentGitWorkspaceRestoreComparison",
    "AgentGitWorkspaceStatus",
    "canonical_workspace_digest",
    "compare_agent_git_workspace_identity",
]
