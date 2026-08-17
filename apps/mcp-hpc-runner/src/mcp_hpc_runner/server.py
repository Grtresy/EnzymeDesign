from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from .config import RunnerConfig, load_config
from .models import ExecutorWorkspaceRunSpec
from .models import WORKSPACE_RUNSPEC_SCHEMA_VERSION
from .executor_workspaces import ExecutorWorkspaceCleanupRequest
from .executor_workspaces import ExecutorWorkspaceProvisionRequest
from .executor_workspaces import ExecutorWorkspaceProvisioningService
from .remote import CommandRunner
from .transport import SshTransportManager
from .workspace_revision_jobs import SchedulerOccurrenceCredential
from .workspace_revision_jobs import WorkspaceRevisionJobService
from .workspace_revision_jobs import WorkspaceRevisionSourcePrepareRequest


class MCPHpcServer:
    def __init__(self, config_path: str | Path | None) -> None:
        self.config: RunnerConfig = load_config(config_path)
        self.command_runner = CommandRunner()
        self.transport_manager = SshTransportManager(
            self.config,
            self.command_runner,
        )
        self.executor_workspace_provisioning = ExecutorWorkspaceProvisioningService(
            self.config,
            self.transport_manager,
        )
        self.workspace_revision_jobs = WorkspaceRevisionJobService(
            self.config,
            self.transport_manager,
            self.executor_workspace_provisioning,
        )

    def close(self) -> dict[str, object]:
        return self.transport_manager.shutdown()

    def _tools(self) -> list[dict[str, Any]]:
        public_runspec_schema = {
            "type": "object",
            "required": [
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
            ],
            "additionalProperties": False,
            "properties": {
                "schema_version": {
                    "type": "string",
                    "const": WORKSPACE_RUNSPEC_SCHEMA_VERSION,
                },
                "execution_id": {"type": "string"},
                "operation_id": {"type": "string"},
                "dispatch_id": {"type": "string"},
                "runner_run_id": {"type": "string"},
                "executor_hpc_workspace_id": {"type": "string"},
                "executor_hpc_workspace_generation": {
                    "type": "integer",
                    "minimum": 1,
                },
                "repository_binding_id": {"type": "string"},
                "repository_binding_version": {
                    "type": "integer",
                    "minimum": 1,
                },
                "repository_binding_digest": {"type": "string"},
                "repository_policy_digest": {"type": "string"},
                "source_manifest_id": {"type": "string"},
                "source_request_id": {"type": "string"},
                "source_commit": {"type": "string"},
                "source_tree": {"type": "string"},
                "lfs_closure_manifest_digest": {"type": "string"},
                "source_manifest": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": [
                            "schema_version",
                            "path",
                            "object_id",
                            "mode",
                            "size_bytes",
                            "content_digest",
                            "lfs_oid",
                        ],
                        "additionalProperties": False,
                        "properties": {
                            "schema_version": {
                                "type": "string",
                                "const": "compute_source_manifest_entry@1",
                            },
                            "path": {"type": "string"},
                            "object_id": {"type": "string"},
                            "mode": {"type": "string"},
                            "size_bytes": {"type": "integer", "minimum": 0},
                            "content_digest": {"type": "string"},
                            "lfs_oid": {"type": ["string", "null"]},
                        },
                    },
                },
                "source_manifest_digest": {"type": "string"},
                "source_owner_identity_digest": {"type": "string"},
                "source_manifest_created_at": {"type": "string"},
                "target_profile_digest": {"type": "string"},
                "runner_policy_digest": {"type": "string"},
                "toolchain_digest": {"type": "string"},
                "cwd": {"type": "string"},
                "command": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string"},
                },
                "command_digest": {"type": "string"},
                "environment_policy_digest": {"type": "string"},
                "resource_digest": {"type": "string"},
                "selected_mode": {
                    "type": "string",
                    "enum": ["ssh", "sbatch"],
                },
                "scheduler_marker": {"type": "string"},
                "payload_digest": {"type": "string"},
                "absolute_deadline": {"type": "string"},
                "resources": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "cpus": {"type": "integer", "minimum": 1},
                        "mem_mb": {"type": "integer", "minimum": 1},
                        "gpus": {"type": "integer", "minimum": 0},
                        "time_minutes": {"type": "integer", "minimum": 1},
                        "partition": {"type": ["string", "null"]},
                    },
                },
            },
        }
        provision_request_schema = {
            "type": "object",
            "required": ["request"],
            "additionalProperties": False,
            "properties": {
                "request": {
                    "type": "object",
                    "required": [
                        "schema_version",
                        "intent_id",
                        "intent_digest",
                        "workspace_id",
                        "remote_workspace_generation",
                        "target_profile_digest",
                        "repository_endpoint",
                        "repository_remote_digest",
                        "base_commit",
                        "owner_identity_digest",
                        "idempotency_key",
                        "absolute_deadline",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "schema_version": {
                            "type": "string",
                            "const": "executor_workspace_provision_request@1",
                        },
                        "intent_id": {"type": "string"},
                        "intent_digest": {"type": "string"},
                        "workspace_id": {"type": "string"},
                        "remote_workspace_generation": {
                            "type": "integer",
                            "minimum": 1,
                        },
                        "target_profile_digest": {"type": "string"},
                        "repository_endpoint": {"type": "string"},
                        "repository_remote_digest": {"type": "string"},
                        "base_commit": {"type": "string"},
                        "owner_identity_digest": {"type": "string"},
                        "idempotency_key": {"type": "string"},
                        "absolute_deadline": {"type": "string"},
                    },
                }
            },
        }
        cleanup_request_schema = {
            "type": "object",
            "required": ["request"],
            "additionalProperties": False,
            "properties": {
                "request": {
                    "type": "object",
                    "required": [
                        "schema_version",
                        "provision_request",
                        "cleanup_intent_id",
                        "cleanup_intent_digest",
                        "workspace_state_version",
                        "settlement_proof_digest",
                        "idempotency_key",
                        "unsettled_effect_count",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "schema_version": {
                            "type": "string",
                            "const": "executor_workspace_cleanup_request@1",
                        },
                        "provision_request": provision_request_schema["properties"][
                            "request"
                        ],
                        "cleanup_intent_id": {"type": "string"},
                        "cleanup_intent_digest": {"type": "string"},
                        "workspace_state_version": {
                            "type": "integer",
                            "minimum": 1,
                        },
                        "settlement_proof_digest": {"type": "string"},
                        "idempotency_key": {"type": "string"},
                        "unsettled_effect_count": {"type": "integer", "const": 0},
                    },
                }
            },
        }
        return [
            {
                "name": "workspace.provision",
                "description": (
                    "Compare-and-create one exact executor login workspace"
                ),
                "inputSchema": provision_request_schema,
            },
            {
                "name": "workspace.inspect",
                "description": (
                    "Inspect the exact provision intent without replacement creation"
                ),
                "inputSchema": provision_request_schema,
            },
            {
                "name": "workspace.verify",
                "description": "Verify exact remote root and independent clone identity",
                "inputSchema": provision_request_schema,
            },
            {
                "name": "workspace.cleanup",
                "description": "Delete only the exact settled executor workspace handle",
                "inputSchema": cleanup_request_schema,
            },
            {
                "name": "workspace.cleanup.inspect",
                "description": "Reconcile only the exact cleanup intent and handle",
                "inputSchema": cleanup_request_schema,
            },
            {
                "name": "workspace.job.prepare",
                "description": (
                    "Validate an exact login revision and atomically prepare its Gitless tree"
                ),
                "inputSchema": {
                    "type": "object",
                    "required": ["request"],
                    "additionalProperties": False,
                    "properties": {"request": {"type": "object"}},
                },
            },
            {
                "name": "exec.run",
                "description": (
                    "Dispatch one qualified direct workspace-revision occurrence"
                ),
                "inputSchema": {
                    "type": "object",
                    "required": ["runspec"],
                    "additionalProperties": False,
                    "properties": {"runspec": public_runspec_schema},
                },
            },
            {
                "name": "job.submit",
                "description": (
                    "Dispatch one protected Slurm occurrence with a one-use credential"
                ),
                "inputSchema": {
                    "type": "object",
                    "required": ["runspec", "scheduler_credential"],
                    "additionalProperties": False,
                    "properties": {
                        "runspec": public_runspec_schema,
                        "scheduler_credential": {"type": "object"},
                    },
                },
            },
            {
                "name": "job.reconcile",
                "description": "Reconcile only the frozen dispatch ledger occurrence",
                "inputSchema": {
                    "type": "object",
                    "required": ["run_id"],
                    "additionalProperties": False,
                    "properties": {"run_id": {"type": "string"}},
                },
            },
            {
                "name": "job.observe",
                "description": "Append one bounded observation for the exact handle",
                "inputSchema": {
                    "type": "object",
                    "required": ["run_id", "observation_index"],
                    "additionalProperties": False,
                    "properties": {
                        "run_id": {"type": "string"},
                        "observation_index": {
                            "type": "integer",
                            "minimum": 1,
                        },
                    },
                },
            },
            {
                "name": "job.logs",
                "description": "Read bounded diagnostics from the latest durable observation",
                "inputSchema": {
                    "type": "object",
                    "required": ["run_id"],
                    "additionalProperties": False,
                    "properties": {
                        "run_id": {"type": "string"},
                        "tail_lines": {"type": "integer", "minimum": 1},
                    },
                },
            },
            {
                "name": "job.cancel",
                "description": (
                    "Request cancellation of the exact handle without claiming settlement"
                ),
                "inputSchema": {
                    "type": "object",
                    "required": ["run_id", "cancellation"],
                    "additionalProperties": False,
                    "properties": {
                        "run_id": {"type": "string"},
                        "cancellation": {
                            "type": "object",
                            "required": [
                                "schema_version",
                                "cancellation_id",
                                "execution_id",
                                "handle_id",
                                "execution_state_version",
                                "execution_fencing_token",
                                "idempotency_key",
                                "reason_digest",
                                "created_at",
                            ],
                            "additionalProperties": False,
                            "properties": {
                                "schema_version": {
                                    "type": "string",
                                    "const": "workspace_job_cancellation_intent@1",
                                },
                                "cancellation_id": {"type": "string"},
                                "execution_id": {"type": "string"},
                                "handle_id": {"type": "string"},
                                "execution_state_version": {
                                    "type": "integer",
                                    "minimum": 1,
                                },
                                "execution_fencing_token": {
                                    "type": "integer",
                                    "minimum": 0,
                                },
                                "idempotency_key": {"type": "string"},
                                "reason_digest": {"type": "string"},
                                "created_at": {"type": "string"},
                            },
                        },
                    },
                },
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

    def call_tool(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        args = arguments or {}
        if name in {"workspace.provision", "workspace.inspect", "workspace.verify"}:
            self._require_arguments(
                name,
                args,
                required=frozenset({"request"}),
                allowed=frozenset({"request"}),
            )
            request = ExecutorWorkspaceProvisionRequest.from_dict(args["request"])
            if name == "workspace.provision":
                return self.executor_workspace_provisioning.provision(request)
            if name == "workspace.verify":
                return self.executor_workspace_provisioning.verify(request)
            return {
                "schema_version": "executor_workspace_inspection@1",
                "workspace": self.executor_workspace_provisioning.inspect(request),
                "replacement_created": False,
            }
        if name in {"workspace.cleanup", "workspace.cleanup.inspect"}:
            self._require_arguments(
                name,
                args,
                required=frozenset({"request"}),
                allowed=frozenset({"request"}),
            )
            request = ExecutorWorkspaceCleanupRequest.from_dict(args["request"])
            if name == "workspace.cleanup":
                return self.executor_workspace_provisioning.cleanup(request)
            return {
                "schema_version": "executor_workspace_cleanup_inspection@1",
                "cleanup": self.executor_workspace_provisioning.inspect_cleanup(
                    request
                ),
                "replacement_targeted": False,
            }
        if name == "workspace.job.prepare":
            self._require_arguments(
                name,
                args,
                required=frozenset({"request"}),
                allowed=frozenset({"request"}),
            )
            request = WorkspaceRevisionSourcePrepareRequest.from_dict(args["request"])
            return self.workspace_revision_jobs.prepare_source(request)

        if name == "exec.run":
            self._require_arguments(
                name,
                args,
                required=frozenset({"runspec"}),
                allowed=frozenset({"runspec"}),
            )
            spec = ExecutorWorkspaceRunSpec.from_dict(args["runspec"])
            if spec.selected_mode != "ssh":
                raise ValueError("exec.run requires the frozen ssh mode")
            return self.workspace_revision_jobs.dispatch(spec)

        if name == "job.submit":
            self._require_arguments(
                name,
                args,
                required=frozenset({"runspec", "scheduler_credential"}),
                allowed=frozenset({"runspec", "scheduler_credential"}),
            )
            spec = ExecutorWorkspaceRunSpec.from_dict(args["runspec"])
            if spec.selected_mode != "sbatch":
                raise ValueError("job.submit requires the frozen sbatch mode")
            credential = SchedulerOccurrenceCredential.from_dict(
                args["scheduler_credential"]
            )
            return self.workspace_revision_jobs.dispatch(
                spec,
                scheduler_credential=credential,
            )

        if name == "job.reconcile":
            self._require_arguments(
                name,
                args,
                required=frozenset({"run_id"}),
                allowed=frozenset({"run_id"}),
            )
            return self.workspace_revision_jobs.reconcile_run(str(args["run_id"]))

        if name == "job.observe":
            self._require_arguments(
                name,
                args,
                required=frozenset({"run_id", "observation_index"}),
                allowed=frozenset({"run_id", "observation_index"}),
            )
            observation_index = args["observation_index"]
            if not isinstance(observation_index, int) or isinstance(
                observation_index,
                bool,
            ):
                raise ValueError("observation_index must be an integer")
            return self.workspace_revision_jobs.observe_run(
                str(args["run_id"]),
                index=observation_index,
            )

        if name == "job.logs":
            self._require_arguments(
                name,
                args,
                required=frozenset({"run_id"}),
                allowed=frozenset({"run_id", "tail_lines"}),
            )
            tail_lines = args.get("tail_lines", 200)
            if not isinstance(tail_lines, int) or isinstance(tail_lines, bool):
                raise ValueError("tail_lines must be an integer")
            return self.workspace_revision_jobs.logs_run(
                str(args["run_id"]),
                tail_lines=tail_lines,
            )

        if name == "job.cancel":
            self._require_arguments(
                name,
                args,
                required=frozenset({"run_id", "cancellation"}),
                allowed=frozenset({"run_id", "cancellation"}),
            )
            cancellation = args["cancellation"]
            if not isinstance(cancellation, dict):
                raise ValueError("cancellation must be an object")
            return self.workspace_revision_jobs.cancel_run(
                str(args["run_id"]),
                cancellation=cancellation,
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
            except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
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
