from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Literal

ExecutionMode = Literal["ssh", "sbatch", "auto"]
SelectedMode = Literal["ssh", "sbatch"]
WORKSPACE_RUNSPEC_SCHEMA_VERSION = "executor_workspace_runspec@2"
_STALE_ARTIFACT_RUNSPEC_FIELDS = frozenset(
    {
        "inputs",
        "input_artifact_ids",
        "artifact_ids",
        "artifact_id",
        "artifacts",
        "stage_to",
        "hpc_stage_ref",
        "hpc_stage_refs",
        "expected_outputs",
        "output_fetch",
        "remote_run_dir",
        "local_path",
        "run_id",
    }
)


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(slots=True)
class ResourceSpec:
    cpus: int = 1
    mem_mb: int = 1024
    gpus: int = 0
    time_minutes: int = 10
    partition: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ResourceSpec":
        data = data or {}
        return cls(
            cpus=int(data.get("cpus", 1)),
            mem_mb=int(data.get("mem_mb", 1024)),
            gpus=int(data.get("gpus", 0)),
            time_minutes=int(data.get("time_minutes", 10)),
            partition=data.get("partition"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpus": self.cpus,
            "mem_mb": self.mem_mb,
            "gpus": self.gpus,
            "time_minutes": self.time_minutes,
            "partition": self.partition,
        }


@dataclass(slots=True)
class StagedInput:
    local_path: str
    remote_path: str
    artifact_id: str | None = None
    required: bool = True
    stage_to: str = "work"  # "work" or "out"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StagedInput":
        return cls(
            local_path=str(data["local_path"]),
            remote_path=str(data["remote_path"]),
            artifact_id=None if data.get("artifact_id") is None else str(data["artifact_id"]),
            required=bool(data.get("required", True)),
            stage_to=str(data.get("stage_to", "work")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "local_path": self.local_path,
            "remote_path": self.remote_path,
            "artifact_id": self.artifact_id,
            "required": self.required,
            "stage_to": self.stage_to,
        }


@dataclass(slots=True)
class ExpectedOutput:
    path: str
    kind: Literal["file", "dir"] = "file"
    required: bool = True
    non_empty: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExpectedOutput":
        return cls(
            path=str(data["path"]),
            kind=str(data.get("kind", "file")),
            required=bool(data.get("required", True)),
            non_empty=bool(data.get("non_empty", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "required": self.required,
            "non_empty": self.non_empty,
        }


@dataclass(slots=True)
class SuccessCheck:
    check_type: Literal["exists", "non_empty", "json"]
    path: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SuccessCheck":
        return cls(check_type=str(data["check_type"]), path=str(data["path"]))

    def to_dict(self) -> dict[str, Any]:
        return {"check_type": self.check_type, "path": self.path}


@dataclass(slots=True)
class FailureSignature:
    pattern: str
    error_code: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FailureSignature":
        return cls(pattern=str(data["pattern"]), error_code=str(data["error_code"]))

    def to_dict(self) -> dict[str, Any]:
        return {"pattern": self.pattern, "error_code": self.error_code}


@dataclass(slots=True)
class RunSpec:
    name: str
    stage: str
    command: list[str]
    execution_mode: ExecutionMode = "auto"
    resources: ResourceSpec = field(default_factory=ResourceSpec)
    inputs: list[StagedInput] = field(default_factory=list)
    expected_outputs: list[ExpectedOutput] = field(default_factory=list)
    success_checks: list[SuccessCheck] = field(default_factory=list)
    failure_signatures: list[FailureSignature] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    run_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunSpec":
        return cls(
            name=str(data["name"]),
            stage=str(data["stage"]),
            command=[str(value) for value in data.get("command", [])],
            execution_mode=str(data.get("execution_mode", "auto")),
            resources=ResourceSpec.from_dict(data.get("resources")),
            inputs=[StagedInput.from_dict(value) for value in data.get("inputs", [])],
            expected_outputs=[
                ExpectedOutput.from_dict(value)
                for value in data.get("expected_outputs", [])
            ],
            success_checks=[
                SuccessCheck.from_dict(value)
                for value in data.get("success_checks", [])
            ],
            failure_signatures=[
                FailureSignature.from_dict(value)
                for value in data.get("failure_signatures", [])
            ],
            metadata=dict(data.get("metadata", {})),
            run_id=data.get("run_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "stage": self.stage,
            "command": self.command,
            "execution_mode": self.execution_mode,
            "resources": self.resources.to_dict(),
            "inputs": [value.to_dict() for value in self.inputs],
            "expected_outputs": [value.to_dict() for value in self.expected_outputs],
            "success_checks": [value.to_dict() for value in self.success_checks],
            "failure_signatures": [
                value.to_dict() for value in self.failure_signatures
            ],
            "metadata": self.metadata,
            "run_id": self.run_id,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceSourceManifestEntry:
    path: str
    object_id: str
    mode: str
    size_bytes: int
    content_digest: str
    lfs_oid: str | None = None
    schema_version: str = "compute_source_manifest_entry@1"

    def __post_init__(self) -> None:
        path = PurePosixPath(self.path)
        if (
            not self.path
            or path.is_absolute()
            or ".." in path.parts
            or path.as_posix() != self.path
            or self.path == ".git"
            or self.path.startswith(".git/")
        ):
            raise ValueError("workspace source manifest path is invalid")
        if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", self.object_id) is None:
            raise ValueError("workspace source object id is invalid")
        if self.mode not in {"100644", "100755", "120000"}:
            raise ValueError("workspace source mode is unsupported")
        if (
            not isinstance(self.size_bytes, int)
            or isinstance(self.size_bytes, bool)
            or self.size_bytes < 0
        ):
            raise ValueError("workspace source size is invalid")
        for value in (self.content_digest, self.lfs_oid):
            if value is not None and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
                raise ValueError("workspace source digest is invalid")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkspaceSourceManifestEntry":
        expected = {
            "schema_version",
            "path",
            "object_id",
            "mode",
            "size_bytes",
            "content_digest",
            "lfs_oid",
        }
        if not isinstance(data, dict) or set(data) != expected:
            raise ValueError("workspace source manifest entry fields are closed")
        if data["schema_version"] != "compute_source_manifest_entry@1":
            raise ValueError("workspace source manifest entry schema is unsupported")
        return cls(**data)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "path": self.path,
            "object_id": self.object_id,
            "mode": self.mode,
            "size_bytes": self.size_bytes,
            "content_digest": self.content_digest,
            "lfs_oid": self.lfs_oid,
        }


@dataclass(frozen=True, slots=True)
class ExecutorWorkspaceRunSpec:
    execution_id: str
    operation_id: str
    dispatch_id: str
    runner_run_id: str
    executor_hpc_workspace_id: str
    executor_hpc_workspace_generation: int
    repository_binding_id: str
    repository_binding_version: int
    repository_binding_digest: str
    repository_policy_digest: str
    source_manifest_id: str
    source_request_id: str
    source_commit: str
    source_tree: str
    lfs_closure_manifest_digest: str
    source_manifest: tuple[WorkspaceSourceManifestEntry, ...]
    source_manifest_digest: str
    source_owner_identity_digest: str
    source_manifest_created_at: str
    target_profile_digest: str
    runner_policy_digest: str
    toolchain_digest: str
    cwd: str
    command: tuple[str, ...]
    command_digest: str
    environment_policy_digest: str
    resource_digest: str
    selected_mode: SelectedMode
    scheduler_marker: str
    payload_digest: str
    absolute_deadline: str
    resources: ResourceSpec
    schema_version: str = WORKSPACE_RUNSPEC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != WORKSPACE_RUNSPEC_SCHEMA_VERSION:
            raise ValueError("workspace RunSpec schema is unsupported")
        for name in (
            "executor_hpc_workspace_generation",
            "repository_binding_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in (
            "execution_id",
            "operation_id",
            "dispatch_id",
            "runner_run_id",
            "executor_hpc_workspace_id",
            "repository_binding_id",
            "scheduler_marker",
            "source_manifest_id",
            "source_request_id",
        ):
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", getattr(self, name)) is None:
                raise ValueError(f"workspace RunSpec {name} is invalid")
        for name in (
            "repository_binding_digest",
            "repository_policy_digest",
            "lfs_closure_manifest_digest",
            "source_manifest_digest",
            "source_owner_identity_digest",
            "target_profile_digest",
            "runner_policy_digest",
            "toolchain_digest",
            "command_digest",
            "environment_policy_digest",
            "resource_digest",
            "payload_digest",
        ):
            if re.fullmatch(r"sha256:[0-9a-f]{64}", getattr(self, name)) is None:
                raise ValueError(f"workspace RunSpec {name} is invalid")
        for name in ("source_commit", "source_tree"):
            if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", getattr(self, name)) is None:
                raise ValueError(f"workspace RunSpec {name} is invalid")
        paths = tuple(entry.path for entry in self.source_manifest)
        if not paths or paths != tuple(sorted(set(paths))):
            raise ValueError("workspace source manifest must be non-empty and sorted")
        if self.cwd != "." and (
            not self.cwd
            or self.cwd.startswith("/")
            or "\\" in self.cwd
            or any(part in {"", ".", ".."} for part in self.cwd.split("/"))
        ):
            raise ValueError("workspace RunSpec cwd must remain relative to its root")
        if self.selected_mode not in {"ssh", "sbatch"}:
            raise ValueError("workspace RunSpec selected mode must be frozen")
        if not self.absolute_deadline or any(
            character.isspace() for character in self.absolute_deadline
        ):
            raise ValueError("workspace RunSpec absolute deadline is invalid")
        if not self.command or any(not value for value in self.command):
            raise ValueError("workspace RunSpec command is empty")
        if self.command_digest != _canonical_digest(list(self.command)):
            raise ValueError("workspace RunSpec command digest mismatch")
        if self.resource_digest != _canonical_digest(self.resources.to_dict()):
            raise ValueError("workspace RunSpec resource digest mismatch")
        manifest_payload = {
            "schema_version": "compute_source_manifest@1",
            "manifest_id": self.source_manifest_id,
            "request_id": self.source_request_id,
            "workspace_id": self.executor_hpc_workspace_id,
            "source_commit": self.source_commit,
            "source_tree": self.source_tree,
            "lfs_closure_manifest_digest": self.lfs_closure_manifest_digest,
            "binding_digest": self.repository_binding_digest,
            "repository_policy_digest": self.repository_policy_digest,
            "toolchain_digest": self.toolchain_digest,
            "owner_identity_digest": self.source_owner_identity_digest,
            "entries": [entry.to_dict() for entry in self.source_manifest],
            "created_at": self.source_manifest_created_at,
        }
        if self.source_manifest_digest != _canonical_digest(manifest_payload):
            raise ValueError("workspace RunSpec source manifest digest mismatch")
        for name, minimum in (
            ("cpus", 1),
            ("mem_mb", 1),
            ("gpus", 0),
            ("time_minutes", 1),
        ):
            value = getattr(self.resources, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
                raise ValueError(
                    f"workspace RunSpec resources.{name} is below its minimum"
                )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutorWorkspaceRunSpec":
        if not isinstance(data, dict):
            raise ValueError("workspace RunSpec must be an object")
        stale = sorted(set(data) & _STALE_ARTIFACT_RUNSPEC_FIELDS)
        if stale:
            raise ValueError(
                "current workspace RunSpec forbids artifact staging/fetch fields: "
                + ", ".join(stale)
            )
        expected = {
            "schema_version",
            "execution_id",
            "operation_id",
            "dispatch_id",
            "runner_run_id",
            "executor_hpc_workspace_id",
            "executor_hpc_workspace_generation",
            "repository_binding_id",
            "repository_binding_version",
            "repository_binding_digest",
            "repository_policy_digest",
            "source_manifest_id",
            "source_request_id",
            "source_commit",
            "source_tree",
            "lfs_closure_manifest_digest",
            "source_manifest",
            "source_manifest_digest",
            "source_owner_identity_digest",
            "source_manifest_created_at",
            "target_profile_digest",
            "runner_policy_digest",
            "toolchain_digest",
            "cwd",
            "command",
            "command_digest",
            "environment_policy_digest",
            "resource_digest",
            "selected_mode",
            "scheduler_marker",
            "payload_digest",
            "absolute_deadline",
            "resources",
        }
        if set(data) != expected:
            raise ValueError(
                "workspace RunSpec fields are incomplete or unknown"
            )
        if data["schema_version"] != WORKSPACE_RUNSPEC_SCHEMA_VERSION:
            raise ValueError("workspace RunSpec schema is unsupported")
        raw_command = data["command"]
        if not isinstance(raw_command, list) or not raw_command:
            raise ValueError("workspace RunSpec command must be a non-empty argv array")
        if any(not isinstance(value, str) or not value for value in raw_command):
            raise ValueError("workspace RunSpec command entries must be non-empty strings")
        raw_manifest = data["source_manifest"]
        if not isinstance(raw_manifest, list) or not raw_manifest:
            raise ValueError("workspace RunSpec source_manifest must be non-empty")
        resources = data["resources"]
        if not isinstance(resources, dict):
            raise ValueError("workspace RunSpec resources must be an object")
        allowed_resource_fields = {
            "cpus",
            "mem_mb",
            "gpus",
            "time_minutes",
            "partition",
        }
        if not set(resources) <= allowed_resource_fields:
            raise ValueError("workspace RunSpec resource fields are unknown")
        resource_values: dict[str, Any] = {
            "cpus": resources.get("cpus", 1),
            "mem_mb": resources.get("mem_mb", 1024),
            "gpus": resources.get("gpus", 0),
            "time_minutes": resources.get("time_minutes", 10),
            "partition": resources.get("partition"),
        }
        for name in ("cpus", "mem_mb", "gpus", "time_minutes"):
            value = resource_values[name]
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(
                    f"workspace RunSpec resources.{name} must be an integer"
                )
        partition = resource_values["partition"]
        if partition is not None and not isinstance(partition, str):
            raise ValueError(
                "workspace RunSpec resources.partition must be a string or null"
            )
        for name in (
            "execution_id",
            "operation_id",
            "dispatch_id",
            "runner_run_id",
            "executor_hpc_workspace_id",
            "repository_binding_id",
            "repository_binding_digest",
            "repository_policy_digest",
            "source_manifest_id",
            "source_request_id",
            "source_commit",
            "source_tree",
            "lfs_closure_manifest_digest",
            "source_manifest_digest",
            "source_owner_identity_digest",
            "source_manifest_created_at",
            "target_profile_digest",
            "runner_policy_digest",
            "toolchain_digest",
            "cwd",
            "command_digest",
            "environment_policy_digest",
            "resource_digest",
            "selected_mode",
            "scheduler_marker",
            "payload_digest",
            "absolute_deadline",
        ):
            if not isinstance(data[name], str):
                raise ValueError(f"workspace RunSpec {name} must be a string")
        for name in (
            "executor_hpc_workspace_generation",
            "repository_binding_version",
        ):
            value = data[name]
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"workspace RunSpec {name} must be an integer")
        return cls(
            execution_id=data["execution_id"],
            operation_id=data["operation_id"],
            dispatch_id=data["dispatch_id"],
            runner_run_id=data["runner_run_id"],
            executor_hpc_workspace_id=data["executor_hpc_workspace_id"],
            executor_hpc_workspace_generation=data[
                "executor_hpc_workspace_generation"
            ],
            repository_binding_id=data["repository_binding_id"],
            repository_binding_version=data["repository_binding_version"],
            repository_binding_digest=data["repository_binding_digest"],
            repository_policy_digest=data["repository_policy_digest"],
            source_manifest_id=data["source_manifest_id"],
            source_request_id=data["source_request_id"],
            source_commit=data["source_commit"],
            source_tree=data["source_tree"],
            lfs_closure_manifest_digest=data["lfs_closure_manifest_digest"],
            source_manifest=tuple(
                WorkspaceSourceManifestEntry.from_dict(item)
                for item in raw_manifest
            ),
            source_manifest_digest=data["source_manifest_digest"],
            source_owner_identity_digest=data["source_owner_identity_digest"],
            source_manifest_created_at=data["source_manifest_created_at"],
            target_profile_digest=data["target_profile_digest"],
            runner_policy_digest=data["runner_policy_digest"],
            toolchain_digest=data["toolchain_digest"],
            cwd=data["cwd"],
            command=tuple(raw_command),
            command_digest=data["command_digest"],
            environment_policy_digest=data["environment_policy_digest"],
            resource_digest=data["resource_digest"],
            selected_mode=data["selected_mode"],
            scheduler_marker=data["scheduler_marker"],
            payload_digest=data["payload_digest"],
            absolute_deadline=data["absolute_deadline"],
            resources=ResourceSpec(**resource_values),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "execution_id": self.execution_id,
            "operation_id": self.operation_id,
            "dispatch_id": self.dispatch_id,
            "runner_run_id": self.runner_run_id,
            "executor_hpc_workspace_id": self.executor_hpc_workspace_id,
            "executor_hpc_workspace_generation": (
                self.executor_hpc_workspace_generation
            ),
            "repository_binding_id": self.repository_binding_id,
            "repository_binding_version": self.repository_binding_version,
            "repository_binding_digest": self.repository_binding_digest,
            "repository_policy_digest": self.repository_policy_digest,
            "source_manifest_id": self.source_manifest_id,
            "source_request_id": self.source_request_id,
            "source_commit": self.source_commit,
            "source_tree": self.source_tree,
            "lfs_closure_manifest_digest": self.lfs_closure_manifest_digest,
            "source_manifest": [entry.to_dict() for entry in self.source_manifest],
            "source_manifest_digest": self.source_manifest_digest,
            "source_owner_identity_digest": self.source_owner_identity_digest,
            "source_manifest_created_at": self.source_manifest_created_at,
            "target_profile_digest": self.target_profile_digest,
            "runner_policy_digest": self.runner_policy_digest,
            "toolchain_digest": self.toolchain_digest,
            "cwd": self.cwd,
            "command": list(self.command),
            "command_digest": self.command_digest,
            "environment_policy_digest": self.environment_policy_digest,
            "resource_digest": self.resource_digest,
            "selected_mode": self.selected_mode,
            "scheduler_marker": self.scheduler_marker,
            "payload_digest": self.payload_digest,
            "absolute_deadline": self.absolute_deadline,
            "resources": self.resources.to_dict(),
        }


@dataclass(slots=True)
class JobHandle:
    run_id: str
    job_id: str
    remote_run_dir: str
    submitted_at: str = field(default_factory=_now_iso)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobHandle":
        return cls(
            run_id=str(data["run_id"]),
            job_id=str(data["job_id"]),
            remote_run_dir=str(data["remote_run_dir"]),
            submitted_at=str(data.get("submitted_at", _now_iso())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "job_id": self.job_id,
            "remote_run_dir": self.remote_run_dir,
            "submitted_at": self.submitted_at,
        }


@dataclass(slots=True)
class JobStatus:
    run_id: str
    job_id: str
    state: str
    raw_state: str | None = None
    exit_code: int | None = None
    message: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "job_id": self.job_id,
            "state": self.state,
            "raw_state": self.raw_state,
            "exit_code": self.exit_code,
            "message": self.message,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class RunResult:
    run_id: str
    requested_mode: str
    selected_mode: str
    remote_run_dir: str
    status: str
    exit_code: int | None = None
    job_id: str | None = None
    stdout: str | None = None
    stderr: str | None = None
    error_code: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    logs: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "requested_mode": self.requested_mode,
            "selected_mode": self.selected_mode,
            "remote_run_dir": self.remote_run_dir,
            "status": self.status,
            "exit_code": self.exit_code,
            "job_id": self.job_id,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error_code": self.error_code,
            "artifacts": self.artifacts,
            "logs": self.logs,
            "metadata": self.metadata,
        }
