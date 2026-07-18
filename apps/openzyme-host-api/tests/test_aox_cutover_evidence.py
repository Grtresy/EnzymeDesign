from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from pathlib import Path

import pytest

from openzyme_host_api.aox_cutover_cli import main as cutover_cli_main
from openzyme_host_api.aox_cutover_evidence import AoxCutoverCampaign
from openzyme_host_api.aox_cutover_evidence import AttemptRunRecord
from openzyme_host_api.aox_cutover_evidence import canonical_digest
from openzyme_host_api.aox_cutover_evidence import canonical_json_bytes
from openzyme_host_api.aox_cutover_evidence import controlled_operation_digest
from openzyme_host_api.aox_cutover_evidence import create_blank_world_roots
from openzyme_host_api.aox_cutover_evidence import CutoverEvidenceError
from openzyme_host_api.aox_cutover_evidence import evaluate_campaign
from openzyme_host_api.aox_cutover_evidence import FAULT_ARTIFACT_BYTE_FLIP_ID
from openzyme_host_api.aox_cutover_evidence import inject_artifact_byte_flip
from openzyme_host_api.aox_cutover_evidence import KNOWN_POSITIVE_PROBE_ID
from openzyme_host_api.aox_cutover_evidence import KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS
from openzyme_host_api.aox_cutover_evidence import KNOWN_POSITIVE_PROBE_SCHEMA_ID
from openzyme_host_api.aox_cutover_evidence import KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS
from openzyme_host_api.aox_cutover_evidence import safe_micu_ledger_snapshot
from openzyme_host_api.aox_cutover_evidence import seal_campaign_decision
from openzyme_host_api.aox_cutover_evidence import seal_attempt_bundle
from openzyme_host_api.aox_cutover_evidence import VerificationResult
from openzyme_host_api.aox_cutover_evidence import verify_attempt_bundle
from openzyme_host_api.aox_cutover_evidence import build_attempt_bundle
from openzyme_pipeline import aox_hmmer
from openzyme_pipeline import aox_motif
from openzyme_pipeline import aox_reference
from openzyme_pipeline import aox_sequence_join
from openzyme_pipeline import aox_similarity
from openzyme_runtime import LiveMicuTokenLedger


REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_ALIGNMENT = (
    REPO_ROOT
    / "packages/openzyme-pipeline/tests/fixtures/aox_motif_rule_score_v1/alignment.fasta"
)
AOX_POST_UNIPROT_FILTER_ID = aox_sequence_join.CONTRACT_ID
AOX_POST_UNIPROT_FILTER_CONTRACT_DIGEST = aox_sequence_join.CONTRACT_DIGEST
AOX_UPSTREAM_EMPTY_MATERIALIZATION_ID = "aox_upstream_empty_materialization@1"
AOX_UPSTREAM_EMPTY_MATERIALIZATION_CONTRACT_DIGEST = canonical_digest(
    {
        "calculation_id": AOX_UPSTREAM_EMPTY_MATERIALIZATION_ID,
        "input_contract_id": aox_hmmer.CONTRACT_ID,
        "reference_accession": aox_motif.REFERENCE_ACCESSION,
        "outputs": [
            "aox_hmm/hits_len650_700_200.csv",
            "aox_hmm/target.fasta",
        ],
    }
)
AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_ID = "aox_reference_only_scoring_alignment@1"
AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_CONTRACT_DIGEST = canonical_digest(
    {
        "calculation_id": AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_ID,
        "reference_accession": aox_motif.REFERENCE_ACCESSION,
        "trigger": "empty_scoring_input_targets",
        "input": "aox_hmm/AOX_scoring_input.fasta",
        "output": "aox_hmm/AOX_scoring_alignment.fasta",
    }
)
AOX_EMPTY_MEMBERSHIP_ID = "canonical_empty_cluster_membership@1"
AOX_EMPTY_MEMBERSHIP_CONTRACT_DIGEST = canonical_digest(
    {
        "calculation_id": AOX_EMPTY_MEMBERSHIP_ID,
        "membership_schema_id": aox_similarity.MEMBERSHIP_SCHEMA_ID,
        "identity_threshold_ppm": aox_similarity.DEFAULT_THRESHOLD_PPM,
        "output": "aox_hmm/AOX_candidates_cdhit85.clusters.csv",
    }
)


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _identity() -> dict[str, str]:
    return {
        "git_commit": "a" * 40,
        "config_digest": _digest("config"),
        "workflow_ref": f"workflow:aox-hmm-live@2.0.0#{_digest('workflow')}",
        "scoring_contract_digest": aox_motif.CONTRACT_DIGEST,
        "scoring_implementation_digest": aox_motif.IMPLEMENTATION_DIGEST,
        "image_digest": _digest("image"),
        "sdk_digest": _digest("sdk"),
    }


def _ledger_snapshot(
    *,
    charged_tokens: int = 10,
    attempt_count: int = 1,
) -> dict[str, object]:
    input_tokens = charged_tokens // 2
    output_tokens = charged_tokens - input_tokens
    grouped_counters = {
        "attempt_count": attempt_count,
        "charged_tokens": charged_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "actual_input_tokens": input_tokens,
        "actual_output_tokens": output_tokens,
        "estimated_input_tokens": 0,
        "estimated_output_tokens": 0,
        "estimated_attempt_count": 0,
        "reservation_overage_tokens": 0,
        "hard_limit_breach_count": 0,
    }
    return {
        "ledger_identity_digest": _digest("persistent-ledger"),
        "hard_limit_tokens": 100_000_000,
        "charged_tokens": charged_tokens,
        "remaining_tokens": 100_000_000 - charged_tokens,
        "hard_limit_overage_tokens": 0,
        "attempt_count": attempt_count,
        "estimated_attempt_count": 0,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "actual_input_tokens": input_tokens,
        "actual_output_tokens": output_tokens,
        "estimated_input_tokens": 0,
        "estimated_output_tokens": 0,
        "reservation_overage_tokens": 0,
        "hard_limit_breach_count": 0,
        "by_scenario": [{"scenario": "aox_blank_world_cutover", **grouped_counters}],
        "by_model": [{"model": "micu-live", **grouped_counters}],
    }


def _write_artifact(root: Path, relative_path: str, content: bytes) -> str:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _refresh_operation_identity(operation: dict[str, object]) -> None:
    operation["canonical_ref_kind"] = "controlled_operation"
    route_policy_id = str(operation.get("route_policy_id") or "pending.route:v1")
    route_name = route_policy_id.partition(":")[0]
    if "." in route_name:
        sdk_module, function_name = route_name.rsplit(".", 1)
    else:
        sdk_module, function_name = "openzyme_pipeline", route_name
    inputs = [dict(item) for item in operation.get("inputs") or []]
    outputs = [dict(item) for item in operation.get("outputs") or []]
    selected_backend = str(operation.get("selected_backend") or "sandbox_sdk")
    source_snapshot_digest = str(
        operation.get("source_snapshot_digest") or _digest("aox-pipeline-source")
    )
    params_digest = canonical_digest(dict(operation.get("parameters") or {}))
    operation["params_digest"] = params_digest
    material = {
        "schema_version": "s12.adapter_envelope.v1",
        "sandbox_workspace_id": str(
            operation.get("sandbox_workspace_id") or "sandbox_workspace_aox"
        ),
        "source_snapshot_digest": source_snapshot_digest,
        "sdk_module": sdk_module,
        "function_name": function_name,
        "params_digest": params_digest,
        "input_artifact_ids": [str(item.get("artifact_id") or "") for item in inputs],
        "input_artifact_digests": [
            str(item.get("content_digest") or "") for item in inputs
        ],
        "placement": "trusted_host_supervised",
        "hpc_workspace_id": (
            str(operation.get("hpc_workspace_id") or "hpc_workspace_aox")
            if selected_backend == "hpc"
            else None
        ),
        "stage_refs": [],
        "selected_backend": selected_backend,
        "route_reason": "workflow_selected_controlled_route",
        "route_policy_id": route_policy_id,
        "runtime_packaging_id": "openzyme_pipeline_sdk@1",
        "toolchain_id": (
            f"{function_name}@test" if selected_backend == "hpc" else None
        ),
        "provider_config_digest": _digest("provider-config"),
        "resource_class": "network" if selected_backend == "provider_http" else "cpu",
        "resource_estimate": {},
        "expected_outputs": {
            "items": [
                {"artifact_id": str(item.get("artifact_id") or "")} for item in outputs
            ]
        },
        "planned_fetch_intent": {},
        "approval_requirement": {"required": True},
    }
    operation["operation_identity_schema"] = "openzyme_controlled_operation_s12@1"
    operation["operation_identity_material"] = material
    operation["operation_identity_digest"] = controlled_operation_digest(material)


def _refresh_sandbox_calculation_identity(operation: dict[str, object]) -> None:
    inputs = [dict(item) for item in operation.get("inputs") or []]
    outputs = [dict(item) for item in operation.get("outputs") or []]
    params_digest = canonical_digest(dict(operation.get("parameters") or {}))
    calculation_id = str(operation.get("kind") or operation["operation_id"])
    source_snapshot_digest = _digest("aox-pipeline-source")
    operation.update(
        {
            "canonical_ref_kind": "sandbox_calculation",
            "route_policy_id": "sandbox.calculation:v1",
            "selected_backend": "sandbox_run",
            "backend_run_id": "sandbox_run_aox",
            "source_snapshot_digest": source_snapshot_digest,
            "params_digest": params_digest,
        }
    )
    calculation_contract_digest = _digest(f"contract:{calculation_id}")
    calculation_implementation_digest = _digest(f"implementation:{calculation_id}")
    if calculation_id == aox_hmmer.CONTRACT_ID:
        calculation_contract_digest = aox_hmmer.CONTRACT_DIGEST
        calculation_implementation_digest = aox_hmmer.IMPLEMENTATION_DIGEST
    elif calculation_id == AOX_POST_UNIPROT_FILTER_ID:
        calculation_contract_digest = AOX_POST_UNIPROT_FILTER_CONTRACT_DIGEST
        calculation_implementation_digest = aox_sequence_join.IMPLEMENTATION_DIGEST
    elif calculation_id == aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID:
        calculation_contract_digest = (
            aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
        )
        calculation_implementation_digest = (
            aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
        )
    elif calculation_id == aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID:
        calculation_contract_digest = (
            aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST
        )
        calculation_implementation_digest = (
            aox_reference.SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
        )
    elif calculation_id == aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID:
        calculation_contract_digest = (
            aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST
        )
        calculation_implementation_digest = (
            aox_reference.SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST
        )
    elif calculation_id == AOX_UPSTREAM_EMPTY_MATERIALIZATION_ID:
        calculation_contract_digest = (
            AOX_UPSTREAM_EMPTY_MATERIALIZATION_CONTRACT_DIGEST
        )
    elif calculation_id == AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_ID:
        calculation_contract_digest = (
            AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_CONTRACT_DIGEST
        )
    elif calculation_id == AOX_EMPTY_MEMBERSHIP_ID:
        calculation_contract_digest = AOX_EMPTY_MEMBERSHIP_CONTRACT_DIGEST
    material = {
        "schema_version": "openzyme_sandbox_calculation_receipt@1",
        "sandbox_run_id": "sandbox_run_aox",
        "sandbox_workspace_id": "sandbox_workspace_aox",
        "source_snapshot_artifact_id": "art_source_snapshot",
        "source_snapshot_digest": source_snapshot_digest,
        "calculation_id": calculation_id,
        "calculation_contract_digest": calculation_contract_digest,
        "calculation_implementation_digest": calculation_implementation_digest,
        "params_digest": params_digest,
        "input_artifact_ids": [str(item["artifact_id"]) for item in inputs],
        "input_artifact_digests": [str(item["content_digest"]) for item in inputs],
        "output_artifact_ids": [str(item["artifact_id"]) for item in outputs],
        "output_artifact_digests": [str(item["content_digest"]) for item in outputs],
    }
    operation["operation_identity_schema"] = "openzyme_sandbox_calculation_receipt@1"
    operation["operation_identity_material"] = material
    operation["operation_identity_digest"] = canonical_digest(material)


def _operation(
    operation_id: str,
    *,
    inputs: list[tuple[str, str]] | None = None,
    outputs: list[tuple[str, str]] | None = None,
    status: str = "completed",
    failure_code: str | None = None,
    scope: str = "formal",
) -> dict[str, object]:
    operation: dict[str, object] = {
        "operation_id": operation_id,
        "kind": operation_id.removeprefix("op_"),
        "scope": scope,
        "status": status,
        "terminal": True,
        "inputs": [
            {"artifact_id": artifact_id, "content_digest": digest}
            for artifact_id, digest in inputs or []
        ],
        "outputs": [
            {"artifact_id": artifact_id, "content_digest": digest}
            for artifact_id, digest in outputs or []
        ],
        "parameters": {},
    }
    if failure_code is not None:
        operation["failure_code"] = failure_code
    _refresh_operation_identity(operation)
    return operation


def _refresh_fixture_operation_identities(evidence: dict[str, object]) -> None:
    refreshed_identities: dict[str, str] = {}
    for operation in evidence["operations"]:
        if operation.get("canonical_ref_kind") == "sandbox_calculation":
            _refresh_sandbox_calculation_identity(operation)
        else:
            _refresh_operation_identity(operation)
        refreshed_identities[operation["operation_id"]] = operation[
            "operation_identity_digest"
        ]
    for approval in evidence["approvals"]:
        approval["operation_identity_digest"] = refreshed_identities[
            approval["operation_id"]
        ]


def _replace_artifact_bytes(
    artifact_root: Path,
    evidence: dict[str, object],
    *,
    artifact_id: str,
    content: bytes,
) -> str:
    artifact = next(
        item
        for item in evidence["artifacts"]
        if item["artifact_id"] == artifact_id
    )
    digest = _write_artifact(
        artifact_root,
        str(artifact["relative_path"]),
        content,
    )
    for operation in evidence["operations"]:
        for direction in ("inputs", "outputs"):
            for ref in operation.get(direction) or []:
                if ref.get("artifact_id") == artifact_id:
                    ref["content_digest"] = digest
    return digest


def _reference_only_alignment() -> bytes:
    alignment = aox_motif.score_aligned_fasta(GOLDEN_ALIGNMENT.read_bytes()).alignment
    reference = next(
        record
        for record in alignment.records
        if record.sequence_id == aox_motif.REFERENCE_ACCESSION
    )
    return f">{reference.sequence_id}\n{reference.sequence}\n".encode("ascii")


def _ncbi_reference_set() -> bytes:
    reference_sequence = _reference_only_alignment().splitlines()[1].decode("ascii")
    records: list[str] = []
    for accession in aox_reference.NCBI_REFERENCE_ACCESSIONS:
        source_id = "pdb|9AVH|A" if accession == "9AVH_A" else accession
        records.append(f">{source_id}\n{reference_sequence}\n")
    return "".join(records).encode("ascii")


