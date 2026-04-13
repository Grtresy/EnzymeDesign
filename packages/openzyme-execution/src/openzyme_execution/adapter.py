from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from mcp_hpc_runner.server import MCPHpcServer
from openzyme_domain import ArtifactKind
from openzyme_domain import RunStatus
from openzyme_runtime.seams import ExecutionAdapter

_SUPPORTED_EXECUTION_TOOLS = frozenset({"exec.run"})


def _artifact_kind_from_uri(storage_uri: str) -> ArtifactKind:
    path = storage_uri.lower()
    if path.endswith(".log") or "/logs/" in path:
        return ArtifactKind.LOG
    if path.endswith((".pdb", ".cif", ".mol2", ".sdf")):
        return ArtifactKind.STRUCTURE
    if path.endswith((".md", ".pdf", ".html")):
        return ArtifactKind.REPORT
    return ArtifactKind.RESULT


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


@dataclass(slots=True)
class HpcRunnerExecutionAdapter(ExecutionAdapter):
    config_path: str | None = None
    server: MCPHpcServer | None = None

    def __post_init__(self) -> None:
        if self.server is None:
            self.server = MCPHpcServer(self.config_path)

    def submit_execution(self, episode_id: str, payload: dict[str, Any]) -> ExecutionOutcome:
        requested_tool_name = str(payload.get("tool_name", "exec.run"))
        tool_name = (
            requested_tool_name
            if requested_tool_name in _SUPPORTED_EXECUTION_TOOLS
            else "exec.run"
        )
        runspec = dict(payload["runspec"])
        metadata = dict(runspec.get("metadata", {}))
        metadata.setdefault("openzyme", {})
        metadata["openzyme"]["episode_id"] = episode_id
        if tool_name != requested_tool_name:
            metadata["openzyme"]["requested_tool_name"] = requested_tool_name
        runspec["metadata"] = metadata
        result = self.server.call_tool(tool_name, {"runspec": runspec})
        return self._normalize_result(result)

    def _normalize_result(self, result: dict[str, Any]) -> ExecutionOutcome:
        selected_mode = str(result.get("selected_mode", result.get("requested_mode", "unknown")))
        artifacts = tuple(
            ExecutionArtifactRef(
                storage_uri=str(local_path),
                relative_path=PurePosixPath(remote_path).name,
                kind=_artifact_kind_from_uri(str(local_path)),
            )
            for remote_path, local_path in sorted(dict(result.get("artifacts", {})).items())
        )
        return ExecutionOutcome(
            run_id=str(result["run_id"]),
            status=map_runner_status_to_run_status(str(result.get("status", "failed"))),
            execution_mode=selected_mode,
            remote_run_dir=str(result.get("remote_run_dir", "")),
            artifacts=artifacts,
            raw_result=result,
        )
