from __future__ import annotations

from typing import Any

from .client import PipelineSdkError
from .client import call
from .client import controlled_operation
from .client import supervised_sandbox_mode
from .hpc import HpcWorkspace


_ROUTE_POLICY_IDS = {
    "cdhit": "bio_tools.cdhit.hpc:v1",
    "mafft": "bio_tools.mafft.hpc:v1",
    "hmmbuild": "bio_tools.hmmbuild.hpc:v1",
    "hmmalign": "bio_tools.hmmalign.hpc:v1",
    "hmmer_search_cli": "bio_tools.hmmer_search_cli.disabled:v1",
}


_HPC_STAGE_REF_REQUIRED_FIELDS = (
    "kind",
    "stage_ref_id",
    "hpc_workspace_id",
    "artifact_id",
    "artifact_digest",
)


def _input_refs(
    function_name: str,
    *refs: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    stage_refs: list[dict[str, Any]] = []
    for input_index, ref in enumerate(refs):
        missing_fields = [
            field
            for field in _HPC_STAGE_REF_REQUIRED_FIELDS
            if not isinstance(ref.get(field), str) or not str(ref[field]).strip()
        ]
        if ref.get("kind") != "hpc_stage_ref" and "kind" not in missing_fields:
            missing_fields.insert(0, "kind")
        if missing_fields:
            raise PipelineSdkError(
                "HPC bio_tools inputs must be the exact object returned by "
                "ws.stage_artifact(...); pass that return value directly and do not "
                "hand-write or reconstruct the input dict.",
                error_code="hpc_stage_ref_required",
                stage="bio_tools.input_validation",
                retryable=False,
                hint=(
                    "Call staged = ws.stage_artifact(artifact_id, workspace_path=...), "
                    f"then pass staged directly to bio_tools.{function_name}(...)."
                ),
                details={
                    "function_name": function_name,
                    "input_index": input_index,
                    "expected_kind": "hpc_stage_ref",
                    "missing_fields": missing_fields,
                },
            )
        stage_refs.append(dict(ref))
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


def _hpc_operation(
    *,
    function_name: str,
    params: dict[str, Any],
    placement: HpcWorkspace,
    expected_outputs: list[dict[str, Any]],
    stage_refs: list[dict[str, Any]],
    input_artifact_ids: list[str],
    input_artifact_digests: list[str],
) -> dict[str, Any]:
    response = dict(
        controlled_operation(
            sdk_module="bio_tools",
            function_name=function_name,
            route_policy_id=_ROUTE_POLICY_IDS[function_name],
            params=params,
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


def cdhit(
    *,
    input_fasta: dict[str, Any],
    placement: HpcWorkspace,
    expected_outputs: list[dict[str, Any]],
    identity: float,
    mode: str = "protein",
) -> dict[str, Any]:
    params = {
        "input_fasta": dict(input_fasta),
        "placement": placement.to_dict(),
        "expected_outputs": list(expected_outputs),
        "identity": identity,
        "mode": mode,
    }
    if supervised_sandbox_mode():
        stage_refs, input_artifact_ids, input_artifact_digests = _input_refs(
            "cdhit", input_fasta
        )
        return _hpc_operation(
            function_name="cdhit",
            params=params,
            placement=placement,
            expected_outputs=expected_outputs,
            stage_refs=stage_refs,
            input_artifact_ids=input_artifact_ids,
            input_artifact_digests=input_artifact_digests,
        )
    return dict(
        call(
            "bio_tools.cdhit",
            params,
        )
    )


def mafft(
    *,
    input_fasta: dict[str, Any],
    placement: HpcWorkspace,
    expected_outputs: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params_payload = {
        "input_fasta": dict(input_fasta),
        "placement": placement.to_dict(),
        "expected_outputs": list(expected_outputs),
        "params": dict(params or {}),
    }
    if supervised_sandbox_mode():
        stage_refs, input_artifact_ids, input_artifact_digests = _input_refs(
            "mafft", input_fasta
        )
        return _hpc_operation(
            function_name="mafft",
            params=params_payload,
            placement=placement,
            expected_outputs=expected_outputs,
            stage_refs=stage_refs,
            input_artifact_ids=input_artifact_ids,
            input_artifact_digests=input_artifact_digests,
        )
    return dict(
        call(
            "bio_tools.mafft",
            params_payload,
        )
    )


def hmmbuild(
    *,
    alignment: dict[str, Any],
    placement: HpcWorkspace,
    expected_outputs: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params_payload = {
        "alignment": dict(alignment),
        "placement": placement.to_dict(),
        "expected_outputs": list(expected_outputs),
        "params": dict(params or {}),
    }
    if supervised_sandbox_mode():
        stage_refs, input_artifact_ids, input_artifact_digests = _input_refs(
            "hmmbuild", alignment
        )
        return _hpc_operation(
            function_name="hmmbuild",
            params=params_payload,
            placement=placement,
            expected_outputs=expected_outputs,
            stage_refs=stage_refs,
            input_artifact_ids=input_artifact_ids,
            input_artifact_digests=input_artifact_digests,
        )
    return dict(
        call(
            "bio_tools.hmmbuild",
            params_payload,
        )
    )


def hmmalign(
    *,
    hmm: dict[str, Any],
    fasta: dict[str, Any],
    placement: HpcWorkspace,
    expected_outputs: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params_payload = {
        "hmm": dict(hmm),
        "fasta": dict(fasta),
        "placement": placement.to_dict(),
        "expected_outputs": list(expected_outputs),
        "params": dict(params or {}),
    }
    if supervised_sandbox_mode():
        stage_refs, input_artifact_ids, input_artifact_digests = _input_refs(
            "hmmalign", hmm, fasta
        )
        return _hpc_operation(
            function_name="hmmalign",
            params=params_payload,
            placement=placement,
            expected_outputs=expected_outputs,
            stage_refs=stage_refs,
            input_artifact_ids=input_artifact_ids,
            input_artifact_digests=input_artifact_digests,
        )
    return dict(
        call(
            "bio_tools.hmmalign",
            params_payload,
        )
    )


def hmmer_search_cli(
    *,
    hmm: dict[str, Any],
    target_fasta: dict[str, Any],
    placement: HpcWorkspace,
    expected_outputs: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params_payload = {
        "hmm": dict(hmm),
        "target_fasta": dict(target_fasta),
        "placement": placement.to_dict(),
        "expected_outputs": list(expected_outputs),
        "params": dict(params or {}),
    }
    if supervised_sandbox_mode():
        stage_refs, input_artifact_ids, input_artifact_digests = _input_refs(
            "hmmer_search_cli", hmm, target_fasta
        )
        return _hpc_operation(
            function_name="hmmer_search_cli",
            params=params_payload,
            placement=placement,
            expected_outputs=expected_outputs,
            stage_refs=stage_refs,
            input_artifact_ids=input_artifact_ids,
            input_artifact_digests=input_artifact_digests,
        )
    return dict(
        call(
            "bio_tools.hmmer_search_cli",
            params_payload,
        )
    )


__all__ = ["cdhit", "hmmalign", "hmmbuild", "hmmer_search_cli", "mafft"]
