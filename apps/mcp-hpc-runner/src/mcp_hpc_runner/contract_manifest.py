from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import json
import os
import re
from typing import Any

from .models import (
    ExpectedOutput,
    FailureSignature,
    ResourceSpec,
    RunResult,
    RunSpec,
    StagedInput,
    SuccessCheck,
)


SUPPORT_STATUSES = {
    "smoke_runnable",
    "entrypoint_only",
    "blocked_missing_db_or_sample",
    "documented_only",
}

EXECUTOR_RELEVANCE = {
    "compile_and_parse",
    "compile_only",
    "discovery_only",
    "blocked",
}

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|passwd|token|secret|api[_-]?key)", re.IGNORECASE
)


class ContractManifestError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ToolContract:
    raw: dict[str, Any]

    @property
    def tool_id(self) -> str:
        return str(self.raw["tool_id"])

    @property
    def stage(self) -> str:
        return str(self.raw["stage"])

    @property
    def support_status(self) -> str:
        return str(self.raw["support_status"])

    @property
    def executor_relevance(self) -> str:
        return str(self.raw["executor_relevance"])

    @property
    def adapter_id(self) -> str:
        return str(self.raw.get("adapter_id", self.tool_id))

    @property
    def entrypoint(self) -> dict[str, Any]:
        return dict(self.raw["entrypoint"])

    @property
    def resource_profile(self) -> dict[str, Any]:
        return dict(self.raw["resource_profile"])


def default_manifest_path() -> Path:
    return Path(__file__).resolve().parent / "contracts" / "hpc_tool_contracts.json"


def load_contract_manifest(path: str | Path | None = None) -> list[ToolContract]:
    manifest_path = Path(path).expanduser() if path else default_manifest_path()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_contract_manifest(payload)
    return [ToolContract(raw=item) for item in payload["tools"]]


