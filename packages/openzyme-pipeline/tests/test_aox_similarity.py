from __future__ import annotations

import csv
import io
import json
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

    verified = aox_similarity.validate_graph_artifacts(
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
        (b">\nAAAA\n", "empty_candidate_fasta_header"),
        (b">seq\n", "empty_candidate_sequence"),
        (b">seq\nAA-AA\n", "candidate_residue_unsupported"),
        (b">seq\nAA*AA\n", "candidate_residue_unsupported"),
        (b">seq\nAA AA\n", "whitespace_in_candidate_sequence"),
        (b">seq\n\xff\n", "candidate_fasta_not_utf8"),
    ],
)
def test_candidate_fasta_parser_fails_closed(data: bytes, code: str) -> None:
    with pytest.raises(aox_similarity.ScientificPrerequisiteError) as error:
        aox_similarity.parse_candidate_fasta(data)
    assert _error_code(error) == code


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


def test_graph_artifacts_round_trip_through_real_recomputation() -> None:
    result = _sample_result()

    verified = aox_similarity.validate_graph_artifacts(
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
        aox_similarity.validate_graph_artifacts(
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
        aox_similarity.validate_graph_artifacts(
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
        aox_similarity.validate_graph_artifacts(
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
        aox_similarity.validate_graph_artifacts(
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
        aox_similarity.validate_graph_artifacts(
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
        aox_similarity.validate_graph_artifacts(
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


def test_implementation_digest_is_the_installed_source_digest() -> None:
    source = Path(aox_similarity.__file__)
    assert aox_similarity.implementation_digest() == (
        "sha256:" + __import__("hashlib").sha256(source.read_bytes()).hexdigest()
    )
