from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .aox_motif import ScientificPrerequisiteError


CALCULATION_ID = "aox_global_sequence_identity@1"
MEMBERSHIP_SCHEMA_ID = "cdhit_cluster_membership@1"
NODE_SCHEMA_ID = "aox_candidate_graph_nodes@1"
EDGE_SCHEMA_ID = "aox_candidate_graph_edges@1"
MANIFEST_SCHEMA_ID = "aox_candidate_similarity_graph_manifest@1"
DEFAULT_THRESHOLD_PPM = 850_000
PPM_SCALE = 1_000_000

BLOSUM62_ID = "BLOSUM62"
BLOSUM62_ALPHABET = tuple("ARNDCQEGHILKMFPSTWYVBZX*")
GAP_OPEN_HALF_SCORE = -20
GAP_EXTEND_HALF_SCORE = -1
IDENTITY_DENOMINATOR = "aligned_residue_pairs_excluding_gaps"
TIE_BREAK_POLICY = (
    "higher_alignment_score_then_more_exact_matches_then_more_aligned_residue_pairs_"
    "then_terminal_or_diagonal_predecessor_state_order_match_gap_in_target_gap_in_source_"
    "and_prefer_gap_extension_over_equal_score_opening"
)

MEMBERSHIP_COLUMNS = (
    "cluster_id",
    "member_id",
    "representative_id",
    "is_representative",
    "identity_to_representative",
    "member_length",
)
NODE_COLUMNS = (
    "node_id",
    "sequence_digest",
    "sequence_length",
    "cluster_id",
    "representative_id",
    "is_representative",
    "identity_to_representative",
    "candidate_fasta_digest",
    "candidate_sequence_set_digest",
    "cdhit_membership_digest",
    "cdhit_membership_set_digest",
    "cdhit_membership_schema_id",
    "node_schema_id",
    "similarity_calculation_id",
    "similarity_calculation_digest",
    "similarity_implementation_digest",
)
EDGE_COLUMNS = (
    "source",
    "target",
    "source_sequence_digest",
    "target_sequence_digest",
    "source_cluster_id",
    "target_cluster_id",
    "alignment_score_half_units",
    "identity_matches",
    "identity_aligned_residues",
    "similarity_ppm",
    "similarity",
    "similarity_threshold_ppm",
    "candidate_sequence_set_digest",
    "cdhit_membership_set_digest",
    "cdhit_membership_schema_id",
    "edge_schema_id",
    "similarity_calculation_id",
    "similarity_calculation_digest",
    "similarity_implementation_digest",
)

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_SEQUENCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.|:/-]*$")
_CLUSTER_ID_PATTERN = re.compile(r"^cluster_(0|[1-9][0-9]*)$")
_IDENTITY_PATTERN = re.compile(r"^(?:0\.[0-9]{6}|1\.000000)$")
_LEGACY_NODE_FIELDS = frozenset({"label", "score"})
_LEGACY_EDGE_FIELDS = frozenset({"weight"})
_NEGATIVE_INFINITY = -(10**15)

# Standard BLOSUM62 values.  Alignment scores are multiplied by two so the
# reference half-point gap extension is represented with exact integers.
_BLOSUM62_ROWS = (
    " 4 -1 -2 -2  0 -1 -1  0 -2 -1 -1 -1 -1 -2 -1  1  0 -3 -2  0 -2 -1  0 -4",
    "-1  5  0 -2 -3  1  0 -2  0 -3 -2  2 -1 -3 -2 -1 -1 -3 -2 -3 -1  0 -1 -4",
    "-2  0  6  1 -3  0  0  0  1 -3 -3  0 -2 -3 -2  1  0 -4 -2 -3  3  0 -1 -4",
    "-2 -2  1  6 -3  0  2 -1 -1 -3 -4 -1 -3 -3 -1  0 -1 -4 -3 -3  4  1 -1 -4",
    " 0 -3 -3 -3  9 -3 -4 -3 -3 -1 -1 -3 -1 -2 -3 -1 -1 -2 -2 -1 -3 -3 -2 -4",
    "-1  1  0  0 -3  5  2 -2  0 -3 -2  1  0 -3 -1  0 -1 -2 -1 -2  0  3 -1 -4",
    "-1  0  0  2 -4  2  5 -2  0 -3 -3  1 -2 -3 -1  0 -1 -3 -2 -2  1  4 -1 -4",
    " 0 -2  0 -1 -3 -2 -2  6 -2 -4 -4 -2 -3 -3 -2  0 -2 -2 -3 -3 -1 -2 -1 -4",
    "-2  0  1 -1 -3  0  0 -2  8 -3 -3 -1 -2 -1 -2 -1 -2 -2  2 -3  0  0 -1 -4",
    "-1 -3 -3 -3 -1 -3 -3 -4 -3  4  2 -3  1  0 -3 -2 -1 -3 -1  3 -3 -3 -1 -4",
    "-1 -2 -3 -4 -1 -2 -3 -4 -3  2  4 -2  2  0 -3 -2 -1 -2 -1  1 -4 -3 -1 -4",
    "-1  2  0 -1 -3  1  1 -2 -1 -3 -2  5 -1 -3 -1  0 -1 -3 -2 -2  0  1 -1 -4",
    "-1 -1 -2 -3 -1  0 -2 -3 -2  1  2 -1  5  0 -2 -1 -1 -1 -1  1 -3 -1 -1 -4",
    "-2 -3 -3 -3 -2 -3 -3 -3 -1  0  0 -3  0  6 -4 -2 -2  1  3 -1 -3 -3 -1 -4",
    "-1 -2 -2 -1 -3 -1 -1 -2 -2 -3 -3 -1 -2 -4  7 -1 -1 -4 -3 -2 -2 -1 -2 -4",
    " 1 -1  1  0 -1  0  0  0 -1 -2 -2  0 -1 -2 -1  4  1 -3 -2 -2  0  0  0 -4",
    " 0 -1  0 -1 -1 -1 -1 -2 -2 -1 -1 -1 -1 -2 -1  1  5 -2 -2  0 -1 -1  0 -4",
    "-3 -3 -4 -4 -2 -2 -3 -2 -2 -3 -2 -3 -1  1 -4 -3 -2 11  2 -3 -4 -3 -2 -4",
    "-2 -2 -2 -3 -2 -1 -2 -3  2 -1 -1 -2 -1  3 -3 -2 -2  2  7 -1 -3 -2 -1 -4",
    " 0 -3 -3 -3 -1 -2 -2 -3 -3  3  1 -2  1 -1 -2 -2  0 -3 -1  4 -3 -2 -1 -4",
    "-2 -1  3  4 -3  0  1 -1  0 -3 -4  0 -3 -3 -2  0 -1 -4 -3 -3  4  1 -1 -4",
    "-1  0  0  1 -3  3  4 -2  0 -3 -3  1 -1 -3 -1  0 -1 -3 -2 -2  1  4 -1 -4",
    " 0 -1 -1 -1 -2 -1 -1 -1 -1 -1 -1 -1 -1 -1 -2  0  0 -2 -1 -1 -1 -1 -1 -4",
    "-4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4  1",
)


