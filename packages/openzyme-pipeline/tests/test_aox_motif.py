from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import pytest

from openzyme_pipeline import aox_motif


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "aox_motif_rule_score_v1"
ALIGNMENT_PATH = FIXTURE_ROOT / "alignment.fasta"
EXPECTED_PATH = FIXTURE_ROOT / "expected.json"


def _fixture_bytes() -> bytes:
    return ALIGNMENT_PATH.read_bytes()


def _expected() -> dict[str, object]:
    return json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))


def _error_code(
    error: pytest.ExceptionInfo[aox_motif.ScientificPrerequisiteError],
) -> str:
    assert error.value.to_dict()["error_type"] == "scientific_prerequisite_missing"
    return error.value.code


def _golden_result() -> aox_motif.ScoringResult:
    expected = _expected()["expected"]
    assert isinstance(expected, dict)
    return aox_motif.score_aligned_fasta(
        _fixture_bytes(),
        expected_contract_id=str(expected["contract_id"]),
        expected_contract_digest=str(expected["contract_digest"]),
        expected_implementation_digest=str(expected["implementation_digest"]),
        expected_input_digest=str(expected["input_digest"]),
    )


def test_reference_derived_golden_scores_and_digests() -> None:
    fixture = _expected()
    expected = fixture["expected"]
    assert isinstance(expected, dict)
    result = _golden_result()

    assert fixture["derivation"] == {
        "method": (
            "Retain exactly the alignment columns occupied by the ungapped "
            "AAB57849.1 reference and preserve the observed residues for three "
            "authorized reference rows."
        ),
        "source_alignment_digest": (
            "sha256:993ee2b3175abb68d2e1a4aad56edce1c3d33a19b07a600912fe6844e6484bfa"
        ),
        "source_records": {
            "AAB57849.1": "AAB57849.1 alcohol oxidase [Komagataella pastoris]",
            "K3VE05_FUSPC": "tr|K3VE05|K3VE05_FUSPC",
            "pdb|9AVH|A": "pdb|9AVH|A Chain A, Aryl Alcohol Oxidase",
        },
    }
    assert result.alignment.input_digest == expected["input_digest"]
    assert result.alignment.alignment_digest == expected["alignment_digest"]
    assert result.alignment.width == expected["alignment_width"]
    assert result.reference.sequence_digest == expected["reference_sequence_digest"]
    assert aox_motif.CONTRACT_ID == expected["contract_id"]
    assert aox_motif.CONTRACT_DIGEST == expected["contract_digest"]
    assert aox_motif.IMPLEMENTATION_DIGEST == expected["implementation_digest"]

    actual_rows = result.canonical_rows()
    golden_rows = expected["rows"]
    assert isinstance(golden_rows, list)
    assert [row["sequence_id"] for row in actual_rows] == [
        row["sequence_id"] for row in golden_rows
    ]
    for actual, golden in zip(actual_rows, golden_rows, strict=True):
        assert actual["sequence_digest"] == golden["sequence_digest"]
        assert actual["aligned_sequence_digest"] == golden["aligned_sequence_digest"]
        assert actual["motif_rule_score_tenths"] == golden["motif_rule_score_tenths"]
        assert actual["motif_rule_score"] == golden["motif_rule_score"]
        assert actual["passes_motif_rule"] is golden["passes_motif_rule"]
        assert {
            str(coordinate): actual[f"residue_{coordinate}"]
            for coordinate in aox_motif.RULE_COORDINATES
        } == golden["residues"]

    canonical_csv = result.to_csv()
    assert "activity_score" not in canonical_csv
    assert "seq_score" not in canonical_csv
    assert "pass_rule" not in canonical_csv
    assert "motif_rule_score,passes_motif_rule" in canonical_csv
    assert (
        "sha256:" + hashlib.sha256(canonical_csv.encode("utf-8")).hexdigest()
        == expected["canonical_csv_digest"]
    )
    parsed_csv = list(csv.DictReader(io.StringIO(canonical_csv)))
    assert [row["passes_motif_rule"] for row in parsed_csv] == ["true", "true", "false"]


