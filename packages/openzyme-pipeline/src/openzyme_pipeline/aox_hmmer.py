from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .aox_motif import ScientificPrerequisiteError


CONTRACT_ID = "hmmer_score_filtered_accessions@1"
SCORE_THRESHOLD_DISPLAY = "200"

INPUT_COLUMNS = (
    "target",
    "accession",
    "evalue",
    "score",
    "page",
    "hit_index",
    "evalue_numeric",
    "score_numeric",
    "raw_page_digest",
    "raw_hit_digest",
    "parsed_row_digest",
)
OUTPUT_COLUMNS = (
    "accession",
    "target",
    "evalue_numeric",
    "score_numeric",
    "raw_page_digest",
    "raw_hit_digest",
    "parsed_row_digest",
)

_SCORE_THRESHOLD = Decimal(SCORE_THRESHOLD_DISPLAY)
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_UNIPROT_ACCESSION_PATTERN = re.compile(
    r"(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}){1,2}[0-9])(?:-[0-9]+)?"
)


@dataclass(frozen=True, slots=True)
class HmmerHit:
    target: str
    accession: str
    evalue_numeric: str
    score_numeric: str
    page: int
    hit_index: int
    raw_page_digest: str
    raw_hit_digest: str
    parsed_row_digest: str

    @property
    def score(self) -> Decimal:
        return Decimal(self.score_numeric)

    def to_output_row(self) -> dict[str, str]:
        return {
            "accession": self.accession,
            "target": self.target,
            "evalue_numeric": self.evalue_numeric,
            "score_numeric": self.score_numeric,
            "raw_page_digest": self.raw_page_digest,
            "raw_hit_digest": self.raw_hit_digest,
            "parsed_row_digest": self.parsed_row_digest,
        }


@dataclass(frozen=True, slots=True)
class ScoreFilteredAccessionsResult:
    hits: tuple[HmmerHit, ...]
    input_digest: str
    input_row_count: int

    @property
    def accessions(self) -> tuple[str, ...]:
        return tuple(hit.accession for hit in self.hits)

    @property
    def output_digest(self) -> str:
        return _sha256(self.to_csv().encode("utf-8"))

    def to_csv(self) -> str:
        return canonical_rows_to_csv(hit.to_output_row() for hit in self.hits)

    def metadata(self) -> dict[str, object]:
        return {
            "contract_id": CONTRACT_ID,
            "contract_digest": CONTRACT_DIGEST,
            "implementation_digest": IMPLEMENTATION_DIGEST,
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
            "score_threshold_exclusive_gt": SCORE_THRESHOLD_DISPLAY,
            "input_row_count": self.input_row_count,
            "row_count": len(self.hits),
            "accession_count": len(self.accessions),
            "accessions": list(self.accessions),
            "healthy_empty": not self.hits,
        }


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def implementation_digest() -> str:
    return _sha256(Path(__file__).read_bytes())


def contract_payload(
    *, implementation_digest_value: str | None = None
) -> dict[str, object]:
    source_digest = implementation_digest_value or implementation_digest()
    return {
        "contract_id": CONTRACT_ID,
        "scientific_claim": (
            "deterministic pre-UniProt accession selection by EBI HMMER score; "
            "not a sequence-length or activity filter"
        ),
        "upstream": {
            "provider": "ebi_hmmer",
            "database": "refprot",
            "artifact_path": "provider_parsed/parsed_hits.csv",
            "columns": list(INPUT_COLUMNS),
            "row_digest": {
                "field": "parsed_row_digest",
                "algorithm": "sha256",
                "serialization": "json_sort_keys_indent_2_trailing_newline",
            },
        },
        "validation": {
            "exact_input_schema": True,
            "numeric_fields": "finite_decimal_with_provider_canonical_form",
            "evalue_domain": "nonnegative",
            "accession_identity": "uppercase_uniprot_accession",
            "accession_uniqueness": "required",
            "provider_hit_index": "zero_based_contiguous_input_order",
            "digest_format": "sha256_lowercase_hex",
        },
        "filter": {
            "field": "score_numeric",
            "operator": "strictly_greater_than",
            "threshold": SCORE_THRESHOLD_DISPLAY,
        },
        "output": {
            "columns": list(OUTPUT_COLUMNS),
            "ordering": "accession_lexical_ascending",
            "uniqueness": "one_row_per_accession",
            "healthy_empty": "header_only_csv",
            "forbidden_pre_uniprot_fields": ["length", "sequence"],
        },
        "implementation_digest": source_digest,
    }