def validate_contract_manifest(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != 1:
        raise ContractManifestError("contract manifest schema_version must be 1")
    tools = payload.get("tools")
    if not isinstance(tools, list) or not tools:
        raise ContractManifestError("contract manifest must contain a non-empty tools list")

    seen: set[str] = set()
    required = {
        "tool_id",
        "stage",
        "deployment_mode",
        "entrypoint",
        "resource_profile",
        "required_inputs",
        "optional_params",
        "expected_outputs",
        "success_checks",
        "known_failure_signatures",
        "support_status",
        "executor_relevance",
    }
    for index, tool in enumerate(tools):
        if not isinstance(tool, dict):
            raise ContractManifestError(f"tool entry {index} must be an object")
        missing = sorted(required.difference(tool))
        if missing:
            raise ContractManifestError(
                f"{tool.get('tool_id', f'tool[{index}]')} is missing {missing}"
            )
        tool_id = str(tool["tool_id"])
        if tool_id in seen:
            raise ContractManifestError(f"duplicate tool_id: {tool_id}")
        seen.add(tool_id)
        if tool["support_status"] not in SUPPORT_STATUSES:
            raise ContractManifestError(f"{tool_id} has unsupported support_status")
        if tool["executor_relevance"] not in EXECUTOR_RELEVANCE:
            raise ContractManifestError(f"{tool_id} has unsupported executor_relevance")
        _validate_entrypoint(tool_id, tool["entrypoint"])
        _validate_resource_profile(tool_id, tool["resource_profile"])


def _validate_entrypoint(tool_id: str, entrypoint: Any) -> None:
    if not isinstance(entrypoint, dict):
        raise ContractManifestError(f"{tool_id}.entrypoint must be an object")
    if entrypoint.get("kind") not in {"wrapper", "sif", "native", "spack"}:
        raise ContractManifestError(f"{tool_id}.entrypoint.kind is unsupported")
    if not entrypoint.get("path"):
        raise ContractManifestError(f"{tool_id}.entrypoint.path must be non-empty")


def _validate_resource_profile(tool_id: str, profile: Any) -> None:
    if not isinstance(profile, dict):
        raise ContractManifestError(f"{tool_id}.resource_profile must be an object")
    for key in ("cpus", "mem_mb", "gpus", "time_minutes"):
        if int(profile.get(key, 0)) < (0 if key == "gpus" else 1):
            raise ContractManifestError(f"{tool_id}.resource_profile.{key} is invalid")


def build_discovery_runspec(contract: ToolContract) -> RunSpec:
    entrypoint = contract.entrypoint
    command = _discovery_command(contract)
    return RunSpec(
        name=f"contract-discovery-{contract.tool_id}",
        stage=contract.stage,
        command=command,
        execution_mode="ssh",
        resources=ResourceSpec(cpus=1, mem_mb=256, gpus=0, time_minutes=5),
        metadata={
            "tool_contract": {
                "adapter_id": contract.adapter_id,
                "tool_id": contract.tool_id,
                "phase": "discovery",
                "entrypoint": entrypoint,
            }
        },
    )


def build_smoke_runspec(
    contract: ToolContract,
    input_root: Path,
    *,
    partition: str | None = None,
) -> RunSpec:
    if contract.support_status != "smoke_runnable":
        raise ValueError(f"{contract.tool_id} is not marked smoke_runnable")
    if contract.tool_id == "fpocket":
        return _build_fpocket_smoke(contract, input_root, partition=partition)
    if contract.tool_id == "vina":
        return _build_vina_smoke(contract, input_root, partition=partition)
    raise ValueError(f"no smoke RunSpec compiler is available for {contract.tool_id}")


def _resource_spec(contract: ToolContract, partition: str | None) -> ResourceSpec:
    profile = contract.resource_profile
    return ResourceSpec(
        cpus=int(profile["cpus"]),
        mem_mb=int(profile["mem_mb"]),
        gpus=int(profile["gpus"]),
        time_minutes=int(profile["time_minutes"]),
        partition=partition or profile.get("partition"),
    )


def _common_metadata(contract: ToolContract, phase: str) -> dict[str, Any]:
    entrypoint = contract.entrypoint
    preflight_kind = "sif" if entrypoint["kind"] == "sif" else "binary"
    return {
        "tool_contract": {
            "adapter_id": contract.adapter_id,
            "tool_id": contract.tool_id,
            "phase": phase,
            "support_status": contract.support_status,
            "executor_relevance": contract.executor_relevance,
            "preflight_hints": {
                "entrypoint": {"kind": preflight_kind, "path": entrypoint["path"]},
                "bind_paths": entrypoint.get("bind_paths", []),
            },
        }
    }


def _build_fpocket_smoke(
    contract: ToolContract, input_root: Path, *, partition: str | None
) -> RunSpec:
    command = [
        "bash",
        "-lc",
        (
            'apptainer exec --cleanenv '
            '--pwd /out '
            '--bind "$MCP_WORKDIR:/work" '
            '--bind "$MCP_OUTDIR:/out" '
            '--bind "$MCP_TMPDIR:/tmp" '
            "~/containers/fpocket.sif fpocket -f /work/target.pdb && "
            'if [ -d "$MCP_WORKDIR/target_out" ]; then '
            'rm -rf "$MCP_OUTDIR/target_out" && '
            'mv "$MCP_WORKDIR/target_out" "$MCP_OUTDIR/target_out"; '
            "fi"
        ),
    ]
    return RunSpec(
        name="contract-smoke-fpocket",
        stage=contract.stage,
        command=command,
        execution_mode="sbatch",
        resources=_resource_spec(contract, partition),
        inputs=[
            StagedInput(
                local_path=str(input_root / "target.pdb"),
                remote_path="target.pdb",
            )
        ],
        expected_outputs=[
            ExpectedOutput(
                path="target_out", kind="dir", required=True, non_empty=True
            )
        ],
        success_checks=[
            SuccessCheck(check_type="exists", path="target_out"),
            SuccessCheck(check_type="non_empty", path="target_out"),
        ],
        failure_signatures=[
            FailureSignature(pattern="SIF image not found", error_code="SIF_MISSING"),
            FailureSignature(pattern="apptainer: command not found", error_code="APPTAINER_MISSING"),
            FailureSignature(pattern="No such file", error_code="INPUT_OR_ENTRYPOINT_MISSING"),
        ],
        metadata=_common_metadata(contract, "smoke"),
    )


def _build_vina_smoke(
    contract: ToolContract, input_root: Path, *, partition: str | None
) -> RunSpec:
    command = [
        "bash",
        "-lc",
        (
            'apptainer exec --cleanenv '
            '--bind "$MCP_WORKDIR:/work" '
            '--bind "$MCP_OUTDIR:/out" '
            '--bind "$MCP_TMPDIR:/tmp" '
            "~/containers/vina.sif vina "
            "--receptor /work/receptor.pdbqt "
            "--ligand /work/ligand.pdbqt "
            "--center_x 0 --center_y 0 --center_z 0 "
            "--size_x 10 --size_y 10 --size_z 10 "
            "--exhaustiveness 1 --num_modes 1 "
            "--out /out/vina_out.pdbqt --log /out/vina.log"
        ),
    ]
    return RunSpec(
        name="contract-smoke-vina",
        stage=contract.stage,
        command=command,
        execution_mode="sbatch",
        resources=_resource_spec(contract, partition),
        inputs=[
            StagedInput(
                local_path=str(input_root / "receptor.pdbqt"),
                remote_path="receptor.pdbqt",
            ),
            StagedInput(
                local_path=str(input_root / "ligand.pdbqt"),
                remote_path="ligand.pdbqt",
            ),
        ],
        expected_outputs=[
            ExpectedOutput(
                path="vina_out.pdbqt", kind="file", required=True, non_empty=True
            ),
            ExpectedOutput(path="vina.log", kind="file", required=True, non_empty=True),
        ],
        success_checks=[
            SuccessCheck(check_type="exists", path="vina_out.pdbqt"),
            SuccessCheck(check_type="exists", path="vina.log"),
            SuccessCheck(check_type="non_empty", path="vina.log"),
        ],
        failure_signatures=[
            FailureSignature(pattern="SIF image not found", error_code="SIF_MISSING"),
            FailureSignature(pattern="apptainer: command not found", error_code="APPTAINER_MISSING"),
            FailureSignature(pattern="Parse error", error_code="INPUT_PARSE_ERROR"),
        ],
        metadata=_common_metadata(contract, "smoke"),
    )


def _discovery_command(contract: ToolContract) -> list[str]:
    entrypoint = contract.entrypoint
    usage_args = entrypoint.get("usage_args", ["--help"])
    path = str(entrypoint["path"])
    kind = entrypoint["kind"]
    if kind == "sif":
        entry = str(entrypoint.get("entrypoint", contract.tool_id))
        return [
            "bash",
            "-lc",
            (
                f"test -r {path} && "
                f"apptainer exec --cleanenv {path} {entry} {' '.join(usage_args)}"
            ),
        ]
    return [
        "bash",
        "-lc",
        f"test -x {path} && {path} {' '.join(usage_args)}",
    ]


def base_contract_record(contract: ToolContract) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
        "tool_id": contract.tool_id,
        "stage": contract.stage,
        "support_status": contract.support_status,
        "executor_relevance": contract.executor_relevance,
        "declared_contract": contract.raw,
        "discovery": None,
        "smoke": None,
        "final_status": "not_run",
        "diagnostics": [],
    }


