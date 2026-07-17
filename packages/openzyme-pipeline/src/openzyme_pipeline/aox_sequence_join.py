from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import aox_hmmer
from .aox_motif import ScientificPrerequisiteError


CONTRACT_ID = "aox_sequence_length_join@1"
LENGTH_MIN = 650
LENGTH_MAX = 700
HITS_OUTPUT_NAME = "hits_len650_700_200.csv"
FASTA_OUTPUT_NAME = "target.fasta"
OUTPUT_COLUMNS = (
    "target",
    "uniprot_accession",
    "hmm_score",
    "evalue",
    "length",
    "sequence",
)

_UNIPROT_IDENTITY_CONTRACT_ID = "uniprot_primary_sequence_identity@1"
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_UNIPROT_ACCESSION_SOURCE = (
    r"(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|"
    r"[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}){1,2}[0-9])(?:-[0-9]+)?"
)
_UNIPROT_ACCESSION_PATTERN = re.compile(rf"^{_UNIPROT_ACCESSION_SOURCE}$")
_UNIPROT_RELEASE_PATTERN = re.compile(r"^[0-9]{4}_[0-9]{2}$")
_TAGGED_FASTA_ID_PATTERN = re.compile(
    rf"^(?P<database>sp|tr)\|(?P<accession>{_UNIPROT_ACCESSION_SOURCE})\|"
    r"(?P<entry>[^|\s]+)$"
)
_SEQUENCE_PATTERN = re.compile(r"^[ACDEFGHIKLMNPQRSTVWYBXZJUO]+$")
_REQUIRED_UNIPROT_FIELDS = frozenset(
    {"accession", "id", "sequence", "reviewed", "sequence_version", "version"}
)
_UNIPROT_METADATA_KEYS = frozenset(
    {
        "provider",
        "database",
        "fields",
        "batch_size",
        "identity_contract_id",
        "requested_accessions",
        "records",
        "warnings",
        "retrieved_at",
        "uniprot_release",
        "uniprot_release_date",
        "aggregate_response_digest",
        "source_sequence_identity_count",
        "sequence_mismatch_resolution_count",
        "api_version",
    }
)
_UNIPROT_RECORD_KEYS = frozenset(
    {
        "requested_accession",
        "primary_accession",
        "uniprot_identifier",
        "reviewed",
        "entry_type",
        "uniprot_release",
        "uniprot_release_date",
        "retrieved_at",
        "entry_version",
        "sequence_version",
        "sequence_length",
        "sequence_digest",
        "response_digest",
        "record_digest",
        "mapping_annotations",
        "provider_metadata",
    }
)


@dataclass(frozen=True, slots=True)
class ScoreFilteredHit:
    accession: str
    target: str
    evalue: str
    hmm_score: str
    raw_page_digest: str
    raw_hit_digest: str
    parsed_row_digest: str


@dataclass(frozen=True, slots=True)
class FastaSequence:
    primary_accession: str
    sequence: str
    database_tag: str | None
    description: str

    @property
    def sequence_digest(self) -> str:
        return _sha256(self.sequence.encode("ascii"))


@dataclass(frozen=True, slots=True)
class UniProtIdentity:
    requested_accession: str
    primary_accession: str
    sequence: str
    sequence_digest: str
    reviewed: bool
    entry_version: int
    sequence_version: int
    response_digest: str
    record_digest: str


@dataclass(frozen=True, slots=True)
class ParsedUniProtEvidence:
    records: tuple[UniProtIdentity, ...]
    release: str
    release_date: str | None
    retrieved_at: str
    aggregate_response_digest: str
    api_version: str
    warning_count: int
    source_sequence_identity_count: int
    sequence_mismatch_resolution_count: int


@dataclass(frozen=True, slots=True)
class JoinedHit:
    target: str
    uniprot_accession: str
    primary_accession: str
    hmm_score: str
    evalue: str
    sequence: str
    sequence_digest: str

    def to_row(self) -> dict[str, str]:
        return {
            "target": self.target,
            "uniprot_accession": self.uniprot_accession,
            "hmm_score": self.hmm_score,
            "evalue": self.evalue,
            "length": str(len(self.sequence)),
            "sequence": self.sequence,
        }


