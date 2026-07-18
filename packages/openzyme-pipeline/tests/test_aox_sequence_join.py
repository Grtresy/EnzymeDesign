from __future__ import annotations

import csv
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path

import pytest

from openzyme_pipeline import aox_hmmer, aox_sequence_join


def _digest(content: str | bytes) -> str:
    raw = content.encode("utf-8") if isinstance(content, str) else content
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _sequence(length: int, residue: str = "A") -> str:
    return residue * length


def _canonical_decimal(value: str) -> str:
    numeric = Decimal(value)
    return str(numeric.normalize()) if numeric else "0"


def _hmmer_csv(
    rows: list[tuple[str, str, str, str]],
) -> str:
    return aox_hmmer.canonical_rows_to_csv(
        {
            "accession": accession,
            "target": target,
            "evalue_numeric": _canonical_decimal(evalue),
            "score_numeric": _canonical_decimal(score),
            "raw_page_digest": _digest(f"page:{accession}"),
            "raw_hit_digest": _digest(f"hit:{accession}"),
            "parsed_row_digest": _digest(f"row:{accession}"),
        }
        for accession, target, evalue, score in rows
    )


def _provider_mapping(requested: str, primary: str) -> dict[str, object]:
    return {
        "annotation_type": "provider_identity_mapping",
        "source_database": "requested_identifier",
        "source_accession": requested,
        "target_database": "uniprotkb",
        "target_accession": primary,
        "relationship": "resolves_to_primary_accession",
        "identity_replaced": False,
    }


def _uniprot_inputs(
    records: list[tuple[str, str, str, bool]],
    *,
    header_styles: dict[str, str] | None = None,
    fasta_order: list[str] | None = None,
) -> tuple[str, str]:
    header_styles = header_styles or {}
    by_primary = {primary: (requested, sequence, reviewed) for requested, primary, sequence, reviewed in records}
    order = fasta_order or [primary for _, primary, _, _ in records]
    fasta_parts: list[str] = []
    for primary in order:
        _, sequence, reviewed = by_primary[primary]
        style = header_styles.get(primary, "bare")
        if style == "bare":
            header = f"{primary} {primary}_AOX"
        elif style in {"sp", "tr"}:
            header = f"{style}|{primary}|{primary}_AOX protein"
        else:
            header = style
        del reviewed
        fasta_parts.append(f">{header}\n{sequence}\n")

    metadata_records: list[dict[str, object]] = []
    for index, (requested, primary, sequence, reviewed) in enumerate(records, start=1):
        entry_type = (
            "UniProtKB reviewed (Swiss-Prot)"
            if reviewed
            else "UniProtKB unreviewed (TrEMBL)"
        )
        identifier = f"{primary}_AOX"
        metadata_records.append(
            {
                "requested_accession": requested,
                "primary_accession": primary,
                "uniprot_identifier": identifier,
                "reviewed": reviewed,
                "entry_type": entry_type,
                "uniprot_release": "2026_03",
                "uniprot_release_date": "15-July-2026",
                "retrieved_at": "2026-07-17T00:00:00+00:00",
                "entry_version": index + 10,
                "sequence_version": index + 2,
                "sequence_length": len(sequence),
                "sequence_digest": _digest(sequence),
                "response_digest": _digest(f"response:{requested}"),
                "record_digest": _digest(f"record:{requested}"),
                "mapping_annotations": [_provider_mapping(requested, primary)],
                "provider_metadata": {
                    "entryType": entry_type,
                    "primaryAccession": primary,
                    "secondaryAccessions": [] if requested == primary else [requested],
                    "uniProtkbId": identifier,
                    "entryAudit": {
                        "entryVersion": index + 10,
                        "sequenceVersion": index + 2,
                    },
                },
            }
        )
    metadata = {
        "provider": "uniprot",
        "database": "uniprotkb",
        "fields": [
            "accession",
            "id",
            "sequence",
            "reviewed",
            "sequence_version",
            "version",
            "length",
        ],
        "batch_size": 100,
        "identity_contract_id": "uniprot_primary_sequence_identity@1",
        "requested_accessions": [record[0] for record in records],
        "records": metadata_records,
        "warnings": [],
        "retrieved_at": "2026-07-17T00:00:00+00:00",
        "uniprot_release": "2026_03",
        "uniprot_release_date": "15-July-2026",
        "aggregate_response_digest": _digest("aggregate-response"),
        "source_sequence_identity_count": 0,
        "sequence_mismatch_resolution_count": 0,
        "api_version": "provider-http-v1",
    }
    return "".join(fasta_parts), json.dumps(metadata, sort_keys=True, indent=2) + "\n"