def test_exact_integer_tenths_preserve_the_33_6_boundary() -> None:
    reference_row = _golden_result().canonical_rows()[0]

    assert 5 + 5 + 5 + 5 + 2 + 2 + 5 + 5 - 0.1 - 0.1 - 0.1 - 0.1 < 33.6
    assert reference_row["motif_rule_score_tenths"] == 336
    assert reference_row["motif_rule_score"] == "33.6"
    assert reference_row["passes_motif_rule"] is True


def test_contract_payload_covers_rules_schema_and_non_activity_claim() -> None:
    payload = aox_motif.contract_payload(
        implementation_digest_value=aox_motif.IMPLEMENTATION_DIGEST
    )

    assert payload["contract_id"] == "aox_motif_rule_score@1"
    assert "not experimental activity prediction" in str(payload["scientific_claim"])
    assert payload["reference"] == {
        "accession": "AAB57849.1",
        "coordinate_convention": "one-based ungapped reference coordinates",
        "resolution": "exact FASTA sequence identifier",
    }
    assert payload["alignment_input"] == {
        "canonicalization_id": "hmmer_afa_alignment_canonicalization@1",
        "format": "aligned_fasta",
        "raw_sequence_line_pattern": "^[A-Za-z.-]+$",
        "empty_lines": "ignored",
        "sequence_line_whitespace": "rejected",
        "physical_lines": (
            "split_on_lf_and_remove_one_immediately_preceding_cr_only_"
            "from_lf_terminated_lines"
        ),
        "header_start": "raw_column_zero_greater_than",
        "bare_header_carriage_return": "forbidden",
        "residue_case": ("case_insensitive_ascii_letters_canonicalized_to_uppercase"),
        "accepted_gap_characters": ["-", "."],
        "gap_semantics": {
            "-": "canonical_alignment_gap",
            ".": "hmmer_insert_column_gap",
        },
        "canonical_gap_character": "-",
        "canonicalization_order": (
            "validate_raw_alignment_characters_then_uppercase_residues_"
            "then_replace_hmmer_insert_column_dots_with_hyphens"
        ),
        "input_digest_semantics": "sha256_of_exact_precanonicalization_bytes",
        "alignment_digest_semantics": (
            "sha256_of_canonical_uppercase_hyphen_gap_alignment_records"
        ),
    }
    calculation = payload["calculation"]
    assert isinstance(calculation, dict)
    assert calculation["threshold_tenths"] == 336
    assert calculation["threshold_display"] == "33.6"
    assert calculation["non_gap_penalty"] == {
        "coordinates": [660, 661, 662, 663],
        "weight_tenths_each": -1,
    }
    assert [rule["weight_tenths"] for rule in calculation["positive_rules"]] == [
        50,
        50,
        50,
        50,
        20,
        20,
        50,
        50,
    ]
    assert [field["name"] for field in payload["output_schema"]] == list(
        aox_motif.CANONICAL_COLUMNS
    )
    assert payload["implementation_digest"] == aox_motif.IMPLEMENTATION_DIGEST


def test_implementation_digest_is_the_installed_source_digest() -> None:
    source_path = Path(aox_motif.__file__)
    expected = "sha256:" + hashlib.sha256(source_path.read_bytes()).hexdigest()

    assert aox_motif.implementation_digest() == expected
    assert aox_motif.IMPLEMENTATION_DIGEST == expected
    assert (
        aox_motif.contract_digest(implementation_digest_value=expected)
        == aox_motif.CONTRACT_DIGEST
    )