@dataclass(frozen=True, slots=True)
class SequenceLengthJoinResult:
    input_hits: tuple[ScoreFilteredHit, ...]
    uniprot_records: tuple[UniProtIdentity, ...]
    hits: tuple[JoinedHit, ...]
    score_filtered_csv_digest: str
    uniprot_fasta_digest: str
    uniprot_metadata_digest: str
    uniprot_release: str
    uniprot_release_date: str | None
    retrieved_at: str
    aggregate_response_digest: str
    api_version: str
    warning_count: int
    source_sequence_identity_count: int
    sequence_mismatch_resolution_count: int

    def hits_csv(self) -> str:
        return canonical_hits_to_csv(hit.to_row() for hit in self.hits)

    def target_fasta(self) -> str:
        return "".join(
            f">{hit.uniprot_accession}\n{hit.sequence}\n" for hit in self.hits
        )

    def metadata(self) -> dict[str, object]:
        hits_bytes = self.hits_csv().encode("utf-8")
        fasta_bytes = self.target_fasta().encode("utf-8")
        return {
            "contract_id": CONTRACT_ID,
            "contract_digest": CONTRACT_DIGEST,
            "implementation_digest": IMPLEMENTATION_DIGEST,
            "upstream_hmmer_contract": {
                "contract_id": aox_hmmer.CONTRACT_ID,
                "contract_digest": aox_hmmer.CONTRACT_DIGEST,
                "implementation_digest": aox_hmmer.IMPLEMENTATION_DIGEST,
            },
            "input_digests": {
                "hmmer_score_filtered_accessions_csv": (
                    self.score_filtered_csv_digest
                ),
                "uniprot_sequences_fasta": self.uniprot_fasta_digest,
                "uniprot_metadata_json": self.uniprot_metadata_digest,
            },
            "output_digests": {
                HITS_OUTPUT_NAME: _sha256(hits_bytes),
                FASTA_OUTPUT_NAME: _sha256(fasta_bytes),
            },
            "length_filter": {
                "minimum": LENGTH_MIN,
                "maximum": LENGTH_MAX,
                "minimum_inclusive": True,
                "maximum_inclusive": True,
            },
            "counts": {
                "input_hit_count": len(self.input_hits),
                "uniprot_record_count": len(self.uniprot_records),
                "output_hit_count": len(self.hits),
                "length_rejected_count": len(self.input_hits) - len(self.hits),
            },
            "uniprot_provider": {
                "identity_contract_id": _UNIPROT_IDENTITY_CONTRACT_ID,
                "release": self.uniprot_release,
                "release_date": self.uniprot_release_date,
                "retrieved_at": self.retrieved_at,
                "aggregate_response_digest": self.aggregate_response_digest,
                "api_version": self.api_version,
                "warning_count": self.warning_count,
                "source_sequence_identity_count": (
                    self.source_sequence_identity_count
                ),
                "sequence_mismatch_resolution_count": (
                    self.sequence_mismatch_resolution_count
                ),
            },
            "identity_mappings": [
                {
                    "requested_accession": record.requested_accession,
                    "primary_accession": record.primary_accession,
                    "identity_replaced": False,
                    "sequence_digest": record.sequence_digest,
                    "reviewed": record.reviewed,
                    "entry_version": record.entry_version,
                    "sequence_version": record.sequence_version,
                    "response_digest": record.response_digest,
                    "record_digest": record.record_digest,
                }
                for record in self.uniprot_records
            ],
            "healthy_empty": not self.hits,
        }

    def metadata_json(self) -> str:
        return _canonical_json_bytes(self.metadata()).decode("utf-8") + "\n"


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
            "deterministic identity-preserving join of HMMER-selected accessions "
            "to exact UniProt sequence bytes, followed only by an inclusive "
            "protein-length filter; not an activity prediction"
        ),
        "upstream_hmmer_contract": {
            "contract_id": aox_hmmer.CONTRACT_ID,
            "contract_digest": aox_hmmer.CONTRACT_DIGEST,
            "implementation_digest": aox_hmmer.IMPLEMENTATION_DIGEST,
            "columns": list(aox_hmmer.OUTPUT_COLUMNS),
        },
        "uniprot_provider_contract": {
            "identity_contract_id": _UNIPROT_IDENTITY_CONTRACT_ID,
            "required_artifacts": [
                "provider_parsed/sequences.fasta",
                "provider_parsed/metadata.json",
            ],
            "accepted_fasta_headers": [
                "sp|ACCESSION|ENTRY",
                "tr|ACCESSION|ENTRY",
                "ACCESSION",
            ],
            "mapping_semantics": (
                "requested HMMER accession remains the candidate identity; "
                "resolved primary accession is an append-only annotation"
            ),
            "required_metadata": [
                "release",
                "retrieved_at",
                "requested_to_primary_mapping",
                "sequence_digest",
                "response_digest",
                "record_digest",
            ],
        },
        "validation": {
            "exact_hmmer_csv_schema_and_serialization": True,
            "exact_uniprot_metadata_schema_and_serialization": True,
            "accession_set_equality": True,
            "missing_duplicate_or_extra_sequence": "fail_closed",
            "sequence_alphabet": "ACDEFGHIKLMNPQRSTVWYBXZJUO",
            "sequence_identity_replacement": "forbidden",
        },
        "filter": {
            "field": "length_of_exact_uniprot_sequence_bytes",
            "minimum": LENGTH_MIN,
            "maximum": LENGTH_MAX,
            "minimum_inclusive": True,
            "maximum_inclusive": True,
        },
        "outputs": {
            HITS_OUTPUT_NAME: {
                "columns": list(OUTPUT_COLUMNS),
                "ordering": "uniprot_accession_lexical_ascending",
                "healthy_empty": "header_only_csv",
            },
            FASTA_OUTPUT_NAME: {
                "header_identity": "requested_hmmer_uniprot_accession",
                "ordering": "uniprot_accession_lexical_ascending",
                "healthy_empty": "zero_bytes",
            },
        },
        "implementation_digest": source_digest,
    }


def contract_digest(*, implementation_digest_value: str | None = None) -> str:
    return _sha256(
        _canonical_json_bytes(
            contract_payload(implementation_digest_value=implementation_digest_value)
        )
    )


def _validate_digest(value: str, *, field: str, code: str) -> None:
    if _DIGEST_PATTERN.fullmatch(value) is None:
        raise ScientificPrerequisiteError(
            code,
            "an AOX sequence-join digest is not canonical sha256",
            details={"field": field, "value": value},
        )


