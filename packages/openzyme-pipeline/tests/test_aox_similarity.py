from __future__ import annotations

import csv
import io
import itertools
import json
import random
import time
from pathlib import Path

import pytest

from openzyme_pipeline import aox_motif
from openzyme_pipeline import aox_similarity


SAMPLE_FASTA = (
    ">A0A_TEST_A representative\n"
    "AAAAAAAAAA\n"
    ">A0A_TEST_B one substitution\n"
    "AAAAAAAAAT\n"
    ">A0A_TEST_C two substitutions\n"
    "AAAAAAAATT\n"
)
SAMPLE_MEMBERSHIP = (
    "cluster_id,member_id,representative_id,is_representative,"
    "identity_to_representative,member_length\n"
    "cluster_0,A0A_TEST_A,A0A_TEST_A,true,1.000000,10\n"
    "cluster_0,A0A_TEST_B,A0A_TEST_A,false,0.900000,10\n"
    "cluster_1,A0A_TEST_C,A0A_TEST_C,true,1.000000,10\n"
)
EMPTY_MEMBERSHIP = ",".join(aox_similarity.MEMBERSHIP_COLUMNS) + "\n"


def _error_code(
    error: pytest.ExceptionInfo[aox_similarity.ScientificPrerequisiteError],
) -> str:
    assert error.value.to_dict()["error_type"] == "scientific_prerequisite_missing"
    return error.value.code


def _sample_result(
    *, threshold_ppm: int = 750_000
) -> aox_similarity.SimilarityGraphResult:
    return aox_similarity.build_similarity_graph(
        SAMPLE_FASTA,
        SAMPLE_MEMBERSHIP,
        threshold_ppm=threshold_ppm,
    )


def _reference_global_identity(
    source: str,
    target: str,
) -> aox_similarity.AlignmentIdentity:
    """The pre-optimization tuple recurrence, retained as an independent oracle."""

    unreachable = (-(10**15), 0, 0)
    width = len(target)
    match_previous = [unreachable] * (width + 1)
    gap_target_previous = [unreachable] * (width + 1)
    gap_source_previous = [unreachable] * (width + 1)
    match_previous[0] = (0, 0, 0)
    for column in range(1, width + 1):
        gap_source_previous[column] = (
            aox_similarity.GAP_OPEN_HALF_SCORE
            + (column - 1) * aox_similarity.GAP_EXTEND_HALF_SCORE,
            0,
            0,
        )

    def add_score(state: tuple[int, int, int], score: int) -> tuple[int, int, int]:
        if state[0] == unreachable[0]:
            return state
        return state[0] + score, state[1], state[2]

    for row, source_residue in enumerate(source, start=1):
        match_current = [unreachable] * (width + 1)
        gap_target_current = [unreachable] * (width + 1)
        gap_source_current = [unreachable] * (width + 1)
        gap_target_current[0] = (
            aox_similarity.GAP_OPEN_HALF_SCORE
            + (row - 1) * aox_similarity.GAP_EXTEND_HALF_SCORE,
            0,
            0,
        )
        for column, target_residue in enumerate(target, start=1):
            diagonal = max(
                match_previous[column - 1],
                gap_target_previous[column - 1],
                gap_source_previous[column - 1],
            )
            substitution = aox_similarity._BLOSUM62_HALF_SCORES[
                (source_residue, target_residue)
            ]
            match_current[column] = (
                diagonal[0] + substitution,
                diagonal[1] + int(source_residue == target_residue),
                diagonal[2] + 1,
            )
            gap_target_current[column] = max(
                add_score(
                    gap_target_previous[column],
                    aox_similarity.GAP_EXTEND_HALF_SCORE,
                ),
                add_score(
                    match_previous[column],
                    aox_similarity.GAP_OPEN_HALF_SCORE,
                ),
            )
            gap_source_current[column] = max(
                add_score(
                    gap_source_current[column - 1],
                    aox_similarity.GAP_EXTEND_HALF_SCORE,
                ),
                add_score(
                    match_current[column - 1],
                    aox_similarity.GAP_OPEN_HALF_SCORE,
                ),
            )
        match_previous = match_current
        gap_target_previous = gap_target_current
        gap_source_previous = gap_source_current

    score, matches, aligned = max(
        match_previous[width],
        gap_target_previous[width],
        gap_source_previous[width],
    )
    return aox_similarity.AlignmentIdentity(score, matches, aligned)


