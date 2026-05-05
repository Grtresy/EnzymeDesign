from __future__ import annotations

from typing import Any

from .client import call
from .client import PipelineSdkError


def fpocket(*, structure_artifact_id: str, params: dict[str, Any] | None = None, expected_outputs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return _checked_hpc_result(
        "hpc.fpocket",
        call("hpc.fpocket", {"structure_artifact_id": structure_artifact_id, "params": dict(params or {}), "expected_outputs": list(expected_outputs or [])}),
    )


def vina(*, receptor_artifact_id: str, ligand_artifact_id: str, params: dict[str, Any] | None = None, expected_outputs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return _checked_hpc_result(
        "hpc.vina",
        call(
            "hpc.vina",
            {
                "receptor_artifact_id": receptor_artifact_id,
                "ligand_artifact_id": ligand_artifact_id,
                "params": dict(params or {}),
                "expected_outputs": list(expected_outputs or []),
            },
        ),
    )


def _checked_hpc_result(method: str, result: Any) -> dict[str, Any]:
    payload = dict(result or {})
    status = str(payload.get("status") or "").lower()
    if status and status not in {"succeeded", "success", "completed"}:
        run_id = payload.get("run_id") or payload.get("runner_run_id") or "unknown"
        raise PipelineSdkError(f"{method} failed with status {status} for run {run_id}")
    return payload


__all__ = ["fpocket", "vina"]