def _provider_raw_envelope(
    *,
    provider: str,
    operation: str,
    body: bytes,
) -> tuple[bytes, str]:
    body_digest = _digest_bytes(body)
    envelope = (
        json.dumps(
            {
                "schema_id": "provider_raw_http_response_set@1",
                "provider": provider,
                "operation": operation,
                "responses": [
                    {
                        "ordinal": 1,
                        "phase": "response",
                        "status_code": 200,
                        "headers": {},
                        "body_encoding": "base64",
                        "body_base64": base64.b64encode(body).decode("ascii"),
                        "body_digest": body_digest,
                        "size_bytes": len(body),
                    }
                ],
            },
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        + b"\n"
    )
    return envelope, body_digest


def _known_positive_probe_fixture(
    artifact_root: Path,
) -> dict[str, object]:
    beta_globin = (
        "MVHLTPEEKSAVTALWGKVNVDEVGGEALGRLLVVYPWTQRFFESFGDLSTPDAVMGNPKV"
        "KAHGKKVLGAFSDGLAHLDNLKGTFATLSELHCDKLHVDPENFRLLGNVLVCVLAHHFGK"
        "EFTPPVQAAYQKVVAGVANALAHKYH"
    )
    alpha_globin = (
        "MVLSPADKTNVKAAWGKVGAHAGEYGAEALERMFLSFPTTKTYFPHFDLSHGSAQVKGHG"
        "KKVADALTNAVAHVDDMPNALSALSDLHAHKLRVDPVNFKLLSHCLLVTLAAHLPAEFTP"
        "AVHASLDKFLASVSTVLTSKYR"
    )
    ncbi_fasta = (
        f">{KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS[0]}\n{beta_globin}\n"
        f">{KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS[1]}\n{alpha_globin}\n"
    ).encode("ascii")
    uniprot_fasta = (
        f">{KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS[0]}\n{beta_globin}\n"
        f">{KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS[1]}\n{alpha_globin}\n"
    ).encode("ascii")
    ncbi_raw, ncbi_response_digest = _provider_raw_envelope(
        provider="ncbi",
        operation="bio.ncbi_fetch_proteins",
        body=ncbi_fasta,
    )
    uniprot_body = canonical_json_bytes(
        {
            "results": [
                {
                    "primaryAccession": accession,
                    "sequence": {"value": sequence},
                }
                for accession, sequence in zip(
                    KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS,
                    (beta_globin, alpha_globin),
                    strict=True,
                )
            ]
        }
    ) + b"\n"
    uniprot_raw, uniprot_response_digest = _provider_raw_envelope(
        provider="uniprot",
        operation="bio.uniprot_fetch",
        body=uniprot_body,
    )
    mafft_alignment = ncbi_fasta
    hmm_model = b"HMMER3/f [globin-known-positive]\nNAME globin_probe\n//\n"
    clustered_fasta = uniprot_fasta
    membership = (
        "cluster_id,member_id,representative_id,is_representative,"
        "identity_to_representative,member_length\n"
        f"cluster_0,{KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS[0]},"
        f"{KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS[0]},true,1.000000,"
        f"{len(beta_globin)}\n"
        f"cluster_1,{KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS[1]},"
        f"{KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS[1]},true,1.000000,"
        f"{len(alpha_globin)}\n"
    ).encode("ascii")
    hmmalign_alignment = uniprot_fasta
    source_snapshot = canonical_json_bytes(
        {
            "schema_id": "sandbox_source_snapshot@1",
            "package": "openzyme_pipeline",
            "purpose": "independent_globin_provider_hpc_probe",
        }
    ) + b"\n"

    contents = {
        "art_probe_source_snapshot": (
            "probe/source/openzyme-pipeline-snapshot.json",
            source_snapshot,
        ),
        "art_probe_ncbi_raw": ("probe/provider/ncbi-raw.json", ncbi_raw),
        "art_probe_ncbi_fasta": ("probe/provider/ncbi-globins.fasta", ncbi_fasta),
        "art_probe_mafft_alignment": (
            "probe/toolchain/ncbi-globins-aligned.fasta",
            mafft_alignment,
        ),
        "art_probe_hmm_model": ("probe/toolchain/globin.hmm", hmm_model),
        "art_probe_uniprot_raw": ("probe/provider/uniprot-raw.json", uniprot_raw),
        "art_probe_uniprot_fasta": (
            "probe/provider/uniprot-globins.fasta",
            uniprot_fasta,
        ),
        "art_probe_cdhit_fasta": (
            "probe/toolchain/uniprot-globins-clustered.fasta",
            clustered_fasta,
        ),
        "art_probe_cdhit_membership": (
            "probe/toolchain/uniprot-globins-clusters.csv",
            membership,
        ),
        "art_probe_hmmalign_alignment": (
            "probe/toolchain/uniprot-globins-aligned.fasta",
            hmmalign_alignment,
        ),
    }
    digests = {
        artifact_id: _write_artifact(artifact_root, relative_path, content)
        for artifact_id, (relative_path, content) in contents.items()
    }
    session_id = "sess_probe_globin"
    task_id = "task_probe_globin"
    sandbox_run_id = "sandbox_run_probe_globin"
    sandbox_workspace_id = "sandbox_workspace_probe_globin"
    hpc_workspace_id = "hpc_workspace_probe_globin"
    source_snapshot_digest = _digest("probe-source-tree")
    source_snapshot_artifact_digest = digests["art_probe_source_snapshot"]
    provenance = {
        "art_probe_source_snapshot": {
            "producer": "sandbox_source_snapshot",
            "sandbox_run_id": sandbox_run_id,
            "source_snapshot_digest": source_snapshot_digest,
        },
        "art_probe_ncbi_raw": {"provider": "ncbi", "provider_artifact_kind": "provider_raw"},
        "art_probe_ncbi_fasta": {"provider": "ncbi", "provider_artifact_kind": "provider_parsed"},
        "art_probe_mafft_alignment": {"tool": "mafft"},
        "art_probe_hmm_model": {"tool": "hmmbuild"},
        "art_probe_uniprot_raw": {"provider": "uniprot", "provider_artifact_kind": "provider_raw"},
        "art_probe_uniprot_fasta": {"provider": "uniprot", "provider_artifact_kind": "provider_parsed"},
        "art_probe_cdhit_fasta": {"tool": "cd-hit"},
        "art_probe_cdhit_membership": {"tool": "cd-hit"},
        "art_probe_hmmalign_alignment": {"tool": "hmmalign"},
    }
    artifact_kind = {
        "art_probe_source_snapshot": "source_snapshot",
        "art_probe_ncbi_raw": "provider_evidence",
        "art_probe_ncbi_fasta": "sequence",
        "art_probe_mafft_alignment": "sequence",
        "art_probe_hmm_model": "model",
        "art_probe_uniprot_raw": "provider_evidence",
        "art_probe_uniprot_fasta": "sequence",
        "art_probe_cdhit_fasta": "sequence",
        "art_probe_cdhit_membership": "result",
        "art_probe_hmmalign_alignment": "sequence",
    }
    artifacts = [
        {
            "artifact_id": artifact_id,
            "relative_path": relative_path,
            "scope": "probe",
            "origin": (
                "sandbox_run"
                if artifact_id == "art_probe_source_snapshot"
                else "operation"
            ),
            "kind": artifact_kind[artifact_id],
            "provenance": {
                "probe_id": KNOWN_POSITIVE_PROBE_ID,
                **provenance[artifact_id],
            },
        }
        for artifact_id, (relative_path, _) in contents.items()
    ]

    def probe_operation(
        operation_id: str,
        *,
        inputs: list[tuple[str, str]] | None = None,
        outputs: list[tuple[str, str]],
        parameters: dict[str, object] | None = None,
        route_policy_id: str,
        selected_backend: str,
        backend_run_id: str,
    ) -> dict[str, object]:
        operation = _operation(
            operation_id,
            inputs=inputs,
            outputs=outputs,
            scope="probe",
        )
        operation.update(
            {
                "session_id": session_id,
                "task_id": task_id,
                "sandbox_run_id": sandbox_run_id,
                "sandbox_workspace_id": sandbox_workspace_id,
                "source_snapshot_artifact_id": "art_probe_source_snapshot",
                "source_snapshot_digest": source_snapshot_digest,
                "hpc_workspace_id": (
                    hpc_workspace_id if selected_backend == "hpc" else None
                ),
                "parameters": dict(parameters or {}),
                "route_policy_id": route_policy_id,
                "selected_backend": selected_backend,
                "backend_run_id": backend_run_id,
            }
        )
        _refresh_operation_identity(operation)
        return operation

    operations = [
        probe_operation(
            "op_probe_ncbi",
            outputs=[
                ("art_probe_ncbi_raw", digests["art_probe_ncbi_raw"]),
                ("art_probe_ncbi_fasta", digests["art_probe_ncbi_fasta"]),
            ],
            parameters={"accessions": list(KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS)},
            route_policy_id="bio.ncbi_fetch_proteins.provider:v1",
            selected_backend="provider_http",
            backend_run_id="invocation_probe_ncbi",
        ),
        probe_operation(
            "op_probe_mafft",
            inputs=[("art_probe_ncbi_fasta", digests["art_probe_ncbi_fasta"])],
            outputs=[
                (
                    "art_probe_mafft_alignment",
                    digests["art_probe_mafft_alignment"],
                )
            ],
            route_policy_id="bio_tools.mafft.hpc:v1",
            selected_backend="hpc",
            backend_run_id="job_probe_mafft",
        ),
        probe_operation(
            "op_probe_hmmbuild",
            inputs=[
                (
                    "art_probe_mafft_alignment",
                    digests["art_probe_mafft_alignment"],
                )
            ],
            outputs=[("art_probe_hmm_model", digests["art_probe_hmm_model"])],
            route_policy_id="bio_tools.hmmbuild.hpc:v1",
            selected_backend="hpc",
            backend_run_id="job_probe_hmmbuild",
        ),
        probe_operation(
            "op_probe_uniprot",
            outputs=[
                ("art_probe_uniprot_raw", digests["art_probe_uniprot_raw"]),
                ("art_probe_uniprot_fasta", digests["art_probe_uniprot_fasta"]),
            ],
            parameters={
                "accessions": list(KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS)
            },
            route_policy_id="bio.uniprot_fetch.provider:v1",
            selected_backend="provider_http",
            backend_run_id="invocation_probe_uniprot",
        ),
        probe_operation(
            "op_probe_cdhit",
            inputs=[
                ("art_probe_uniprot_fasta", digests["art_probe_uniprot_fasta"])
            ],
            outputs=[
                ("art_probe_cdhit_fasta", digests["art_probe_cdhit_fasta"]),
                (
                    "art_probe_cdhit_membership",
                    digests["art_probe_cdhit_membership"],
                ),
            ],
            parameters={"identity": 1.0, "mode": "protein"},
            route_policy_id="bio_tools.cdhit.hpc:v1",
            selected_backend="hpc",
            backend_run_id="job_probe_cdhit",
        ),
        probe_operation(
            "op_probe_hmmalign",
            inputs=[
                ("art_probe_hmm_model", digests["art_probe_hmm_model"]),
                ("art_probe_cdhit_fasta", digests["art_probe_cdhit_fasta"]),
            ],
            outputs=[
                (
                    "art_probe_hmmalign_alignment",
                    digests["art_probe_hmmalign_alignment"],
                )
            ],
            route_policy_id="bio_tools.hmmalign.hpc:v1",
            selected_backend="hpc",
            backend_run_id="job_probe_hmmalign",
        ),
    ]
    operation_by_id = {
        operation["operation_id"]: operation for operation in operations
    }
    provider_receipts = [
        {
            "provider_record_id": "provider_record_probe_ncbi",
            "provider": "ncbi",
            "status": "completed",
            "invocation_id": "invocation_probe_ncbi",
            "operation_id": "op_probe_ncbi",
            "cache_hit": False,
            "request_digest": operation_by_id["op_probe_ncbi"]["params_digest"],
            "response_digest": ncbi_response_digest,
            "artifact_ids": ["art_probe_ncbi_raw", "art_probe_ncbi_fasta"],
            "raw_response_artifact_id": "art_probe_ncbi_raw",
            "parsed_fasta_artifact_id": "art_probe_ncbi_fasta",
        },
        {
            "provider_record_id": "provider_record_probe_uniprot",
            "provider": "uniprot",
            "status": "completed",
            "invocation_id": "invocation_probe_uniprot",
            "operation_id": "op_probe_uniprot",
            "cache_hit": False,
            "request_digest": operation_by_id["op_probe_uniprot"]["params_digest"],
            "response_digest": uniprot_response_digest,
            "artifact_ids": ["art_probe_uniprot_raw", "art_probe_uniprot_fasta"],
            "raw_response_artifact_id": "art_probe_uniprot_raw",
            "parsed_fasta_artifact_id": "art_probe_uniprot_fasta",
        },
    ]
    toolchain_receipts = [
        {
            "toolchain_record_id": "toolchain_record_probe_mafft",
            "toolchain_id": "mafft@7.526",
            "tool": "mafft",
            "operation_id": "op_probe_mafft",
            "job_id": "job_probe_mafft",
            "image_digest": _digest("probe-mafft-image"),
            "status": "completed",
            "artifact_ids": ["art_probe_mafft_alignment"],
        },
        {
            "toolchain_record_id": "toolchain_record_probe_hmmbuild",
            "toolchain_id": "hmmbuild@3.4",
            "tool": "hmmbuild",
            "operation_id": "op_probe_hmmbuild",
            "job_id": "job_probe_hmmbuild",
            "image_digest": _digest("probe-hmmbuild-image"),
            "status": "completed",
            "artifact_ids": ["art_probe_hmm_model"],
        },
        {
            "toolchain_record_id": "toolchain_record_probe_cdhit",
            "toolchain_id": "cd-hit@4.8.1",
            "tool": "cd-hit",
            "operation_id": "op_probe_cdhit",
            "job_id": "job_probe_cdhit",
            "image_digest": _digest("probe-cdhit-image"),
            "status": "completed",
            "artifact_ids": [
                "art_probe_cdhit_fasta",
                "art_probe_cdhit_membership",
            ],
            "parameters": {"identity": 1.0, "mode": "protein"},
        },
        {
            "toolchain_record_id": "toolchain_record_probe_hmmalign",
            "toolchain_id": "hmmalign@3.4",
            "tool": "hmmalign",
            "operation_id": "op_probe_hmmalign",
            "job_id": "job_probe_hmmalign",
            "image_digest": _digest("probe-hmmalign-image"),
            "status": "completed",
            "artifact_ids": ["art_probe_hmmalign_alignment"],
        },
    ]
    provider_by_name = {
        receipt["provider"]: receipt for receipt in provider_receipts
    }
    toolchain_by_tool = {
        receipt["tool"]: receipt for receipt in toolchain_receipts
    }
    artifact_roles = {
        "source_snapshot": "art_probe_source_snapshot",
        "ncbi_raw_response": "art_probe_ncbi_raw",
        "ncbi_fasta": "art_probe_ncbi_fasta",
        "mafft_alignment": "art_probe_mafft_alignment",
        "hmm_model": "art_probe_hmm_model",
        "uniprot_raw_response": "art_probe_uniprot_raw",
        "uniprot_fasta": "art_probe_uniprot_fasta",
        "cdhit_clustered_fasta": "art_probe_cdhit_fasta",
        "cdhit_membership": "art_probe_cdhit_membership",
        "hmmalign_alignment": "art_probe_hmmalign_alignment",
    }
    operation_roles = {
        "ncbi_fetch": "op_probe_ncbi",
        "reference_alignment": "op_probe_mafft",
        "hmm_build": "op_probe_hmmbuild",
        "uniprot_fetch": "op_probe_uniprot",
        "candidate_cluster": "op_probe_cdhit",
        "candidate_alignment": "op_probe_hmmalign",
    }
    sequence_digests = sorted(
        (
            _digest_bytes(beta_globin.encode("ascii")),
            _digest_bytes(alpha_globin.encode("ascii")),
        )
    )
    probe = {
        "schema_id": KNOWN_POSITIVE_PROBE_SCHEMA_ID,
        "probe_id": KNOWN_POSITIVE_PROBE_ID,
        "status": "passed",
        "bounded": True,
        "formal_data_isolated": True,
        "artifact_ids": list(contents),
        "operation_roles": operation_roles,
        "artifact_roles": artifact_roles,
        "isolation": {
            "schema_id": "aox_known_positive_probe_isolation@1",
            "session_id": session_id,
            "task_id": task_id,
            "task_finish_ref": "doc_probe_task_finish",
            "sandbox_run_id": sandbox_run_id,
            "sandbox_workspace_id": sandbox_workspace_id,
            "source_snapshot_artifact_id": "art_probe_source_snapshot",
            "source_snapshot_digest": source_snapshot_digest,
            "source_snapshot_artifact_digest": source_snapshot_artifact_digest,
            "hpc_workspace_id": hpc_workspace_id,
            "controlled_operation_count": 6,
        },
        "known_positive_identity": {
            "ncbi_accessions": list(KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS),
            "uniprot_accessions": list(KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS),
            "cross_provider_sequence_digest": canonical_digest(sequence_digests),
        },
        "checks": [
            {
                "check_id": "ncbi_globin_pair",
                "category": "provider",
                "status": "passed",
                "receipt_id": provider_by_name["ncbi"]["provider_record_id"],
            },
            {
                "check_id": "uniprot_globin_pair",
                "category": "provider",
                "status": "passed",
                "receipt_id": provider_by_name["uniprot"]["provider_record_id"],
            },
            *(
                {
                    "check_id": f"hpc_{tool_name.replace('-', '')}",
                    "category": "hpc",
                    "status": "passed",
                    "receipt_id": toolchain_by_tool[tool_name][
                        "toolchain_record_id"
                    ],
                }
                for tool_name in ("mafft", "hmmbuild", "cd-hit", "hmmalign")
            ),
        ],
        "provider_receipts": provider_receipts,
        "toolchain_receipts": toolchain_receipts,
    }
    approvals = [
        {
            "approval_id": f"approval_{operation['operation_id']}",
            "operation_id": operation["operation_id"],
            "operation_identity_digest": operation["operation_identity_digest"],
            "decision": "approved",
        }
        for operation in operations
    ]
    return {
        "artifacts": artifacts,
        "operations": operations,
        "approvals": approvals,
        "probe": probe,
    }


def _apply_hmmer_upstream_empty_fixture(
    artifact_root: Path,
    evidence: dict[str, object],
) -> None:
    reason = "no_hmmer_hits"
    empty_hmmer_body = (
        json.dumps(
            {"database": "refprot", "hits": []},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    raw_page_digest = _digest_bytes(empty_hmmer_body)
    empty_hmmer_envelope = (
        json.dumps(
            {
                "schema_id": "provider_raw_http_response_set@1",
                "provider": "ebi_hmmer",
                "operation": "bio.hmmer_search",
                "responses": [
                    {
                        "ordinal": 1,
                        "phase": "results",
                        "status_code": 200,
                        "headers": {},
                        "body_encoding": "base64",
                        "body_base64": base64.b64encode(empty_hmmer_body).decode(
                            "ascii"
                        ),
                        "body_digest": raw_page_digest,
                        "size_bytes": len(empty_hmmer_body),
                    }
                ],
            },
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        + b"\n"
    )
    parsed_output = io.StringIO(newline="")
    parsed_writer = csv.DictWriter(
        parsed_output,
        fieldnames=list(aox_hmmer.INPUT_COLUMNS),
        lineterminator="\n",
    )
    parsed_writer.writeheader()
    parsed_bytes = parsed_output.getvalue().encode("utf-8")
    score_filter_result = aox_hmmer.parse_and_filter_csv(parsed_bytes)
    score_filtered_bytes = score_filter_result.to_csv().encode("utf-8")
    post_uniprot_filtered_bytes = (
        ",".join(aox_sequence_join.OUTPUT_COLUMNS) + "\n"
    ).encode("utf-8")
    target_bytes = b""
    scoring_reference_artifact = next(
        artifact
        for artifact in evidence["artifacts"]
        if artifact["artifact_id"] == "art_scoring_reference"
    )
    scoring_reference_bytes = (
        artifact_root / str(scoring_reference_artifact["relative_path"])
    ).read_bytes()
    scoring_input_result = aox_reference.assemble_scoring_input(
        scoring_reference_bytes,
        target_bytes,
        expected_scoring_reference_input_digest=_digest_bytes(
            scoring_reference_bytes
        ),
        expected_target_input_digest=_digest_bytes(target_bytes),
    )
    scoring_input_bytes = scoring_input_result.to_fasta().encode("utf-8")
    scoring_result = aox_motif.score_aligned_fasta(scoring_reference_bytes)
    scored_bytes = scoring_result.to_csv().encode("utf-8")
    candidate_bytes = b""
    membership_bytes = (
        ",".join(aox_similarity.MEMBERSHIP_COLUMNS) + "\n"
    ).encode("utf-8")
    graph = aox_similarity.build_similarity_graph(
        candidate_bytes,
        membership_bytes,
        threshold_ppm=750_000,
        empty_result_reason=reason,
    )

    scoring_input_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_scoring_input",
        content=scoring_input_bytes,
    )
    hmmer_response_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_ebi_hmmer_response",
        content=empty_hmmer_envelope,
    )
    parsed_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_hmmer_parsed_hits",
        content=parsed_bytes,
    )
    score_filtered_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_hmmer_score_filtered_accessions",
        content=score_filtered_bytes,
    )
    post_uniprot_filtered_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_post_uniprot_filtered_hits",
        content=post_uniprot_filtered_bytes,
    )
    target_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_target_sequences",
        content=target_bytes,
    )
    scoring_alignment_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_alignment",
        content=scoring_reference_bytes,
    )
    scored_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_scores",
        content=scored_bytes,
    )
    candidate_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_candidates",
        content=candidate_bytes,
    )
    membership_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_membership",
        content=membership_bytes,
    )
    nodes_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_nodes",
        content=graph.nodes_csv().encode("utf-8"),
    )
    edges_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_edges",
        content=graph.edges_csv().encode("utf-8"),
    )
    manifest_digest = _replace_artifact_bytes(
        artifact_root,
        evidence,
        artifact_id="art_graph_manifest",
        content=graph.manifest_json().encode("utf-8"),
    )

    omitted_operation_ids = {
        "op_uniprot",
        "op_post_uniprot_filter",
        "op_hmmalign",
        "op_cdhit",
    }
    evidence["operations"] = [
        operation
        for operation in evidence["operations"]
        if operation["operation_id"] not in omitted_operation_ids
    ]
    upstream_materialization = _operation(
        "op_upstream_empty_materialization",
        inputs=[("art_hmmer_score_filtered_accessions", score_filtered_digest)],
        outputs=[
            ("art_post_uniprot_filtered_hits", post_uniprot_filtered_digest),
            ("art_target_sequences", target_digest),
        ],
    )
    upstream_materialization["kind"] = AOX_UPSTREAM_EMPTY_MATERIALIZATION_ID
    upstream_materialization["parameters"] = {
        "reason": reason,
        "reference_accession": aox_motif.REFERENCE_ACCESSION,
    }
    _refresh_sandbox_calculation_identity(upstream_materialization)
    empty_target_scoring = _operation(
        "op_empty_target_scoring",
        inputs=[
            ("art_scoring_input", scoring_input_digest),
            ("art_target_sequences", target_digest),
        ],
        outputs=[("art_alignment", scoring_alignment_digest)],
    )
    empty_target_scoring["kind"] = AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_ID
    empty_target_scoring["parameters"] = {
        "reason": reason,
        "reference_accession": aox_motif.REFERENCE_ACCESSION,
    }
    _refresh_sandbox_calculation_identity(empty_target_scoring)
    empty_membership = _operation(
        "op_empty_membership",
        inputs=[("art_candidates", candidate_digest)],
        outputs=[("art_membership", membership_digest)],
    )
    empty_membership["kind"] = AOX_EMPTY_MEMBERSHIP_ID
    empty_membership["parameters"] = {"identity_threshold_ppm": 750_000}
    _refresh_sandbox_calculation_identity(empty_membership)
    evidence["operations"].extend(
        [upstream_materialization, empty_target_scoring, empty_membership]
    )

    operation_by_id = {
        operation["operation_id"]: operation for operation in evidence["operations"]
    }
    operation_by_id["op_scoring_input_assembly"]["parameters"] = {
        "reference_accession": aox_reference.SCORING_REFERENCE_ACCESSION,
        "target_count": 0,
    }
    operation_by_id["op_score"]["inputs"] = [
        {
            "artifact_id": "art_alignment",
            "content_digest": scoring_alignment_digest,
        }
    ]
    operation_by_id["op_score"]["outputs"] = [
        {"artifact_id": "art_scores", "content_digest": scored_digest}
    ]
    operation_by_id["op_candidate_filter"]["inputs"] = [
        {"artifact_id": "art_scores", "content_digest": scored_digest},
        {"artifact_id": "art_target_sequences", "content_digest": target_digest},
    ]
    operation_by_id["op_candidate_filter"]["outputs"] = [
        {"artifact_id": "art_candidates", "content_digest": candidate_digest}
    ]
    operation_by_id["op_similarity"]["inputs"] = [
        {"artifact_id": "art_candidates", "content_digest": candidate_digest},
        {"artifact_id": "art_membership", "content_digest": membership_digest},
    ]
    operation_by_id["op_similarity"]["outputs"] = [
        {"artifact_id": "art_nodes", "content_digest": nodes_digest},
        {"artifact_id": "art_edges", "content_digest": edges_digest},
        {"artifact_id": "art_graph_manifest", "content_digest": manifest_digest},
    ]

    removed_artifact_ids = {"art_uniprot_candidates", "art_uniprot_metadata"}
    evidence["artifacts"] = [
        artifact
        for artifact in evidence["artifacts"]
        if artifact["artifact_id"] not in removed_artifact_ids
    ]
    artifact_by_id = {
        artifact["artifact_id"]: artifact for artifact in evidence["artifacts"]
    }
    artifact_by_id["art_alignment"]["provenance"] = {
        "operation_id": "op_empty_target_scoring",
        "calculation_id": AOX_REFERENCE_ONLY_SCORING_ALIGNMENT_ID,
    }
    for artifact_id in ("art_post_uniprot_filtered_hits", "art_target_sequences"):
        artifact_by_id[artifact_id]["provenance"] = {
            "operation_id": "op_upstream_empty_materialization",
            "calculation_id": AOX_UPSTREAM_EMPTY_MATERIALIZATION_ID,
        }
    artifact_by_id["art_membership"]["provenance"] = {
        "operation_id": "op_empty_membership",
        "schema_id": aox_similarity.MEMBERSHIP_SCHEMA_ID,
    }

    provider_by_name = {
        provider["provider"]: provider for provider in evidence["provider_identities"]
    }
    provider_by_name["ebi_hmmer"]["response_digest"] = raw_page_digest
    dependency = {
        "upstream_provider_record_id": "provider_record_ebi_hmmer",
        "downstream_provider_record_id": "provider_record_uniprot_upstream_empty",
        "derivation_id": aox_hmmer.CONTRACT_ID,
        "upstream_response_artifact_ids": ["art_ebi_hmmer_response"],
        "derivation_operation_id": "op_pre_uniprot_score_filter",
        "parsed_hit_artifact_id": "art_hmmer_parsed_hits",
        "parsed_hit_artifact_digest": parsed_digest,
        "derived_accession_artifact_id": (
            "art_hmmer_score_filtered_accessions"
        ),
        "derived_accession_artifact_digest": score_filtered_digest,
        "derivation_contract_digest": aox_hmmer.CONTRACT_DIGEST,
        "derivation_implementation_digest": aox_hmmer.IMPLEMENTATION_DIGEST,
        "derived_accessions": [],
        "derived_accessions_digest": canonical_digest([]),
        "terminal_empty_reason": reason,
    }
    decision_material = {
        "reason": reason,
        "upstream_provider_record_id": dependency["upstream_provider_record_id"],
        "derivation_operation_id": dependency["derivation_operation_id"],
        "derived_accession_artifact_id": dependency[
            "derived_accession_artifact_id"
        ],
        "derived_accession_artifact_digest": dependency[
            "derived_accession_artifact_digest"
        ],
        "derived_accessions_digest": dependency["derived_accessions_digest"],
    }
    skip_payload = {
        "schema_id": "provider_upstream_empty_receipt@1",
        "provider_record_id": "provider_record_uniprot_upstream_empty",
        "provider": "uniprot",
        "status": "upstream_empty",
        "canonical_ref_kind": "upstream_empty",
        "operation_id": None,
        "invocation_id": None,
        "provider_io_performed": False,
        "cache_consulted": False,
        **decision_material,
        "decision_input_digest": canonical_digest(decision_material),
    }
    skip_payload["skip_receipt_digest"] = canonical_digest(skip_payload)
    _write_artifact(
        artifact_root,
        "formal/provider/uniprot-upstream-empty.json",
        canonical_json_bytes(skip_payload) + b"\n",
    )
    skip_artifact = {
        "artifact_id": "art_uniprot_upstream_empty",
        "relative_path": "formal/provider/uniprot-upstream-empty.json",
        "scope": "formal",
        "origin": "attestation",
        "kind": "provider_receipt",
        "provenance": {
            "provider_record_id": "provider_record_uniprot_upstream_empty",
            "upstream_provider_record_id": "provider_record_ebi_hmmer",
            "derivation_operation_id": "op_pre_uniprot_score_filter",
            "skip_receipt_digest": skip_payload["skip_receipt_digest"],
        },
    }
    evidence["artifacts"].append(skip_artifact)
    skipped_uniprot_provider = {
        "provider_record_id": "provider_record_uniprot_upstream_empty",
        "provider": "uniprot",
        "status": "upstream_empty",
        "canonical_ref_kind": "upstream_empty",
        "invocation_id": None,
        "operation_id": None,
        "cache_hit": False,
        "request_digest": None,
        "response_digest": None,
        "artifact_ids": ["art_uniprot_upstream_empty"],
        "source_ref_ids": [],
        "reason": reason,
        "skip_receipt_digest": skip_payload["skip_receipt_digest"],
        "provider_io_performed": False,
        "cache_consulted": False,
    }
    evidence["provider_identities"] = [
        skipped_uniprot_provider if provider["provider"] == "uniprot" else provider
        for provider in evidence["provider_identities"]
    ]
    dependency.update(
        {
            "skip_receipt_digest": skip_payload["skip_receipt_digest"],
            "skip_artifact_id": "art_uniprot_upstream_empty",
        }
    )

    evidence["toolchain_identities"] = [
        toolchain
        for toolchain in evidence["toolchain_identities"]
        if toolchain["tool"] in {"mafft", "hmmbuild"}
    ]
    evidence["report"]["artifact_ids"] = [
        artifact_id
        for artifact_id in evidence["report"]["artifact_ids"]
        if artifact_id not in removed_artifact_ids
    ]
    scientific_checks = evidence["scientific_checks"]
    scientific_checks.pop("sequence_join")
    scientific_checks["scoring"].update(
        {
            "alignment_artifact_id": "art_alignment",
            "scored_artifact_id": "art_scores",
            "input_digest": scoring_result.alignment.input_digest,
        }
    )
    scientific_checks["similarity"].update(
        {
            "empty_result_reason": reason,
            "candidate_fasta_digest": graph.sequences.input_digest,
            "membership_digest": graph.membership.input_digest,
        }
    )
    scientific_checks["aox_chain"] = {
        "literature_provider_record_id": "provider_record_pubmed",
        "operation_roles": {
            "ncbi_fetch": "op_ncbi",
            "hmm_reference_set_selection": "op_hmm_reference_set_selection",
            "scoring_reference_selection": "op_scoring_reference_selection",
            "reference_alignment": "op_align",
            "hmm_build": "op_hmmbuild",
            "hmmer_search": "op_ebi_hmmer",
            "pre_uniprot_score_filter": "op_pre_uniprot_score_filter",
            "scoring_input_assembly": "op_scoring_input_assembly",
            "upstream_empty_materialization": (
                "op_upstream_empty_materialization"
            ),
            "empty_target_scoring_materialization": "op_empty_target_scoring",
            "motif_score": "op_score",
            "candidate_filter": "op_candidate_filter",
            "empty_membership": "op_empty_membership",
            "similarity": "op_similarity",
        },
        "provider_dependencies": [dependency],
        "artifact_roles": {
            "literature_evidence": "art_pubmed_response",
            "ncbi_provider_sequences": "art_ncbi_provider_sequences",
            "hmm_reference_set": "art_hmm_reference_set",
            "scoring_reference": "art_scoring_reference",
            "scoring_input": "art_scoring_input",
            "reference_alignment": "art_reference_alignment",
            "hmm_model": "art_hmm_model",
            "hmmer_response": "art_ebi_hmmer_response",
            "hmmer_parsed_hits": "art_hmmer_parsed_hits",
            "hmmer_score_filtered_accessions": (
                "art_hmmer_score_filtered_accessions"
            ),
            "post_uniprot_filtered_hits": "art_post_uniprot_filtered_hits",
            "target_sequences": "art_target_sequences",
            "scoring_alignment": "art_alignment",
            "motif_scores": "art_scores",
            "candidates": "art_candidates",
            "cdhit_membership": "art_membership",
            "graph_nodes": "art_nodes",
            "graph_edges": "art_edges",
            "graph_manifest": "art_graph_manifest",
        },
        "excluded_scoring_sequence_ids": [aox_motif.REFERENCE_ACCESSION],
        "empty_branch": {
            "schema_id": "aox_empty_branch@1",
            "stage": "pre_uniprot_score_filter",
            "reason": reason,
            "trigger_artifact_id": "art_hmmer_score_filtered_accessions",
            "trigger_artifact_digest": score_filtered_digest,
            "observed_count_before": 0,
            "observed_count_after": 0,
            "derivation_operation_id": "op_pre_uniprot_score_filter",
            "skip_provider_record_id": "provider_record_uniprot_upstream_empty",
            "omitted_controlled_roles": [
                "uniprot_fetch",
                "candidate_alignment",
                "cdhit",
            ],
            "empty_materialization_operation_id": (
                "op_upstream_empty_materialization"
            ),
            "empty_membership_operation_id": "op_empty_membership",
        },
    }
    evidence["scientific_outcome"] = {
        "status": "empty",
        "candidate_count": 0,
        "empty_result_reason": reason,
        "cutover_eligible": True,
    }

    operation_by_id["op_ebi_hmmer"]["outputs"] = [
        {
            "artifact_id": "art_ebi_hmmer_response",
            "content_digest": hmmer_response_digest,
        },
        {"artifact_id": "art_hmmer_parsed_hits", "content_digest": parsed_digest},
    ]
    operation_by_id["op_pre_uniprot_score_filter"]["inputs"] = [
        {"artifact_id": "art_hmmer_parsed_hits", "content_digest": parsed_digest}
    ]
    operation_by_id["op_pre_uniprot_score_filter"]["outputs"] = [
        {
            "artifact_id": "art_hmmer_score_filtered_accessions",
            "content_digest": score_filtered_digest,
        }
    ]
    _refresh_fixture_operation_identities(evidence)


