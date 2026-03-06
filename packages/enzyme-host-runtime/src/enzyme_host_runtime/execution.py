from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import uuid

from mcp_hpc_tool_contracts.runner_client import RunnerClient
from mcp_hpc_tool_contracts.service import run_adapter
from mcp_project_memory.models import utc_now_iso
from preprocess_backend import convert_format
from preprocess_backend import prepare_ligand
from preprocess_backend import prepare_receptor
from preprocess_backend import smiles_to_3d

from .plan_runtime import PlanStep

_ALIASES: dict[str, dict[str, str]] = {
    "convert_format": {"input": "input_path", "output": "output_path"},
    "hhblits": {"fasta": "query_fasta", "db": "db_prefix"},
    "chai_fold": {"fasta": "input_fasta"},
    "colabfold": {"fasta": "input_fasta"},
    "fpocket": {"pdb": "structure_path"},
    "prepare_receptor": {"input": "input_path", "output": "output_path"},
    "prepare_ligand": {"input": "input_path", "output": "output_path"},
    "smiles_to_3d": {"output": "output_path"},
    "tunnels": {"pdb": "structure_path"},
    "vina": {
        "receptor_pdbqt": "receptor_path",
        "ligand_pdbqt": "ligand_path",
    },
}
PREPROCESS_TOOLS = {
    "convert_format",
    "smiles_to_3d",
    "prepare_receptor",
    "prepare_ligand",
}
HPC_TOOLS = {
    "fpocket",
    "hhblits",
    "chai_fold",
    "colabfold",
    "alphafold3",
    "tunnels",
    "vina",
}


@dataclass(slots=True)
class ExecutionResult:
    run_id: str
    status: str
    manifest_payload: dict[str, Any]


class StepExecutor:
    def supports(self, tool: str) -> bool:
        raise NotImplementedError

    def run_step(self, project_root: Path, episode_id: str, step: PlanStep) -> ExecutionResult:
        raise NotImplementedError


class RoutedExecutionAdapter:
    def __init__(self, executors: list[StepExecutor] | None = None) -> None:
        self.executors = executors or [LocalPreprocessExecutor(), HpcToolContractsExecutor()]

    def supports(self, tool: str) -> bool:
        return any(executor.supports(tool) for executor in self.executors)

    def run_step(self, project_root: Path, episode_id: str, step: PlanStep) -> ExecutionResult:
        for executor in self.executors:
            if executor.supports(step.tool):
                return executor.run_step(project_root, episode_id, step)
        raise RuntimeError(f"Unsupported execution tool: {step.tool}")


class LocalPreprocessExecutor(StepExecutor):
    def supports(self, tool: str) -> bool:
        return tool in PREPROCESS_TOOLS

    def run_step(self, project_root: Path, episode_id: str, step: PlanStep) -> ExecutionResult:
        params = build_step_params(project_root, step)
        if step.tool == "convert_format":
            result = convert_format(
                input_path=str(params["input_path"]),
                fmt_out=str(params["fmt_out"]),
                output_path=params.get("output_path"),
            )
        elif step.tool == "smiles_to_3d":
            result = smiles_to_3d(
                smiles=str(params["smiles"]),
                output_path=params.get("output_path"),
                n_confs=int(params.get("n_confs", 1)),
            )
        elif step.tool == "prepare_receptor":
            result = prepare_receptor(
                input_path=str(params["input_path"]),
                output_path=params.get("output_path"),
            )
        elif step.tool == "prepare_ligand":
            result = prepare_ligand(
                input_path=params.get("input_path"),
                smiles=params.get("smiles"),
                output_path=params.get("output_path"),
            )
        else:
            raise RuntimeError(f"Unsupported preprocess tool: {step.tool}")

        payload = result.to_dict()
        run_id = stable_local_run_id(episode_id, step.step_id)
        manifest_payload = {
            "backend": "local-preprocess",
            "tool": step.tool,
            "step_id": step.step_id,
            "status": "completed",
            "created_at": utc_now_iso(),
            "result": {
                "status": "completed",
                "output": payload,
            },
            "output_refs": _output_refs(project_root, payload),
            "payload": payload,
        }
        return ExecutionResult(run_id=run_id, status="completed", manifest_payload=manifest_payload)


class HpcToolContractsExecutor(StepExecutor):
    def __init__(self, runner_client: RunnerClient | None = None) -> None:
        self.runner_client = runner_client

    def supports(self, tool: str) -> bool:
        return tool in HPC_TOOLS

    def run_step(self, project_root: Path, episode_id: str, step: PlanStep) -> ExecutionResult:
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
            "backend": "mcp-hpc-tool-contracts",
            "tool": step.tool,
            "step_id": step.step_id,
            "status": status,
            "created_at": utc_now_iso(),
            "submission": submission,
            "job_status": job_status,
            "result": result,
            "fetch": fetch,
            "compiled": envelope.get("compiled"),
            "output_refs": _artifact_output_refs(fetch),
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


def stable_local_run_id(episode_id: str, step_id: str) -> str:
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, f"enzyme:{episode_id}")
    return f"local-{uuid.uuid5(namespace, step_id)}"


def _output_refs(project_root: Path, payload: dict[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    output_path = payload.get("output_path")
    if isinstance(output_path, str) and output_path:
        refs.append({"path": _relative_or_absolute(project_root, output_path), "kind": "output"})
    input_path = payload.get("input_path")
    if isinstance(input_path, str) and input_path:
        refs.append({"path": _relative_or_absolute(project_root, input_path), "kind": "input"})
    return refs


def _artifact_output_refs(fetch_payload: dict[str, Any]) -> list[dict[str, str]]:
    artifacts = fetch_payload.get("normalized_artifacts")
    if not isinstance(artifacts, list):
        return []
    refs: list[dict[str, str]] = []
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        refs.append(
            {
                "path": str(item.get("local_path") or item.get("remote_path") or ""),
                "kind": "artifact",
            }
        )
    return [ref for ref in refs if ref["path"]]


def _looks_like_path_key(key: str) -> bool:
    return key.endswith("_path") or key.endswith("_fasta") or key.endswith("_json")


def _resolve_path(project_root: Path, value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str((project_root / path).resolve())


def _relative_or_absolute(project_root: Path, value: str) -> str:
    path = Path(value)
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path)


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