def verify_contract(
    *,
    expected_contract_id: str = CONTRACT_ID,
    expected_contract_digest: str | None = None,
    expected_implementation_digest: str | None = None,
    expected_hmmer_contract_id: str = aox_hmmer.CONTRACT_ID,
    expected_hmmer_contract_digest: str | None = None,
    expected_hmmer_implementation_digest: str | None = None,
) -> None:
    expected = {
        "contract_id": expected_contract_id,
        "contract_digest": expected_contract_digest or CONTRACT_DIGEST,
        "implementation_digest": expected_implementation_digest
        or IMPLEMENTATION_DIGEST,
        "hmmer_contract_id": expected_hmmer_contract_id,
        "hmmer_contract_digest": expected_hmmer_contract_digest
        or aox_hmmer.CONTRACT_DIGEST,
        "hmmer_implementation_digest": expected_hmmer_implementation_digest
        or aox_hmmer.IMPLEMENTATION_DIGEST,
    }
    actual = {
        "contract_id": CONTRACT_ID,
        "contract_digest": CONTRACT_DIGEST,
        "implementation_digest": IMPLEMENTATION_DIGEST,
        "hmmer_contract_id": aox_hmmer.CONTRACT_ID,
        "hmmer_contract_digest": aox_hmmer.CONTRACT_DIGEST,
        "hmmer_implementation_digest": aox_hmmer.IMPLEMENTATION_DIGEST,
    }
    for field, value in expected.items():
        if field.endswith("digest"):
            _validate_digest(
                str(value),
                field=field,
                code="sequence_join_bound_digest_invalid",
            )
    if expected != actual:
        raise ScientificPrerequisiteError(
            "sequence_join_contract_digest_drift",
            "the bound AOX sequence-join identity does not match the installed contracts",
            details={"expected": expected, "actual": actual},
        )
    aox_hmmer.verify_contract(
        expected_contract_id=expected_hmmer_contract_id,
        expected_contract_digest=expected["hmmer_contract_digest"],
        expected_implementation_digest=expected["hmmer_implementation_digest"],
    )


def _bytes_and_digest(
    data: str | bytes,
    *,
    field: str,
    expected_digest: str | None,
) -> tuple[bytes, str]:
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    digest = _sha256(raw)
    if expected_digest is not None:
        _validate_digest(
            expected_digest,
            field=field,
            code="sequence_join_bound_digest_invalid",
        )
        if digest != expected_digest:
            raise ScientificPrerequisiteError(
                "sequence_join_input_digest_mismatch",
                "an AOX sequence-join input does not match its bound byte digest",
                details={"field": field, "expected": expected_digest, "actual": digest},
            )
    return raw, digest


