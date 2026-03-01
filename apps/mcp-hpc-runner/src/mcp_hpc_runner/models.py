from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

ExecutionMode = Literal["ssh", "sbatch", "auto"]
SelectedMode = Literal["ssh", "sbatch"]


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


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
    required: bool = True
    stage_to: str = "work"  # "work" or "out"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StagedInput":
        return cls(
            local_path=str(data["local_path"]),
            remote_path=str(data["remote_path"]),
            required=bool(data.get("required", True)),
            stage_to=str(data.get("stage_to", "work")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "local_path": self.local_path,
            "remote_path": self.remote_path,
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
class FallbackStep:
    mode: str
    reason: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FallbackStep":
        return cls(mode=str(data["mode"]), reason=str(data["reason"]))

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "reason": self.reason}


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
    fallback: list[FallbackStep] = field(default_factory=list)
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
            fallback=[
                FallbackStep.from_dict(value) for value in data.get("fallback", [])
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
            "fallback": [value.to_dict() for value in self.fallback],
            "metadata": self.metadata,
            "run_id": self.run_id,
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