def contract_digest(*, implementation_digest_value: str | None = None) -> str:
    return _sha256(
        _canonical_json_bytes(
            contract_payload(implementation_digest_value=implementation_digest_value)
        )
    )


def verify_contract(
    *,
    expected_contract_id: str = CONTRACT_ID,
    expected_contract_digest: str | None = None,
    expected_implementation_digest: str | None = None,
) -> None:
    expected = {
        "contract_id": expected_contract_id,
        "contract_digest": expected_contract_digest or CONTRACT_DIGEST,
        "implementation_digest": expected_implementation_digest
        or IMPLEMENTATION_DIGEST,
    }
    actual = {
        "contract_id": CONTRACT_ID,
        "contract_digest": CONTRACT_DIGEST,
        "implementation_digest": IMPLEMENTATION_DIGEST,
    }
    for field, value in expected.items():
        if field.endswith("digest") and not _DIGEST_PATTERN.fullmatch(str(value)):
            raise ScientificPrerequisiteError(
                "hmmer_filter_bound_digest_invalid",
                "a bound HMMER score-filter digest is not canonical sha256",
                details={"field": field, "value": str(value)},
            )
    if expected != actual:
        raise ScientificPrerequisiteError(
            "hmmer_filter_contract_digest_drift",
            "the bound HMMER score-filter identity does not match the installed implementation",
            details={"expected": expected, "actual": actual},
        )


def _parse_decimal(
    value: str,
    *,
    field: str,
    row_number: int,
    nonnegative: bool,
) -> Decimal:
    if not value or value != value.strip():
        raise ScientificPrerequisiteError(
            "hmmer_filter_numeric_invalid",
            "an HMMER numeric field is empty or contains surrounding whitespace",
            details={"row": row_number, "field": field, "value": value},
        )
    try:
        numeric = Decimal(value)
    except InvalidOperation as exc:
        raise ScientificPrerequisiteError(
            "hmmer_filter_numeric_invalid",
            "an HMMER numeric field is not a decimal number",
            details={"row": row_number, "field": field, "value": value},
        ) from exc
    if not numeric.is_finite() or (nonnegative and numeric < 0):
        raise ScientificPrerequisiteError(
            "hmmer_filter_numeric_invalid",
            "an HMMER numeric field is outside its accepted finite domain",
            details={"row": row_number, "field": field, "value": value},
        )
    return numeric


def _provider_decimal_display(value: Decimal) -> str:
    return str(value.normalize()) if value else "0"


def _parse_provider_integer(
    value: str,
    *,
    field: str,
    row_number: int,
    minimum: int,
) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ScientificPrerequisiteError(
            "hmmer_filter_integer_invalid",
            "an HMMER provider index is not an integer",
            details={"row": row_number, "field": field, "value": value},
        ) from exc
    if str(parsed) != value or parsed < minimum:
        raise ScientificPrerequisiteError(
            "hmmer_filter_integer_invalid",
            "an HMMER provider index is outside its canonical domain",
            details={"row": row_number, "field": field, "value": value},
        )
    return parsed


def _validate_digest(value: str, *, field: str, row_number: int) -> None:
    if not _DIGEST_PATTERN.fullmatch(value):
        raise ScientificPrerequisiteError(
            "hmmer_filter_digest_invalid",
            "an HMMER provenance digest is not canonical sha256",
            details={"row": row_number, "field": field, "value": value},
        )


def _parsed_row_digest(row: Mapping[str, object]) -> str:
    content = json.dumps(dict(row), sort_keys=True, indent=2) + "\n"
    return _sha256(content.encode("utf-8"))