def _rewrite_csv(
    data: str,
    mutate: object,
) -> str:
    reader = csv.DictReader(io.StringIO(data))
    rows = list(reader)
    assert reader.fieldnames is not None
    for row in rows:
        mutate(row)  # type: ignore[operator]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=reader.fieldnames,
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def test_versioned_calculation_uses_exact_reference_alignment_parameters() -> None:
    payload = aox_similarity.calculation_payload(
        implementation_digest_value=aox_similarity.IMPLEMENTATION_DIGEST
    )

    assert payload["calculation_id"] == "aox_global_sequence_identity@1"
    alignment = payload["alignment"]
    assert isinstance(alignment, dict)
    assert alignment["substitution_matrix_id"] == "BLOSUM62"
    assert alignment["gap_open_half_score"] == -20
    assert alignment["gap_extend_half_score"] == -1
    assert alignment["identity_denominator"] == ("aligned_residue_pairs_excluding_gaps")
    assert alignment["identity_scale"] == "integer_parts_per_million_floor"
    assert alignment["tie_break_policy"] == aox_similarity.TIE_BREAK_POLICY
    assert alignment["input_normalization"] == {
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
    }
    assert alignment["backend"] == {
        "backend_id": "biopython_trace_guarded_numpy_gotoh@1",
        "api": "Bio.Align.PairwiseAligner.score+align()[0].coordinates",
        "biopython_version": "1.87",
        "numpy_version": "2.4.4",
        "algorithm": "Gotoh global alignment algorithm",
        "import_policy": "lazy_on_first_alignment",
        "fallback_policy": "forbidden",
        "sequence_transport": "ASCII_bytes",
        "numeric_transport": "IEEE_754_binary64_exact_integer",
        "max_exact_integer_exclusive": 1 << 53,
        "integrality_epsilon": "0.000001",
        "trace_validation": (
            "first_optimal_coordinates_reject_adjacent_opposite_gap_states"
        ),
        "gap_state_switch_correction": {
            "correction_id": "numpy_three_state_gap_switch_correction@1",
            "backend": "NumPy_int64_row_vectorized_exact_three_state",
            "activation": "adjacent_horizontal_vertical_gap_switch",
            "unreachable_sentinel": -(1 << 60),
            "exception_policy": "fail_closed_without_correction_or_fallback",
            "fallback": "forbidden",
        },
    }
    execution = payload["execution"]
    assert isinstance(execution, dict)
    assert execution == {
        "state_encoding": (
            "exact_mixed_radix_score_matches_aligned_residues_in_binary64_integer"
        ),
        "pair_order": "lexicographic_sequence_id_order",
        "parallelism": "bounded_process_pool_output_order_preserving",
        "max_worker_processes": 16,
        "parallel_pair_threshold": 128,
        "parallel_pair_chunk_size": 64,
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
    }
    assert payload["default_threshold_ppm"] == 850_000
    assert payload["implementation_digest"] == aox_similarity.IMPLEMENTATION_DIGEST
    assert (
        aox_similarity.calculation_digest(
            implementation_digest_value=aox_similarity.IMPLEMENTATION_DIGEST
        )
        == aox_similarity.CALCULATION_DIGEST
    )


def test_global_identity_is_derived_from_real_residues_and_is_symmetric() -> None:
    identical = aox_similarity.calculate_global_sequence_identity("ARND", "ARND")
    one_mismatch = aox_similarity.calculate_global_sequence_identity(
        "AAAAAAAAAA", "AAAAAAAAAT"
    )
    gapped = aox_similarity.calculate_global_sequence_identity("AAAA", "AAA")
    reverse = aox_similarity.calculate_global_sequence_identity(
        "AAAAAAAAAT", "AAAAAAAAAA"
    )

    assert identical == aox_similarity.AlignmentIdentity(42, 4, 4)
    assert identical.similarity_display == "1.000000"
    assert one_mismatch.alignment_score_half_units == 72
    assert one_mismatch.identity_matches == 9
    assert one_mismatch.identity_aligned_residues == 10
    assert one_mismatch.similarity_ppm == 900_000
    assert one_mismatch.similarity_display == "0.900000"
    assert reverse == one_mismatch
    assert gapped.identity_matches == 3
    assert gapped.identity_aligned_residues == 3
    assert gapped.similarity_display == "1.000000"


def test_trace_guarded_backend_matches_tuple_oracle_for_8001_exhaustive_pairs() -> (
    None
):
    exhaustive_sequences = [
        "".join(residues)
        for length in range(1, 7)
        for residues in itertools.product("CW", repeat=length)
    ]
    pairs = list(itertools.combinations_with_replacement(exhaustive_sequences, 2))
    assert len(exhaustive_sequences) == 126
    assert len(pairs) == 8_001

    for source, target in pairs:
        assert aox_similarity.calculate_global_sequence_identity(
            source,
            target,
        ) == _reference_global_identity(source, target)