def result_summary(result: RunResult) -> dict[str, Any]:
    payload = result.to_dict()
    return sanitize_record(
        {
            "run_result_shape": sorted(payload),
            "run_result": payload,
            "parser_candidates": _parser_candidates(result),
        }
    )


def write_contract_record(record_root: Path, tool_id: str, record: dict[str, Any]) -> Path:
    record_root.mkdir(parents=True, exist_ok=True)
    path = record_root / f"{tool_id}.json"
    path.write_text(
        json.dumps(sanitize_record(record), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def sanitize_record(value: Any) -> Any:
    home = str(Path.home())
    cwd = str(Path.cwd())
    return _sanitize_value(value, path_prefixes=[home, cwd])


def _sanitize_value(value: Any, *, path_prefixes: list[str]) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            raw_key = str(key)
            sanitized_key = _sanitize_value(raw_key, path_prefixes=path_prefixes)
            sanitized[sanitized_key] = (
                "<REDACTED>"
                if _SENSITIVE_KEY_PATTERN.search(raw_key)
                else _sanitize_value(item, path_prefixes=path_prefixes)
            )
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item, path_prefixes=path_prefixes) for item in value]
    if isinstance(value, str):
        sanitized = value
        for prefix in path_prefixes:
            if prefix:
                sanitized = sanitized.replace(prefix, "<LOCAL_ROOT>")
        sanitized = re.sub(r"/home/[^/\s]+", "<HOME>", sanitized)
        sanitized = re.sub(r"[\w.-]+@[\w.-]+", "<SSH_TARGET>", sanitized)
        return sanitized
    return value


def _parser_candidates(result: RunResult) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for remote_path, local_path in result.artifacts.items():
        basename = os.path.basename(local_path.rstrip("/")) or os.path.basename(remote_path)
        if basename.endswith(".log") or basename == "vina.log":
            candidates.append({"artifact": basename, "parser": "vina_log"})
        elif basename.endswith(".pdbqt"):
            candidates.append({"artifact": basename, "parser": "vina_pose_pdbqt"})
        elif basename.endswith("_out") or basename == "target_out":
            candidates.append({"artifact": basename, "parser": "fpocket_output_dir"})
    return candidates