def _build_blosum62() -> dict[tuple[str, str], int]:
    rows = [tuple(int(value) for value in row.split()) for row in _BLOSUM62_ROWS]
    if len(rows) != len(BLOSUM62_ALPHABET) or any(
        len(row) != len(BLOSUM62_ALPHABET) for row in rows
    ):
        raise RuntimeError("embedded BLOSUM62 dimensions do not match its alphabet")
    if any(
        rows[left][right] != rows[right][left]
        for left in range(len(rows))
        for right in range(len(rows))
    ):
        raise RuntimeError("embedded BLOSUM62 must be symmetric")
    return {
        (left_residue, right_residue): rows[left][right] * 2
        for left, left_residue in enumerate(BLOSUM62_ALPHABET)
        for right, right_residue in enumerate(BLOSUM62_ALPHABET)
    }


_BLOSUM62_HALF_SCORES = _build_blosum62()


@dataclass(frozen=True, slots=True)
class SequenceRecord:
    sequence_id: str
    description: str
    sequence: str

    @property
    def sequence_digest(self) -> str:
        return _sha256(self.sequence.encode("ascii"))


@dataclass(frozen=True, slots=True)
class ParsedSequenceSet:
    records: tuple[SequenceRecord, ...]
    input_digest: str
    sequence_set_digest: str


@dataclass(frozen=True, slots=True)
class CDHitMembershipRow:
    cluster_id: str
    member_id: str
    representative_id: str
    is_representative: bool
    identity_ppm: int
    member_length: int

    @property
    def identity_display(self) -> str:
        return _format_ppm(self.identity_ppm)

    def to_row(self) -> dict[str, object]:
        return {
            "cluster_id": self.cluster_id,
            "member_id": self.member_id,
            "representative_id": self.representative_id,
            "is_representative": self.is_representative,
            "identity_to_representative": self.identity_display,
            "member_length": self.member_length,
        }


@dataclass(frozen=True, slots=True)
class ParsedCDHitMembership:
    rows: tuple[CDHitMembershipRow, ...]
    input_digest: str
    membership_set_digest: str


@dataclass(frozen=True, slots=True)
class AlignmentIdentity:
    alignment_score_half_units: int
    identity_matches: int
    identity_aligned_residues: int

    @property
    def similarity_ppm(self) -> int:
        if self.identity_aligned_residues == 0:
            return 0
        return self.identity_matches * PPM_SCALE // self.identity_aligned_residues

    @property
    def similarity_display(self) -> str:
        return _format_ppm(self.similarity_ppm)

    def passes_threshold(self, threshold_ppm: int) -> bool:
        if self.identity_aligned_residues == 0:
            return threshold_ppm == 0
        return (
            self.identity_matches * PPM_SCALE
            >= threshold_ppm * self.identity_aligned_residues
        )


@dataclass(frozen=True, slots=True)
class GraphNode:
    sequence: SequenceRecord
    membership: CDHitMembershipRow
    candidate_fasta_digest: str
    candidate_sequence_set_digest: str
    cdhit_membership_digest: str
    cdhit_membership_set_digest: str

    def to_row(self) -> dict[str, object]:
        return {
            "node_id": self.sequence.sequence_id,
            "sequence_digest": self.sequence.sequence_digest,
            "sequence_length": len(self.sequence.sequence),
            "cluster_id": self.membership.cluster_id,
            "representative_id": self.membership.representative_id,
            "is_representative": self.membership.is_representative,
            "identity_to_representative": self.membership.identity_display,
            "candidate_fasta_digest": self.candidate_fasta_digest,
            "candidate_sequence_set_digest": self.candidate_sequence_set_digest,
            "cdhit_membership_digest": self.cdhit_membership_digest,
            "cdhit_membership_set_digest": self.cdhit_membership_set_digest,
            "cdhit_membership_schema_id": MEMBERSHIP_SCHEMA_ID,
            "node_schema_id": NODE_SCHEMA_ID,
            "similarity_calculation_id": CALCULATION_ID,
            "similarity_calculation_digest": CALCULATION_DIGEST,
            "similarity_implementation_digest": IMPLEMENTATION_DIGEST,
        }


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source: GraphNode
    target: GraphNode
    identity: AlignmentIdentity
    threshold_ppm: int

    def to_row(self) -> dict[str, object]:
        return {
            "source": self.source.sequence.sequence_id,
            "target": self.target.sequence.sequence_id,
            "source_sequence_digest": self.source.sequence.sequence_digest,
            "target_sequence_digest": self.target.sequence.sequence_digest,
            "source_cluster_id": self.source.membership.cluster_id,
            "target_cluster_id": self.target.membership.cluster_id,
            "alignment_score_half_units": self.identity.alignment_score_half_units,
            "identity_matches": self.identity.identity_matches,
            "identity_aligned_residues": self.identity.identity_aligned_residues,
            "similarity_ppm": self.identity.similarity_ppm,
            "similarity": self.identity.similarity_display,
            "similarity_threshold_ppm": self.threshold_ppm,
            "candidate_sequence_set_digest": self.source.candidate_sequence_set_digest,
            "cdhit_membership_set_digest": self.source.cdhit_membership_set_digest,
            "cdhit_membership_schema_id": MEMBERSHIP_SCHEMA_ID,
            "edge_schema_id": EDGE_SCHEMA_ID,
            "similarity_calculation_id": CALCULATION_ID,
            "similarity_calculation_digest": CALCULATION_DIGEST,
            "similarity_implementation_digest": IMPLEMENTATION_DIGEST,
        }