def test_trace_guarded_backend_matches_250_seeded_full_alphabet_pairs() -> None:
    generator = random.Random(20260720)
    full_alphabet = "ARNDCQEGHILKMFPSTWYVBZX"
    pairs = [
        (
            "".join(
                generator.choice(full_alphabet)
                for _ in range(generator.randint(1, 18))
            ),
            "".join(
                generator.choice(full_alphabet)
                for _ in range(generator.randint(1, 18))
            ),
        )
        for _ in range(250)
    ]
    pairs.extend(
        [
            (
                "A",
                "A",
            ),
            ("AAAA", "AAA"),
            ("ARAR", "RARA"),
            ("WWWW", "CCCC"),
            ("ABZX", "XZBA"),
        ]
    )

    for source, target in pairs:
        assert aox_similarity.calculate_global_sequence_identity(
            source,
            target,
        ) == _reference_global_identity(source, target)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("W" * 7, "C" * 9),
        ("A", "A" * 1_024),
        ("A" * 1_024, "A"),
        ("W" * 37, "C" * 211),
    ],
)
def test_packed_negative_score_divmod_and_long_short_boundaries_match_oracle(
    source: str,
    target: str,
) -> None:
    expected = _reference_global_identity(source, target)
    actual = aox_similarity.calculate_global_sequence_identity(source, target)

    assert expected.alignment_score_half_units < 0
    assert actual == expected


def test_authorized_real_aox_reference_sequence_has_self_identity() -> None:
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "aox_motif_rule_score_v1"
        / "alignment.fasta"
    )
    alignment = aox_motif.parse_aligned_fasta(fixture.read_bytes())
    reference = next(
        record for record in alignment.records if record.sequence_id == "AAB57849.1"
    )

    identity = aox_similarity.calculate_global_sequence_identity(
        reference.sequence,
        reference.sequence,
    )

    assert len(reference.sequence) == 663
    assert identity.identity_matches == 663
    assert identity.identity_aligned_residues == 663
    assert identity.similarity_display == "1.000000"


def test_real_sequence_graph_closes_sequence_membership_and_edge_identity() -> None:
    result = _sample_result()
    node_rows = result.canonical_node_rows()
    edge_rows = result.canonical_edge_rows()

    assert [row["node_id"] for row in node_rows] == [
        "A0A_TEST_A",
        "A0A_TEST_B",
        "A0A_TEST_C",
    ]
    assert [row["cluster_id"] for row in node_rows] == [
        "cluster_0",
        "cluster_0",
        "cluster_1",
    ]
    assert [row["identity_to_representative"] for row in node_rows] == [
        "1.000000",
        "0.900000",
        "1.000000",
    ]
    assert all(row["sequence_length"] == 10 for row in node_rows)
    assert len({row["sequence_digest"] for row in node_rows}) == 3
    assert all(
        row["candidate_sequence_set_digest"] == result.sequences.sequence_set_digest
        for row in node_rows
    )
    assert all(
        row["cdhit_membership_set_digest"] == result.membership.membership_set_digest
        for row in node_rows
    )

    assert [(row["source"], row["target"]) for row in edge_rows] == [
        ("A0A_TEST_A", "A0A_TEST_B"),
        ("A0A_TEST_A", "A0A_TEST_C"),
        ("A0A_TEST_B", "A0A_TEST_C"),
    ]
    assert [row["similarity"] for row in edge_rows] == [
        "0.900000",
        "0.800000",
        "0.900000",
    ]
    assert [row["identity_matches"] for row in edge_rows] == [9, 8, 9]
    assert all(
        row["similarity_calculation_digest"] == aox_similarity.CALCULATION_DIGEST
        for row in edge_rows
    )
    assert all(
        row["cdhit_membership_schema_id"] == "cdhit_cluster_membership@1"
        for row in edge_rows
    )

    manifest = result.manifest()
    assert manifest["node_count"] == 3
    assert manifest["edge_count"] == 3
    assert manifest["empty_result"] is False
    assert manifest["empty_result_reason"] is None
    assert manifest["nodes_digest"].startswith("sha256:")
    assert manifest["edges_digest"].startswith("sha256:")


def test_schema_valid_empty_graph_has_headers_reason_and_no_fabricated_rows() -> None:
    result = aox_similarity.build_similarity_graph(
        b"",
        EMPTY_MEMBERSHIP,
        empty_result_reason="no_candidates_after_motif_filter",
    )

    assert result.nodes == ()
    assert result.edges == ()
    assert result.nodes_csv() == ",".join(aox_similarity.NODE_COLUMNS) + "\n"
    assert result.edges_csv() == ",".join(aox_similarity.EDGE_COLUMNS) + "\n"
    assert result.manifest()["empty_result"] is True
    assert result.manifest()["empty_result_reason"] == (
        "no_candidates_after_motif_filter"
    )
    assert result.manifest()["node_count"] == 0
    assert result.manifest()["edge_count"] == 0

    verified = aox_similarity.validate_graph_files(
        b"",
        EMPTY_MEMBERSHIP,
        result.nodes_csv(),
        result.edges_csv(),
        result.manifest_json(),
        empty_result_reason="no_candidates_after_motif_filter",
    )
    assert verified.empty_result is True


