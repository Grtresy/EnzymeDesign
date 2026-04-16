from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from .config import RunnerConfig, load_config
from .errors import FailureMapper
from .mode import select_execution_mode
from .models import JobHandle, RunSpec
from .remote import CommandRunner
from .slurm import SlurmRunner
from .ssh_runner import SSHRunner
from .staging import StagingManager
from .store import ArtifactStore


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
        return [
            {
                "name": "exec.run",
                "description": "Execute a RunSpec using ssh|sbatch|auto selection",
                "inputSchema": {
                    "type": "object",
                    "required": ["runspec"],
                    "properties": {
                        "runspec": {"type": "object"},
                        "mode_override": {"type": "string"},
                    },
                },
            },
            {
                "name": "job.submit",
                "description": "Submit a RunSpec as an sbatch job",
                "inputSchema": {
                    "type": "object",
                    "required": ["runspec"],
                    "properties": {"runspec": {"type": "object"}},
                },
            },
            {
                "name": "job.status",
                "description": "Query status for a submitted job",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "job_id": {"type": "string"},
                        "remote_run_dir": {"type": "string"},
                    },
                    "anyOf": [
                        {"required": ["run_id"]},
                        {"required": ["job_id", "remote_run_dir"]},
                    ],
                },
            },
            {
                "name": "job.logs",
                "description": "Fetch remote slurm log tails",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "job_id": {"type": "string"},
                        "remote_run_dir": {"type": "string"},
                        "tail_lines": {"type": "integer", "default": 200},
                    },
                    "anyOf": [
                        {"required": ["run_id"]},
                        {"required": ["job_id", "remote_run_dir"]},
                    ],
                },
            },
            {
                "name": "job.cancel",
                "description": "Cancel a submitted slurm job",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"},
                        "job_id": {"type": "string"},
                        "remote_run_dir": {"type": "string"},
                    },
                    "anyOf": [
                        {"required": ["run_id"]},
                        {"required": ["job_id", "remote_run_dir"]},
                    ],
                },
            },
            {
                "name": "job.fetch_artifacts",
                "description": "Download declared outputs and validate success checks",
                "inputSchema": {
                    "type": "object",
                    "required": ["run_id"],
                    "properties": {
                        "run_id": {"type": "string"},
                        "job_id": {"type": "string"},
                        "remote_run_dir": {"type": "string"},
                        "runspec": {"type": "object"},
                    },
                },
            },
        ]

    def _load_handle(self, args: dict[str, Any]) -> JobHandle:
        run_id = args.get("run_id")
        if run_id:
            try:
                return self.slurm_runner.load_handle(str(run_id))
            except FileNotFoundError:
                pass

        job_id = args.get("job_id")
        remote_run_dir = args.get("remote_run_dir")
        if job_id and remote_run_dir:
            return JobHandle(
                run_id=str(run_id) if run_id else f"adhoc-{job_id}",
                job_id=str(job_id),
                remote_run_dir=str(remote_run_dir),
            )
        raise ValueError(
            "Provide run_id with stored handle, or job_id+remote_run_dir (optionally run_id)"
        )

    def _load_runspec_for_run(
        self, run_id: str, inline: dict[str, Any] | None
    ) -> RunSpec:
        if inline:
            return RunSpec.from_dict(inline)
        return RunSpec.from_dict(self.store.read_json(run_id, "runspec.json"))

    def call_tool(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        args = arguments or {}
        if name == "exec.run":
            spec = RunSpec.from_dict(args["runspec"])
            selected = select_execution_mode(
                spec, self.config, args.get("mode_override")
            )
            if selected == "ssh":
                return self.ssh_runner.exec_run(spec).to_dict()
            return self.slurm_runner.submit(spec).to_dict()

        if name == "job.submit":
            spec = RunSpec.from_dict(args["runspec"])
            spec.execution_mode = "sbatch"
            return self.slurm_runner.submit(spec).to_dict()

        if name == "job.status":
            handle = self._load_handle(args)
            return self.slurm_runner.status(handle).to_dict()

        if name == "job.logs":
            handle = self._load_handle(args)
            return self.slurm_runner.logs(
                handle, tail_lines=int(args.get("tail_lines", 200))
            )

        if name == "job.cancel":
            handle = self._load_handle(args)
            return self.slurm_runner.cancel(handle).to_dict()

        if name == "job.fetch_artifacts":
            run_id = str(args["run_id"])
            handle = self._load_handle(args)
            spec = self._load_runspec_for_run(run_id, args.get("runspec"))
            return self.slurm_runner.fetch_artifacts(spec, handle).to_dict()

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
