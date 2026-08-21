from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import aox_motif
from .aox_motif import ScientificPrerequisiteError


CALCULATION_ID = "aox_motif_candidate_filter@1"
RESULT_SCHEMA_ID = "aox_motif_candidate_filter_result@1"
SERIALIZER_ID = "aox_motif_candidate_fasta_serializer@1"
REFERENCE_ACCESSION = aox_motif.REFERENCE_ACCESSION

_SEQUENCE_PATTERN = re.compile(r"^[ACDEFGHIKLMNPQRSTVWYBXZJUO]+$")
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_CALCULATION_RECEIPT_KEYS = frozenset(
    {
        "schema_id",
        "calculation_id",
        "calculation_contract_digest",
        "calculation_implementation_digest",
        "serializer_id",
        "target_input_digest",
        "scoring_input_digest",
        "target_count",
        "candidate_count",
        "candidate_membership_digest",
        "output_digest",
        "empty_result_reason",
    }
)


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class TargetSequence:
    sequence_id: str
    description: str
    sequence: str

    @property
    def sequence_digest(self) -> str:
        return _sha256(self.sequence.encode("ascii"))

    def to_fasta(self) -> str:
        header = self.sequence_id
        if self.description:
            header = f"{header} {self.description}"
        return f">{header}\n{self.sequence}\n"


@dataclass(frozen=True, slots=True)
class CandidateFilterResult:
    target_input_digest: str
    scoring_input_digest: str
    targets: tuple[TargetSequence, ...]
    candidates: tuple[TargetSequence, ...]

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def empty_result_reason(self) -> str | None:
        if self.candidates:
            return None
        return "no_candidates_after_motif_filter"

    def to_fasta(self) -> str:
        return "".join(record.to_fasta() for record in self.candidates)

    def calculation_receipt(self) -> dict[str, object]:
        output = self.to_fasta().encode("ascii")
        members = [
            {
                "sequence_id": record.sequence_id,
                "sequence_digest": record.sequence_digest,
            }
            for record in self.candidates
        ]
        return validate_calculation_receipt(
            {
                "schema_id": RESULT_SCHEMA_ID,
                "calculation_id": CALCULATION_ID,
                "calculation_contract_digest": CONTRACT_DIGEST,
                "calculation_implementation_digest": IMPLEMENTATION_DIGEST,
                "serializer_id": SERIALIZER_ID,
                "target_input_digest": self.target_input_digest,
                "scoring_input_digest": self.scoring_input_digest,
                "target_count": len(self.targets),
                "candidate_count": len(self.candidates),
                "candidate_membership_digest": _sha256(
                    _canonical_json_bytes(members)
                ),
                "output_digest": _sha256(output),
                "empty_result_reason": self.empty_result_reason,
            }
        )

    def metadata(self) -> dict[str, object]:
        return dict(self.calculation_receipt())


def _parse_target_fasta(data: str | bytes) -> tuple[TargetSequence, ...]:
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    if b"\r" in raw:
        raise ScientificPrerequisiteError(
            "candidate_target_fasta_line_endings_invalid",
            "candidate filtering requires LF-only canonical target FASTA",
        )
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ScientificPrerequisiteError(
            "candidate_target_fasta_not_ascii",
            "candidate filtering requires ASCII target FASTA",
            details={"start": exc.start},
        ) from exc
    if not text:
        return ()
    if not text.endswith("\n"):
        raise ScientificPrerequisiteError(
            "candidate_target_fasta_not_canonical",
            "canonical target FASTA must end with one LF",
        )

    records: list[TargetSequence] = []
    header: str | None = None
    fragments: list[str] = []

    def finish() -> None:
        nonlocal header, fragments
        if header is None:
            return
        sequence = "".join(fragments)
        if not sequence or _SEQUENCE_PATTERN.fullmatch(sequence) is None:
            raise ScientificPrerequisiteError(
                "candidate_target_sequence_invalid",
                "target FASTA contains an empty or noncanonical protein sequence",
                details={"sequence_id": header.split(maxsplit=1)[0]},
            )
        parts = header.split(maxsplit=1)
        records.append(
            TargetSequence(
                sequence_id=parts[0],
                description="" if len(parts) == 1 else parts[1],
                sequence=sequence,
            )
        )
        header = None
        fragments = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise ScientificPrerequisiteError(
                "candidate_target_fasta_blank_line",
                "canonical target FASTA does not permit blank lines",
                details={"line": line_number},
            )
        if line.startswith(">"):
            finish()
            header = line[1:]
            if not header or header != header.strip():
                raise ScientificPrerequisiteError(
                    "candidate_target_header_invalid",
                    "target FASTA requires a non-empty canonical header",
                    details={"line": line_number},
                )
            continue
        if header is None or line != line.strip() or any(
            character.isspace() for character in line
        ):
            raise ScientificPrerequisiteError(
                "candidate_target_fasta_structure_invalid",
                "target FASTA sequence lines must follow a header without whitespace",
                details={"line": line_number},
            )
        fragments.append(line)
    finish()

    ids = [record.sequence_id for record in records]
    if (
        ids != sorted(ids)
        or len(ids) != len(set(ids))
        or REFERENCE_ACCESSION in ids
    ):
        raise ScientificPrerequisiteError(
            "candidate_target_identity_invalid",
            "target FASTA requires unique lexical non-reference sequence ids",
            details={"sequence_ids": ids[:32], "sequence_count": len(ids)},
        )
    return tuple(records)