@dataclass(frozen=True, slots=True)
class SimilarityGraphResult:
    sequences: ParsedSequenceSet
    membership: ParsedCDHitMembership
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    threshold_ppm: int
    empty_result_reason: str | None

    @property
    def empty_result(self) -> bool:
        return not self.nodes

    def canonical_node_rows(self) -> tuple[dict[str, object], ...]:
        return tuple(node.to_row() for node in self.nodes)

    def canonical_edge_rows(self) -> tuple[dict[str, object], ...]:
        return tuple(edge.to_row() for edge in self.edges)

    def nodes_csv(self) -> str:
        return _rows_to_csv(NODE_COLUMNS, self.canonical_node_rows())

    def edges_csv(self) -> str:
        return _rows_to_csv(EDGE_COLUMNS, self.canonical_edge_rows())

    def manifest(self) -> dict[str, object]:
        nodes_bytes = self.nodes_csv().encode("utf-8")
        edges_bytes = self.edges_csv().encode("utf-8")
        return {
            "manifest_schema_id": MANIFEST_SCHEMA_ID,
            "node_schema_id": NODE_SCHEMA_ID,
            "edge_schema_id": EDGE_SCHEMA_ID,
            "cdhit_membership_schema_id": MEMBERSHIP_SCHEMA_ID,
            "similarity_calculation_id": CALCULATION_ID,
            "similarity_calculation_digest": CALCULATION_DIGEST,
            "similarity_implementation_digest": IMPLEMENTATION_DIGEST,
            "similarity_threshold_ppm": self.threshold_ppm,
            "similarity_threshold": _format_ppm(self.threshold_ppm),
            "candidate_fasta_digest": self.sequences.input_digest,
            "candidate_sequence_set_digest": self.sequences.sequence_set_digest,
            "cdhit_membership_digest": self.membership.input_digest,
            "cdhit_membership_set_digest": self.membership.membership_set_digest,
            "nodes_digest": _sha256(nodes_bytes),
            "edges_digest": _sha256(edges_bytes),
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "empty_result": self.empty_result,
            "empty_result_reason": self.empty_result_reason,
        }

    def manifest_json(self) -> str:
        return _canonical_json_bytes(self.manifest()).decode("utf-8") + "\n"


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _format_ppm(value: int) -> str:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= PPM_SCALE
    ):
        raise ValueError(
            "parts-per-million identity must be an integer in [0, 1000000]"
        )
    return f"{value // PPM_SCALE}.{value % PPM_SCALE:06d}"


def _validate_sequence_id(
    sequence_id: str, *, field: str, row: int | None = None
) -> None:
    if not _SEQUENCE_ID_PATTERN.fullmatch(sequence_id):
        details: dict[str, object] = {"field": field, "value": sequence_id}
        if row is not None:
            details["row"] = row
        raise ScientificPrerequisiteError(
            "similarity_sequence_id_invalid",
            "AOX similarity inputs require a non-empty ASCII sequence identifier",
            details=details,
        )


def _validate_threshold(threshold_ppm: int) -> None:
    if (
        isinstance(threshold_ppm, bool)
        or not isinstance(threshold_ppm, int)
        or not 0 <= threshold_ppm <= PPM_SCALE
    ):
        raise ScientificPrerequisiteError(
            "similarity_threshold_invalid",
            "the similarity threshold must be integer parts-per-million in [0, 1000000]",
            details={"threshold_ppm": threshold_ppm},
        )


def _validate_digest(value: str, *, field: str) -> None:
    if not _DIGEST_PATTERN.fullmatch(value):
        raise ScientificPrerequisiteError(
            "similarity_digest_invalid",
            "a bound AOX similarity digest is malformed",
            details={"field": field},
        )


def implementation_digest() -> str:
    return _sha256(Path(__file__).read_bytes())


def matrix_digest() -> str:
    return _sha256(
        _canonical_json_bytes(
            {
                "alphabet": list(BLOSUM62_ALPHABET),
                "half_score_rows": [
                    [value * 2 for value in (int(item) for item in row.split())]
                    for row in _BLOSUM62_ROWS
                ],
            }
        )
    )


def calculation_payload(
    *, implementation_digest_value: str | None = None
) -> dict[str, object]:
    source_digest = implementation_digest_value or implementation_digest()
    return {
        "calculation_id": CALCULATION_ID,
        "scientific_claim": (
            "global protein alignment identity over supplied sequence bytes; "
            "not HMM score, motif score, CD-HIT identity, or experimental activity"
        ),
        "alignment": {
            "mode": "global_affine_gap",
            "substitution_matrix_id": BLOSUM62_ID,
            "substitution_matrix_digest": matrix_digest(),
            "substitution_matrix_alphabet": list(BLOSUM62_ALPHABET),
            "numeric_unit": "integer_half_score",
            "gap_open_half_score": GAP_OPEN_HALF_SCORE,
            "gap_extend_half_score": GAP_EXTEND_HALF_SCORE,
            "identity_denominator": IDENTITY_DENOMINATOR,
            "identity_scale": "integer_parts_per_million_floor",
            "tie_break_policy": TIE_BREAK_POLICY,
        },
        "default_threshold_ppm": DEFAULT_THRESHOLD_PPM,
        "membership_schema": {
            "schema_id": MEMBERSHIP_SCHEMA_ID,
            "columns": list(MEMBERSHIP_COLUMNS),
            "row_semantics": "one_member_per_row",
            "identity_scale": "fixed_six_decimal_fraction",
        },
        "output_schemas": {
            "nodes": {"schema_id": NODE_SCHEMA_ID, "columns": list(NODE_COLUMNS)},
            "edges": {"schema_id": EDGE_SCHEMA_ID, "columns": list(EDGE_COLUMNS)},
            "manifest": {"schema_id": MANIFEST_SCHEMA_ID},
        },
        "implementation_digest": source_digest,
    }


