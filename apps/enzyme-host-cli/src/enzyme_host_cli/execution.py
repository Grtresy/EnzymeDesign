from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_hpc_tool_contracts.runner_client import RunnerClient
from mcp_hpc_tool_contracts.service import run_adapter
from mcp_project_memory.models import utc_now_iso

from .plan_runtime import PlanStep

_ALIASES: dict[str, dict[str, str]] = {
    "hhblits": {"fasta": "query_fasta", "db": "db_prefix"},
    "chai_fold": {"fasta": "input_fasta"},
    "colabfold": {"fasta": "input_fasta"},
    "fpocket": {"pdb": "structure_path"},
    "tunnels": {"pdb": "structure_path"},
    "vina": {
        "receptor_pdbqt": "receptor_path",
        "ligand_pdbqt": "ligand_path",
    },
}


@dataclass(slots=True)
class ExecutionResult:
    run_id: str
    status: str
    manifest_payload: dict[str, Any]


class ExecutionAdapter:
    def __init__(self, runner_client: RunnerClient | None = None) -> None:
        self.runner_client = runner_client

    def run_step(self, project_root: Path, step: PlanStep) -> ExecutionResult:
        params = build_step_params(project_root, step)
        envelope = run_adapter(
            step.tool,
            params,
            asynchronous=True,
            wait=True,
            runner_client=self.runner_client,
        )
        submission = envelope.get("submission") or {}
        fetch = envelope.get("fetch") or {}
        job_status = envelope.get("job_status") or {}
        result = envelope.get("result") or {}
        run_id = str(
            submission.get("run_id")
            or job_status.get("run_id")
            or fetch.get("run_id")
            or result.get("run_id")
            or ""
        )
        if not run_id:
            raise RuntimeError(f"Missing run_id in execution response for step {step.step_id}")
        status = _final_status(envelope)
        manifest_payload = {
            "tool": step.tool,
            "step_id": step.step_id,
            "status": status,
            "created_at": utc_now_iso(),
            "submission": submission,
            "job_status": job_status,
            "result": result,
            "fetch": fetch,
            "compiled": envelope.get("compiled"),
        }
        return ExecutionResult(run_id=run_id, status=status, manifest_payload=manifest_payload)


def build_step_params(project_root: Path, step: PlanStep) -> dict[str, Any]:
    payload = step.payload
    params_raw = payload.get("params")
    inputs_raw = payload.get("inputs")
    if params_raw is not None and not isinstance(params_raw, dict):
        raise RuntimeError(f"Step {step.step_id} has invalid `params` payload")
    if inputs_raw is not None and not isinstance(inputs_raw, dict):
        raise RuntimeError(f"Step {step.step_id} has invalid `inputs` payload")

    params = dict(params_raw or {})
    aliases = _ALIASES.get(step.tool, {})
    for key, value in dict(inputs_raw or {}).items():
        normalized = aliases.get(str(key), str(key))
        params.setdefault(normalized, value)

    for key, value in list(params.items()):
        if _looks_like_path_key(key) and isinstance(value, str) and value:
            params[key] = _resolve_path(project_root, value)
    return params


def _looks_like_path_key(key: str) -> bool:
    return key.endswith("_path") or key.endswith("_fasta") or key.endswith("_json")


def _resolve_path(project_root: Path, value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str((project_root / path).resolve())


def _final_status(envelope: dict[str, Any]) -> str:
    fetch = envelope.get("fetch")
    if isinstance(fetch, dict) and fetch.get("status"):
        return str(fetch["status"])
    job_status = envelope.get("job_status")
    if isinstance(job_status, dict) and job_status.get("state"):
        return str(job_status["state"])
    submission = envelope.get("submission")
    if isinstance(submission, dict) and submission.get("status"):
        return str(submission["status"])
    result = envelope.get("result")
    if isinstance(result, dict) and result.get("status"):
        return str(result["status"])
    return "unknown"