def _mutate_metadata(metadata: str, mutate) -> str:  # type: ignore[no-untyped-def]
    payload = json.loads(metadata)
    mutate(payload)
    return json.dumps(payload, sort_keys=True, indent=2) + "\n"


def _code(
    error: pytest.ExceptionInfo[aox_sequence_join.ScientificPrerequisiteError],
) -> str:
    return error.value.code


def test_join_accepts_bare_sp_tr_headers_and_preserves_requested_identity() -> None:
    score_csv = _hmmer_csv(
        [
            ("P12345", "AOX_P12345", "1E-80", "250"),
            ("Q8XYZ1", "AOX_Q8XYZ1", "2E-40", "300.5"),
        ]
    )
    p_sequence = _sequence(650, "A")
    q_sequence = _sequence(700, "G")
    fasta, metadata = _uniprot_inputs(
        [
            ("P12345", "P12345", p_sequence, True),
            ("Q8XYZ1", "A0A123", q_sequence, False),
        ],
        header_styles={"P12345": "sp", "A0A123": "tr"},
        fasta_order=["A0A123", "P12345"],
    )

    result = aox_sequence_join.join_score_filtered_accessions(
        score_csv,
        fasta,
        metadata,
    )

    rows = list(csv.DictReader(io.StringIO(result.hits_csv())))
    assert rows == [
        {
            "target": "AOX_P12345",
            "uniprot_accession": "P12345",
            "hmm_score": "2.5E+2",
            "evalue": "1E-80",
            "length": "650",
            "sequence": p_sequence,
        },
        {
            "target": "AOX_Q8XYZ1",
            "uniprot_accession": "Q8XYZ1",
            "hmm_score": "300.5",
            "evalue": "2E-40",
            "length": "700",
            "sequence": q_sequence,
        },
    ]
    assert result.target_fasta() == (
        f">P12345\n{p_sequence}\n>Q8XYZ1\n{q_sequence}\n"
    )
    assert result.hits[1].primary_accession == "A0A123"
    assert result.metadata()["identity_mappings"][1] == {
        "requested_accession": "Q8XYZ1",
        "primary_accession": "A0A123",
        "identity_replaced": False,
        "sequence_digest": _digest(q_sequence),
        "reviewed": False,
        "entry_version": 12,
        "sequence_version": 4,
        "response_digest": _digest("response:Q8XYZ1"),
        "record_digest": _digest("record:Q8XYZ1"),
    }


def test_join_accepts_current_ten_character_uniprot_accession() -> None:
    accession = "A0A378ARX6"
    sequence = _sequence(675, "A")
    score_csv = _hmmer_csv(
        [(accession, "A0A378ARX6_KLEPO", "1E-12", "250")]
    )
    fasta, metadata = _uniprot_inputs(
        [(accession, accession, sequence, False)],
        header_styles={accession: "tr"},
    )

    result = aox_sequence_join.join_score_filtered_accessions(
        score_csv,
        fasta,
        metadata,
    )

    assert result.hits[0].uniprot_accession == accession
    assert result.hits[0].primary_accession == accession
    assert result.target_fasta() == f">{accession}\n{sequence}\n"


def test_length_filter_is_inclusive_and_supports_healthy_empty_output() -> None:
    score_csv = _hmmer_csv(
        [
            ("P12345", "AOX_P12345", "1E-10", "201"),
            ("Q8XYZ1", "AOX_Q8XYZ1", "2E-10", "202"),
        ]
    )
    fasta, metadata = _uniprot_inputs(
        [
            ("P12345", "P12345", _sequence(649), True),
            ("Q8XYZ1", "Q8XYZ1", _sequence(701), False),
        ]
    )

    result = aox_sequence_join.join_score_filtered_accessions(
        score_csv,
        fasta,
        metadata,
    )

    assert result.hits == ()
    assert result.hits_csv() == ",".join(aox_sequence_join.OUTPUT_COLUMNS) + "\n"
    assert result.target_fasta() == ""
    assert result.metadata()["healthy_empty"] is True
    assert result.metadata()["counts"] == {
        "input_hit_count": 2,
        "uniprot_record_count": 2,
        "output_hit_count": 0,
        "length_rejected_count": 2,
    }