def _parse_hit(row: Mapping[str, str], *, row_number: int) -> HmmerHit:
    target = row["target"]
    if (
        not target
        or target != target.strip()
        or any(ord(character) < 32 or ord(character) > 126 for character in target)
    ):
        raise ScientificPrerequisiteError(
            "hmmer_filter_target_invalid",
            "an HMMER target must be non-empty printable ASCII without surrounding whitespace",
            details={"row": row_number, "target": target},
        )

    accession = row["accession"]
    if _UNIPROT_ACCESSION_PATTERN.fullmatch(accession) is None:
        raise ScientificPrerequisiteError(
            "hmmer_filter_accession_invalid",
            "an HMMER refprot row does not contain one canonical uppercase UniProt accession",
            details={"row": row_number, "accession": accession},
        )

    evalue = _parse_decimal(
        row["evalue"], field="evalue", row_number=row_number, nonnegative=True
    )
    score = _parse_decimal(
        row["score"], field="score", row_number=row_number, nonnegative=False
    )
    evalue_numeric = _parse_decimal(
        row["evalue_numeric"],
        field="evalue_numeric",
        row_number=row_number,
        nonnegative=True,
    )
    score_numeric = _parse_decimal(
        row["score_numeric"],
        field="score_numeric",
        row_number=row_number,
        nonnegative=False,
    )
    expected_numeric = {
        "evalue_numeric": _provider_decimal_display(evalue),
        "score_numeric": _provider_decimal_display(score),
    }
    actual_numeric = {
        "evalue_numeric": row["evalue_numeric"],
        "score_numeric": row["score_numeric"],
    }
    if (
        actual_numeric != expected_numeric
        or evalue_numeric != evalue
        or score_numeric != score
    ):
        raise ScientificPrerequisiteError(
            "hmmer_filter_numeric_binding_mismatch",
            "HMMER normalized numeric fields do not exactly match their raw provider values",
            details={
                "row": row_number,
                "expected": expected_numeric,
                "actual": actual_numeric,
            },
        )

    page = _parse_provider_integer(
        row["page"], field="page", row_number=row_number, minimum=1
    )
    hit_index = _parse_provider_integer(
        row["hit_index"], field="hit_index", row_number=row_number, minimum=0
    )
    for field in ("raw_page_digest", "raw_hit_digest", "parsed_row_digest"):
        _validate_digest(row[field], field=field, row_number=row_number)

    digest_payload: dict[str, object] = {
        "target": target,
        "accession": accession,
        "evalue": row["evalue"],
        "score": row["score"],
        "page": page,
        "hit_index": hit_index,
        "evalue_numeric": row["evalue_numeric"],
        "score_numeric": row["score_numeric"],
        "raw_page_digest": row["raw_page_digest"],
        "raw_hit_digest": row["raw_hit_digest"],
    }
    expected_row_digest = _parsed_row_digest(digest_payload)
    if row["parsed_row_digest"] != expected_row_digest:
        raise ScientificPrerequisiteError(
            "hmmer_filter_parsed_row_digest_mismatch",
            "an HMMER parsed row does not match its provider-computed digest",
            details={
                "row": row_number,
                "expected": expected_row_digest,
                "actual": row["parsed_row_digest"],
            },
        )

    return HmmerHit(
        target=target,
        accession=accession,
        evalue_numeric=row["evalue_numeric"],
        score_numeric=row["score_numeric"],
        page=page,
        hit_index=hit_index,
        raw_page_digest=row["raw_page_digest"],
        raw_hit_digest=row["raw_hit_digest"],
        parsed_row_digest=row["parsed_row_digest"],
    )