def _decode_utf8(raw: bytes, *, field: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScientificPrerequisiteError(
            "sequence_join_input_not_utf8",
            "an AOX sequence-join input is not valid UTF-8",
            details={"field": field, "start": exc.start},
        ) from exc


def _canonical_decimal(
    value: str,
    *,
    field: str,
    row_number: int,
    nonnegative: bool,
) -> Decimal:
    if not value or value != value.strip():
        raise ScientificPrerequisiteError(
            "sequence_join_hmmer_numeric_invalid",
            "a score-filter numeric value is empty or has surrounding whitespace",
            details={"field": field, "row": row_number},
        )
    try:
        numeric = Decimal(value)
    except InvalidOperation as exc:
        raise ScientificPrerequisiteError(
            "sequence_join_hmmer_numeric_invalid",
            "a score-filter numeric value is not a decimal",
            details={"field": field, "row": row_number},
        ) from exc
    canonical = str(numeric.normalize()) if numeric else "0"
    if not numeric.is_finite() or (nonnegative and numeric < 0) or value != canonical:
        raise ScientificPrerequisiteError(
            "sequence_join_hmmer_numeric_invalid",
            "a score-filter numeric value is outside its canonical finite domain",
            details={"field": field, "row": row_number, "value": value},
        )
    return numeric


def _parse_score_filtered_csv(raw: bytes) -> tuple[ScoreFilteredHit, ...]:
    text = _decode_utf8(raw, field="hmmer_score_filtered_accessions_csv")
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        columns = tuple(reader.fieldnames or ())
        if columns != aox_hmmer.OUTPUT_COLUMNS:
            raise ScientificPrerequisiteError(
                "sequence_join_hmmer_schema_mismatch",
                "the score-filter CSV does not match hmmer_score_filtered_accessions@1",
                details={
                    "expected": list(aox_hmmer.OUTPUT_COLUMNS),
                    "actual": list(columns),
                },
            )
        rows: list[dict[str, str]] = []
        hits: list[ScoreFilteredHit] = []
        previous_accession: str | None = None
        threshold = Decimal(aox_hmmer.SCORE_THRESHOLD_DISPLAY)
        for offset, raw_row in enumerate(reader):
            row_number = offset + 2
            if None in raw_row or any(
                raw_row[column] is None for column in aox_hmmer.OUTPUT_COLUMNS
            ):
                raise ScientificPrerequisiteError(
                    "sequence_join_hmmer_schema_mismatch",
                    "a score-filter row contains malformed CSV fields",
                    details={"row": row_number},
                )
            row = {
                column: str(raw_row[column]) for column in aox_hmmer.OUTPUT_COLUMNS
            }
            accession = row["accession"]
            if _UNIPROT_ACCESSION_PATTERN.fullmatch(accession) is None:
                raise ScientificPrerequisiteError(
                    "sequence_join_hmmer_accession_invalid",
                    "a score-filter row has an invalid UniProt accession",
                    details={"row": row_number, "accession": accession},
                )
            if previous_accession is not None and accession <= previous_accession:
                raise ScientificPrerequisiteError(
                    "sequence_join_hmmer_order_invalid",
                    "score-filter accessions must be unique and lexically ordered",
                    details={"row": row_number, "accession": accession},
                )
            target = row["target"]
            if (
                not target
                or target != target.strip()
                or any(ord(character) < 32 or ord(character) > 126 for character in target)
            ):
                raise ScientificPrerequisiteError(
                    "sequence_join_hmmer_target_invalid",
                    "a score-filter target is not canonical printable ASCII",
                    details={"row": row_number},
                )
            evalue = _canonical_decimal(
                row["evalue_numeric"],
                field="evalue_numeric",
                row_number=row_number,
                nonnegative=True,
            )
            score = _canonical_decimal(
                row["score_numeric"],
                field="score_numeric",
                row_number=row_number,
                nonnegative=False,
            )
            if score <= threshold:
                raise ScientificPrerequisiteError(
                    "sequence_join_hmmer_threshold_mismatch",
                    "a score-filter row does not satisfy the strict HMM score threshold",
                    details={"row": row_number, "score_numeric": str(score)},
                )
            for field in (
                "raw_page_digest",
                "raw_hit_digest",
                "parsed_row_digest",
            ):
                _validate_digest(
                    row[field],
                    field=field,
                    code="sequence_join_hmmer_digest_invalid",
                )
            rows.append(row)
            hits.append(
                ScoreFilteredHit(
                    accession=accession,
                    target=target,
                    evalue=str(evalue.normalize()) if evalue else "0",
                    hmm_score=str(score.normalize()) if score else "0",
                    raw_page_digest=row["raw_page_digest"],
                    raw_hit_digest=row["raw_hit_digest"],
                    parsed_row_digest=row["parsed_row_digest"],
                )
            )
            previous_accession = accession
    except csv.Error as exc:
        raise ScientificPrerequisiteError(
            "sequence_join_hmmer_csv_invalid",
            "the score-filter artifact is not valid CSV",
            details={"message": str(exc)},
        ) from exc
    if aox_hmmer.canonical_rows_to_csv(rows) != text:
        raise ScientificPrerequisiteError(
            "sequence_join_hmmer_serialization_mismatch",
            "the score-filter CSV is not the canonical upstream serialization",
        )
    return tuple(hits)


def _parse_fasta_header(header: str, *, line_number: int) -> tuple[str, str | None]:
    if (
        not header
        or header != header.strip()
        or any(ord(character) < 32 or ord(character) > 126 for character in header)
    ):
        raise ScientificPrerequisiteError(
            "sequence_join_fasta_header_invalid",
            "a UniProt FASTA header is empty or non-canonical",
            details={"line": line_number},
        )
    identifier = header.split(maxsplit=1)[0]
    tagged = _TAGGED_FASTA_ID_PATTERN.fullmatch(identifier)
    if tagged is not None:
        return tagged.group("accession"), tagged.group("database")
    if _UNIPROT_ACCESSION_PATTERN.fullmatch(identifier) is not None:
        return identifier, None
    raise ScientificPrerequisiteError(
        "sequence_join_fasta_header_invalid",
        "a UniProt FASTA header is not sp|ACCESSION|, tr|ACCESSION|, or bare ACCESSION",
        details={"line": line_number, "identifier": identifier},
    )


def _parse_uniprot_fasta(raw: bytes) -> tuple[FastaSequence, ...]:
    text = _decode_utf8(raw, field="uniprot_sequences_fasta")
    records: list[FastaSequence] = []
    seen: set[str] = set()
    header: str | None = None
    accession: str | None = None
    database_tag: str | None = None
    sequence_lines: list[str] = []

    def finish_record(*, line_number: int) -> None:
        nonlocal header, accession, database_tag, sequence_lines
        if header is None or accession is None:
            return
        sequence = "".join(sequence_lines)
        if not sequence or _SEQUENCE_PATTERN.fullmatch(sequence) is None:
            raise ScientificPrerequisiteError(
                "sequence_join_fasta_sequence_invalid",
                "a UniProt FASTA record has an empty or illegal protein sequence",
                details={"accession": accession, "line": line_number},
            )
        if accession in seen:
            raise ScientificPrerequisiteError(
                "sequence_join_fasta_duplicate_accession",
                "the UniProt FASTA contains a duplicate primary accession",
                details={"accession": accession},
            )
        records.append(
            FastaSequence(
                primary_accession=accession,
                sequence=sequence,
                database_tag=database_tag,
                description=header,
            )
        )
        seen.add(accession)
        header = None
        accession = None
        database_tag = None
        sequence_lines = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise ScientificPrerequisiteError(
                "sequence_join_fasta_blank_line",
                "the UniProt FASTA contains a blank line",
                details={"line": line_number},
            )
        if line.startswith(">"):
            finish_record(line_number=line_number)
            header = line[1:]
            accession, database_tag = _parse_fasta_header(
                header,
                line_number=line_number,
            )
            continue
        if header is None:
            raise ScientificPrerequisiteError(
                "sequence_join_fasta_sequence_before_header",
                "the UniProt FASTA contains sequence bytes before a header",
                details={"line": line_number},
            )
        if line != line.strip() or _SEQUENCE_PATTERN.fullmatch(line) is None:
            raise ScientificPrerequisiteError(
                "sequence_join_fasta_sequence_invalid",
                "a UniProt FASTA line contains whitespace or illegal residues",
                details={"accession": accession, "line": line_number},
            )
        sequence_lines.append(line)
    finish_record(line_number=len(text.splitlines()) + 1)
    return tuple(records)


class _DuplicateJsonKey(ValueError):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(key)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def _positive_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_metadata_invalid",
            "a UniProt metadata integer is not positive",
            details={"field": field},
        )
    return value