def test_empty_graph_requires_reason_and_non_empty_graph_rejects_one() -> None:
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as missing:
        aox_similarity.build_similarity_graph(b"", EMPTY_MEMBERSHIP)
    assert _error_code(missing) == "empty_graph_reason_missing"

    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as unexpected:
        aox_similarity.build_similarity_graph(
            SAMPLE_FASTA,
            SAMPLE_MEMBERSHIP,
            empty_result_reason="not_really_empty",
        )
    assert _error_code(unexpected) == "empty_graph_reason_unexpected"

    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as unsafe:
        aox_similarity.build_similarity_graph(
            b"",
            EMPTY_MEMBERSHIP,
            empty_result_reason="No candidates\n/private/path",
        )
    assert _error_code(unsafe) == "empty_graph_reason_invalid"


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"AAAA\n", "candidate_sequence_before_header"),
        (b" >seq\nAAAA\n", "candidate_sequence_before_header"),
        (b"\t>seq\nAAAA\n", "candidate_sequence_before_header"),
        (b">\nAAAA\n", "empty_candidate_fasta_header"),
        (b">seq\r", "candidate_fasta_header_carriage_return"),
        (b">se\rquence\nAAAA\n", "candidate_fasta_header_carriage_return"),
        (b">seq\r\r\nAAAA\n", "candidate_fasta_header_carriage_return"),
        (b">seq\n", "empty_candidate_sequence"),
        (b">seq\nAA-AA\n", "candidate_residue_unsupported"),
        (b">seq\nAA*AA\n", "candidate_residue_unsupported"),
        (">seq\nAAßAA\n".encode(), "candidate_residue_unsupported"),
        (">seq\nAAſAA\n".encode(), "candidate_residue_unsupported"),
        (b">seq\n AA\n", "whitespace_in_candidate_sequence"),
        (b">seq\nAA \n", "whitespace_in_candidate_sequence"),
        (b">seq\nAA\r", "whitespace_in_candidate_sequence"),
        (b">seq\n\t\n", "whitespace_in_candidate_sequence"),
        (b">seq\nAA AA\n", "whitespace_in_candidate_sequence"),
        (b">seq\n\xff\n", "candidate_fasta_not_utf8"),
    ],
)
def test_candidate_fasta_parser_fails_closed(data: bytes, code: str) -> None:
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as error:
        aox_similarity.parse_candidate_fasta(data)
    assert _error_code(error) == code


def test_candidate_ascii_lowercase_is_normalized_only_after_raw_validation() -> None:
    parsed = aox_similarity.parse_candidate_fasta(b">seq\r\narnd\r\n")

    assert parsed.records[0].sequence == "ARND"


@pytest.mark.parametrize("unsafe", ["AAß", "AAſ", " AA", "AA ", "AA\t"])
def test_direct_identity_rejects_non_ascii_and_all_whitespace(
    unsafe: str,
) -> None:
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as error:
        aox_similarity.calculate_global_sequence_identity(unsafe, "AAAA")

    assert _error_code(error) == "similarity_sequence_residue_unsupported"


def test_duplicate_candidate_and_membership_ids_are_rejected() -> None:
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as fasta_error:
        aox_similarity.parse_candidate_fasta(">seq\nAAAA\n>seq\nAAAT\n")
    assert _error_code(fasta_error) == "duplicate_candidate_sequence_id"

    duplicate_membership = SAMPLE_MEMBERSHIP + (
        "cluster_2,A0A_TEST_B,A0A_TEST_B,true,1.000000,10\n"
    )
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as member_error:
        aox_similarity.parse_cdhit_membership_csv(duplicate_membership)
    assert _error_code(member_error) == "duplicate_cdhit_member_id"


@pytest.mark.parametrize(
    ("membership", "code"),
    [
        (
            "cluster_id,representative,member_count\ncluster_0,A0A_TEST_A,3\n",
            "legacy_cdhit_membership_schema",
        ),
        (
            EMPTY_MEMBERSHIP.replace("member_length", "length"),
            "cdhit_membership_schema_mismatch",
        ),
        (
            SAMPLE_MEMBERSHIP.replace(
                "cluster_0,A0A_TEST_A,A0A_TEST_A,true",
                "cluster_0,A0A_TEST_A,A0A_TEST_A,false",
            ),
            "cdhit_representative_missing_or_duplicate",
        ),
        (
            SAMPLE_MEMBERSHIP.replace("0.900000", "90.000000"),
            "cdhit_membership_identity_invalid",
        ),
        (
            SAMPLE_MEMBERSHIP.replace(
                "A0A_TEST_B,A0A_TEST_A,false", "A0A_TEST_B,A0A_TEST_C,false"
            ),
            "cdhit_representative_identity_inconsistent",
        ),
    ],
)
def test_membership_parser_rejects_schema_and_identity_failures(
    membership: str, code: str
) -> None:
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as error:
        aox_similarity.parse_cdhit_membership_csv(membership)
    assert _error_code(error) == code


