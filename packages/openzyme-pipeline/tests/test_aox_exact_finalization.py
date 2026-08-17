from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from openzyme_pipeline import aox_candidate
from openzyme_pipeline import aox_finalization
from openzyme_pipeline import aox_hmmer
from openzyme_pipeline import aox_motif
from openzyme_pipeline.aox_motif import ScientificPrerequisiteError
from openzyme_pipeline.client import PipelineSdkError


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "aox_motif_rule_score_v1"
    / "alignment.fasta"
)


def _candidate_inputs() -> tuple[bytes, bytes, list[str]]:
    scoring = aox_motif.score_aligned_fasta(FIXTURE.read_bytes())
    records = {
        record.sequence_id: record.sequence.replace("-", "").replace(".", "")
        for record in scoring.alignment.records
        if record.sequence_id != aox_motif.REFERENCE_ACCESSION
    }
    target_fasta = "".join(
        f">{sequence_id}\n{records[sequence_id]}\n"
        for sequence_id in sorted(records)
    ).encode("ascii")
    expected = sorted(
        row.sequence_id
        for row in scoring.rows
        if row.sequence_id != aox_motif.REFERENCE_ACCESSION
        and row.passes_motif_rule
    )
    return target_fasta, scoring.to_csv().encode("utf-8"), expected


def test_candidate_filter_uses_canonical_typed_decision_field() -> None:
    target_fasta, scoring_csv, expected = _candidate_inputs()

    result = aox_candidate.filter_motif_candidates(
        target_fasta,
        scoring_csv,
        expected_contract_digest=aox_candidate.CONTRACT_DIGEST,
        expected_implementation_digest=aox_candidate.IMPLEMENTATION_DIGEST,
    )

    assert [record.sequence_id for record in result.candidates] == expected
    assert result.calculation_receipt()["candidate_count"] == len(expected)
    assert result.calculation_receipt()["output_digest"].startswith("sha256:")


def test_candidate_filter_rejects_r65_noncanonical_field_substitute() -> None:
    target_fasta, scoring_csv, _ = _candidate_inputs()
    drifted = scoring_csv.replace(
        b"passes_motif_rule",
        b"pass_rule",
        1,
    )

    with pytest.raises(ScientificPrerequisiteError) as error:
        aox_candidate.filter_motif_candidates(target_fasta, drifted)

    assert error.value.code == "candidate_scoring_schema_mismatch"


def test_candidate_receipt_rejects_source_snapshot_substitute_fields() -> None:
    target_fasta, scoring_csv, _ = _candidate_inputs()
    receipt = aox_candidate.filter_motif_candidates(
        target_fasta,
        scoring_csv,
    ).calculation_receipt()
    receipt["source_snapshot_implementation_digest"] = (
        "sha256:" + "f" * 64
    )

    with pytest.raises(ScientificPrerequisiteError) as error:
        aox_candidate.validate_calculation_receipt(receipt)

    assert error.value.code == "candidate_calculation_receipt_invalid"


def _empty_hmmer_result() -> aox_hmmer.ScoreFilteredAccessionsResult:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=list(aox_hmmer.INPUT_COLUMNS),
        lineterminator="\n",
    )
    writer.writeheader()
    return aox_hmmer.parse_and_filter_csv(output.getvalue())


def test_conditional_empty_chain_accepts_only_installed_typed_sources() -> None:
    hmmer_receipt = aox_finalization.hmmer_zero_source_receipt(
        _empty_hmmer_result()
    )
    upstream = aox_finalization.encode_upstream_empty(hmmer_receipt)
    upstream_receipt = upstream.calculation_receipt()
    reference = aox_finalization.encode_reference_only_alignment(
        b">AAB57849.1\nACDE\n",
        upstream_receipt,
    )
    candidate_zero = aox_candidate.CandidateFilterResult(
        target_input_digest="sha256:" + "1" * 64,
        scoring_input_digest="sha256:" + "2" * 64,
        targets=(),
        candidates=(),
    )
    membership = aox_finalization.encode_empty_membership(
        candidate_zero.calculation_receipt()
    )

    upstream_file = json.loads(upstream.output_bytes)
    assert upstream_file["schema_id"] == "aox_conditional_empty_file@1"
    assert upstream_file["empty_result_reason"] == (
        "no_accessions_after_hmmer_score_filter"
    )
    assert reference.output_bytes == b">AAB57849.1\nACDE\n"
    assert membership.output_bytes.startswith(b"cluster_id,member_id")
    for receipt in (
        upstream_receipt,
        reference.calculation_receipt(),
        membership.calculation_receipt(),
    ):
        assert aox_finalization.validate_conditional_receipt(receipt) == receipt


def test_conditional_empty_rejects_arbitrary_source_snapshot_identity() -> None:
    fabricated = {
        "calculation_id": "sandbox_source_snapshot@1",
        "calculation_contract_digest": "sha256:" + "1" * 64,
        "calculation_implementation_digest": "sha256:" + "2" * 64,
        "output_count": 0,
        "output_digest": "sha256:" + "3" * 64,
        "empty_result_reason": "no_candidates",
    }

    with pytest.raises(ScientificPrerequisiteError) as error:
        aox_finalization.encode_upstream_empty(fabricated)

    assert error.value.code == "conditional_empty_source_receipt_invalid"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("output_format", "txt"),
        ("empty_result_reason", "fabricated_empty"),
        ("source_snapshot_implementation_digest", "sha256:" + "4" * 64),
    ],
)
def test_conditional_empty_receipt_rejects_schema_or_source_drift(
    field: str,
    value: str,
) -> None:
    upstream = aox_finalization.encode_upstream_empty(
        aox_finalization.hmmer_zero_source_receipt(_empty_hmmer_result())
    ).calculation_receipt()
    upstream[field] = value

    with pytest.raises(ScientificPrerequisiteError) as error:
        aox_finalization.validate_conditional_receipt(upstream)

    assert error.value.code == "conditional_empty_receipt_invalid"