def _valid_evidence(
    artifact_root: Path,
    *,
    attempt_kind: str,
    clean_world: dict[str, object],
    run_suffix: str | None = None,
    scientific_branch: str = "nonempty",
) -> dict[str, object]:
    alignment_bytes = GOLDEN_ALIGNMENT.read_bytes()
    scoring_result = aox_motif.score_aligned_fasta(alignment_bytes)
    scored_bytes = scoring_result.to_csv().encode("utf-8")
    aligned_records = {
        record.sequence_id: record.sequence
        for record in scoring_result.alignment.records
    }
    normalized_hit_sequences = {
        sequence_id.strip().upper(): sequence.replace("-", "").replace(".", "")
        for sequence_id, sequence in aligned_records.items()
        if sequence_id != aox_motif.REFERENCE_ACCESSION
    }
    hit_ids = sorted(normalized_hit_sequences)
    accession_by_hit_id = dict(zip(hit_ids, ("K3VE05", "Q9XYZ1"), strict=True))
    hit_id_by_accession = {
        accession: hit_id for hit_id, accession in accession_by_hit_id.items()
    }
    candidate_ids = [
        row.sequence_id
        for row in scoring_result.rows
        if row.passes_motif_rule and row.sequence_id != aox_motif.REFERENCE_ACCESSION
    ]
    report_bytes = (
        b"# AOX/HMM report\n\nThe formula-derived motif result is reproducible.\n"
        if attempt_kind == "positive"
        else b"# AOX/HMM fault evidence\n\nThe required-chain byte fault failed closed.\n"
    )
    probe_fixture = _known_positive_probe_fixture(artifact_root)
    pubmed_request_digest = _digest("pubmed-request")
    pubmed_response_digest = _digest("pubmed-provider-response")
    pubmed_bytes = (
        canonical_json_bytes(
            {
                "schema_id": "provider_web_evidence@1",
                "provider": "pubmed",
                "request_digest": pubmed_request_digest,
                "response_digest": pubmed_response_digest,
                "citations": [{"pmid": "12345678", "title": "AOX evidence"}],
            }
        )
        + b"\n"
    )
    ncbi_bytes = _ncbi_reference_set()
    ncbi_digest = _digest_bytes(ncbi_bytes)
    hmm_reference_selection = aox_reference.select_hmm_reference_set(
        ncbi_bytes,
        expected_input_digest=ncbi_digest,
    )
    hmm_reference_set_bytes = hmm_reference_selection.to_fasta().encode("utf-8")
    scoring_reference_selection = aox_reference.select_scoring_reference(
        ncbi_bytes,
        expected_input_digest=ncbi_digest,
    )
    scoring_reference_bytes = scoring_reference_selection.to_fasta().encode("utf-8")
    ebi_hmmer_body = (
        json.dumps(
            {
                "database": "refprot",
                "hits": [
                    {
                        "acc": accession_by_hit_id[hit_id],
                        "target": hit_id,
                    }
                    for hit_id in hit_ids
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    parsed_hit_rows: list[dict[str, str]] = []
    raw_page_digest = _digest_bytes(ebi_hmmer_body)
    ebi_hmmer_bytes = (
        json.dumps(
            {
                "schema_id": "provider_raw_http_response_set@1",
                "provider": "ebi_hmmer",
                "operation": "bio.hmmer_search",
                "responses": [
                    {
                        "ordinal": 1,
                        "phase": "results",
                        "status_code": 200,
                        "headers": {},
                        "body_encoding": "base64",
                        "body_base64": base64.b64encode(ebi_hmmer_body).decode("ascii"),
                        "body_digest": raw_page_digest,
                        "size_bytes": len(ebi_hmmer_body),
                    }
                ],
            },
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        + b"\n"
    )
    for hit_index, hit_id in enumerate(hit_ids):
        accession = accession_by_hit_id[hit_id]
        score_numeric = f"25{hit_index}.1"
        digest_payload: dict[str, object] = {
            "target": hit_id,
            "accession": accession,
            "evalue": "0.000001",
            "score": score_numeric,
            "page": 1,
            "hit_index": hit_index,
            "evalue_numeric": "0.000001",
            "score_numeric": score_numeric,
            "raw_page_digest": raw_page_digest,
            "raw_hit_digest": _digest(f"ebi-hmmer-hit:{accession}"),
        }
        parsed_row_digest = _digest_bytes(
            (json.dumps(digest_payload, sort_keys=True, indent=2) + "\n").encode(
                "utf-8"
            )
        )
        parsed_hit_rows.append(
            {
                **{key: str(value) for key, value in digest_payload.items()},
                "parsed_row_digest": parsed_row_digest,
            }
        )
    parsed_hit_output = io.StringIO(newline="")
    parsed_hit_writer = csv.DictWriter(
        parsed_hit_output,
        fieldnames=list(aox_hmmer.INPUT_COLUMNS),
        lineterminator="\n",
    )
    parsed_hit_writer.writeheader()
    parsed_hit_writer.writerows(parsed_hit_rows)
    parsed_hit_bytes = parsed_hit_output.getvalue().encode("utf-8")
    score_filter_result = aox_hmmer.parse_and_filter_csv(parsed_hit_bytes)
    score_filtered_accession_bytes = score_filter_result.to_csv().encode("utf-8")
    derived_accessions = list(score_filter_result.accessions)
    uniprot_retrieved_at = "2026-07-17T00:00:00+00:00"
    uniprot_release = "2026_03"
    uniprot_release_date = "2026-06-17"
    uniprot_page_response_digest = _digest("uniprot-page-response")
    uniprot_bytes = "".join(
        f">{accession} {accession}_AOX\n"
        f"{normalized_hit_sequences[hit_id_by_accession[accession]]}\n"
        for accession in derived_accessions
    ).encode("utf-8")
    uniprot_metadata_records: list[dict[str, object]] = []
    for accession in derived_accessions:
        sequence = normalized_hit_sequences[hit_id_by_accession[accession]]
        sequence_digest = _digest_bytes(sequence.encode("ascii"))
        identifier = f"{accession}_AOX"
        entry_type = "UniProtKB reviewed (Swiss-Prot)"
        provider_metadata = {
            "primaryAccession": accession,
            "secondaryAccessions": [],
            "uniProtkbId": identifier,
            "entryType": entry_type,
            "entryAudit": {"entryVersion": 1, "sequenceVersion": 1},
        }
        provider_result = {
            **provider_metadata,
            "sequence": {"value": sequence, "length": len(sequence)},
        }
        uniprot_metadata_records.append(
            {
                "requested_accession": accession,
                "primary_accession": accession,
                "uniprot_identifier": identifier,
                "reviewed": True,
                "entry_type": entry_type,
                "uniprot_release": uniprot_release,
                "uniprot_release_date": uniprot_release_date,
                "retrieved_at": uniprot_retrieved_at,
                "entry_version": 1,
                "sequence_version": 1,
                "sequence_length": len(sequence),
                "sequence_digest": sequence_digest,
                "response_digest": uniprot_page_response_digest,
                "record_digest": _digest_bytes(
                    (
                        json.dumps(provider_result, sort_keys=True, indent=2) + "\n"
                    ).encode("utf-8")
                ),
                "mapping_annotations": [
                    {
                        "annotation_type": "provider_identity_mapping",
                        "source_database": "requested_identifier",
                        "source_accession": accession,
                        "target_database": "uniprotkb",
                        "target_accession": accession,
                        "relationship": "resolves_to_primary_accession",
                        "identity_replaced": False,
                    }
                ],
                "provider_metadata": provider_metadata,
            }
        )
    uniprot_aggregate_response_digest = _digest_bytes(
        (
            json.dumps(
                [uniprot_page_response_digest],
                sort_keys=True,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
    )
    uniprot_metadata_bytes = (
        json.dumps(
            {
                "provider": "uniprot",
                "database": "uniprotkb",
                "fields": [
                    "accession",
                    "id",
                    "sequence",
                    "reviewed",
                    "sequence_version",
                    "version",
                ],
                "batch_size": 100,
                "identity_contract_id": "uniprot_primary_sequence_identity@1",
                "requested_accessions": derived_accessions,
                "records": uniprot_metadata_records,
                "warnings": [],
                "retrieved_at": uniprot_retrieved_at,
                "uniprot_release": uniprot_release,
                "uniprot_release_date": uniprot_release_date,
                "aggregate_response_digest": uniprot_aggregate_response_digest,
                "source_sequence_identity_count": 0,
                "sequence_mismatch_resolution_count": 0,
                "api_version": "rest.uniprot.org@2026-03",
            },
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        + b"\n"
    )
    sequence_join_result = aox_sequence_join.join_score_filtered_accessions(
        score_filtered_accession_bytes,
        uniprot_bytes,
        uniprot_metadata_bytes,
        expected_contract_id=aox_sequence_join.CONTRACT_ID,
        expected_contract_digest=aox_sequence_join.CONTRACT_DIGEST,
        expected_implementation_digest=aox_sequence_join.IMPLEMENTATION_DIGEST,
        expected_hmmer_contract_id=aox_hmmer.CONTRACT_ID,
        expected_hmmer_contract_digest=aox_hmmer.CONTRACT_DIGEST,
        expected_hmmer_implementation_digest=aox_hmmer.IMPLEMENTATION_DIGEST,
        expected_score_filtered_csv_digest=_digest_bytes(
            score_filtered_accession_bytes
        ),
        expected_uniprot_fasta_digest=_digest_bytes(uniprot_bytes),
        expected_uniprot_metadata_digest=_digest_bytes(uniprot_metadata_bytes),
    )
    post_uniprot_filtered_bytes = sequence_join_result.hits_csv().encode("utf-8")
    target_sequence_bytes = sequence_join_result.target_fasta().encode("utf-8")
    scoring_input_assembly = aox_reference.assemble_scoring_input(
        scoring_reference_bytes,
        target_sequence_bytes,
        expected_scoring_reference_input_digest=_digest_bytes(
            scoring_reference_bytes
        ),
        expected_target_input_digest=_digest_bytes(target_sequence_bytes),
    )
    scoring_input_bytes = scoring_input_assembly.to_fasta().encode("utf-8")
    candidate_bytes = "".join(
        f">{item}\n{aligned_records[item]}\n" for item in candidate_ids
    ).encode("utf-8")
    membership_bytes = (
        "cluster_id,member_id,representative_id,is_representative,"
        "identity_to_representative,member_length\n"
        + "".join(
            f"cluster_{index},{item},{item},true,1.000000,"
            f"{len(aligned_records[item])}\n"
            for index, item in enumerate(candidate_ids)
        )
    ).encode("utf-8")
    reference_alignment_bytes = hmm_reference_set_bytes
    hmm_model_bytes = b"HMMER3/f [aox-test]\nNAME AOX_test\n//\n"
    graph = aox_similarity.build_similarity_graph(
        candidate_bytes,
        membership_bytes,
        threshold_ppm=750_000,
    )
    alignment_digest = _write_artifact(
        artifact_root, "formal/scoring-alignment.fasta", alignment_bytes
    )
    scored_digest = _write_artifact(
        artifact_root, "formal/motif-scores.csv", scored_bytes
    )
    report_digest = _write_artifact(artifact_root, "formal/report.md", report_bytes)
    pubmed_digest = _write_artifact(
        artifact_root, "formal/provider/pubmed-response.json", pubmed_bytes
    )
    ncbi_digest = _write_artifact(
        artifact_root, "formal/provider/ncbi-provider-sequences.fasta", ncbi_bytes
    )
    hmm_reference_set_digest = _write_artifact(
        artifact_root,
        "formal/calculation/AOX-ref21.fasta",
        hmm_reference_set_bytes,
    )
    scoring_reference_digest = _write_artifact(
        artifact_root,
        "formal/calculation/AOX-coordinate-reference-AAB57849.1.fasta",
        scoring_reference_bytes,
    )
    scoring_input_digest = _write_artifact(
        artifact_root,
        "formal/calculation/AOX-scoring-input.fasta",
        scoring_input_bytes,
    )
    reference_alignment_digest = _write_artifact(
        artifact_root,
        "formal/toolchain/reference-alignment.fasta",
        reference_alignment_bytes,
    )
    hmm_model_digest = _write_artifact(
        artifact_root,
        "formal/toolchain/aox-reference.hmm",
        hmm_model_bytes,
    )
    ebi_hmmer_artifact_digest = _write_artifact(
        artifact_root,
        "formal/provider/ebi-hmmer-response.json",
        ebi_hmmer_bytes,
    )
    parsed_hit_digest = _write_artifact(
        artifact_root,
        "formal/provider/ebi-hmmer-parsed-hits.csv",
        parsed_hit_bytes,
    )
    score_filtered_accession_digest = _write_artifact(
        artifact_root,
        "formal/calculation/hmmer-score-filtered-accessions.csv",
        score_filtered_accession_bytes,
    )
    uniprot_digest = _write_artifact(
        artifact_root, "formal/provider/uniprot-candidates.fasta", uniprot_bytes
    )
    uniprot_metadata_digest = _write_artifact(
        artifact_root,
        "formal/provider/uniprot-metadata.json",
        uniprot_metadata_bytes,
    )
    post_uniprot_filtered_digest = _write_artifact(
        artifact_root,
        "formal/calculation/hits-len650-700-200.csv",
        post_uniprot_filtered_bytes,
    )
    target_sequence_digest = _write_artifact(
        artifact_root,
        "formal/calculation/target-sequences.fasta",
        target_sequence_bytes,
    )
    candidate_digest = _write_artifact(
        artifact_root, "formal/candidates.fasta", candidate_bytes
    )
    membership_digest = _write_artifact(
        artifact_root, "formal/cdhit-membership.csv", membership_bytes
    )
    nodes_digest = _write_artifact(
        artifact_root, "formal/graph-nodes.csv", graph.nodes_csv().encode("utf-8")
    )
    edges_digest = _write_artifact(
        artifact_root, "formal/graph-edges.csv", graph.edges_csv().encode("utf-8")
    )
    manifest_digest = _write_artifact(
        artifact_root,
        "formal/graph-manifest.json",
        graph.manifest_json().encode("utf-8"),
    )
    artifacts = [
        {
            "artifact_id": "art_pubmed_response",
            "relative_path": "formal/provider/pubmed-response.json",
            "scope": "formal",
            "origin": "engine_invocation",
            "kind": "provider_evidence",
            "provenance": {
                "invocation_id": "invocation_pubmed",
                "provider": "pubmed",
            },
        },
        {
            "artifact_id": "art_ncbi_provider_sequences",
            "relative_path": "formal/provider/ncbi-provider-sequences.fasta",
            "scope": "formal",
            "origin": "operation",
            "kind": "provider_evidence",
            "provenance": {"operation_id": "op_ncbi", "provider": "ncbi"},
        },
        {
            "artifact_id": "art_hmm_reference_set",
            "relative_path": "formal/calculation/AOX-ref21.fasta",
            "scope": "formal",
            "origin": "operation",
            "kind": "sequence",
            "provenance": {
                "operation_id": "op_hmm_reference_set_selection",
                "calculation_id": (
                    aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID
                ),
            },
        },
        {
            "artifact_id": "art_scoring_reference",
            "relative_path": (
                "formal/calculation/AOX-coordinate-reference-AAB57849.1.fasta"
            ),
            "scope": "formal",
            "origin": "operation",
            "kind": "sequence",
            "provenance": {
                "operation_id": "op_scoring_reference_selection",
                "calculation_id": (
                    aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID
                ),
                "reference_accession": aox_reference.SCORING_REFERENCE_ACCESSION,
            },
        },
        {
            "artifact_id": "art_scoring_input",
            "relative_path": "formal/calculation/AOX-scoring-input.fasta",
            "scope": "formal",
            "origin": "operation",
            "kind": "sequence",
            "provenance": {
                "operation_id": "op_scoring_input_assembly",
                "calculation_id": aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID,
            },
        },
        {
            "artifact_id": "art_reference_alignment",
            "relative_path": "formal/toolchain/reference-alignment.fasta",
            "scope": "formal",
            "origin": "operation",
            "kind": "sequence",
            "provenance": {"operation_id": "op_align", "tool": "mafft"},
        },
        {
            "artifact_id": "art_hmm_model",
            "relative_path": "formal/toolchain/aox-reference.hmm",
            "scope": "formal",
            "origin": "operation",
            "kind": "model",
            "provenance": {"operation_id": "op_hmmbuild", "tool": "hmmbuild"},
        },
        {
            "artifact_id": "art_ebi_hmmer_response",
            "relative_path": "formal/provider/ebi-hmmer-response.json",
            "scope": "formal",
            "origin": "operation",
            "kind": "provider_evidence",
            "provenance": {
                "operation_id": "op_ebi_hmmer",
                "provider": "ebi_hmmer",
            },
        },
        {
            "artifact_id": "art_hmmer_parsed_hits",
            "relative_path": "formal/provider/ebi-hmmer-parsed-hits.csv",
            "scope": "formal",
            "origin": "operation",
            "kind": "result",
            "provenance": {
                "operation_id": "op_ebi_hmmer",
                "provider": "ebi_hmmer",
                "provider_artifact_kind": "provider_parsed",
            },
        },
        {
            "artifact_id": "art_hmmer_score_filtered_accessions",
            "relative_path": ("formal/calculation/hmmer-score-filtered-accessions.csv"),
            "scope": "formal",
            "origin": "operation",
            "kind": "result",
            "provenance": {
                "operation_id": "op_pre_uniprot_score_filter",
                "derivation_id": aox_hmmer.CONTRACT_ID,
            },
        },
        {
            "artifact_id": "art_uniprot_candidates",
            "relative_path": "formal/provider/uniprot-candidates.fasta",
            "scope": "formal",
            "origin": "operation",
            "kind": "provider_evidence",
            "provenance": {"operation_id": "op_uniprot", "provider": "uniprot"},
        },
        {
            "artifact_id": "art_uniprot_metadata",
            "relative_path": "formal/provider/uniprot-metadata.json",
            "scope": "formal",
            "origin": "operation",
            "kind": "provider_evidence",
            "provenance": {
                "operation_id": "op_uniprot",
                "provider": "uniprot",
                "identity_contract_id": "uniprot_primary_sequence_identity@1",
            },
        },
        {
            "artifact_id": "art_post_uniprot_filtered_hits",
            "relative_path": "formal/calculation/hits-len650-700-200.csv",
            "scope": "formal",
            "origin": "operation",
            "kind": "result",
            "provenance": {
                "operation_id": "op_post_uniprot_filter",
                "calculation_id": AOX_POST_UNIPROT_FILTER_ID,
            },
        },
        {
            "artifact_id": "art_target_sequences",
            "relative_path": "formal/calculation/target-sequences.fasta",
            "scope": "formal",
            "origin": "operation",
            "kind": "sequence",
            "provenance": {
                "operation_id": "op_post_uniprot_filter",
                "calculation_id": AOX_POST_UNIPROT_FILTER_ID,
            },
        },
        {
            "artifact_id": "art_alignment",
            "relative_path": "formal/scoring-alignment.fasta",
            "scope": "formal",
            "origin": "operation",
            "kind": "sequence",
            "provenance": {
                "operation_id": "op_hmmalign",
                "provider": "hpc_mafft",
                "source_digest": alignment_digest,
            },
        },
        {
            "artifact_id": "art_scores",
            "relative_path": "formal/motif-scores.csv",
            "scope": "formal",
            "origin": "operation",
            "kind": "result",
            "provenance": {
                "operation_id": "op_score",
                "contract_id": aox_motif.CONTRACT_ID,
                "input_digest": scoring_result.alignment.input_digest,
            },
        },
        {
            "artifact_id": "art_report",
            "relative_path": "formal/report.md",
            "scope": "formal",
            "origin": "report",
            "kind": "report",
            "provenance": {
                "report_id": "report_aox",
                "draft_id": "draft_aox",
                "content_ref": "doc_report_aox",
                "content_document_digest": report_digest,
                "draft_published": attempt_kind == "positive",
            },
        },
        {
            "artifact_id": "art_candidates",
            "relative_path": "formal/candidates.fasta",
            "scope": "formal",
            "origin": "operation",
            "kind": "sequence",
            "provenance": {"operation_id": "op_candidate_filter"},
        },
        {
            "artifact_id": "art_membership",
            "relative_path": "formal/cdhit-membership.csv",
            "scope": "formal",
            "origin": "operation",
            "kind": "result",
            "provenance": {
                "operation_id": "op_cdhit",
                "schema_id": aox_similarity.MEMBERSHIP_SCHEMA_ID,
            },
        },
        {
            "artifact_id": "art_nodes",
            "relative_path": "formal/graph-nodes.csv",
            "scope": "formal",
            "origin": "operation",
            "kind": "result",
            "provenance": {"operation_id": "op_similarity"},
        },
        {
            "artifact_id": "art_edges",
            "relative_path": "formal/graph-edges.csv",
            "scope": "formal",
            "origin": "operation",
            "kind": "result",
            "provenance": {"operation_id": "op_similarity"},
        },
        {
            "artifact_id": "art_graph_manifest",
            "relative_path": "formal/graph-manifest.json",
            "scope": "formal",
            "origin": "operation",
            "kind": "result",
            "provenance": {
                "operation_id": "op_similarity",
                "calculation_id": aox_similarity.CALCULATION_ID,
            },
        },
        *probe_fixture["artifacts"],
    ]
    operations = [
        *probe_fixture["operations"],
        _operation(
            "op_ncbi",
            outputs=[("art_ncbi_provider_sequences", ncbi_digest)],
        ),
        _operation(
            "op_hmm_reference_set_selection",
            inputs=[("art_ncbi_provider_sequences", ncbi_digest)],
            outputs=[("art_hmm_reference_set", hmm_reference_set_digest)],
        ),
        _operation(
            "op_scoring_reference_selection",
            inputs=[("art_ncbi_provider_sequences", ncbi_digest)],
            outputs=[("art_scoring_reference", scoring_reference_digest)],
        ),
        _operation(
            "op_ebi_hmmer",
            inputs=[("art_hmm_model", hmm_model_digest)],
            outputs=[
                ("art_ebi_hmmer_response", ebi_hmmer_artifact_digest),
                ("art_hmmer_parsed_hits", parsed_hit_digest),
            ],
        ),
        _operation(
            "op_pre_uniprot_score_filter",
            inputs=[("art_hmmer_parsed_hits", parsed_hit_digest)],
            outputs=[
                (
                    "art_hmmer_score_filtered_accessions",
                    score_filtered_accession_digest,
                )
            ],
        ),
        _operation(
            "op_uniprot",
            inputs=[
                (
                    "art_hmmer_score_filtered_accessions",
                    score_filtered_accession_digest,
                )
            ],
            outputs=[
                ("art_uniprot_candidates", uniprot_digest),
                ("art_uniprot_metadata", uniprot_metadata_digest),
            ],
        ),
        _operation(
            "op_post_uniprot_filter",
            inputs=[
                (
                    "art_hmmer_score_filtered_accessions",
                    score_filtered_accession_digest,
                ),
                ("art_uniprot_candidates", uniprot_digest),
                ("art_uniprot_metadata", uniprot_metadata_digest),
            ],
            outputs=[
                (
                    "art_post_uniprot_filtered_hits",
                    post_uniprot_filtered_digest,
                ),
                ("art_target_sequences", target_sequence_digest),
            ],
        ),
        _operation(
            "op_align",
            inputs=[("art_hmm_reference_set", hmm_reference_set_digest)],
            outputs=[("art_reference_alignment", reference_alignment_digest)],
        ),
        _operation(
            "op_hmmbuild",
            inputs=[("art_reference_alignment", reference_alignment_digest)],
            outputs=[("art_hmm_model", hmm_model_digest)],
        ),
        _operation(
            "op_scoring_input_assembly",
            inputs=[
                ("art_scoring_reference", scoring_reference_digest),
                ("art_target_sequences", target_sequence_digest),
            ],
            outputs=[("art_scoring_input", scoring_input_digest)],
        ),
        _operation(
            "op_hmmalign",
            inputs=[
                ("art_hmm_model", hmm_model_digest),
                ("art_scoring_input", scoring_input_digest),
            ],
            outputs=[("art_alignment", alignment_digest)],
        ),
        _operation(
            "op_score",
            inputs=[("art_alignment", alignment_digest)],
            outputs=[("art_scores", scored_digest)],
        ),
        _operation(
            "op_candidate_filter",
            inputs=[
                ("art_scores", scored_digest),
                ("art_target_sequences", target_sequence_digest),
            ],
            outputs=[("art_candidates", candidate_digest)],
        ),
        _operation(
            "op_cdhit",
            inputs=[("art_candidates", candidate_digest)],
            outputs=[("art_membership", membership_digest)],
        ),
        _operation(
            "op_similarity",
            inputs=[
                ("art_candidates", candidate_digest),
                ("art_membership", membership_digest),
            ],
            outputs=[
                ("art_nodes", nodes_digest),
                ("art_edges", edges_digest),
                ("art_graph_manifest", manifest_digest),
            ],
        ),
    ]
    operation_runtime_receipts = {
        "op_ncbi": (
            "bio.ncbi_fetch_proteins.provider:v1",
            "provider_http",
            "invocation_ncbi",
        ),
        "op_ebi_hmmer": (
            "bio.hmmer_search.provider:v1",
            "provider_http",
            "invocation_ebi_hmmer",
        ),
        "op_uniprot": (
            "bio.uniprot_fetch.provider:v1",
            "provider_http",
            "invocation_uniprot",
        ),
        "op_align": ("bio_tools.mafft.hpc:v1", "hpc", "job_mafft"),
        "op_hmmbuild": ("bio_tools.hmmbuild.hpc:v1", "hpc", "job_hmmbuild"),
        "op_hmmalign": ("bio_tools.hmmalign.hpc:v1", "hpc", "job_hmmalign"),
        "op_cdhit": ("bio_tools.cdhit.hpc:v1", "hpc", "job_cdhit"),
    }
    operation_by_id = {item["operation_id"]: item for item in operations}
    operation_by_id["op_ebi_hmmer"]["parameters"] = {
        "hmm_artifact_id": "art_hmm_model",
        "hmm_artifact_digest": hmm_model_digest,
        "database": "refprot",
    }
    operation_by_id["op_uniprot"]["parameters"] = {
        "accessions": derived_accessions,
        "source_hit_artifact": {
            "artifact_id": "art_hmmer_score_filtered_accessions",
            "content_digest": score_filtered_accession_digest,
        },
    }
    operation_by_id["op_hmm_reference_set_selection"]["parameters"] = {
        "selected_accessions": list(aox_reference.HMM_REFERENCE_ACCESSIONS),
        "identity_replacement": False,
    }
    operation_by_id["op_hmm_reference_set_selection"]["kind"] = (
        aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID
    )
    operation_by_id["op_scoring_reference_selection"]["parameters"] = {
        "reference_accession": aox_reference.SCORING_REFERENCE_ACCESSION,
        "identity_replacement": False,
    }
    operation_by_id["op_scoring_reference_selection"]["kind"] = (
        aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID
    )
    operation_by_id["op_scoring_input_assembly"]["parameters"] = {
        "reference_accession": aox_reference.SCORING_REFERENCE_ACCESSION,
        "target_count": len(scoring_input_assembly.targets),
    }
    operation_by_id["op_scoring_input_assembly"]["kind"] = (
        aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID
    )
    operation_by_id["op_pre_uniprot_score_filter"]["parameters"] = {
        "hmm_score_exclusive_gt": aox_hmmer.SCORE_THRESHOLD_DISPLAY,
    }
    operation_by_id["op_pre_uniprot_score_filter"]["kind"] = aox_hmmer.CONTRACT_ID
    operation_by_id["op_post_uniprot_filter"]["parameters"] = {
        "length_inclusive": [650, 700],
    }
    operation_by_id["op_post_uniprot_filter"]["kind"] = AOX_POST_UNIPROT_FILTER_ID
    for operation in operations:
        if operation["scope"] == "probe":
            _refresh_operation_identity(operation)
            continue
        if operation["operation_id"] in {
            "op_hmm_reference_set_selection",
            "op_scoring_reference_selection",
            "op_scoring_input_assembly",
            "op_pre_uniprot_score_filter",
            "op_post_uniprot_filter",
            "op_score",
            "op_candidate_filter",
            "op_similarity",
        }:
            _refresh_sandbox_calculation_identity(operation)
            continue
        route_policy_id, selected_backend, backend_run_id = (
            operation_runtime_receipts.get(
                operation["operation_id"],
                (
                    "openzyme_pipeline.scientific_calculation:v1",
                    "sandbox_sdk",
                    f"job_{operation['operation_id']}_sandbox",
                ),
            )
        )
        operation.update(
            {
                "route_policy_id": route_policy_id,
                "selected_backend": selected_backend,
                "backend_run_id": backend_run_id,
                "source_snapshot_digest": _digest("aox-pipeline-source"),
            }
        )
        _refresh_operation_identity(operation)
    product_report_record = {
        "report_id": "report_aox",
        "session_id": "sess_aox_live",
        "task_id": "task_report",
        "lane_id": "lane_report",
        "invocation_id": None,
        "run_id": None,
        "artifact_id": None,
        "status": "ready",
        "title": "AOX/HMM report",
        "summary": "Formula-derived AOX motif result",
        "stage_summary": "Research, execution, and reporting completed.",
        "created_at": "2026-07-17T00:00:08+00:00",
        "updated_at": "2026-07-17T00:00:09+00:00",
    }
    published_draft_record = {
        "draft_id": "draft_aox",
        "session_id": "sess_aox_live",
        "task_id": "task_report",
        "owner_agent_id": "agent_reporter_aox",
        "status": "published",
        "title": "AOX/HMM report",
        "summary": "Formula-derived AOX motif result",
        "content_ref": "doc_report_aox",
        "published_report_id": "report_aox",
        "created_at": "2026-07-17T00:00:07+00:00",
        "updated_at": "2026-07-17T00:00:09+00:00",
    }
    content_document_record = {
        "document_id": "doc_report_aox",
        "session_id": "sess_aox_live",
        "invocation_id": None,
        "document_kind": "report_draft_content",
        "payload": {"markdown": report_bytes.decode("utf-8")},
        "created_at": "2026-07-17T00:00:07+00:00",
        "updated_at": "2026-07-17T00:00:07+00:00",
    }
    report_publish_events = [
        {
            "event_id": "event_report_publish_invoked",
            "cursor": 40,
            "event_type": "tool.invoked",
            "payload": {
                "call_id": "call_report_publish",
                "tool_name": "report.publish",
                "task_id": "task_report",
                "lane_id": "lane_report",
                "role": "reporter",
            },
        },
        {
            "event_id": "event_report_draft_updated",
            "cursor": 41,
            "event_type": "report_draft.updated",
            "payload": published_draft_record,
        },
        {
            "event_id": "event_report_generated",
            "cursor": 42,
            "event_type": "report.generated",
            "payload": product_report_record,
        },
        {
            "event_id": "event_report_publish_completed",
            "cursor": 43,
            "event_type": "tool.completed",
            "payload": {
                "call_id": "call_report_publish",
                "tool_name": "report.publish",
                "task_id": "task_report",
                "lane_id": "lane_report",
                "role": "reporter",
                "ok": True,
                "status": "ok",
            },
        },
    ]
    report = {
        "report_id": "report_aox",
        "status": "ready" if attempt_kind == "positive" else "failed_evidence",
        "session_id": "sess_aox_live" if attempt_kind == "positive" else None,
        "task_id": "task_report" if attempt_kind == "positive" else None,
        "lane_id": "lane_report" if attempt_kind == "positive" else None,
        "invocation_id": None,
        "run_id": None,
        "draft_id": "draft_aox" if attempt_kind == "positive" else None,
        "draft_status": "published" if attempt_kind == "positive" else None,
        "published_report_id": ("report_aox" if attempt_kind == "positive" else None),
        "content_ref": "doc_report_aox" if attempt_kind == "positive" else None,
        "content_document_digest": (
            canonical_digest(content_document_record)
            if attempt_kind == "positive"
            else None
        ),
        "content_document_kind": (
            "report_draft_content" if attempt_kind == "positive" else None
        ),
        "content_document_invocation_id": None,
        "owner_agent_id": "agent_reporter_aox" if attempt_kind == "positive" else None,
        "product_artifact_id": None,
        "publication_action": "report.publish" if attempt_kind == "positive" else None,
        "product_report_record": (
            product_report_record if attempt_kind == "positive" else None
        ),
        "published_draft_record": (
            published_draft_record if attempt_kind == "positive" else None
        ),
        "content_document_record": (
            content_document_record if attempt_kind == "positive" else None
        ),
        "publish_events": report_publish_events if attempt_kind == "positive" else [],
        "cutover_eligible": attempt_kind == "positive",
        "content_artifact_id": "art_report",
        "content_digest": report_digest,
        "artifact_ids": [
            "art_alignment",
            "art_pubmed_response",
            "art_ncbi_provider_sequences",
            "art_hmm_reference_set",
            "art_scoring_reference",
            "art_scoring_input",
            "art_ebi_hmmer_response",
            "art_hmmer_parsed_hits",
            "art_hmmer_score_filtered_accessions",
            "art_uniprot_candidates",
            "art_uniprot_metadata",
            "art_post_uniprot_filtered_hits",
            "art_target_sequences",
            "art_scores",
            "art_candidates",
            "art_membership",
            "art_nodes",
            "art_edges",
            "art_graph_manifest",
            "art_report",
        ],
        "source_ref_ids": ["source_pubmed_aox"],
        "claim_source_links": [
            {
                "claim_id": "claim_motif_reproducible",
                "source_ref_ids": ["source_pubmed_aox"],
                "artifact_ids": ["art_scores"],
            }
        ],
    }
    report_artifact = next(
        artifact for artifact in artifacts if artifact["artifact_id"] == "art_report"
    )
    report_artifact["provenance"] = {
        "report_id": "report_aox",
        "draft_id": "draft_aox",
        "content_ref": "doc_report_aox",
        "content_document_digest": canonical_digest(content_document_record),
        "draft_published": attempt_kind == "positive",
    }
    evidence: dict[str, object] = {
        "provider_identities": [
            {
                "provider_record_id": "provider_record_pubmed",
                "provider": "pubmed",
                "status": "completed",
                "canonical_ref_kind": "engine_invocation",
                "invocation_id": "invocation_pubmed",
                "operation_id": None,
                "cache_hit": False,
                "request_digest": pubmed_request_digest,
                "response_digest": pubmed_response_digest,
                "artifact_ids": ["art_pubmed_response"],
                "source_ref_ids": ["source_pubmed_aox"],
                "source_refs": [
                    {
                        "source_ref_id": "source_pubmed_aox",
                        "pmid": "12345678",
                    }
                ],
            },
            {
                "provider_record_id": "provider_record_ncbi",
                "provider": "ncbi",
                "status": "completed",
                "canonical_ref_kind": "controlled_operation",
                "invocation_id": "invocation_ncbi",
                "operation_id": "op_ncbi",
                "cache_hit": False,
                "request_digest": _digest("ncbi-request"),
                "response_digest": ncbi_digest,
                "artifact_ids": ["art_ncbi_provider_sequences"],
                "source_ref_ids": [],
            },
            {
                "provider_record_id": "provider_record_ebi_hmmer",
                "provider": "ebi_hmmer",
                "status": "completed",
                "canonical_ref_kind": "controlled_operation",
                "invocation_id": "invocation_ebi_hmmer",
                "operation_id": "op_ebi_hmmer",
                "cache_hit": False,
                "request_digest": _digest("ebi-hmmer-request"),
                "response_digest": raw_page_digest,
                "artifact_ids": [
                    "art_ebi_hmmer_response",
                    "art_hmmer_parsed_hits",
                ],
                "source_ref_ids": [],
            },
            {
                "provider_record_id": "provider_record_uniprot",
                "provider": "uniprot",
                "status": "completed",
                "canonical_ref_kind": "controlled_operation",
                "invocation_id": "invocation_uniprot",
                "operation_id": "op_uniprot",
                "cache_hit": False,
                "request_digest": _digest("uniprot-request"),
                "response_digest": uniprot_digest,
                "artifact_ids": [
                    "art_uniprot_candidates",
                    "art_uniprot_metadata",
                ],
                "source_ref_ids": [],
            },
        ],
        "engine_invocations": [
            {
                "invocation_id": "invocation_pubmed",
                "engine_name": "research_tool",
                "status": "succeeded",
                "task_id": "task_research",
                "lane_id": "lane_research",
                "input_ref": "invocation_pubmed:input",
                "input_document_digest": _digest("pubmed-input-document"),
                "output_ref": "invocation_pubmed:output",
                "output_document_digest": _digest("pubmed-output-document"),
                "started_at": "2026-07-17T00:00:00+00:00",
                "finished_at": "2026-07-17T00:00:01+00:00",
                "artifact_refs": [
                    {
                        "artifact_id": "art_pubmed_response",
                        "content_digest": pubmed_digest,
                    }
                ],
            }
        ],
        "toolchain_identities": [
            {
                "toolchain_record_id": "toolchain_record_mafft",
                "toolchain_id": "mafft@7.526",
                "tool": "mafft",
                "operation_id": "op_align",
                "job_id": "job_mafft",
                "image_digest": _digest("mafft-image"),
                "status": "completed",
            },
            {
                "toolchain_record_id": "toolchain_record_hmmbuild",
                "toolchain_id": "hmmbuild@3.4",
                "tool": "hmmbuild",
                "operation_id": "op_hmmbuild",
                "job_id": "job_hmmbuild",
                "image_digest": _digest("hmmbuild-image"),
                "status": "completed",
            },
            {
                "toolchain_record_id": "toolchain_record_hmmalign",
                "toolchain_id": "hmmalign@3.4",
                "tool": "hmmalign",
                "operation_id": "op_hmmalign",
                "job_id": "job_hmmalign",
                "image_digest": _digest("hmmalign-image"),
                "status": "completed",
            },
            {
                "toolchain_record_id": "toolchain_record_cdhit",
                "toolchain_id": "cd-hit@4.8.1",
                "tool": "cd-hit",
                "operation_id": "op_cdhit",
                "job_id": "job_cdhit",
                "image_digest": _digest("cdhit-image"),
                "status": "completed",
            },
        ],
        "known_positive_probe": probe_fixture["probe"],
        "product_path": {
            "entry_message_count": 1,
            "canonical_api_only": True,
            "cache_hit": False,
            "participant_roles": ["researcher", "executor", "reporter"],
            "session_id": "sess_aox_live",
            "entry_message_id": "msg_entry",
            "final_master_response_id": "msg_final",
            "entry_message_digest": _digest("entry-message"),
            "workspace_projection_digest": _digest("workspace-projection"),
            "event_log_digest": _digest("event-log"),
            "runtime_config_digest": _digest("runtime-config"),
            "micu_scenario": "aox_blank_world_cutover",
            "micu_model": "micu-live",
            "micu_invocation_ids": ["invocation_micu_master"],
            "task_ids_by_role": {
                "executor": "task_execute",
                "reporter": "task_report",
                "researcher": "task_research",
            },
            "launch_receipt": {
                "root_identity": clean_world["root_identity"],
                "hpc_workspace_label": clean_world["hpc_workspace_label"],
                "sqlite_initialized_fresh": True,
                "artifact_root_bound": True,
                "blob_root_bound": True,
                "sandbox_root_bound": True,
                "sandbox_runtime_identity": {
                    "image_digest": _identity()["image_digest"],
                    "pipeline_sdk_digest": _identity()["sdk_digest"],
                    "runtime_identity_digest": _digest("sandbox-runtime"),
                    "sandbox_protocol_version": "s10",
                },
            },
        },
        "approvals": [
            *probe_fixture["approvals"],
            {
                "approval_id": "approval_hmmbuild",
                "operation_id": "op_hmmbuild",
                "operation_identity_digest": operation_by_id["op_hmmbuild"][
                    "operation_identity_digest"
                ],
                "decision": "approved",
            }
        ],
        "operations": operations,
        "tasks": [
            {
                "task_id": "task_research",
                "role": "researcher",
                "status": "completed",
                "business_exit": "agent_explicit",
            },
            {
                "task_id": "task_execute",
                "role": "executor",
                "status": "completed" if attempt_kind == "positive" else "failed",
                "business_exit": "agent_explicit",
            },
            {
                "task_id": "task_report",
                "role": "reporter",
                "status": "completed" if attempt_kind == "positive" else "failed",
                "business_exit": "agent_explicit",
            },
        ],
        "artifacts": artifacts,
        "report": report,
        "final_answer": {
            "message_id": "msg_final",
            "content": (
                "AOX/HMM completed with a sealed report."
                if attempt_kind == "positive"
                else "AOX/HMM failed closed at the injected artifact seam."
            ),
        },
        "scientific_checks": (
            {
                "scoring": {
                    "alignment_artifact_id": "art_alignment",
                    "scored_artifact_id": "art_scores",
                    "scoring_contract_id": aox_motif.CONTRACT_ID,
                    "scoring_contract_digest": aox_motif.CONTRACT_DIGEST,
                    "scoring_implementation_digest": aox_motif.IMPLEMENTATION_DIGEST,
                    "input_digest": scoring_result.alignment.input_digest,
                },
                "sequence_join": {
                    "score_filtered_artifact_id": (
                        "art_hmmer_score_filtered_accessions"
                    ),
                    "uniprot_fasta_artifact_id": "art_uniprot_candidates",
                    "uniprot_metadata_artifact_id": "art_uniprot_metadata",
                    "filtered_hits_artifact_id": ("art_post_uniprot_filtered_hits"),
                    "target_fasta_artifact_id": "art_target_sequences",
                    "contract_id": aox_sequence_join.CONTRACT_ID,
                    "contract_digest": aox_sequence_join.CONTRACT_DIGEST,
                    "implementation_digest": aox_sequence_join.IMPLEMENTATION_DIGEST,
                    "metadata": sequence_join_result.metadata(),
                },
                "similarity": {
                    "candidate_fasta_artifact_id": "art_candidates",
                    "membership_artifact_id": "art_membership",
                    "nodes_artifact_id": "art_nodes",
                    "edges_artifact_id": "art_edges",
                    "manifest_artifact_id": "art_graph_manifest",
                    "threshold_ppm": 750_000,
                    "empty_result_reason": None,
                    "calculation_id": aox_similarity.CALCULATION_ID,
                    "calculation_digest": aox_similarity.CALCULATION_DIGEST,
                    "implementation_digest": aox_similarity.IMPLEMENTATION_DIGEST,
                    "candidate_fasta_digest": graph.sequences.input_digest,
                    "membership_digest": graph.membership.input_digest,
                },
                "aox_chain": {
                    "literature_provider_record_id": "provider_record_pubmed",
                    "operation_roles": {
                        "ncbi_fetch": "op_ncbi",
                        "hmm_reference_set_selection": (
                            "op_hmm_reference_set_selection"
                        ),
                        "scoring_reference_selection": (
                            "op_scoring_reference_selection"
                        ),
                        "reference_alignment": "op_align",
                        "hmm_build": "op_hmmbuild",
                        "hmmer_search": "op_ebi_hmmer",
                        "pre_uniprot_score_filter": ("op_pre_uniprot_score_filter"),
                        "uniprot_fetch": "op_uniprot",
                        "post_uniprot_filter": "op_post_uniprot_filter",
                        "scoring_input_assembly": "op_scoring_input_assembly",
                        "candidate_alignment": "op_hmmalign",
                        "motif_score": "op_score",
                        "candidate_filter": "op_candidate_filter",
                        "cdhit": "op_cdhit",
                        "similarity": "op_similarity",
                    },
                    "provider_dependencies": [
                        {
                            "upstream_provider_record_id": "provider_record_ebi_hmmer",
                            "downstream_provider_record_id": "provider_record_uniprot",
                            "derivation_id": aox_hmmer.CONTRACT_ID,
                            "upstream_response_artifact_ids": [
                                "art_ebi_hmmer_response"
                            ],
                            "derivation_operation_id": ("op_pre_uniprot_score_filter"),
                            "parsed_hit_artifact_id": "art_hmmer_parsed_hits",
                            "parsed_hit_artifact_digest": parsed_hit_digest,
                            "derived_accession_artifact_id": (
                                "art_hmmer_score_filtered_accessions"
                            ),
                            "derived_accession_artifact_digest": (
                                score_filtered_accession_digest
                            ),
                            "derivation_contract_digest": (aox_hmmer.CONTRACT_DIGEST),
                            "derivation_implementation_digest": (
                                aox_hmmer.IMPLEMENTATION_DIGEST
                            ),
                            "derived_accessions": derived_accessions,
                            "derived_accessions_digest": canonical_digest(
                                sorted(derived_accessions)
                            ),
                        }
                    ],
                    "artifact_roles": {
                        "literature_evidence": "art_pubmed_response",
                        "ncbi_provider_sequences": "art_ncbi_provider_sequences",
                        "hmm_reference_set": "art_hmm_reference_set",
                        "scoring_reference": "art_scoring_reference",
                        "scoring_input": "art_scoring_input",
                        "reference_alignment": "art_reference_alignment",
                        "hmm_model": "art_hmm_model",
                        "hmmer_response": "art_ebi_hmmer_response",
                        "hmmer_parsed_hits": "art_hmmer_parsed_hits",
                        "hmmer_score_filtered_accessions": (
                            "art_hmmer_score_filtered_accessions"
                        ),
                        "uniprot_sequences": "art_uniprot_candidates",
                        "uniprot_metadata": "art_uniprot_metadata",
                        "post_uniprot_filtered_hits": (
                            "art_post_uniprot_filtered_hits"
                        ),
                        "target_sequences": "art_target_sequences",
                        "scoring_alignment": "art_alignment",
                        "motif_scores": "art_scores",
                        "candidates": "art_candidates",
                        "cdhit_membership": "art_membership",
                        "graph_nodes": "art_nodes",
                        "graph_edges": "art_edges",
                        "graph_manifest": "art_graph_manifest",
                    },
                    "excluded_scoring_sequence_ids": [aox_motif.REFERENCE_ACCESSION],
                },
            }
            if attempt_kind == "positive"
            else {}
        ),
        "warnings": [],
        "degradations": [],
        "scientific_outcome": {
            "status": "discovered" if attempt_kind == "positive" else "failed",
            "candidate_count": len(candidate_ids) if attempt_kind == "positive" else 0,
            "cutover_eligible": attempt_kind == "positive",
        },
        "fault_injection": (
            None
            if attempt_kind == "positive"
            else {
                "fault_id": FAULT_ARTIFACT_BYTE_FLIP_ID,
                "target_operation_id": "op_score",
                "reached_target_seam": True,
                "expected_failure_observed": True,
                "terminal_failure_operation_id": "op_score",
            }
        ),
    }
    if attempt_kind == "fault":
        fault = inject_artifact_byte_flip(
            artifact_root,
            relative_path="formal/provider/ebi-hmmer-response.json",
            byte_offset=4,
        )
        fault_operation = _operation(
            "op_fault_validation",
            inputs=[("art_ebi_hmmer_response", fault["before_digest"])],
            status="failed",
            failure_code="artifact_content_digest_mismatch",
        )
        fault_operation.update(
            {
                "route_policy_id": "bio_tools.hmmalign.hpc:v1",
                "selected_backend": "hpc",
                "backend_run_id": "job_op_fault_validation",
                "source_snapshot_digest": _digest("aox-pipeline-source"),
            }
        )
        _refresh_operation_identity(fault_operation)
        evidence["operations"].append(fault_operation)
        evidence["fault_injection"] = {
            **fault,
            "target_artifact_id": "art_ebi_hmmer_response",
            "source_operation_id": "op_ebi_hmmer",
            "terminal_failure_operation_id": "op_fault_validation",
            "failure_code": "artifact_content_digest_mismatch",
            "expected_failure_observed": True,
        }
    if scientific_branch == "hmmer_upstream_empty":
        if attempt_kind != "positive":
            raise ValueError("healthy-empty fixture is only valid for positive attempts")
        _apply_hmmer_upstream_empty_fixture(artifact_root, evidence)
    elif scientific_branch != "nonempty":
        raise ValueError(f"unknown scientific fixture branch: {scientific_branch}")
    namespaced = _namespace_evidence(evidence, run_suffix=run_suffix)
    if attempt_kind == "positive":
        _attach_product_receipts(
            artifact_root,
            namespaced,
            run_suffix=run_suffix,
        )
    return namespaced


def _namespace_evidence(
    evidence: dict[str, object],
    *,
    run_suffix: str | None,
) -> dict[str, object]:
    if not run_suffix:
        return evidence
    identity_prefixes = (
        "approval_",
        "art_",
        "call_",
        "check_",
        "claim_",
        "doc_",
        "draft_",
        "event_",
        "invocation_",
        "job_",
        "lane_",
        "msg_",
        "op_",
        "probe_",
        "provider_record_",
        "report_",
        "sess_",
        "source_",
        "task_",
        "toolchain_record_",
    )

    semantic_text_keys = {
        "business_exit",
        "canonical_ref_kind",
        "content_document_kind",
        "document_kind",
        "event_type",
        "kind",
        "operation_identity_schema",
        "publication_action",
        "role",
        "schema_id",
        "schema_version",
        "status",
        "tool_name",
    }

    def visit(value, *, field_name: str | None = None):
        if isinstance(value, dict):
            return {key: visit(item, field_name=key) for key, item in value.items()}
        if isinstance(value, list):
            return [visit(item, field_name=field_name) for item in value]
        if (
            isinstance(value, str)
            and field_name not in semantic_text_keys
            and value.startswith(identity_prefixes)
        ):
            return f"{value}_{run_suffix}"
        return value

    namespaced = visit(evidence)
    report = namespaced["report"]
    content_document = report.get("content_document_record")
    if isinstance(content_document, dict):
        content_document_digest = canonical_digest(content_document)
        report["content_document_digest"] = content_document_digest
        report_artifact_id = report["content_artifact_id"]
        report_artifact = next(
            artifact
            for artifact in namespaced["artifacts"]
            if artifact["artifact_id"] == report_artifact_id
        )
        report_artifact["provenance"]["content_document_digest"] = (
            content_document_digest
        )
    operation_identities = {}
    for operation in namespaced["operations"]:
        if operation.get("canonical_ref_kind") == "sandbox_calculation":
            _refresh_sandbox_calculation_identity(operation)
        else:
            _refresh_operation_identity(operation)
        operation_identities[operation["operation_id"]] = operation[
            "operation_identity_digest"
        ]
    for approval in namespaced["approvals"]:
        approval["operation_identity_digest"] = operation_identities[
            approval["operation_id"]
        ]
    return namespaced


def _attach_product_receipts(
    artifact_root: Path,
    evidence: dict[str, object],
    *,
    run_suffix: str | None,
) -> None:
    suffix = "" if not run_suffix else f"_{run_suffix}"
    workspace_artifact_id = f"art_workspace_projection{suffix}"
    event_artifact_id = f"art_event_log{suffix}"
    product_path = evidence["product_path"]
    report = evidence["report"]
    operations = evidence["operations"]
    providers = evidence["provider_identities"]
    toolchains = evidence["toolchain_identities"]
    approvals = evidence["approvals"]
    tasks = evidence["tasks"]
    final_answer = evidence["final_answer"]
    outcome = evidence["scientific_outcome"]
    workspace_payload = {
        "schema_id": "aox_workspace_projection_receipt@1",
        "session_id": product_path["session_id"],
        "task_ids_by_role": product_path["task_ids_by_role"],
        "operation_ids": sorted(item["operation_id"] for item in operations),
        "provider_invocation_ids": sorted(
            str(item.get("invocation_id") or "") for item in providers
        ),
        "toolchain_job_ids": sorted(item["job_id"] for item in toolchains),
        "report_id": report["report_id"],
        "final_master_response_id": product_path["final_master_response_id"],
        "root_identity": product_path["launch_receipt"]["root_identity"],
        "runtime_config_digest": product_path["runtime_config_digest"],
        "cache_hit": product_path["cache_hit"],
        "participant_roles": sorted(product_path["participant_roles"]),
        "task_receipts": sorted(
            (
                {
                    "task_id": item["task_id"],
                    "role": item["role"],
                    "status": item["status"],
                    "business_exit": item["business_exit"],
                }
                for item in tasks
            ),
            key=lambda item: item["task_id"],
        ),
        "report_receipt": {
            "report_id": report["report_id"],
            "session_id": report["session_id"],
            "task_id": report["task_id"],
            "lane_id": report["lane_id"],
            "status": report["status"],
            "invocation_id": report["invocation_id"],
            "run_id": report["run_id"],
            "product_artifact_id": report["product_artifact_id"],
            "draft_id": report["draft_id"],
            "draft_status": report["draft_status"],
            "published_report_id": report["published_report_id"],
            "owner_agent_id": report["owner_agent_id"],
            "content_ref": report["content_ref"],
            "content_document_kind": report["content_document_kind"],
            "content_document_invocation_id": report["content_document_invocation_id"],
            "content_document_digest": report["content_document_digest"],
            "publication_action": report["publication_action"],
            "content_artifact_id": report["content_artifact_id"],
            "content_digest": report["content_digest"],
        },
        "final_answer_receipt": {
            "message_id": final_answer["message_id"],
            "content_digest": _digest_bytes(final_answer["content"].encode("utf-8")),
        },
        "scientific_outcome": {
            "status": outcome["status"],
            "candidate_count": outcome["candidate_count"],
            "empty_result_reason": outcome.get("empty_result_reason"),
            "cutover_eligible": outcome["cutover_eligible"],
        },
        "micu_scenario": product_path["micu_scenario"],
        "micu_model": product_path["micu_model"],
        "micu_invocation_ids": sorted(product_path["micu_invocation_ids"]),
    }
    event_payload = {
        "schema_id": "aox_event_log_receipt@1",
        "session_id": product_path["session_id"],
        "entry_message_id": product_path["entry_message_id"],
        "entry_message_digest": product_path["entry_message_digest"],
        "final_master_response_id": product_path["final_master_response_id"],
        "task_ids": sorted(product_path["task_ids_by_role"].values()),
        "operation_ids": sorted(item["operation_id"] for item in operations),
        "approval_bindings": sorted(
            (
                {
                    "approval_id": item["approval_id"],
                    "operation_id": item["operation_id"],
                    "operation_identity_digest": item["operation_identity_digest"],
                }
                for item in approvals
            ),
            key=lambda item: item["approval_id"],
        ),
        "micu_invocation_ids": sorted(product_path["micu_invocation_ids"]),
        "task_finishes": sorted(
            (
                {
                    "task_id": item["task_id"],
                    "status": item["status"],
                    "business_exit": item["business_exit"],
                }
                for item in tasks
            ),
            key=lambda item: item["task_id"],
        ),
        "operation_finishes": sorted(
            (
                {
                    "operation_id": item["operation_id"],
                    "operation_identity_digest": item["operation_identity_digest"],
                    "status": item["status"],
                    "terminal": item["terminal"],
                }
                for item in operations
            ),
            key=lambda item: item["operation_id"],
        ),
        "provider_invocations": sorted(
            (
                {
                    "invocation_id": item["invocation_id"],
                    "operation_id": item["operation_id"],
                    "provider": item["provider"],
                    "status": item["status"],
                }
                for item in providers
            ),
            key=lambda item: str(item["invocation_id"] or ""),
        ),
        "toolchain_jobs": sorted(
            (
                {
                    "job_id": item["job_id"],
                    "operation_id": item["operation_id"],
                    "tool": item["tool"],
                    "status": item["status"],
                }
                for item in toolchains
            ),
            key=lambda item: item["job_id"],
        ),
        "report_publish": {
            "report_id": report["report_id"],
            "session_id": report["session_id"],
            "task_id": report["task_id"],
            "lane_id": report["lane_id"],
            "status": report["status"],
            "invocation_id": report["invocation_id"],
            "run_id": report["run_id"],
            "product_artifact_id": report["product_artifact_id"],
            "draft_id": report["draft_id"],
            "draft_status": report["draft_status"],
            "published_report_id": report["published_report_id"],
            "owner_agent_id": report["owner_agent_id"],
            "content_ref": report["content_ref"],
            "content_document_kind": report["content_document_kind"],
            "content_document_invocation_id": report["content_document_invocation_id"],
            "content_document_digest": report["content_document_digest"],
            "publication_action": report["publication_action"],
            "content_digest": report["content_digest"],
            "publish_events": report["publish_events"],
        },
    }
    workspace_bytes = canonical_json_bytes(workspace_payload) + b"\n"
    event_bytes = canonical_json_bytes(event_payload) + b"\n"
    workspace_digest = _write_artifact(
        artifact_root,
        "formal/attestation/workspace-projection.json",
        workspace_bytes,
    )
    event_digest = _write_artifact(
        artifact_root,
        "formal/attestation/event-log.json",
        event_bytes,
    )
    evidence["artifacts"].extend(
        [
            {
                "artifact_id": workspace_artifact_id,
                "relative_path": "formal/attestation/workspace-projection.json",
                "scope": "formal",
                "origin": "attestation",
                "kind": "workspace_projection",
                "provenance": {"producer": "host_workspace_projection"},
            },
            {
                "artifact_id": event_artifact_id,
                "relative_path": "formal/attestation/event-log.json",
                "scope": "formal",
                "origin": "attestation",
                "kind": "event_log",
                "provenance": {"producer": "host_event_log_projection"},
            },
        ]
    )
    product_path["workspace_projection_artifact_id"] = workspace_artifact_id
    product_path["workspace_projection_digest"] = workspace_digest
    product_path["event_log_artifact_id"] = event_artifact_id
    product_path["event_log_digest"] = event_digest


def _build_bundle(
    tmp_path: Path,
    *,
    attempt_kind: str = "positive",
    scientific_branch: str = "nonempty",
    mutate_evidence=None,
    ledger_before: dict[str, object] | None = None,
    ledger_after: dict[str, object] | None = None,
) -> tuple[dict[str, object], Path, Path]:
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind=attempt_kind,
        attempt_id=f"{attempt_kind}-one",
        allowed_prerequisites={"workflow_ref": _identity()["workflow_ref"]},
    )
    evidence = _valid_evidence(
        roots.artifact_root,
        attempt_kind=attempt_kind,
        clean_world=roots.proof,
        scientific_branch=scientific_branch,
    )
    if mutate_evidence is not None:
        mutate_evidence(evidence)
    payload = build_attempt_bundle(
        attempt_id=roots.attempt_id,
        attempt_kind=attempt_kind,
        identity=_identity(),
        clean_world=roots.proof,
        ledger_before=ledger_before or _ledger_snapshot(),
        ledger_after=ledger_after
        or _ledger_snapshot(charged_tokens=20, attempt_count=2),
        artifact_root=roots.artifact_root,
        evidence=evidence,
        sealed_at="2026-07-17T00:00:00+00:00",
    )
    bundle_path = roots.evidence_root / "attempt-bundle.json"
    seal_attempt_bundle(payload, bundle_path)
    return payload, bundle_path, roots.artifact_root


def _rewrite_envelope(bundle_path: Path, mutate) -> None:
    envelope = json.loads(bundle_path.read_text(encoding="utf-8"))
    mutate(envelope)
    bundle_path.chmod(0o600)
    bundle_path.write_bytes(canonical_json_bytes(envelope) + b"\n")


def test_blank_world_preflight_creates_unique_empty_roots_without_public_paths(
    tmp_path: Path,
) -> None:
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        attempt_id="positive-clean",
        allowed_prerequisites={"git_commit": "a" * 40},
    )

    assert not roots.sqlite_path.exists()
    assert all(
        path.is_dir() and list(path.iterdir()) == []
        for name, path in roots.local_paths().items()
        if name not in {"attempt_root", "sqlite_path"}
    )
    proof_text = json.dumps(roots.proof, sort_keys=True)
    assert str(tmp_path) not in proof_text
    assert roots.proof["provider_cache_mode"] == "bypass"
    assert roots.proof["evidence_cache_reuse"] is False


def test_blank_world_preflight_rejects_preloaded_science(tmp_path: Path) -> None:
    attempt_root = tmp_path / "campaign" / "positive-preloaded"
    attempt_root.mkdir(parents=True)
    (attempt_root / "AOX_candidates.fasta").write_text(">old\nMOLD\n", encoding="utf-8")

    with pytest.raises(CutoverEvidenceError) as error:
        create_blank_world_roots(
            tmp_path / "campaign",
            attempt_kind="positive",
            attempt_id="positive-preloaded",
            allowed_prerequisites={},
        )

    assert error.value.code == "preloaded_science_detected"
    assert error.value.details["entries"] == ["AOX_candidates.fasta"]


def test_blank_world_preflight_rejects_science_in_allowed_prerequisites(
    tmp_path: Path,
) -> None:
    with pytest.raises(CutoverEvidenceError) as error:
        create_blank_world_roots(
            tmp_path / "campaign",
            attempt_kind="positive",
            attempt_id="positive-prerequisite",
            allowed_prerequisites={"alignment_fasta": ">cached\nMPEPTIDE\n"},
        )

    assert error.value.code == "allowed_prerequisite_field_forbidden"


def test_micu_snapshot_is_read_only_safe_and_keeps_the_fixed_ceiling(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "persistent-ledger.sqlite3"

    snapshot = safe_micu_ledger_snapshot(ledger)

    assert not ledger.exists()
    assert "path" not in snapshot
    assert snapshot["hard_limit_tokens"] == 100_000_000
    assert snapshot["charged_tokens"] == 0
    assert str(tmp_path) not in json.dumps(snapshot, sort_keys=True)


def test_untampered_positive_and_fault_bundles_verify_offline(tmp_path: Path) -> None:
    for attempt_kind in ("positive", "fault"):
        _, bundle_path, artifact_root = _build_bundle(
            tmp_path / attempt_kind,
            attempt_kind=attempt_kind,
        )

        result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

        assert result.passed, result.to_dict()
        assert result.attempt_kind == attempt_kind


@pytest.mark.parametrize(
    ("runtime_field", "identity_field"),
    (("image_digest", "image_digest"), ("pipeline_sdk_digest", "sdk_digest")),
)
def test_sandbox_preflight_identity_tamper_fails_offline_verification(
    tmp_path: Path,
    runtime_field: str,
    identity_field: str,
) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)

    def drift_runtime_identity(envelope: dict[str, object]) -> None:
        payload = envelope["payload"]
        launch = payload["product_path"]["launch_receipt"]
        launch["sandbox_runtime_identity"][runtime_field] = _digest(
            f"drift-{identity_field}"
        )
        envelope["bundle_digest"] = canonical_digest(payload)

    _rewrite_envelope(bundle_path, drift_runtime_identity)

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(
        issue.code == "sandbox_runtime_identity_drift" for issue in result.issues
    )


def test_nonempty_reference_chain_uses_exact_14_13_aab_plus_target_contract(
    tmp_path: Path,
) -> None:
    payload, bundle_path, artifact_root = _build_bundle(tmp_path)

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed, result.to_dict()
    chain = payload["scientific_checks"]["aox_chain"]
    assert chain["operation_roles"] == {
        **chain["operation_roles"],
        "hmm_reference_set_selection": "op_hmm_reference_set_selection",
        "scoring_reference_selection": "op_scoring_reference_selection",
        "scoring_input_assembly": "op_scoring_input_assembly",
    }
    artifact_by_id = {
        artifact["artifact_id"]: artifact for artifact in payload["artifacts"]
    }

    def artifact_bytes(role: str) -> bytes:
        artifact = artifact_by_id[chain["artifact_roles"][role]]
        return (artifact_root / artifact["relative_path"]).read_bytes()

    ncbi_bytes = artifact_bytes("ncbi_provider_sequences")
    hmm_reference_set_bytes = artifact_bytes("hmm_reference_set")
    scoring_reference_bytes = artifact_bytes("scoring_reference")
    target_bytes = artifact_bytes("target_sequences")
    scoring_input_bytes = artifact_bytes("scoring_input")
    hmm_result = aox_reference.select_hmm_reference_set(ncbi_bytes)
    scoring_reference_result = aox_reference.select_scoring_reference(ncbi_bytes)
    scoring_input_result = aox_reference.assemble_scoring_input(
        scoring_reference_bytes,
        target_bytes,
    )
    assert len(hmm_result.source_records) == 14
    assert [record.sequence_id for record in hmm_result.selected_records] == list(
        aox_reference.HMM_REFERENCE_ACCESSIONS
    )
    assert hmm_reference_set_bytes == hmm_result.to_fasta().encode("utf-8")
    assert scoring_reference_bytes == scoring_reference_result.to_fasta().encode(
        "utf-8"
    )
    assert scoring_input_bytes == scoring_input_result.to_fasta().encode("utf-8")
    assert scoring_input_result.records[0].sequence_id == "AAB57849.1"
    assert len(scoring_input_result.targets) > 0
    operations = {
        operation["operation_id"]: operation for operation in payload["operations"]
    }
    assert {
        item["artifact_id"] for item in operations["op_hmmalign"]["inputs"]
    } == {"art_hmm_model", "art_scoring_input"}


@pytest.mark.parametrize(
    "scientific_branch",
    ["nonempty", "hmmer_upstream_empty"],
)
def test_reference_chain_contract_tamper_fails_closed(
    tmp_path: Path,
    scientific_branch: str,
) -> None:
    def tamper_scoring_input_contract(evidence: dict[str, object]) -> None:
        operation = next(
            item
            for item in evidence["operations"]
            if item["operation_id"] == "op_scoring_input_assembly"
        )
        operation["parameters"] = {
            **dict(operation["parameters"]),
            "target_count": int(operation["parameters"]["target_count"]) + 1,
        }
        _refresh_sandbox_calculation_identity(operation)

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        scientific_branch=scientific_branch,
        mutate_evidence=tamper_scoring_input_contract,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(issue.code == "aox_reference_chain_invalid" for issue in result.issues)


@pytest.mark.parametrize(
    "scientific_branch",
    ["nonempty", "hmmer_upstream_empty"],
)
def test_reference_chain_rejects_rebound_incomplete_ncbi_provider_set(
    tmp_path: Path,
    scientific_branch: str,
) -> None:
    artifact_root = tmp_path / "campaign" / "positive-one" / "artifacts"

    def drop_coordinate_reference(evidence: dict[str, object]) -> None:
        artifact = next(
            item
            for item in evidence["artifacts"]
            if item["artifact_id"] == "art_ncbi_provider_sequences"
        )
        path = artifact_root / str(artifact["relative_path"])
        incomplete = path.read_bytes().rsplit(b">AAB57849.1\n", maxsplit=1)[0]
        digest = _replace_artifact_bytes(
            artifact_root,
            evidence,
            artifact_id="art_ncbi_provider_sequences",
            content=incomplete,
        )
        provider = next(
            item
            for item in evidence["provider_identities"]
            if item["provider"] == "ncbi"
        )
        provider["response_digest"] = digest
        _refresh_fixture_operation_identities(evidence)

    _, bundle_path, sealed_root = _build_bundle(
        tmp_path,
        scientific_branch=scientific_branch,
        mutate_evidence=drop_coordinate_reference,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=sealed_root)

    assert result.passed is False
    assert any(issue.code == "aox_reference_chain_invalid" for issue in result.issues)


def _wrap_ncbi_response_as_raw_envelope(
    evidence: dict[str, object],
    *,
    artifact_root: Path,
    malformed_tail: bool = False,
) -> None:
    reference_artifact = next(
        item
        for item in evidence["artifacts"]
        if item["artifact_id"] == "art_ncbi_provider_sequences"
    )
    reference_path = artifact_root / reference_artifact["relative_path"]
    raw = reference_path.read_bytes()
    raw_response_body = raw + b"\n"
    raw_digest = _digest_bytes(raw_response_body)
    response = {
        "ordinal": 1,
        "phase": "efetch",
        "status_code": 200,
        "headers": {},
        "body_encoding": "base64",
        "body_base64": base64.b64encode(raw_response_body).decode("ascii"),
        "body_digest": raw_digest,
        "size_bytes": len(raw_response_body),
    }
    responses = [response]
    if malformed_tail:
        responses.append(
            {
                **response,
                "ordinal": 2,
                "phase": "followup",
                "body_digest": _digest("wrong-tail-body"),
            }
        )
    envelope = {
        "schema_id": "provider_raw_http_response_set@1",
        "provider": "ncbi",
        "operation": "bio.ncbi_fetch_proteins",
        "responses": responses,
    }
    wrapped = canonical_json_bytes(envelope) + b"\n"
    raw_relative_path = "formal/provider/ncbi-raw-response.json"
    raw_path = artifact_root / raw_relative_path
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(wrapped)
    wrapped_digest = _digest_bytes(wrapped)
    provider = next(
        item for item in evidence["provider_identities"] if item["provider"] == "ncbi"
    )
    provider["response_digest"] = raw_digest
    provider["artifact_ids"].append("art_ncbi_raw_response")
    ncbi_operation = next(
        item
        for item in evidence["operations"]
        if item["operation_id"] == "op_ncbi"
    )
    ncbi_operation["outputs"].append(
        {
            "artifact_id": "art_ncbi_raw_response",
            "content_digest": wrapped_digest,
        }
    )
    _refresh_operation_identity(ncbi_operation)
    evidence["artifacts"].append(
        {
            "artifact_id": "art_ncbi_raw_response",
            "relative_path": raw_relative_path,
            "scope": "formal",
            "origin": "operation",
            "kind": "provider_evidence",
            "provenance": {
                "operation_id": "op_ncbi",
                "provider": "ncbi",
                "provider_artifact_kind": "provider_raw",
            },
        }
    )
    evidence["artifacts"] = [
        item for item in evidence["artifacts"] if item.get("origin") != "attestation"
    ]
    _attach_product_receipts(artifact_root, evidence, run_suffix=None)


def test_provider_response_digest_can_be_recomputed_from_raw_byte_envelope(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "campaign" / "positive-one" / "artifacts"

    def wrap_ncbi_response(evidence: dict[str, object]) -> None:
        _wrap_ncbi_response_as_raw_envelope(
            evidence,
            artifact_root=artifact_root,
        )

    _, bundle_path, sealed_root = _build_bundle(
        tmp_path,
        mutate_evidence=wrap_ncbi_response,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=sealed_root)

    assert result.passed, result.to_dict()


def test_provider_raw_envelope_validates_all_responses_before_digest_match(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "campaign" / "positive-one" / "artifacts"

    def add_malformed_tail(evidence: dict[str, object]) -> None:
        _wrap_ncbi_response_as_raw_envelope(
            evidence,
            artifact_root=artifact_root,
            malformed_tail=True,
        )

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=add_malformed_tail)

    assert error.value.code == "provider_artifact_lineage_invalid"


def test_fault_bundle_proves_real_byte_flip_and_terminal_failed_operation(
    tmp_path: Path,
) -> None:
    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        attempt_kind="fault",
    )
    envelope = json.loads(bundle_path.read_text(encoding="utf-8"))
    payload = envelope["payload"]
    fault = payload["fault_injection"]
    target = artifact_root / fault["relative_path"]
    mutated = target.read_bytes()
    restored = bytearray(mutated)
    restored[fault["byte_offset"]] ^= 1
    operations = {item["operation_id"]: item for item in payload["operations"]}

    assert fault["after_digest"] == _digest_bytes(mutated)
    assert fault["before_digest"] == _digest_bytes(bytes(restored))
    assert operations[fault["terminal_failure_operation_id"]]["status"] == "failed"
    assert operations[fault["terminal_failure_operation_id"]]["inputs"] == [
        {
            "artifact_id": fault["target_artifact_id"],
            "content_digest": fault["before_digest"],
        }
    ]
    assert verify_attempt_bundle(bundle_path, artifact_root=artifact_root).passed


def test_fault_self_declaration_cannot_replace_byte_proof(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        attempt_kind="fault",
    )

    def forge(envelope):
        envelope["payload"]["fault_injection"]["before_digest"] = _digest("forged")
        envelope["bundle_digest"] = canonical_digest(envelope["payload"])

    _rewrite_envelope(bundle_path, forge)

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "fault_byte_flip_proof_mismatch" for issue in result.issues
    )


def test_artifact_byte_tamper_reports_exact_artifact(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)

    fault = inject_artifact_byte_flip(
        artifact_root,
        relative_path="formal/motif-scores.csv",
        byte_offset=4,
    )
    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert fault["fault_id"] == FAULT_ARTIFACT_BYTE_FLIP_ID
    assert fault["reached_target_seam"] is True
    assert result.passed is False
    issue = next(
        item
        for item in result.issues
        if item.code == "artifact_content_digest_mismatch"
    )
    assert issue.identity == "artifact:art_scores:content"


def test_provenance_operation_report_and_bundle_tampering_are_located(
    tmp_path: Path,
) -> None:
    cases = {
        "provenance": (
            lambda envelope: envelope["payload"]["artifacts"][0]["provenance"].update(
                {"provider": "tampered"}
            ),
            "artifact_provenance_digest_mismatch",
        ),
        "operation": (
            lambda envelope: envelope["payload"]["operations"][0].update(
                {"status": "failed"}
            ),
            "record_digest_mismatch",
        ),
        "report": (
            lambda envelope: envelope["payload"]["report"].update({"status": "draft"}),
            "record_digest_mismatch",
        ),
        "bundle": (
            lambda envelope: envelope["payload"].update(
                {"warnings": ["tampered warning"]}
            ),
            "bundle_digest_mismatch",
        ),
    }
    for name, (mutate, expected_code) in cases.items():
        _, bundle_path, artifact_root = _build_bundle(tmp_path / name)
        _rewrite_envelope(bundle_path, mutate)

        result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

        assert result.passed is False
        assert expected_code in {issue.code for issue in result.issues}


def test_envelope_top_level_secret_is_rejected(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)
    _rewrite_envelope(
        bundle_path,
        lambda envelope: envelope.update({"api_key": "must-not-project"}),
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    codes = {issue.code for issue in result.issues}
    assert "bundle_envelope_invalid" in codes
    assert "public_projection_sensitive_key" in codes


def test_malformed_bundle_returns_issues_instead_of_crashing(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)
    _rewrite_envelope(
        bundle_path,
        lambda envelope: envelope["payload"].update({"report": "malformed"}),
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(issue.code == "bundle_field_type_invalid" for issue in result.issues)


def test_missing_artifact_issue_does_not_leak_host_path(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)
    (artifact_root / "formal/report.md").unlink()

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    issue = next(item for item in result.issues if item.code == "artifact_unreadable")
    assert str(tmp_path) not in issue.message


def test_eligible_positive_rejects_empty_provider_chain(tmp_path: Path) -> None:
    def remove_providers(evidence: dict[str, object]) -> None:
        evidence["provider_identities"] = []

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=remove_providers)

    assert error.value.code == "required_provider_chain_missing"


def test_required_pubmed_receipt_must_bind_real_pmid_artifact(tmp_path: Path) -> None:
    def change_declared_pmid(evidence: dict[str, object]) -> None:
        provider = next(
            item
            for item in evidence["provider_identities"]
            if item["provider"] == "pubmed"
        )
        provider["source_refs"][0]["pmid"] = "87654321"

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=change_declared_pmid)

    assert error.value.code == "pubmed_artifact_identity_mismatch"


def test_micu_overage_or_breach_cannot_enter_attempt_bundle(tmp_path: Path) -> None:
    breached = _ledger_snapshot(
        charged_tokens=100_000_000,
        attempt_count=2,
    )
    breached["hard_limit_overage_tokens"] = 1
    breached["hard_limit_breach_count"] = 1
    breached["reservation_overage_tokens"] = 1

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(
            tmp_path,
            ledger_before=_ledger_snapshot(),
            ledger_after=breached,
        )

    assert error.value.code == "micu_ledger_budget_invalid"


def test_report_content_tamper_is_detected_from_sealed_bytes(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)
    report_path = artifact_root / "formal/report.md"
    report_path.write_text("tampered report", encoding="utf-8")

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.identity == "artifact:art_report:content"
        and issue.code == "artifact_content_digest_mismatch"
        for issue in result.issues
    )


def test_scoring_is_recomputed_not_trusted_from_declared_digest(tmp_path: Path) -> None:
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        attempt_id="positive-wrong-score",
        allowed_prerequisites={"git_commit": "a" * 40},
    )
    evidence = _valid_evidence(
        roots.artifact_root,
        attempt_kind="positive",
        clean_world=roots.proof,
    )
    scored_path = roots.artifact_root / "formal/motif-scores.csv"
    scored_path.write_text(
        scored_path.read_text(encoding="utf-8").replace("33.6", "99.9", 1),
        encoding="utf-8",
    )
    payload = build_attempt_bundle(
        attempt_id=roots.attempt_id,
        attempt_kind="positive",
        identity=_identity(),
        clean_world=roots.proof,
        ledger_before=_ledger_snapshot(),
        ledger_after=_ledger_snapshot(charged_tokens=20, attempt_count=2),
        artifact_root=roots.artifact_root,
        evidence=evidence,
    )
    bundle_path = roots.evidence_root / "attempt-bundle.json"
    seal_attempt_bundle(payload, bundle_path)

    result = verify_attempt_bundle(bundle_path, artifact_root=roots.artifact_root)

    assert any(issue.code == "scoring_output_mismatch" for issue in result.issues)


def test_similarity_graph_is_recomputed_from_candidate_and_membership_bytes(
    tmp_path: Path,
) -> None:
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        attempt_id="positive-wrong-graph",
        allowed_prerequisites={"git_commit": "a" * 40},
    )
    evidence = _valid_evidence(
        roots.artifact_root,
        attempt_kind="positive",
        clean_world=roots.proof,
    )
    nodes_path = roots.artifact_root / "formal/graph-nodes.csv"
    nodes_path.write_text(
        nodes_path.read_text(encoding="utf-8").replace("1.000000", "0.999999", 1),
        encoding="utf-8",
    )
    payload = build_attempt_bundle(
        attempt_id=roots.attempt_id,
        attempt_kind="positive",
        identity=_identity(),
        clean_world=roots.proof,
        ledger_before=_ledger_snapshot(),
        ledger_after=_ledger_snapshot(charged_tokens=20, attempt_count=2),
        artifact_root=roots.artifact_root,
        evidence=evidence,
    )
    bundle_path = roots.evidence_root / "attempt-bundle.json"
    seal_attempt_bundle(payload, bundle_path)

    result = verify_attempt_bundle(bundle_path, artifact_root=roots.artifact_root)

    assert any(issue.code == "similarity_recompute_failed" for issue in result.issues)


def test_offline_verifier_rejects_non_finite_json_without_crashing(
    tmp_path: Path,
) -> None:
    bundle_path = tmp_path / "attempt-bundle.json"
    bundle_path.write_text('{"payload":{"value":NaN},"bundle_digest":"bad"}\n')

    result = verify_attempt_bundle(bundle_path, artifact_root=tmp_path)

    assert result.passed is False
    assert result.issues[0].code == "bundle_unreadable"


def test_bundle_rejects_artifact_symlink_even_when_target_stays_in_root(
    tmp_path: Path,
) -> None:
    roots = create_blank_world_roots(
        tmp_path / "campaign",
        attempt_kind="positive",
        attempt_id="positive-symlink",
        allowed_prerequisites={"git_commit": "a" * 40},
    )
    evidence = _valid_evidence(
        roots.artifact_root,
        attempt_kind="positive",
        clean_world=roots.proof,
    )
    report_path = roots.artifact_root / "formal/report.md"
    actual_path = roots.artifact_root / "formal/report-real.md"
    report_path.replace(actual_path)
    report_path.symlink_to(actual_path.name)

    with pytest.raises(CutoverEvidenceError) as error:
        build_attempt_bundle(
            attempt_id=roots.attempt_id,
            attempt_kind="positive",
            identity=_identity(),
            clean_world=roots.proof,
            ledger_before=_ledger_snapshot(),
            ledger_after=_ledger_snapshot(charged_tokens=20, attempt_count=2),
            artifact_root=roots.artifact_root,
            evidence=evidence,
        )

    assert error.value.code == "artifact_symlink_forbidden"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda evidence: evidence["provider_identities"][0].update(
                {"api_key": "forbidden"}
            ),
            "public_projection_sensitive_key",
        ),
        (
            lambda evidence: evidence["provider_identities"][0].update(
                {"diagnostic": "/tmp/provider/private.json"}
            ),
            "public_projection_host_path",
        ),
        (
            lambda evidence: evidence["provider_identities"][0].update(
                {"endpoint": "http://127.0.0.1:9000/private"}
            ),
            "public_projection_private_url",
        ),
    ],
)
def test_bundle_rejects_secret_and_private_path_projection(
    tmp_path: Path,
    mutation,
    code: str,
) -> None:
    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=mutation)

    assert error.value.code == code