def test_candidate_and_membership_sets_and_lengths_must_close_exactly() -> None:
    missing = "\n".join(SAMPLE_MEMBERSHIP.splitlines()[:-1]) + "\n"
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as missing_error:
        aox_similarity.build_similarity_graph(SAMPLE_FASTA, missing)
    assert _error_code(missing_error) == "candidate_membership_set_mismatch"
    assert missing_error.value.details["missing_membership"] == ["A0A_TEST_C"]

    wrong_length = SAMPLE_MEMBERSHIP.replace(
        "cluster_0,A0A_TEST_B,A0A_TEST_A,false,0.900000,10",
        "cluster_0,A0A_TEST_B,A0A_TEST_A,false,0.900000,9",
    )
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as length_error:
        aox_similarity.build_similarity_graph(SAMPLE_FASTA, wrong_length)
    assert _error_code(length_error) == "cdhit_member_length_mismatch"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"expected_calculation_id": ""},
        {"expected_calculation_id": "aox_global_sequence_identity@2"},
        {"expected_calculation_digest": "sha256:" + "0" * 64},
        {"expected_implementation_digest": "sha256:" + "0" * 64},
    ],
)
def test_calculation_drift_fails_before_parsing(kwargs: dict[str, str]) -> None:
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as error:
        aox_similarity.build_similarity_graph(b"not fasta", b"not csv", **kwargs)
    assert _error_code(error) == "similarity_calculation_digest_drift"


@pytest.mark.parametrize(
    "field",
    ["expected_calculation_digest", "expected_implementation_digest"],
)
def test_explicit_empty_expected_digest_never_defaults(
    field: str,
) -> None:
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as error:
        aox_similarity.build_similarity_graph(
            b"not fasta",
            b"not csv",
            **{field: ""},
        )

    assert _error_code(error) == "similarity_digest_invalid"


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("expected_candidate_fasta_digest", "candidate_fasta_digest_mismatch"),
        ("expected_membership_digest", "cdhit_membership_digest_mismatch"),
    ],
)
def test_input_byte_digest_drift_is_rejected(field: str, code: str) -> None:
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as error:
        aox_similarity.build_similarity_graph(
            SAMPLE_FASTA,
            SAMPLE_MEMBERSHIP,
            **{field: "sha256:" + "0" * 64},
        )
    assert _error_code(error) == code


def test_graph_files_round_trip_through_real_recomputation() -> None:
    result = _sample_result()

    verified = aox_similarity.validate_graph_files(
        SAMPLE_FASTA,
        SAMPLE_MEMBERSHIP,
        result.nodes_csv(),
        result.edges_csv(),
        result.manifest_json(),
        threshold_ppm=750_000,
        expected_calculation_digest=aox_similarity.CALCULATION_DIGEST,
        expected_implementation_digest=aox_similarity.IMPLEMENTATION_DIGEST,
        expected_candidate_fasta_digest=result.sequences.input_digest,
        expected_membership_digest=result.membership.input_digest,
    )

    assert verified.manifest() == result.manifest()


def test_node_sequence_and_cluster_tampering_is_rejected() -> None:
    result = _sample_result()
    tampered_digest = _rewrite_csv(
        result.nodes_csv(),
        lambda row: (
            row.update({"sequence_digest": "sha256:" + "0" * 64})
            if row["node_id"] == "A0A_TEST_B"
            else None
        ),
    )
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as digest_error:
        aox_similarity.validate_graph_files(
            SAMPLE_FASTA,
            SAMPLE_MEMBERSHIP,
            tampered_digest,
            result.edges_csv(),
            result.manifest_json(),
            threshold_ppm=750_000,
        )
    assert _error_code(digest_error) == "graph_node_binding_mismatch"
    assert digest_error.value.details["field"] == "sequence_digest"

    constant_cluster = _rewrite_csv(
        result.nodes_csv(),
        lambda row: row.update({"cluster_id": "cluster_0"}),
    )
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as cluster_error:
        aox_similarity.validate_graph_files(
            SAMPLE_FASTA,
            SAMPLE_MEMBERSHIP,
            constant_cluster,
            result.edges_csv(),
            result.manifest_json(),
            threshold_ppm=750_000,
        )
    assert _error_code(cluster_error) == "graph_node_binding_mismatch"
    assert cluster_error.value.details["field"] == "cluster_id"


def test_constant_or_copied_edge_similarity_is_rejected_by_recomputation() -> None:
    result = _sample_result()
    constant_edges = _rewrite_csv(
        result.edges_csv(),
        lambda row: row.update({"similarity_ppm": "900000", "similarity": "0.900000"}),
    )

    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as error:
        aox_similarity.validate_graph_files(
            SAMPLE_FASTA,
            SAMPLE_MEMBERSHIP,
            result.nodes_csv(),
            constant_edges,
            result.manifest_json(),
            threshold_ppm=750_000,
        )

    assert _error_code(error) == "graph_edge_recalculation_mismatch"
    assert error.value.details["source"] == "A0A_TEST_A"
    assert error.value.details["target"] == "A0A_TEST_C"
    assert error.value.details["field"] == "similarity_ppm"


