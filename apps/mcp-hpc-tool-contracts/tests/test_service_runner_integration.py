from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp_hpc_tool_contracts.runner_client import RunnerClient
from mcp_hpc_tool_contracts.service import run_adapter


def _params(tmp_path: Path) -> dict[str, Any]:
    structure = tmp_path / "target.pdb"
    structure.write_text("ATOM\n", encoding="utf-8")
    return {"structure_path": str(structure)}


def test_sync_run_surfaces_stable_error_code_and_metadata(tmp_path: Path) -> None:
    def call_impl(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert name == "exec.run"
        assert "runspec" in arguments
        return {"status": "failed", "stderr": "boom"}

    client = RunnerClient(call_impl=call_impl)
    response = run_adapter("fpocket", _params(tmp_path), runner_client=client)
    result = response["result"]

    assert result["status"] == "failed"
    assert result["error_code"] == "RUNNER_ERROR"
    assert result["adapter_metadata"]["tool_contract"]["adapter_id"] == "fpocket"


def test_async_run_fetches_and_normalizes_artifacts(tmp_path: Path) -> None:
    calls: list[str] = []

    def call_impl(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append(name)
        if name == "job.submit":
            return {
                "run_id": "abc123",
                "job_id": "42",
                "remote_run_dir": "/remote/runs/abc123",
                "status": "submitted",
            }
        if name == "job.status":
            return {"run_id": "abc123", "job_id": "42", "state": "completed"}
        if name == "job.fetch_artifacts":
            return {
                "status": "completed",
                "artifacts": {"/remote/runs/abc123/out/target_out": "/tmp/target_out"},
            }
        raise AssertionError(name)

    client = RunnerClient(call_impl=call_impl)
    response = run_adapter(
        "fpocket",
        _params(tmp_path),
        asynchronous=True,
        wait=True,
        runner_client=client,
    )

    assert calls == ["job.submit", "job.status", "job.fetch_artifacts"]
    assert response["fetch"]["normalized_artifacts"] == [
        {
            "remote_path": "/remote/runs/abc123/out/target_out",
            "local_path": "/tmp/target_out",
        }
    ]


def test_async_run_does_not_fetch_artifacts_after_failed_job(tmp_path: Path) -> None:
    calls: list[str] = []

    def call_impl(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append(name)
        if name == "job.submit":
            return {
                "run_id": "abc123",
                "job_id": "42",
                "remote_run_dir": "/remote/runs/abc123",
                "status": "submitted",
            }
        if name == "job.status":
            return {"run_id": "abc123", "job_id": "42", "state": "failed"}
        if name == "job.fetch_artifacts":
            raise AssertionError("fetch should not be called for failed jobs")
        raise AssertionError(name)

    client = RunnerClient(call_impl=call_impl)
    response = run_adapter(
        "fpocket",
        _params(tmp_path),
        asynchronous=True,
        wait=True,
        runner_client=client,
    )

    assert calls == ["job.submit", "job.status"]
    assert response["job_status"]["state"] == "failed"
    assert "fetch" not in response