def test_probe_artifacts_cannot_enter_formal_operation(tmp_path: Path) -> None:
    def contaminate(evidence: dict[str, object]) -> None:
        operation = next(
            item for item in evidence["operations"] if item["operation_id"] == "op_ncbi"
        )
        operation["inputs"] = [
            {
                "artifact_id": "art_probe_ncbi_fasta",
                "content_digest": _digest("probe"),
            }
        ]

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=contaminate)

    assert error.value.code == "probe_data_entered_formal_operation"


def test_known_positive_probe_cannot_pass_from_status_flags_only(
    tmp_path: Path,
) -> None:
    def detach_probe_receipt(evidence: dict[str, object]) -> None:
        evidence["known_positive_probe"]["provider_receipts"][0]["operation_id"] = (
            "op_ncbi"
        )

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=detach_probe_receipt)

    assert error.value.code == "known_positive_probe_receipt_invalid"


def test_known_positive_probe_v2_closes_the_globin_six_operation_dag(
    tmp_path: Path,
) -> None:
    payload, bundle_path, artifact_root = _build_bundle(tmp_path)

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed, result.to_dict()
    probe = payload["known_positive_probe"]
    assert probe["schema_id"] == KNOWN_POSITIVE_PROBE_SCHEMA_ID
    assert probe["probe_id"] == KNOWN_POSITIVE_PROBE_ID
    assert probe["operation_roles"] == {
        "ncbi_fetch": "op_probe_ncbi",
        "reference_alignment": "op_probe_mafft",
        "hmm_build": "op_probe_hmmbuild",
        "uniprot_fetch": "op_probe_uniprot",
        "candidate_cluster": "op_probe_cdhit",
        "candidate_alignment": "op_probe_hmmalign",
    }
    assert set(probe["artifact_roles"]) == {
        "source_snapshot",
        "ncbi_raw_response",
        "ncbi_fasta",
        "mafft_alignment",
        "hmm_model",
        "uniprot_raw_response",
        "uniprot_fasta",
        "cdhit_clustered_fasta",
        "cdhit_membership",
        "hmmalign_alignment",
    }
    probe_artifacts = {
        artifact["artifact_id"]: artifact
        for artifact in payload["artifacts"]
        if artifact["scope"] == "probe"
    }
    assert set(probe["artifact_ids"]) == set(probe_artifacts)
    assert len(probe_artifacts) == 10
    operations = {
        operation["operation_id"]: operation
        for operation in payload["operations"]
        if operation["scope"] == "probe"
    }
    assert len(operations) == 6
    for provider_receipt in probe["provider_receipts"]:
        raw_artifact = probe_artifacts[
            provider_receipt["raw_response_artifact_id"]
        ]
        envelope = json.loads(
            (artifact_root / raw_artifact["relative_path"]).read_text(
                encoding="utf-8"
            )
        )
        assert envelope["schema_id"] == "provider_raw_http_response_set@1"
        assert envelope["provider"] == provider_receipt["provider"]
        response = envelope["responses"][0]
        raw_body = base64.b64decode(response["body_base64"], validate=True)
        assert response["body_digest"] == _digest_bytes(raw_body)
        assert response["size_bytes"] == len(raw_body)
        assert provider_receipt["response_digest"] == response["body_digest"]
    assert operations["op_probe_ncbi"]["parameters"]["accessions"] == list(
        KNOWN_POSITIVE_PROBE_NCBI_ACCESSIONS
    )
    assert operations["op_probe_uniprot"]["parameters"]["accessions"] == list(
        KNOWN_POSITIVE_PROBE_UNIPROT_ACCESSIONS
    )
    cdhit_receipt = next(
        receipt
        for receipt in probe["toolchain_receipts"]
        if receipt["tool"] == "cd-hit"
    )
    assert cdhit_receipt["parameters"] == {"identity": 1.0, "mode": "protein"}
    snapshot = probe_artifacts[probe["artifact_roles"]["source_snapshot"]]
    isolation = probe["isolation"]
    assert snapshot["origin"] == "sandbox_run"
    assert snapshot["provenance"] == {
        **snapshot["provenance"],
        "producer": "sandbox_source_snapshot",
        "sandbox_run_id": isolation["sandbox_run_id"],
        "source_snapshot_digest": isolation["source_snapshot_digest"],
    }
    assert isolation["source_snapshot_artifact_digest"] == snapshot["content_digest"]


