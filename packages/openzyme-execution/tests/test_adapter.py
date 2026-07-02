from __future__ import annotations

import asyncio
import threading
import time

import pytest

from openzyme_domain import RunStatus
from openzyme_execution import HpcRunnerExecutionAdapter
from openzyme_execution import map_runner_status_to_run_status
from openzyme_runtime import LimiterRegistry


class FakeRunnerServer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, arguments))
        if name == "job.status":
            return {
                "run_id": str(arguments["run_id"]),
                "job_id": "123",
                "state": "completed",
                "exit_code": 0,
            }
        if name == "job.fetch_artifacts":
            return {
                "run_id": str(arguments["run_id"]),
                "requested_mode": "sbatch",
                "selected_mode": "sbatch",
                "remote_run_dir": str(arguments["remote_run_dir"]),
                "status": "completed",
                "job_id": "123",
                "artifacts": {
                    "/remote/run_001/out/a/result.json": "/tmp/a/result.json",
                },
            }
        return {
            "run_id": "run_001",
            "requested_mode": "auto",
            "selected_mode": "ssh",
            "remote_run_dir": "/remote/run_001",
            "status": "completed",
            "artifacts": {
                "/remote/run_001/out/result.json": "/tmp/result.json",
                "/remote/run_001/logs/stdout.log": "/tmp/stdout.log",
            },
        }


def test_runner_status_mapping_covers_minimum_execution_lifecycle() -> None:
    assert map_runner_status_to_run_status("submitted") is RunStatus.QUEUED
    assert map_runner_status_to_run_status("running") is RunStatus.RUNNING
    assert map_runner_status_to_run_status("completed") is RunStatus.SUCCEEDED
    assert map_runner_status_to_run_status("cancelled") is RunStatus.CANCELLED
    assert map_runner_status_to_run_status("failed") is RunStatus.FAILED


def test_hpc_runner_adapter_requires_injected_runner_server() -> None:
    with pytest.raises(ValueError, match="requires an injected runner server"):
        HpcRunnerExecutionAdapter()


def test_hpc_runner_adapter_calls_real_boundary_shape_and_normalizes_output() -> None:
    server = FakeRunnerServer()
    adapter = HpcRunnerExecutionAdapter(server=server)

    outcome = adapter.submit_execution(
        "sess_001",
        {
            "tool_name": "exec.run",
            "runspec": {
                "name": "fpocket",
                "stage": "execution",
                "command": ["fpocket", "-f", "input.pdb"],
                "execution_mode": "auto",
                "metadata": {"tool_contract": {"adapter_id": "fpocket"}},
            },
        },
    )

    assert server.calls[0][0] == "exec.run"
    sent_runspec = server.calls[0][1]["runspec"]
    assert sent_runspec["metadata"]["openzyme"]["session_id"] == "sess_001"
    assert outcome.run_id == "run_001"
    assert outcome.status is RunStatus.SUCCEEDED
    assert outcome.execution_mode == "ssh"
    assert outcome.artifacts[0].storage_uri == "/tmp/stdout.log"
    assert outcome.artifacts[0].kind.value == "log"


def test_hpc_runner_adapter_normalizes_unknown_tool_names_to_exec_run() -> None:
    server = FakeRunnerServer()
    adapter = HpcRunnerExecutionAdapter(server=server)

    adapter.submit_execution(
        "sess_001",
        {
            "tool_name": "protein_engineering_pipeline",
            "runspec": {
                "name": "pipeline-run",
                "stage": "execution",
                "command": ["echo", "ok"],
                "execution_mode": "auto",
                "metadata": {},
            },
        },
    )

    assert server.calls[0][0] == "exec.run"
    sent_runspec = server.calls[0][1]["runspec"]
    assert sent_runspec["metadata"]["openzyme"]["session_id"] == "sess_001"
    assert (
        sent_runspec["metadata"]["openzyme"]["requested_tool_name"]
        == "protein_engineering_pipeline"
    )


def test_hpc_runner_adapter_queries_status_and_fetches_artifacts() -> None:
    server = FakeRunnerServer()
    adapter = HpcRunnerExecutionAdapter(server=server)

    status = adapter.get_execution_status(
        run_id="run_001",
        remote_run_dir="/remote/run_001",
        job_id="123",
    )
    fetched = adapter.fetch_execution_artifacts(
        run_id="run_001",
        remote_run_dir="/remote/run_001",
        job_id="123",
        runspec={"name": "fpocket"},
    )

    assert status.status is RunStatus.SUCCEEDED
    assert fetched.job_id == "123"
    assert fetched.artifacts[0].relative_path == "a/result.json"
    assert [name for name, _ in server.calls[-2:]] == ["job.status", "job.fetch_artifacts"]


def test_hpc_runner_adapter_treats_pdbqt_as_structure() -> None:
    server = FakeRunnerServer()
    adapter = HpcRunnerExecutionAdapter(server=server)

    outcome = adapter._normalize_result(
        {
            "run_id": "run_001",
            "selected_mode": "ssh",
            "remote_run_dir": "/remote/run_001",
            "status": "completed",
            "artifacts": {
                "/remote/run_001/out/vina_out.pdbqt": "/tmp/vina_out.pdbqt",
            },
        }
    )

    assert outcome.artifacts[0].kind.value == "structure"


def test_hpc_runner_adapter_limits_runner_boundary_calls() -> None:
    class SlowRunnerServer(FakeRunnerServer):
        def __init__(self) -> None:
            super().__init__()
            self.active = 0
            self.observed_max = 0
            self.lock = threading.Lock()

        def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
            with self.lock:
                self.active += 1
                self.observed_max = max(self.observed_max, self.active)
            try:
                time.sleep(0.01)
                return super().call_tool(name, arguments)
            finally:
                with self.lock:
                    self.active -= 1

    server = SlowRunnerServer()
    adapter = HpcRunnerExecutionAdapter(
        server=server,
        limiter_registry=LimiterRegistry({"execution_provider": 1}),
    )

    async def run_calls() -> None:
        await asyncio.gather(
            *(
                asyncio.to_thread(
                    adapter.submit_execution,
                    "ep_001",
                    {
                        "tool_name": "exec.run",
                        "runspec": {
                            "name": f"run-{index}",
                            "stage": "execution",
                            "command": ["echo", "ok"],
                            "execution_mode": "auto",
                            "metadata": {},
                        },
                    },
                )
                for index in range(6)
            )
        )

    asyncio.run(run_calls())

    assert server.observed_max == 1