def _finalization_items() -> list[dict[str, object]]:
    return [
        {
            "path": f"/workspace/output/{path}",
            "kind": "sequence" if path.endswith(".fasta") else "result",
            "format": path.rsplit(".", maxsplit=1)[-1],
            "validation_profile": None,
            "metadata": {},
        }
        for path in aox_finalization.FIXED_DELIVERABLE_PATHS
    ]


def test_finalizer_sdk_submits_each_exact_path_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_call(method: str, params: dict[str, object]) -> dict[str, object]:
        observed.update({"method": method, "params": params})
        return {"status": "passed", "receipt_id": "receipt_1"}

    monkeypatch.setattr(aox_finalization, "call", fake_call)
    candidate = aox_candidate.CandidateFilterResult(
        target_input_digest="sha256:" + "1" * 64,
        scoring_input_digest="sha256:" + "2" * 64,
        targets=(),
        candidates=(),
    )

    result = aox_finalization.finalize_deliverable_bundle(
        publication_id="publication_1",
        attempt_id="attempt_1",
        selection_id="selection_1",
        execution_fencing_token=1,
        producer_adoption_ids_by_role={
            role: f"adoption_{index}"
            for index, role in enumerate(aox_finalization.FIXED_DELIVERABLE_ROLES)
        },
        calculation_receipts=[
            candidate.calculation_receipt(),
            aox_finalization.finalization_calculation_receipt(),
        ],
    )

    assert result["receipt_id"] == "receipt_1"
    assert observed["method"] == "scientific.deliverables.finalize"
    params = observed["params"]
    assert isinstance(params, dict)
    assert params["publication_id"] == "publication_1"
    assert set(params["producer_adoption_ids_by_role"]) == set(
        aox_finalization.FIXED_DELIVERABLE_ROLES
    )


def test_producer_adoption_sdk_submits_exact_revision_result_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_call(method: str, params: dict[str, object]) -> dict[str, object]:
        observed.update({"method": method, "params": params})
        return {
            "schema_version": "scientific_file_effect_adoption_result@1",
            "adoption": {"adoption_id": "adoption_1"},
        }

    monkeypatch.setattr(aox_finalization, "call", fake_call)

    result = aox_finalization.adopt_producer_result(
        selection_id="selection_1",
        operation_id="operation_1",
        execution_id="execution_1",
        result_id="result_1",
        workflow_role=aox_finalization.FIXED_DELIVERABLE_ROLES[0],
        execution_fencing_token=3,
        idempotency_key="adopt-role-1",
    )

    assert result["adoption"] == {"adoption_id": "adoption_1"}
    assert observed["method"] == "scientific.deliverables.adopt"
    params = observed["params"]
    assert isinstance(params, dict)
    assert params == {
        "schema_version": "scientific_file_effect_adoption_request@1",
        "selection_id": "selection_1",
        "operation_id": "operation_1",
        "execution_id": "execution_1",
        "result_id": "result_1",
        "workflow_role": aox_finalization.FIXED_DELIVERABLE_ROLES[0],
        "execution_fencing_token": 3,
        "idempotency_key": "adopt-role-1",
    }


def test_finalizer_sdk_rejects_incomplete_bundle_before_transport() -> None:
    candidate = aox_candidate.CandidateFilterResult(
        target_input_digest="sha256:" + "1" * 64,
        scoring_input_digest="sha256:" + "2" * 64,
        targets=(),
        candidates=(),
    )

    with pytest.raises(PipelineSdkError) as error:
        aox_finalization.finalize_deliverable_bundle(
            publication_id="publication_1",
            attempt_id="attempt_1",
            selection_id="selection_1",
            execution_fencing_token=1,
            producer_adoption_ids_by_role={
                role: f"adoption_{index}"
                for index, role in enumerate(
                    aox_finalization.FIXED_DELIVERABLE_ROLES[:-1]
                )
            },
            calculation_receipts=[
                candidate.calculation_receipt(),
                aox_finalization.finalization_calculation_receipt(),
            ],
        )

    assert error.value.error_code == "aox_finalization_adoption_set_invalid"


def test_exact_calculation_manifest_enumerates_finalization_surface() -> None:
    manifest = aox_finalization.installed_calculation_manifest()

    assert set(manifest["calculations"]) == {
        aox_candidate.CALCULATION_ID,
        aox_finalization.UPSTREAM_EMPTY_CALCULATION_ID,
        aox_finalization.REFERENCE_ONLY_ALIGNMENT_CALCULATION_ID,
        aox_finalization.EMPTY_MEMBERSHIP_CALCULATION_ID,
        aox_finalization.FINALIZATION_CALCULATION_ID,
    }
    assert "aox_finalization.finalize_deliverable_bundle" in manifest[
        "callable_names"
    ]
    finalizer = manifest["calculations"][
        aox_finalization.FINALIZATION_CALCULATION_ID
    ]
    assert finalizer["result_schema_id"] == (
        aox_finalization.FINALIZATION_CALCULATION_RESULT_SCHEMA_ID
    )
    assert finalizer["result_schema_id"] != (
        aox_finalization.FINALIZATION_RECEIPT_SCHEMA_ID
    )