@pytest.mark.parametrize("provider", ["ncbi", "uniprot"])
def test_known_positive_probe_rejects_raw_provider_body_digest_tamper(
    tmp_path: Path,
    provider: str,
) -> None:
    artifact_root = tmp_path / "campaign" / "positive-one" / "artifacts"

    def tamper_raw_body(evidence: dict[str, object]) -> None:
        probe = evidence["known_positive_probe"]
        artifact_role = f"{provider}_raw_response"
        artifact_id = probe["artifact_roles"][artifact_role]
        artifact = next(
            item
            for item in evidence["artifacts"]
            if item["artifact_id"] == artifact_id
        )
        path = artifact_root / str(artifact["relative_path"])
        envelope = json.loads(path.read_text(encoding="utf-8"))
        body = base64.b64decode(
            envelope["responses"][0]["body_base64"],
            validate=True,
        )
        envelope["responses"][0]["body_base64"] = base64.b64encode(
            body + b"tamper"
        ).decode("ascii")
        path.write_bytes(canonical_json_bytes(envelope) + b"\n")

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=tamper_raw_body)

    assert error.value.code == "known_positive_probe_provider_invalid"


def test_known_positive_probe_rejects_weakened_cdhit_parameters(
    tmp_path: Path,
) -> None:
    def weaken_cdhit(evidence: dict[str, object]) -> None:
        receipt = next(
            item
            for item in evidence["known_positive_probe"]["toolchain_receipts"]
            if item["tool"] == "cd-hit"
        )
        receipt["parameters"] = {"identity": 0.85, "mode": "protein"}

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=weaken_cdhit)

    assert error.value.code == "known_positive_probe_toolchain_invalid"


