from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from openzyme_runtime import ExecutionPlanDraft

from .catalog import RepoBackedHpcCatalogProvider
from .contracts import ToolExecutionContract
from .contracts import get_hpc_tool_contract
from .models import ParsedExecutionResult
from .parsers import parse_fpocket_artifacts
from .parsers import parse_vina_artifacts


def _artifact_id(artifact: dict[str, Any]) -> str:
    return str(artifact.get("artifact_id") or "")


def _select_artifact(
    *,
    slot_name: str,
    explicit_id: Any,
    required_artifacts: list[dict[str, Any]],
    default_index: int,
) -> dict[str, Any]:
    if explicit_id is not None:
        requested = str(explicit_id)
        for artifact in required_artifacts:
            if _artifact_id(artifact) == requested:
                return artifact
        raise ValueError(f"{slot_name} artifact {requested!r} was not provided in required_artifact_ids")
    if len(required_artifacts) > default_index:
        return required_artifacts[default_index]
    raise ValueError(f"{slot_name} requires an artifact id or required_artifact_ids[{default_index}]")


def _local_path(artifact: dict[str, Any], slot_name: str) -> str:
    storage_uri = str(artifact.get("storage_uri") or "")
    if not storage_uri:
        raise ValueError(f"{slot_name} artifact {_artifact_id(artifact)!r} has no storage_uri")
    return storage_uri


def _validate_runner_relative_path(path: str) -> str:
    normalized = path.strip()
    if not normalized or normalized.startswith("/"):
        raise ValueError(f"runner path must be relative under work/out: {path!r}")
    parts = PurePosixPath(normalized).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"runner path must not contain empty, '.', or '..' segments: {path!r}")
    if any(char in normalized for char in (";", "&", "|", "`", "$", "\\", "\n", "\r")):
        raise ValueError(f"runner path must not contain shell metacharacters: {path!r}")
    return normalized


def _shell_number(value: Any, default: float | int) -> str:
    candidate = default if value is None else value
    try:
        number = float(candidate)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Vina numeric parameter must be a number: {candidate!r}") from exc
    if number.is_integer():
        return str(int(number))
    return str(number)


def _fpocket_command() -> list[str]:
    return [
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


def _render_command(contract: ToolExecutionContract, tool_inputs: dict[str, Any]) -> list[str]:
    if contract.command_template_id == "fpocket_sif_v1":
        return _fpocket_command()
    if contract.command_template_id == "vina_sif_v1":
        return _vina_command(tool_inputs)
    raise ValueError(f"unsupported command template {contract.command_template_id!r}")


def _vina_command(tool_inputs: dict[str, Any]) -> list[str]:
    center_x = _shell_number(tool_inputs.get("center_x"), 0)
    center_y = _shell_number(tool_inputs.get("center_y"), 0)
    center_z = _shell_number(tool_inputs.get("center_z"), 0)
    size_x = _shell_number(tool_inputs.get("size_x"), 10)
    size_y = _shell_number(tool_inputs.get("size_y"), 10)
    size_z = _shell_number(tool_inputs.get("size_z"), 10)
    exhaustiveness = _shell_number(tool_inputs.get("exhaustiveness"), 8)
    num_modes = _shell_number(tool_inputs.get("num_modes"), 9)
    return [
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
            f"--center_x {center_x} --center_y {center_y} --center_z {center_z} "
            f"--size_x {size_x} --size_y {size_y} --size_z {size_z} "
            f"--exhaustiveness {exhaustiveness} --num_modes {num_modes} "
            "--out /out/vina_out.pdbqt --log /out/vina.log"
        ),
    ]


