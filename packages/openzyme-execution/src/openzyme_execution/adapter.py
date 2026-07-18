from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from typing import Any
from typing import Protocol

from openzyme_domain import ArtifactKind
from openzyme_domain import RunStatus
from openzyme_runtime.limits import LimiterRegistry
from openzyme_runtime.seams import ExecutionAdapter

_SUPPORTED_EXECUTION_TOOLS = frozenset({"exec.run"})
_TOOLCHAIN_RUNTIME_IDENTITY_FIELDS = (
    "schema_id",
    "attestation_scope",
    "execution_mode",
    "tool_id",
    "adapter_id",
    "command_template_id",
    "runner_contract_digest",
    "image_digest",
)
_SAFE_TOOLCHAIN_IDENTIFIER_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$"
)
_SHA256_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


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
    if not path.is_absolute() and ".." not in parts:
        return path.as_posix()
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


def _project_toolchain_runtime_identity(
    value: Any,
    *,
    execution_mode: str,
) -> dict[str, str] | None:
    if execution_mode != "ssh" or not isinstance(value, dict):
        return None
    identity = {
        field: str(value.get(field) or "")
        for field in _TOOLCHAIN_RUNTIME_IDENTITY_FIELDS
    }
    if (
        identity["schema_id"] != "mcp_hpc_toolchain_runtime_identity@1"
        or identity["attestation_scope"]
        != "same_ssh_login_shell_pre_exec"
        or identity["execution_mode"] != "ssh"
        or any(
            _SAFE_TOOLCHAIN_IDENTIFIER_PATTERN.fullmatch(identity[field]) is None
            for field in ("tool_id", "adapter_id", "command_template_id")
        )
        or any(
            _SHA256_DIGEST_PATTERN.fullmatch(identity[field]) is None
            for field in ("runner_contract_digest", "image_digest")
        )
    ):
        return None
    return identity


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
    artifacts: tuple[ExecutionArtifactRef, ...]
    raw_result: dict[str, Any]
    exit_code: int | None = None
    toolchain_runtime_identity: dict[str, str] | None = None
    # Compatibility-only DTO fields. The active HPC adapter never populates raw
    # runner handles; it uses only an opaque URI and leaves job_id unset.
    remote_run_dir: str = ""
    job_id: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionStatusSnapshot:
    run_id: str
    status: RunStatus
    raw_result: dict[str, Any]
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
        if requested_tool_name not in _SUPPORTED_EXECUTION_TOOLS:
            raise ValueError(
                f"unsupported execution tool {requested_tool_name!r}; expected 'exec.run'"
            )
        tool_name = requested_tool_name
        runspec = dict(payload["runspec"])
        if "run_id" in runspec:
            raise ValueError("RunSpec.run_id is server-generated and must not be supplied")
        metadata = dict(runspec.get("metadata", {}))
        metadata.setdefault("openzyme", {})
        metadata["openzyme"]["session_id"] = session_id
        runspec["metadata"] = metadata
        result = self._call_tool(tool_name, {"runspec": runspec})
        return self._normalize_result(result, declared_paths=_declared_output_paths(runspec))

    def get_execution_status(
        self,
        *,
        run_id: str,
    ) -> ExecutionStatusSnapshot:
        result = self._call_tool(
            "job.status",
            {"run_id": run_id},
        )
        return ExecutionStatusSnapshot(
            run_id=str(result["run_id"]),
            status=map_runner_status_to_run_status(str(result.get("state", "failed"))),
            raw_result=result,
            exit_code=None if result.get("exit_code") is None else int(result["exit_code"]),
        )

    def fetch_execution_artifacts(
        self,
        *,
        run_id: str,
    ) -> ExecutionOutcome:
        result = self._call_tool(
            "job.fetch_artifacts",
            {"run_id": run_id},
        )
        return self._normalize_result(result)

    def cancel_execution(
        self,
        *,
        run_id: str,
    ) -> ExecutionOutcome:
        result = self._call_tool(
            "job.cancel",
            {"run_id": run_id},
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
        run_status = map_runner_status_to_run_status(
            str(result.get("status", "failed"))
        )
        toolchain_runtime_identity = _project_toolchain_runtime_identity(
            result.get("toolchain_runtime_identity"),
            execution_mode=selected_mode,
        )
        safe_result = dict(result)
        if toolchain_runtime_identity is None:
            safe_result.pop("toolchain_runtime_identity", None)
        else:
            safe_result["toolchain_runtime_identity"] = dict(
                toolchain_runtime_identity
            )
        if run_status is not RunStatus.SUCCEEDED:
            safe_result["artifacts"] = {}
        artifacts = tuple(
            ExecutionArtifactRef(
                storage_uri=str(local_path),
                relative_path=_relative_output_path(str(remote_path)),
                kind=_artifact_kind_from_uri(str(local_path)),
            )
            for remote_path, local_path in sorted(dict(result.get("artifacts", {})).items())
            if run_status is RunStatus.SUCCEEDED
            and (
                declared_paths is None
                or _relative_output_path(str(remote_path)) in declared_paths
            )
        )
        return ExecutionOutcome(
            run_id=str(result["run_id"]),
            status=run_status,
            execution_mode=selected_mode,
            artifacts=artifacts,
            raw_result=safe_result,
            exit_code=None if result.get("exit_code") is None else int(result["exit_code"]),
            toolchain_runtime_identity=toolchain_runtime_identity,
            remote_run_dir=f"opaque://{result['run_id']}",
        )


def _declared_output_paths(runspec: dict[str, Any]) -> set[str] | None:
    paths = {str(item.get("path")) for item in list(runspec.get("expected_outputs") or []) if item.get("path")}
    return paths or None