def test_metadata_binds_contract_input_output_provider_and_counts() -> None:
    score_csv = _hmmer_csv(
        [("P12345", "AOX_P12345", "0", "200.1")]
    )
    sequence = _sequence(675, "V")
    fasta, metadata = _uniprot_inputs(
        [("P12345", "P12345", sequence, True)]
    )

    result = aox_sequence_join.join_score_filtered_accessions(
        score_csv,
        fasta,
        metadata,
        expected_score_filtered_csv_digest=_digest(score_csv),
        expected_uniprot_fasta_digest=_digest(fasta),
        expected_uniprot_metadata_digest=_digest(metadata),
    )
    manifest = result.metadata()

    assert manifest["contract_id"] == "aox_sequence_length_join@1"
    assert manifest["contract_digest"] == aox_sequence_join.CONTRACT_DIGEST
    assert manifest["implementation_digest"] == aox_sequence_join.IMPLEMENTATION_DIGEST
    assert manifest["upstream_hmmer_contract"] == {
        "contract_id": aox_hmmer.CONTRACT_ID,
        "contract_digest": aox_hmmer.CONTRACT_DIGEST,
        "implementation_digest": aox_hmmer.IMPLEMENTATION_DIGEST,
    }
    assert manifest["input_digests"] == {
        "hmmer_score_filtered_accessions_csv": _digest(score_csv),
        "uniprot_sequences_fasta": _digest(fasta),
        "uniprot_metadata_json": _digest(metadata),
    }
    assert manifest["output_digests"] == {
        "hits_len650_700_200.csv": _digest(result.hits_csv()),
        "target.fasta": _digest(result.target_fasta()),
    }
    assert manifest["uniprot_provider"] == {
        "identity_contract_id": "uniprot_primary_sequence_identity@1",
        "release": "2026_03",
        "release_date": "15-July-2026",
        "retrieved_at": "2026-07-17T00:00:00+00:00",
        "aggregate_response_digest": _digest("aggregate-response"),
        "api_version": "provider-http-v1",
        "warning_count": 0,
        "source_sequence_identity_count": 0,
        "sequence_mismatch_resolution_count": 0,
    }
    assert result.metadata_json() == (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    )

    repeated = aox_sequence_join.join_score_filtered_accessions(
        score_csv,
        fasta,
        metadata,
    )
    assert repeated.hits_csv() == result.hits_csv()
    assert repeated.target_fasta() == result.target_fasta()
    assert repeated.metadata_json() == result.metadata_json()


def test_contract_and_implementation_digests_are_offline_recomputable() -> None:
    source_path = Path(aox_sequence_join.__file__)

    assert aox_sequence_join.implementation_digest() == _digest(
        source_path.read_bytes()
    )
    assert (
        aox_sequence_join.contract_digest(
            implementation_digest_value=aox_sequence_join.IMPLEMENTATION_DIGEST
        )
        == aox_sequence_join.CONTRACT_DIGEST
    )
    payload = aox_sequence_join.contract_payload(
        implementation_digest_value=aox_sequence_join.IMPLEMENTATION_DIGEST
    )
    assert payload["upstream_hmmer_contract"] == {
        "contract_id": aox_hmmer.CONTRACT_ID,
        "contract_digest": aox_hmmer.CONTRACT_DIGEST,
        "implementation_digest": aox_hmmer.IMPLEMENTATION_DIGEST,
        "columns": list(aox_hmmer.OUTPUT_COLUMNS),
    }
    assert payload["filter"] == {
        "field": "length_of_exact_uniprot_sequence_bytes",
        "minimum": 650,
        "maximum": 700,
        "minimum_inclusive": True,
        "maximum_inclusive": True,
    }