def calculation_digest(*, implementation_digest_value: str | None = None) -> str:
    return _sha256(
        _canonical_json_bytes(
            calculation_payload(implementation_digest_value=implementation_digest_value)
        )
    )


def calculation_metadata() -> dict[str, object]:
    return {
        "similarity_calculation_id": CALCULATION_ID,
        "similarity_calculation_digest": CALCULATION_DIGEST,
        "similarity_implementation_digest": IMPLEMENTATION_DIGEST,
        "substitution_matrix_id": BLOSUM62_ID,
        "substitution_matrix_digest": matrix_digest(),
        "gap_open_half_score": GAP_OPEN_HALF_SCORE,
        "gap_extend_half_score": GAP_EXTEND_HALF_SCORE,
        "identity_denominator": IDENTITY_DENOMINATOR,
        "default_threshold_ppm": DEFAULT_THRESHOLD_PPM,
    }


def verify_calculation(
    *,
    expected_calculation_id: str = CALCULATION_ID,
    expected_calculation_digest: str | None = None,
    expected_implementation_digest: str | None = None,
) -> None:
    expected = {
        "calculation_id": expected_calculation_id,
        "calculation_digest": expected_calculation_digest or CALCULATION_DIGEST,
        "implementation_digest": expected_implementation_digest
        or IMPLEMENTATION_DIGEST,
    }
    actual = {
        "calculation_id": CALCULATION_ID,
        "calculation_digest": CALCULATION_DIGEST,
        "implementation_digest": IMPLEMENTATION_DIGEST,
    }
    for field, value in expected.items():
        if field.endswith("digest"):
            _validate_digest(str(value), field=field)
    if expected != actual:
        raise ScientificPrerequisiteError(
            "similarity_calculation_digest_drift",
            "the bound AOX similarity identity does not match the installed implementation",
            details={"expected": expected, "actual": actual},
        )