@pytest.mark.parametrize(
    ("nodes", "edges", "code"),
    [
        (
            "node_id,label,score,cluster_id\nA,candidate,33.6,cluster_1\n",
            None,
            "legacy_graph_schema",
        ),
        (
            None,
            "source,target,similarity\nA,B,0.91\n",
            "legacy_graph_schema",
        ),
        (
            "node_id,unexpected\nA,value\n",
            None,
            "graph_nodes_schema_mismatch",
        ),
        (
            None,
            "source,target,unexpected\nA,B,value\n",
            "graph_edges_schema_mismatch",
        ),
    ],
)
def test_legacy_and_unversioned_graph_schemas_are_rejected(
    nodes: str | None, edges: str | None, code: str
) -> None:
    result = _sample_result()
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as error:
        aox_similarity.validate_graph_files(
            SAMPLE_FASTA,
            SAMPLE_MEMBERSHIP,
            nodes or result.nodes_csv(),
            edges or result.edges_csv(),
            result.manifest_json(),
            threshold_ppm=750_000,
        )
    assert _error_code(error) == code


def test_manifest_field_digest_and_canonical_bytes_are_verified() -> None:
    result = _sample_result()
    payload = result.manifest()
    payload["edge_count"] = 99
    tampered = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as field_error:
        aox_similarity.validate_graph_files(
            SAMPLE_FASTA,
            SAMPLE_MEMBERSHIP,
            result.nodes_csv(),
            result.edges_csv(),
            tampered,
            threshold_ppm=750_000,
        )
    assert _error_code(field_error) == "graph_manifest_recalculation_mismatch"
    assert field_error.value.details["field"] == "edge_count"

    noncanonical = json.dumps(result.manifest(), indent=2, sort_keys=True) + "\n"
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as bytes_error:
        aox_similarity.validate_graph_files(
            SAMPLE_FASTA,
            SAMPLE_MEMBERSHIP,
            result.nodes_csv(),
            result.edges_csv(),
            noncanonical,
            threshold_ppm=750_000,
        )
    assert _error_code(bytes_error) == "graph_manifest_not_canonical"


def test_single_real_candidate_is_non_empty_with_a_schema_valid_empty_edge_set() -> (
    None
):
    fasta = ">ONLY_AOX\nARNDCQEGHILK\n"
    membership = EMPTY_MEMBERSHIP + "cluster_0,ONLY_AOX,ONLY_AOX,true,1.000000,12\n"
    result = aox_similarity.build_similarity_graph(fasta, membership)

    assert len(result.nodes) == 1
    assert result.edges == ()
    assert result.empty_result is False
    assert result.empty_result_reason is None
    assert result.edges_csv() == ",".join(aox_similarity.EDGE_COLUMNS) + "\n"


def test_parallel_pair_execution_preserves_exact_lexicographic_pair_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alphabet = "".join(aox_similarity.BLOSUM62_ALPHABET[:-1]).encode("ascii")
    sequences = tuple(
        bytes(
            alphabet[(position * 7 + sequence_index * 11) % len(alphabet)]
            for position in range(36)
        )
        for sequence_index in range(17)
    )
    monkeypatch.setattr(aox_similarity, "_alignment_worker_count", lambda _: 2)

    actual = aox_similarity._calculate_graph_identities(
        sequences,
        threshold_ppm=0,
    )
    expected = tuple(
        (
            source_index,
            target_index,
            aox_similarity._calculate_encoded_global_sequence_identity(
                sequences[source_index],
                sequences[target_index],
            ),
        )
        for source_index in range(len(sequences))
        for target_index in range(source_index + 1, len(sequences))
    )

    assert actual == expected


def test_parallel_worker_start_failure_is_typed_and_does_not_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingExecutor:
        def __init__(self, **_: object) -> None:
            raise OSError("process creation intentionally unavailable")

    monkeypatch.setattr(aox_similarity, "_alignment_worker_count", lambda _: 2)
    monkeypatch.setattr(aox_similarity, "ProcessPoolExecutor", FailingExecutor)

    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as error:
        aox_similarity._calculate_graph_identities(
            (bytes([0, 1]), bytes([0, 2])),
            threshold_ppm=0,
        )

    assert _error_code(error) == "similarity_parallel_execution_failed"
    assert error.value.details == {"failure_type": "OSError"}