def test_known_positive_probe_rejects_source_tree_isolation_drift(
    tmp_path: Path,
) -> None:
    def drift_source_tree(evidence: dict[str, object]) -> None:
        evidence["known_positive_probe"]["isolation"]["source_snapshot_digest"] = (
            _digest("different-probe-source-tree")
        )

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=drift_source_tree)

    assert error.value.code == "known_positive_probe_isolation_invalid"


def test_known_positive_probe_rejects_snapshot_sandbox_lineage_tamper(
    tmp_path: Path,
) -> None:
    def detach_snapshot(evidence: dict[str, object]) -> None:
        snapshot_id = evidence["known_positive_probe"]["artifact_roles"][
            "source_snapshot"
        ]
        snapshot = next(
            item
            for item in evidence["artifacts"]
            if item["artifact_id"] == snapshot_id
        )
        snapshot["provenance"]["sandbox_run_id"] = "sandbox_run_unbound"

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        mutate_evidence=detach_snapshot,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(
        issue.code == "sandbox_source_snapshot_lineage_invalid"
        for issue in result.issues
    )


def test_required_aox_dag_rejects_missing_digest_edge(tmp_path: Path) -> None:
    def remove_hmm_input(evidence: dict[str, object]) -> None:
        operation = next(
            item
            for item in evidence["operations"]
            if item["operation_id"] == "op_hmmbuild"
        )
        operation["inputs"] = []
        _refresh_operation_identity(operation)

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        mutate_evidence=remove_hmm_input,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "aox_operation_dag_edge_missing" for issue in result.issues
    )


