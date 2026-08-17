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
    operation: dict[str, Any],
    execution_request: dict[str, Any],
    clean_observation: dict[str, Any],
) -> WorkspaceRevisionJob:
    if not all(
        isinstance(value, dict)
        for value in (operation, execution_request, clean_observation)
    ):
        raise TypeError(
            "workspace revision submission requires exact operation, execution request, and clean observation objects"
        )
    payload = dict(
        call(
            "workspace_revision_job.submit",
            {
                "schema_version": "workspace_revision_job_admission_request@1",
                "operation": dict(operation),
                "execution_request": dict(execution_request),
                "clean_observation": dict(clean_observation),
            },
        )
    )
    return WorkspaceRevisionJob(
        execution_id=str(payload["execution_id"]),
        operation_id=str(payload["operation_id"]),
        request_id=str(execution_request["request_id"]),
        source_revision_id=str(execution_request["source_revision_id"]),
        source_commit=str(execution_request["source_commit"]),
        source_tree=str(execution_request["source_tree"]),
        cwd=str(execution_request["cwd"]),
    )


__all__ = ["WorkspaceRevisionJob", "submit"]