@pytest.mark.parametrize(
    ("fasta_mutation", "expected_code"),
    [
        (lambda fasta: "", "sequence_join_uniprot_sequence_missing"),
        (
            lambda fasta: fasta + f">Q8XYZ1\n{_sequence(675)}\n",
            "sequence_join_uniprot_sequence_extra",
        ),
        (
            lambda fasta: fasta + fasta,
            "sequence_join_fasta_duplicate_accession",
        ),
        (
            lambda fasta: fasta.replace(">P12345", ">xx|P12345|ENTRY"),
            "sequence_join_fasta_header_invalid",
        ),
        (
            lambda fasta: fasta.replace("A" * 675, "A" * 674 + "*"),
            "sequence_join_fasta_sequence_invalid",
        ),
    ],
)
def test_missing_extra_duplicate_or_illegal_uniprot_fasta_fails_closed(
    fasta_mutation,
    expected_code: str,
) -> None:  # type: ignore[no-untyped-def]
    score_csv = _hmmer_csv(
        [("P12345", "AOX_P12345", "1E-20", "250")]
    )
    fasta, metadata = _uniprot_inputs(
        [("P12345", "P12345", _sequence(675), True)]
    )

    with pytest.raises(aox_sequence_join.ScientificPrerequisiteError) as error:
        aox_sequence_join.join_score_filtered_accessions(
            score_csv,
            fasta_mutation(fasta),
            metadata,
        )

    assert _code(error) == expected_code


def test_sp_tr_header_must_match_reviewed_status() -> None:
    score_csv = _hmmer_csv(
        [("P12345", "AOX_P12345", "1E-20", "250")]
    )
    fasta, metadata = _uniprot_inputs(
        [("P12345", "P12345", _sequence(675), False)],
        header_styles={"P12345": "sp"},
    )

    with pytest.raises(aox_sequence_join.ScientificPrerequisiteError) as error:
        aox_sequence_join.join_score_filtered_accessions(score_csv, fasta, metadata)

    assert _code(error) == "sequence_join_uniprot_review_status_mismatch"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            lambda payload: payload["requested_accessions"].append("Q8XYZ1"),
            "sequence_join_uniprot_requested_accessions_mismatch",
        ),
        (
            lambda payload: payload["records"][0].update(
                {"sequence_digest": _digest("wrong")}
            ),
            "sequence_join_uniprot_sequence_digest_mismatch",
        ),
        (
            lambda payload: payload["records"][0].update({"sequence_length": 999}),
            "sequence_join_uniprot_sequence_length_mismatch",
        ),
        (
            lambda payload: payload["records"][0]["mapping_annotations"][0].update(
                {"identity_replaced": True}
            ),
            "sequence_join_uniprot_mapping_invalid",
        ),
        (
            lambda payload: payload.update({"uniprot_release": "2026_04"}),
            "sequence_join_uniprot_provenance_mismatch",
        ),
        (
            lambda payload: (
                payload.update({"uniprot_release": "latest"}),
                payload["records"][0].update({"uniprot_release": "latest"}),
            ),
            "sequence_join_uniprot_metadata_invalid",
        ),
        (
            lambda payload: payload["records"][0]["provider_metadata"].update(
                {"primaryAccession": "Q8XYZ1"}
            ),
            "sequence_join_uniprot_provider_record_mismatch",
        ),
    ],
)
def test_uniprot_identity_provenance_and_mapping_drift_fail_closed(
    mutation,
    expected_code: str,
) -> None:  # type: ignore[no-untyped-def]
    score_csv = _hmmer_csv(
        [("P12345", "AOX_P12345", "1E-20", "250")]
    )
    fasta, metadata = _uniprot_inputs(
        [("P12345", "P12345", _sequence(675), True)]
    )
    changed = _mutate_metadata(metadata, mutation)

    with pytest.raises(aox_sequence_join.ScientificPrerequisiteError) as error:
        aox_sequence_join.join_score_filtered_accessions(score_csv, fasta, changed)

    assert _code(error) == expected_code