def _nonnegative_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_metadata_invalid",
            "a UniProt metadata count is not a nonnegative integer",
            details={"field": field},
        )
    return value


def _nonempty_string(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
    ):
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_metadata_invalid",
            "a required UniProt metadata string is empty or malformed",
            details={"field": field},
        )
    return value


def _timestamp(value: object, *, field: str) -> str:
    text = _nonempty_string(value, field=field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_metadata_invalid",
            "a UniProt retrieval timestamp is not RFC3339-compatible",
            details={"field": field},
        ) from exc
    if parsed.tzinfo is None:
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_metadata_invalid",
            "a UniProt retrieval timestamp lacks a timezone",
            details={"field": field},
        )
    return text


def _validate_mapping_annotations(
    annotations: object,
    *,
    requested_accession: str,
    primary_accession: str,
    sequence_digest: str,
) -> tuple[int, int]:
    if not isinstance(annotations, list) or any(
        not isinstance(annotation, dict) for annotation in annotations
    ):
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_mapping_invalid",
            "UniProt mapping annotations are not an object list",
            details={"requested_accession": requested_accession},
        )
    provider_mappings = [
        annotation
        for annotation in annotations
        if annotation.get("annotation_type") == "provider_identity_mapping"
    ]
    expected_provider_mapping = {
        "annotation_type": "provider_identity_mapping",
        "source_database": "requested_identifier",
        "source_accession": requested_accession,
        "target_database": "uniprotkb",
        "target_accession": primary_accession,
        "relationship": "resolves_to_primary_accession",
        "identity_replaced": False,
    }
    if provider_mappings != [expected_provider_mapping]:
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_mapping_invalid",
            "UniProt metadata lacks one exact requested-to-primary mapping",
            details={
                "requested_accession": requested_accession,
                "primary_accession": primary_accession,
            },
        )

    source_identity_count = 0
    mismatch_resolution_count = 0
    for annotation in annotations:
        if annotation.get("identity_replaced") is not False:
            raise ScientificPrerequisiteError(
                "sequence_join_uniprot_identity_replacement_forbidden",
                "a UniProt mapping annotation attempts to replace identity",
                details={"requested_accession": requested_accession},
            )
        annotation_type = annotation.get("annotation_type")
        if annotation_type == "provider_identity_mapping":
            continue
        if annotation_type != "cross_database_sequence_identity":
            raise ScientificPrerequisiteError(
                "sequence_join_uniprot_mapping_invalid",
                "UniProt metadata contains an unknown mapping annotation",
                details={
                    "requested_accession": requested_accession,
                    "annotation_type": annotation_type,
                },
            )
        source_identity_count += 1
        if (
            annotation.get("target_database") != "uniprotkb"
            or annotation.get("target_accession") != primary_accession
            or annotation.get("target_sequence_digest") != sequence_digest
        ):
            raise ScientificPrerequisiteError(
                "sequence_join_uniprot_mapping_invalid",
                "a cross-database annotation does not bind the selected UniProt sequence",
                details={"requested_accession": requested_accession},
            )
        relationship = annotation.get("relationship")
        choice = annotation.get("explicit_choice")
        if relationship == "sequence_digest_match":
            if choice is not None:
                raise ScientificPrerequisiteError(
                    "sequence_join_uniprot_mapping_invalid",
                    "a matching sequence identity carries a stale explicit choice",
                    details={"requested_accession": requested_accession},
                )
        elif relationship == "sequence_mismatch_explicitly_resolved":
            if choice != "accept_uniprot":
                raise ScientificPrerequisiteError(
                    "sequence_join_uniprot_identity_replacement_forbidden",
                    "a sequence mismatch lacks the explicit accept_uniprot decision",
                    details={"requested_accession": requested_accession},
                )
            mismatch_resolution_count += 1
        else:
            raise ScientificPrerequisiteError(
                "sequence_join_uniprot_mapping_invalid",
                "a cross-database annotation has an unknown relationship",
                details={"requested_accession": requested_accession},
            )
    return source_identity_count, mismatch_resolution_count