def test_canonical_alignment_and_row_order_do_not_depend_on_record_order() -> None:
    original = aox_motif.parse_aligned_fasta(_fixture_bytes())
    reversed_fasta = "".join(
        f">{record.sequence_id} {record.description}\n{record.aligned_sequence}\n"
        for record in reversed(original.records)
    )
    reordered = aox_motif.score_aligned_fasta(reversed_fasta)

    assert reordered.alignment.input_digest != original.input_digest
    assert reordered.alignment.alignment_digest == original.alignment_digest
    assert [row.sequence_id for row in reordered.rows] == [
        "AAB57849.1",
        "K3VE05_FUSPC",
        "pdb|9AVH|A",
    ]
    assert [row.score_tenths for row in reordered.rows] == [336, 340, 320]


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "empty_alignment"),
        (b"AAAA\n", "sequence_before_header"),
        (b" >record\nAAAA\n", "sequence_before_header"),
        (b"\t>record\nAAAA\n", "sequence_before_header"),
        (b">\nAAAA\n", "empty_fasta_header"),
        (b">record\r", "fasta_header_carriage_return"),
        (b">rec\rord\nAAAA\n", "fasta_header_carriage_return"),
        (b">record\r\r\nAAAA\n", "fasta_header_carriage_return"),
        (b">record\n", "empty_alignment_sequence"),
        (b">record\nAA*A\n", "invalid_alignment_residue"),
        (b">record\nAA AA\n", "whitespace_in_alignment_sequence"),
        (b">record\n AAA\n", "whitespace_in_alignment_sequence"),
        (b">record\nAAA \n", "whitespace_in_alignment_sequence"),
        (b">record\nAAA\r", "whitespace_in_alignment_sequence"),
        (b">record\nAA\rA\n", "whitespace_in_alignment_sequence"),
        (b">record\nAA\tAA\n", "whitespace_in_alignment_sequence"),
        (">record\nAA\u00a0AA\n".encode(), "whitespace_in_alignment_sequence"),
        (">record\nAA\u2028AA\n".encode(), "whitespace_in_alignment_sequence"),
        (">record\nAAßAA\n".encode(), "invalid_alignment_residue"),
        (">record\nAAſAA\n".encode(), "invalid_alignment_residue"),
        (b">record\n\xff\n", "alignment_not_utf8"),
    ],
)
def test_parser_rejects_malformed_alignment(data: bytes, code: str) -> None:
    with pytest.raises(aox_motif.ScientificPrerequisiteError) as error:
        aox_motif.parse_aligned_fasta(data)

    assert _error_code(error) == code


def test_parser_normalizes_sequence_case_and_line_wrapping() -> None:
    lines = _fixture_bytes().decode("utf-8").splitlines()
    lower_sequences = "\n".join(
        line if line.startswith(">") else line.lower() for line in lines
    )
    original = aox_motif.parse_aligned_fasta(_fixture_bytes())
    normalized = aox_motif.parse_aligned_fasta(lower_sequences)

    assert normalized.input_digest != original.input_digest
    assert normalized.alignment_digest == original.alignment_digest


def test_parser_allows_explicit_empty_lines_and_crlf_delimiters() -> None:
    with_blank_lines = b"\n>first\r\n\r\nAa.-\r\n\r\n>second\r\nAa.-\r\n\n"
    canonical = b">first\nAA--\n>second\nAA--\n"

    parsed = aox_motif.parse_aligned_fasta(with_blank_lines)
    canonical_parsed = aox_motif.parse_aligned_fasta(canonical)

    assert parsed.input_digest == (
        "sha256:" + hashlib.sha256(with_blank_lines).hexdigest()
    )
    assert parsed.input_digest != canonical_parsed.input_digest
    assert parsed.alignment_digest == canonical_parsed.alignment_digest
    assert [record.aligned_sequence for record in parsed.records] == ["AA--", "AA--"]


def test_hmmer_insert_gap_and_lowercase_residue_input_canonicalize_to_hyphens() -> None:
    hyphen_input = _fixture_bytes()
    hmmer_style_input = "\n".join(
        line if line.startswith(">") else line.lower().replace("-", ".")
        for line in hyphen_input.decode("utf-8").splitlines()
    ).encode("utf-8")

    hyphen_result = aox_motif.score_aligned_fasta(hyphen_input)
    hmmer_style_result = aox_motif.score_aligned_fasta(hmmer_style_input)

    assert hyphen_result.alignment.input_digest == (
        "sha256:" + hashlib.sha256(hyphen_input).hexdigest()
    )
    assert hmmer_style_result.alignment.input_digest == (
        "sha256:" + hashlib.sha256(hmmer_style_input).hexdigest()
    )
    assert hmmer_style_result.alignment.input_digest != (
        hyphen_result.alignment.input_digest
    )
    assert hmmer_style_result.alignment.alignment_digest == (
        hyphen_result.alignment.alignment_digest
    )
    assert [
        record.aligned_sequence for record in hmmer_style_result.alignment.records
    ] == [record.aligned_sequence for record in hyphen_result.alignment.records]
    assert all(
        "." not in record.aligned_sequence
        for record in hmmer_style_result.alignment.records
    )

    for canonical, hmmer_style in zip(
        hyphen_result.canonical_rows(),
        hmmer_style_result.canonical_rows(),
        strict=True,
    ):
        assert canonical["input_digest"] != hmmer_style["input_digest"]
        assert {
            key: value for key, value in canonical.items() if key != "input_digest"
        } == {key: value for key, value in hmmer_style.items() if key != "input_digest"}


