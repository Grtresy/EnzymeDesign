from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Protocol


class WorkspaceRevisionRunnerServer(Protocol):
    def call_tool(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(slots=True)
class WorkspaceRevisionRunnerAdapter:
    """Private Host adapter for the revision-bound runner contract.

    It deliberately exposes no artifact resolution, staging, expected-output,
    fetch, or replacement-submit method.
    """

    server: WorkspaceRevisionRunnerServer

    def prepare_source(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._call("workspace.job.prepare", {"request": dict(request)})

    def dispatch_direct(self, runspec: dict[str, Any]) -> dict[str, Any]:
        if runspec.get("selected_mode") != "ssh":
            raise ValueError("direct runner adapter requires frozen ssh mode")
        return self._call("exec.run", {"runspec": dict(runspec)})

    def dispatch_slurm(
        self,
        runspec: dict[str, Any],
        *,
        scheduler_credential: dict[str, Any],
    ) -> dict[str, Any]:
        if runspec.get("selected_mode") != "sbatch":
            raise ValueError("Slurm runner adapter requires frozen sbatch mode")
        return self._call(
            "job.submit",
            {
                "runspec": dict(runspec),
                "scheduler_credential": dict(scheduler_credential),
            },
        )

    def reconcile(self, runner_run_id: str) -> dict[str, Any]:
        return self._call("job.reconcile", {"run_id": runner_run_id})

    def observe(
        self,
        runner_run_id: str,
        *,
        observation_index: int,
    ) -> dict[str, Any]:
        return self._call(
            "job.observe",
            {
                "run_id": runner_run_id,
                "observation_index": observation_index,
            },
        )

    def cancel(
        self,
        runner_run_id: str,
        *,
        cancellation: dict[str, Any],
    ) -> dict[str, Any]:
        return self._call(
            "job.cancel",
            {"run_id": runner_run_id, "cancellation": dict(cancellation)},
        )

    def _call(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.server.call_tool(tool_name, payload)
        if not isinstance(result, dict):
            raise ValueError("workspace revision runner result must be an object")
        return result


__all__ = ["WorkspaceRevisionRunnerAdapter", "WorkspaceRevisionRunnerServer"]