def _parse_uniprot_metadata(
    raw: bytes,
    *,
    input_hits: tuple[ScoreFilteredHit, ...],
    fasta_records: tuple[FastaSequence, ...],
) -> ParsedUniProtEvidence:
    text = _decode_utf8(raw, field="uniprot_metadata_json")
    try:
        payload = json.loads(text, object_pairs_hook=_unique_json_object)
    except _DuplicateJsonKey as exc:
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_metadata_duplicate_key",
            "UniProt metadata contains a duplicate JSON key",
            details={"key": exc.key},
        ) from exc
    except json.JSONDecodeError as exc:
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_metadata_json_invalid",
            "UniProt metadata is not valid JSON",
            details={"line": exc.lineno, "column": exc.colno},
        ) from exc
    if not isinstance(payload, dict) or frozenset(payload) != _UNIPROT_METADATA_KEYS:
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_metadata_schema_mismatch",
            "UniProt metadata does not match the provider schema",
            details={
                "expected": sorted(_UNIPROT_METADATA_KEYS),
                "actual": sorted(payload) if isinstance(payload, dict) else [],
            },
        )
    canonical_text = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    if canonical_text != text:
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_metadata_serialization_mismatch",
            "UniProt metadata is not the canonical provider serialization",
        )
    if (
        payload["provider"] != "uniprot"
        or payload["database"] != "uniprotkb"
        or payload["identity_contract_id"] != _UNIPROT_IDENTITY_CONTRACT_ID
    ):
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_identity_contract_mismatch",
            "UniProt metadata does not bind the required provider identity contract",
        )
    fields = payload["fields"]
    if (
        not isinstance(fields, list)
        or any(not isinstance(field, str) or not field for field in fields)
        or len(fields) != len(set(fields))
        or not _REQUIRED_UNIPROT_FIELDS.issubset(fields)
    ):
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_metadata_invalid",
            "UniProt metadata lacks the required identity and sequence fields",
            details={"field": "fields"},
        )
    _positive_integer(payload["batch_size"], field="batch_size")
    release = _nonempty_string(payload["uniprot_release"], field="uniprot_release")
    if _UNIPROT_RELEASE_PATTERN.fullmatch(release) is None:
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_metadata_invalid",
            "the UniProt release does not match the versioned provider format",
            details={"field": "uniprot_release"},
        )
    release_date_raw = payload["uniprot_release_date"]
    if release_date_raw is not None:
        release_date = _nonempty_string(
            release_date_raw,
            field="uniprot_release_date",
        )
    else:
        release_date = None
    retrieved_at = _timestamp(payload["retrieved_at"], field="retrieved_at")
    aggregate_response_digest = str(payload["aggregate_response_digest"])
    _validate_digest(
        aggregate_response_digest,
        field="aggregate_response_digest",
        code="sequence_join_uniprot_digest_invalid",
    )
    api_version = _nonempty_string(payload["api_version"], field="api_version")
    warnings = payload["warnings"]
    if not isinstance(warnings, list):
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_metadata_invalid",
            "UniProt warnings are not a list",
            details={"field": "warnings"},
        )
    declared_source_count = _nonnegative_integer(
        payload["source_sequence_identity_count"],
        field="source_sequence_identity_count",
    )
    declared_mismatch_count = _nonnegative_integer(
        payload["sequence_mismatch_resolution_count"],
        field="sequence_mismatch_resolution_count",
    )

    expected_accessions = [hit.accession for hit in input_hits]
    if payload["requested_accessions"] != expected_accessions:
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_requested_accessions_mismatch",
            "UniProt requested accessions do not exactly match the HMMER-selected identities",
            details={
                "expected": expected_accessions,
                "actual": payload["requested_accessions"],
            },
        )
    records_payload = payload["records"]
    if not isinstance(records_payload, list) or any(
        not isinstance(record, dict) for record in records_payload
    ):
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_metadata_invalid",
            "UniProt records are not an object list",
            details={"field": "records"},
        )
    if len(records_payload) != len(input_hits):
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_record_count_mismatch",
            "UniProt metadata does not contain one record per HMMER-selected accession",
            details={"expected": len(input_hits), "actual": len(records_payload)},
        )
    fasta_by_primary = {record.primary_accession: record for record in fasta_records}
    identities: list[UniProtIdentity] = []
    used_primary: set[str] = set()
    actual_source_count = 0
    actual_mismatch_count = 0

    for index, (hit, record) in enumerate(
        zip(input_hits, records_payload, strict=True),
        start=1,
    ):
        if frozenset(record) != _UNIPROT_RECORD_KEYS:
            raise ScientificPrerequisiteError(
                "sequence_join_uniprot_record_schema_mismatch",
                "a UniProt identity record does not match the provider schema",
                details={
                    "record": index,
                    "expected": sorted(_UNIPROT_RECORD_KEYS),
                    "actual": sorted(record),
                },
            )
        requested = str(record["requested_accession"])
        primary = str(record["primary_accession"])
        if requested != hit.accession:
            raise ScientificPrerequisiteError(
                "sequence_join_uniprot_requested_accessions_mismatch",
                "a UniProt record does not preserve the HMMER requested accession",
                details={"record": index, "expected": hit.accession, "actual": requested},
            )
        if _UNIPROT_ACCESSION_PATTERN.fullmatch(primary) is None:
            raise ScientificPrerequisiteError(
                "sequence_join_uniprot_primary_accession_invalid",
                "a UniProt record has an invalid primary accession",
                details={"record": index, "primary_accession": primary},
            )
        if primary in used_primary:
            raise ScientificPrerequisiteError(
                "sequence_join_uniprot_duplicate_primary_accession",
                "multiple HMMER identities resolve to one UniProt primary accession",
                details={"primary_accession": primary},
            )
        fasta = fasta_by_primary.get(primary)
        if fasta is None:
            raise ScientificPrerequisiteError(
                "sequence_join_uniprot_sequence_missing",
                "a UniProt metadata record has no matching FASTA sequence",
                details={"requested_accession": requested, "primary_accession": primary},
            )
        reviewed = record["reviewed"]
        if not isinstance(reviewed, bool):
            raise ScientificPrerequisiteError(
                "sequence_join_uniprot_metadata_invalid",
                "a UniProt reviewed flag is not boolean",
                details={"record": index},
            )
        if (fasta.database_tag == "sp" and not reviewed) or (
            fasta.database_tag == "tr" and reviewed
        ):
            raise ScientificPrerequisiteError(
                "sequence_join_uniprot_review_status_mismatch",
                "the FASTA sp/tr tag disagrees with UniProt reviewed status",
                details={"primary_accession": primary},
            )
        if record["uniprot_release"] != release or record["retrieved_at"] != retrieved_at:
            raise ScientificPrerequisiteError(
                "sequence_join_uniprot_provenance_mismatch",
                "a UniProt record does not bind the aggregate release and retrieval time",
                details={"requested_accession": requested},
            )
        if record["uniprot_release_date"] != release_date:
            raise ScientificPrerequisiteError(
                "sequence_join_uniprot_provenance_mismatch",
                "a UniProt record release date differs from aggregate metadata",
                details={"requested_accession": requested},
            )
        sequence_digest = str(record["sequence_digest"])
        response_digest = str(record["response_digest"])
        record_digest = str(record["record_digest"])
        for field, value in (
            ("sequence_digest", sequence_digest),
            ("response_digest", response_digest),
            ("record_digest", record_digest),
        ):
            _validate_digest(
                value,
                field=field,
                code="sequence_join_uniprot_digest_invalid",
            )
        if sequence_digest != fasta.sequence_digest:
            raise ScientificPrerequisiteError(
                "sequence_join_uniprot_sequence_digest_mismatch",
                "UniProt FASTA bytes do not match the metadata sequence digest",
                details={"primary_accession": primary},
            )
        if record["sequence_length"] != len(fasta.sequence):
            raise ScientificPrerequisiteError(
                "sequence_join_uniprot_sequence_length_mismatch",
                "UniProt metadata length does not match the exact FASTA sequence",
                details={"primary_accession": primary},
            )
        entry_version = _positive_integer(
            record["entry_version"], field=f"records[{index}].entry_version"
        )
        sequence_version = _positive_integer(
            record["sequence_version"], field=f"records[{index}].sequence_version"
        )
        identifier = _nonempty_string(
            record["uniprot_identifier"],
            field=f"records[{index}].uniprot_identifier",
        )
        entry_type = _nonempty_string(
            record["entry_type"],
            field=f"records[{index}].entry_type",
        )
        provider_metadata = record["provider_metadata"]
        if not isinstance(provider_metadata, dict) or "sequence" in provider_metadata:
            raise ScientificPrerequisiteError(
                "sequence_join_uniprot_metadata_invalid",
                "a UniProt provider record summary is malformed or embeds sequence bytes",
                details={"record": index},
            )
        secondary = provider_metadata.get("secondaryAccessions") or []
        audit = provider_metadata.get("entryAudit")
        if (
            provider_metadata.get("primaryAccession") != primary
            or (provider_metadata.get("uniProtkbId") or primary) != identifier
            or provider_metadata.get("entryType") != entry_type
            or not isinstance(secondary, list)
            or any(not isinstance(value, str) for value in secondary)
            or not isinstance(audit, dict)
            or audit.get("entryVersion") != entry_version
            or audit.get("sequenceVersion") != sequence_version
            or (requested != primary and requested not in secondary)
        ):
            raise ScientificPrerequisiteError(
                "sequence_join_uniprot_provider_record_mismatch",
                "the safe UniProt provider record summary disagrees with normalized identity metadata",
                details={"requested_accession": requested, "primary_accession": primary},
            )
        source_count, mismatch_count = _validate_mapping_annotations(
            record["mapping_annotations"],
            requested_accession=requested,
            primary_accession=primary,
            sequence_digest=sequence_digest,
        )
        actual_source_count += source_count
        actual_mismatch_count += mismatch_count
        identities.append(
            UniProtIdentity(
                requested_accession=requested,
                primary_accession=primary,
                sequence=fasta.sequence,
                sequence_digest=sequence_digest,
                reviewed=reviewed,
                entry_version=entry_version,
                sequence_version=sequence_version,
                response_digest=response_digest,
                record_digest=record_digest,
            )
        )
        used_primary.add(primary)

    extra_fasta = sorted(set(fasta_by_primary) - used_primary)
    if extra_fasta:
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_sequence_extra",
            "the UniProt FASTA contains records outside the requested identity set",
            details={"primary_accessions": extra_fasta},
        )
    if (
        actual_source_count != declared_source_count
        or actual_mismatch_count != declared_mismatch_count
    ):
        raise ScientificPrerequisiteError(
            "sequence_join_uniprot_mapping_count_mismatch",
            "UniProt mapping counts do not match the sealed annotations",
            details={
                "declared_source_sequence_identity_count": declared_source_count,
                "actual_source_sequence_identity_count": actual_source_count,
                "declared_sequence_mismatch_resolution_count": declared_mismatch_count,
                "actual_sequence_mismatch_resolution_count": actual_mismatch_count,
            },
        )
    return ParsedUniProtEvidence(
        records=tuple(identities),
        release=release,
        release_date=release_date,
        retrieved_at=retrieved_at,
        aggregate_response_digest=aggregate_response_digest,
        api_version=api_version,
        warning_count=len(warnings),
        source_sequence_identity_count=actual_source_count,
        sequence_mismatch_resolution_count=actual_mismatch_count,
    )