def parse_candidate_fasta(data: str | bytes) -> ParsedSequenceSet:
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScientificPrerequisiteError(
            "candidate_fasta_not_utf8",
            "the candidate FASTA input is not valid UTF-8",
            details={"start": exc.start},
        ) from exc

    records: list[SequenceRecord] = []
    header: str | None = None
    fragments: list[str] = []

    def finish_record() -> None:
        nonlocal header, fragments
        if header is None:
            return
        sequence = "".join(fragments).upper()
        if not sequence:
            raise ScientificPrerequisiteError(
                "empty_candidate_sequence",
                "a candidate FASTA record has no sequence",
                details={"header": header},
            )
        invalid = sorted(set(sequence) - set(BLOSUM62_ALPHABET[:-1]))
        if invalid:
            raise ScientificPrerequisiteError(
                "candidate_residue_unsupported",
                "candidate sequences must use residues supported by BLOSUM62 and may not contain gaps or stops",
                details={"header": header, "invalid_characters": invalid},
            )
        parts = header.split(maxsplit=1)
        sequence_id = parts[0]
        _validate_sequence_id(sequence_id, field="candidate_fasta_header")
        records.append(
            SequenceRecord(
                sequence_id=sequence_id,
                description=parts[1].strip() if len(parts) == 2 else "",
                sequence=sequence,
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
                    "empty_candidate_fasta_header",
                    "a candidate FASTA header is empty",
                    details={"line": line_number},
                )
            continue
        if header is None:
            raise ScientificPrerequisiteError(
                "candidate_sequence_before_header",
                "candidate FASTA sequence data appeared before its header",
                details={"line": line_number},
            )
        if any(character.isspace() for character in line):
            raise ScientificPrerequisiteError(
                "whitespace_in_candidate_sequence",
                "candidate FASTA sequence lines may not contain internal whitespace",
                details={"line": line_number},
            )
        fragments.append(line)
    finish_record()

    sequence_ids = [record.sequence_id for record in records]
    duplicates = sorted(
        sequence_id
        for sequence_id in set(sequence_ids)
        if sequence_ids.count(sequence_id) > 1
    )
    if duplicates:
        raise ScientificPrerequisiteError(
            "duplicate_candidate_sequence_id",
            "candidate graph inputs require unique FASTA sequence identifiers",
            details={"sequence_ids": duplicates},
        )

    canonical_records = [
        {
            "sequence_id": record.sequence_id,
            "sequence_digest": record.sequence_digest,
            "sequence_length": len(record.sequence),
        }
        for record in sorted(records, key=lambda item: item.sequence_id)
    ]
    return ParsedSequenceSet(
        records=tuple(records),
        input_digest=_sha256(raw),
        sequence_set_digest=_sha256(
            _canonical_json_bytes(
                {"record_count": len(canonical_records), "records": canonical_records}
            )
        ),
    )


def _parse_membership_identity(value: str, *, row: int) -> int:
    if not _IDENTITY_PATTERN.fullmatch(value):
        raise ScientificPrerequisiteError(
            "cdhit_membership_identity_invalid",
            "CD-HIT membership identity must be a fixed six-decimal fraction in [0, 1]",
            details={"row": row, "value": value},
        )
    whole, fraction = value.split(".", maxsplit=1)
    return int(whole) * PPM_SCALE + int(fraction)


def _membership_sort_key(row: CDHitMembershipRow) -> tuple[int, str]:
    cluster_number = int(row.cluster_id.removeprefix("cluster_"))
    return cluster_number, row.member_id


def parse_cdhit_membership_csv(data: str | bytes) -> ParsedCDHitMembership:
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScientificPrerequisiteError(
            "cdhit_membership_not_utf8",
            "the CD-HIT membership input is not valid UTF-8",
            details={"start": exc.start},
        ) from exc

    reader = csv.DictReader(io.StringIO(text, newline=""))
    actual_columns = tuple(reader.fieldnames or ())
    if actual_columns != MEMBERSHIP_COLUMNS:
        legacy_fields = {"representative", "member_count"}
        if legacy_fields.intersection(actual_columns):
            code = "legacy_cdhit_membership_schema"
            message = (
                "legacy representative-count CD-HIT output is not valid graph evidence"
            )
        else:
            code = "cdhit_membership_schema_mismatch"
            message = (
                "CD-HIT membership columns do not match cdhit_cluster_membership@1"
            )
        raise ScientificPrerequisiteError(
            code,
            message,
            details={
                "expected": list(MEMBERSHIP_COLUMNS),
                "actual": list(actual_columns),
            },
        )

    rows: list[CDHitMembershipRow] = []
    for row_number, raw_row in enumerate(reader, start=2):
        if None in raw_row:
            raise ScientificPrerequisiteError(
                "cdhit_membership_schema_mismatch",
                "a CD-HIT membership row contains unexpected CSV fields",
                details={"row": row_number},
            )
        row = {field: (raw_row[field] or "").strip() for field in MEMBERSHIP_COLUMNS}
        cluster_id = row["cluster_id"]
        if not _CLUSTER_ID_PATTERN.fullmatch(cluster_id):
            raise ScientificPrerequisiteError(
                "cdhit_cluster_id_invalid",
                "CD-HIT cluster ids must use canonical cluster_<integer> identity",
                details={"row": row_number, "cluster_id": cluster_id},
            )
        member_id = row["member_id"]
        representative_id = row["representative_id"]
        _validate_sequence_id(member_id, field="member_id", row=row_number)
        _validate_sequence_id(
            representative_id, field="representative_id", row=row_number
        )
        is_representative_value = row["is_representative"]
        if is_representative_value not in {"true", "false"}:
            raise ScientificPrerequisiteError(
                "cdhit_representative_flag_invalid",
                "CD-HIT membership representative flags must be literal true or false",
                details={"row": row_number, "value": is_representative_value},
            )
        length_value = row["member_length"]
        if (
            not length_value.isascii()
            or not length_value.isdigit()
            or int(length_value) <= 0
        ):
            raise ScientificPrerequisiteError(
                "cdhit_member_length_invalid",
                "CD-HIT membership lengths must be positive base-10 integers",
                details={"row": row_number, "value": length_value},
            )
        rows.append(
            CDHitMembershipRow(
                cluster_id=cluster_id,
                member_id=member_id,
                representative_id=representative_id,
                is_representative=is_representative_value == "true",
                identity_ppm=_parse_membership_identity(
                    row["identity_to_representative"], row=row_number
                ),
                member_length=int(length_value),
            )
        )

    member_ids = [row.member_id for row in rows]
    duplicate_members = sorted(
        member_id for member_id in set(member_ids) if member_ids.count(member_id) > 1
    )
    if duplicate_members:
        raise ScientificPrerequisiteError(
            "duplicate_cdhit_member_id",
            "each sequence must occur exactly once in CD-HIT membership output",
            details={"member_ids": duplicate_members},
        )

    clusters: dict[str, list[CDHitMembershipRow]] = {}
    for row in rows:
        clusters.setdefault(row.cluster_id, []).append(row)
    for cluster_id, cluster_rows in sorted(clusters.items()):
        representatives = [row for row in cluster_rows if row.is_representative]
        if len(representatives) != 1:
            raise ScientificPrerequisiteError(
                "cdhit_representative_missing_or_duplicate",
                "each CD-HIT cluster must have exactly one representative row",
                details={
                    "cluster_id": cluster_id,
                    "representative_count": len(representatives),
                },
            )
        representative = representatives[0]
        if (
            representative.representative_id != representative.member_id
            or representative.identity_ppm != PPM_SCALE
            or any(
                row.representative_id != representative.member_id
                for row in cluster_rows
            )
        ):
            raise ScientificPrerequisiteError(
                "cdhit_representative_identity_inconsistent",
                "CD-HIT membership rows do not bind consistently to their representative",
                details={
                    "cluster_id": cluster_id,
                    "representative_id": representative.member_id,
                },
            )

    canonical_rows = [row.to_row() for row in sorted(rows, key=_membership_sort_key)]
    return ParsedCDHitMembership(
        rows=tuple(rows),
        input_digest=_sha256(raw),
        membership_set_digest=_sha256(
            _canonical_json_bytes(
                {
                    "schema_id": MEMBERSHIP_SCHEMA_ID,
                    "row_count": len(canonical_rows),
                    "rows": canonical_rows,
                }
            )
        ),
    )


_AlignmentState = tuple[int, int, int]


def _choose_alignment_state(*states: _AlignmentState) -> _AlignmentState:
    best = states[0]
    for state in states[1:]:
        if (state[0], state[1], state[2]) > (best[0], best[1], best[2]):
            best = state
    return best


def _add_score(state: _AlignmentState, score: int) -> _AlignmentState:
    if state[0] == _NEGATIVE_INFINITY:
        return state
    return state[0] + score, state[1], state[2]


def _add_aligned_pair(
    state: _AlignmentState,
    *,
    score: int,
    matches: bool,
) -> _AlignmentState:
    if state[0] == _NEGATIVE_INFINITY:
        return state
    return state[0] + score, state[1] + int(matches), state[2] + 1


def _normalize_alignment_sequence(sequence: str, *, field: str) -> str:
    if not isinstance(sequence, str):
        raise ScientificPrerequisiteError(
            "similarity_sequence_invalid",
            "global sequence identity inputs must be strings",
            details={"field": field},
        )
    normalized = sequence.upper()
    if not normalized:
        raise ScientificPrerequisiteError(
            "similarity_sequence_empty",
            "global sequence identity inputs must not be empty",
            details={"field": field},
        )
    invalid = sorted(set(normalized) - set(BLOSUM62_ALPHABET[:-1]))
    if invalid:
        raise ScientificPrerequisiteError(
            "similarity_sequence_residue_unsupported",
            "global sequence identity inputs must use gap-free residues supported by BLOSUM62",
            details={"field": field, "invalid_characters": invalid},
        )
    return normalized


def calculate_global_sequence_identity(
    source_sequence: str,
    target_sequence: str,
) -> AlignmentIdentity:
    """Calculate deterministic global affine-gap identity without third parties.

    The dynamic program uses three Gotoh states and exact half-score integers.
    Only residue-residue columns contribute to the identity denominator, matching
    the user-authorized AOX reference calculation's ``nongap`` convention.
    """

    source = _normalize_alignment_sequence(source_sequence, field="source_sequence")
    target = _normalize_alignment_sequence(target_sequence, field="target_sequence")
    target_width = len(target)
    unreachable = (_NEGATIVE_INFINITY, 0, 0)

    match_previous: list[_AlignmentState] = [unreachable] * (target_width + 1)
    gap_target_previous: list[_AlignmentState] = [unreachable] * (target_width + 1)
    gap_source_previous: list[_AlignmentState] = [unreachable] * (target_width + 1)
    match_previous[0] = (0, 0, 0)
    for column in range(1, target_width + 1):
        gap_source_previous[column] = (
            GAP_OPEN_HALF_SCORE + (column - 1) * GAP_EXTEND_HALF_SCORE,
            0,
            0,
        )

    for row, source_residue in enumerate(source, start=1):
        match_current: list[_AlignmentState] = [unreachable] * (target_width + 1)
        gap_target_current: list[_AlignmentState] = [unreachable] * (target_width + 1)
        gap_source_current: list[_AlignmentState] = [unreachable] * (target_width + 1)
        gap_target_current[0] = (
            GAP_OPEN_HALF_SCORE + (row - 1) * GAP_EXTEND_HALF_SCORE,
            0,
            0,
        )

        for column, target_residue in enumerate(target, start=1):
            diagonal = _choose_alignment_state(
                match_previous[column - 1],
                gap_target_previous[column - 1],
                gap_source_previous[column - 1],
            )
            match_current[column] = _add_aligned_pair(
                diagonal,
                score=_BLOSUM62_HALF_SCORES[(source_residue, target_residue)],
                matches=source_residue == target_residue,
            )
            gap_target_current[column] = _choose_alignment_state(
                _add_score(gap_target_previous[column], GAP_EXTEND_HALF_SCORE),
                _add_score(match_previous[column], GAP_OPEN_HALF_SCORE),
            )
            gap_source_current[column] = _choose_alignment_state(
                _add_score(gap_source_current[column - 1], GAP_EXTEND_HALF_SCORE),
                _add_score(match_current[column - 1], GAP_OPEN_HALF_SCORE),
            )

        match_previous = match_current
        gap_target_previous = gap_target_current
        gap_source_previous = gap_source_current

    best = _choose_alignment_state(
        match_previous[target_width],
        gap_target_previous[target_width],
        gap_source_previous[target_width],
    )
    if best[0] == _NEGATIVE_INFINITY or best[2] <= 0:
        raise ScientificPrerequisiteError(
            "global_alignment_unresolved",
            "the global alignment did not contain a residue-residue column",
        )
    return AlignmentIdentity(
        alignment_score_half_units=best[0],
        identity_matches=best[1],
        identity_aligned_residues=best[2],
    )


def _verify_expected_input_digest(
    *, actual: str, expected: str | None, field: str, code: str
) -> None:
    if expected is None:
        return
    _validate_digest(expected, field=field)
    if actual != expected:
        raise ScientificPrerequisiteError(
            code,
            "an AOX similarity input does not match its expected byte digest",
            details={"field": field, "expected": expected, "actual": actual},
        )


def _bind_membership(
    sequences: ParsedSequenceSet,
    membership: ParsedCDHitMembership,
) -> tuple[GraphNode, ...]:
    records_by_id = {record.sequence_id: record for record in sequences.records}
    membership_by_id = {row.member_id: row for row in membership.rows}
    missing_membership = sorted(set(records_by_id) - set(membership_by_id))
    unknown_members = sorted(set(membership_by_id) - set(records_by_id))
    if missing_membership or unknown_members:
        raise ScientificPrerequisiteError(
            "candidate_membership_set_mismatch",
            "candidate FASTA and CD-HIT membership must describe exactly the same identifiers",
            details={
                "missing_membership": missing_membership,
                "unknown_members": unknown_members,
            },
        )

    for member_id, row in sorted(membership_by_id.items()):
        actual_length = len(records_by_id[member_id].sequence)
        if row.member_length != actual_length:
            raise ScientificPrerequisiteError(
                "cdhit_member_length_mismatch",
                "CD-HIT membership length does not match the bound candidate sequence",
                details={
                    "member_id": member_id,
                    "declared": row.member_length,
                    "actual": actual_length,
                },
            )

    return tuple(
        GraphNode(
            sequence=record,
            membership=membership_by_id[record.sequence_id],
            candidate_fasta_digest=sequences.input_digest,
            candidate_sequence_set_digest=sequences.sequence_set_digest,
            cdhit_membership_digest=membership.input_digest,
            cdhit_membership_set_digest=membership.membership_set_digest,
        )
        for record in sorted(sequences.records, key=lambda item: item.sequence_id)
    )


def build_similarity_graph(
    candidate_fasta: str | bytes,
    membership_csv: str | bytes,
    *,
    threshold_ppm: int = DEFAULT_THRESHOLD_PPM,
    empty_result_reason: str | None = None,
    expected_calculation_id: str = CALCULATION_ID,
    expected_calculation_digest: str | None = None,
    expected_implementation_digest: str | None = None,
    expected_candidate_fasta_digest: str | None = None,
    expected_membership_digest: str | None = None,
) -> SimilarityGraphResult:
    verify_calculation(
        expected_calculation_id=expected_calculation_id,
        expected_calculation_digest=expected_calculation_digest,
        expected_implementation_digest=expected_implementation_digest,
    )
    _validate_threshold(threshold_ppm)
    sequences = parse_candidate_fasta(candidate_fasta)
    membership = parse_cdhit_membership_csv(membership_csv)
    _verify_expected_input_digest(
        actual=sequences.input_digest,
        expected=expected_candidate_fasta_digest,
        field="candidate_fasta_digest",
        code="candidate_fasta_digest_mismatch",
    )
    _verify_expected_input_digest(
        actual=membership.input_digest,
        expected=expected_membership_digest,
        field="cdhit_membership_digest",
        code="cdhit_membership_digest_mismatch",
    )
    nodes = _bind_membership(sequences, membership)

    normalized_reason = (
        empty_result_reason.strip() if isinstance(empty_result_reason, str) else None
    )
    if not nodes and not normalized_reason:
        raise ScientificPrerequisiteError(
            "empty_graph_reason_missing",
            "an empty candidate graph requires an explicit scientific empty-result reason",
        )
    if not nodes and (
        len(normalized_reason) > 128
        or not re.fullmatch(r"[a-z][a-z0-9_]*", normalized_reason)
    ):
        raise ScientificPrerequisiteError(
            "empty_graph_reason_invalid",
            "the empty-result reason must be a stable lowercase reason code",
            details={"reason": normalized_reason},
        )
    if nodes and empty_result_reason is not None:
        raise ScientificPrerequisiteError(
            "empty_graph_reason_unexpected",
            "a non-empty candidate graph may not carry an empty-result reason",
        )

    edges: list[GraphEdge] = []
    for left_index, source in enumerate(nodes):
        for target in nodes[left_index + 1 :]:
            identity = calculate_global_sequence_identity(
                source.sequence.sequence,
                target.sequence.sequence,
            )
            if identity.passes_threshold(threshold_ppm):
                edges.append(
                    GraphEdge(
                        source=source,
                        target=target,
                        identity=identity,
                        threshold_ppm=threshold_ppm,
                    )
                )

    return SimilarityGraphResult(
        sequences=sequences,
        membership=membership,
        nodes=nodes,
        edges=tuple(edges),
        threshold_ppm=threshold_ppm,
        empty_result_reason=normalized_reason,
    )


def _rows_to_csv(columns: Sequence[str], rows: Sequence[Mapping[str, object]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=list(columns),
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        serialized = dict(row)
        for field, value in tuple(serialized.items()):
            if isinstance(value, bool):
                serialized[field] = "true" if value else "false"
        writer.writerow(serialized)
    return output.getvalue()


def _artifact_bytes(data: str | bytes) -> bytes:
    return data.encode("utf-8") if isinstance(data, str) else bytes(data)


def _parse_graph_csv(
    data: str | bytes,
    *,
    expected_columns: Sequence[str],
    artifact: str,
) -> tuple[bytes, list[dict[str, str]]]:
    raw = _artifact_bytes(data)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScientificPrerequisiteError(
            f"graph_{artifact}_not_utf8",
            f"the canonical graph {artifact} artifact is not valid UTF-8",
            details={"start": exc.start},
        ) from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    actual_columns = tuple(reader.fieldnames or ())
    expected = tuple(expected_columns)
    legacy = (
        bool(_LEGACY_NODE_FIELDS.intersection(actual_columns))
        if artifact == "nodes"
        else bool(_LEGACY_EDGE_FIELDS.intersection(actual_columns))
        or actual_columns == ("source", "target", "similarity")
    )
    if actual_columns != expected:
        raise ScientificPrerequisiteError(
            "legacy_graph_schema" if legacy else f"graph_{artifact}_schema_mismatch",
            (
                "legacy graph artifacts are not cutover-valid similarity evidence"
                if legacy
                else f"canonical graph {artifact} columns do not match the versioned schema"
            ),
            details={"expected": list(expected), "actual": list(actual_columns)},
        )
    rows: list[dict[str, str]] = []
    for row_number, raw_row in enumerate(reader, start=2):
        if None in raw_row or any(raw_row[column] is None for column in expected):
            raise ScientificPrerequisiteError(
                f"graph_{artifact}_schema_mismatch",
                f"a canonical graph {artifact} row contains malformed CSV fields",
                details={"row": row_number},
            )
        rows.append({column: str(raw_row[column]) for column in expected})
    return raw, rows


def _compare_graph_rows(
    *,
    artifact: str,
    actual: Sequence[Mapping[str, str]],
    expected: Sequence[Mapping[str, str]],
) -> None:
    if len(actual) != len(expected):
        raise ScientificPrerequisiteError(
            f"graph_{artifact}_row_count_mismatch",
            f"canonical graph {artifact} row count does not match recomputation",
            details={"expected": len(expected), "actual": len(actual)},
        )
    for index, (actual_row, expected_row) in enumerate(
        zip(actual, expected, strict=True), start=2
    ):
        for field in expected_row:
            if actual_row[field] != expected_row[field]:
                identity = {
                    key: actual_row.get(key, "")
                    for key in ("node_id", "source", "target")
                    if key in actual_row
                }
                raise ScientificPrerequisiteError(
                    (
                        "graph_node_binding_mismatch"
                        if artifact == "nodes"
                        else "graph_edge_recalculation_mismatch"
                    ),
                    f"canonical graph {artifact} does not match real sequence and membership recomputation",
                    details={
                        "row": index,
                        "field": field,
                        "expected": expected_row[field],
                        "actual": actual_row[field],
                        **identity,
                    },
                )


def _strict_json_object(data: bytes) -> dict[str, object]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScientificPrerequisiteError(
            "graph_manifest_not_utf8",
            "the graph manifest is not valid UTF-8",
            details={"start": exc.start},
        ) from exc

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key: {key}")
            result[key] = value
        return result

    try:
        payload = json.loads(text, object_pairs_hook=reject_duplicates)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ScientificPrerequisiteError(
            "graph_manifest_invalid",
            "the graph manifest is not canonical schema-valid JSON",
        ) from exc
    if not isinstance(payload, dict):
        raise ScientificPrerequisiteError(
            "graph_manifest_invalid",
            "the graph manifest must be a JSON object",
        )
    return payload


def validate_graph_artifacts(
    candidate_fasta: str | bytes,
    membership_csv: str | bytes,
    nodes_csv: str | bytes,
    edges_csv: str | bytes,
    manifest_json: str | bytes,
    *,
    threshold_ppm: int = DEFAULT_THRESHOLD_PPM,
    empty_result_reason: str | None = None,
    expected_calculation_id: str = CALCULATION_ID,
    expected_calculation_digest: str | None = None,
    expected_implementation_digest: str | None = None,
    expected_candidate_fasta_digest: str | None = None,
    expected_membership_digest: str | None = None,
) -> SimilarityGraphResult:
    expected_result = build_similarity_graph(
        candidate_fasta,
        membership_csv,
        threshold_ppm=threshold_ppm,
        empty_result_reason=empty_result_reason,
        expected_calculation_id=expected_calculation_id,
        expected_calculation_digest=expected_calculation_digest,
        expected_implementation_digest=expected_implementation_digest,
        expected_candidate_fasta_digest=expected_candidate_fasta_digest,
        expected_membership_digest=expected_membership_digest,
    )

    actual_nodes_bytes, actual_nodes = _parse_graph_csv(
        nodes_csv,
        expected_columns=NODE_COLUMNS,
        artifact="nodes",
    )
    actual_edges_bytes, actual_edges = _parse_graph_csv(
        edges_csv,
        expected_columns=EDGE_COLUMNS,
        artifact="edges",
    )
    expected_nodes_bytes, expected_nodes = _parse_graph_csv(
        expected_result.nodes_csv(),
        expected_columns=NODE_COLUMNS,
        artifact="nodes",
    )
    expected_edges_bytes, expected_edges = _parse_graph_csv(
        expected_result.edges_csv(),
        expected_columns=EDGE_COLUMNS,
        artifact="edges",
    )
    _compare_graph_rows(artifact="nodes", actual=actual_nodes, expected=expected_nodes)
    _compare_graph_rows(artifact="edges", actual=actual_edges, expected=expected_edges)
    if actual_nodes_bytes != expected_nodes_bytes:
        raise ScientificPrerequisiteError(
            "graph_nodes_not_canonical",
            "graph node bytes are semantically valid but not canonical",
        )
    if actual_edges_bytes != expected_edges_bytes:
        raise ScientificPrerequisiteError(
            "graph_edges_not_canonical",
            "graph edge bytes are semantically valid but not canonical",
        )

    actual_manifest_bytes = _artifact_bytes(manifest_json)
    actual_manifest = _strict_json_object(actual_manifest_bytes)
    expected_manifest = expected_result.manifest()
    if set(actual_manifest) != set(expected_manifest):
        raise ScientificPrerequisiteError(
            "graph_manifest_schema_mismatch",
            "graph manifest fields do not match the versioned schema",
            details={
                "missing": sorted(set(expected_manifest) - set(actual_manifest)),
                "unexpected": sorted(set(actual_manifest) - set(expected_manifest)),
            },
        )
    for field, expected_value in expected_manifest.items():
        if actual_manifest[field] != expected_value:
            raise ScientificPrerequisiteError(
                "graph_manifest_recalculation_mismatch",
                "graph manifest does not match the recomputed graph closure",
                details={
                    "field": field,
                    "expected": expected_value,
                    "actual": actual_manifest[field],
                },
            )
    expected_manifest_bytes = expected_result.manifest_json().encode("utf-8")
    if actual_manifest_bytes != expected_manifest_bytes:
        raise ScientificPrerequisiteError(
            "graph_manifest_not_canonical",
            "graph manifest bytes are semantically valid but not canonical",
        )
    return expected_result


IMPLEMENTATION_DIGEST = implementation_digest()
CALCULATION_DIGEST = calculation_digest(
    implementation_digest_value=IMPLEMENTATION_DIGEST
)


__all__ = [
    "BLOSUM62_ALPHABET",
    "BLOSUM62_ID",
    "CALCULATION_DIGEST",
    "CALCULATION_ID",
    "DEFAULT_THRESHOLD_PPM",
    "EDGE_COLUMNS",
    "EDGE_SCHEMA_ID",
    "GAP_EXTEND_HALF_SCORE",
    "GAP_OPEN_HALF_SCORE",
    "IDENTITY_DENOMINATOR",
    "IMPLEMENTATION_DIGEST",
    "MANIFEST_SCHEMA_ID",
    "MEMBERSHIP_COLUMNS",
    "MEMBERSHIP_SCHEMA_ID",
    "NODE_COLUMNS",
    "NODE_SCHEMA_ID",
    "PPM_SCALE",
    "TIE_BREAK_POLICY",
    "AlignmentIdentity",
    "CDHitMembershipRow",
    "GraphEdge",
    "GraphNode",
    "ParsedCDHitMembership",
    "ParsedSequenceSet",
    "SequenceRecord",
    "SimilarityGraphResult",
    "build_similarity_graph",
    "calculate_global_sequence_identity",
    "calculation_digest",
    "calculation_metadata",
    "calculation_payload",
    "implementation_digest",
    "matrix_digest",
    "parse_candidate_fasta",
    "parse_cdhit_membership_csv",
    "validate_graph_artifacts",
    "verify_calculation",
]
