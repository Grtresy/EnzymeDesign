from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any


FILE_WORKSPACE_PUBLIC_SCHEMA_VERSION = "file_workspace_public@1"


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


def _assert_shared_safe(value: object, *, path: str = "projection") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in _PRIVATE_KEYS:
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
        if self.workspace_generation < 1:
            raise ValueError("executor owner workspace generation must be positive")
        if not self.login_alias or not self.workspace_path.startswith("/"):
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
            "executor_owner_workspace": (
                None
                if self.executor_owner_workspace is None
                else self.executor_owner_workspace.to_dict()
            ),
        }


__all__ = [
    "FILE_WORKSPACE_PUBLIC_SCHEMA_VERSION",
    "ExecutorOwnerWorkspaceView",
    "FileWorkspacePublicProjection",
]