def test_missing_reference_fails_exactly() -> None:
    data = _fixture_bytes().replace(b">AAB57849.1 ", b">AAB57849.2 ", 1)

    with pytest.raises(aox_motif.ScientificPrerequisiteError) as error:
        aox_motif.score_aligned_fasta(data)

    assert _error_code(error) == "reference_missing"


def test_reference_substring_is_not_accepted() -> None:
    data = _fixture_bytes().replace(b">AAB57849.1 ", b">prefix_AAB57849.1 ", 1)

    with pytest.raises(aox_motif.ScientificPrerequisiteError) as error:
        aox_motif.score_aligned_fasta(data)

    assert _error_code(error) == "reference_missing"


def test_duplicate_reference_is_ambiguous_before_generic_duplicate_check() -> None:
    alignment = aox_motif.parse_aligned_fasta(_fixture_bytes())
    reference = alignment.records[0]
    data = (
        _fixture_bytes().decode("utf-8")
        + f">{reference.sequence_id} duplicate\n{reference.aligned_sequence}\n"
    )

    with pytest.raises(aox_motif.ScientificPrerequisiteError) as error:
        aox_motif.score_aligned_fasta(data)

    assert _error_code(error) == "reference_ambiguous"


def test_duplicate_non_reference_identifier_is_rejected() -> None:
    alignment = aox_motif.parse_aligned_fasta(_fixture_bytes())
    target = alignment.records[1]
    data = (
        _fixture_bytes().decode("utf-8")
        + f">{target.sequence_id} duplicate\n{target.aligned_sequence}\n"
    )

    with pytest.raises(aox_motif.ScientificPrerequisiteError) as error:
        aox_motif.score_aligned_fasta(data)

    assert _error_code(error) == "duplicate_sequence_id"


def test_truncated_reference_fails_before_scoring() -> None:
    sequence = "A" * (aox_motif.MAX_RULE_COORDINATE - 1)
    data = f">AAB57849.1\n{sequence}\n>target\n{sequence}\n"

    with pytest.raises(aox_motif.ScientificPrerequisiteError) as error:
        aox_motif.score_aligned_fasta(data)

    assert _error_code(error) == "reference_truncated"
    assert error.value.details["observed_ungapped_length"] == 662


def test_unequal_alignment_width_fails_before_scoring() -> None:
    data = f">AAB57849.1\n{'A' * 663}\n>target\n{'A' * 662}\n"

    with pytest.raises(aox_motif.ScientificPrerequisiteError) as error:
        aox_motif.score_aligned_fasta(data)

    assert _error_code(error) == "unequal_alignment_width"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"expected_contract_id": ""},
        {"expected_contract_digest": ""},
        {"expected_implementation_digest": ""},
        {"expected_contract_id": "aox_motif_rule_score@2"},
        {"expected_contract_digest": "sha256:" + "0" * 64},
        {"expected_implementation_digest": "sha256:" + "0" * 64},
    ],
)
def test_bound_contract_drift_fails_before_parsing(kwargs: dict[str, str]) -> None:
    with pytest.raises(aox_motif.ScientificPrerequisiteError) as error:
        aox_motif.score_aligned_fasta(b"not even FASTA", **kwargs)

    assert _error_code(error) == "scoring_digest_drift"