@dataclass(frozen=True, slots=True)
class DefaultHpcExecutionRegistry:
    catalog_provider: RepoBackedHpcCatalogProvider

    def compile_request(
        self,
        *,
        tool_id: str,
        plan: ExecutionPlanDraft,
        handoff: dict[str, Any],
        host_toolbox: Any,
    ) -> dict[str, Any]:
        entry = self.catalog_provider.get_entry(tool_id)
        if entry is None:
            raise ValueError(f"Unknown HPC catalog tool: {tool_id}")
        if str(entry.get("execution_support")) != "runnable":
            raise ValueError(f"HPC catalog tool {tool_id} is discovery-only in V1.")
        contract = get_hpc_tool_contract(tool_id)
        session_id = str(handoff.get("session_id") or "")
        required_artifacts = host_toolbox.resolve_artifacts(
            session_id,
            list(handoff.get("required_artifact_ids") or []),
        )
        context_artifacts = host_toolbox.resolve_artifacts(
            session_id,
            list(handoff.get("context_artifact_ids") or []),
        )
        if tool_id == "fpocket":
            primary_input = _select_artifact(
                slot_name="fpocket structure",
                explicit_id=plan.tool_inputs.get("structure_artifact_id"),
                required_artifacts=required_artifacts,
                default_index=0,
            )
            request = host_toolbox.build_execution_request(
                execution_subject_id=str(primary_input.get("artifact_id") or "artifact"),
                execution_subject_label=str(primary_input.get("title") or "artifact"),
                execution_mode=plan.execution_mode,
                command=_render_command(contract, dict(plan.tool_inputs)),
                resources=contract.resources,
                inputs=[
                    {
                        "artifact_id": _artifact_id(primary_input),
                        "local_path": _local_path(primary_input, "fpocket structure"),
                        "remote_path": _validate_runner_relative_path(contract.input_slots[0].remote_path),
                        "required": True,
                        "stage_to": "work",
                    }
                ],
                expected_outputs=[
                    {
                        "path": _validate_runner_relative_path(output.path),
                        "kind": output.kind,
                        "required": output.required,
                        "non_empty": output.non_empty,
                    }
                    for output in contract.expected_outputs
                ],
                success_checks=[dict(item) for item in contract.success_checks],
                failure_signatures=[dict(item) for item in contract.failure_signatures],
                metadata={
                    "catalog_tool_id": tool_id,
                    "tool_inputs": dict(plan.tool_inputs),
                    "tool_contract": {
                        "adapter_id": contract.adapter_id,
                        "tool_id": contract.tool_id,
                        "command_template_id": contract.command_template_id,
                        "parser_hints": contract.parser_hints,
                        "preprocess_requirements": contract.preprocess_requirements,
                    },
                    "execution_goal": handoff.get("execution_goal"),
                    "required_artifact_ids": list(handoff.get("required_artifact_ids") or []),
                    "context_artifact_ids": list(handoff.get("context_artifact_ids") or []),
                    "resolved_artifacts": required_artifacts + context_artifacts,
                    "input_artifact_ids": [_artifact_id(primary_input)],
                },
                tool_name="exec.run",
            )
            return request.model_dump()
        if tool_id == "vina":
            receptor = _select_artifact(
                slot_name="vina receptor",
                explicit_id=plan.tool_inputs.get("receptor_artifact_id"),
                required_artifacts=required_artifacts,
                default_index=0,
            )
            ligand = _select_artifact(
                slot_name="vina ligand",
                explicit_id=plan.tool_inputs.get("ligand_artifact_id"),
                required_artifacts=required_artifacts,
                default_index=1,
            )
            request = host_toolbox.build_execution_request(
                execution_subject_id=str(receptor.get("artifact_id") or "artifact"),
                execution_subject_label=str(receptor.get("title") or "artifact"),
                execution_mode=plan.execution_mode,
                command=_render_command(contract, dict(plan.tool_inputs)),
                resources=contract.resources,
                inputs=[
                    {
                        "artifact_id": _artifact_id(receptor),
                        "local_path": _local_path(receptor, "vina receptor"),
                        "remote_path": _validate_runner_relative_path(contract.input_slots[0].remote_path),
                        "required": True,
                        "stage_to": "work",
                    },
                    {
                        "artifact_id": _artifact_id(ligand),
                        "local_path": _local_path(ligand, "vina ligand"),
                        "remote_path": _validate_runner_relative_path(contract.input_slots[1].remote_path),
                        "required": True,
                        "stage_to": "work",
                    },
                ],
                expected_outputs=[
                    {
                        "path": _validate_runner_relative_path(output.path),
                        "kind": output.kind,
                        "required": output.required,
                        "non_empty": output.non_empty,
                    }
                    for output in contract.expected_outputs
                ],
                success_checks=[dict(item) for item in contract.success_checks],
                failure_signatures=[dict(item) for item in contract.failure_signatures],
                metadata={
                    "catalog_tool_id": tool_id,
                    "tool_inputs": dict(plan.tool_inputs),
                    "tool_contract": {
                        "adapter_id": contract.adapter_id,
                        "tool_id": contract.tool_id,
                        "command_template_id": contract.command_template_id,
                        "parser_hints": contract.parser_hints,
                        "preprocess_requirements": contract.preprocess_requirements,
                    },
                    "execution_goal": handoff.get("execution_goal"),
                    "required_artifact_ids": list(handoff.get("required_artifact_ids") or []),
                    "context_artifact_ids": list(handoff.get("context_artifact_ids") or []),
                    "resolved_artifacts": required_artifacts + context_artifacts,
                    "input_artifact_ids": [_artifact_id(receptor), _artifact_id(ligand)],
                },
                tool_name="exec.run",
            )
            return request.model_dump()
        raise ValueError(f"No execution compiler registered for {tool_id}.")

    def parse_result(
        self,
        *,
        tool_id: str,
        outcome: Any,
        plan: ExecutionPlanDraft,
        artifact_refs: list[dict[str, Any]],
    ) -> ParsedExecutionResult:
        if tool_id == "fpocket":
            parsed = parse_fpocket_artifacts(artifact_refs)
            pockets_found = int(parsed.findings.get("pockets_found") or 0)
            return ParsedExecutionResult(
                result_summary=parsed.summary
                or "fpocket completed, but no structured pocket summary was parsed.",
                structured_findings={
                    "design_signal": "proceed" if pockets_found > 0 else "revise",
                    "confidence": "medium" if parsed.parser_status == "parsed" else "low",
                    "parser_status": parsed.parser_status,
                    "artifacts": artifact_refs,
                    **parsed.findings,
                },
            )
        if tool_id == "vina":
            parsed = parse_vina_artifacts(artifact_refs)
            affinity_value = parsed.findings.get("best_affinity")
            has_affinity = isinstance(affinity_value, int | float)
            return ParsedExecutionResult(
                result_summary=parsed.summary
                or "vina completed, but no structured docking score was parsed.",
                structured_findings={
                    "design_signal": "proceed"
                    if has_affinity and float(affinity_value) <= -6.0
                    else "revise",
                    "confidence": "medium" if parsed.parser_status == "parsed" else "low",
                    "parser_status": parsed.parser_status,
                    "artifacts": artifact_refs,
                    **parsed.findings,
                },
            )
        return ParsedExecutionResult(
            result_summary=f"{tool_id} execution completed.",
            structured_findings={
                "design_signal": "proceed",
                "artifacts": artifact_refs,
                "tool_inputs": dict(plan.tool_inputs),
            },
        )


__all__ = ["DefaultHpcExecutionRegistry"]
