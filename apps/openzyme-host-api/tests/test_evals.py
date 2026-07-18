from __future__ import annotations

import csv
from dataclasses import replace
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import subprocess

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import SandboxImageCompatibility
from openzyme_domain import SandboxRunRecord
from openzyme_domain import SandboxRunStatus
from openzyme_domain import SandboxWorkspaceRecord
from openzyme_domain import SandboxWorkspaceStatus
from openzyme_domain import Session
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SessionStatus
from openzyme_host_api.evals import S15_AOX_HMM_FIXED_DELIVERABLES
from openzyme_host_api.evals import S15_AOX_HMM_FIXTURE_SCENARIO_ID
from openzyme_host_api.evals import S15_AOX_HMM_OLD_DELIVERABLES
from openzyme_host_api.evals import S15_AOX_HMM_SCENARIO_ID
from openzyme_host_api.evals import S15_ROUTE_POLICY_IDS
from openzyme_host_api.evals import AOX_HMM_ACCESSIONS
from openzyme_host_api.evals import AOX_NCBI_ACCESSIONS
from openzyme_host_api.evals import _s15_aox_validate_final_artifacts
from openzyme_host_api.evals import _s15_bootstrap_live_sandbox_image
from openzyme_host_api.evals import _s15_build_evidence_bundle
from openzyme_host_api.evals import _s15_event_text_has_legacy_execution_pipeline
from openzyme_host_api.evals import _s15_live_prerequisite_report
from openzyme_host_api.evals import _s15_live_workspace_ready
from openzyme_host_api.evals import _run_v3_aox_hmm_prompt_scenario
from openzyme_host_api.evals import _s15_validate_evidence_bundle
from openzyme_host_api.evals import _s15_validate_live_product_path
from openzyme_host_api.evals import build_local_eval_runtime
from openzyme_host_api.evals import run_v3_local_evals
from openzyme_host_api.evals import run_v3_s15_live_evals
from openzyme_pipeline import aox_hmmer
from openzyme_pipeline import aox_motif
from openzyme_pipeline import aox_reference
from openzyme_pipeline import aox_sequence_join
from openzyme_pipeline import aox_similarity
from openzyme_runtime import reset_settings_cache


