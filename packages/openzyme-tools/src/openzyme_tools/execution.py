from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any

from openzyme_runtime import ExecutionPlanDraft

from .catalog import RepoBackedHpcCatalogProvider
from .command_templates import contract_outputs
from .command_templates import contract_payload
from .command_templates import render_contract_command
from .command_templates import validate_runner_relative_path
from .contracts import get_hpc_tool_contract
from .models import ParsedExecutionResult
from .parsers import parse_fpocket_artifacts
from .parsers import parse_vina_artifacts


def _artifact_payload(artifact: Any) -> dict[str, Any]:
    if isinstance(artifact, dict):
        return dict(artifact)
    if hasattr(artifact, "to_dict"):
        return dict(artifact.to_dict())
    return {
        "artifact_id": getattr(artifact, "artifact_id", None),
        "storage_uri": getattr(artifact, "storage_uri", None),
        "title": getattr(artifact, "title", None),
        "relative_path": getattr(artifact, "relative_path", None),
        "metadata": getattr(artifact, "metadata", None),
    }


def _artifact_id(artifact: Any) -> str:
    return str(_artifact_payload(artifact).get("artifact_id") or "")


def _select_artifact(
    *,
    slot_name: str,
    explicit_id: Any,
    required_artifacts: Sequence[Any],
    default_index: int,
) -> Any:
    if explicit_id is not None:
        requested = str(explicit_id)
        for artifact in required_artifacts:
            if _artifact_id(artifact) == requested:
                return artifact
        raise ValueError(f"{slot_name} artifact {requested!r} was not provided in required_artifact_ids")
    if len(required_artifacts) > default_index:
        return required_artifacts[default_index]
    raise ValueError(f"{slot_name} requires an artifact id or required_artifact_ids[{default_index}]")


def _local_path(artifact: Any, slot_name: str) -> str:
    storage_uri = str(_artifact_payload(artifact).get("storage_uri") or "")
    if not storage_uri:
        raise ValueError(f"{slot_name} artifact {_artifact_id(artifact)!r} has no storage_uri")
    return storage_uri


def _resolved_artifact_payloads(artifacts: Sequence[Any]) -> list[dict[str, Any]]:
    return [_artifact_payload(artifact) for artifact in artifacts]


def _compile_inputs_for_contract(
    *,
    tool_id: str,
    tool_inputs: dict[str, Any],
    required_artifacts: Sequence[Any],
) -> tuple[list[dict[str, Any]], list[str], Any]:
    contract = get_hpc_tool_contract(tool_id)
    inputs: list[dict[str, Any]] = []
    input_artifact_ids: list[str] = []
    first_artifact: Any | None = None
    for index, slot in enumerate(contract.input_slots):
        artifact = _select_artifact(
            slot_name=f"{tool_id} {slot.slot_id}",
            explicit_id=tool_inputs.get(f"{slot.slot_id}_artifact_id"),
            required_artifacts=required_artifacts,
            default_index=index,
        )
        first_artifact = artifact if first_artifact is None else first_artifact
        input_artifact_ids.append(_artifact_id(artifact))
        inputs.append(
            {
                "artifact_id": _artifact_id(artifact),
                "local_path": _local_path(artifact, f"{tool_id} {slot.slot_id}"),
                "remote_path": validate_runner_relative_path(slot.remote_path),
                "required": slot.required,
                "stage_to": "work",
            }
        )
    if first_artifact is None:
        raise ValueError(f"{tool_id} requires at least one input artifact.")
    return inputs, input_artifact_ids, first_artifact


def compile_hpc_tool_request(
    *,
    tool_id: str,
    tool_inputs: dict[str, Any],
    execution_mode: str,
    execution_goal: Any,
    required_artifacts: Sequence[Any],
    context_artifacts: Sequence[Any],
    required_artifact_ids: Sequence[str],
    context_artifact_ids: Sequence[str],
    task_id: str | None = None,
) -> dict[str, Any]:
    contract = get_hpc_tool_contract(tool_id)
    inputs, input_artifact_ids, subject_artifact = _compile_inputs_for_contract(
        tool_id=tool_id,
        tool_inputs=tool_inputs,
        required_artifacts=required_artifacts,
    )
    metadata: dict[str, Any] = {
        "catalog_tool_id": tool_id,
        "tool_inputs": dict(tool_inputs),
        "tool_contract": contract_payload(contract),
        "execution_goal": execution_goal,
        "required_artifact_ids": list(required_artifact_ids),
        "context_artifact_ids": list(context_artifact_ids),
        "resolved_artifacts": _resolved_artifact_payloads((*required_artifacts, *context_artifacts)),
        "input_artifact_ids": input_artifact_ids,
    }
    if task_id is not None:
        metadata["task_id"] = task_id
    preprocess_artifact_ids = [
        _artifact_id(artifact)
        for artifact in required_artifacts
        if isinstance(_artifact_payload(artifact).get("metadata"), dict)
        and _artifact_payload(artifact)["metadata"].get("source") == "preprocess"
    ]
    if preprocess_artifact_ids:
        metadata["preprocess_artifact_ids"] = preprocess_artifact_ids
    subject_id = _artifact_id(subject_artifact) or "artifact"
    if tool_id.startswith("bio_tools."):
        run_name = f"execution-{tool_id.removeprefix('bio_tools.')}-{subject_id}"
    else:
        run_name = f"execution-{subject_id}"
    return {
        "tool_name": "exec.run",
        "runspec": {
            "name": run_name,
            "stage": "execution",
            "command": render_contract_command(contract, tool_inputs),
            "execution_mode": execution_mode,
            "resources": dict(contract.resources),
            "inputs": inputs,
            "expected_outputs": contract_outputs(contract),
            "success_checks": [dict(item) for item in contract.success_checks],
            "failure_signatures": [dict(item) for item in contract.failure_signatures],
            "metadata": metadata,
        },
    }


