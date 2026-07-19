from __future__ import annotations

import csv
import hashlib
import importlib
import io
import json
import math
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .aox_motif import ScientificPrerequisiteError


CALCULATION_ID = "aox_global_sequence_identity@1"
MEMBERSHIP_SCHEMA_ID = "cdhit_cluster_membership@1"
NODE_SCHEMA_ID = "aox_candidate_graph_nodes@1"
EDGE_SCHEMA_ID = "aox_candidate_graph_edges@1"
MANIFEST_SCHEMA_ID = "aox_candidate_similarity_graph_manifest@1"
DEFAULT_THRESHOLD_PPM = 850_000
PPM_SCALE = 1_000_000
MAX_ALIGNMENT_WORKERS = 16
PARALLEL_PAIR_THRESHOLD = 128
PARALLEL_PAIR_CHUNK_SIZE = 64
ALIGNMENT_BACKEND_ID = "biopython_trace_guarded_numpy_gotoh@1"
ALIGNMENT_CORRECTION_ID = "numpy_three_state_gap_switch_correction@1"
BIOPYTHON_VERSION = "1.87"
NUMPY_VERSION = "2.4.4"
ALIGNMENT_BACKEND_ALGORITHM = "Gotoh global alignment algorithm"
ALIGNMENT_BACKEND_EPSILON = 1e-6
MAX_EXACT_FLOAT_INTEGER = 1 << 53
NUMPY_NEGATIVE_INFINITY = -(1 << 60)
ALIGNMENT_STATE_ENCODING = (
    "exact_mixed_radix_score_matches_aligned_residues_in_binary64_integer"
)

_CGROUP_V2_CPU_MAX_PATH = Path("/sys/fs/cgroup/cpu.max")
_CGROUP_V1_CPU_PATHS = (
    (
        Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"),
        Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us"),
    ),
    (
        Path("/sys/fs/cgroup/cpu,cpuacct/cpu.cfs_quota_us"),
        Path("/sys/fs/cgroup/cpu,cpuacct/cpu.cfs_period_us"),
    ),
)

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
_BLOSUM62_HALF_SCORE_VECTOR = tuple(
    _BLOSUM62_HALF_SCORES[(source, target)]
    for source in BLOSUM62_ALPHABET
    for target in BLOSUM62_ALPHABET
)
_BLOSUM62_WIDTH = len(BLOSUM62_ALPHABET)
_MAX_ABS_ALIGNMENT_TRANSITION = max(
    abs(GAP_OPEN_HALF_SCORE),
    abs(GAP_EXTEND_HALF_SCORE),
    *(abs(score) for score in _BLOSUM62_HALF_SCORE_VECTOR),
)


@dataclass(frozen=True, slots=True)
class _AlignmentBackend:
    bio_version: str
    numpy_version: str
    align_module: Any
    substitution_matrices_module: Any
    numpy_module: Any