def join_score_filtered_accessions(
    score_filtered_csv: str | bytes,
    uniprot_fasta: str | bytes,
    uniprot_metadata_json: str | bytes,
    *,
    expected_contract_id: str = CONTRACT_ID,
    expected_contract_digest: str | None = None,
    expected_implementation_digest: str | None = None,
    expected_hmmer_contract_id: str = aox_hmmer.CONTRACT_ID,
    expected_hmmer_contract_digest: str | None = None,
    expected_hmmer_implementation_digest: str | None = None,
    expected_score_filtered_csv_digest: str | None = None,
    expected_uniprot_fasta_digest: str | None = None,
    expected_uniprot_metadata_digest: str | None = None,
) -> SequenceLengthJoinResult:
    verify_contract(
        expected_contract_id=expected_contract_id,
        expected_contract_digest=expected_contract_digest,
        expected_implementation_digest=expected_implementation_digest,
        expected_hmmer_contract_id=expected_hmmer_contract_id,
        expected_hmmer_contract_digest=expected_hmmer_contract_digest,
        expected_hmmer_implementation_digest=expected_hmmer_implementation_digest,
    )
    score_bytes, score_digest = _bytes_and_digest(
        score_filtered_csv,
        field="hmmer_score_filtered_accessions_csv",
        expected_digest=expected_score_filtered_csv_digest,
    )
    fasta_bytes, fasta_digest = _bytes_and_digest(
        uniprot_fasta,
        field="uniprot_sequences_fasta",
        expected_digest=expected_uniprot_fasta_digest,
    )
    metadata_bytes, metadata_digest = _bytes_and_digest(
        uniprot_metadata_json,
        field="uniprot_metadata_json",
        expected_digest=expected_uniprot_metadata_digest,
    )
    input_hits = _parse_score_filtered_csv(score_bytes)
    fasta_records = _parse_uniprot_fasta(fasta_bytes)
    evidence = _parse_uniprot_metadata(
        metadata_bytes,
        input_hits=input_hits,
        fasta_records=fasta_records,
    )
    evidence_by_requested = {
        record.requested_accession: record for record in evidence.records
    }
    joined = tuple(
        JoinedHit(
            target=hit.target,
            uniprot_accession=hit.accession,
            primary_accession=evidence_by_requested[hit.accession].primary_accession,
            hmm_score=hit.hmm_score,
            evalue=hit.evalue,
            sequence=evidence_by_requested[hit.accession].sequence,
            sequence_digest=evidence_by_requested[hit.accession].sequence_digest,
        )
        for hit in input_hits
        if LENGTH_MIN
        <= len(evidence_by_requested[hit.accession].sequence)
        <= LENGTH_MAX
    )
    return SequenceLengthJoinResult(
        input_hits=input_hits,
        uniprot_records=evidence.records,
        hits=joined,
        score_filtered_csv_digest=score_digest,
        uniprot_fasta_digest=fasta_digest,
        uniprot_metadata_digest=metadata_digest,
        uniprot_release=evidence.release,
        uniprot_release_date=evidence.release_date,
        retrieved_at=evidence.retrieved_at,
        aggregate_response_digest=evidence.aggregate_response_digest,
        api_version=evidence.api_version,
        warning_count=evidence.warning_count,
        source_sequence_identity_count=evidence.source_sequence_identity_count,
        sequence_mismatch_resolution_count=evidence.sequence_mismatch_resolution_count,
    )