def parse_and_filter_csv(
    data: str | bytes,
    *,
    expected_contract_id: str = CONTRACT_ID,
    expected_contract_digest: str | None = None,
    expected_implementation_digest: str | None = None,
    expected_input_digest: str | None = None,
) -> ScoreFilteredAccessionsResult:
    verify_contract(
        expected_contract_id=expected_contract_id,
        expected_contract_digest=expected_contract_digest,
        expected_implementation_digest=expected_implementation_digest,
    )
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    input_digest = _sha256(raw)
    if expected_input_digest is not None:
        if not _DIGEST_PATTERN.fullmatch(expected_input_digest):
            raise ScientificPrerequisiteError(
                "hmmer_filter_bound_digest_invalid",
                "the bound HMMER input digest is not canonical sha256",
                details={"field": "input_digest", "value": expected_input_digest},
            )
        if input_digest != expected_input_digest:
            raise ScientificPrerequisiteError(
                "hmmer_filter_input_digest_mismatch",
                "the HMMER parsed-hit artifact does not match its expected byte digest",
                details={"expected": expected_input_digest, "actual": input_digest},
            )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScientificPrerequisiteError(
            "hmmer_filter_input_not_utf8",
            "the HMMER parsed-hit CSV is not valid UTF-8",
            details={"start": exc.start},
        ) from exc

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        actual_columns = tuple(reader.fieldnames or ())
        if actual_columns != INPUT_COLUMNS:
            raise ScientificPrerequisiteError(
                "hmmer_filter_input_schema_mismatch",
                "the HMMER parsed-hit CSV columns do not match the provider contract",
                details={
                    "expected": list(INPUT_COLUMNS),
                    "actual": list(actual_columns),
                },
            )
        hits: list[HmmerHit] = []
        previous_page = 0
        seen_accessions: set[str] = set()
        for offset, raw_row in enumerate(reader):
            row_number = offset + 2
            if None in raw_row or any(
                raw_row[column] is None for column in INPUT_COLUMNS
            ):
                raise ScientificPrerequisiteError(
                    "hmmer_filter_input_schema_mismatch",
                    "an HMMER parsed-hit row contains malformed CSV fields",
                    details={"row": row_number},
                )
            row = {column: str(raw_row[column]) for column in INPUT_COLUMNS}
            hit = _parse_hit(row, row_number=row_number)
            if hit.hit_index != offset or hit.page < previous_page:
                raise ScientificPrerequisiteError(
                    "hmmer_filter_provider_order_invalid",
                    "HMMER provider rows must preserve contiguous hit indexes and nondecreasing pages",
                    details={
                        "row": row_number,
                        "expected_hit_index": offset,
                        "actual_hit_index": hit.hit_index,
                        "previous_page": previous_page,
                        "actual_page": hit.page,
                    },
                )
            if hit.accession in seen_accessions:
                raise ScientificPrerequisiteError(
                    "hmmer_filter_duplicate_accession",
                    "HMMER provider rows must contain one unique row per UniProt accession",
                    details={"row": row_number, "accession": hit.accession},
                )
            previous_page = hit.page
            seen_accessions.add(hit.accession)
            hits.append(hit)
    except csv.Error as exc:
        raise ScientificPrerequisiteError(
            "hmmer_filter_csv_invalid",
            "the HMMER parsed-hit artifact is not valid CSV",
            details={"message": str(exc)},
        ) from exc

    selected = tuple(
        sorted(
            (hit for hit in hits if hit.score > _SCORE_THRESHOLD),
            key=lambda hit: hit.accession,
        )
    )
    return ScoreFilteredAccessionsResult(
        hits=selected,
        input_digest=input_digest,
        input_row_count=len(hits),
    )


def canonical_rows_to_csv(rows: Iterable[Mapping[str, str]]) -> str:
    materialized = tuple(rows)
    accessions: list[str] = []
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=list(OUTPUT_COLUMNS),
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for index, row in enumerate(materialized, start=2):
        if tuple(row) != OUTPUT_COLUMNS:
            raise ScientificPrerequisiteError(
                "hmmer_filter_output_schema_mismatch",
                "a canonical HMMER score-filter row has the wrong columns or column order",
                details={"row": index, "actual": list(row)},
            )
        accession = row["accession"]
        if _UNIPROT_ACCESSION_PATTERN.fullmatch(accession) is None:
            raise ScientificPrerequisiteError(
                "hmmer_filter_output_accession_invalid",
                "a canonical HMMER score-filter row has an invalid UniProt accession",
                details={"row": index, "accession": accession},
            )
        accessions.append(accession)
        writer.writerow(dict(row))
    if accessions != sorted(accessions) or len(accessions) != len(set(accessions)):
        raise ScientificPrerequisiteError(
            "hmmer_filter_output_order_invalid",
            "canonical HMMER score-filter rows require unique accessions in lexical order",
            details={"accessions": accessions},
        )
    return output.getvalue()


IMPLEMENTATION_DIGEST = implementation_digest()
CONTRACT_DIGEST = contract_digest(implementation_digest_value=IMPLEMENTATION_DIGEST)


__all__ = [
    "CONTRACT_DIGEST",
    "CONTRACT_ID",
    "IMPLEMENTATION_DIGEST",
    "INPUT_COLUMNS",
    "OUTPUT_COLUMNS",
    "SCORE_THRESHOLD_DISPLAY",
    "HmmerHit",
    "ScientificPrerequisiteError",
    "ScoreFilteredAccessionsResult",
    "canonical_rows_to_csv",
    "contract_digest",
    "contract_payload",
    "implementation_digest",
    "parse_and_filter_csv",
    "verify_contract",
]
