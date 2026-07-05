from __future__ import annotations

from typing import Any

from .client import call
from .client import controlled_operation
from .client import supervised_sandbox_mode
from .hpc import HpcWorkspace


_ROUTE_POLICY_IDS = {
    "fpocket": "structure_tools.fpocket.hpc:v1",
}


def _input_refs(*refs: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    stage_refs = [dict(ref) for ref in refs]
    artifact_ids = [
        str(ref.get("artifact_id"))
        for ref in stage_refs
        if ref.get("artifact_id") not in {None, ""}
    ]
    artifact_digests = [
        str(ref.get("artifact_digest"))
        for ref in stage_refs
        if ref.get("artifact_digest") not in {None, ""}
    ]
    return stage_refs, artifact_ids, artifact_digests


def fpocket(
    *,
    structure: dict[str, Any],
    placement: HpcWorkspace,
    expected_outputs: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params_payload = {
        "structure": dict(structure),
        "placement": placement.to_dict(),
        "expected_outputs": list(expected_outputs),
        "params": dict(params or {}),
    }
    if supervised_sandbox_mode():
        stage_refs, input_artifact_ids, input_artifact_digests = _input_refs(structure)
        response = dict(
            controlled_operation(
                sdk_module="structure_tools",
                function_name="fpocket",
                route_policy_id=_ROUTE_POLICY_IDS["fpocket"],
                params=params_payload,
                expected_outputs=list(expected_outputs),
                resource_estimate={"placement": "hpc", "resource_class": "hpc_batch_small"},
                input_artifact_ids=input_artifact_ids,
                input_artifact_digests=input_artifact_digests,
                placement="hpc",
                hpc_workspace_id=placement.hpc_workspace_id,
                stage_refs=stage_refs,
                planned_fetch_intent={"declared_outputs": list(expected_outputs)},
            )
        )
        result = dict(response.get("result_summary") or {})
        if result.get("kind") == "hpc_run_handle":
            return {
                **result,
                "operation_id": response.get("operation_id"),
                "operation_digest": response.get("operation_digest"),
                "adapter_result_envelope": dict(response.get("adapter_result_envelope") or {}),
            }
        return response
    return dict(
        call(
            "structure_tools.fpocket",
            params_payload,
        )
    )


__all__ = ["fpocket"]
