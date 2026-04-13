from openzyme_domain import RunStatus
from openzyme_execution import HpcRunnerExecutionAdapter
from openzyme_execution import map_runner_status_to_run_status


class FakeRunnerServer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, arguments))
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


def test_runner_status_mapping_covers_minimum_phase_b_lifecycle() -> None:
    assert map_runner_status_to_run_status("submitted") is RunStatus.QUEUED
    assert map_runner_status_to_run_status("running") is RunStatus.RUNNING
    assert map_runner_status_to_run_status("completed") is RunStatus.SUCCEEDED
    assert map_runner_status_to_run_status("cancelled") is RunStatus.CANCELLED
    assert map_runner_status_to_run_status("failed") is RunStatus.FAILED


def test_hpc_runner_adapter_calls_real_boundary_shape_and_normalizes_output() -> None:
    server = FakeRunnerServer()
    adapter = HpcRunnerExecutionAdapter(server=server)

    outcome = adapter.submit_execution(
        "ep_001",
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
    assert sent_runspec["metadata"]["openzyme"]["episode_id"] == "ep_001"
    assert outcome.run_id == "run_001"
    assert outcome.status is RunStatus.SUCCEEDED
    assert outcome.execution_mode == "ssh"
    assert outcome.artifacts[0].storage_uri == "/tmp/stdout.log"
    assert outcome.artifacts[0].kind.value == "log"


def test_hpc_runner_adapter_normalizes_unknown_tool_names_to_exec_run() -> None:
    server = FakeRunnerServer()
    adapter = HpcRunnerExecutionAdapter(server=server)

    adapter.submit_execution(
        "ep_001",
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
    assert sent_runspec["metadata"]["openzyme"]["episode_id"] == "ep_001"
    assert (
        sent_runspec["metadata"]["openzyme"]["requested_tool_name"]
        == "protein_engineering_pipeline"
    )
