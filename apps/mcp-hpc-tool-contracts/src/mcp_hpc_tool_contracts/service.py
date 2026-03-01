from __future__ import annotations

import time
from typing import Any

from .models import CompiledAdapterRun
from .registry import compile_adapter as _compile_adapter
from .runner_client import RunnerClient


def compile_adapter(adapter_id: str, params: dict[str, Any]) -> CompiledAdapterRun:
    return _compile_adapter(adapter_id, params)


def _normalize_artifacts(payload: dict[str, Any]) -> list[dict[str, str]]:
    artifacts = payload.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        return []
    normalized: list[dict[str, str]] = []
    for remote_path, local_path in artifacts.items():
        normalized.append(
            {"remote_path": str(remote_path), "local_path": str(local_path)}
        )
    return normalized


def _decorate_result(
    result: dict[str, Any], compiled: CompiledAdapterRun
) -> dict[str, Any]:
    status = str(result.get("status", "unknown"))
    error_code = result.get("error_code")
    if status == "failed" and not error_code:
        error_code = "RUNNER_ERROR"
    return {
        **result,
        "status": status,
        "error_code": error_code,
        "normalized_artifacts": _normalize_artifacts(result),
        "adapter_metadata": compiled.metadata,
    }


def run_adapter(
    adapter_id: str,
    params: dict[str, Any],
    *,
    asynchronous: bool = False,
    wait: bool = False,
    poll_seconds: int = 5,
    max_polls: int = 120,
    runner_client: RunnerClient | None = None,
) -> dict[str, Any]:
    compiled = compile_adapter(adapter_id, params)
    client = runner_client or RunnerClient()

    if not asynchronous:
        sync_result = client.call_tool("exec.run", {"runspec": compiled.runspec})
        decorated = _decorate_result(sync_result, compiled)
        return {
            "mode": "sync",
            "compiled": compiled.to_dict(),
            "result": decorated,
        }

    submission = client.call_tool("job.submit", {"runspec": compiled.runspec})
    response: dict[str, Any] = {
        "mode": "async",
        "compiled": compiled.to_dict(),
        "submission": submission,
    }
    if not wait:
        return response

    run_id = str(submission["run_id"])
    status_payload: dict[str, Any] | None = None
    for _ in range(max_polls):
        status_payload = client.call_tool("job.status", {"run_id": run_id})
        state = str(status_payload.get("state", ""))
        if state in {"completed", "failed", "cancelled"}:
            break
        time.sleep(max(1, poll_seconds))
    else:
        raise RuntimeError(
            f"Timed out waiting for async run_id={run_id} after {max_polls} polls"
        )

    response["job_status"] = status_payload
    state = str((status_payload or {}).get("state", ""))
    if state != "completed":
        return response

    fetch_payload = client.call_tool(
        "job.fetch_artifacts",
        {
            "run_id": run_id,
            "job_id": submission.get("job_id"),
            "remote_run_dir": submission.get("remote_run_dir"),
            "runspec": compiled.runspec,
        },
    )
    response["fetch"] = _decorate_result(fetch_payload, compiled)
    return response