def test_parallel_map_failure_is_typed_and_never_retried_serially(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serial_call_count = 0
    original = aox_similarity._calculate_encoded_global_sequence_identity

    def serial_probe(source: bytes, target: bytes) -> aox_similarity.AlignmentIdentity:
        nonlocal serial_call_count
        serial_call_count += 1
        return original(source, target)

    class FailingMapExecutor:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self) -> FailingMapExecutor:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def map(self, *_: object, **__: object) -> object:
            raise RuntimeError("executor map intentionally failed")

    monkeypatch.setattr(aox_similarity, "_alignment_worker_count", lambda _: 2)
    monkeypatch.setattr(aox_similarity, "ProcessPoolExecutor", FailingMapExecutor)
    monkeypatch.setattr(
        aox_similarity,
        "_calculate_encoded_global_sequence_identity",
        serial_probe,
    )

    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as error:
        aox_similarity._calculate_graph_identities(
            (bytes([0, 1]), bytes([0, 2])),
            threshold_ppm=0,
        )

    assert _error_code(error) == "similarity_parallel_execution_failed"
    assert error.value.details == {"failure_type": "RuntimeError"}
    assert serial_call_count == 0


def test_parallel_worker_runtime_failure_is_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(aox_similarity, "_alignment_worker_count", lambda _: 2)

    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as error:
        aox_similarity._calculate_graph_identities(
            (bytes([255]), bytes([0])),
            threshold_ppm=0,
    )

    assert _error_code(error) == "similarity_parallel_execution_failed"
    assert error.value.details == {"failure_type": "BrokenProcessPool"}


def test_worker_count_uses_bounded_cpu_fallback_when_affinity_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def affinity_unavailable(_: int) -> set[int]:
        raise OSError("affinity intentionally unavailable")

    monkeypatch.setattr(aox_similarity.os, "sched_getaffinity", affinity_unavailable)
    monkeypatch.setattr(aox_similarity.os, "cpu_count", lambda: 7)
    monkeypatch.setattr(aox_similarity, "_cgroup_worker_limits", lambda: ())

    assert aox_similarity._alignment_worker_count(500) == 7


def test_cgroup_v2_and_v1_quotas_jointly_bound_affinity_workers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    v2 = tmp_path / "cpu.max"
    v2.write_text("350000 100000\n")
    quota = tmp_path / "cpu.cfs_quota_us"
    period = tmp_path / "cpu.cfs_period_us"
    quota.write_text("150000\n")
    period.write_text("100000\n")
    monkeypatch.setattr(aox_similarity, "_CGROUP_V2_CPU_MAX_PATH", v2)
    monkeypatch.setattr(
        aox_similarity,
        "_CGROUP_V1_CPU_PATHS",
        ((quota, period),),
    )
    monkeypatch.setattr(
        aox_similarity.os, "sched_getaffinity", lambda _: set(range(8))
    )

    assert aox_similarity._alignment_worker_count(500) == 2


@pytest.mark.parametrize("quota", ["max", "-1"])
def test_unbounded_cgroup_quota_still_requires_valid_period(quota: str) -> None:
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as error:
        aox_similarity._quota_worker_limit(
            quota,
            "nonsense",
            source="test",
        )

    assert _error_code(error) == "similarity_cpu_limit_invalid"


def test_existing_unreadable_cgroup_constraint_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    unreadable_file = tmp_path / "cpu.max"
    unreadable_file.mkdir()
    monkeypatch.setattr(
        aox_similarity,
        "_CGROUP_V2_CPU_MAX_PATH",
        unreadable_file,
    )
    monkeypatch.setattr(aox_similarity, "_CGROUP_V1_CPU_PATHS", ())

    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as error:
        aox_similarity._alignment_worker_count(500)

    assert _error_code(error) == "similarity_cpu_limit_unreadable"


def test_backend_import_is_lazy_and_unavailable_backend_has_no_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imports: list[str] = []

    def broken_import(name: str) -> object:
        imports.append(name)
        raise OSError("broken extension module")

    monkeypatch.setattr(aox_similarity, "_ALIGNMENT_BACKEND", None)
    aox_similarity._PACKED_ALIGNER_CACHE.clear()
    monkeypatch.setattr(aox_similarity.importlib, "import_module", broken_import)

    metadata = aox_similarity.calculation_metadata()
    assert metadata["alignment_backend_biopython_version"] == "1.87"
    assert imports == []
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as error:
        aox_similarity.calculate_global_sequence_identity("A", "A")

    assert _error_code(error) == "similarity_backend_unavailable"
    assert imports == ["Bio"]


def test_backend_version_and_algorithm_mismatch_fail_parent_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(aox_similarity, "_ALIGNMENT_BACKEND", None)
    aox_similarity._PACKED_ALIGNER_CACHE.clear()
    monkeypatch.setattr(aox_similarity, "BIOPYTHON_VERSION", "0.invalid")
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as version_error:
        aox_similarity.calculate_global_sequence_identity("A", "A")
    assert _error_code(version_error) == "similarity_backend_version_mismatch"

    monkeypatch.setattr(aox_similarity, "BIOPYTHON_VERSION", "1.87")
    monkeypatch.setattr(aox_similarity, "ALIGNMENT_BACKEND_ALGORITHM", "unexpected")
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as algorithm_error:
        aox_similarity.calculate_global_sequence_identity("A", "A")
    assert _error_code(algorithm_error) == "similarity_backend_algorithm_mismatch"