def test_explicit_sequence_mismatch_annotation_is_bound_without_identity_rewrite() -> None:
    score_csv = _hmmer_csv(
        [("P12345", "AOX_P12345", "1E-20", "250")]
    )
    sequence = _sequence(675)
    fasta, metadata = _uniprot_inputs(
        [("P12345", "P12345", sequence, True)]
    )

    def add_explicit_mapping(payload: dict[str, object]) -> None:
        record = payload["records"][0]  # type: ignore[index]
        record["mapping_annotations"].append(  # type: ignore[index,union-attr]
            {
                "annotation_type": "cross_database_sequence_identity",
                "source_database": "other",
                "source_accession": "OLD123",
                "source_sequence_digest": _digest("different"),
                "target_database": "uniprotkb",
                "target_accession": "P12345",
                "target_sequence_digest": _digest(sequence),
                "relationship": "sequence_mismatch_explicitly_resolved",
                "explicit_choice": "accept_uniprot",
                "identity_replaced": False,
            }
        )
        payload["source_sequence_identity_count"] = 1
        payload["sequence_mismatch_resolution_count"] = 1

    changed = _mutate_metadata(metadata, add_explicit_mapping)

    result = aox_sequence_join.join_score_filtered_accessions(
        score_csv,
        fasta,
        changed,
    )

    assert result.hits[0].uniprot_accession == "P12345"
    assert result.metadata()["uniprot_provider"][
        "sequence_mismatch_resolution_count"
    ] == 1


def test_provider_identifier_can_use_the_adapter_primary_accession_fallback() -> None:
    score_csv = _hmmer_csv(
        [("P12345", "AOX_P12345", "1E-20", "250")]
    )
    fasta, metadata = _uniprot_inputs(
        [("P12345", "P12345", _sequence(675), True)]
    )

    def remove_optional_identifier(payload: dict[str, object]) -> None:
        record = payload["records"][0]  # type: ignore[index]
        record["uniprot_identifier"] = "P12345"  # type: ignore[index]
        record["provider_metadata"].pop("uniProtkbId")  # type: ignore[index,union-attr]

    changed = _mutate_metadata(metadata, remove_optional_identifier)

    result = aox_sequence_join.join_score_filtered_accessions(
        score_csv,
        fasta,
        changed,
    )

    assert result.hits[0].uniprot_accession == "P12345"


@pytest.mark.parametrize(
    "binding",
    [
        {"expected_contract_id": "aox_sequence_length_join@2"},
        {"expected_contract_digest": "sha256:" + "0" * 64},
        {"expected_implementation_digest": "sha256:" + "0" * 64},
        {"expected_hmmer_contract_id": "hmmer_score_filtered_accessions@2"},
        {"expected_hmmer_contract_digest": "sha256:" + "0" * 64},
        {"expected_hmmer_implementation_digest": "sha256:" + "0" * 64},
    ],
)
def test_contract_or_upstream_hmmer_drift_fails_closed(
    binding: dict[str, str],
) -> None:
    score_csv = _hmmer_csv([])
    _, metadata = _uniprot_inputs([])

    with pytest.raises(aox_sequence_join.ScientificPrerequisiteError) as error:
        aox_sequence_join.join_score_filtered_accessions(
            score_csv,
            "",
            metadata,
            **binding,
        )

    assert _code(error) == "sequence_join_contract_digest_drift"


@pytest.mark.parametrize(
    "field",
    [
        "expected_score_filtered_csv_digest",
        "expected_uniprot_fasta_digest",
        "expected_uniprot_metadata_digest",
    ],
)
def test_each_input_byte_digest_is_checked_before_parsing(field: str) -> None:
    score_csv = _hmmer_csv([])
    _, metadata = _uniprot_inputs([])

    with pytest.raises(aox_sequence_join.ScientificPrerequisiteError) as error:
        aox_sequence_join.join_score_filtered_accessions(
            score_csv,
            "",
            metadata,
            **{field: "sha256:" + "0" * 64},
        )

    assert _code(error) == "sequence_join_input_digest_mismatch"
    expected_fields = {
        "expected_score_filtered_csv_digest": "hmmer_score_filtered_accessions_csv",
        "expected_uniprot_fasta_digest": "uniprot_sequences_fasta",
        "expected_uniprot_metadata_digest": "uniprot_metadata_json",
    }
    assert error.value.details["field"] == expected_fields[field]