def parse_execution_result(
    *,
    tool_id: str,
    raw_result: dict[str, Any],
    tool_inputs: dict[str, Any],
    artifact_refs: Sequence[Any],
) -> ParsedExecutionResult:
    artifact_payloads = [_artifact_payload(artifact) for artifact in artifact_refs]
    if tool_id == "fpocket":
        parsed = parse_fpocket_artifacts(artifact_payloads)
        fallback_pockets = raw_result.get("pockets_found")
        try:
            pockets_found = int(parsed.findings.get("pockets_found") or fallback_pockets or 0)
        except (TypeError, ValueError):
            pockets_found = 0
        used_raw_result_fallback = parsed.parser_status != "parsed" and pockets_found > 0
        result_summary = parsed.summary
        if used_raw_result_fallback:
            result_summary = f"fpocket found {pockets_found} pocket(s) for the selected artifact set."
        return ParsedExecutionResult(
            result_summary=result_summary
            or (
                f"fpocket found {pockets_found} pocket(s) for the selected artifact set."
                if pockets_found
                else "fpocket completed, but no structured pocket summary was parsed."
            ),
            structured_findings={
                "design_signal": "proceed" if pockets_found > 0 else "revise",
                "confidence": "medium" if parsed.parser_status == "parsed" else "low",
                "parser_status": (
                    "raw_result_fallback" if used_raw_result_fallback else parsed.parser_status
                ),
                "artifacts": artifact_payloads,
                **parsed.findings,
                "pockets_found": pockets_found,
            },
        )
    if tool_id == "vina":
        parsed = parse_vina_artifacts(artifact_payloads)
        affinity_value = parsed.findings.get("best_affinity")
        has_affinity = isinstance(affinity_value, int | float)
        structured_findings = {
            "design_signal": "proceed" if has_affinity and float(affinity_value) <= -6.0 else "revise",
            "confidence": "medium" if parsed.parser_status == "parsed" else "low",
            "parser_status": parsed.parser_status,
            "artifacts": artifact_payloads,
            **parsed.findings,
        }
        return ParsedExecutionResult(
            result_summary=parsed.summary
            or "vina completed, but no structured docking score was parsed.",
            structured_findings=structured_findings,
        )
    return ParsedExecutionResult(
        result_summary=f"{tool_id} execution completed.",
        structured_findings={
            "design_signal": "proceed",
            "artifacts": artifact_payloads,
            "tool_inputs": dict(tool_inputs),
        },
    )


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
        session_id = str(handoff.get("session_id") or "")
        required_artifacts = host_toolbox.resolve_artifacts(
            session_id,
            list(handoff.get("required_artifact_ids") or []),
        )
        context_artifacts = host_toolbox.resolve_artifacts(
            session_id,
            list(handoff.get("context_artifact_ids") or []),
        )
        return compile_hpc_tool_request(
            tool_id=tool_id,
            tool_inputs=dict(plan.tool_inputs),
            execution_mode=plan.execution_mode,
            execution_goal=handoff.get("execution_goal"),
            required_artifacts=required_artifacts,
            context_artifacts=context_artifacts,
            required_artifact_ids=[str(value) for value in list(handoff.get("required_artifact_ids") or [])],
            context_artifact_ids=[str(value) for value in list(handoff.get("context_artifact_ids") or [])],
        )

    def parse_result(
        self,
        *,
        tool_id: str,
        outcome: Any,
        plan: ExecutionPlanDraft,
        artifact_refs: list[dict[str, Any]],
    ) -> ParsedExecutionResult:
        return parse_execution_result(
            tool_id=tool_id,
            raw_result=dict(getattr(outcome, "raw_result", {}) or {}),
            tool_inputs=dict(plan.tool_inputs),
            artifact_refs=artifact_refs,
        )


__all__ = [
    "DefaultHpcExecutionRegistry",
    "compile_hpc_tool_request",
    "parse_execution_result",
]
