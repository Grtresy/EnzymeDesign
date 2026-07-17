from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CONTRACT_ID = "aox_motif_rule_score@1"
REFERENCE_ACCESSION = "AAB57849.1"
THRESHOLD_TENTHS = 336
THRESHOLD_DISPLAY = "33.6"

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_SEQUENCE_PATTERN = re.compile(r"^[A-Z-]+$")
_LEGACY_FIELDS = frozenset({"activity_score", "pass_rule", "seq_score"})


@dataclass(frozen=True, slots=True)
class PositiveRule:
    coordinate: int
    allowed_residues: tuple[str, ...]
    weight_tenths: int


POSITIVE_RULES = (
    PositiveRule(13, ("G",), 50),
    PositiveRule(15, ("G",), 50),
    PositiveRule(18, ("G",), 50),
    PositiveRule(98, ("F", "W", "Y"), 50),
    PositiveRule(417, ("F", "W", "Y"), 20),
    PositiveRule(566, ("F", "W", "Y"), 20),
    PositiveRule(567, ("H",), 50),
    PositiveRule(616, ("H", "N", "P"), 50),
)
PENALTY_COORDINATES = (660, 661, 662, 663)
RULE_COORDINATES = tuple(rule.coordinate for rule in POSITIVE_RULES) + PENALTY_COORDINATES
MAX_RULE_COORDINATE = max(RULE_COORDINATES)

RESIDUE_COLUMNS = tuple(f"residue_{coordinate}" for coordinate in RULE_COORDINATES)
CANONICAL_COLUMNS = (
    "sequence_id",
    "description",
    "sequence_digest",
    "aligned_sequence_digest",
    "input_digest",
    "alignment_digest",
    "alignment_width",
    "reference_accession",
    "reference_sequence_id",
    "reference_sequence_digest",
    "scoring_contract_id",
    "scoring_contract_digest",
    "scoring_implementation_digest",
    "motif_rule_score_tenths",
    "motif_rule_score",
    "passes_motif_rule",
    *RESIDUE_COLUMNS,
)
CANONICAL_FIELD_TYPES = {
    "sequence_id": "string",
    "description": "string",
    "sequence_digest": "sha256",
    "aligned_sequence_digest": "sha256",
    "input_digest": "sha256",
    "alignment_digest": "sha256",
    "alignment_width": "integer",
    "reference_accession": "string",
    "reference_sequence_id": "string",
    "reference_sequence_digest": "sha256",
    "scoring_contract_id": "string",
    "scoring_contract_digest": "sha256",
    "scoring_implementation_digest": "sha256",
    "motif_rule_score_tenths": "integer",
    "motif_rule_score": "fixed-one-decimal-string",
    "passes_motif_rule": "boolean",
    **{column: "residue-or-gap" for column in RESIDUE_COLUMNS},
}


