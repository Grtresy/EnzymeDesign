from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re


WORKSPACE_CHECKPOINT_PROOF_INPUT_SCHEMA_VERSION = (
    "workspace_checkpoint_proof_input@1"
)
REMOTE_PRIVATE_REF_OBSERVATION_SCHEMA_VERSION = (
    "remote_private_ref_observation@1"
)
AGENT_WORKSPACE_STATE_OBSERVATION_SCHEMA_VERSION = (
    "agent_workspace_state_observation@2"
)
VERIFIED_WORKSPACE_CHECKPOINT_SCHEMA_VERSION = "verified_workspace_checkpoint@1"
CLEAN_COMMITTED_REVISION_PROOF_SCHEMA_VERSION = "clean_committed_revision_proof@1"


class WorkspaceFormalBoundary(StrEnum):
    DURABLE_CHECKPOINT = "durable_checkpoint"
    PUBLICATION = "publication"
    HANDOFF = "handoff"
    EXTERNAL_JOB = "external_job"
    TASK_TERMINAL = "task_terminal"


class PrivateRefAdvanceKind(StrEnum):
    CREATE = "create"
    FAST_FORWARD = "fast_forward"


class WorkspaceDirtyState(StrEnum):
    CLEAN = "clean"
    DIRTY = "dirty"
    UNKNOWN = "unknown"


def _canonical_digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _require_identifier(value: str, field_name: str) -> None:
    if not value or value != value.strip() or any(char.isspace() for char in value):
        raise ValueError(f"{field_name} must be an exact non-empty identifier")


def _require_object_id(value: str, field_name: str) -> None:
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value) is None:
        raise ValueError(f"{field_name} must be a lowercase Git object id")


def _require_private_ref(value: str) -> None:
    if (
        not value.startswith("refs/openzyme/private/")
        or value.endswith("/")
        or ".." in value
        or "//" in value
        or re.search(r"[\x00-\x20~^:?*\\]", value) is not None
    ):
        raise ValueError("private_ref must be a fully qualified safe private ref")