def _parse_scoring_csv(data: str | bytes) -> tuple[dict[str, object], ...]:
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScientificPrerequisiteError(
            "candidate_scoring_csv_not_utf8",
            "candidate filtering requires UTF-8 canonical scoring CSV",
            details={"start": exc.start},
        ) from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != aox_motif.CANONICAL_COLUMNS:
        raise ScientificPrerequisiteError(
            "candidate_scoring_schema_mismatch",
            "candidate filtering accepts only the canonical motif scoring columns",
            details={"actual": list(reader.fieldnames or ())},
        )
    rows: list[dict[str, object]] = []
    for row_number, raw_row in enumerate(reader, start=2):
        if None in raw_row or any(value is None for value in raw_row.values()):
            raise ScientificPrerequisiteError(
                "candidate_scoring_schema_mismatch",
                "candidate scoring CSV contains a short or extra-field row",
                details={"row": row_number},
            )
        row: dict[str, object] = dict(raw_row)
        for field in ("alignment_width", "motif_rule_score_tenths"):
            value = str(row[field])
            try:
                parsed = int(value)
            except ValueError as exc:
                raise ScientificPrerequisiteError(
                    "candidate_scoring_numeric_invalid",
                    "candidate scoring integer field is malformed",
                    details={"row": row_number, "field": field},
                ) from exc
            if str(parsed) != value:
                raise ScientificPrerequisiteError(
                    "candidate_scoring_numeric_invalid",
                    "candidate scoring integer field is not canonical",
                    details={"row": row_number, "field": field},
                )
            row[field] = parsed
        decision = row["passes_motif_rule"]
        if decision == "true":
            row["passes_motif_rule"] = True
        elif decision == "false":
            row["passes_motif_rule"] = False
        else:
            raise ScientificPrerequisiteError(
                "candidate_scoring_boolean_invalid",
                "passes_motif_rule must be exactly true or false",
                details={"row": row_number},
            )
        rows.append(row)
    aox_motif.validate_canonical_rows(rows)
    if aox_motif.canonical_rows_to_csv(rows) != text:
        raise ScientificPrerequisiteError(
            "candidate_scoring_serializer_mismatch",
            "candidate filtering requires bytes from the canonical scoring serializer",
        )
    return tuple(rows)


def filter_motif_candidates(
    target_fasta: str | bytes,
    scoring_csv: str | bytes,
    *,
    expected_calculation_id: str = CALCULATION_ID,
    expected_contract_digest: str | None = None,
    expected_implementation_digest: str | None = None,
) -> CandidateFilterResult:
    verify_contract(
        expected_calculation_id=expected_calculation_id,
        expected_contract_digest=expected_contract_digest,
        expected_implementation_digest=expected_implementation_digest,
    )
    target_bytes = (
        target_fasta.encode("utf-8")
        if isinstance(target_fasta, str)
        else bytes(target_fasta)
    )
    scoring_bytes = (
        scoring_csv.encode("utf-8")
        if isinstance(scoring_csv, str)
        else bytes(scoring_csv)
    )
    targets = _parse_target_fasta(target_bytes)
    rows = _parse_scoring_csv(scoring_bytes)
    rows_by_id = {str(row["sequence_id"]): row for row in rows}
    target_ids = {record.sequence_id for record in targets}
    expected_score_ids = target_ids | {REFERENCE_ACCESSION}
    if set(rows_by_id) != expected_score_ids:
        raise ScientificPrerequisiteError(
            "candidate_scoring_target_membership_mismatch",
            "motif scoring rows must equal the target ids plus the coordinate reference",
            details={
                "missing": sorted(expected_score_ids - set(rows_by_id))[:32],
                "unexpected": sorted(set(rows_by_id) - expected_score_ids)[:32],
            },
        )
    for target in targets:
        row = rows_by_id[target.sequence_id]
        if row["sequence_digest"] != target.sequence_digest:
            raise ScientificPrerequisiteError(
                "candidate_scoring_sequence_digest_mismatch",
                "a motif scoring row does not bind the exact target sequence",
                details={"sequence_id": target.sequence_id},
            )
    candidates = tuple(
        target
        for target in targets
        if rows_by_id[target.sequence_id]["passes_motif_rule"] is True
    )
    return CandidateFilterResult(
        target_input_digest=_sha256(target_bytes),
        scoring_input_digest=_sha256(scoring_bytes),
        targets=targets,
        candidates=candidates,
    )


