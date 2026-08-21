from __future__ import annotations

import csv
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path

import pytest

from enzymedesign_aox_executor import aox_hmmer


PAGE_DIGEST = "sha256:" + "a" * 64


def _digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _numeric(value: str) -> str:
    number = Decimal(value)
    return str(number.normalize()) if number else "0"


def _row(
    *,
    accession: str,
    score: str,
    hit_index: int,
    evalue: str = "1e-42",
    page: int = 1,
    target: str | None = None,
) -> dict[str, str]:
    payload: dict[str, object] = {
        "target": target or f"AOX_{accession}",
        "accession": accession,
        "evalue": evalue,
        "score": score,
        "page": page,
        "hit_index": hit_index,
        "evalue_numeric": _numeric(evalue),
        "score_numeric": _numeric(score),
        "raw_page_digest": PAGE_DIGEST,
        "raw_hit_digest": "sha256:" + f"{hit_index + 1:064x}",
    }
    serialized = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    payload["parsed_row_digest"] = _digest(serialized.encode("utf-8"))
    return {column: str(payload[column]) for column in aox_hmmer.INPUT_COLUMNS}


def _csv(rows: list[dict[str, str]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=list(aox_hmmer.INPUT_COLUMNS),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _code(error: pytest.ExceptionInfo[aox_hmmer.ScientificPrerequisiteError]) -> str:
    return error.value.code


def test_parse_and_filter_is_strictly_greater_than_200_and_sorts_accessions() -> None:
    source = _csv(
        [
            _row(accession="Q9XYZ1", score="201", hit_index=0),
            _row(accession="P12345", score="200.0001", hit_index=1),
            _row(accession="O98765", score="200", hit_index=2),
            _row(accession="A0A123", score="-1", hit_index=3),
        ]
    )

    result = aox_hmmer.parse_and_filter_csv(source)

    assert result.accessions == ("P12345", "Q9XYZ1")
    assert [hit.score_numeric for hit in result.hits] == ["200.0001", "201"]
    assert result.input_row_count == 4
    output = list(csv.DictReader(result.to_csv().splitlines()))
    assert [row["accession"] for row in output] == ["P12345", "Q9XYZ1"]
    assert tuple(output[0]) == aox_hmmer.OUTPUT_COLUMNS
    assert "length" not in output[0]
    assert "sequence" not in output[0]


def test_parse_and_filter_accepts_current_ten_character_uniprot_accession() -> None:
    source = _csv(
        [_row(accession="A0A378ARX6", score="300", hit_index=0)]
    )

    result = aox_hmmer.parse_and_filter_csv(source)

    assert result.accessions == ("A0A378ARX6",)
    assert result.hits[0].accession == "A0A378ARX6"


def test_metadata_binds_contract_input_output_and_cardinality() -> None:
    source = _csv([_row(accession="P12345", score="1834.7", hit_index=0)])

    result = aox_hmmer.parse_and_filter_csv(source)
    metadata = result.metadata()

    assert metadata == {
        "contract_id": aox_hmmer.CONTRACT_ID,
        "contract_digest": aox_hmmer.CONTRACT_DIGEST,
        "implementation_digest": aox_hmmer.IMPLEMENTATION_DIGEST,
        "input_digest": _digest(source.encode("utf-8")),
        "output_digest": _digest(result.to_csv().encode("utf-8")),
        "score_threshold_exclusive_gt": "200",
        "input_row_count": 1,
        "row_count": 1,
        "accession_count": 1,
        "accessions": ["P12345"],
        "healthy_empty": False,
    }
    assert result.output_digest == metadata["output_digest"]


def test_healthy_empty_input_has_canonical_header_only_output() -> None:
    source = _csv([])

    result = aox_hmmer.parse_and_filter_csv(source)

    assert result.accessions == ()
    assert result.hits == ()
    assert result.to_csv() == ",".join(aox_hmmer.OUTPUT_COLUMNS) + "\n"
    assert result.metadata()["healthy_empty"] is True
    assert result.metadata()["input_row_count"] == 0
    assert result.metadata()["row_count"] == 0


def test_nonempty_input_can_filter_to_a_canonical_healthy_empty_output() -> None:
    source = _csv(
        [
            _row(accession="P12345", score="200", hit_index=0),
            _row(accession="Q9XYZ1", score="199.999", hit_index=1),
        ]
    )

    result = aox_hmmer.parse_and_filter_csv(source)

    assert result.accessions == ()
    assert result.metadata()["input_row_count"] == 2
    assert result.metadata()["healthy_empty"] is True


@pytest.mark.parametrize(
    "columns",
    [
        aox_hmmer.INPUT_COLUMNS[:-1],
        (*aox_hmmer.INPUT_COLUMNS, "length"),
        tuple(reversed(aox_hmmer.INPUT_COLUMNS)),
    ],
)
def test_input_schema_must_match_provider_columns_exactly(
    columns: tuple[str, ...],
) -> None:
    source = ",".join(columns) + "\n"

    with pytest.raises(aox_hmmer.ScientificPrerequisiteError) as error:
        aox_hmmer.parse_and_filter_csv(source)

    assert _code(error) == "hmmer_filter_input_schema_mismatch"


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("accession", "p12345", "hmmer_filter_accession_invalid"),
        ("accession", "NOT_UNIPROT", "hmmer_filter_accession_invalid"),
        ("target", " AOX", "hmmer_filter_target_invalid"),
        ("evalue", "NaN", "hmmer_filter_numeric_invalid"),
        ("evalue", "-1", "hmmer_filter_numeric_invalid"),
        ("score", "Infinity", "hmmer_filter_numeric_invalid"),
        ("page", "0", "hmmer_filter_integer_invalid"),
        ("hit_index", "00", "hmmer_filter_integer_invalid"),
        ("raw_page_digest", "sha256:bad", "hmmer_filter_digest_invalid"),
        ("raw_hit_digest", "sha256:" + "A" * 64, "hmmer_filter_digest_invalid"),
    ],
)
def test_invalid_provider_fields_fail_closed(
    field: str,
    value: str,
    expected_code: str,
) -> None:
    row = _row(accession="P12345", score="300", hit_index=0)
    row[field] = value

    with pytest.raises(aox_hmmer.ScientificPrerequisiteError) as error:
        aox_hmmer.parse_and_filter_csv(_csv([row]))

    assert _code(error) == expected_code


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evalue_numeric", "1e-42"),
        ("evalue_numeric", "1E-41"),
        ("score_numeric", "300.0"),
        ("score_numeric", "301"),
    ],
)
def test_numeric_projections_must_match_raw_provider_values_exactly(
    field: str,
    value: str,
) -> None:
    row = _row(accession="P12345", score="300", hit_index=0)
    row[field] = value

    with pytest.raises(aox_hmmer.ScientificPrerequisiteError) as error:
        aox_hmmer.parse_and_filter_csv(_csv([row]))

    assert _code(error) == "hmmer_filter_numeric_binding_mismatch"