_ALIGNMENT_WORKER_SEQUENCES: tuple[bytes, ...] | None = None
_ALIGNMENT_WORKER_THRESHOLD_PPM: int | None = None
_ALIGNMENT_BACKEND: _AlignmentBackend | None = None
_PACKED_ALIGNER_CACHE: dict[int, Any] = {}


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
            "input_normalization": {
                "encoding": "ASCII",
                "case": "uppercase_after_ascii_validation",
                "whitespace": "forbidden",
                "gaps_and_stops": "forbidden",
                "physical_lines": (
                    "split_on_lf_and_remove_one_immediately_preceding_cr_only_"
                    "from_lf_terminated_lines"
                ),
                "header_start": "raw_column_zero_greater_than",
                "bare_header_carriage_return": "forbidden",
            },
            "backend": {
                "backend_id": ALIGNMENT_BACKEND_ID,
                "api": (
                    "Bio.Align.PairwiseAligner.score+align()[0].coordinates"
                ),
                "biopython_version": BIOPYTHON_VERSION,
                "numpy_version": NUMPY_VERSION,
                "algorithm": ALIGNMENT_BACKEND_ALGORITHM,
                "import_policy": "lazy_on_first_alignment",
                "fallback_policy": "forbidden",
                "sequence_transport": "ASCII_bytes",
                "numeric_transport": "IEEE_754_binary64_exact_integer",
                "max_exact_integer_exclusive": MAX_EXACT_FLOAT_INTEGER,
                "integrality_epsilon": "0.000001",
                "trace_validation": (
                    "first_optimal_coordinates_reject_adjacent_opposite_gap_states"
                ),
                "gap_state_switch_correction": {
                    "correction_id": ALIGNMENT_CORRECTION_ID,
                    "backend": "NumPy_int64_row_vectorized_exact_three_state",
                    "activation": "adjacent_horizontal_vertical_gap_switch",
                    "unreachable_sentinel": NUMPY_NEGATIVE_INFINITY,
                    "exception_policy": (
                        "fail_closed_without_correction_or_fallback"
                    ),
                    "fallback": "forbidden",
                },
            },
        },
        "execution": {
            "state_encoding": ALIGNMENT_STATE_ENCODING,
            "pair_order": "lexicographic_sequence_id_order",
            "parallelism": "bounded_process_pool_output_order_preserving",
            "max_worker_processes": MAX_ALIGNMENT_WORKERS,
            "parallel_pair_threshold": PARALLEL_PAIR_THRESHOLD,
            "parallel_pair_chunk_size": PARALLEL_PAIR_CHUNK_SIZE,
            "worker_limit_rule": (
                "minimum_of_pair_count_hard_max_affinity_and_available_"
                "cgroup_v2_or_v1_quota_ceil"
            ),
            "worker_limit_sources": [
                "os.sched_getaffinity",
                "os.cpu_count_when_affinity_unavailable",
                "/sys/fs/cgroup/cpu.max",
                "/sys/fs/cgroup/cpu/cpu.cfs_quota_us",
                "/sys/fs/cgroup/cpu/cpu.cfs_period_us",
                "/sys/fs/cgroup/cpu,cpuacct/cpu.cfs_quota_us",
                "/sys/fs/cgroup/cpu,cpuacct/cpu.cfs_period_us",
            ],
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
        "alignment_state_encoding": ALIGNMENT_STATE_ENCODING,
        "alignment_backend_id": ALIGNMENT_BACKEND_ID,
        "alignment_backend_api": (
            "Bio.Align.PairwiseAligner.score+align()[0].coordinates"
        ),
        "alignment_backend_algorithm": ALIGNMENT_BACKEND_ALGORITHM,
        "alignment_backend_biopython_version": BIOPYTHON_VERSION,
        "alignment_backend_numpy_version": NUMPY_VERSION,
        "alignment_backend_epsilon": "0.000001",
        "alignment_backend_max_exact_integer_exclusive": (
            MAX_EXACT_FLOAT_INTEGER
        ),
        "alignment_backend_fallback_policy": "forbidden",
        "alignment_gap_switch_correction_id": ALIGNMENT_CORRECTION_ID,
        "alignment_sequence_transport": "ASCII_bytes",
        "max_alignment_workers": MAX_ALIGNMENT_WORKERS,
        "alignment_worker_limit_rule": (
            "minimum_of_pair_count_hard_max_affinity_and_available_"
            "cgroup_v2_or_v1_quota_ceil"
        ),
    }