def canonical_hits_to_csv(rows: Iterable[Mapping[str, str]]) -> str:
    materialized = tuple(rows)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=list(OUTPUT_COLUMNS),
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    previous_accession: str | None = None
    for row_number, row in enumerate(materialized, start=2):
        if tuple(row) != OUTPUT_COLUMNS:
            raise ScientificPrerequisiteError(
                "sequence_join_output_schema_mismatch",
                "a canonical joined-hit row has the wrong columns or order",
                details={"row": row_number, "actual": list(row)},
            )
        accession = row["uniprot_accession"]
        if (
            _UNIPROT_ACCESSION_PATTERN.fullmatch(accession) is None
            or (previous_accession is not None and accession <= previous_accession)
        ):
            raise ScientificPrerequisiteError(
                "sequence_join_output_order_invalid",
                "joined-hit rows require unique lexical UniProt accessions",
                details={"row": row_number, "uniprot_accession": accession},
            )
        sequence = row["sequence"]
        target = row["target"]
        try:
            length = int(row["length"])
            score = Decimal(row["hmm_score"])
            evalue = Decimal(row["evalue"])
        except (ValueError, InvalidOperation) as exc:
            raise ScientificPrerequisiteError(
                "sequence_join_output_numeric_invalid",
                "a canonical joined-hit row has malformed numeric fields",
                details={"row": row_number},
            ) from exc
        if (
            not target
            or target != target.strip()
            or any(ord(character) < 32 or ord(character) > 126 for character in target)
            or not score.is_finite()
            or score <= Decimal(aox_hmmer.SCORE_THRESHOLD_DISPLAY)
            or row["hmm_score"] != (str(score.normalize()) if score else "0")
            or not evalue.is_finite()
            or evalue < 0
            or row["evalue"] != (str(evalue.normalize()) if evalue else "0")
            or _SEQUENCE_PATTERN.fullmatch(sequence) is None
            or length != len(sequence)
            or row["length"] != str(length)
            or not LENGTH_MIN <= length <= LENGTH_MAX
        ):
            raise ScientificPrerequisiteError(
                "sequence_join_output_scientific_mismatch",
                "a canonical joined-hit row violates score, sequence, or length invariants",
                details={"row": row_number, "uniprot_accession": accession},
            )
        writer.writerow(dict(row))
        previous_accession = accession
    return output.getvalue()


IMPLEMENTATION_DIGEST = implementation_digest()
CONTRACT_DIGEST = contract_digest(implementation_digest_value=IMPLEMENTATION_DIGEST)


__all__ = [
    "CONTRACT_DIGEST",
    "CONTRACT_ID",
    "FASTA_OUTPUT_NAME",
    "HITS_OUTPUT_NAME",
    "IMPLEMENTATION_DIGEST",
    "LENGTH_MAX",
    "LENGTH_MIN",
    "OUTPUT_COLUMNS",
    "FastaSequence",
    "JoinedHit",
    "ParsedUniProtEvidence",
    "ScientificPrerequisiteError",
    "ScoreFilteredHit",
    "SequenceLengthJoinResult",
    "UniProtIdentity",
    "canonical_hits_to_csv",
    "contract_digest",
    "contract_payload",
    "implementation_digest",
    "join_score_filtered_accessions",
    "verify_contract",
]
