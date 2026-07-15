from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import sys
from typing import Any
import uuid

from .config import RunnerConfig, load_config
from .errors import FailureMapper
from .mode import select_execution_mode
from .models import JobHandle, RunSpec
from .remote import CommandRunner
from .slurm import SlurmRunner
from .ssh_runner import SSHRunner
from .staging import StagingManager
from .store import ArtifactStore
from .validation import ensure_valid_runspec


class MCPHpcServer:
    def __init__(self, config_path: str | Path | None) -> None:
        self.config: RunnerConfig = load_config(config_path)
        self.store = ArtifactStore(self.config.artifact_root)
        self.command_runner = CommandRunner()
        self.failure_mapper = FailureMapper()
        self.staging = StagingManager(self.config, self.store, self.command_runner)
        self.ssh_runner = SSHRunner(
            self.config,
            self.store,
            self.staging,
            self.command_runner,
            self.failure_mapper,
        )
        self.slurm_runner = SlurmRunner(
            self.config,
            self.store,
            self.staging,
            self.command_runner,
            self.failure_mapper,
        )

    def _tools(self) -> list[dict[str, Any]]:
        opaque_run_id_schema = {
            "type": "object",
            "required": ["run_id"],
            "additionalProperties": False,
            "properties": {"run_id": {"type": "string"}},
        }
        public_runspec_schema = {
            "type": "object",
            "not": {"required": ["run_id"]},
        }
        return [
            {
                "name": "exec.run",
                "description": "Execute a RunSpec using ssh|sbatch|auto selection",
                "inputSchema": {
                    "type": "object",
                    "required": ["runspec"],
                    "additionalProperties": False,
                    "properties": {
                        "runspec": public_runspec_schema,
                        "mode_override": {
                            "type": "string",
                            "enum": ["ssh", "sbatch", "auto"],
                        },
                    },
                },
            },
            {
                "name": "job.submit",
                "description": "Submit a RunSpec as an sbatch job",
                "inputSchema": {
                    "type": "object",
                    "required": ["runspec"],
                    "additionalProperties": False,
                    "properties": {"runspec": public_runspec_schema},
                },
            },
            {
                "name": "job.status",
                "description": "Query status by opaque server-issued run_id",
                "inputSchema": opaque_run_id_schema,
            },
            {
                "name": "job.logs",
                "description": "Fetch remote slurm log tails",
                "inputSchema": {
                    "type": "object",
                    "required": ["run_id"],
                    "additionalProperties": False,
                    "properties": {
                        "run_id": {"type": "string"},
                        "tail_lines": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": self.config.limits.max_tail_lines,
                            "default": 200,
                        },
                    },
                },
            },
            {
                "name": "job.cancel",
                "description": "Cancel a submitted Slurm job by opaque run_id",
                "inputSchema": opaque_run_id_schema,
            },
            {
                "name": "job.fetch_artifacts",
                "description": (
                    "Download persisted declared outputs by opaque run_id and "
                    "validate success checks"
                ),
                "inputSchema": opaque_run_id_schema,
            },
        ]

    @staticmethod
    def _require_arguments(
        tool_name: str,
        args: dict[str, Any],
        *,
        required: frozenset[str],
        allowed: frozenset[str],
    ) -> None:
        unexpected = sorted(set(args) - allowed)
        if unexpected:
            raise ValueError(
                f"{tool_name} received unexpected arguments: {', '.join(unexpected)}"
            )
        missing = sorted(required - set(args))
        if missing:
            raise ValueError(
                f"{tool_name} is missing required arguments: {', '.join(missing)}"
            )

    def _new_run_id(self) -> str:
        for _ in range(10):
            # The value is an opaque authority handle, not a display id. Keep
            # the full UUID entropy so guessing it is not a realistic access
            # path even inside the trusted Host boundary.
            run_id = uuid.uuid4().hex
            if not self.store.run_root(run_id).exists():
                return run_id
        raise RuntimeError("Unable to allocate a unique runner run_id")

    def _public_runspec(self, raw: Any) -> RunSpec:
        if not isinstance(raw, dict):
            raise ValueError("runspec must be an object")
        if "run_id" in raw:
            raise ValueError("RunSpec.run_id is server-generated and must not be supplied")
        spec = RunSpec.from_dict(raw)
        spec.run_id = self._new_run_id()
        ensure_valid_runspec(
            spec,
            limits=self.config.limits,
            allowed_partitions=self.config.slurm.allowed_partitions,
        )
        return spec

    def _load_handle(self, run_id: str) -> JobHandle:
        try:
            handle = self.slurm_runner.load_handle(run_id)
        except FileNotFoundError as exc:
            raise ValueError(
                f"No persisted job handle exists for run_id {run_id!r}"
            ) from exc
        if handle.run_id != run_id:
            raise ValueError(
                f"Persisted job handle does not belong to run_id {run_id!r}"
            )
        return handle

    def _load_runspec_for_run(self, run_id: str) -> RunSpec:
        try:
            spec = RunSpec.from_dict(self.store.read_json(run_id, "runspec.json"))
        except FileNotFoundError as exc:
            raise ValueError(
                f"No persisted RunSpec exists for run_id {run_id!r}"
            ) from exc
        if spec.run_id != run_id:
            raise ValueError(
                f"Persisted RunSpec does not belong to run_id {run_id!r}"
            )
        return spec

    @staticmethod
    def _relative_artifact_path(path: str) -> str:
        remote_path = PurePosixPath(path)
        parts = remote_path.parts
        if "out" in parts:
            out_index = len(parts) - 1 - list(reversed(parts)).index("out")
            remainder = parts[out_index + 1 :]
            if remainder:
                return str(PurePosixPath(*remainder))
        if not remote_path.is_absolute() and ".." not in parts:
            return remote_path.as_posix()
        return remote_path.name

    @classmethod
    def _project_run_result(cls, result: dict[str, Any]) -> dict[str, Any]:
        selected_mode = str(result.get("selected_mode", "unknown"))
        status = result.get("status")
        return {
            "run_id": str(result["run_id"]),
            "status": "failed" if status is None else str(status),
            "selected_mode": selected_mode,
            "exit_code": result.get("exit_code"),
            "error_code": result.get("error_code"),
            "artifacts": {
                cls._relative_artifact_path(str(path)): str(storage_uri)
                for path, storage_uri in dict(result.get("artifacts") or {}).items()
            },
            # Slurm submit stdout contains the raw scheduler job ID. Async
            # diagnostics are retrieved separately through bounded job.logs.
            "logs": (
                dict(result.get("logs") or {}) if selected_mode == "ssh" else {}
            ),
        }

    @staticmethod
    def _project_job_status(result: dict[str, Any]) -> dict[str, Any]:
        return {
            key: result.get(key)
            for key in (
                "run_id",
                "state",
                "raw_state",
                "exit_code",
                "message",
                "started_at",
                "ended_at",
                "updated_at",
            )
        }

    @staticmethod
    def _project_job_logs(result: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_id": str(result["run_id"]),
            "stdout": dict(result.get("stdout") or {}),
            "stderr": dict(result.get("stderr") or {}),
        }

    def call_tool(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        args = arguments or {}
        if name == "exec.run":
            self._require_arguments(
                name,
                args,
                required=frozenset({"runspec"}),
                allowed=frozenset({"runspec", "mode_override"}),
            )
            spec = self._public_runspec(args["runspec"])
            selected = select_execution_mode(
                spec, self.config, args.get("mode_override")
            )
            if selected == "ssh":
                result = self.ssh_runner.exec_run(spec).to_dict()
            else:
                result = self.slurm_runner.submit(spec).to_dict()
            return self._project_run_result(result)

        if name == "job.submit":
            self._require_arguments(
                name,
                args,
                required=frozenset({"runspec"}),
                allowed=frozenset({"runspec"}),
            )
            spec = self._public_runspec(args["runspec"])
            spec.execution_mode = "sbatch"
            return self._project_run_result(self.slurm_runner.submit(spec).to_dict())

        if name == "job.status":
            self._require_arguments(
                name,
                args,
                required=frozenset({"run_id"}),
                allowed=frozenset({"run_id"}),
            )
            run_id = str(args["run_id"])
            handle = self._load_handle(run_id)
            return self._project_job_status(self.slurm_runner.status(handle).to_dict())

        if name == "job.logs":
            self._require_arguments(
                name,
                args,
                required=frozenset({"run_id"}),
                allowed=frozenset({"run_id", "tail_lines"}),
            )
            run_id = str(args["run_id"])
            handle = self._load_handle(run_id)
            result = self.slurm_runner.logs(
                handle, tail_lines=int(args.get("tail_lines", 200))
            )
            return self._project_job_logs(result)

        if name == "job.cancel":
            self._require_arguments(
                name,
                args,
                required=frozenset({"run_id"}),
                allowed=frozenset({"run_id"}),
            )
            run_id = str(args["run_id"])
            handle = self._load_handle(run_id)
            return self._project_run_result(self.slurm_runner.cancel(handle).to_dict())

        if name == "job.fetch_artifacts":
            self._require_arguments(
                name,
                args,
                required=frozenset({"run_id"}),
                allowed=frozenset({"run_id"}),
            )
            run_id = str(args["run_id"])
            handle = self._load_handle(run_id)
            spec = self._load_runspec_for_run(run_id)
            return self._project_run_result(
                self.slurm_runner.fetch_artifacts(spec, handle).to_dict()
            )

        raise ValueError(f"Unknown tool: {name}")

    def serve_stdio(self) -> None:
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue

            request_id = None
            try:
                request = json.loads(raw)
                request_id = request.get("id") if isinstance(request, dict) else None
                response = self._handle_rpc(request)
            except Exception as exc:  # noqa: BLE001
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32000, "message": str(exc)},
                }

            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

    def _handle_rpc(self, request: dict[str, Any]) -> dict[str, Any]:
        rpc_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "serverInfo": {"name": "mcp-hpc-runner", "version": "0.1.0"},
                    "capabilities": {"tools": {}},
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {"tools": self._tools()},
            }

        if method == "tools/call":
            tool_name = params["name"]
            tool_args = params.get("arguments", {})
            result = self.call_tool(tool_name, tool_args)
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result)}],
                    "isError": False,
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