@pytest.fixture(scope="module")
def local_eval_summary() -> dict[str, object]:
    return run_v3_local_evals(upload_results=False)


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _canonical_hmmer_provider_row(
    *,
    accession: str,
    target: str,
    score: str,
    evalue: str,
    hit_index: int,
) -> dict[str, str]:
    score_decimal = Decimal(score)
    evalue_decimal = Decimal(evalue)
    payload: dict[str, object] = {
        "target": target,
        "accession": accession,
        "evalue": evalue,
        "score": score,
        "page": 1,
        "hit_index": hit_index,
        "evalue_numeric": (
            str(evalue_decimal.normalize()) if evalue_decimal else "0"
        ),
        "score_numeric": str(score_decimal.normalize()) if score_decimal else "0",
        "raw_page_digest": _sha256(b"canonical-hmmer-page-1"),
        "raw_hit_digest": _sha256(f"canonical-hmmer-hit-{hit_index}".encode()),
    }
    parsed_row_bytes = (
        json.dumps(payload, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    payload["parsed_row_digest"] = _sha256(parsed_row_bytes)
    return {column: str(payload[column]) for column in aox_hmmer.INPUT_COLUMNS}


def _canonical_hmmer_provider_csv(rows: list[dict[str, str]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=list(aox_hmmer.INPUT_COLUMNS),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _canonical_aox_test_artifacts(
    *,
    empty: bool = False,
) -> tuple[dict[str, str], dict[str, dict[str, object]]]:
    repository_root = Path(__file__).parents[3]
    golden_path = (
        repository_root
        / "packages/openzyme-pipeline/tests/fixtures/aox_motif_rule_score_v1/alignment.fasta"
    )
    golden = aox_motif.parse_aligned_fasta(golden_path.read_text(encoding="utf-8"))
    reference_record = next(
        record
        for record in golden.records
        if record.sequence_id == aox_motif.REFERENCE_ACCESSION
    )
    golden_candidate = next(
        record for record in golden.records if record.sequence_id == "K3VE05_FUSPC"
    )
    candidate_id = "K3VE05"
    candidate_alignment = golden_candidate.aligned_sequence
    if empty:
        candidate_characters = list(candidate_alignment)
        candidate_characters[12] = "A"
        candidate_alignment = "".join(candidate_characters)
    candidate_sequence = candidate_alignment.replace("-", "")
    scoring_alignment = (
        f">{reference_record.sequence_id} {reference_record.description}\n"
        f"{reference_record.aligned_sequence}\n"
        f">{candidate_id} {golden_candidate.description}\n"
        f"{candidate_alignment}\n"
    )
    scoring = aox_motif.score_aligned_fasta(scoring_alignment)
    target_fasta = f">{candidate_id}\n{candidate_sequence}\n"
    candidate_fasta = "" if empty else target_fasta
    membership_csv = ",".join(aox_similarity.MEMBERSHIP_COLUMNS) + "\n"
    representative_fasta = ""
    if not empty:
        membership_csv += (
            f"cluster_0,{candidate_id},{candidate_id},true,1.000000,"
            f"{len(candidate_sequence)}\n"
        )
        representative_fasta = candidate_fasta
    empty_reason = "no_candidates_after_motif_filter" if empty else None
    graph = aox_similarity.build_similarity_graph(
        candidate_fasta,
        membership_csv,
        empty_result_reason=empty_reason,
    )

    alphabet = "ACDEFGHIKLMNPQRSTVWY"
    ncbi_records: list[str] = []
    for index, accession in enumerate(AOX_NCBI_ACCESSIONS):
        source_id = "pdb|9AVH|A" if accession == "9AVH_A" else accession
        sequence = (
            reference_record.sequence
            if accession == aox_reference.SCORING_REFERENCE_ACCESSION
            else "".join(
                alphabet[(position + index) % len(alphabet)]
                for position in range(663)
            )
        )
        ncbi_records.append(f">{source_id} provider-resolved reference\n{sequence}\n")
    ncbi_reference_fasta = "".join(ncbi_records)
    hmm_reference_selection = aox_reference.select_hmm_reference_set(
        ncbi_reference_fasta
    )
    scoring_reference_selection = aox_reference.select_scoring_reference(
        ncbi_reference_fasta
    )
    reference_fasta = hmm_reference_selection.to_fasta()
    scoring_reference_fasta = scoring_reference_selection.to_fasta()
    scoring_input = aox_reference.assemble_scoring_input(
        scoring_reference_fasta,
        target_fasta,
    )

    hits_filtered = (
        "target,uniprot_accession,hmm_score,evalue,length,sequence\n"
        f"target_1,{candidate_id},250,1e-40,{len(candidate_sequence)},"
        f"{candidate_sequence}\n"
    )
    hmmer_rows = [
        _canonical_hmmer_provider_row(
            accession=candidate_id,
            target="target_1",
            score="250",
            evalue="1e-40",
            hit_index=0,
        )
    ]
    hits_raw = _canonical_hmmer_provider_csv(hmmer_rows)
    score_filter_result = aox_hmmer.parse_and_filter_csv(hits_raw)

    graph_manifest = graph.manifest_json()
    scientific_branch = "motif_filter_empty" if empty else "nonempty"
    omitted_operation_roles = ["cdhit"] if empty else []
    summary: dict[str, object] = {
        "accession_count": len(AOX_HMM_ACCESSIONS),
        "ncbi_reference_accession_count": len(AOX_NCBI_ACCESSIONS),
        "filtered_hit_count": 1,
        "scoring_row_count": len(scoring.rows),
        "candidate_count": int(not empty),
        "representative_count": int(not empty),
        "graph_node_count": len(graph.nodes),
        "graph_edge_count": len(graph.edges),
        "length_filter": [650, 700],
        "hmm_score_threshold": 200,
        "motif_rule_score_threshold_tenths": aox_motif.THRESHOLD_TENTHS,
        "motif_rule_score_threshold": aox_motif.THRESHOLD_DISPLAY,
        "similarity_threshold_ppm": aox_similarity.DEFAULT_THRESHOLD_PPM,
        "similarity_threshold": "0.850000",
        "hmmer_database": "refprot",
        "hmmer_score_filter_contract_id": aox_hmmer.CONTRACT_ID,
        "hmmer_score_filter_contract_digest": aox_hmmer.CONTRACT_DIGEST,
        "hmmer_score_filter_implementation_digest": aox_hmmer.IMPLEMENTATION_DIGEST,
        "hmmer_score_filter_input_digest": score_filter_result.input_digest,
        "hmmer_score_filter_output_digest": score_filter_result.output_digest,
        "sequence_length_join_contract_id": aox_sequence_join.CONTRACT_ID,
        "sequence_length_join_contract_digest": aox_sequence_join.CONTRACT_DIGEST,
        "sequence_length_join_implementation_digest": (
            aox_sequence_join.IMPLEMENTATION_DIGEST
        ),
        "sequence_length_join_hits_digest": _sha256(hits_filtered.encode("utf-8")),
        "sequence_length_join_target_digest": _sha256(target_fasta.encode("utf-8")),
        "hmm_reference_set_selection_contract_id": (
            aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID
        ),
        "hmm_reference_set_selection_contract_digest": (
            aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
        ),
        "hmm_reference_set_selection_implementation_digest": (
            aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
        ),
        "hmm_reference_set_input_digest": hmm_reference_selection.input_digest,
        "hmm_reference_set_output_digest": hmm_reference_selection.output_digest,
        "scoring_reference_selection_contract_id": (
            aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID
        ),
        "scoring_reference_selection_contract_digest": (
            aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST
        ),
        "scoring_reference_selection_implementation_digest": (
            aox_reference.SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
        ),
        "scoring_reference_selection_input_digest": (
            scoring_reference_selection.input_digest
        ),
        "scoring_reference_output_digest": scoring_reference_selection.output_digest,
        "scoring_input_assembly_contract_id": (
            aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID
        ),
        "scoring_input_assembly_contract_digest": (
            aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST
        ),
        "scoring_input_assembly_implementation_digest": (
            aox_reference.SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST
        ),
        "scoring_reference_input_digest": (
            scoring_input.scoring_reference_input_digest
        ),
        "post_uniprot_target_input_digest": scoring_input.target_input_digest,
        "scoring_contract_id": aox_motif.CONTRACT_ID,
        "scoring_contract_digest": aox_motif.CONTRACT_DIGEST,
        "scoring_implementation_digest": aox_motif.IMPLEMENTATION_DIGEST,
        "scoring_reference_accession": aox_motif.REFERENCE_ACCESSION,
        "scoring_input_digest": scoring_input.output_digest,
        "scoring_alignment_input_digest": scoring.alignment.input_digest,
        "scoring_alignment_digest": scoring.alignment.alignment_digest,
        "cdhit_membership_schema_id": aox_similarity.MEMBERSHIP_SCHEMA_ID,
        "similarity_calculation_id": aox_similarity.CALCULATION_ID,
        "similarity_calculation_digest": aox_similarity.CALCULATION_DIGEST,
        "similarity_implementation_digest": aox_similarity.IMPLEMENTATION_DIGEST,
        "candidate_graph_manifest_schema_id": aox_similarity.MANIFEST_SCHEMA_ID,
        "candidate_graph_node_schema_id": aox_similarity.NODE_SCHEMA_ID,
        "candidate_graph_edge_schema_id": aox_similarity.EDGE_SCHEMA_ID,
        "candidate_graph_manifest_digest": (
            "sha256:" + hashlib.sha256(graph_manifest.encode("utf-8")).hexdigest()
        ),
        "scientific_outcome": "empty" if empty else "candidates_found",
        "scientific_branch": scientific_branch,
        "omitted_operation_roles": omitted_operation_roles,
        "upstream_empty_skip_receipt_digest": None,
        "provider_status": "complete",
        "tool_status": "complete",
        "warning_count": 1 if empty else 0,
        "artifact_ids": [
            f"artifact_{index}"
            for index, _ in enumerate(sorted(S15_AOX_HMM_FIXED_DELIVERABLES), start=1)
        ],
        "normalized_final_deliverable_paths": sorted(S15_AOX_HMM_FIXED_DELIVERABLES),
    }
    if empty_reason is not None:
        summary["empty_result"] = {
            "reason": empty_reason,
            "scientific_branch": scientific_branch,
            "omitted_operation_roles": omitted_operation_roles,
        }

    text = {
        "aox_hmm/AOX_ref21.fasta": reference_fasta,
        "aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta": (
            scoring_reference_fasta
        ),
        "aox_hmm/AOX_scoring_input.fasta": scoring_input.to_fasta(),
        "aox_hmm/target.fasta": target_fasta,
        "aox_hmm/AOX_ref.hmm": "HMMER3/f [aox]\nNAME AOX_ref\n//\n",
        "aox_hmm/hits_raw.csv": hits_raw,
        "aox_hmm/hmmer_score_filtered_accessions.csv": (
            score_filter_result.to_csv()
        ),
        "aox_hmm/hits_len650_700_200.csv": hits_filtered,
        "aox_hmm/AOX_scoring_alignment.fasta": scoring_alignment,
        "aox_hmm/scored_ref_plus_hits.csv": scoring.to_csv(),
        "aox_hmm/AOX_candidates.fasta": candidate_fasta,
        "aox_hmm/AOX_candidates_cdhit85.fasta": representative_fasta,
        "aox_hmm/AOX_candidates_cdhit85.clusters.csv": membership_csv,
        "aox_hmm/nodes.csv": graph.nodes_csv(),
        "aox_hmm/edges_similarity.csv": graph.edges_csv(),
        "aox_hmm/similarity_graph_manifest.json": graph_manifest,
        "aox_hmm/execution_summary.json": json.dumps(summary, sort_keys=True) + "\n",
    }
    shared_reference_metadata = {
        "source_ncbi_fasta_artifact_id": "artifact_ncbi_provider_fasta",
        "provider_request_ids": ["provider_req_1"],
        "ncbi_reference_accessions": list(AOX_NCBI_ACCESSIONS),
    }
    metadata = {
        "aox_hmm/AOX_ref21.fasta": {
            **hmm_reference_selection.metadata(),
            "accession_count": len(AOX_HMM_ACCESSIONS),
            **shared_reference_metadata,
        },
        "aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta": {
            **scoring_reference_selection.metadata(),
            **shared_reference_metadata,
        },
        "aox_hmm/AOX_scoring_input.fasta": {
            **scoring_input.metadata(),
            "source_scoring_reference_artifact_id": "artifact_scoring_reference",
            "source_target_fasta_artifact_id": "artifact_target",
        },
        "aox_hmm/AOX_ref.hmm": {
            "source_reference_fasta_artifact_id": "artifact_ref",
            "source_reference_fasta_digest": hmm_reference_selection.output_digest,
            "mafft_artifact_ids": ["artifact_alignment"],
            "hmmbuild_artifact_ids": ["artifact_hmm"],
        },
        "aox_hmm/hmmer_score_filtered_accessions.csv": {
            **score_filter_result.metadata(),
            "source_provider_parsed_artifact_id": "artifact_hmmer_parsed_hits",
        },
        "aox_hmm/AOX_scoring_alignment.fasta": {
            "source_hmm_artifact_id": "artifact_hmm",
            "source_hmm_digest": _sha256(
                b"HMMER3/f [aox]\nNAME AOX_ref\n//\n"
            ),
            "source_scoring_input_artifact_id": "artifact_scoring_input",
            "source_scoring_input_digest": scoring_input.output_digest,
            "alignment_operation_artifact_ids": ["artifact_hmmalign"],
            "reference_accession": aox_motif.REFERENCE_ACCESSION,
        },
        "aox_hmm/scored_ref_plus_hits.csv": {
            **scoring.metadata(),
            "source_alignment_artifact_id": "artifact_scoring_alignment",
        },
        "aox_hmm/AOX_candidates.fasta": {
            "source_scored_artifact_id": "artifact_scored",
            "source_alignment_artifact_id": "artifact_scoring_alignment",
        },
        "aox_hmm/AOX_candidates_cdhit85.fasta": {
            "source_candidate_fasta_artifact_id": "artifact_candidates",
            "source_membership_artifact_id": "artifact_membership",
            "cdhit_operation_artifact_ids": (
                [] if empty else ["artifact_cdhit_output"]
            ),
        },
        "aox_hmm/AOX_candidates_cdhit85.clusters.csv": {
            "membership_schema_id": aox_similarity.MEMBERSHIP_SCHEMA_ID,
            "source_candidate_fasta_artifact_id": "artifact_candidates",
            "cdhit_identity_ppm": aox_similarity.DEFAULT_THRESHOLD_PPM,
            "cdhit_operation_artifact_ids": (
                [] if empty else ["artifact_cdhit_output"]
            ),
            "empty_result_reason": empty_reason,
        },
        "aox_hmm/similarity_graph_manifest.json": {
            "manifest_schema_id": aox_similarity.MANIFEST_SCHEMA_ID,
            "node_schema_id": aox_similarity.NODE_SCHEMA_ID,
            "edge_schema_id": aox_similarity.EDGE_SCHEMA_ID,
            "similarity_calculation_id": aox_similarity.CALCULATION_ID,
            "similarity_calculation_digest": aox_similarity.CALCULATION_DIGEST,
            "similarity_implementation_digest": aox_similarity.IMPLEMENTATION_DIGEST,
            "source_candidate_fasta_artifact_id": "artifact_candidates",
            "source_membership_artifact_id": "artifact_membership",
            "nodes_artifact_id": "artifact_nodes",
            "edges_artifact_id": "artifact_edges",
        },
    }
    return text, metadata


def test_v3_local_eval_covers_cutover_design_path(
    local_eval_summary: dict[str, object],
) -> None:
    summary = local_eval_summary
    assert summary["scenario_count"] == 2
    assert summary["failed"] == 0
    result = next(
        item
        for item in summary["results"]
        if item["scenario_id"] == "v3_design_cutover_path"
    )
    assert result["scenario_id"] == "v3_design_cutover_path"
    assert result["task_count"] == 3
    assert set(result["agent_roles"]) >= {"researcher", "executor", "reporter"}
    assert set(result["capability_keys"]) >= {"deep_research", "execution"}
    assert result["report_count"] == 1
    assert all(result["checks"].values())


def test_v3_local_eval_covers_aox_hmm_prompt_e2e(
    local_eval_summary: dict[str, object],
) -> None:
    summary = local_eval_summary
    result = next(
        item
        for item in summary["results"]
        if item["scenario_id"] == S15_AOX_HMM_FIXTURE_SCENARIO_ID
    )
    assert result["scenario_class"] == "fixture"
    assert result["status"] == "passed"
    assert result["live_cutover_eligible"] is False
    assert result["task_count"] == 1
    assert (
        result["candidate_count"]
        == result["final_output_validation"]["candidate_count"]
    )
    assert set(result["required_artifacts"]) == S15_AOX_HMM_FIXED_DELIVERABLES
    assert result["legacy_artifacts"] == []
    assert result["final_output_validation"]["passed"] is False
    assert result["checks"]["final_output_validation"] is False
    assert not (S15_AOX_HMM_OLD_DELIVERABLES & set(result["required_artifacts"]))
    fixture_control_checks = {
        key: value
        for key, value in result["checks"].items()
        if key
        not in {
            "required_artifacts",
            "candidate85_artifact",
            "final_output_validation",
            "evidence_bundle_complete",
            "canonical_product_roles",
            "explicit_task_business_exits",
            "required_pubmed_evidence",
            "published_report",
        }
    }
    assert all(fixture_control_checks.values())


def test_s15_final_output_validator_rejects_legacy_only_outputs() -> None:
    legacy_only = set(S15_AOX_HMM_OLD_DELIVERABLES)

    validation = _s15_aox_validate_final_artifacts(legacy_only, {})

    assert validation["passed"] is False
    error_codes = {error["error_code"] for error in validation["errors"]}
    assert "live_artifact_missing" in error_codes
    assert "legacy_artifact_path_forbidden" in error_codes
    assert validation["legacy_paths"] == sorted(S15_AOX_HMM_OLD_DELIVERABLES)


def test_s15_final_output_validator_enforces_fixed_thresholds_and_provenance() -> None:
    valid_text, valid_metadata = _canonical_aox_test_artifacts()

    accepted = _s15_aox_validate_final_artifacts(
        set(S15_AOX_HMM_FIXED_DELIVERABLES),
        valid_text,
        valid_metadata,
    )
    broken_text = dict(valid_text)
    scored_lines = broken_text["aox_hmm/scored_ref_plus_hits.csv"].splitlines()
    scored_fields = scored_lines[1].split(",")
    score_index = list(aox_motif.CANONICAL_COLUMNS).index("motif_rule_score_tenths")
    scored_fields[score_index] = "999"
    scored_lines[1] = ",".join(scored_fields)
    broken_text["aox_hmm/scored_ref_plus_hits.csv"] = "\n".join(scored_lines) + "\n"
    broken_text["aox_hmm/execution_summary.json"] = broken_text[
        "aox_hmm/execution_summary.json"
    ].replace(
        '"refprot"',
        '"nr"',
    )
    broken_metadata = {
        "aox_hmm/AOX_ref21.fasta": {"accession_count": 12},
        "aox_hmm/AOX_ref.hmm": {"source_reference_fasta_artifact_id": "artifact_ref"},
    }

    rejected = _s15_aox_validate_final_artifacts(
        set(S15_AOX_HMM_FIXED_DELIVERABLES),
        broken_text,
        broken_metadata,
    )

    assert accepted["passed"] is True
    error_codes = {error["error_code"] for error in rejected["errors"]}
    assert rejected["passed"] is False
    assert {
        "motif_scoring_recalculation_mismatch",
        "invalid_execution_summary_value",
        "invalid_accession_count",
        "provider_provenance_incomplete",
        "hmm_provenance_incomplete",
    } <= error_codes


def test_s15_final_output_validator_rejects_reference_chain_drift() -> None:
    text, metadata = _canonical_aox_test_artifacts()
    reference_lines = text["aox_hmm/AOX_ref21.fasta"].splitlines()
    reference_records = [
        reference_lines[index : index + 2]
        for index in range(0, len(reference_lines), 2)
    ]
    reference_records[0], reference_records[1] = (
        reference_records[1],
        reference_records[0],
    )
    text["aox_hmm/AOX_ref21.fasta"] = (
        "\n".join(line for record in reference_records for line in record) + "\n"
    )
    metadata["aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta"][
        "input_digest"
    ] = _sha256(b"different-ncbi-input")

    validation = _s15_aox_validate_final_artifacts(
        set(S15_AOX_HMM_FIXED_DELIVERABLES),
        text,
        metadata,
    )

    error_codes = {error["error_code"] for error in validation["errors"]}
    assert validation["passed"] is False
    assert {
        "hmm_reference_identity_order_mismatch",
        "reference_selection_source_mismatch",
    } <= error_codes


def test_s15_final_output_validator_recomputes_scoring_input_assembly() -> None:
    text, metadata = _canonical_aox_test_artifacts()
    scoring_input_lines = text["aox_hmm/AOX_scoring_input.fasta"].splitlines()
    target_header_index = scoring_input_lines.index(">K3VE05")
    scoring_input_lines = (
        scoring_input_lines[target_header_index:]
        + scoring_input_lines[:target_header_index]
    )
    text["aox_hmm/AOX_scoring_input.fasta"] = (
        "\n".join(scoring_input_lines) + "\n"
    )

    validation = _s15_aox_validate_final_artifacts(
        set(S15_AOX_HMM_FIXED_DELIVERABLES),
        text,
        metadata,
    )

    error_codes = {error["error_code"] for error in validation["errors"]}
    assert validation["passed"] is False
    assert "scoring_input_assembly_mismatch" in error_codes


def test_s15_final_output_validator_rejects_summary_contract_or_branch_drift() -> None:
    text, metadata = _canonical_aox_test_artifacts(empty=True)
    summary = json.loads(text["aox_hmm/execution_summary.json"])
    summary["scoring_input_assembly_contract_digest"] = _sha256(b"drift")
    summary["scientific_branch"] = "length_filter_empty"
    text["aox_hmm/execution_summary.json"] = json.dumps(summary) + "\n"

    validation = _s15_aox_validate_final_artifacts(
        set(S15_AOX_HMM_FIXED_DELIVERABLES),
        text,
        metadata,
    )

    summary_errors = [
        error
        for error in validation["errors"]
        if error["error_code"] == "invalid_execution_summary_value"
    ]
    assert validation["passed"] is False
    assert {
        "scoring_input_assembly_contract_digest",
        "scientific_branch",
    } <= {error["field"] for error in summary_errors}


def test_s15_final_output_validator_rejects_post_uniprot_fields_in_raw_hits() -> None:
    text, metadata = _canonical_aox_test_artifacts()
    raw_lines = text["aox_hmm/hits_raw.csv"].splitlines()
    raw_lines[0] += ",length,sequence"
    raw_lines[1] += ",663,ACDEFGHIK"
    text["aox_hmm/hits_raw.csv"] = "\n".join(raw_lines) + "\n"

    validation = _s15_aox_validate_final_artifacts(
        set(S15_AOX_HMM_FIXED_DELIVERABLES),
        text,
        metadata,
    )

    error_codes = {error["error_code"] for error in validation["errors"]}
    assert validation["passed"] is False
    assert {
        "invalid_csv_columns",
        "hmmer_score_filter_input_invalid",
    } <= error_codes


def test_s15_final_output_validator_recomputes_hmmer_score_filter() -> None:
    text, metadata = _canonical_aox_test_artifacts()
    filtered_lines = text[
        "aox_hmm/hmmer_score_filtered_accessions.csv"
    ].splitlines()
    filtered_fields = filtered_lines[1].split(",")
    score_index = list(aox_hmmer.OUTPUT_COLUMNS).index("score_numeric")
    filtered_fields[score_index] = "2.4E+2"
    filtered_lines[1] = ",".join(filtered_fields)
    text["aox_hmm/hmmer_score_filtered_accessions.csv"] = (
        "\n".join(filtered_lines) + "\n"
    )

    validation = _s15_aox_validate_final_artifacts(
        set(S15_AOX_HMM_FIXED_DELIVERABLES),
        text,
        metadata,
    )

    assert validation["passed"] is False
    assert {
        "error_code": "hmmer_score_filter_output_mismatch",
        "path": "aox_hmm/hmmer_score_filtered_accessions.csv",
    } in validation["errors"]


def test_s15_final_output_validator_requires_empty_target_warning() -> None:
    text, metadata = _canonical_aox_test_artifacts()
    text["aox_hmm/target.fasta"] = ""

    validation = _s15_aox_validate_final_artifacts(
        set(S15_AOX_HMM_FIXED_DELIVERABLES),
        text,
        metadata,
    )

    assert validation["passed"] is False
    assert {
        "error_code": "empty_target_warning_missing",
        "path": "aox_hmm/target.fasta",
    } in validation["errors"]


def test_s15_final_output_validator_accepts_schema_valid_empty_science() -> None:
    text, metadata = _canonical_aox_test_artifacts(empty=True)

    validation = _s15_aox_validate_final_artifacts(
        set(S15_AOX_HMM_FIXED_DELIVERABLES),
        text,
        metadata,
    )

    assert validation == {
        "passed": True,
        "missing_paths": [],
        "legacy_paths": [],
        "errors": [],
        "candidate_count": 0,
        "representative_count": 0,
        "graph_node_count": 0,
        "graph_edge_count": 0,
        "scientific_outcome": "empty",
        "scientific_branch": "motif_filter_empty",
        "omitted_operation_roles": ["cdhit"],
    }


def test_s15_final_output_validator_rejects_legacy_scoring_fields() -> None:
    text, metadata = _canonical_aox_test_artifacts()
    lines = text["aox_hmm/scored_ref_plus_hits.csv"].splitlines()
    header = lines[0].split(",")
    header[0] = "activity_score"
    lines[0] = ",".join(header)
    text["aox_hmm/scored_ref_plus_hits.csv"] = "\n".join(lines) + "\n"
    summary = json.loads(text["aox_hmm/execution_summary.json"])
    summary["pass_rule"] = True
    text["aox_hmm/execution_summary.json"] = json.dumps(summary) + "\n"

    validation = _s15_aox_validate_final_artifacts(
        set(S15_AOX_HMM_FIXED_DELIVERABLES),
        text,
        metadata,
    )

    error_codes = {error["error_code"] for error in validation["errors"]}
    assert validation["passed"] is False
    assert "legacy_scoring_schema_forbidden" in error_codes
    assert "legacy_scientific_field_forbidden" in error_codes


def test_s15_final_output_validator_rejects_fixture_non_cutover_evidence() -> None:
    text, metadata = _canonical_aox_test_artifacts()
    metadata["aox_hmm/AOX_candidates.fasta"] = {
        "scientific_status": "fixture_non_cutover"
    }

    validation = _s15_aox_validate_final_artifacts(
        set(S15_AOX_HMM_FIXED_DELIVERABLES),
        text,
        metadata,
    )

    assert validation["passed"] is False
    assert {
        "error_code": "fixture_non_cutover_forbidden",
        "path": "aox_hmm/AOX_candidates.fasta",
    } in validation["errors"]


def test_s15_final_output_validator_recomputes_graph_and_membership_lineage() -> None:
    text, metadata = _canonical_aox_test_artifacts()
    text["aox_hmm/nodes.csv"] = (
        "node_id,label,score,cluster_id\nK3VE05_FUSPC,x,0,cluster_1\n"
    )
    text["aox_hmm/AOX_candidates_cdhit85.clusters.csv"] = text[
        "aox_hmm/AOX_candidates_cdhit85.clusters.csv"
    ].replace("cluster_0", "cluster_1")

    validation = _s15_aox_validate_final_artifacts(
        set(S15_AOX_HMM_FIXED_DELIVERABLES),
        text,
        metadata,
    )

    graph_error = next(
        error
        for error in validation["errors"]
        if error["error_code"] == "similarity_graph_recalculation_failed"
    )
    assert validation["passed"] is False
    assert graph_error["scientific_error"]["code"] == "legacy_graph_schema"


def test_s15_final_output_validator_rejects_synthetic_candidate_sequence() -> None:
    text, metadata = _canonical_aox_test_artifacts()
    text["aox_hmm/AOX_candidates.fasta"] = ">K3VE05_FUSPC\nMSEQUENCEAOX\n"

    validation = _s15_aox_validate_final_artifacts(
        set(S15_AOX_HMM_FIXED_DELIVERABLES),
        text,
        metadata,
    )

    assert validation["passed"] is False
    assert {
        "error_code": "synthetic_sequence_evidence_forbidden",
        "path": "aox_hmm/AOX_candidates.fasta",
        "sequence_id": "K3VE05_FUSPC",
    } in validation["errors"]


def test_s15_evidence_bundle_rejects_summary_only_payload() -> None:
    validation = _s15_validate_evidence_bundle(
        {
            "fixed_prompt_digest": "sha256:prompt",
            "session_id": "sess_eval_aox_hmm",
            "registered_artifact_ids": ["artifact_1"],
            "normalized_final_deliverable_paths": sorted(
                S15_AOX_HMM_FIXED_DELIVERABLES
            ),
            "final_answer_available": True,
        }
    )

    assert validation["passed"] is False
    missing = set(validation["missing_fields"])
    assert {
        "approval_ids",
        "operation_trace",
        "sandbox_workspace_id",
        "sandbox_image_digests",
        "source_snapshot_digests",
        "route_policy_ids",
        "toolchain_ids",
        "provider_config_digests",
        "backend_run_ids",
        "final_answer_digest",
    } <= missing


def test_s15_evidence_bundle_rejects_approval_bridge_only_operation() -> None:
    evidence = {
        "fixed_prompt_digest": "sha256:prompt",
        "config_snapshot_digest": "sha256:config",
        "session_id": "sess_eval_aox_hmm",
        "sandbox_workspace_id": "sbx_s15",
        "sandbox_image_digests": ["sha256:image"],
        "adapter_schema_versions": ["s12.adapter_envelope.v1"],
        "route_policy_ids": ["bio.ncbi_fetch_proteins.provider:v1"],
        "toolchain_ids": ["toolchain:v1"],
        "provider_config_digests": ["provider_config:ncbi:v1"],
        "approval_ids": ["approval_s15"],
        "operation_trace": [
            {
                "operation_id": "op_s15",
                "operation_digest": "sha256:operation",
                "approval_id": "approval_s15",
                "sandbox_workspace_id": "sbx_s15",
                "source_snapshot_artifact_id": "artifact_source",
                "source_snapshot_digest": "sha256:source",
                "route_policy_id": "bio.ncbi_fetch_proteins.provider:v1",
                "selected_backend": "provider_http",
            }
        ],
        "operation_digests": ["sha256:operation"],
        "source_snapshot_artifact_ids": ["artifact_source"],
        "source_snapshot_digests": ["sha256:source"],
        "backend_run_ids": [],
        "registered_artifact_ids": ["artifact_output"],
        "normalized_final_deliverable_paths": sorted(S15_AOX_HMM_FIXED_DELIVERABLES),
        "final_answer_digest": "sha256:answer",
    }

    validation = _s15_validate_evidence_bundle(evidence)

    assert validation["passed"] is False
    assert validation["missing_fields"] == ["backend_run_ids"]
    assert validation["errors"] == [
        {
            "error_code": "live_evidence_incomplete",
            "missing_fields": ["backend_run_ids"],
        }
    ]


def test_s15_evidence_bundle_collects_approval_operation_and_sandbox_records(
    tmp_path,
) -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    now = "2026-05-31T00:00:00+00:00"
    session = Session(
        session_id="sess_s15_evidence",
        project_id="proj_001",
        title="S15 evidence",
        objective="Validate S15 evidence bundle.",
        status=SessionStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    repositories.sessions.save(session)
    repositories.agents.save(
        AgentMember(
            agent_id="agent_executor",
            session_id=session.session_id,
            lane_id=None,
            task_id=None,
            name="Executor",
            role="executor",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at=now,
            updated_at=now,
            member_id="member_executor",
        )
    )
    repositories.sandbox_workspaces.save(
        SandboxWorkspaceRecord(
            sandbox_workspace_id="sbx_s15",
            session_id=session.session_id,
            agent_member_id="member_executor",
            agent_id="agent_executor",
            status=SandboxWorkspaceStatus.READY,
            image_ref="localhost/openzyme-pipeline-sandbox:dev",
            image_digest="sha256:image",
            image_version="2026.05",
            sandbox_protocol_version="s09",
            image_compatibility=SandboxImageCompatibility.COMPATIBLE,
            manifest_version="1",
            created_at=now,
            last_attached_at=now,
            registered_artifact_ids=("artifact_hits",),
            source_code_artifact_ids=("artifact_source",),
        )
    )
    source_path = tmp_path / "aox_hmm.py"
    source_path.write_text("print('run aox/hmm')\n", encoding="utf-8")
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="artifact_source",
            session_id=session.session_id,
            task_id=None,
            lane_id=None,
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.CODE,
            storage_uri=str(source_path),
            relative_path="src/aox_hmm.py",
            created_at=now,
            metadata={
                "semantic_type": "pipeline_source",
                "content_digest": "sha256:source",
            },
        )
    )
    repositories.sandbox_runs.save(
        SandboxRunRecord(
            sandbox_run_id="run_s15",
            session_id=session.session_id,
            sandbox_workspace_id="sbx_s15",
            agent_id="agent_executor",
            argv=("python", "src/aox_hmm.py"),
            argv_digest="sha256:argv",
            cwd="/workspace",
            env_digest="sha256:env",
            status=SandboxRunStatus.COMPLETED,
            created_at=now,
            updated_at=now,
            source_snapshot_artifact_id="artifact_source",
            source_tree_digest="sha256:source",
            stdout_summary="registered AOX/HMM outputs",
            stderr_summary="",
            stdout_metadata={
                "raw_digest": "sha256:" + "a" * 64,
                "raw_size_bytes": 26,
                "truncated": False,
                "log_ref": None,
            },
            stderr_metadata={
                "raw_digest": "sha256:" + "b" * 64,
                "raw_size_bytes": 0,
                "truncated": False,
                "log_ref": None,
            },
            exit_code=0,
            duration_ms=1234,
            changed_files_summary={"created": ["aox_hmm/hits_raw.csv"]},
        )
    )
    repositories.approvals.save(
        ApprovalRequest(
            approval_id="approval_s15",
            session_id=session.session_id,
            task_id=None,
            lane_id=None,
            kind="sdk_controlled_operation",
            requested_action="Run AOX/HMM provider and HPC operations.",
            status=ApprovalRequestStatus.APPROVED,
            request_ref="request_ref",
            resolution_ref="resolution_ref",
            created_at=now,
            resolved_at=now,
        )
    )
    repositories.controlled_operations.save(
        ControlledOperation(
            operation_id="op_s15",
            session_id=session.session_id,
            sandbox_workspace_id="sbx_s15",
            sandbox_run_id="run_s15",
            logical_operation_key="bio.hmmer_search",
            operation_digest="sha256:operation",
            params_digest="sha256:params",
            backend_category="provider_http",
            status=ControlledOperationStatus.COMPLETED,
            created_at=now,
            updated_at=now,
            approval_id="approval_s15",
            approval_state="approved",
            route_reason="static_policy:v1",
            source_snapshot_artifact_id="artifact_source",
            source_snapshot_digest="sha256:source",
            adapter_envelope_schema_version="s12.adapter_envelope.v1",
            sdk_module="bio",
            function_name="hmmer_search",
            route_policy_id="bio.hmmer_search.provider:v1",
            selected_backend="provider_http",
            runtime_packaging_id="provider_http.aox_hmm_2026_05_31",
            toolchain_id="ebi_hmmer_rest.refprot:v1",
            provider_config_digest="sha256:provider-config",
            expected_outputs_summary={"items": [{"path": "aox_hmm/hits_raw.csv"}]},
            result_summary={"backend_run_id": "backend_s15"},
            adapter_approval_envelope={"schema_version": "s12.adapter_envelope.v1"},
            adapter_result_envelope={"backend_run_id": "backend_s15"},
        )
    )
    artifact_path = tmp_path / "hits_raw.csv"
    artifact_path.write_text(
        "target,uniprot_accession,hmm_score,evalue,length\n", encoding="utf-8"
    )
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="artifact_hits",
            session_id=session.session_id,
            task_id=None,
            lane_id=None,
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.RESULT,
            storage_uri=str(artifact_path),
            relative_path="aox_hmm/hits_raw.csv",
            created_at=now,
            metadata={
                "source_code_artifact_id": "artifact_source",
                "source_code_digest": "sha256:source",
            },
        )
    )

    evidence = _s15_build_evidence_bundle(
        repositories,
        scenario_id=S15_AOX_HMM_SCENARIO_ID,
        session_id=session.session_id,
        prompt="Run AOX/HMM",
        prerequisite_report={"status": "ok", "required": ["llm"]},
        workspace={
            "conversation": [
                {"role": "assistant", "content": "AOX/HMM mining completed."}
            ]
        },
        artifacts=repositories.artifacts.list_by_session(session.session_id),
        required_paths=S15_AOX_HMM_FIXED_DELIVERABLES,
        final_output_validation={"passed": True, "errors": []},
    )
    validation = _s15_validate_evidence_bundle(evidence)

    assert validation["passed"] is True
    assert evidence["sandbox_workspace_id"] == "sbx_s15"
    assert evidence["approval_ids"] == ["approval_s15"]
    assert evidence["route_policy_ids"] == ["bio.hmmer_search.provider:v1"]
    assert evidence["toolchain_ids"] == ["ebi_hmmer_rest.refprot:v1"]
    assert evidence["provider_config_digests"] == ["sha256:provider-config"]
    assert evidence["source_snapshot_digests"] == ["sha256:source"]
    assert evidence["backend_run_ids"] == ["backend_s15"]
    assert evidence["operation_trace"][0]["expected_output_paths"] == [
        "aox_hmm/hits_raw.csv"
    ]
    assert evidence["sandbox_runs"][0]["exit_code"] == 0
    assert evidence["sandbox_runs"][0]["stdout_summary"] == "registered AOX/HMM outputs"
    assert evidence["sandbox_runs"][0]["stdout_metadata"] == {
        "raw_digest": "sha256:" + "a" * 64,
        "raw_size_bytes": 26,
        "truncated": False,
        "log_ref": None,
    }
    assert evidence["sandbox_runs"][0]["stderr_metadata"]["log_ref"] is None
    assert evidence["sandbox_runs"][0]["stdout_metadata_valid"] is True
    assert evidence["sandbox_runs"][0]["stderr_metadata_valid"] is True
    assert evidence["sandbox_runs"][0]["log_artifact_ref_valid"] is True
    assert evidence["sandbox_runs"][0]["changed_files_summary"] == {
        "created": ["aox_hmm/hits_raw.csv"]
    }

    stored_run = repositories.sandbox_runs.get("run_s15")
    assert stored_run is not None
    repositories.sandbox_runs.save(
        replace(
            stored_run,
            stdout_metadata={
                "raw_digest": "sha256:" + "a" * 64,
                "raw_size_bytes": 40_000,
                "truncated": True,
                "log_ref": "/home/operator/private-stdout.log",
                "storage_uri": "storage://private/stdout",
            },
            log_artifact_ref="storage://private/legacy-log",
        )
    )
    unsafe_evidence = _s15_build_evidence_bundle(
        repositories,
        scenario_id=S15_AOX_HMM_SCENARIO_ID,
        session_id=session.session_id,
        prompt="Run AOX/HMM",
        prerequisite_report={"status": "ok", "required": ["llm"]},
        workspace={
            "conversation": [
                {"role": "assistant", "content": "AOX/HMM mining completed."}
            ]
        },
        artifacts=repositories.artifacts.list_by_session(session.session_id),
        required_paths=S15_AOX_HMM_FIXED_DELIVERABLES,
        final_output_validation={"passed": True, "errors": []},
    )
    unsafe_serialized = json.dumps(unsafe_evidence, sort_keys=True)
    unsafe_validation = _s15_validate_evidence_bundle(unsafe_evidence)

    assert unsafe_evidence["sandbox_runs"][0]["stdout_metadata"] is None
    assert unsafe_evidence["sandbox_runs"][0]["stdout_metadata_valid"] is False
    assert unsafe_evidence["sandbox_runs"][0]["log_artifact_ref"] is None
    assert unsafe_evidence["sandbox_runs"][0]["log_artifact_ref_valid"] is False
    assert "/home/operator" not in unsafe_serialized
    assert "storage://private" not in unsafe_serialized
    assert unsafe_validation["passed"] is False
    assert {
        error["error_code"] for error in unsafe_validation["errors"]
    } >= {
        "live_sandbox_stdio_metadata_invalid",
        "live_sandbox_log_ref_invalid",
    }


def test_s15_live_product_path_rejects_legacy_execution_pipeline() -> None:
    required_route_policy_ids = [
        S15_ROUTE_POLICY_IDS["bio.ncbi_fetch_proteins"],
        S15_ROUTE_POLICY_IDS["bio.uniprot_fetch"],
        S15_ROUTE_POLICY_IDS["bio.hmmer_search"],
        S15_ROUTE_POLICY_IDS["bio_tools.cdhit"],
        S15_ROUTE_POLICY_IDS["bio_tools.mafft"],
        S15_ROUTE_POLICY_IDS["bio_tools.hmmbuild"],
        S15_ROUTE_POLICY_IDS["bio_tools.hmmalign"],
    ]
    evidence = {
        "participant_roles": ["researcher", "executor", "reporter"],
        "task_receipts": [
            {
                "task_id": f"task_{kind}",
                "kind": kind,
                "status": "completed",
                "finish_ref": f"finish_{kind}",
                "finish_payload_digest": "sha256:" + "a" * 64,
                "finished_by": f"agent_{kind}",
            }
            for kind in ("research", "execution", "reporting")
        ],
        "research_source_receipts": [
            {
                "source_ref_id": "source_pubmed",
                "provider": "pubmed",
                "pmid": "12345678",
                "request_digest": "sha256:" + "b" * 64,
                "response_digest": "sha256:" + "c" * 64,
                "evidence_artifact_id": "artifact_pubmed",
            }
        ],
        "report_receipts": [
            {
                "report_id": "report_s15",
                "status": "ready",
                "artifact_id": "artifact_report",
            }
        ],
        "report_draft_receipts": [
            {
                "draft_id": "draft_s15",
                "status": "published",
                "published_report_id": "report_s15",
            }
        ],
        "sandbox_runs": [
            {
                "sandbox_run_id": "run_s15",
                "status": "completed",
                "source_snapshot_artifact_id": "artifact_source",
                "source_tree_digest": "sha256:source",
            }
        ],
        "approval_trace": [
            {"approval_id": f"approval_{index}", "status": "approved"}
            for index, _ in enumerate(required_route_policy_ids)
        ],
        "operation_trace": [
            {
                "operation_id": f"op_{index}",
                "status": "completed",
                "approval_id": f"approval_{index}",
                "route_policy_id": route_policy_id,
            }
            for index, route_policy_id in enumerate(required_route_policy_ids)
        ],
        "route_policy_ids": required_route_policy_ids,
    }

    accepted = _s15_validate_live_product_path(
        evidence,
        workspace={"pending_approvals": []},
        has_legacy_execution_pipeline=False,
    )
    rejected = _s15_validate_live_product_path(
        evidence,
        workspace={"pending_approvals": []},
        has_legacy_execution_pipeline=True,
    )

    assert accepted["passed"] is True
    assert rejected["passed"] is False
    assert {"error_code": "live_legacy_pipeline_forbidden"} in rejected["errors"]

    missing_product_evidence = json.loads(json.dumps(evidence))
    missing_product_evidence["participant_roles"] = ["executor"]
    missing_product_evidence["task_receipts"] = []
    missing_product_evidence["research_source_receipts"] = []
    missing_product_evidence["report_receipts"] = []
    missing_product_evidence["report_draft_receipts"] = []

    incomplete = _s15_validate_live_product_path(
        missing_product_evidence,
        workspace={"pending_approvals": []},
        has_legacy_execution_pipeline=False,
    )

    assert incomplete["passed"] is False
    assert {
        "live_product_roles_incomplete",
        "live_task_business_exit_incomplete",
        "live_pubmed_evidence_missing",
        "live_published_report_missing",
    } <= {item["error_code"] for item in incomplete["errors"]}


def test_s15_legacy_pipeline_detector_ignores_docs_prose() -> None:
    assert (
        _s15_event_text_has_legacy_execution_pipeline(
            '{"content": "Do not use execution.pipeline.start for AOX/HMM."}'
        )
        is False
    )
    assert (
        _s15_event_text_has_legacy_execution_pipeline(
            '{"tool_name": "execution.pipeline.start", "status": "called"}'
        )
        is True
    )


def test_s15_live_readiness_uses_sandbox_records_not_legacy_execution_capability(
    tmp_path,
) -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    now = "2026-05-31T00:00:00+00:00"
    session_id = "sess_s15_live_ready"
    repositories.sessions.save(
        Session(
            session_id=session_id,
            project_id="proj_001",
            title="S15 live readiness",
            objective="Validate sandbox-first readiness.",
            status=SessionStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
    )
    repositories.agents.save(
        AgentMember(
            agent_id="agent_executor",
            session_id=session_id,
            lane_id=None,
            task_id=None,
            name="Executor",
            role="executor",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at=now,
            updated_at=now,
            member_id="member_executor",
        )
    )
    for relative_path in sorted(S15_AOX_HMM_FIXED_DELIVERABLES):
        path = tmp_path / relative_path.replace("/", "_")
        path.write_text("placeholder\n", encoding="utf-8")
        repositories.artifacts.save(
            SessionArtifactRecord(
                artifact_id=f"artifact_{relative_path.replace('/', '_')}",
                session_id=session_id,
                task_id=None,
                lane_id=None,
                invocation_id=None,
                run_id=None,
                kind=ArtifactKind.RESULT,
                storage_uri=str(path),
                relative_path=relative_path,
                created_at=now,
                metadata={},
            )
        )
    repositories.sandbox_workspaces.save(
        SandboxWorkspaceRecord(
            sandbox_workspace_id="sbx_s15_ready",
            session_id=session_id,
            agent_member_id="member_executor",
            agent_id="agent_executor",
            status=SandboxWorkspaceStatus.READY,
            image_ref="localhost/openzyme-pipeline-sandbox:dev",
            image_digest="sha256:image",
            image_version="dev",
            sandbox_protocol_version="s09",
            image_compatibility=SandboxImageCompatibility.COMPATIBLE,
            manifest_version="1",
            created_at=now,
            last_attached_at=now,
        )
    )
    repositories.sandbox_runs.save(
        SandboxRunRecord(
            sandbox_run_id="run_s15_ready",
            session_id=session_id,
            sandbox_workspace_id="sbx_s15_ready",
            agent_id="agent_executor",
            argv=("python", "src/aox_hmm.py"),
            argv_digest="sha256:argv",
            cwd="/workspace",
            env_digest="sha256:env",
            status=SandboxRunStatus.COMPLETED,
            created_at=now,
            updated_at=now,
            source_snapshot_artifact_id=None,
            source_tree_digest="sha256:source",
        )
    )
    workspace = {
        "pending_approvals": [],
        "task_board": {
            "items": [
                {
                    "task": {
                        "task_id": "task_aox_hmm_research",
                        "kind": "research",
                        "status": "completed",
                    }
                },
                {
                    "task": {
                        "task_id": "task_aox_hmm_execution",
                        "kind": "execution",
                        "status": "completed",
                    }
                },
                {
                    "task": {
                        "task_id": "task_aox_hmm_reporting",
                        "kind": "reporting",
                        "status": "completed",
                    }
                },
            ]
        },
        "capabilities": {},
        "report_drafts": [{"status": "published"}],
        "reports": [{"status": "ready"}],
        "conversation": [{"role": "assistant", "content": "AOX/HMM complete."}],
    }

    assert _s15_live_workspace_ready(
        repositories,
        session_id=session_id,
        workspace=workspace,
    )


def test_s15_live_prerequisite_report_requires_sandbox_image(monkeypatch) -> None:
    monkeypatch.setenv("OPENZYME_NCBI_EMAIL", "dev@example.org")
    monkeypatch.setattr(
        "openzyme_host_api.evals.live_e2e_skip_reason", lambda settings: None
    )
    monkeypatch.setattr(
        "openzyme_host_api.evals.live_llm_skip_reason", lambda settings: None
    )
    monkeypatch.setattr(
        "openzyme_host_api.evals.live_tavily_skip_reason", lambda settings: None
    )
    monkeypatch.setattr(
        "openzyme_host_api.evals.live_hpc_skip_reason", lambda settings: None
    )
    monkeypatch.setattr(
        "openzyme_host_api.evals.shutil.which", lambda binary: "/usr/bin/podman"
    )

    def fake_run(args, **kwargs):
        del kwargs
        if args[:2] == ["podman", "info"]:
            return subprocess.CompletedProcess(args, 0, stdout="true\n", stderr="")
        if args[:3] == ["podman", "image", "exists"]:
            return subprocess.CompletedProcess(
                args, 1, stdout="", stderr="missing image"
            )
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr("openzyme_host_api.evals.subprocess.run", fake_run)
    reset_settings_cache()
    try:
        report = _s15_live_prerequisite_report()
    finally:
        reset_settings_cache()

    image_check = next(
        check for check in report["checks"] if check["name"] == "sandbox_image"
    )
    missing_names = {check["name"] for check in report["missing"]}
    assert report["status"] == "prerequisite_missing"
    assert "sandbox_image" in report["required"]
    assert "sandbox_image" in missing_names
    assert image_check["status"] == "prerequisite_missing"
    assert image_check["error_code"] == "sandbox_image_missing"


def test_s15_bootstrap_live_sandbox_image_registers_probe_digest(monkeypatch) -> None:
    image_digest = "sha256:" + "b" * 64
    monkeypatch.setenv("OPENZYME_NCBI_EMAIL", "dev@example.org")
    monkeypatch.setattr(
        "openzyme_host_api.evals.live_e2e_skip_reason", lambda settings: None
    )
    monkeypatch.setattr(
        "openzyme_host_api.evals.live_llm_skip_reason", lambda settings: None
    )
    monkeypatch.setattr(
        "openzyme_host_api.evals.live_tavily_skip_reason", lambda settings: None
    )
    monkeypatch.setattr(
        "openzyme_host_api.evals.live_hpc_skip_reason", lambda settings: None
    )
    monkeypatch.setattr(
        "openzyme_host_api.evals.shutil.which", lambda binary: "/usr/bin/podman"
    )

    def fake_run(args, **kwargs):
        del kwargs
        if args[:2] == ["podman", "info"]:
            return subprocess.CompletedProcess(args, 0, stdout="true\n", stderr="")
        if args[:3] == ["podman", "image", "exists"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[:3] == ["podman", "image", "inspect"]:
            return subprocess.CompletedProcess(
                args, 0, stdout=f"{image_digest}\n", stderr=""
            )
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr("openzyme_host_api.evals.subprocess.run", fake_run)
    reset_settings_cache()
    try:
        report = _s15_live_prerequisite_report()
    finally:
        reset_settings_cache()
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)

    _s15_bootstrap_live_sandbox_image(repositories, report)

    image = repositories.sandbox_images.get_default()
    image_check = next(
        check for check in report["checks"] if check["name"] == "sandbox_image"
    )
    assert report["status"] == "ok"
    assert image_check["image_digest"] == image_digest
    assert image is not None
    assert image.image_digest == image_digest
    assert image.compatibility is SandboxImageCompatibility.COMPATIBLE_NON_CUTOVER_GRADE


def test_v3_live_eval_reports_s15_prerequisite_missing_without_fixture_fallback(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.settings.load_env_files", lambda *args, **kwargs: None
    )
    for key in (
        "OPENZYME_TEST_ENABLE_LIVE_E2E",
        "OPENZYME_TEST_ENABLE_LIVE_LLM",
        "OPENZYME_TEST_ENABLE_LIVE_TAVILY",
        "OPENZYME_TEST_ENABLE_LIVE_HPC",
        "OPENZYME_LLM_API_KEY",
        "TAVILY_API_KEY",
        "OPENZYME_HPC_RUNNER_CONFIG",
        "HPC_RUNNER_CONFIG",
        "OPENZYME_NCBI_EMAIL",
        "NCBI_EMAIL",
    ):
        monkeypatch.delenv(key, raising=False)
    reset_settings_cache()

    try:
        summary = run_v3_s15_live_evals(upload_results=False)
    finally:
        reset_settings_cache()

    assert summary["scenario_count"] == 1
    assert summary["passed"] == 0
    assert summary["failed"] == 0
    assert summary["prerequisite_missing"] == 1
    result = summary["results"][0]
    assert result["scenario_id"] == S15_AOX_HMM_SCENARIO_ID
    assert result["scenario_class"] == "live"
    assert result["status"] == "prerequisite_missing"
    assert str(result["fixed_prompt_digest"]).startswith("sha256:")
    assert str(result["config_snapshot_digest"]).startswith("sha256:")
    assert str(result["prerequisite_report_digest"]).startswith("sha256:")
    assert result["evidence_bundle_digest"] is None
    assert result["evidence_sealed"] is False
    assert result["evidence_bundle"] is None
    assert result["checks"]["fixture_dependencies_forbidden"] is True
    assert set(result["required_artifacts"]) == S15_AOX_HMM_FIXED_DELIVERABLES
    assert result["prerequisite_report"]["status"] == "prerequisite_missing"


def test_s15_live_scenario_rejects_fixture_dependency_injection() -> None:
    with pytest.raises(ValueError, match="cannot use fixture dependencies"):
        _run_v3_aox_hmm_prompt_scenario(
            foundation_builder=build_local_eval_runtime,
            model_factory=None,
            scenario_class="live",
            use_fixture_dependencies=True,
        )