@pytest.mark.parametrize(
    ("score_csv_mutation", "expected_code"),
    [
        (
            lambda text: text.replace("score_numeric", "score"),
            "sequence_join_hmmer_schema_mismatch",
        ),
        (
            lambda text: text.replace(",2.5E+2,", ",2E+2,"),
            "sequence_join_hmmer_threshold_mismatch",
        ),
        (
            lambda text: text.replace("sha256:", "sha256:BAD", 1),
            "sequence_join_hmmer_digest_invalid",
        ),
        (
            lambda text: text.rstrip("\n"),
            "sequence_join_hmmer_serialization_mismatch",
        ),
    ],
)
def test_hmmer_schema_threshold_digest_and_serialization_drift_fail_closed(
    score_csv_mutation,
    expected_code: str,
) -> None:  # type: ignore[no-untyped-def]
    score_csv = _hmmer_csv(
        [("P12345", "AOX_P12345", "1E-20", "250")]
    )
    fasta, metadata = _uniprot_inputs(
        [("P12345", "P12345", _sequence(675), True)]
    )

    with pytest.raises(aox_sequence_join.ScientificPrerequisiteError) as error:
        aox_sequence_join.join_score_filtered_accessions(
            score_csv_mutation(score_csv),
            fasta,
            metadata,
        )

    assert _code(error) == expected_code


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hmm_score", "250.0"),
        ("evalue", "0.0"),
        ("length", "0675"),
        ("target", " AOX_P12345"),
    ],
)
def test_canonical_output_serializer_rejects_noncanonical_fields(
    field: str,
    value: str,
) -> None:
    row = {
        "target": "AOX_P12345",
        "uniprot_accession": "P12345",
        "hmm_score": "2.5E+2",
        "evalue": "0",
        "length": "675",
        "sequence": _sequence(675),
    }
    row[field] = value

    with pytest.raises(aox_sequence_join.ScientificPrerequisiteError) as error:
        aox_sequence_join.canonical_hits_to_csv([row])

    assert _code(error) == "sequence_join_output_scientific_mismatch"


def test_metadata_duplicate_key_and_noncanonical_serialization_fail_closed() -> None:
    score_csv = _hmmer_csv([])
    _, metadata = _uniprot_inputs([])
    duplicate = metadata.replace(
        '  "provider": "uniprot",',
        '  "provider": "uniprot",\n  "provider": "uniprot",',
    )

    with pytest.raises(aox_sequence_join.ScientificPrerequisiteError) as duplicate_error:
        aox_sequence_join.join_score_filtered_accessions(score_csv, "", duplicate)
    with pytest.raises(aox_sequence_join.ScientificPrerequisiteError) as format_error:
        aox_sequence_join.join_score_filtered_accessions(
            score_csv,
            "",
            json.dumps(json.loads(metadata)),
        )

    assert _code(duplicate_error) == "sequence_join_uniprot_metadata_duplicate_key"
    assert _code(format_error) == "sequence_join_uniprot_metadata_serialization_mismatch"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("score_filtered_csv", b"\xff"),
        ("uniprot_fasta", b"\xff"),
        ("uniprot_metadata_json", b"\xff"),
    ],
)
def test_non_utf8_inputs_fail_closed(field: str, value: bytes) -> None:
    score_csv = _hmmer_csv([])
    _, metadata = _uniprot_inputs([])
    inputs: dict[str, str | bytes] = {
        "score_filtered_csv": score_csv,
        "uniprot_fasta": "",
        "uniprot_metadata_json": metadata,
    }
    inputs[field] = value

    with pytest.raises(aox_sequence_join.ScientificPrerequisiteError) as error:
        aox_sequence_join.join_score_filtered_accessions(**inputs)

    assert _code(error) == "sequence_join_input_not_utf8"
    expected_fields = {
        "score_filtered_csv": "hmmer_score_filtered_accessions_csv",
        "uniprot_fasta": "uniprot_sequences_fasta",
        "uniprot_metadata_json": "uniprot_metadata_json",
    }
    assert error.value.details["field"] == expected_fields[field]