@dataclass(frozen=True, slots=True)
class RemotePrivateRefObservation:
    service_id: str
    repository_id: str
    private_ref: str
    prior_commit: str | None
    observed_commit: str
    advance_kind: PrivateRefAdvanceKind
    observed_at: str
    schema_version: str = REMOTE_PRIVATE_REF_OBSERVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REMOTE_PRIVATE_REF_OBSERVATION_SCHEMA_VERSION:
            raise ValueError("unsupported remote private ref observation schema")
        _require_identifier(self.service_id, "service_id")
        _require_identifier(self.repository_id, "repository_id")
        _require_private_ref(self.private_ref)
        _require_object_id(self.observed_commit, "observed_commit")
        if self.prior_commit is not None:
            _require_object_id(self.prior_commit, "prior_commit")
        if self.advance_kind is PrivateRefAdvanceKind.CREATE:
            if self.prior_commit is not None:
                raise ValueError("create observation must not carry prior_commit")
        elif self.prior_commit is None:
            raise ValueError("fast-forward observation requires prior_commit")
        _require_identifier(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class WorkspaceCheckpointProofInput:
    boundary: WorkspaceFormalBoundary
    workspace_id: str
    session_id: str
    agent_member_id: str
    agent_id: str
    workspace_generation: int
    repository_binding_id: str
    repository_binding_version: int
    commit: str
    tree: str
    private_ref: str
    remote_observation: RemotePrivateRefObservation
    schema_version: str = WORKSPACE_CHECKPOINT_PROOF_INPUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != WORKSPACE_CHECKPOINT_PROOF_INPUT_SCHEMA_VERSION:
            raise ValueError("unsupported workspace checkpoint proof input schema")
        for field_name in (
            "workspace_id",
            "session_id",
            "agent_member_id",
            "agent_id",
            "repository_binding_id",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        for field_name in ("workspace_generation", "repository_binding_version"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        _require_object_id(self.commit, "commit")
        _require_object_id(self.tree, "tree")
        _require_private_ref(self.private_ref)
        if self.remote_observation.private_ref != self.private_ref:
            raise ValueError("remote observation private ref does not match proof input")
        if self.remote_observation.observed_commit != self.commit:
            raise ValueError("remote observation commit does not match proof input")


@dataclass(frozen=True, slots=True)
class AgentWorkspaceStateObservation:
    observation_id: str
    workspace_id: str
    session_id: str
    agent_member_id: str
    agent_id: str
    workspace_generation: int
    head_commit: str
    head_tree: str
    dirty_state: WorkspaceDirtyState
    staged: bool
    unstaged: bool
    untracked: bool
    changed_paths: tuple[str, ...]
    changed_paths_truncated: bool
    observed_at: str
    schema_version: str = AGENT_WORKSPACE_STATE_OBSERVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_WORKSPACE_STATE_OBSERVATION_SCHEMA_VERSION:
            raise ValueError("unsupported agent workspace state observation schema")
        for field_name in (
            "observation_id",
            "workspace_id",
            "session_id",
            "agent_member_id",
            "agent_id",
            "observed_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        if self.workspace_generation <= 0:
            raise ValueError("workspace_generation must be positive")
        _require_object_id(self.head_commit, "head_commit")
        _require_object_id(self.head_tree, "head_tree")
        has_dirty_entry = self.staged or self.unstaged or self.untracked
        if self.dirty_state is WorkspaceDirtyState.CLEAN and has_dirty_entry:
            raise ValueError("clean workspace observation cannot carry dirty entries")
        if self.dirty_state is WorkspaceDirtyState.DIRTY and not has_dirty_entry:
            raise ValueError("dirty workspace observation requires a dirty entry")
        if len(self.changed_paths) > 2_000 or len(self.changed_paths) != len(
            set(self.changed_paths)
        ):
            raise ValueError("changed workspace paths must be unique and bounded")
        for path in self.changed_paths:
            if (
                not path
                or len(path.encode("utf-8")) > 1024
                or path.startswith("/")
                or "\x00" in path
                or ".." in path.split("/")
            ):
                raise ValueError("changed workspace path is unsafe")
        if self.dirty_state is WorkspaceDirtyState.CLEAN and self.changed_paths:
            raise ValueError("clean workspace observation cannot carry changed paths")


@dataclass(frozen=True, slots=True)
class VerifiedWorkspaceCheckpoint:
    checkpoint_id: str
    boundary: WorkspaceFormalBoundary
    workspace_id: str
    session_id: str
    agent_member_id: str
    agent_id: str
    workspace_generation: int
    repository_binding_id: str
    repository_binding_version: int
    repository_id: str
    commit: str
    tree: str
    private_ref: str
    prior_commit: str | None
    advance_kind: PrivateRefAdvanceKind
    remote_observed_at: str
    verified_at: str
    checkpoint_digest: str
    schema_version: str = VERIFIED_WORKSPACE_CHECKPOINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != VERIFIED_WORKSPACE_CHECKPOINT_SCHEMA_VERSION:
            raise ValueError("unsupported verified workspace checkpoint schema")
        for field_name in (
            "checkpoint_id",
            "workspace_id",
            "session_id",
            "agent_member_id",
            "agent_id",
            "repository_binding_id",
            "repository_id",
            "remote_observed_at",
            "verified_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        if self.workspace_generation <= 0 or self.repository_binding_version <= 0:
            raise ValueError(
                "checkpoint generation and binding version must be positive"
            )
        _require_object_id(self.commit, "commit")
        _require_object_id(self.tree, "tree")
        _require_private_ref(self.private_ref)
        if self.prior_commit is not None:
            _require_object_id(self.prior_commit, "prior_commit")
        expected_digest = _canonical_digest(self.identity_payload)
        if self.checkpoint_digest != expected_digest:
            raise ValueError("checkpoint_digest does not match checkpoint identity")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "checkpoint_id": self.checkpoint_id,
            "boundary": self.boundary.value,
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "agent_member_id": self.agent_member_id,
            "agent_id": self.agent_id,
            "workspace_generation": self.workspace_generation,
            "repository_binding_id": self.repository_binding_id,
            "repository_binding_version": self.repository_binding_version,
            "repository_id": self.repository_id,
            "commit": self.commit,
            "tree": self.tree,
            "private_ref": self.private_ref,
            "prior_commit": self.prior_commit,
            "advance_kind": self.advance_kind.value,
            "remote_observed_at": self.remote_observed_at,
            "verified_at": self.verified_at,
        }

    @classmethod
    def create(cls, **values: object) -> "VerifiedWorkspaceCheckpoint":
        payload = {
            **values,
            "schema_version": VERIFIED_WORKSPACE_CHECKPOINT_SCHEMA_VERSION,
        }
        typed_payload = {
            **payload,
            "boundary": values["boundary"].value,  # type: ignore[union-attr]
            "advance_kind": values["advance_kind"].value,  # type: ignore[union-attr]
        }
        return cls(
            **values,  # type: ignore[arg-type]
            checkpoint_digest=_canonical_digest(typed_payload),
        )


@dataclass(frozen=True, slots=True)
class CleanCommittedRevisionProof:
    workspace_id: str
    workspace_generation: int
    repository_binding_id: str
    repository_binding_version: int
    commit: str
    tree: str
    state_observation_id: str
    verified_checkpoint_id: str
    verified_at: str
    schema_version: str = CLEAN_COMMITTED_REVISION_PROOF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CLEAN_COMMITTED_REVISION_PROOF_SCHEMA_VERSION:
            raise ValueError("unsupported clean committed revision proof schema")
        for field_name in (
            "workspace_id",
            "repository_binding_id",
            "state_observation_id",
            "verified_checkpoint_id",
            "verified_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        if self.workspace_generation <= 0 or self.repository_binding_version <= 0:
            raise ValueError(
                "clean revision generation and binding version must be positive"
            )
        _require_object_id(self.commit, "commit")
        _require_object_id(self.tree, "tree")