def test_nonintegral_score_and_trace_failure_never_trigger_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    correction_calls = 0

    def forbidden_correction(*_: object, **__: object) -> object:
        nonlocal correction_calls
        correction_calls += 1
        raise AssertionError("correction must not be an exception fallback")

    class NonIntegralAligner:
        def score(self, *_: object) -> float:
            return 35.25

    monkeypatch.setattr(aox_similarity, "_packed_aligner", lambda _: NonIntegralAligner())
    monkeypatch.setattr(
        aox_similarity,
        "_calculate_numpy_three_state_correction",
        forbidden_correction,
    )
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as score_error:
        aox_similarity._calculate_encoded_global_sequence_identity(b"A", b"A")
    assert _error_code(score_error) == "similarity_backend_score_nonintegral"
    assert correction_calls == 0

    class TraceFailureAligner:
        def score(self, *_: object) -> float:
            return 35.0

        def align(self, *_: object) -> object:
            raise RuntimeError("trace intentionally unavailable")

    monkeypatch.setattr(aox_similarity, "_packed_aligner", lambda _: TraceFailureAligner())
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as trace_error:
        aox_similarity._calculate_encoded_global_sequence_identity(b"A", b"A")
    assert _error_code(trace_error) == "similarity_backend_trace_failed"
    assert correction_calls == 0


def test_explicit_gap_switch_correction_failure_is_typed_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ValidScoreAligner:
        def score(self, *_: object) -> float:
            return 35.0

    def correction_failure(*_: object, **__: object) -> object:
        raise MemoryError("correction intentionally unavailable")

    monkeypatch.setattr(aox_similarity, "_packed_aligner", lambda _: ValidScoreAligner())
    monkeypatch.setattr(
        aox_similarity,
        "_alignment_has_opposite_gap_switch",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        aox_similarity,
        "_run_numpy_three_state_correction",
        correction_failure,
    )

    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as error:
        aox_similarity._calculate_encoded_global_sequence_identity(b"A", b"A")

    assert _error_code(error) == "similarity_gap_switch_correction_failed"
    assert error.value.details == {"failure_type": "MemoryError"}


def test_gap_switch_activates_exact_numpy_three_state_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    correction_calls = 0
    original = aox_similarity._run_numpy_three_state_correction

    def correction_probe(
        source: bytes, target: bytes, *, bound: int
    ) -> aox_similarity.AlignmentIdentity:
        nonlocal correction_calls
        correction_calls += 1
        return original(source, target, bound=bound)

    monkeypatch.setattr(
        aox_similarity,
        "_run_numpy_three_state_correction",
        correction_probe,
    )
    source = "W" * 37
    target = "C" * 211

    assert aox_similarity.calculate_global_sequence_identity(
        source, target
    ) == _reference_global_identity(source, target)
    assert correction_calls == 1


def test_binary64_bound_and_numpy_unreachable_sentinel_have_strict_margin() -> None:
    low = 1
    high = 100_000
    while low + 1 < high:
        middle = (low + high) // 2
        if (
            aox_similarity._packed_score_bound(middle, middle)
            < aox_similarity.MAX_EXACT_FLOAT_INTEGER
        ):
            low = middle
        else:
            high = middle

    safe_length = low
    assert (
        aox_similarity._require_exact_float_bound(safe_length, safe_length)
        < aox_similarity.MAX_EXACT_FLOAT_INTEGER
    )
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as error:
        aox_similarity._require_exact_float_bound(high, high)
    assert _error_code(error) == "similarity_backend_numeric_bound_exceeded"
    assert (
        aox_similarity.NUMPY_NEGATIVE_INFINITY
        + aox_similarity.MAX_EXACT_FLOAT_INTEGER
        < -aox_similarity.MAX_EXACT_FLOAT_INTEGER
    )


def test_real_length_bounded_parallel_kernel_performance_regression() -> None:
    alphabet = "".join(aox_similarity.BLOSUM62_ALPHABET[:-1]).encode("ascii")
    sequences = tuple(
        bytes(
            alphabet[(position * 7 + sequence_index * 11) % len(alphabet)]
            for position in range(180)
        )
        for sequence_index in range(48)
    )

    started = time.perf_counter()
    aox_similarity._calculate_graph_identities(
        sequences,
        threshold_ppm=1_000_000,
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 30.0


def test_implementation_digest_is_the_installed_source_digest() -> None:
    source = Path(aox_similarity.__file__)
    assert aox_similarity.implementation_digest() == (
        "sha256:" + __import__("hashlib").sha256(source.read_bytes()).hexdigest()
    )