def test_parsed_row_digest_is_recomputed_from_provider_typed_row() -> None:
    row = _row(accession="P12345", score="300", hit_index=0)
    row["parsed_row_digest"] = "sha256:" + "f" * 64

    with pytest.raises(aox_hmmer.ScientificPrerequisiteError) as error:
        aox_hmmer.parse_and_filter_csv(_csv([row]))

    assert _code(error) == "hmmer_filter_parsed_row_digest_mismatch"


def test_duplicate_accessions_fail_instead_of_silently_collapsing_provenance() -> None:
    source = _csv(
        [
            _row(accession="P12345", score="300", hit_index=0),
            _row(accession="P12345", score="400", hit_index=1),
        ]
    )

    with pytest.raises(aox_hmmer.ScientificPrerequisiteError) as error:
        aox_hmmer.parse_and_filter_csv(source)

    assert _code(error) == "hmmer_filter_duplicate_accession"


def test_provider_row_order_and_contiguous_hit_indexes_are_required() -> None:
    source = _csv([_row(accession="P12345", score="300", hit_index=1)])

    with pytest.raises(aox_hmmer.ScientificPrerequisiteError) as error:
        aox_hmmer.parse_and_filter_csv(source)

    assert _code(error) == "hmmer_filter_provider_order_invalid"


def test_expected_input_digest_is_checked_before_scientific_parsing() -> None:
    source = _csv([_row(accession="P12345", score="300", hit_index=0)])

    with pytest.raises(aox_hmmer.ScientificPrerequisiteError) as error:
        aox_hmmer.parse_and_filter_csv(
            source,
            expected_input_digest="sha256:" + "0" * 64,
        )

    assert _code(error) == "hmmer_filter_input_digest_mismatch"


@pytest.mark.parametrize(
    "binding",
    [
        {"expected_contract_id": "hmmer_score_filtered_accessions@2"},
        {"expected_contract_digest": "sha256:" + "0" * 64},
        {"expected_implementation_digest": "sha256:" + "0" * 64},
    ],
)
def test_contract_identity_drift_fails_closed(binding: dict[str, str]) -> None:
    with pytest.raises(aox_hmmer.ScientificPrerequisiteError) as error:
        aox_hmmer.parse_and_filter_csv(_csv([]), **binding)

    assert _code(error) == "hmmer_filter_contract_digest_drift"


def test_contract_and_implementation_digests_are_recomputable() -> None:
    source_path = Path(aox_hmmer.__file__)

    assert aox_hmmer.CONTRACT_ID == "hmmer_score_filtered_accessions@1"
    assert aox_hmmer.implementation_digest() == _digest(source_path.read_bytes())
    assert aox_hmmer.IMPLEMENTATION_DIGEST == aox_hmmer.implementation_digest()
    assert (
        aox_hmmer.contract_digest(
            implementation_digest_value=aox_hmmer.IMPLEMENTATION_DIGEST
        )
        == aox_hmmer.CONTRACT_DIGEST
    )
    payload = aox_hmmer.contract_payload(
        implementation_digest_value=aox_hmmer.IMPLEMENTATION_DIGEST
    )
    assert payload["filter"] == {
        "field": "score_numeric",
        "operator": "strictly_greater_than",
        "threshold": "200",
    }
    assert payload["output"]["forbidden_pre_uniprot_fields"] == [
        "length",
        "sequence",
    ]


def test_non_utf8_input_fails_closed() -> None:
    with pytest.raises(aox_hmmer.ScientificPrerequisiteError) as error:
        aox_hmmer.parse_and_filter_csv(b"\xff")

    assert _code(error) == "hmmer_filter_input_not_utf8"