def test_uniprot_source_cannot_bind_post_uniprot_filtered_hits(
    tmp_path: Path,
) -> None:
    payload, _, artifact_root = _build_bundle(tmp_path)
    operations = {item["operation_id"]: item for item in payload["operations"]}
    post_filter_output = next(
        dict(item)
        for item in operations["op_post_uniprot_filter"]["outputs"]
        if item["artifact_id"] == "art_post_uniprot_filtered_hits"
    )
    uniprot_operation = operations["op_uniprot"]
    uniprot_operation["inputs"] = [post_filter_output]
    uniprot_operation["parameters"] = {
        **dict(uniprot_operation["parameters"]),
        "source_hit_artifact": post_filter_output,
    }
    _refresh_operation_identity(uniprot_operation)
    uniprot_operation["record_digest"] = canonical_digest(
        {
            key: value
            for key, value in uniprot_operation.items()
            if key != "record_digest"
        }
    )
    cyclic_bundle_path = tmp_path / "cyclic-attempt-bundle.json"
    seal_attempt_bundle(payload, cyclic_bundle_path)

    result = verify_attempt_bundle(
        cyclic_bundle_path,
        artifact_root=artifact_root,
    )

    assert any(
        issue.code == "aox_provider_dependency_invalid" for issue in result.issues
    )


