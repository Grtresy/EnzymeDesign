from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Protocol

from openzyme_domain import parse_external_job_observation
from openzyme_domain import parse_workspace_job_cancellation_intent
from openzyme_domain import parse_workspace_job_cancellation_receipt
from openzyme_domain import parse_workspace_job_reconciliation
from openzyme_domain import parse_workspace_job_runner_handle


class WorkspaceRevisionRunnerServer(Protocol):
    def call_tool(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(slots=True)
class WorkspaceRevisionRunnerAdapter:
    """Private Host adapter for the revision-bound runner contract.

    It deliberately exposes only revision preparation, dispatch, observation,
    logs, cancellation, and reconciliation.
    """

    server: WorkspaceRevisionRunnerServer

    def prepare_source(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._call("workspace.job.prepare", {"request": dict(request)})

    def dispatch_direct(self, runspec: dict[str, Any]) -> dict[str, Any]:
        if runspec.get("selected_mode") != "ssh":
            raise ValueError("direct runner adapter requires frozen ssh mode")
        return parse_workspace_job_runner_handle(
            self._call("exec.run", {"runspec": dict(runspec)}),
            expected=self._expected_handle(runspec),
        )

    def dispatch_slurm(
        self,
        runspec: dict[str, Any],
        *,
        scheduler_credential: dict[str, Any],
    ) -> dict[str, Any]:
        if runspec.get("selected_mode") != "sbatch":
            raise ValueError("Slurm runner adapter requires frozen sbatch mode")
        return parse_workspace_job_runner_handle(
            self._call(
                "job.submit",
                {
                    "runspec": dict(runspec),
                    "scheduler_credential": dict(scheduler_credential),
                },
            ),
            expected=self._expected_handle(runspec),
        )

    def reconcile(self, runner_run_id: str) -> dict[str, Any]:
        response = self._call("job.reconcile", {"run_id": runner_run_id})
        return parse_workspace_job_reconciliation(
            response,
            expected_handle={"runner_run_id": runner_run_id},
        )

    def observe(
        self,
        runner_run_id: str,
        *,
        observation_index: int,
    ) -> dict[str, Any]:
        return parse_external_job_observation(
            self._call(
                "job.observe",
                {
                    "run_id": runner_run_id,
                    "observation_index": observation_index,
                },
            ),
            expected={"observation_index": observation_index},
        )

    def logs(
        self,
        runner_run_id: str,
        *,
        tail_lines: int = 200,
    ) -> dict[str, Any]:
        return self._call(
            "job.logs",
            {"run_id": runner_run_id, "tail_lines": tail_lines},
        )

    def cancel(
        self,
        runner_run_id: str,
        *,
        cancellation: dict[str, Any],
    ) -> dict[str, Any]:
        cancellation = parse_workspace_job_cancellation_intent(cancellation)
        return parse_workspace_job_cancellation_receipt(
            self._call(
                "job.cancel",
                {"run_id": runner_run_id, "cancellation": cancellation},
            ),
            expected={
                "cancellation_id": cancellation["cancellation_id"],
                "handle_id": cancellation["handle_id"],
            },
        )

    @staticmethod
    def _expected_handle(runspec: dict[str, Any]) -> dict[str, object]:
        required = (
            "execution_id",
            "operation_id",
            "dispatch_id",
            "runner_run_id",
            "target_profile_digest",
            "executor_hpc_workspace_id",
            "executor_hpc_workspace_generation",
            "source_commit",
            "source_manifest_digest",
            "selected_mode",
        )
        missing = [field for field in required if field not in runspec]
        if missing:
            raise ValueError(f"runner adapter RunSpec lacks fields: {missing!r}")
        return {
            "execution_id": runspec["execution_id"],
            "operation_id": runspec["operation_id"],
            "dispatch_id": runspec["dispatch_id"],
            "runner_run_id": runspec["runner_run_id"],
            "target_profile_digest": runspec["target_profile_digest"],
            "workspace_id": runspec["executor_hpc_workspace_id"],
            "remote_workspace_generation": runspec[
                "executor_hpc_workspace_generation"
            ],
            "source_commit": runspec["source_commit"],
            "source_manifest_digest": runspec["source_manifest_digest"],
            "backend": "slurm" if runspec["selected_mode"] == "sbatch" else "direct",
        }

    def _call(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.server.call_tool(tool_name, payload)
        if not isinstance(result, dict):
            raise ValueError("workspace revision runner result must be an object")
        return result


__all__ = ["WorkspaceRevisionRunnerAdapter", "WorkspaceRevisionRunnerServer"]
