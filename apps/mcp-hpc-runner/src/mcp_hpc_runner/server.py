from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any
import uuid

from .config import RunnerConfig, load_config
from .contract_manifest import ToolContract, load_contract_manifest
from .errors import FailureMapper
from .mode import select_execution_mode
from .models import JobHandle, RunSpec
from .remote import CommandRunner
from .slurm import SlurmRunner
from .ssh_runner import SSHRunner
from .staging import StagingManager
from .store import ArtifactStore
from .validation import ensure_valid_runspec


_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_PUBLIC_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PUBLIC_RUN_STATUSES = {
    "submitted",
    "queued",
    "pending",
    "running",
    "in_progress",
    "completed",
    "succeeded",
    "success",
    "cancelled",
    "canceled",
    "failed",
}


class MCPHpcServer:
    def __init__(self, config_path: str | Path | None) -> None:
        self.config: RunnerConfig = load_config(config_path)
        self.store = ArtifactStore(self.config.artifact_root)
        self.command_runner = CommandRunner()
        self.failure_mapper = FailureMapper()
        self._tool_contracts_by_adapter = {
            contract.adapter_id: contract for contract in load_contract_manifest()
        }
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
        self._bind_runner_toolchain_contract(spec)
        ensure_valid_runspec(
            spec,
            limits=self.config.limits,
            allowed_partitions=self.config.slurm.allowed_partitions,
        )
        return spec

    def _bind_runner_toolchain_contract(self, spec: RunSpec) -> None:
        metadata = dict(spec.metadata or {})
        caller_owned_runtime_fields = sorted(
            {"toolchain_runtime_request", "toolchain_runtime_identity"} & set(metadata)
        )
        if caller_owned_runtime_fields:
            raise ValueError(
                "runner-owned toolchain runtime fields cannot be supplied: "
                + ", ".join(caller_owned_runtime_fields)
            )
        caller_contract = dict(metadata.get("tool_contract") or {})
        adapter_id = str(caller_contract.get("adapter_id") or "")
        contract = self._tool_contracts_by_adapter.get(adapter_id)
        if (
            contract is None
            or contract.entrypoint.get("kind") != "sif"
            or contract.command_template_id is None
        ):
            return
        self._validate_caller_tool_contract(caller_contract, contract)
        contract_digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    contract.raw,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
        entrypoint = contract.entrypoint
        caller_contract.update(
            {
                "preflight_hints": {
                    "entrypoint": {
                        "kind": "sif",
                        "path": str(entrypoint["path"]),
                    },
                    "bind_paths": list(entrypoint.get("bind_paths") or []),
                },
                "runner_contract_digest": contract_digest,
            }
        )
        metadata["tool_contract"] = caller_contract
        metadata["toolchain_runtime_request"] = {
            "schema_id": "mcp_hpc_toolchain_runtime_request@1",
            "tool_id": contract.tool_id,
            "adapter_id": contract.adapter_id,
            "command_template_id": contract.command_template_id,
            "entrypoint_kind": "sif",
            "sif_locator": str(entrypoint["path"]),
            "runner_contract_digest": contract_digest,
        }
        spec.metadata = metadata

    @staticmethod
    def _validate_caller_tool_contract(
        caller: dict[str, Any],
        contract: ToolContract,
    ) -> None:
        if (
            caller.get("tool_id") != contract.tool_id
            or caller.get("adapter_id") != contract.adapter_id
            or not contract.command_template_id
            or caller.get("command_template_id") != contract.command_template_id
        ):
            raise ValueError(
                "Host tool contract does not match the runner-owned SIF contract"
            )

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

    def _project_run_result(
        self,
        result: dict[str, Any],
        *,
        authoritative_mode: str,
        runtime_request: dict[str, object] | None,
    ) -> dict[str, Any]:
        reported_mode = str(result.get("selected_mode", "unknown"))
        if reported_mode != authoritative_mode:
            raise ValueError(
                "runner result selected_mode does not match the authoritative dispatch mode"
            )
        selected_mode = authoritative_mode
        raw_status = result.get("status")
        normalized_status = str(raw_status or "").strip().lower()
        status_valid = normalized_status in _PUBLIC_RUN_STATUSES
        status = normalized_status if status_valid else "failed"
        metadata = dict(result.get("metadata") or {})
        stage = metadata.get("stage")
        if selected_mode != "ssh" or stage != "remote_execution":
            stage = None
        projected = {
            "run_id": str(result["run_id"]),
            "status": status,
            "selected_mode": selected_mode,
            "exit_code": result.get("exit_code"),
            "error_code": result.get("error_code"),
            "stage": stage,
            "artifacts": {
                self._relative_artifact_path(str(path)): str(storage_uri)
                for path, storage_uri in dict(result.get("artifacts") or {}).items()
            },
            # Raw runner logs remain Host-private. Async diagnostics are
            # retrieved separately through bounded operator-facing job.logs.
            "logs": {},
        }
        if not status_valid and not projected["error_code"]:
            projected["error_code"] = "RUNNER_STATUS_INVALID"
        execution_identity = self._project_toolchain_runtime_identity(
            result,
            selected_mode=selected_mode,
            runtime_request=runtime_request,
        )
        if execution_identity is not None:
            projected["toolchain_runtime_identity"] = execution_identity
        elif (
            selected_mode == "ssh"
            and runtime_request
            and projected["status"] in {"completed", "succeeded", "success"}
        ):
            projected["status"] = "failed"
            projected["error_code"] = "TOOLCHAIN_IDENTITY_MISSING"
        if projected["status"] not in {"completed", "succeeded", "success"}:
            projected["artifacts"] = {}
        return projected

    @staticmethod
    def _project_toolchain_runtime_identity(
        result: dict[str, Any],
        *,
        selected_mode: str,
        runtime_request: dict[str, object] | None,
    ) -> dict[str, str] | None:
        # Only the synchronous SSH runner can currently attest the image in the
        # same login shell that executes the payload. Never reinterpret Slurm
        # submit/preflight metadata as an execution identity.
        if selected_mode != "ssh" or not runtime_request:
            return None
        raw_identity = dict(
            dict(result.get("metadata") or {}).get("toolchain_runtime_identity") or {}
        )
        if not raw_identity:
            return None
        projected = {
            "schema_id": str(raw_identity.get("schema_id") or ""),
            "attestation_scope": str(raw_identity.get("attestation_scope") or ""),
            "execution_mode": str(raw_identity.get("execution_mode") or ""),
            "tool_id": str(raw_identity.get("tool_id") or ""),
            "adapter_id": str(raw_identity.get("adapter_id") or ""),
            "command_template_id": str(raw_identity.get("command_template_id") or ""),
            "runner_contract_digest": str(
                raw_identity.get("runner_contract_digest") or ""
            ),
            "image_digest": str(raw_identity.get("image_digest") or ""),
        }
        if (
            projected["schema_id"] != "mcp_hpc_toolchain_runtime_identity@1"
            or projected["attestation_scope"] != "same_ssh_login_shell_pre_exec"
            or projected["execution_mode"] != "ssh"
            or projected["tool_id"] != runtime_request.get("tool_id")
            or projected["adapter_id"] != runtime_request.get("adapter_id")
            or projected["command_template_id"]
            != runtime_request.get("command_template_id")
            or projected["runner_contract_digest"]
            != runtime_request.get("runner_contract_digest")
            or any(
                _PUBLIC_ID_PATTERN.fullmatch(projected[key]) is None
                for key in ("tool_id", "adapter_id", "command_template_id")
            )
            or _DIGEST_PATTERN.fullmatch(projected["runner_contract_digest"]) is None
            or _DIGEST_PATTERN.fullmatch(projected["image_digest"]) is None
        ):
            return None
        # Rebuild a closed public object instead of forwarding runner metadata;
        # paths and future private fields therefore cannot cross this boundary.
        return projected

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
            return self._project_run_result(
                result,
                authoritative_mode=selected,
                runtime_request=dict(
                    spec.metadata.get("toolchain_runtime_request") or {}
                )
                or None,
            )

        if name == "job.submit":
            self._require_arguments(
                name,
                args,
                required=frozenset({"runspec"}),
                allowed=frozenset({"runspec"}),
            )
            spec = self._public_runspec(args["runspec"])
            spec.execution_mode = "sbatch"
            return self._project_run_result(
                self.slurm_runner.submit(spec).to_dict(),
                authoritative_mode="sbatch",
                runtime_request=None,
            )

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
            return self._project_run_result(
                self.slurm_runner.cancel(handle).to_dict(),
                authoritative_mode="sbatch",
                runtime_request=None,
            )

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
                self.slurm_runner.fetch_artifacts(spec, handle).to_dict(),
                authoritative_mode="sbatch",
                runtime_request=None,
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