def test_hmmer_upstream_empty_is_accepted_only_from_recomputed_artifacts(
    tmp_path: Path,
) -> None:
    payload, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        scientific_branch="hmmer_upstream_empty",
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is True
    operations = {
        item["operation_id"]: item for item in payload["operations"]
    }
    assert "op_uniprot" not in operations
    assert "op_hmmalign" not in operations
    assert "op_cdhit" not in operations
    assert {
        "op_pre_uniprot_score_filter",
        "op_upstream_empty_materialization",
        "op_empty_target_scoring",
        "op_empty_membership",
    }.issubset(operations)
    chain = payload["scientific_checks"]["aox_chain"]
    assert chain["operation_roles"]["empty_target_scoring_materialization"] == (
        "op_empty_target_scoring"
    )
    artifact_by_id = {
        artifact["artifact_id"]: artifact for artifact in payload["artifacts"]
    }

    def artifact_bytes(role: str) -> bytes:
        artifact = artifact_by_id[chain["artifact_roles"][role]]
        return (artifact_root / artifact["relative_path"]).read_bytes()

    assert artifact_bytes("scoring_input") == artifact_bytes("scoring_reference")
    assert artifact_bytes("scoring_alignment") == artifact_bytes("scoring_reference")
    assert operations["op_scoring_input_assembly"]["parameters"]["target_count"] == 0
    uniprot = next(
        item
        for item in payload["provider_identities"]
        if item["provider"] == "uniprot"
    )
    assert uniprot == {
        **uniprot,
        "status": "upstream_empty",
        "canonical_ref_kind": "upstream_empty",
        "operation_id": None,
        "invocation_id": None,
        "request_digest": None,
        "response_digest": None,
        "provider_io_performed": False,
        "cache_consulted": False,
    }
    receipt_artifact = next(
        item
        for item in payload["artifacts"]
        if item["artifact_id"] == "art_uniprot_upstream_empty"
    )
    receipt_payload = json.loads(
        (artifact_root / receipt_artifact["relative_path"]).read_text(
            encoding="utf-8"
        )
    )
    assert receipt_payload["schema_id"] == "provider_upstream_empty_receipt@1"
    assert "request_digest" not in receipt_payload
    assert "response_digest" not in receipt_payload


def test_self_claimed_hmmer_empty_cannot_override_nonempty_derived_accessions(
    tmp_path: Path,
) -> None:
    def forge_empty_claim(evidence: dict[str, object]) -> None:
        chain = evidence["scientific_checks"]["aox_chain"]
        dependency = chain["provider_dependencies"][0]
        chain["empty_branch"] = {
            "schema_id": "aox_empty_branch@1",
            "stage": "pre_uniprot_score_filter",
            "reason": "no_filtered_hmmer_accessions",
            "trigger_artifact_id": dependency["derived_accession_artifact_id"],
            "trigger_artifact_digest": dependency[
                "derived_accession_artifact_digest"
            ],
            "observed_count_before": 2,
            "observed_count_after": 0,
            "derivation_operation_id": dependency["derivation_operation_id"],
            "skip_provider_record_id": "provider_record_uniprot",
            "omitted_controlled_roles": [],
            "empty_materialization_operation_id": None,
            "empty_membership_operation_id": None,
        }
        evidence["scientific_outcome"] = {
            "status": "empty",
            "candidate_count": 0,
            "empty_result_reason": "no_filtered_hmmer_accessions",
            "cutover_eligible": True,
        }

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        mutate_evidence=forge_empty_claim,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert result.passed is False
    assert any(
        issue.code
        in {
            "aox_empty_branch_invalid",
            "aox_operation_dag_schema_invalid",
            "scientific_outcome_artifact_mismatch",
        }
        for issue in result.issues
    )


@pytest.mark.parametrize("digest_field", ["request_digest", "response_digest"])
def test_upstream_empty_provider_receipt_rejects_fake_io_digests(
    tmp_path: Path,
    digest_field: str,
) -> None:
    def add_fake_io_digest(evidence: dict[str, object]) -> None:
        provider = next(
            item
            for item in evidence["provider_identities"]
            if item["provider"] == "uniprot"
        )
        provider[digest_field] = _digest(f"fake-{digest_field}")

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(
            tmp_path,
            scientific_branch="hmmer_upstream_empty",
            mutate_evidence=add_fake_io_digest,
        )

    assert error.value.code == "provider_receipt_invalid"


@pytest.mark.parametrize("tamper_target", ["provider", "dependency"])
def test_upstream_empty_provider_receipt_rejects_tampered_skip_digest(
    tmp_path: Path,
    tamper_target: str,
) -> None:
    def tamper_skip_digest(evidence: dict[str, object]) -> None:
        if tamper_target == "provider":
            provider = next(
                item
                for item in evidence["provider_identities"]
                if item["provider"] == "uniprot"
            )
            provider["skip_receipt_digest"] = _digest("tampered-provider-skip")
        else:
            dependency = evidence["scientific_checks"]["aox_chain"][
                "provider_dependencies"
            ][0]
            dependency["skip_receipt_digest"] = _digest(
                "tampered-dependency-skip"
            )

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(
            tmp_path,
            scientific_branch="hmmer_upstream_empty",
            mutate_evidence=tamper_skip_digest,
        )

    assert error.value.code == "provider_receipt_invalid"


def test_sequence_join_rejects_uniprot_mapping_tamper(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)
    metadata_path = artifact_root / "formal/provider/uniprot-metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["records"][0]["mapping_annotations"][0]["target_accession"] = "Q9ZZZ9"
    metadata_path.write_text(
        json.dumps(metadata, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "sequence_join_recompute_failed" for issue in result.issues
    )


def test_sequence_join_rejects_final_join_output_tamper(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)
    joined_hits_path = artifact_root / "formal/calculation/hits-len650-700-200.csv"
    joined_hits_path.write_bytes(joined_hits_path.read_bytes() + b"tampered\n")

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(issue.code == "sequence_join_output_mismatch" for issue in result.issues)


def test_required_aox_dag_rejects_failed_critical_operation(tmp_path: Path) -> None:
    def fail_hmm_build(evidence: dict[str, object]) -> None:
        operation = next(
            item
            for item in evidence["operations"]
            if item["operation_id"] == "op_hmmbuild"
        )
        operation["status"] = "failed"

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        mutate_evidence=fail_hmm_build,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "aox_required_operation_not_completed" for issue in result.issues
    )


def test_approval_cannot_be_reused_after_operation_inputs_change(
    tmp_path: Path,
) -> None:
    def change_approved_operation(evidence: dict[str, object]) -> None:
        operation = next(
            item
            for item in evidence["operations"]
            if item["operation_id"] == "op_hmmbuild"
        )
        operation["parameters"] = {"threshold_tenths": 59}
        _refresh_operation_identity(operation)

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        mutate_evidence=change_approved_operation,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "approval_operation_identity_mismatch" for issue in result.issues
    )


def test_approval_cannot_be_reused_after_operation_route_changes(
    tmp_path: Path,
) -> None:
    def change_approved_route(evidence: dict[str, object]) -> None:
        operation = next(
            item
            for item in evidence["operations"]
            if item["operation_id"] == "op_hmmbuild"
        )
        operation["selected_backend"] = "hpc"
        operation["route_policy_id"] = "bio_tools.score.hpc:v1"
        _refresh_operation_identity(operation)

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        mutate_evidence=change_approved_route,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "approval_operation_identity_mismatch" for issue in result.issues
    )


def test_provider_backend_run_must_match_invocation_receipt(tmp_path: Path) -> None:
    def replace_backend_run(evidence: dict[str, object]) -> None:
        operation = next(
            item for item in evidence["operations"] if item["operation_id"] == "op_ncbi"
        )
        operation["backend_run_id"] = "different_invocation"

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=replace_backend_run)

    assert error.value.code == "provider_operation_receipt_mismatch"


def test_tool_backend_run_must_match_hpc_job_receipt(tmp_path: Path) -> None:
    def replace_backend_run(evidence: dict[str, object]) -> None:
        operation = next(
            item
            for item in evidence["operations"]
            if item["operation_id"] == "op_align"
        )
        operation["backend_run_id"] = "different_job"

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, mutate_evidence=replace_backend_run)

    assert error.value.code == "toolchain_operation_receipt_mismatch"


def test_scientific_outcome_must_match_candidate_and_graph_artifacts(
    tmp_path: Path,
) -> None:
    def contradict_candidate_count(evidence: dict[str, object]) -> None:
        evidence["scientific_outcome"]["candidate_count"] = 0
        evidence["scientific_outcome"]["status"] = "empty"
        evidence["scientific_outcome"]["empty_result_reason"] = "no_candidates"

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        mutate_evidence=contradict_candidate_count,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "scientific_outcome_artifact_mismatch" for issue in result.issues
    )


def test_positive_micu_delta_must_belong_to_aox_scenario(tmp_path: Path) -> None:
    before = _ledger_snapshot()
    after = _ledger_snapshot(charged_tokens=20, attempt_count=2)
    before["by_scenario"][0]["scenario"] = "unrelated_live_test"
    after["by_scenario"][0]["scenario"] = "unrelated_live_test"

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(
            tmp_path,
            ledger_before=before,
            ledger_after=after,
        )

    assert error.value.code == "positive_micu_usage_unattributed"


def test_micu_group_totals_cannot_contradict_snapshot(tmp_path: Path) -> None:
    after = _ledger_snapshot(charged_tokens=20, attempt_count=2)
    after["by_model"][0]["charged_tokens"] = 19

    with pytest.raises(CutoverEvidenceError) as error:
        _build_bundle(tmp_path, ledger_after=after)

    assert error.value.code == "micu_ledger_group_invalid"


def test_fault_target_must_be_bound_to_completed_provider_receipt(
    tmp_path: Path,
) -> None:
    def detach_provider_artifact(evidence: dict[str, object]) -> None:
        provider = next(
            item
            for item in evidence["provider_identities"]
            if item["provider"] == "ebi_hmmer"
        )
        provider["artifact_ids"] = []

    _, bundle_path, artifact_root = _build_bundle(
        tmp_path,
        attempt_kind="fault",
        mutate_evidence=detach_provider_artifact,
    )

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(
        issue.code == "fault_operation_attestation_invalid" for issue in result.issues
    )


def test_product_receipt_bytes_are_parsed_and_bound_offline(tmp_path: Path) -> None:
    _, bundle_path, artifact_root = _build_bundle(tmp_path)
    receipt_path = artifact_root / "formal/attestation/workspace-projection.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["session_id"] = "sess_unbound"
    receipt_path.write_bytes(canonical_json_bytes(receipt) + b"\n")

    result = verify_attempt_bundle(bundle_path, artifact_root=artifact_root)

    assert any(issue.code == "product_receipt_mismatch" for issue in result.issues)


def test_campaign_derives_go_only_from_two_independent_positive_and_one_fault(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "persistent-ledger.sqlite3"
    ledger = LiveMicuTokenLedger(ledger_path, hard_limit_tokens=100_000_000)
    invocation_count = 0

    def charge_micu() -> None:
        nonlocal invocation_count
        invocation_count += 1
        reservation = ledger.reserve_attempt(
            scenario="aox_blank_world_cutover",
            purpose="positive_e2e",
            kind="tool_calling",
            model="micu-live",
            attempt=invocation_count,
            estimated_input_tokens=2,
            reserved_output_tokens=2,
        )
        ledger.reconcile_success(
            reservation,
            {"input_tokens": 2, "output_tokens": 2},
        )

    def positive_runner(context):
        charge_micu()
        return _valid_evidence(
            context.roots.artifact_root,
            attempt_kind="positive",
            clean_world=context.roots.proof,
            run_suffix=context.roots.attempt_id,
        )

    def fault_runner(context):
        return _valid_evidence(
            context.roots.artifact_root,
            attempt_kind="fault",
            clean_world=context.roots.proof,
            run_suffix=context.roots.attempt_id,
        )

    campaign = AoxCutoverCampaign(
        campaign_root=tmp_path / "campaign",
        identity=_identity(),
        ledger_path=ledger_path,
        positive_runner=positive_runner,
        fault_runner=fault_runner,
        allowed_prerequisites={"workflow_ref": _identity()["workflow_ref"]},
    )

    records, decision = campaign.run()

    assert len(records) == 3
    assert all(record.verification.passed for record in records)
    assert len({record.artifact_root.parent.name for record in records}) == 3
    assert decision["decision"] == "GO"
    assert decision["attempt_digests"] == [record.bundle_digest for record in records]
    assert decision["decision_digest"] == canonical_digest(
        {key: value for key, value in decision.items() if key != "decision_digest"}
    )


def test_campaign_rejects_reused_positive_runtime_receipts(tmp_path: Path) -> None:
    ledger_path = tmp_path / "persistent-ledger.sqlite3"
    ledger = LiveMicuTokenLedger(ledger_path, hard_limit_tokens=100_000_000)
    invocation_count = 0

    def charge_micu() -> None:
        nonlocal invocation_count
        invocation_count += 1
        reservation = ledger.reserve_attempt(
            scenario="aox_blank_world_cutover",
            purpose="positive_e2e",
            kind="tool_calling",
            model="micu-live",
            attempt=invocation_count,
            estimated_input_tokens=1,
            reserved_output_tokens=1,
        )
        ledger.reconcile_success(
            reservation,
            {"input_tokens": 1, "output_tokens": 1},
        )

    def positive_runner(context):
        charge_micu()
        return _valid_evidence(
            context.roots.artifact_root,
            attempt_kind="positive",
            clean_world=context.roots.proof,
        )

    def fault_runner(context):
        return _valid_evidence(
            context.roots.artifact_root,
            attempt_kind="fault",
            clean_world=context.roots.proof,
            run_suffix=context.roots.attempt_id,
        )

    campaign = AoxCutoverCampaign(
        campaign_root=tmp_path / "campaign",
        identity=_identity(),
        ledger_path=ledger_path,
        positive_runner=positive_runner,
        fault_runner=fault_runner,
        allowed_prerequisites={"workflow_ref": _identity()["workflow_ref"]},
    )

    records, decision = campaign.run()

    assert len(records) == 3
    assert all(record.verification.passed for record in records)
    assert decision["decision"] == "NO-GO"
    assert decision["blocker"]["code"] == "campaign_positive_not_independent"


def test_fault_runner_exception_is_sealed_and_campaign_stays_no_go(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "persistent-ledger.sqlite3"
    ledger = LiveMicuTokenLedger(ledger_path, hard_limit_tokens=100_000_000)
    invocation_count = 0

    def positive_runner(context):
        nonlocal invocation_count
        invocation_count += 1
        reservation = ledger.reserve_attempt(
            scenario="aox_blank_world_cutover",
            purpose="positive_e2e",
            kind="tool_calling",
            model="micu-live",
            attempt=invocation_count,
            estimated_input_tokens=1,
            reserved_output_tokens=1,
        )
        ledger.reconcile_success(
            reservation,
            {"input_tokens": 1, "output_tokens": 1},
        )
        return _valid_evidence(
            context.roots.artifact_root,
            attempt_kind="positive",
            clean_world=context.roots.proof,
            run_suffix=context.roots.attempt_id,
        )

    def fault_runner(context):
        del context
        raise RuntimeError("private fault runner detail")

    campaign = AoxCutoverCampaign(
        campaign_root=tmp_path / "campaign",
        identity=_identity(),
        ledger_path=ledger_path,
        positive_runner=positive_runner,
        fault_runner=fault_runner,
        allowed_prerequisites={"workflow_ref": _identity()["workflow_ref"]},
    )

    records, decision = campaign.run()

    assert len(records) == 3
    assert records[-1].verification.passed is True
    assert decision["decision"] == "NO-GO"
    assert decision["blocker"]["code"] == "fault_not_fail_closed"


def test_campaign_remains_no_go_for_missing_or_unverified_attempt() -> None:
    failed = AttemptRunRecord(
        attempt_id="positive-failed",
        attempt_kind="positive",
        bundle_path=Path("missing.json"),
        artifact_root=Path("missing-artifacts"),
        bundle_digest=_digest("failed"),
        verification=VerificationResult(
            passed=False,
            bundle_digest=_digest("failed"),
            attempt_id="positive-failed",
            attempt_kind="positive",
            issues=(),
        ),
    )

    decision = evaluate_campaign([failed], decided_at="2026-07-17T00:00:00+00:00")

    assert decision["decision"] == "NO-GO"
    assert decision["blocker"]["code"] == "attempt_verification_failed"


def test_campaign_runner_failure_is_sealed_as_safe_no_go_evidence(
    tmp_path: Path,
) -> None:
    def failing_runner(context):
        del context
        raise RuntimeError("private /tmp/detail and api_key=must-not-project")

    campaign = AoxCutoverCampaign(
        campaign_root=tmp_path / "campaign",
        identity=_identity(),
        ledger_path=tmp_path / "persistent-ledger.sqlite3",
        positive_runner=failing_runner,
        fault_runner=failing_runner,
        allowed_prerequisites={"workflow_ref": _identity()["workflow_ref"]},
    )

    records, decision = campaign.run()

    assert len(records) == 1
    assert records[0].verification.passed is True
    assert decision["decision"] == "NO-GO"
    assert decision["blocker"]["code"] == "campaign_runner_failed"
    serialized = records[0].bundle_path.read_text(encoding="utf-8")
    assert "must-not-project" not in serialized
    assert str(tmp_path) not in serialized


def test_campaign_decision_is_digest_checked_and_append_only(tmp_path: Path) -> None:
    decision = evaluate_campaign([], decided_at="2026-07-17T00:00:00+00:00")
    destination = tmp_path / "campaign-decision.json"

    digest = seal_campaign_decision(decision, destination)

    assert digest == decision["decision_digest"]
    assert destination.stat().st_mode & 0o222 == 0
    with pytest.raises(CutoverEvidenceError) as error:
        seal_campaign_decision(decision, destination)
    assert error.value.code == "campaign_decision_append_only"


def test_cli_decide_returns_structured_no_go_for_unreadable_bundle(
    tmp_path: Path,
    capsys,
) -> None:
    exit_code = cutover_cli_main(
        [
            "decide",
            "--attempt",
            str(tmp_path / "missing-bundle.json"),
            str(tmp_path / "missing-artifacts"),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert output["decision"] == "NO-GO"
    assert output["blocker"]["code"] == "attempt_verification_failed"