class ScientificPrerequisiteError(ValueError):
    """A structured fail-closed scientific input or contract error."""

    error_type = "scientific_prerequisite_missing"

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = dict(details or {})
        super().__init__(f"{self.error_type}:{code}: {message}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type,
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class AlignmentRecord:
    sequence_id: str
    description: str
    aligned_sequence: str

    @property
    def sequence(self) -> str:
        return self.aligned_sequence.replace("-", "")

    @property
    def sequence_digest(self) -> str:
        return _sha256(self.sequence.encode("ascii"))

    @property
    def aligned_sequence_digest(self) -> str:
        return _sha256(self.aligned_sequence.encode("ascii"))


@dataclass(frozen=True, slots=True)
class ParsedAlignment:
    records: tuple[AlignmentRecord, ...]
    width: int
    input_digest: str
    alignment_digest: str


@dataclass(frozen=True, slots=True)
class ScoredSequence:
    sequence_id: str
    description: str
    sequence_digest: str
    aligned_sequence_digest: str
    input_digest: str
    alignment_digest: str
    alignment_width: int
    reference_sequence_id: str
    reference_sequence_digest: str
    score_tenths: int
    residues: tuple[tuple[int, str], ...]

    @property
    def score_display(self) -> str:
        return _format_tenths(self.score_tenths)

    @property
    def passes_motif_rule(self) -> bool:
        return self.score_tenths >= THRESHOLD_TENTHS

    def to_row(self) -> dict[str, object]:
        row: dict[str, object] = {
            "sequence_id": self.sequence_id,
            "description": self.description,
            "sequence_digest": self.sequence_digest,
            "aligned_sequence_digest": self.aligned_sequence_digest,
            "input_digest": self.input_digest,
            "alignment_digest": self.alignment_digest,
            "alignment_width": self.alignment_width,
            "reference_accession": REFERENCE_ACCESSION,
            "reference_sequence_id": self.reference_sequence_id,
            "reference_sequence_digest": self.reference_sequence_digest,
            "scoring_contract_id": CONTRACT_ID,
            "scoring_contract_digest": CONTRACT_DIGEST,
            "scoring_implementation_digest": IMPLEMENTATION_DIGEST,
            "motif_rule_score_tenths": self.score_tenths,
            "motif_rule_score": self.score_display,
            "passes_motif_rule": self.passes_motif_rule,
        }
        row.update({f"residue_{coordinate}": residue for coordinate, residue in self.residues})
        return row


@dataclass(frozen=True, slots=True)
class ScoringResult:
    alignment: ParsedAlignment
    reference: AlignmentRecord
    rows: tuple[ScoredSequence, ...]

    def canonical_rows(self) -> tuple[dict[str, object], ...]:
        rows = tuple(row.to_row() for row in self.rows)
        validate_canonical_rows(rows)
        return rows

    def to_csv(self) -> str:
        return canonical_rows_to_csv(self.canonical_rows())

    def metadata(self) -> dict[str, object]:
        return {
            **contract_metadata(),
            "input_digest": self.alignment.input_digest,
            "alignment_digest": self.alignment.alignment_digest,
            "alignment_width": self.alignment.width,
            "reference_sequence_id": self.reference.sequence_id,
            "reference_sequence_digest": self.reference.sequence_digest,
            "row_count": len(self.rows),
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


def _format_tenths(value: int) -> str:
    sign = "-" if value < 0 else ""
    whole, fraction = divmod(abs(value), 10)
    return f"{sign}{whole}.{fraction}"


def implementation_digest() -> str:
    return _sha256(Path(__file__).read_bytes())


def contract_payload(*, implementation_digest_value: str | None = None) -> dict[str, object]:
    source_digest = implementation_digest_value or implementation_digest()
    return {
        "contract_id": CONTRACT_ID,
        "scientific_claim": "reference-coordinate motif heuristic; not experimental activity prediction",
        "reference": {
            "accession": REFERENCE_ACCESSION,
            "coordinate_convention": "one-based ungapped reference coordinates",
            "resolution": "exact FASTA sequence identifier",
        },
        "calculation": {
            "numeric_unit": "integer tenths",
            "positive_rules": [
                {
                    "coordinate": rule.coordinate,
                    "allowed_residues": list(rule.allowed_residues),
                    "weight_tenths": rule.weight_tenths,
                }
                for rule in POSITIVE_RULES
            ],
            "non_gap_penalty": {
                "coordinates": list(PENALTY_COORDINATES),
                "weight_tenths_each": -1,
            },
            "threshold_tenths": THRESHOLD_TENTHS,
            "threshold_display": THRESHOLD_DISPLAY,
        },
        "output_schema": [
            {"name": column, "type": CANONICAL_FIELD_TYPES[column]}
            for column in CANONICAL_COLUMNS
        ],
        "implementation_digest": source_digest,
    }


def contract_digest(*, implementation_digest_value: str | None = None) -> str:
    return _sha256(
        _canonical_json_bytes(
            contract_payload(implementation_digest_value=implementation_digest_value)
        )
    )


def contract_metadata() -> dict[str, object]:
    return {
        "scoring_contract_id": CONTRACT_ID,
        "scoring_contract_digest": CONTRACT_DIGEST,
        "scoring_implementation_digest": IMPLEMENTATION_DIGEST,
        "reference_accession": REFERENCE_ACCESSION,
        "threshold_tenths": THRESHOLD_TENTHS,
        "threshold": THRESHOLD_DISPLAY,
    }


def verify_contract(
    *,
    expected_contract_id: str = CONTRACT_ID,
    expected_contract_digest: str | None = None,
    expected_implementation_digest: str | None = None,
) -> None:
    expected_contract_digest = expected_contract_digest or CONTRACT_DIGEST
    expected_implementation_digest = expected_implementation_digest or IMPLEMENTATION_DIGEST
    expected = {
        "contract_id": expected_contract_id,
        "contract_digest": expected_contract_digest,
        "implementation_digest": expected_implementation_digest,
    }
    actual = {
        "contract_id": CONTRACT_ID,
        "contract_digest": CONTRACT_DIGEST,
        "implementation_digest": IMPLEMENTATION_DIGEST,
    }
    if expected != actual:
        raise ScientificPrerequisiteError(
            "scoring_digest_drift",
            "the bound AOX motif scoring identity does not match the installed implementation",
            details={"expected": expected, "actual": actual},
        )


def parse_aligned_fasta(data: str | bytes) -> ParsedAlignment:
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScientificPrerequisiteError(
            "alignment_not_utf8",
            "the aligned FASTA input is not valid UTF-8",
            details={"start": exc.start},
        ) from exc

    parsed: list[AlignmentRecord] = []
    header: str | None = None
    fragments: list[str] = []

    def finish_record() -> None:
        nonlocal header, fragments
        if header is None:
            return
        aligned_sequence = "".join(fragments).upper()
        if not aligned_sequence:
            raise ScientificPrerequisiteError(
                "empty_alignment_sequence",
                "an aligned FASTA record has no sequence",
                details={"header": header},
            )
        if not _SEQUENCE_PATTERN.fullmatch(aligned_sequence):
            invalid = sorted(set(aligned_sequence) - set("ABCDEFGHIJKLMNOPQRSTUVWXYZ-"))
            raise ScientificPrerequisiteError(
                "invalid_alignment_residue",
                "aligned FASTA sequences may contain only ASCII letters and '-' gaps",
                details={"header": header, "invalid_characters": invalid},
            )
        parts = header.split(maxsplit=1)
        sequence_id = parts[0]
        description = parts[1] if len(parts) == 2 else ""
        parsed.append(
            AlignmentRecord(
                sequence_id=sequence_id,
                description=description.strip(),
                aligned_sequence=aligned_sequence,
            )
        )
        header = None
        fragments = []

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            finish_record()
            header = line[1:].strip()
            if not header:
                raise ScientificPrerequisiteError(
                    "empty_fasta_header",
                    "an aligned FASTA header is empty",
                    details={"line": line_number},
                )
            continue
        if header is None:
            raise ScientificPrerequisiteError(
                "sequence_before_header",
                "aligned FASTA sequence data appeared before its header",
                details={"line": line_number},
            )
        if any(character.isspace() for character in line):
            raise ScientificPrerequisiteError(
                "whitespace_in_alignment_sequence",
                "aligned FASTA sequence lines may not contain internal whitespace",
                details={"line": line_number},
            )
        fragments.append(line)
    finish_record()

    if not parsed:
        raise ScientificPrerequisiteError(
            "empty_alignment",
            "the aligned FASTA input contains no records",
        )
    widths = sorted({len(record.aligned_sequence) for record in parsed})
    if len(widths) != 1:
        raise ScientificPrerequisiteError(
            "unequal_alignment_width",
            "all aligned FASTA records must have the same width",
            details={"widths": widths},
        )

    canonical_records = [
        {
            "sequence_id": record.sequence_id,
            "description": record.description,
            "aligned_sequence": record.aligned_sequence,
        }
        for record in sorted(parsed, key=lambda item: item.sequence_id)
    ]
    width = widths[0]
    return ParsedAlignment(
        records=tuple(parsed),
        width=width,
        input_digest=_sha256(raw),
        alignment_digest=_sha256(
            _canonical_json_bytes({"width": width, "records": canonical_records})
        ),
    )


def _resolve_reference(alignment: ParsedAlignment) -> AlignmentRecord:
    matches = [
        record
        for record in alignment.records
        if record.sequence_id == REFERENCE_ACCESSION
    ]
    if not matches:
        raise ScientificPrerequisiteError(
            "reference_missing",
            "the alignment does not contain the exact coordinate reference identifier",
            details={"reference_accession": REFERENCE_ACCESSION},
        )
    if len(matches) != 1:
        raise ScientificPrerequisiteError(
            "reference_ambiguous",
            "the alignment contains more than one exact coordinate reference identifier",
            details={"reference_accession": REFERENCE_ACCESSION, "count": len(matches)},
        )
    return matches[0]


def _validate_unique_sequence_ids(alignment: ParsedAlignment) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for record in alignment.records:
        if record.sequence_id in seen:
            duplicates.add(record.sequence_id)
        seen.add(record.sequence_id)
    if duplicates:
        raise ScientificPrerequisiteError(
            "duplicate_sequence_id",
            "canonical scoring requires unique FASTA sequence identifiers",
            details={"sequence_ids": sorted(duplicates)},
        )


def _reference_column_map(reference: AlignmentRecord) -> dict[int, int]:
    columns: dict[int, int] = {}
    coordinate = 0
    for column, residue in enumerate(reference.aligned_sequence):
        if residue == "-":
            continue
        coordinate += 1
        if coordinate in RULE_COORDINATES:
            columns[coordinate] = column
    if coordinate < MAX_RULE_COORDINATE:
        raise ScientificPrerequisiteError(
            "reference_truncated",
            "the coordinate reference ends before the final required motif coordinate",
            details={
                "reference_accession": REFERENCE_ACCESSION,
                "observed_ungapped_length": coordinate,
                "required_ungapped_length": MAX_RULE_COORDINATE,
            },
        )
    missing = sorted(set(RULE_COORDINATES) - set(columns))
    if missing:
        raise ScientificPrerequisiteError(
            "reference_coordinate_unresolved",
            "one or more motif coordinates could not be mapped to alignment columns",
            details={"coordinates": missing},
        )
    return columns


def _score_record(
    record: AlignmentRecord,
    *,
    alignment: ParsedAlignment,
    reference: AlignmentRecord,
    columns: Mapping[int, int],
) -> ScoredSequence:
    observed = tuple(
        (coordinate, record.aligned_sequence[columns[coordinate]])
        for coordinate in RULE_COORDINATES
    )
    residues = dict(observed)
    score_tenths = sum(
        rule.weight_tenths
        for rule in POSITIVE_RULES
        if residues[rule.coordinate] in rule.allowed_residues
    )
    score_tenths -= sum(
        1 for coordinate in PENALTY_COORDINATES if residues[coordinate] != "-"
    )
    return ScoredSequence(
        sequence_id=record.sequence_id,
        description=record.description,
        sequence_digest=record.sequence_digest,
        aligned_sequence_digest=record.aligned_sequence_digest,
        input_digest=alignment.input_digest,
        alignment_digest=alignment.alignment_digest,
        alignment_width=alignment.width,
        reference_sequence_id=reference.sequence_id,
        reference_sequence_digest=reference.sequence_digest,
        score_tenths=score_tenths,
        residues=observed,
    )


def score_alignment(
    alignment: ParsedAlignment,
    *,
    expected_contract_id: str = CONTRACT_ID,
    expected_contract_digest: str | None = None,
    expected_implementation_digest: str | None = None,
    expected_input_digest: str | None = None,
) -> ScoringResult:
    verify_contract(
        expected_contract_id=expected_contract_id,
        expected_contract_digest=expected_contract_digest,
        expected_implementation_digest=expected_implementation_digest,
    )
    if expected_input_digest is not None and alignment.input_digest != expected_input_digest:
        raise ScientificPrerequisiteError(
            "alignment_input_digest_mismatch",
            "the aligned FASTA bytes do not match the expected input digest",
            details={
                "expected": expected_input_digest,
                "actual": alignment.input_digest,
            },
        )
    reference = _resolve_reference(alignment)
    _validate_unique_sequence_ids(alignment)
    columns = _reference_column_map(reference)
    rows = tuple(
        _score_record(
            record,
            alignment=alignment,
            reference=reference,
            columns=columns,
        )
        for record in sorted(alignment.records, key=lambda item: item.sequence_id)
    )
    return ScoringResult(alignment=alignment, reference=reference, rows=rows)


def score_aligned_fasta(
    data: str | bytes,
    *,
    expected_contract_id: str = CONTRACT_ID,
    expected_contract_digest: str | None = None,
    expected_implementation_digest: str | None = None,
    expected_input_digest: str | None = None,
) -> ScoringResult:
    verify_contract(
        expected_contract_id=expected_contract_id,
        expected_contract_digest=expected_contract_digest,
        expected_implementation_digest=expected_implementation_digest,
    )
    alignment = parse_aligned_fasta(data)
    return score_alignment(
        alignment,
        expected_contract_id=expected_contract_id,
        expected_contract_digest=expected_contract_digest,
        expected_implementation_digest=expected_implementation_digest,
        expected_input_digest=expected_input_digest,
    )


def _require_digest(row: Mapping[str, object], field: str) -> None:
    value = row[field]
    if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value):
        raise ScientificPrerequisiteError(
            "scoring_output_digest_invalid",
            "a canonical scoring output digest is malformed",
            details={"field": field},
        )


def validate_canonical_rows(rows: Sequence[Mapping[str, object]]) -> None:
    sequence_ids: list[str] = []
    required = set(CANONICAL_COLUMNS)
    shared_identity: tuple[object, ...] | None = None
    for index, row in enumerate(rows):
        legacy = sorted(_LEGACY_FIELDS.intersection(row))
        if legacy:
            raise ScientificPrerequisiteError(
                "legacy_scoring_schema",
                "legacy score fields are not valid cutover scoring evidence",
                details={"row": index, "fields": legacy},
            )
        actual = set(row)
        if actual != required:
            raise ScientificPrerequisiteError(
                "scoring_output_schema_mismatch",
                "a canonical scoring row has missing or unexpected fields",
                details={
                    "row": index,
                    "missing": sorted(required - actual),
                    "unexpected": sorted(actual - required),
                },
            )

        sequence_id = row["sequence_id"]
        if not isinstance(sequence_id, str) or not sequence_id:
            raise ScientificPrerequisiteError(
                "scoring_output_sequence_id_invalid",
                "a canonical scoring row requires a non-empty sequence identifier",
                details={"row": index},
            )
        sequence_ids.append(sequence_id)
        if not isinstance(row["description"], str):
            raise ScientificPrerequisiteError(
                "scoring_output_description_invalid",
                "a canonical scoring row description must be a string",
                details={"row": index},
            )

        if row["scoring_contract_id"] != CONTRACT_ID:
            raise ScientificPrerequisiteError(
                "scoring_output_contract_mismatch",
                "a canonical scoring row has the wrong contract id",
                details={"row": index},
            )
        if row["scoring_contract_digest"] != CONTRACT_DIGEST:
            raise ScientificPrerequisiteError(
                "scoring_output_contract_mismatch",
                "a canonical scoring row has the wrong contract digest",
                details={"row": index},
            )
        if row["scoring_implementation_digest"] != IMPLEMENTATION_DIGEST:
            raise ScientificPrerequisiteError(
                "scoring_output_implementation_mismatch",
                "a canonical scoring row has the wrong implementation digest",
                details={"row": index},
            )
        if row["reference_accession"] != REFERENCE_ACCESSION:
            raise ScientificPrerequisiteError(
                "scoring_output_reference_mismatch",
                "a canonical scoring row has the wrong reference accession",
                details={"row": index},
            )
        if row["reference_sequence_id"] != REFERENCE_ACCESSION:
            raise ScientificPrerequisiteError(
                "scoring_output_reference_mismatch",
                "a canonical scoring row was not mapped against the exact reference id",
                details={"row": index},
            )

        for field in (
            "sequence_digest",
            "aligned_sequence_digest",
            "input_digest",
            "alignment_digest",
            "reference_sequence_digest",
            "scoring_contract_digest",
            "scoring_implementation_digest",
        ):
            _require_digest(row, field)

        row_identity = (
            row["input_digest"],
            row["alignment_digest"],
            row["alignment_width"],
            row["reference_sequence_id"],
            row["reference_sequence_digest"],
            row["scoring_contract_id"],
            row["scoring_contract_digest"],
            row["scoring_implementation_digest"],
        )
        if shared_identity is None:
            shared_identity = row_identity
        elif row_identity != shared_identity:
            raise ScientificPrerequisiteError(
                "scoring_output_identity_mismatch",
                "canonical scoring rows must share one alignment and scoring identity",
                details={"row": index},
            )

        score_tenths = row["motif_rule_score_tenths"]
        if isinstance(score_tenths, bool) or not isinstance(score_tenths, int):
            raise ScientificPrerequisiteError(
                "scoring_output_score_invalid",
                "the canonical motif score must be an integer number of tenths",
                details={"row": index},
            )
        if row["motif_rule_score"] != _format_tenths(score_tenths):
            raise ScientificPrerequisiteError(
                "scoring_output_score_invalid",
                "the presented motif score does not match the exact integer score",
                details={"row": index},
            )
        if row["passes_motif_rule"] is not (score_tenths >= THRESHOLD_TENTHS):
            raise ScientificPrerequisiteError(
                "scoring_output_pass_invalid",
                "the pass decision does not match the exact integer threshold",
                details={"row": index},
            )

        residues: dict[int, str] = {}
        for coordinate in RULE_COORDINATES:
            residue = row[f"residue_{coordinate}"]
            if (
                not isinstance(residue, str)
                or len(residue) != 1
                or not _SEQUENCE_PATTERN.fullmatch(residue)
            ):
                raise ScientificPrerequisiteError(
                    "scoring_output_residue_invalid",
                    "a per-rule residue observation is invalid",
                    details={"row": index, "coordinate": coordinate},
                )
            residues[coordinate] = residue
        recomputed = sum(
            rule.weight_tenths
            for rule in POSITIVE_RULES
            if residues[rule.coordinate] in rule.allowed_residues
        )
        recomputed -= sum(
            1 for coordinate in PENALTY_COORDINATES if residues[coordinate] != "-"
        )
        if recomputed != score_tenths:
            raise ScientificPrerequisiteError(
                "scoring_output_recalculation_mismatch",
                "the canonical motif score does not match its residue observations",
                details={"row": index, "expected": recomputed, "actual": score_tenths},
            )

        width = row["alignment_width"]
        if isinstance(width, bool) or not isinstance(width, int) or width < MAX_RULE_COORDINATE:
            raise ScientificPrerequisiteError(
                "scoring_output_alignment_width_invalid",
                "the canonical scoring row has an invalid alignment width",
                details={"row": index},
            )

    if sequence_ids != sorted(sequence_ids) or len(sequence_ids) != len(set(sequence_ids)):
        raise ScientificPrerequisiteError(
            "scoring_output_order_invalid",
            "canonical scoring rows must have unique sequence ids in lexical order",
            details={"sequence_ids": sequence_ids},
        )


def canonical_rows_to_csv(rows: Sequence[Mapping[str, object]]) -> str:
    validate_canonical_rows(rows)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=list(CANONICAL_COLUMNS),
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        serialized = dict(row)
        serialized["passes_motif_rule"] = (
            "true" if row["passes_motif_rule"] else "false"
        )
        writer.writerow(serialized)
    return output.getvalue()


IMPLEMENTATION_DIGEST = implementation_digest()
CONTRACT_DIGEST = contract_digest(implementation_digest_value=IMPLEMENTATION_DIGEST)


__all__ = [
    "CANONICAL_COLUMNS",
    "CANONICAL_FIELD_TYPES",
    "CONTRACT_DIGEST",
    "CONTRACT_ID",
    "IMPLEMENTATION_DIGEST",
    "MAX_RULE_COORDINATE",
    "PENALTY_COORDINATES",
    "POSITIVE_RULES",
    "REFERENCE_ACCESSION",
    "RESIDUE_COLUMNS",
    "RULE_COORDINATES",
    "ScientificPrerequisiteError",
    "ScoredSequence",
    "ScoringResult",
    "THRESHOLD_DISPLAY",
    "THRESHOLD_TENTHS",
    "canonical_rows_to_csv",
    "contract_digest",
    "contract_metadata",
    "contract_payload",
    "implementation_digest",
    "parse_aligned_fasta",
    "score_aligned_fasta",
    "score_alignment",
    "validate_canonical_rows",
    "verify_contract",
]
