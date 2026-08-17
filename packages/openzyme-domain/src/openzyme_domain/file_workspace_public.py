from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any


FILE_WORKSPACE_PUBLIC_SCHEMA_VERSION = "file_workspace_public@1"
FILE_WORKSPACE_PUBLIC_CONTRACT_ID = "file_workspace_public@1"


_PRIVATE_KEYS = frozenset(
    {
        "credential",
        "host_path",
        "private_ref",
        "raw_backend_log",
        "raw_job_handle",
        "remote_directory",
        "runner_handle",
        "slurm_job_id",
        "storage_uri",
        "token",
    }
)
_REMOVED_PUBLIC_KEY_FRAGMENTS = (
    "arti" + "fact",
    "catalog",
    "materialization",
    "staging_ref",
    "storage_uri",
)


def _assert_shared_safe(value: object, *, path: str = "projection") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).lower()
            if normalized_key in _PRIVATE_KEYS or any(
                fragment in normalized_key
                for fragment in _REMOVED_PUBLIC_KEY_FRAGMENTS
            ):
                raise ValueError(f"private field is forbidden at {path}.{key}")
            _assert_shared_safe(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_shared_safe(item, path=f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class ExecutorOwnerWorkspaceView:
    subject_agent_member_id: str
    workspace_id: str
    workspace_generation: int
    login_alias: str
    workspace_path: str
    capability_lease_id: str
    view_digest: str
    schema_version: str = "executor_owner_workspace_view@1"

    def __post_init__(self) -> None:
        locator_text = f"{self.login_alias}\n{self.workspace_path}".lower()
        if self.workspace_generation < 1:
            raise ValueError("executor owner workspace generation must be positive")
        if (
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", self.login_alias)
            is None
            or not self.workspace_path.startswith("/")
            or len(self.workspace_path.encode("utf-8")) > 4096
            or any(part in {"", ".", ".."} for part in self.workspace_path.split("/")[1:])
            or any(character in self.workspace_path for character in ("\x00", "\n", "\r"))
            or any(
                marker in locator_text
                for marker in (
                    "authorization:",
                    "bearer ",
                    "password=",
                    "private_key",
                    "secret=",
                    "token=",
                )
            )
        ):
            raise ValueError("executor owner view requires exact native locator")
        if self.view_digest != self.canonical_digest:
            raise ValueError("executor owner workspace view digest mismatch")

    @property
    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "subject_agent_member_id": self.subject_agent_member_id,
            "workspace_id": self.workspace_id,
            "workspace_generation": self.workspace_generation,
            "login_alias": self.login_alias,
            "workspace_path": self.workspace_path,
            "capability_lease_id": self.capability_lease_id,
        }

    @property
    def canonical_digest(self) -> str:
        encoded = json.dumps(
            self.payload,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    @classmethod
    def create(cls, **values: Any) -> "ExecutorOwnerWorkspaceView":
        payload = {"schema_version": "executor_owner_workspace_view@1", **values}
        encoded = json.dumps(
            payload,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return cls(
            **values,
            view_digest="sha256:" + hashlib.sha256(encoded).hexdigest(),
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.payload, "view_digest": self.view_digest}


@dataclass(frozen=True, slots=True)
class FileWorkspacePublicProjection:
    session: dict[str, object]
    repository_binding: dict[str, object]
    agent_workspaces: tuple[dict[str, object], ...]
    workspace_status: tuple[dict[str, object], ...]
    private_revisions: tuple[dict[str, object], ...]
    published_revisions: tuple[dict[str, object], ...]
    reports: tuple[dict[str, object], ...]
    scientific_deliverables: tuple[dict[str, object], ...]
    external_jobs: tuple[dict[str, object], ...]
    external_job_results: tuple[dict[str, object], ...]
    capability_leases: tuple[dict[str, object], ...]
    executor_owner_workspace: ExecutorOwnerWorkspaceView | None
    conversation: tuple[dict[str, object], ...]
    task_board: dict[str, object]
    lane_board: dict[str, object]
    agents: tuple[dict[str, object], ...]
    pending_approvals: tuple[dict[str, object], ...]
    activity_feed: tuple[dict[str, object], ...]
    failure_observations: tuple[dict[str, object], ...]
    tool_catalog_digest: str
    schema_bundle_digest: str
    schema_version: str = FILE_WORKSPACE_PUBLIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        shared = {
            "session": self.session,
            "repository_binding": self.repository_binding,
            "agent_workspaces": self.agent_workspaces,
            "workspace_status": self.workspace_status,
            "private_revisions": self.private_revisions,
            "published_revisions": self.published_revisions,
            "reports": self.reports,
            "scientific_deliverables": self.scientific_deliverables,
            "external_jobs": self.external_jobs,
            "external_job_results": self.external_job_results,
            "capability_leases": self.capability_leases,
            "conversation": self.conversation,
            "task_board": self.task_board,
            "lane_board": self.lane_board,
            "agents": self.agents,
            "pending_approvals": self.pending_approvals,
            "activity_feed": self.activity_feed,
            "failure_observations": self.failure_observations,
        }
        _assert_shared_safe(shared)
        for value in (self.tool_catalog_digest, self.schema_bundle_digest):
            if not value.startswith("sha256:") or len(value) != 71:
                raise ValueError("file-workspace public digest is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "tool_catalog_digest": self.tool_catalog_digest,
            "schema_bundle_digest": self.schema_bundle_digest,
            "session": self.session,
            "repository_binding": self.repository_binding,
            "agent_workspaces": list(self.agent_workspaces),
            "workspace_status": list(self.workspace_status),
            "private_revisions": list(self.private_revisions),
            "published_revisions": list(self.published_revisions),
            "reports": list(self.reports),
            "scientific_deliverables": list(self.scientific_deliverables),
            "external_jobs": list(self.external_jobs),
            "external_job_results": list(self.external_job_results),
            "capability_leases": list(self.capability_leases),
            "conversation": list(self.conversation),
            "task_board": self.task_board,
            "lane_board": self.lane_board,
            "agents": list(self.agents),
            "pending_approvals": list(self.pending_approvals),
            "activity_feed": list(self.activity_feed),
            "failure_observations": list(self.failure_observations),
            "executor_owner_workspace": (
                None
                if self.executor_owner_workspace is None
                else self.executor_owner_workspace.to_dict()
            ),
        }


__all__ = [
    "FILE_WORKSPACE_PUBLIC_SCHEMA_VERSION",
    "FILE_WORKSPACE_PUBLIC_CONTRACT_ID",
    "ExecutorOwnerWorkspaceView",
    "FileWorkspacePublicProjection",
]
