from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from typing import Protocol

from openzyme_domain import ArtifactKind
from openzyme_domain import RunStatus
from openzyme_runtime.limits import LimiterRegistry
from openzyme_runtime.seams import ExecutionAdapter

_SUPPORTED_EXECUTION_TOOLS = frozenset({"exec.run"})


class HpcRunnerToolServer(Protocol):
    def call_tool(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]: ...


def _artifact_kind_from_uri(storage_uri: str) -> ArtifactKind:
    path = storage_uri.lower()
    if path.endswith(".log") or "/logs/" in path:
        return ArtifactKind.LOG
    if path.endswith((".pdb", ".cif", ".mol2", ".sdf", ".pdbqt")):
        return ArtifactKind.STRUCTURE
    if path.endswith((".md", ".pdf", ".html")):
        return ArtifactKind.REPORT
    return ArtifactKind.RESULT


def _relative_output_path(remote_path: str) -> str:
    path = PurePosixPath(remote_path)
    parts = path.parts
    if "out" in parts:
        out_index = len(parts) - 1 - list(reversed(parts)).index("out")
        remainder = parts[out_index + 1 :]
        if remainder:
            return str(PurePosixPath(*remainder))
    return path.name


def map_runner_status_to_run_status(status: str) -> RunStatus:
    normalized = status.lower()
    if normalized in {"submitted", "queued", "pending"}:
        return RunStatus.QUEUED
    if normalized in {"running", "in_progress"}:
        return RunStatus.RUNNING
    if normalized in {"completed", "succeeded", "success"}:
        return RunStatus.SUCCEEDED
    if normalized in {"cancelled", "canceled"}:
        return RunStatus.CANCELLED
    return RunStatus.FAILED


@dataclass(frozen=True, slots=True)
class ExecutionArtifactRef:
    storage_uri: str
    relative_path: str
    kind: ArtifactKind


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    run_id: str
    status: RunStatus
    execution_mode: str
    remote_run_dir: str
    artifacts: tuple[ExecutionArtifactRef, ...]
    raw_result: dict[str, Any]
    job_id: str | None = None
    exit_code: int | None = None


@dataclass(frozen=True, slots=True)
class ExecutionStatusSnapshot:
    run_id: str
    status: RunStatus
    remote_run_dir: str
    raw_result: dict[str, Any]
    job_id: str | None = None
    exit_code: int | None = None


@dataclass(slots=True)
class HpcRunnerExecutionAdapter(ExecutionAdapter):
    config_path: str | None = None
    server: HpcRunnerToolServer | None = None
    limiter_registry: LimiterRegistry | None = None

    def __post_init__(self) -> None:
        if self.server is None:
            raise ValueError(
                "HpcRunnerExecutionAdapter requires an injected runner server. "
                "Instantiate mcp_hpc_runner.server.MCPHpcServer in the Host API composition root."
            )

    def submit_execution(self, session_id: str, payload: dict[str, Any]) -> ExecutionOutcome:
        requested_tool_name = str(payload.get("tool_name", "exec.run"))
        tool_name = (
            requested_tool_name
            if requested_tool_name in _SUPPORTED_EXECUTION_TOOLS
            else "exec.run"
        )
        runspec = dict(payload["runspec"])
        metadata = dict(runspec.get("metadata", {}))
        metadata.setdefault("openzyme", {})
        metadata["openzyme"]["session_id"] = session_id
        if tool_name != requested_tool_name:
            metadata["openzyme"]["requested_tool_name"] = requested_tool_name
        runspec["metadata"] = metadata
        result = self._call_tool(tool_name, {"runspec": runspec})
        return self._normalize_result(result, declared_paths=_declared_output_paths(runspec))

    def get_execution_status(
        self,
        *,
        run_id: str,
        remote_run_dir: str,
        job_id: str | None = None,
    ) -> ExecutionStatusSnapshot:
        result = self._call_tool(
            "job.status",
            {"run_id": run_id, "job_id": job_id, "remote_run_dir": remote_run_dir},
        )
        return ExecutionStatusSnapshot(
            run_id=str(result["run_id"]),
            status=map_runner_status_to_run_status(str(result.get("state", "failed"))),
            remote_run_dir=remote_run_dir,
            raw_result=result,
            job_id=None if result.get("job_id") is None else str(result["job_id"]),
            exit_code=None if result.get("exit_code") is None else int(result["exit_code"]),
        )

    def fetch_execution_artifacts(
        self,
        *,
        run_id: str,
        remote_run_dir: str,
        runspec: dict[str, Any],
        job_id: str | None = None,
    ) -> ExecutionOutcome:
        result = self._call_tool(
            "job.fetch_artifacts",
            {
                "run_id": run_id,
                "job_id": job_id,
                "remote_run_dir": remote_run_dir,
                "runspec": runspec,
            },
        )
        return self._normalize_result(result, declared_paths=_declared_output_paths(runspec))

    def cancel_execution(
        self,
        *,
        run_id: str,
        remote_run_dir: str,
        job_id: str | None = None,
    ) -> ExecutionOutcome:
        result = self._call_tool(
            "job.cancel",
            {"run_id": run_id, "job_id": job_id, "remote_run_dir": remote_run_dir},
        )
        return self._normalize_result(result)

    def _call_tool(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.server is None:
            raise RuntimeError("HPC runner server is not initialized")

        def operation() -> dict[str, Any]:
            return self.server.call_tool(tool_name, payload)

        if self.limiter_registry is None:
            return operation()
        return self.limiter_registry.sync_limiter("execution_provider").run(operation)

    def _normalize_result(
        self,
        result: dict[str, Any],
        *,
        declared_paths: set[str] | None = None,
    ) -> ExecutionOutcome:
        selected_mode = str(result.get("selected_mode", result.get("requested_mode", "unknown")))
        artifacts = tuple(
            ExecutionArtifactRef(
                storage_uri=str(local_path),
                relative_path=_relative_output_path(str(remote_path)),
                kind=_artifact_kind_from_uri(str(local_path)),
            )
            for remote_path, local_path in sorted(dict(result.get("artifacts", {})).items())
            if declared_paths is None or _relative_output_path(str(remote_path)) in declared_paths
        )
        return ExecutionOutcome(
            run_id=str(result["run_id"]),
            status=map_runner_status_to_run_status(str(result.get("status", "failed"))),
            execution_mode=selected_mode,
            remote_run_dir=str(result.get("remote_run_dir", "")),
            artifacts=artifacts,
            raw_result=result,
            job_id=None if result.get("job_id") is None else str(result["job_id"]),
            exit_code=None if result.get("exit_code") is None else int(result["exit_code"]),
        )


def _declared_output_paths(runspec: dict[str, Any]) -> set[str] | None:
    paths = {str(item.get("path")) for item in list(runspec.get("expected_outputs") or []) if item.get("path")}
    return paths or None
