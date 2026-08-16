from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .client import call


@dataclass(frozen=True, slots=True)
class WorkspaceRevisionJob:
    execution_id: str
    operation_id: str
    request_id: str
    source_revision_id: str
    source_commit: str
    source_tree: str
    cwd: str

    def observe(self) -> dict[str, Any]:
        return dict(
            call(
                "workspace_revision_job.observe",
                {
                    "execution_id": self.execution_id,
                    "operation_id": self.operation_id,
                    "request_id": self.request_id,
                },
            )
        )

    def cancel(self, *, reason_code: str) -> dict[str, Any]:
        return dict(
            call(
                "workspace_revision_job.cancel",
                {
                    "execution_id": self.execution_id,
                    "operation_id": self.operation_id,
                    "request_id": self.request_id,
                    "reason_code": reason_code,
                },
            )
        )


def submit(
    *,
    request_id: str,
    source_revision_id: str,
    source_commit: str,
    source_tree: str,
    lfs_closure_manifest_digest: str,
    cwd: str,
    command: tuple[str, ...],
    resources: dict[str, int | str],
    requested_mode: str,
    absolute_deadline: str,
) -> WorkspaceRevisionJob:
    payload = dict(
        call(
            "workspace_revision_job.submit",
            {
                "schema_version": "workspace_revision_job_sdk_request@1",
                "request_id": request_id,
                "source_revision_id": source_revision_id,
                "source_commit": source_commit,
                "source_tree": source_tree,
                "lfs_closure_manifest_digest": lfs_closure_manifest_digest,
                "cwd": cwd,
                "command": list(command),
                "resources": dict(resources),
                "requested_mode": requested_mode,
                "absolute_deadline": absolute_deadline,
            },
        )
    )
    return WorkspaceRevisionJob(
        execution_id=str(payload["execution_id"]),
        operation_id=str(payload["operation_id"]),
        request_id=request_id,
        source_revision_id=source_revision_id,
        source_commit=source_commit,
        source_tree=source_tree,
        cwd=cwd,
    )


__all__ = ["WorkspaceRevisionJob", "submit"]