def implementation_digest() -> str:
    return _sha256(Path(__file__).read_bytes())


def contract_payload(
    *, implementation_digest_value: str | None = None
) -> dict[str, object]:
    return {
        "calculation_id": CALCULATION_ID,
        "input_scoring_contract_id": aox_motif.CONTRACT_ID,
        "input_scoring_contract_digest": aox_motif.CONTRACT_DIGEST,
        "reference_accession": REFERENCE_ACCESSION,
        "selection_field": "passes_motif_rule",
        "score_field": "motif_rule_score_tenths",
        "target_membership": "exact_scoring_rows_minus_coordinate_reference",
        "serializer_id": SERIALIZER_ID,
        "result_schema_id": RESULT_SCHEMA_ID,
        "implementation_digest": (
            implementation_digest_value or implementation_digest()
        ),
    }


def contract_digest(*, implementation_digest_value: str | None = None) -> str:
    return _sha256(
        _canonical_json_bytes(
            contract_payload(
                implementation_digest_value=implementation_digest_value
            )
        )
    )


def verify_contract(
    *,
    expected_calculation_id: str = CALCULATION_ID,
    expected_contract_digest: str | None = None,
    expected_implementation_digest: str | None = None,
) -> None:
    expected = {
        "calculation_id": expected_calculation_id,
        "contract_digest": expected_contract_digest or CONTRACT_DIGEST,
        "implementation_digest": (
            expected_implementation_digest or IMPLEMENTATION_DIGEST
        ),
    }
    actual = {
        "calculation_id": CALCULATION_ID,
        "contract_digest": CONTRACT_DIGEST,
        "implementation_digest": IMPLEMENTATION_DIGEST,
    }
    if expected != actual:
        raise ScientificPrerequisiteError(
            "candidate_filter_digest_drift",
            "candidate filtering identity does not match the installed implementation",
            details={"expected": expected, "actual": actual},
        )


IMPLEMENTATION_DIGEST = implementation_digest()
CONTRACT_DIGEST = contract_digest(
    implementation_digest_value=IMPLEMENTATION_DIGEST
)


def validate_calculation_receipt(
    receipt: dict[str, object],
) -> dict[str, object]:
    normalized = dict(receipt)
    target_count = normalized.get("target_count")
    candidate_count = normalized.get("candidate_count")
    expected_empty_reason = (
        "no_candidates_after_motif_filter"
        if candidate_count == 0
        else None
    )
    if (
        set(normalized) != _CALCULATION_RECEIPT_KEYS
        or normalized.get("schema_id") != RESULT_SCHEMA_ID
        or normalized.get("calculation_id") != CALCULATION_ID
        or normalized.get("calculation_contract_digest") != CONTRACT_DIGEST
        or normalized.get("calculation_implementation_digest")
        != IMPLEMENTATION_DIGEST
        or normalized.get("serializer_id") != SERIALIZER_ID
        or isinstance(target_count, bool)
        or not isinstance(target_count, int)
        or target_count < 0
        or isinstance(candidate_count, bool)
        or not isinstance(candidate_count, int)
        or candidate_count < 0
        or candidate_count > target_count
        or normalized.get("empty_result_reason") != expected_empty_reason
        or any(
            _DIGEST_PATTERN.fullmatch(str(normalized.get(field) or ""))
            is None
            for field in (
                "target_input_digest",
                "scoring_input_digest",
                "candidate_membership_digest",
                "output_digest",
            )
        )
    ):
        raise ScientificPrerequisiteError(
            "candidate_calculation_receipt_invalid",
            "candidate receipt does not match the exact installed calculation",
        )
    return normalized


__all__ = [
    "CALCULATION_ID",
    "CONTRACT_DIGEST",
    "CandidateFilterResult",
    "IMPLEMENTATION_DIGEST",
    "RESULT_SCHEMA_ID",
    "SERIALIZER_ID",
    "TargetSequence",
    "contract_digest",
    "contract_payload",
    "filter_motif_candidates",
    "implementation_digest",
    "validate_calculation_receipt",
    "verify_contract",
]
