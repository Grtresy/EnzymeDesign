from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Protocol
from typing import Any

from .sandbox_host import SandboxHostCallContext


FILE_WORKSPACE_SANDBOX_CONTRACT_ID = "file_workspace_sandbox@1"
FILE_WORKSPACE_UNSUPPORTED_ERROR_SCHEMA = (
    "unsupported_current_file_workspace_contract@1"
)


class CurrentFileWorkspaceContractError(RuntimeError):
    error_code = "unsupported_current_file_workspace_contract"

    def __init__(self, *, field_or_operation: str) -> None:
        super().__init__(
            f"{field_or_operation} is unsupported by {FILE_WORKSPACE_SANDBOX_CONTRACT_ID}"
        )
        self.details = {
            "schema_id": FILE_WORKSPACE_UNSUPPORTED_ERROR_SCHEMA,
            "field_or_operation": field_or_operation,
            "replacement_inferred": False,
            "mutation_applied": False,
        }


class FileWorkspaceHostOperation(StrEnum):
    WORKSPACE_PUBLISH = "workspace.publish"
    EXTERNAL_JOB_DISPATCH = "external_job.dispatch"
    EXTERNAL_JOB_RECONCILE = "external_job.reconcile"
    EXTERNAL_JOB_CANCEL = "external_job.cancel"
    CONTINUATION_SETTLE = "continuation.settle"
    PROTOCOL_MUTATE = "protocol.mutate"
    TASK_MUTATE = "task.mutate"
    RUNTIME_INSPECT = "runtime.inspect"


_FORBIDDEN_KEYS = frozenset(
    {
        "artifact_id",
        "artifact_ids",
        "artifact_set_digest",
        "catalog_ref",
        "expected_outputs",
        "hpc_stage_ref",
        "source_snapshot_artifact_id",
        "storage_uri",
    }
)


def _walk_forbidden(value: object, *, path: str = "request") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in _FORBIDDEN_KEYS:
                raise CurrentFileWorkspaceContractError(
                    field_or_operation=f"{path}.{key}"
                )
            _walk_forbidden(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _walk_forbidden(item, path=f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class FileWorkspaceHostRequest:
    operation: FileWorkspaceHostOperation
    session_id: str
    body: dict[str, object]
    request_digest: str
    execution_id: str | None = None
    continuation_id: str | None = None
    schema_version: str = "file_workspace_host_request@1"

    def __post_init__(self) -> None:
        if not self.session_id or self.session_id != self.session_id.strip():
            raise ValueError("file-workspace Host request requires an exact session")
        _walk_forbidden(self.body)
        if self.request_digest != self.canonical_digest:
            raise ValueError("file-workspace Host request digest mismatch")

    @property
    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "operation": self.operation.value,
            "session_id": self.session_id,
            "execution_id": self.execution_id,
            "continuation_id": self.continuation_id,
            "body": self.body,
        }

    @property
    def canonical_digest(self) -> str:
        encoded = json.dumps(
            self.payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    @classmethod
    def create(cls, **values: Any) -> "FileWorkspaceHostRequest":
        operation = values["operation"]
        if not isinstance(operation, FileWorkspaceHostOperation):
            raise TypeError("operation must be a FileWorkspaceHostOperation")
        payload = {
            "schema_version": "file_workspace_host_request@1",
            "operation": operation.value,
            "session_id": values["session_id"],
            "execution_id": values.get("execution_id"),
            "continuation_id": values.get("continuation_id"),
            "body": values["body"],
        }
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return cls(
            **values,
            request_digest="sha256:" + hashlib.sha256(encoded).hexdigest(),
        )


class FileWorkspaceSandboxHostGateway(Protocol):
    def invoke_control_plane(
        self,
        *,
        request: FileWorkspaceHostRequest,
        context: SandboxHostCallContext,
    ) -> dict[str, object]: ...


def reject_stale_file_workspace_value(value: object) -> None:
    _walk_forbidden(value)


__all__ = [
    "FILE_WORKSPACE_SANDBOX_CONTRACT_ID",
    "FILE_WORKSPACE_UNSUPPORTED_ERROR_SCHEMA",
    "CurrentFileWorkspaceContractError",
    "FileWorkspaceHostOperation",
    "FileWorkspaceHostRequest",
    "FileWorkspaceSandboxHostGateway",
    "reject_stale_file_workspace_value",
]