def test_input_digest_drift_fails_before_scoring_rows_are_created() -> None:
    with pytest.raises(aox_motif.ScientificPrerequisiteError) as error:
        aox_motif.score_aligned_fasta(
            _fixture_bytes(),
            expected_input_digest="sha256:" + "0" * 64,
        )

    assert _error_code(error) == "alignment_input_digest_mismatch"


def test_legacy_scoring_fields_are_never_accepted_as_canonical() -> None:
    row = dict(_golden_result().canonical_rows()[0])
    row["seq_score"] = 33.6
    row["activity_score"] = 33.6
    row["pass_rule"] = True

    with pytest.raises(aox_motif.ScientificPrerequisiteError) as error:
        aox_motif.validate_canonical_rows([row])

    assert _error_code(error) == "legacy_scoring_schema"
    assert error.value.details["fields"] == ["activity_score", "pass_rule", "seq_score"]


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ({"motif_rule_score_tenths": 33.6}, "scoring_output_score_invalid"),
        ({"motif_rule_score": "33.60"}, "scoring_output_score_invalid"),
        ({"passes_motif_rule": False}, "scoring_output_pass_invalid"),
        (
            {
                "motif_rule_score_tenths": 337,
                "motif_rule_score": "33.7",
            },
            "scoring_output_recalculation_mismatch",
        ),
        ({"residue_417": "V"}, "scoring_output_recalculation_mismatch"),
        ({"residue_417": "GG"}, "scoring_output_residue_invalid"),
        ({"alignment_width": 662}, "scoring_output_alignment_width_invalid"),
        (
            {"scoring_contract_digest": "sha256:" + "0" * 64},
            "scoring_output_contract_mismatch",
        ),
        (
            {"scoring_implementation_digest": "sha256:" + "0" * 64},
            "scoring_output_implementation_mismatch",
        ),
    ],
)
def test_canonical_row_validation_is_fail_closed(
    mutation: dict[str, object],
    code: str,
) -> None:
    row = dict(_golden_result().canonical_rows()[0])
    row.update(mutation)

    with pytest.raises(aox_motif.ScientificPrerequisiteError) as error:
        aox_motif.validate_canonical_rows([row])

    assert _error_code(error) == code


def test_canonical_row_schema_requires_every_field_and_no_extras() -> None:
    missing = dict(_golden_result().canonical_rows()[0])
    missing.pop("residue_13")
    with pytest.raises(aox_motif.ScientificPrerequisiteError) as missing_error:
        aox_motif.validate_canonical_rows([missing])
    assert _error_code(missing_error) == "scoring_output_schema_mismatch"

    extra = dict(_golden_result().canonical_rows()[0])
    extra["unversioned_annotation"] = "not canonical"
    with pytest.raises(aox_motif.ScientificPrerequisiteError) as extra_error:
        aox_motif.validate_canonical_rows([extra])
    assert _error_code(extra_error) == "scoring_output_schema_mismatch"


def test_canonical_rows_require_one_identity_and_lexical_order() -> None:
    rows = [dict(row) for row in _golden_result().canonical_rows()]
    rows[1]["input_digest"] = "sha256:" + "0" * 64
    with pytest.raises(aox_motif.ScientificPrerequisiteError) as identity_error:
        aox_motif.validate_canonical_rows(rows)
    assert _error_code(identity_error) == "scoring_output_identity_mismatch"

    reversed_rows = list(reversed(_golden_result().canonical_rows()))
    with pytest.raises(aox_motif.ScientificPrerequisiteError) as order_error:
        aox_motif.validate_canonical_rows(reversed_rows)
    assert _error_code(order_error) == "scoring_output_order_invalid"


def test_error_envelope_is_stable_and_contains_no_input_bytes() -> None:
    with pytest.raises(aox_motif.ScientificPrerequisiteError) as error:
        aox_motif.score_aligned_fasta(b">private_sequence\nSECRET*\n")

    envelope = error.value.to_dict()
    assert envelope["error_type"] == "scientific_prerequisite_missing"
    assert envelope["code"] == "invalid_alignment_residue"
    assert "SECRET" not in json.dumps(envelope, sort_keys=True)