def verify_calculation(
    *,
    expected_calculation_id: str = CALCULATION_ID,
    expected_calculation_digest: str | None = None,
    expected_implementation_digest: str | None = None,
) -> None:
    expected = {
        "calculation_id": expected_calculation_id,
        "calculation_digest": (
            CALCULATION_DIGEST
            if expected_calculation_digest is None
            else expected_calculation_digest
        ),
        "implementation_digest": (
            IMPLEMENTATION_DIGEST
            if expected_implementation_digest is None
            else expected_implementation_digest
        ),
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
        sequence = "".join(fragments)
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

    raw_lines = text.split("\n")
    for line_number, raw_line_with_ending in enumerate(raw_lines, start=1):
        line_has_lf_ending = line_number < len(raw_lines)
        raw_line = (
            raw_line_with_ending[:-1]
            if line_has_lf_ending and raw_line_with_ending.endswith("\r")
            else raw_line_with_ending
        )
        if raw_line == "":
            continue
        if raw_line.startswith(">"):
            if "\r" in raw_line:
                raise ScientificPrerequisiteError(
                    "candidate_fasta_header_carriage_return",
                    "candidate FASTA headers may not contain a bare carriage return",
                    details={"line": line_number},
                )
            finish_record()
            header = raw_line[1:].strip()
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
        if any(character.isspace() for character in raw_line):
            raise ScientificPrerequisiteError(
                "whitespace_in_candidate_sequence",
                "candidate FASTA sequence lines may not contain leading, trailing, or internal whitespace",
                details={"line": line_number},
            )
        if not raw_line.isascii():
            raise ScientificPrerequisiteError(
                "candidate_residue_unsupported",
                "candidate sequences must be raw ASCII before case normalization",
                details={"line": line_number},
            )
        normalized_line = raw_line.upper()
        invalid = sorted(set(normalized_line) - set(BLOSUM62_ALPHABET[:-1]))
        if invalid:
            raise ScientificPrerequisiteError(
                "candidate_residue_unsupported",
                "candidate sequences must use residues supported by BLOSUM62 and may not contain gaps or stops",
                details={"line": line_number, "invalid_characters": invalid},
            )
        fragments.append(normalized_line)
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


def _normalize_alignment_sequence(sequence: str, *, field: str) -> str:
    if not isinstance(sequence, str):
        raise ScientificPrerequisiteError(
            "similarity_sequence_invalid",
            "global sequence identity inputs must be strings",
            details={"field": field},
        )
    if not sequence:
        raise ScientificPrerequisiteError(
            "similarity_sequence_empty",
            "global sequence identity inputs must not be empty",
            details={"field": field},
        )
    if not sequence.isascii():
        raise ScientificPrerequisiteError(
            "similarity_sequence_residue_unsupported",
            "global sequence identity inputs must be raw ASCII before case normalization",
            details={"field": field},
        )
    normalized = sequence.upper()
    invalid = sorted(set(normalized) - set(BLOSUM62_ALPHABET[:-1]))
    if invalid:
        raise ScientificPrerequisiteError(
            "similarity_sequence_residue_unsupported",
            "global sequence identity inputs must use gap-free residues supported by BLOSUM62",
            details={"field": field, "invalid_characters": invalid},
        )
    return normalized


def _encode_alignment_sequence(sequence: str, *, field: str) -> bytes:
    normalized = _normalize_alignment_sequence(sequence, field=field)
    return normalized.encode("ascii")


def _load_alignment_backend() -> _AlignmentBackend:
    try:
        bio_module = importlib.import_module("Bio")
        numpy_module = importlib.import_module("numpy")
        align_module = importlib.import_module("Bio.Align")
        substitution_matrices_module = importlib.import_module(
            "Bio.Align.substitution_matrices"
        )
    except Exception as exc:
        raise ScientificPrerequisiteError(
            "similarity_backend_unavailable",
            "the exact AOX similarity backend could not be imported",
            details={"failure_type": type(exc).__name__},
        ) from exc

    actual_versions = {
        "biopython": str(getattr(bio_module, "__version__", "")),
        "numpy": str(getattr(numpy_module, "__version__", "")),
    }
    expected_versions = {
        "biopython": BIOPYTHON_VERSION,
        "numpy": NUMPY_VERSION,
    }
    if actual_versions != expected_versions:
        raise ScientificPrerequisiteError(
            "similarity_backend_version_mismatch",
            "the exact AOX similarity backend versions do not match the calculation contract",
            details={"expected": expected_versions, "actual": actual_versions},
        )

    backend = _AlignmentBackend(
        bio_version=actual_versions["biopython"],
        numpy_version=actual_versions["numpy"],
        align_module=align_module,
        substitution_matrices_module=substitution_matrices_module,
        numpy_module=numpy_module,
    )
    _preflight_alignment_backend(backend)
    return backend


def _ensure_alignment_backend() -> _AlignmentBackend:
    global _ALIGNMENT_BACKEND
    if _ALIGNMENT_BACKEND is None:
        _ALIGNMENT_BACKEND = _load_alignment_backend()
    return _ALIGNMENT_BACKEND


def _packed_substitution_values(radix: int) -> list[int]:
    score_unit = radix * radix
    return [
        score * score_unit
        + (radix if source_index == target_index else 0)
        + 1
        for source_index in range(_BLOSUM62_WIDTH)
        for target_index, score in enumerate(
            _BLOSUM62_HALF_SCORE_VECTOR[
                source_index
                * _BLOSUM62_WIDTH : (source_index + 1)
                * _BLOSUM62_WIDTH
            ]
        )
    ]


def _new_packed_aligner(radix: int, backend: _AlignmentBackend) -> Any:
    score_unit = radix * radix
    matrix_values = _packed_substitution_values(radix)
    try:
        matrix_data = backend.numpy_module.asarray(
            matrix_values,
            dtype=backend.numpy_module.float64,
        ).reshape((_BLOSUM62_WIDTH, _BLOSUM62_WIDTH))
        matrix = backend.substitution_matrices_module.Array(
            alphabet="".join(BLOSUM62_ALPHABET),
            dims=2,
            data=matrix_data,
        )
        aligner = backend.align_module.PairwiseAligner()
        aligner.mode = "global"
        aligner.substitution_matrix = matrix
        aligner.open_gap_score = GAP_OPEN_HALF_SCORE * score_unit
        aligner.extend_gap_score = GAP_EXTEND_HALF_SCORE * score_unit
        aligner.epsilon = ALIGNMENT_BACKEND_EPSILON
    except Exception as exc:
        raise ScientificPrerequisiteError(
            "similarity_backend_configuration_failed",
            "the exact AOX similarity backend could not be configured",
            details={"failure_type": type(exc).__name__},
        ) from exc
    if aligner.algorithm != ALIGNMENT_BACKEND_ALGORITHM:
        raise ScientificPrerequisiteError(
            "similarity_backend_algorithm_mismatch",
            "the configured AOX similarity backend selected an unexpected alignment algorithm",
            details={
                "expected": ALIGNMENT_BACKEND_ALGORITHM,
                "actual": str(aligner.algorithm),
            },
        )
    return aligner


def _packed_score_bound(source_length: int, target_length: int) -> int:
    radix = max(source_length, target_length) + 1
    score_unit = radix * radix
    transition_bound = (
        _MAX_ABS_ALIGNMENT_TRANSITION * score_unit + radix + 1
    )
    return (source_length + target_length) * transition_bound


def _require_exact_float_bound(source_length: int, target_length: int) -> int:
    bound = _packed_score_bound(source_length, target_length)
    if bound >= MAX_EXACT_FLOAT_INTEGER:
        raise ScientificPrerequisiteError(
            "similarity_backend_numeric_bound_exceeded",
            "the packed AOX alignment could exceed exact binary64 integer range",
            details={
                "source_length": source_length,
                "target_length": target_length,
                "packed_absolute_bound": bound,
                "required_exclusive_upper_bound": MAX_EXACT_FLOAT_INTEGER,
            },
        )
    return bound


def _integral_packed_score(score: object, *, bound: int) -> int:
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ScientificPrerequisiteError(
            "similarity_backend_score_nonintegral",
            "the exact AOX similarity backend returned a non-numeric score",
            details={"score_type": type(score).__name__},
        )
    numeric_score = float(score)
    if not math.isfinite(numeric_score):
        raise ScientificPrerequisiteError(
            "similarity_backend_score_nonfinite",
            "the exact AOX similarity backend returned a non-finite score",
        )
    packed_score = round(numeric_score)
    if abs(numeric_score - packed_score) > ALIGNMENT_BACKEND_EPSILON:
        raise ScientificPrerequisiteError(
            "similarity_backend_score_nonintegral",
            "the exact AOX similarity backend returned a non-integral packed score",
            details={"score": numeric_score},
        )
    if abs(packed_score) > bound or abs(packed_score) >= MAX_EXACT_FLOAT_INTEGER:
        raise ScientificPrerequisiteError(
            "similarity_backend_score_out_of_bound",
            "the exact AOX similarity backend returned a score outside its proven numeric bound",
            details={"score": packed_score, "packed_absolute_bound": bound},
        )
    return packed_score


def _preflight_alignment_backend(backend: _AlignmentBackend) -> None:
    try:
        float_info = backend.numpy_module.finfo(backend.numpy_module.float64)
        numeric_ok = (
            int(float_info.nmant) == 52
            and int(backend.numpy_module.dtype(backend.numpy_module.float64).itemsize)
            == 8
        )
    except Exception as exc:
        raise ScientificPrerequisiteError(
            "similarity_backend_numeric_incompatible",
            "the AOX similarity backend numeric representation could not be verified",
            details={"failure_type": type(exc).__name__},
        ) from exc
    if not numeric_ok:
        raise ScientificPrerequisiteError(
            "similarity_backend_numeric_incompatible",
            "the AOX similarity backend requires IEEE-754 binary64 semantics",
        )

    aligner = _new_packed_aligner(5, backend)
    expected_scores = (
        (b"ARND", b"ARND", 1_074),
        (b"AAAA", b"AAA", 118),
    )
    for source, target, expected in expected_scores:
        bound = _require_exact_float_bound(len(source), len(target))
        try:
            observed = aligner.score(source, target)
        except Exception as exc:
            raise ScientificPrerequisiteError(
                "similarity_backend_preflight_failed",
                "the exact AOX similarity backend failed its parent-process score preflight",
                details={"failure_type": type(exc).__name__},
            ) from exc
        actual = _integral_packed_score(observed, bound=bound)
        if actual != expected:
            raise ScientificPrerequisiteError(
                "similarity_backend_preflight_failed",
                "the exact AOX similarity backend failed its parent-process numeric preflight",
                details={"expected": expected, "actual": actual},
            )
        if _alignment_has_opposite_gap_switch(
            aligner,
            source,
            target,
            packed_score=actual,
            bound=bound,
        ):
            raise ScientificPrerequisiteError(
                "similarity_backend_preflight_failed",
                "the exact AOX similarity backend produced an unexpected preflight gap switch",
            )


def _packed_aligner(radix: int) -> Any:
    aligner = _PACKED_ALIGNER_CACHE.get(radix)
    if aligner is None:
        aligner = _new_packed_aligner(radix, _ensure_alignment_backend())
        _PACKED_ALIGNER_CACHE[radix] = aligner
    return aligner


def _inspect_alignment_for_opposite_gap_switch(
    aligner: Any,
    source: bytes,
    target: bytes,
    *,
    packed_score: int,
    bound: int,
) -> bool:
    try:
        alignment = aligner.align(source, target)[0]
    except Exception as exc:
        raise ScientificPrerequisiteError(
            "similarity_backend_trace_failed",
            "the exact AOX similarity backend failed closed while tracing its optimum",
            details={"failure_type": type(exc).__name__},
        ) from exc
    traced_score = _integral_packed_score(alignment.score, bound=bound)
    if traced_score != packed_score:
        raise ScientificPrerequisiteError(
            "similarity_backend_trace_score_mismatch",
            "the AOX similarity score and first optimal traceback disagree",
            details={"score": packed_score, "trace_score": traced_score},
        )
    coordinates = alignment.coordinates
    if (
        getattr(coordinates, "ndim", None) != 2
        or tuple(coordinates.shape)[0] != 2
        or tuple(coordinates.shape)[1] < 2
        or (int(coordinates[0, 0]), int(coordinates[1, 0])) != (0, 0)
        or (int(coordinates[0, -1]), int(coordinates[1, -1]))
        != (len(source), len(target))
    ):
        raise ScientificPrerequisiteError(
            "similarity_backend_trace_postcondition_failed",
            "the AOX similarity traceback coordinates are malformed",
        )

    previous_gap_state: int | None = None
    for index in range(tuple(coordinates.shape)[1] - 1):
        source_advance = int(coordinates[0, index + 1] - coordinates[0, index])
        target_advance = int(coordinates[1, index + 1] - coordinates[1, index])
        if source_advance < 0 or target_advance < 0 or not (
            source_advance or target_advance
        ):
            raise ScientificPrerequisiteError(
                "similarity_backend_trace_postcondition_failed",
                "the AOX similarity traceback contains an invalid transition",
            )
        if source_advance and target_advance:
            if source_advance != target_advance:
                raise ScientificPrerequisiteError(
                    "similarity_backend_trace_postcondition_failed",
                    "the AOX similarity traceback contains a non-unit-ratio diagonal",
                )
            previous_gap_state = None
            continue
        gap_state = 1 if source_advance else 2
        if previous_gap_state is not None and previous_gap_state != gap_state:
            return True
        previous_gap_state = gap_state
    return False


def _alignment_has_opposite_gap_switch(
    aligner: Any,
    source: bytes,
    target: bytes,
    *,
    packed_score: int,
    bound: int,
) -> bool:
    try:
        return _inspect_alignment_for_opposite_gap_switch(
            aligner,
            source,
            target,
            packed_score=packed_score,
            bound=bound,
        )
    except ScientificPrerequisiteError:
        raise
    except Exception as exc:
        raise ScientificPrerequisiteError(
            "similarity_backend_trace_failed",
            "the exact AOX similarity backend traceback could not be inspected",
            details={"failure_type": type(exc).__name__},
        ) from exc


def _run_numpy_three_state_correction(
    source: bytes,
    target: bytes,
    *,
    bound: int,
) -> AlignmentIdentity:
    backend = _ensure_alignment_backend()
    numpy = backend.numpy_module
    source_length = len(source)
    target_length = len(target)
    radix = max(source_length, target_length) + 1
    score_unit = radix * radix
    gap_open_delta = GAP_OPEN_HALF_SCORE * score_unit
    gap_extend_delta = GAP_EXTEND_HALF_SCORE * score_unit
    # Every reachable path has absolute packed score < 2**53.  Even after the
    # largest permitted cumulative transition, -2**60 remains below every
    # reachable state while staying safely inside signed int64.
    negative_infinity = NUMPY_NEGATIVE_INFINITY
    residue_indexes = {
        residue: index
        for index, residue in enumerate("".join(BLOSUM62_ALPHABET).encode("ascii"))
    }
    source_indexes = numpy.asarray(
        [residue_indexes[residue] for residue in source], dtype=numpy.intp
    )
    target_indexes = numpy.asarray(
        [residue_indexes[residue] for residue in target], dtype=numpy.intp
    )
    substitution = numpy.asarray(
        _packed_substitution_values(radix), dtype=numpy.int64
    ).reshape((_BLOSUM62_WIDTH, _BLOSUM62_WIDTH))
    match_previous = numpy.full(
        target_length + 1, negative_infinity, dtype=numpy.int64
    )
    gap_target_previous = numpy.full_like(match_previous, negative_infinity)
    gap_source_previous = numpy.full_like(match_previous, negative_infinity)
    match_current = numpy.full_like(match_previous, negative_infinity)
    gap_target_current = numpy.full_like(match_previous, negative_infinity)
    gap_source_current = numpy.full_like(match_previous, negative_infinity)
    match_previous[0] = 0
    if target_length:
        gap_source_previous[1:] = gap_open_delta + numpy.arange(
            target_length, dtype=numpy.int64
        ) * gap_extend_delta
    horizontal_offsets = numpy.arange(target_length, dtype=numpy.int64)

    for row_index, source_index in enumerate(source_indexes, start=1):
        match_current[0] = negative_infinity
        gap_target_current[0] = gap_open_delta + (
            row_index - 1
        ) * gap_extend_delta
        gap_source_current[0] = negative_infinity
        diagonal = numpy.maximum(
            numpy.maximum(match_previous[:-1], gap_target_previous[:-1]),
            gap_source_previous[:-1],
        )
        match_current[1:] = (
            diagonal + substitution[source_index, target_indexes]
        )
        gap_target_current[1:] = numpy.maximum(
            gap_target_previous[1:] + gap_extend_delta,
            match_previous[1:] + gap_open_delta,
        )
        horizontal_prefix = numpy.maximum.accumulate(
            match_current[:-1] - horizontal_offsets * gap_extend_delta
        )
        gap_source_current[1:] = (
            horizontal_prefix
            + gap_open_delta
            + horizontal_offsets * gap_extend_delta
        )
        match_previous, match_current = match_current, match_previous
        gap_target_previous, gap_target_current = (
            gap_target_current,
            gap_target_previous,
        )
        gap_source_previous, gap_source_current = (
            gap_source_current,
            gap_source_previous,
        )

    packed_score = int(
        max(
            match_previous[target_length],
            gap_target_previous[target_length],
            gap_source_previous[target_length],
        )
    )
    packed_score = _integral_packed_score(packed_score, bound=bound)
    return _decode_packed_identity(
        packed_score,
        source_length=source_length,
        target_length=target_length,
    )


def _calculate_numpy_three_state_correction(
    source: bytes,
    target: bytes,
    *,
    bound: int,
) -> AlignmentIdentity:
    try:
        return _run_numpy_three_state_correction(source, target, bound=bound)
    except ScientificPrerequisiteError:
        raise
    except Exception as exc:
        raise ScientificPrerequisiteError(
            "similarity_gap_switch_correction_failed",
            "the deterministic AOX three-state gap-switch correction failed closed",
            details={"failure_type": type(exc).__name__},
        ) from exc


def _decode_packed_identity(
    packed_score: int,
    *,
    source_length: int,
    target_length: int,
) -> AlignmentIdentity:
    radix = max(source_length, target_length) + 1
    score_unit = radix * radix
    alignment_score_half_units, packed_counts = divmod(packed_score, score_unit)
    identity_matches, identity_aligned_residues = divmod(packed_counts, radix)
    if not (
        1 <= identity_aligned_residues <= min(source_length, target_length)
        and 0 <= identity_matches <= identity_aligned_residues
        and packed_score
        == alignment_score_half_units * score_unit
        + identity_matches * radix
        + identity_aligned_residues
    ):
        raise ScientificPrerequisiteError(
            "similarity_backend_decode_postcondition_failed",
            "the packed AOX alignment score did not decode to a valid identity tuple",
            details={
                "packed_score": packed_score,
                "source_length": source_length,
                "target_length": target_length,
                "identity_matches": identity_matches,
                "identity_aligned_residues": identity_aligned_residues,
            },
        )
    return AlignmentIdentity(
        alignment_score_half_units=alignment_score_half_units,
        identity_matches=identity_matches,
        identity_aligned_residues=identity_aligned_residues,
    )


def _calculate_encoded_global_sequence_identity(
    source: bytes,
    target: bytes,
) -> AlignmentIdentity:
    """Calculate the exact lexical identity tuple through the pinned C backend."""

    allowed = frozenset("".join(BLOSUM62_ALPHABET[:-1]).encode("ascii"))
    if (
        not source
        or not target
        or not set(source).issubset(allowed)
        or not set(target).issubset(allowed)
    ):
        raise ScientificPrerequisiteError(
            "similarity_backend_input_invalid",
            "the exact AOX similarity backend requires non-empty normalized ASCII residue bytes",
        )
    source_length = len(source)
    target_length = len(target)
    bound = _require_exact_float_bound(source_length, target_length)
    aligner = _packed_aligner(max(source_length, target_length) + 1)
    try:
        score = aligner.score(source, target)
    except Exception as exc:
        raise ScientificPrerequisiteError(
            "similarity_backend_execution_failed",
            "the exact AOX similarity backend failed closed while scoring a pair",
            details={"failure_type": type(exc).__name__},
        ) from exc
    packed_score = _integral_packed_score(score, bound=bound)
    if _alignment_has_opposite_gap_switch(
        aligner,
        source,
        target,
        packed_score=packed_score,
        bound=bound,
    ):
        return _calculate_numpy_three_state_correction(
            source,
            target,
            bound=bound,
        )
    return _decode_packed_identity(
        packed_score,
        source_length=source_length,
        target_length=target_length,
    )


def calculate_global_sequence_identity(
    source_sequence: str,
    target_sequence: str,
) -> AlignmentIdentity:
    """Calculate deterministic global affine-gap identity through the pinned backend."""

    source = _encode_alignment_sequence(source_sequence, field="source_sequence")
    target = _encode_alignment_sequence(target_sequence, field="target_sequence")
    return _calculate_encoded_global_sequence_identity(
        source,
        target,
    )


def _optional_cgroup_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ScientificPrerequisiteError(
            "similarity_cpu_limit_unreadable",
            "an available cgroup CPU constraint could not be read",
            details={"path": str(path), "failure_type": type(exc).__name__},
        ) from exc


def _quota_worker_limit(quota: str, period: str, *, source: str) -> int | None:
    if (
        not period.isascii()
        or not period.isdigit()
        or int(period) <= 0
    ):
        raise ScientificPrerequisiteError(
            "similarity_cpu_limit_invalid",
            "an available cgroup CPU quota is malformed",
            details={"source": source, "quota": quota, "period": period},
        )
    if quota in {"max", "-1"}:
        return None
    if not quota.isascii() or not quota.isdigit() or int(quota) <= 0:
        raise ScientificPrerequisiteError(
            "similarity_cpu_limit_invalid",
            "an available cgroup CPU quota is malformed",
            details={"source": source, "quota": quota, "period": period},
        )
    quota_value = int(quota)
    period_value = int(period)
    return max(1, (quota_value + period_value - 1) // period_value)


def _cgroup_worker_limits() -> tuple[int, ...]:
    limits: list[int] = []
    v2 = _optional_cgroup_text(_CGROUP_V2_CPU_MAX_PATH)
    if v2 is not None:
        fields = v2.split()
        if len(fields) != 2:
            raise ScientificPrerequisiteError(
                "similarity_cpu_limit_invalid",
                "an available cgroup v2 cpu.max value is malformed",
                details={"source": "cgroup_v2_cpu.max", "value": v2},
            )
        limit = _quota_worker_limit(
            fields[0], fields[1], source="cgroup_v2_cpu.max"
        )
        if limit is not None:
            limits.append(limit)

    for quota_path, period_path in _CGROUP_V1_CPU_PATHS:
        quota = _optional_cgroup_text(quota_path)
        period = _optional_cgroup_text(period_path)
        if quota is None and period is None:
            continue
        if quota is None or period is None:
            raise ScientificPrerequisiteError(
                "similarity_cpu_limit_invalid",
                "an available cgroup v1 CPU quota is incomplete",
                details={"source": str(quota_path.parent)},
            )
        limit = _quota_worker_limit(
            quota, period, source="cgroup_v1_cpu.cfs_quota_us"
        )
        if limit is not None:
            limits.append(limit)
    return tuple(limits)


def _alignment_worker_count(pair_count: int) -> int:
    if pair_count < PARALLEL_PAIR_THRESHOLD:
        return 1
    try:
        available = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):  # pragma: no cover - portability path
        available = os.cpu_count() or 1
    limits = [MAX_ALIGNMENT_WORKERS, max(1, available), pair_count]
    limits.extend(_cgroup_worker_limits())
    return max(1, min(limits))


def _initialize_alignment_worker(
    sequences: tuple[bytes, ...],
    threshold_ppm: int,
) -> None:
    global _ALIGNMENT_WORKER_SEQUENCES
    global _ALIGNMENT_WORKER_THRESHOLD_PPM
    _ALIGNMENT_WORKER_SEQUENCES = sequences
    _ALIGNMENT_WORKER_THRESHOLD_PPM = threshold_ppm
    _PACKED_ALIGNER_CACHE.clear()
    _ensure_alignment_backend()


def _calculate_alignment_pair(
    pair: tuple[int, int],
) -> tuple[int, int, AlignmentIdentity] | None:
    sequences = _ALIGNMENT_WORKER_SEQUENCES
    threshold_ppm = _ALIGNMENT_WORKER_THRESHOLD_PPM
    if sequences is None or threshold_ppm is None:
        raise RuntimeError("AOX alignment worker was not initialized")
    source_index, target_index = pair
    identity = _calculate_encoded_global_sequence_identity(
        sequences[source_index],
        sequences[target_index],
    )
    if not identity.passes_threshold(threshold_ppm):
        return None
    return source_index, target_index, identity


def _pair_indexes(node_count: int) -> Iterator[tuple[int, int]]:
    for source_index in range(node_count):
        for target_index in range(source_index + 1, node_count):
            yield source_index, target_index


def _calculate_graph_identities(
    encoded_sequences: tuple[bytes, ...],
    *,
    threshold_ppm: int,
) -> tuple[tuple[int, int, AlignmentIdentity], ...]:
    _ensure_alignment_backend()
    pair_count = len(encoded_sequences) * (len(encoded_sequences) - 1) // 2
    worker_count = _alignment_worker_count(pair_count)
    if worker_count == 1:
        results: list[tuple[int, int, AlignmentIdentity]] = []
        for source_index, target_index in _pair_indexes(len(encoded_sequences)):
            identity = _calculate_encoded_global_sequence_identity(
                encoded_sequences[source_index],
                encoded_sequences[target_index],
            )
            if identity.passes_threshold(threshold_ppm):
                results.append((source_index, target_index, identity))
        return tuple(results)

    try:
        with ProcessPoolExecutor(
            max_workers=worker_count,
            initializer=_initialize_alignment_worker,
            initargs=(encoded_sequences, threshold_ppm),
        ) as executor:
            mapped = executor.map(
                _calculate_alignment_pair,
                _pair_indexes(len(encoded_sequences)),
                chunksize=PARALLEL_PAIR_CHUNK_SIZE,
            )
            return tuple(result for result in mapped if result is not None)
    except Exception as exc:
        raise ScientificPrerequisiteError(
            "similarity_parallel_execution_failed",
            "bounded exact AOX pairwise alignment execution failed closed",
            details={"failure_type": type(exc).__name__},
        ) from exc


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

    encoded_sequences = tuple(
        _encode_alignment_sequence(
            node.sequence.sequence,
            field=f"candidate_sequence[{node.sequence.sequence_id}]",
        )
        for node in nodes
    )
    edges = [
        GraphEdge(
            source=nodes[source_index],
            target=nodes[target_index],
            identity=identity,
            threshold_ppm=threshold_ppm,
        )
        for source_index, target_index, identity in _calculate_graph_identities(
            encoded_sequences,
            threshold_ppm=threshold_ppm,
        )
    ]

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
