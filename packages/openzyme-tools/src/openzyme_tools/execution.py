from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openzyme_runtime import ExecutionPlanDraft

from .catalog import RepoBackedHpcCatalogProvider
from .models import ParsedExecutionResult
from .parsers import parse_fpocket_artifacts
from .parsers import parse_vina_artifacts


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
        episode_id = str(handoff.get("episode_id") or "")
        required_artifacts = host_toolbox.resolve_artifacts(
            episode_id,
            list(handoff.get("required_artifact_ids") or []),
        )
        context_artifacts = host_toolbox.resolve_artifacts(
            episode_id,
            list(handoff.get("context_artifact_ids") or []),
        )
        primary_input = None if not required_artifacts else required_artifacts[0]
        if tool_id == "fpocket":
            structure_path = str(
                plan.tool_inputs.get("structure_path")
                or (None if primary_input is None else primary_input.get("storage_uri"))
                or "input_structure.pdb"
            )
            request = host_toolbox.build_execution_request(
                execution_subject_id=str((None if primary_input is None else primary_input.get("artifact_id")) or "artifact"),
                execution_subject_label=str((None if primary_input is None else primary_input.get("title")) or "artifact"),
                execution_mode=plan.execution_mode,
                command=["fpocket", "-f", structure_path],
                metadata={
                    "catalog_tool_id": tool_id,
                    "tool_inputs": dict(plan.tool_inputs),
                    "tool_contract": {"adapter_id": "fpocket"},
                    "execution_goal": handoff.get("execution_goal"),
                    "required_artifact_ids": list(handoff.get("required_artifact_ids") or []),
                    "context_artifact_ids": list(handoff.get("context_artifact_ids") or []),
                    "resolved_artifacts": required_artifacts + context_artifacts,
                },
                tool_name="exec.run",
            )
            return request.model_dump()
        if tool_id == "vina":
            receptor_path = str(
                plan.tool_inputs.get("receptor_path")
                or (None if primary_input is None else primary_input.get("storage_uri"))
                or "receptor.pdbqt"
            )
            ligand_default = None
            if len(required_artifacts) > 1:
                ligand_default = required_artifacts[1].get("storage_uri")
            ligand_path = str(plan.tool_inputs.get("ligand_path") or ligand_default or "ligand.pdbqt")
            center_x = str(plan.tool_inputs.get("center_x") or "0")
            center_y = str(plan.tool_inputs.get("center_y") or "0")
            center_z = str(plan.tool_inputs.get("center_z") or "0")
            request = host_toolbox.build_execution_request(
                execution_subject_id=str((None if primary_input is None else primary_input.get("artifact_id")) or "artifact"),
                execution_subject_label=str((None if primary_input is None else primary_input.get("title")) or "artifact"),
                execution_mode=plan.execution_mode,
                command=[
                    "vina",
                    "--receptor",
                    receptor_path,
                    "--ligand",
                    ligand_path,
                    "--center_x",
                    center_x,
                    "--center_y",
                    center_y,
                    "--center_z",
                    center_z,
                ],
                metadata={
                    "catalog_tool_id": tool_id,
                    "tool_inputs": dict(plan.tool_inputs),
                    "tool_contract": {"adapter_id": "vina"},
                    "execution_goal": handoff.get("execution_goal"),
                    "required_artifact_ids": list(handoff.get("required_artifact_ids") or []),
                    "context_artifact_ids": list(handoff.get("context_artifact_ids") or []),
                    "resolved_artifacts": required_artifacts + context_artifacts,
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
