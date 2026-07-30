from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import re

from openzyme_pipeline import aox_hmmer
from openzyme_pipeline import aox_finalization
from openzyme_pipeline import aox_motif
from openzyme_pipeline import aox_reference
from openzyme_pipeline import aox_sequence_join
from openzyme_pipeline import aox_similarity

AOX_HMM_ACCESSIONS = aox_reference.HMM_REFERENCE_ACCESSIONS
AOX_NCBI_ACCESSIONS = aox_reference.NCBI_REFERENCE_ACCESSIONS


def _s15_is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None
    )


S15_AOX_HMM_FIXED_DELIVERABLES = set(aox_finalization.FIXED_DELIVERABLE_PATHS)
S15_AOX_HMM_OLD_DELIVERABLES = {
    "aox_hmm/filtered.fasta",
    "aox_hmm/filtered.csv",
    "aox_hmm/scoring.csv",
    "aox_hmm/candidates.fasta",
    "aox_hmm/candidates.csv",
    "aox_hmm/candidate_cdhit85.fasta",
}
S15_AOX_HMM_REQUIRED_CSV_COLUMNS = {
    "aox_hmm/hits_raw.csv": {
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
    },
    "aox_hmm/hmmer_score_filtered_accessions.csv": {
        "accession",
        "target",
        "evalue_numeric",
        "score_numeric",
        "raw_page_digest",
        "raw_hit_digest",
        "parsed_row_digest",
    },
    "aox_hmm/hits_len650_700_200.csv": {
        "target",
        "uniprot_accession",
        "hmm_score",
        "evalue",
        "length",
        "sequence",
    },
    "aox_hmm/scored_ref_plus_hits.csv": set(aox_motif.CANONICAL_COLUMNS),
    "aox_hmm/AOX_candidates_cdhit85.clusters.csv": {
        "cluster_id",
        "member_id",
        "representative_id",
        "is_representative",
        "identity_to_representative",
        "member_length",
    },
    "aox_hmm/nodes.csv": set(aox_similarity.NODE_COLUMNS),
    "aox_hmm/edges_similarity.csv": set(aox_similarity.EDGE_COLUMNS),
}
S15_AOX_HMM_REQUIRED_SUMMARY_FIELDS = {
    "accession_count",
    "ncbi_reference_accession_count",
    "filtered_hit_count",
    "scoring_row_count",
    "candidate_count",
    "representative_count",
    "graph_node_count",
    "graph_edge_count",
    "length_filter",
    "hmm_score_threshold",
    "motif_rule_score_threshold_tenths",
    "motif_rule_score_threshold",
    "similarity_threshold",
    "hmmer_database",
    "hmmer_score_filter_contract_id",
    "hmmer_score_filter_contract_digest",
    "hmmer_score_filter_implementation_digest",
    "hmmer_score_filter_input_digest",
    "hmmer_score_filter_output_digest",
    "sequence_length_join_contract_id",
    "sequence_length_join_contract_digest",
    "sequence_length_join_implementation_digest",
    "sequence_length_join_hits_digest",
    "sequence_length_join_target_digest",
    "hmm_reference_set_selection_contract_id",
    "hmm_reference_set_selection_contract_digest",
    "hmm_reference_set_selection_implementation_digest",
    "hmm_reference_set_input_digest",
    "hmm_reference_set_output_digest",
    "scoring_reference_selection_contract_id",
    "scoring_reference_selection_contract_digest",
    "scoring_reference_selection_implementation_digest",
    "scoring_reference_selection_input_digest",
    "scoring_reference_output_digest",
    "scoring_input_assembly_contract_id",
    "scoring_input_assembly_contract_digest",
    "scoring_input_assembly_implementation_digest",
    "scoring_reference_input_digest",
    "post_uniprot_target_input_digest",
    "scoring_contract_id",
    "scoring_contract_digest",
    "scoring_implementation_digest",
    "scoring_reference_accession",
    "scoring_input_digest",
    "scoring_alignment_input_digest",
    "scoring_alignment_digest",
    "cdhit_membership_schema_id",
    "similarity_calculation_id",
    "similarity_calculation_digest",
    "similarity_implementation_digest",
    "similarity_threshold_ppm",
    "candidate_graph_manifest_schema_id",
    "candidate_graph_node_schema_id",
    "candidate_graph_edge_schema_id",
    "candidate_graph_manifest_digest",
    "scientific_outcome",
    "scientific_branch",
    "omitted_operation_roles",
    "upstream_empty_skip_receipt_digest",
    "provider_status",
    "tool_status",
    "warning_count",
    "artifact_ids",
    "normalized_final_deliverable_paths",
}


def _s15_aox_required_artifact_paths() -> set[str]:
    return set(S15_AOX_HMM_FIXED_DELIVERABLES)


def _s15_aox_missing_required_paths(artifact_paths: set[str]) -> list[str]:
    return sorted(S15_AOX_HMM_FIXED_DELIVERABLES - artifact_paths)


def _s15_aox_legacy_paths_present(artifact_paths: set[str]) -> list[str]:
    return sorted(S15_AOX_HMM_OLD_DELIVERABLES & artifact_paths)


S15_AOX_HMM_LEGACY_SCIENTIFIC_FIELDS = frozenset(
    {"activity_score", "seq_score", "pass_rule"}
)
S15_AOX_HMM_CDHIT_MEMBERSHIP_COLUMNS = (
    "cluster_id",
    "member_id",
    "representative_id",
    "is_representative",
    "identity_to_representative",
    "member_length",
)
_S15_AOX_SEQUENCE_PATTERN = re.compile(r"^[A-Z]+$")
_S15_AOX_CDHIT_IDENTITY_PATTERN = re.compile(r"(?:0|1)\.[0-9]{6}")
_S15_AOX_SYNTHETIC_MARKERS = ("MSEQUENCE", "FIXTURE", "SYNTHETIC")


def _s15_aox_content_digest(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _s15_aox_reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _s15_aox_error(
    errors: list[dict[str, object]],
    error_code: str,
    *,
    path: str | None = None,
    **details: object,
) -> None:
    error: dict[str, object] = {"error_code": error_code}
    if path is not None:
        error["path"] = path
    error.update(details)
    errors.append(error)


def _s15_aox_parse_fasta(
    text: str,
    *,
    path: str,
    errors: list[dict[str, object]],
    allow_empty: bool,
) -> dict[str, str] | None:
    if not text.strip():
        if allow_empty:
            return {}
        _s15_aox_error(errors, "invalid_fasta", path=path, reason="empty")
        return None
    records: dict[str, str] = {}
    header: str | None = None
    fragments: list[str] = []

    def finish_record() -> bool:
        nonlocal header, fragments
        if header is None:
            return True
        sequence_id = header.split(maxsplit=1)[0] if header else ""
        sequence = "".join(fragments).upper()
        if not sequence_id or not sequence:
            _s15_aox_error(
                errors,
                "invalid_fasta",
                path=path,
                reason="empty_header_or_sequence",
            )
            return False
        if sequence_id in records:
            _s15_aox_error(
                errors,
                "invalid_fasta",
                path=path,
                reason="duplicate_sequence_id",
                sequence_id=sequence_id,
            )
            return False
        if _S15_AOX_SEQUENCE_PATTERN.fullmatch(sequence) is None:
            _s15_aox_error(
                errors,
                "invalid_fasta",
                path=path,
                reason="invalid_sequence_residue",
                sequence_id=sequence_id,
            )
            return False
        upper_header = header.upper()
        if any(
            marker in upper_header or marker in sequence
            for marker in _S15_AOX_SYNTHETIC_MARKERS
        ):
            _s15_aox_error(
                errors,
                "synthetic_sequence_evidence_forbidden",
                path=path,
                sequence_id=sequence_id,
            )
            return False
        records[sequence_id] = sequence
        header = None
        fragments = []
        return True

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if not finish_record():
                return None
            header = line[1:].strip()
            continue
        if header is None or any(character.isspace() for character in line):
            _s15_aox_error(
                errors,
                "invalid_fasta",
                path=path,
                reason="sequence_before_header_or_internal_whitespace",
                line=line_number,
            )
            return None
        fragments.append(line)
    if not finish_record():
        return None
    if not records:
        _s15_aox_error(errors, "invalid_fasta", path=path, reason="no_records")
        return None
    sequences = list(records.values())
    if any(len(set(sequence)) == 1 for sequence in sequences) or (
        path == "aox_hmm/AOX_ref21.fasta"
        and len(sequences) > 1
        and len(set(sequences)) == 1
    ):
        _s15_aox_error(
            errors,
            "constant_sequence_evidence_forbidden",
            path=path,
        )
        return None
    return records


def _s15_aox_parse_csv(
    text: str,
    *,
    path: str,
    expected_columns: tuple[str, ...],
    errors: list[dict[str, object]],
) -> list[dict[str, str]] | None:
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        fieldnames = tuple(reader.fieldnames or ())
        rows = list(reader)
    except csv.Error as exc:
        _s15_aox_error(
            errors,
            "invalid_csv",
            path=path,
            reason=type(exc).__name__,
        )
        return None
    legacy_fields = sorted(
        S15_AOX_HMM_LEGACY_SCIENTIFIC_FIELDS.intersection(fieldnames)
    )
    if legacy_fields:
        _s15_aox_error(
            errors,
            "legacy_scoring_schema_forbidden",
            path=path,
            fields=legacy_fields,
        )
    if fieldnames != expected_columns:
        _s15_aox_error(
            errors,
            "invalid_csv_columns",
            path=path,
            expected_columns=list(expected_columns),
            actual_columns=list(fieldnames),
        )
        return None
    for row_number, row in enumerate(rows, start=2):
        if None in row or any(value is None for value in row.values()):
            _s15_aox_error(
                errors,
                "invalid_csv_row_shape",
                path=path,
                row=row_number,
            )
            return None
    return [{key: str(value) for key, value in row.items()} for row in rows]


def _s15_aox_fixture_or_legacy_evidence_errors(
    payload: object,
    *,
    path: str,
    errors: list[dict[str, object]],
) -> None:
    fixture_found = False
    legacy_fields: set[str] = set()

    def inspect(value: object) -> None:
        nonlocal fixture_found
        if isinstance(value, dict):
            for raw_key, nested in value.items():
                key = str(raw_key)
                if key in S15_AOX_HMM_LEGACY_SCIENTIFIC_FIELDS:
                    legacy_fields.add(key)
                if key == "fixture" and nested is True:
                    fixture_found = True
                if key == "cutover_eligible" and nested is False:
                    fixture_found = True
                inspect(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                inspect(nested)
        elif isinstance(value, str) and "fixture_non_cutover" in value.casefold():
            fixture_found = True

    inspect(payload)
    if legacy_fields:
        _s15_aox_error(
            errors,
            "legacy_scientific_field_forbidden",
            path=path,
            fields=sorted(legacy_fields),
        )
    if fixture_found:
        _s15_aox_error(errors, "fixture_non_cutover_forbidden", path=path)


def _s15_aox_require_metadata(
    metadata_by_path: dict[str, dict[str, object]],
    *,
    path: str,
    fields: tuple[str, ...],
    errors: list[dict[str, object]],
    error_code: str,
) -> None:
    metadata = metadata_by_path.get(path, {})
    for field in fields:
        if metadata.get(field) in (None, "", [], {}):
            _s15_aox_error(
                errors,
                error_code,
                path=path,
                missing_metadata=field,
            )


def _s15_aox_validate_metadata_values(
    metadata_by_path: dict[str, dict[str, object]],
    *,
    path: str,
    expected: dict[str, object],
    errors: list[dict[str, object]],
    error_code: str,
) -> None:
    metadata = metadata_by_path.get(path, {})
    for field, expected_value in expected.items():
        if metadata.get(field) != expected_value:
            _s15_aox_error(
                errors,
                error_code,
                path=path,
                field=field,
                expected=expected_value,
                actual=metadata.get(field),
            )


def _s15_aox_validate_cdhit_membership(
    rows: list[dict[str, str]] | None,
    *,
    candidates: dict[str, str],
    representatives: dict[str, str] | None,
    errors: list[dict[str, object]],
) -> tuple[set[str], dict[str, str]]:
    path = "aox_hmm/AOX_candidates_cdhit85.clusters.csv"
    if rows is None:
        return set(), {}
    if not candidates:
        if rows:
            _s15_aox_error(
                errors,
                "empty_candidate_membership_not_empty",
                path=path,
                row_count=len(rows),
            )
        if representatives:
            _s15_aox_error(
                errors,
                "empty_candidate_representatives_not_empty",
                path="aox_hmm/AOX_candidates_cdhit85.fasta",
            )
        return set(), {}
    if not rows:
        _s15_aox_error(errors, "cdhit_membership_empty", path=path)
        return set(), {}

    members: dict[str, dict[str, str]] = {}
    clusters: dict[str, list[dict[str, str]]] = {}
    for row_number, row in enumerate(rows, start=2):
        empty_fields = [key for key, value in row.items() if not value.strip()]
        if empty_fields:
            _s15_aox_error(
                errors,
                "cdhit_membership_value_missing",
                path=path,
                row=row_number,
                fields=empty_fields,
            )
            continue
        member_id = row["member_id"]
        if member_id in members:
            _s15_aox_error(
                errors,
                "cdhit_membership_duplicate_member",
                path=path,
                member_id=member_id,
            )
            continue
        if row["is_representative"] not in {"true", "false"}:
            _s15_aox_error(
                errors,
                "cdhit_membership_invalid_representative_flag",
                path=path,
                row=row_number,
            )
        identity_text = row["identity_to_representative"]
        if _S15_AOX_CDHIT_IDENTITY_PATTERN.fullmatch(identity_text) is None:
            _s15_aox_error(
                errors,
                "cdhit_membership_invalid_identity",
                path=path,
                row=row_number,
                value=identity_text,
            )
        else:
            try:
                identity = Decimal(identity_text)
            except InvalidOperation:
                identity = Decimal(-1)
            if not identity.is_finite() or identity < 0 or identity > 1:
                _s15_aox_error(
                    errors,
                    "cdhit_membership_invalid_identity",
                    path=path,
                    row=row_number,
                    value=identity_text,
                )
        try:
            member_length = int(row["member_length"])
        except ValueError:
            member_length = -1
        expected_sequence = candidates.get(member_id)
        if expected_sequence is not None and member_length != len(expected_sequence):
            _s15_aox_error(
                errors,
                "cdhit_membership_length_mismatch",
                path=path,
                member_id=member_id,
                expected=len(expected_sequence),
                actual=member_length,
            )
        members[member_id] = row
        clusters.setdefault(row["cluster_id"], []).append(row)

    missing_members = sorted(set(candidates) - set(members))
    unexpected_members = sorted(set(members) - set(candidates))
    if missing_members or unexpected_members:
        _s15_aox_error(
            errors,
            "cdhit_membership_candidate_mismatch",
            path=path,
            missing_member_ids=missing_members,
            unexpected_member_ids=unexpected_members,
        )

    representative_ids: set[str] = set()
    member_clusters: dict[str, str] = {}
    for cluster_id, cluster_rows in clusters.items():
        representative_rows = [
            row for row in cluster_rows if row["is_representative"] == "true"
        ]
        if len(representative_rows) != 1:
            _s15_aox_error(
                errors,
                "cdhit_membership_representative_count_invalid",
                path=path,
                cluster_id=cluster_id,
                representative_count=len(representative_rows),
            )
            continue
        representative = representative_rows[0]
        representative_id = representative["member_id"]
        representative_ids.add(representative_id)
        if (
            representative["representative_id"] != representative_id
            or representative["identity_to_representative"] != "1.000000"
            or any(
                row["representative_id"] != representative_id for row in cluster_rows
            )
        ):
            _s15_aox_error(
                errors,
                "cdhit_membership_representative_inconsistent",
                path=path,
                cluster_id=cluster_id,
            )
        for row in cluster_rows:
            member_clusters[row["member_id"]] = cluster_id

    actual_representatives = set(representatives or {})
    if actual_representatives != representative_ids:
        _s15_aox_error(
            errors,
            "cdhit_representative_fasta_mismatch",
            path="aox_hmm/AOX_candidates_cdhit85.fasta",
            missing_representative_ids=sorted(
                representative_ids - actual_representatives
            ),
            unexpected_representative_ids=sorted(
                actual_representatives - representative_ids
            ),
        )
    for representative_id in sorted(representative_ids & actual_representatives):
        if representatives is not None and representatives[
            representative_id
        ] != candidates.get(representative_id):
            _s15_aox_error(
                errors,
                "cdhit_representative_sequence_mismatch",
                path="aox_hmm/AOX_candidates_cdhit85.fasta",
                representative_id=representative_id,
            )
    return representative_ids, member_clusters


def _s15_aox_validate_final_artifacts(
    artifact_paths: set[str],
    artifact_text_by_path: dict[str, str],
    artifact_metadata_by_path: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    missing = _s15_aox_missing_required_paths(artifact_paths)
    legacy_paths = _s15_aox_legacy_paths_present(artifact_paths)
    metadata_by_path = artifact_metadata_by_path or {}
    execution_summary: dict[str, object] = {}
    errors: list[dict[str, object]] = []
    if missing:
        errors.append({"error_code": "live_artifact_missing", "missing_paths": missing})
    for path in legacy_paths:
        errors.append({"error_code": "legacy_artifact_path_forbidden", "path": path})

    summary_text = artifact_text_by_path.get("aox_hmm/execution_summary.json", "")
    if "aox_hmm/execution_summary.json" in artifact_paths:
        try:
            loaded_summary = json.loads(
                summary_text,
                object_pairs_hook=_s15_aox_reject_duplicate_json_keys,
            )
        except (json.JSONDecodeError, ValueError):
            _s15_aox_error(
                errors,
                "invalid_json",
                path="aox_hmm/execution_summary.json",
            )
        else:
            if isinstance(loaded_summary, dict):
                execution_summary = loaded_summary
            else:
                _s15_aox_error(
                    errors,
                    "invalid_json",
                    path="aox_hmm/execution_summary.json",
                )

    _s15_aox_fixture_or_legacy_evidence_errors(
        execution_summary,
        path="aox_hmm/execution_summary.json",
        errors=errors,
    )
    for path, metadata in sorted(metadata_by_path.items()):
        if path in S15_AOX_HMM_FIXED_DELIVERABLES:
            _s15_aox_fixture_or_legacy_evidence_errors(
                metadata,
                path=path,
                errors=errors,
            )

    reference_path = "aox_hmm/AOX_ref21.fasta"
    reference_text = artifact_text_by_path.get(reference_path, "")
    reference_records: dict[str, str] | None = None
    reference_digest = _s15_aox_content_digest(reference_text)
    if reference_path in artifact_paths:
        reference_records = _s15_aox_parse_fasta(
            reference_text,
            path=reference_path,
            errors=errors,
            allow_empty=False,
        )
        metadata = metadata_by_path.get(reference_path, {})
        if metadata.get("accession_count") != len(AOX_HMM_ACCESSIONS):
            _s15_aox_error(
                errors,
                "invalid_accession_count",
                path=reference_path,
                accession_count=metadata.get("accession_count"),
            )
        _s15_aox_require_metadata(
            metadata_by_path,
            path=reference_path,
            fields=("source_ncbi_fasta_artifact_id", "provider_request_ids"),
            errors=errors,
            error_code="provider_provenance_incomplete",
        )
        _s15_aox_validate_metadata_values(
            metadata_by_path,
            path=reference_path,
            expected={
                "contract_id": (
                    aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID
                ),
                "contract_digest": (
                    aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
                ),
                "implementation_digest": (
                    aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
                ),
                "output_digest": reference_digest,
                "output_name": aox_reference.HMM_REFERENCE_SET_OUTPUT_NAME,
                "selected_accessions": list(AOX_HMM_ACCESSIONS),
                "excluded_accessions": [
                    aox_reference.SCORING_REFERENCE_ACCESSION
                ],
                "identity_replacement_count": 0,
                "ncbi_reference_accessions": list(AOX_NCBI_ACCESSIONS),
            },
            errors=errors,
            error_code="hmm_reference_selection_metadata_mismatch",
        )
        if reference_records is not None:
            actual_ids = tuple(reference_records)
            if actual_ids != AOX_HMM_ACCESSIONS:
                _s15_aox_error(
                    errors,
                    "hmm_reference_identity_order_mismatch",
                    path=reference_path,
                    expected=list(AOX_HMM_ACCESSIONS),
                    actual=list(actual_ids),
                )
            canonical_reference_text = "".join(
                f">{accession}\n{reference_records[accession]}\n"
                for accession in reference_records
            )
            if reference_text != canonical_reference_text:
                _s15_aox_error(
                    errors,
                    "hmm_reference_fasta_not_canonical",
                    path=reference_path,
                )

    scoring_reference_path = (
        "aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta"
    )
    scoring_reference_text = artifact_text_by_path.get(
        scoring_reference_path,
        "",
    )
    scoring_reference_records: dict[str, str] | None = None
    scoring_reference_digest = _s15_aox_content_digest(scoring_reference_text)
    if scoring_reference_path in artifact_paths:
        scoring_reference_records = _s15_aox_parse_fasta(
            scoring_reference_text,
            path=scoring_reference_path,
            errors=errors,
            allow_empty=False,
        )
        _s15_aox_require_metadata(
            metadata_by_path,
            path=scoring_reference_path,
            fields=("source_ncbi_fasta_artifact_id", "provider_request_ids"),
            errors=errors,
            error_code="provider_provenance_incomplete",
        )
        _s15_aox_validate_metadata_values(
            metadata_by_path,
            path=scoring_reference_path,
            expected={
                "contract_id": (
                    aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID
                ),
                "contract_digest": (
                    aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST
                ),
                "implementation_digest": (
                    aox_reference.SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
                ),
                "output_digest": scoring_reference_digest,
                "output_name": aox_reference.SCORING_REFERENCE_OUTPUT_NAME,
                "reference_accession": (
                    aox_reference.SCORING_REFERENCE_ACCESSION
                ),
                "identity_replacement_count": 0,
                "ncbi_reference_accessions": list(AOX_NCBI_ACCESSIONS),
            },
            errors=errors,
            error_code="scoring_reference_selection_metadata_mismatch",
        )
        if scoring_reference_records is not None:
            expected_reference_ids = (
                aox_reference.SCORING_REFERENCE_ACCESSION,
            )
            actual_ids = tuple(scoring_reference_records)
            if actual_ids != expected_reference_ids:
                _s15_aox_error(
                    errors,
                    "scoring_reference_identity_mismatch",
                    path=scoring_reference_path,
                    expected=list(expected_reference_ids),
                    actual=list(actual_ids),
                )
            canonical_scoring_reference_text = "".join(
                f">{accession}\n{scoring_reference_records[accession]}\n"
                for accession in scoring_reference_records
            )
            if scoring_reference_text != canonical_scoring_reference_text:
                _s15_aox_error(
                    errors,
                    "scoring_reference_fasta_not_canonical",
                    path=scoring_reference_path,
                )

    if reference_path in artifact_paths and scoring_reference_path in artifact_paths:
        reference_metadata = metadata_by_path.get(reference_path, {})
        scoring_reference_metadata = metadata_by_path.get(
            scoring_reference_path,
            {},
        )
        for field in (
            "input_digest",
            "source_ncbi_fasta_artifact_id",
            "provider_request_ids",
            "ncbi_reference_accessions",
        ):
            if reference_metadata.get(field) != scoring_reference_metadata.get(field):
                _s15_aox_error(
                    errors,
                    "reference_selection_source_mismatch",
                    path=scoring_reference_path,
                    field=field,
                    hmm_reference_value=reference_metadata.get(field),
                    scoring_reference_value=scoring_reference_metadata.get(field),
                )

    target_path = "aox_hmm/target.fasta"
    target_text = artifact_text_by_path.get(target_path, "")
    target_records: dict[str, str] | None = None
    if target_path in artifact_paths:
        target_records = _s15_aox_parse_fasta(
            target_text,
            path=target_path,
            errors=errors,
            allow_empty=True,
        )
        if not target_text.strip():
            warning_count = execution_summary.get("warning_count")
            if (
                isinstance(warning_count, bool)
                or not isinstance(warning_count, int)
                or warning_count <= 0
            ):
                _s15_aox_error(
                    errors,
                    "empty_target_warning_missing",
                    path=target_path,
                )

    scoring_input_path = "aox_hmm/AOX_scoring_input.fasta"
    scoring_input_text = artifact_text_by_path.get(scoring_input_path, "")
    scoring_input_result: aox_reference.ScoringInputAssemblyResult | None = None
    if scoring_input_path in artifact_paths:
        try:
            scoring_input_result = aox_reference.assemble_scoring_input(
                scoring_reference_text,
                target_text,
                expected_contract_id=(
                    aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID
                ),
                expected_contract_digest=(
                    aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST
                ),
                expected_implementation_digest=(
                    aox_reference.SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST
                ),
            )
        except aox_reference.ScientificPrerequisiteError as exc:
            _s15_aox_error(
                errors,
                "scoring_input_assembly_recalculation_failed",
                path=scoring_input_path,
                scientific_error=exc.to_dict(),
            )
        else:
            if scoring_input_text != scoring_input_result.to_fasta():
                _s15_aox_error(
                    errors,
                    "scoring_input_assembly_mismatch",
                    path=scoring_input_path,
                )
            expected_scoring_input_metadata = scoring_input_result.metadata()
            _s15_aox_validate_metadata_values(
                metadata_by_path,
                path=scoring_input_path,
                expected={
                    "contract_id": expected_scoring_input_metadata["contract_id"],
                    "contract_digest": expected_scoring_input_metadata[
                        "contract_digest"
                    ],
                    "implementation_digest": expected_scoring_input_metadata[
                        "implementation_digest"
                    ],
                    "input_digests": expected_scoring_input_metadata[
                        "input_digests"
                    ],
                    "output_digest": expected_scoring_input_metadata["output_digest"],
                    "output_name": expected_scoring_input_metadata["output_name"],
                    "reference_accession": expected_scoring_input_metadata[
                        "reference_accession"
                    ],
                    "target_accessions": expected_scoring_input_metadata[
                        "target_accessions"
                    ],
                    "ordering": expected_scoring_input_metadata["ordering"],
                    "healthy_empty": expected_scoring_input_metadata["healthy_empty"],
                },
                errors=errors,
                error_code="scoring_input_assembly_metadata_mismatch",
            )
        _s15_aox_require_metadata(
            metadata_by_path,
            path=scoring_input_path,
            fields=(
                "source_scoring_reference_artifact_id",
                "source_target_fasta_artifact_id",
            ),
            errors=errors,
            error_code="scoring_input_assembly_provenance_incomplete",
        )

    hmm_path = "aox_hmm/AOX_ref.hmm"
    hmm_text = artifact_text_by_path.get(hmm_path, "")
    hmm_digest = _s15_aox_content_digest(hmm_text)
    if hmm_path in artifact_paths:
        if not hmm_text.startswith("HMMER3"):
            _s15_aox_error(errors, "invalid_hmm", path=hmm_path)
        metadata = metadata_by_path.get(hmm_path, {})
        for key in (
            "source_reference_fasta_artifact_id",
            "source_reference_fasta_digest",
            "mafft_artifact_ids",
            "hmmbuild_artifact_ids",
        ):
            if metadata.get(key) in (None, "", [], {}):
                _s15_aox_error(
                    errors,
                    "hmm_provenance_incomplete",
                    path=hmm_path,
                    missing_metadata=key,
                )
        if metadata.get("source_reference_fasta_digest") != reference_digest:
            _s15_aox_error(
                errors,
                "hmm_reference_digest_mismatch",
                path=hmm_path,
                expected=reference_digest,
                actual=metadata.get("source_reference_fasta_digest"),
            )

    hit_csv_specs = {
        "aox_hmm/hits_raw.csv": (
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
        ),
        "aox_hmm/hmmer_score_filtered_accessions.csv": (
            "accession",
            "target",
            "evalue_numeric",
            "score_numeric",
            "raw_page_digest",
            "raw_hit_digest",
            "parsed_row_digest",
        ),
        "aox_hmm/hits_len650_700_200.csv": (
            "target",
            "uniprot_accession",
            "hmm_score",
            "evalue",
            "length",
            "sequence",
        ),
    }
    parsed_csv: dict[str, list[dict[str, str]] | None] = {}
    for path, columns in hit_csv_specs.items():
        if path in artifact_paths:
            parsed_csv[path] = _s15_aox_parse_csv(
                artifact_text_by_path.get(path, ""),
                path=path,
                expected_columns=columns,
                errors=errors,
            )

    raw_hits_path = "aox_hmm/hits_raw.csv"
    score_filtered_path = "aox_hmm/hmmer_score_filtered_accessions.csv"
    score_filter_result: aox_hmmer.ScoreFilteredAccessionsResult | None = None
    if raw_hits_path in artifact_paths and score_filtered_path in artifact_paths:
        try:
            score_filter_result = aox_hmmer.parse_and_filter_csv(
                artifact_text_by_path.get(raw_hits_path, ""),
                expected_contract_id=aox_hmmer.CONTRACT_ID,
                expected_contract_digest=aox_hmmer.CONTRACT_DIGEST,
                expected_implementation_digest=aox_hmmer.IMPLEMENTATION_DIGEST,
            )
            expected_score_filtered = score_filter_result.to_csv()
        except ValueError as exc:
            _s15_aox_error(
                errors,
                "hmmer_score_filter_input_invalid",
                path=raw_hits_path,
                detail=type(exc).__name__,
            )
        else:
            if artifact_text_by_path.get(score_filtered_path, "") != (
                expected_score_filtered
            ):
                _s15_aox_error(
                    errors,
                    "hmmer_score_filter_output_mismatch",
                    path=score_filtered_path,
                )
            _s15_aox_validate_metadata_values(
                metadata_by_path,
                path=score_filtered_path,
                expected=score_filter_result.metadata(),
                errors=errors,
                error_code="hmmer_score_filter_metadata_mismatch",
            )
            _s15_aox_require_metadata(
                metadata_by_path,
                path=score_filtered_path,
                fields=("source_provider_parsed_artifact_id",),
                errors=errors,
                error_code="hmmer_score_filter_provenance_incomplete",
            )

    scoring_result: aox_motif.ScoringResult | None = None
    scoring_alignment_path = "aox_hmm/AOX_scoring_alignment.fasta"
    if scoring_alignment_path in artifact_paths:
        try:
            scoring_result = aox_motif.score_aligned_fasta(
                artifact_text_by_path.get(scoring_alignment_path, ""),
            )
        except aox_motif.ScientificPrerequisiteError as exc:
            _s15_aox_error(
                errors,
                "motif_scoring_recalculation_failed",
                path=scoring_alignment_path,
                scientific_error=exc.to_dict(),
            )
        if scoring_result is not None:
            for record in scoring_result.alignment.records:
                if (
                    any(
                        marker in record.aligned_sequence
                        or marker in record.description.upper()
                        for marker in _S15_AOX_SYNTHETIC_MARKERS
                    )
                    or not record.sequence
                    or len(set(record.sequence)) == 1
                ):
                    _s15_aox_error(
                        errors,
                        "synthetic_sequence_evidence_forbidden",
                        path=scoring_alignment_path,
                        sequence_id=record.sequence_id,
                    )
        _s15_aox_require_metadata(
            metadata_by_path,
            path=scoring_alignment_path,
            fields=(
                "source_hmm_artifact_id",
                "source_hmm_digest",
                "source_scoring_input_artifact_id",
                "source_scoring_input_digest",
                "alignment_operation_artifact_ids",
            ),
            errors=errors,
            error_code="motif_alignment_provenance_incomplete",
        )
        alignment_metadata = metadata_by_path.get(scoring_alignment_path, {})
        if (
            alignment_metadata.get("reference_accession")
            != aox_motif.REFERENCE_ACCESSION
        ):
            _s15_aox_error(
                errors,
                "motif_alignment_reference_mismatch",
                path=scoring_alignment_path,
                expected=aox_motif.REFERENCE_ACCESSION,
                actual=alignment_metadata.get("reference_accession"),
            )
        expected_alignment_metadata = {
            "source_hmm_digest": hmm_digest,
            "source_scoring_input_digest": (
                scoring_input_result.output_digest
                if scoring_input_result is not None
                else _s15_aox_content_digest(scoring_input_text)
            ),
        }
        _s15_aox_validate_metadata_values(
            metadata_by_path,
            path=scoring_alignment_path,
            expected=expected_alignment_metadata,
            errors=errors,
            error_code="motif_alignment_input_digest_mismatch",
        )
        if scoring_result is not None and scoring_input_result is not None:
            alignment_sequence_ids = {
                record.sequence_id for record in scoring_result.alignment.records
            }
            expected_sequence_ids = {
                record.sequence_id for record in scoring_input_result.records
            }
            if alignment_sequence_ids != expected_sequence_ids:
                _s15_aox_error(
                    errors,
                    "hmmalign_scoring_input_identity_mismatch",
                    path=scoring_alignment_path,
                    expected=sorted(expected_sequence_ids),
                    actual=sorted(alignment_sequence_ids),
                )

    scored_path = "aox_hmm/scored_ref_plus_hits.csv"
    if scored_path in artifact_paths:
        scored_text = artifact_text_by_path.get(scored_path, "")
        _s15_aox_parse_csv(
            scored_text,
            path=scored_path,
            expected_columns=tuple(aox_motif.CANONICAL_COLUMNS),
            errors=errors,
        )
        if scoring_result is not None and scored_text != scoring_result.to_csv():
            _s15_aox_error(
                errors,
                "motif_scoring_recalculation_mismatch",
                path=scored_path,
            )
        metadata = metadata_by_path.get(scored_path, {})
        expected_metadata = {
            "scoring_contract_id": aox_motif.CONTRACT_ID,
            "scoring_contract_digest": aox_motif.CONTRACT_DIGEST,
            "scoring_implementation_digest": aox_motif.IMPLEMENTATION_DIGEST,
            "reference_accession": aox_motif.REFERENCE_ACCESSION,
        }
        if scoring_result is not None:
            expected_metadata.update(
                {
                    "input_digest": scoring_result.alignment.input_digest,
                    "alignment_digest": scoring_result.alignment.alignment_digest,
                }
            )
        for key, expected in expected_metadata.items():
            if metadata.get(key) != expected:
                _s15_aox_error(
                    errors,
                    "motif_scoring_metadata_mismatch",
                    path=scored_path,
                    field=key,
                    expected=expected,
                    actual=metadata.get(key),
                )
        if metadata.get("source_alignment_artifact_id") in (None, "", [], {}):
            _s15_aox_error(
                errors,
                "motif_scoring_provenance_incomplete",
                path=scored_path,
                missing_metadata="source_alignment_artifact_id",
            )

    filtered_rows = parsed_csv.get("aox_hmm/hits_len650_700_200.csv")
    filtered_sequences: dict[str, str] = {}
    if filtered_rows is not None:
        for row_number, row in enumerate(filtered_rows, start=2):
            accession = row["uniprot_accession"]
            sequence = row["sequence"].upper()
            if not accession or accession in filtered_sequences:
                _s15_aox_error(
                    errors,
                    "filtered_hit_identity_invalid",
                    path="aox_hmm/hits_len650_700_200.csv",
                    row=row_number,
                    uniprot_accession=accession,
                )
                continue
            if _S15_AOX_SEQUENCE_PATTERN.fullmatch(sequence) is None or any(
                marker in sequence for marker in _S15_AOX_SYNTHETIC_MARKERS
            ):
                _s15_aox_error(
                    errors,
                    "synthetic_sequence_evidence_forbidden",
                    path="aox_hmm/hits_len650_700_200.csv",
                    row=row_number,
                    sequence_id=accession,
                )
                continue
            try:
                length = int(row["length"])
                hmm_score = Decimal(row["hmm_score"])
            except (ValueError, InvalidOperation):
                _s15_aox_error(
                    errors,
                    "filtered_hit_numeric_field_invalid",
                    path="aox_hmm/hits_len650_700_200.csv",
                    row=row_number,
                )
                continue
            if (
                not hmm_score.is_finite()
                or length != len(sequence)
                or not 650 <= length <= 700
                or hmm_score <= 200
            ):
                _s15_aox_error(
                    errors,
                    "filtered_hit_threshold_or_length_mismatch",
                    path="aox_hmm/hits_len650_700_200.csv",
                    row=row_number,
                    observed_length=length,
                    sequence_length=len(sequence),
                    hmm_score=row["hmm_score"],
                )
            filtered_sequences[accession] = sequence

    if target_records is not None:
        for accession, sequence in sorted(filtered_sequences.items()):
            if target_records.get(accession) != sequence:
                _s15_aox_error(
                    errors,
                    "filtered_hit_target_sequence_mismatch",
                    path="aox_hmm/hits_len650_700_200.csv",
                    sequence_id=accession,
                )

    expected_candidates: dict[str, str] = {}
    if scoring_result is not None and filtered_rows is not None:
        score_rows = {row.sequence_id: row for row in scoring_result.rows}
        alignment_sequences = {
            record.sequence_id: record.sequence
            for record in scoring_result.alignment.records
        }
        expected_scoring_ids = set(filtered_sequences) | {aox_motif.REFERENCE_ACCESSION}
        if set(score_rows) != expected_scoring_ids:
            _s15_aox_error(
                errors,
                "motif_scoring_hit_lineage_mismatch",
                path=scoring_alignment_path,
                missing_sequence_ids=sorted(expected_scoring_ids - set(score_rows)),
                unexpected_sequence_ids=sorted(set(score_rows) - expected_scoring_ids),
            )
        for accession, sequence in sorted(filtered_sequences.items()):
            scored = score_rows.get(accession)
            if scored is None:
                continue
            if alignment_sequences.get(accession) != sequence:
                _s15_aox_error(
                    errors,
                    "motif_scoring_sequence_mismatch",
                    path=scoring_alignment_path,
                    sequence_id=accession,
                )
                continue
            if scored.passes_motif_rule:
                expected_candidates[accession] = sequence

    candidates_path = "aox_hmm/AOX_candidates.fasta"
    candidates: dict[str, str] | None = None
    if candidates_path in artifact_paths:
        candidates = _s15_aox_parse_fasta(
            artifact_text_by_path.get(candidates_path, ""),
            path=candidates_path,
            errors=errors,
            allow_empty=True,
        )
        if candidates is not None and candidates != expected_candidates:
            _s15_aox_error(
                errors,
                "motif_candidate_fasta_mismatch",
                path=candidates_path,
                expected_sequence_ids=sorted(expected_candidates),
                actual_sequence_ids=sorted(candidates),
            )
        _s15_aox_require_metadata(
            metadata_by_path,
            path=candidates_path,
            fields=("source_scored_artifact_id", "source_alignment_artifact_id"),
            errors=errors,
            error_code="motif_candidate_provenance_incomplete",
        )

    representatives_path = "aox_hmm/AOX_candidates_cdhit85.fasta"
    representatives: dict[str, str] | None = None
    if representatives_path in artifact_paths:
        representatives = _s15_aox_parse_fasta(
            artifact_text_by_path.get(representatives_path, ""),
            path=representatives_path,
            errors=errors,
            allow_empty=True,
        )
        _s15_aox_require_metadata(
            metadata_by_path,
            path=representatives_path,
            fields=(
                (
                    "source_candidate_fasta_artifact_id",
                    "source_membership_artifact_id",
                    "cdhit_operation_artifact_ids",
                )
                if candidates
                else (
                    "source_candidate_fasta_artifact_id",
                    "source_membership_artifact_id",
                )
            ),
            errors=errors,
            error_code="cdhit_representative_provenance_incomplete",
        )

    membership_path = "aox_hmm/AOX_candidates_cdhit85.clusters.csv"
    membership_rows: list[dict[str, str]] | None = None
    if membership_path in artifact_paths:
        membership_rows = _s15_aox_parse_csv(
            artifact_text_by_path.get(membership_path, ""),
            path=membership_path,
            expected_columns=S15_AOX_HMM_CDHIT_MEMBERSHIP_COLUMNS,
            errors=errors,
        )
        metadata = metadata_by_path.get(membership_path, {})
        if metadata.get("membership_schema_id") != "cdhit_cluster_membership@1":
            _s15_aox_error(
                errors,
                "cdhit_membership_metadata_mismatch",
                path=membership_path,
                field="membership_schema_id",
            )
        if metadata.get("source_candidate_fasta_artifact_id") in (None, "", [], {}):
            _s15_aox_error(
                errors,
                "cdhit_membership_provenance_incomplete",
                path=membership_path,
                missing_metadata="source_candidate_fasta_artifact_id",
            )
        if metadata.get("cdhit_identity_ppm") != aox_similarity.DEFAULT_THRESHOLD_PPM:
            _s15_aox_error(
                errors,
                "cdhit_membership_metadata_mismatch",
                path=membership_path,
                field="cdhit_identity_ppm",
                expected=aox_similarity.DEFAULT_THRESHOLD_PPM,
                actual=metadata.get("cdhit_identity_ppm"),
            )
        if candidates and metadata.get("cdhit_operation_artifact_ids") in (
            None,
            "",
            [],
            {},
        ):
            _s15_aox_error(
                errors,
                "cdhit_membership_provenance_incomplete",
                path=membership_path,
                missing_metadata="cdhit_operation_artifact_ids",
            )
        if not candidates:
            empty_result = execution_summary.get("empty_result")
            expected_reason = (
                str(empty_result.get("reason") or "").strip()
                if isinstance(empty_result, dict)
                else ""
            )
            if (
                metadata.get("empty_result_reason") != expected_reason
                or not expected_reason
            ):
                _s15_aox_error(
                    errors,
                    "cdhit_empty_membership_reason_mismatch",
                    path=membership_path,
                    expected=expected_reason,
                    actual=metadata.get("empty_result_reason"),
                )

    representative_ids, _ = _s15_aox_validate_cdhit_membership(
        membership_rows,
        candidates=candidates or {},
        representatives=representatives,
        errors=errors,
    )

    graph_result: aox_similarity.SimilarityGraphResult | None = None
    graph_paths = {
        candidates_path,
        membership_path,
        "aox_hmm/nodes.csv",
        "aox_hmm/edges_similarity.csv",
        "aox_hmm/similarity_graph_manifest.json",
    }
    if graph_paths <= artifact_paths:
        empty_result = execution_summary.get("empty_result")
        empty_result_reason = (
            str(empty_result.get("reason") or "").strip()
            if isinstance(empty_result, dict)
            else None
        )
        if candidates:
            empty_result_reason = None
        try:
            graph_result = aox_similarity.validate_graph_artifacts(
                artifact_text_by_path.get(candidates_path, ""),
                artifact_text_by_path.get(membership_path, ""),
                artifact_text_by_path.get("aox_hmm/nodes.csv", ""),
                artifact_text_by_path.get("aox_hmm/edges_similarity.csv", ""),
                artifact_text_by_path.get("aox_hmm/similarity_graph_manifest.json", ""),
                threshold_ppm=aox_similarity.DEFAULT_THRESHOLD_PPM,
                empty_result_reason=empty_result_reason,
            )
        except aox_motif.ScientificPrerequisiteError as exc:
            _s15_aox_error(
                errors,
                "similarity_graph_recalculation_failed",
                path="aox_hmm/similarity_graph_manifest.json",
                scientific_error=exc.to_dict(),
            )
        manifest_metadata = metadata_by_path.get(
            "aox_hmm/similarity_graph_manifest.json", {}
        )
        expected_manifest_metadata = {
            "manifest_schema_id": aox_similarity.MANIFEST_SCHEMA_ID,
            "node_schema_id": aox_similarity.NODE_SCHEMA_ID,
            "edge_schema_id": aox_similarity.EDGE_SCHEMA_ID,
            "similarity_calculation_id": aox_similarity.CALCULATION_ID,
            "similarity_calculation_digest": aox_similarity.CALCULATION_DIGEST,
            "similarity_implementation_digest": aox_similarity.IMPLEMENTATION_DIGEST,
        }
        for key, expected in expected_manifest_metadata.items():
            if manifest_metadata.get(key) != expected:
                _s15_aox_error(
                    errors,
                    "similarity_graph_metadata_mismatch",
                    path="aox_hmm/similarity_graph_manifest.json",
                    field=key,
                    expected=expected,
                    actual=manifest_metadata.get(key),
                )
        _s15_aox_require_metadata(
            metadata_by_path,
            path="aox_hmm/similarity_graph_manifest.json",
            fields=(
                "source_candidate_fasta_artifact_id",
                "source_membership_artifact_id",
                "nodes_artifact_id",
                "edges_artifact_id",
            ),
            errors=errors,
            error_code="similarity_graph_provenance_incomplete",
        )

    scientific_branch: str | None = None
    omitted_operation_roles: list[str] | None = None
    expected_empty_reason: str | None = None
    if score_filter_result is not None:
        if not score_filter_result.hits:
            scientific_branch = "hmmer_upstream_empty"
            omitted_operation_roles = [
                "candidate_alignment",
                "cdhit",
                "uniprot_fetch",
            ]
            expected_empty_reason = (
                "no_hmmer_hits"
                if score_filter_result.input_row_count == 0
                else "no_filtered_hmmer_accessions"
            )
        elif not filtered_sequences:
            scientific_branch = "length_filter_empty"
            omitted_operation_roles = ["candidate_alignment", "cdhit"]
            expected_empty_reason = "no_candidates_after_length_filter"
        elif not expected_candidates:
            scientific_branch = "motif_filter_empty"
            omitted_operation_roles = ["cdhit"]
            expected_empty_reason = "no_candidates_after_motif_filter"
        else:
            scientific_branch = "nonempty"
            omitted_operation_roles = []

    if execution_summary:
        missing_fields = sorted(
            S15_AOX_HMM_REQUIRED_SUMMARY_FIELDS - set(execution_summary)
        )
        if missing_fields:
            _s15_aox_error(
                errors,
                "invalid_execution_summary",
                path="aox_hmm/execution_summary.json",
                missing_fields=missing_fields,
            )
        expected_values: dict[str, object] = {
            "accession_count": len(AOX_HMM_ACCESSIONS),
            "ncbi_reference_accession_count": len(AOX_NCBI_ACCESSIONS),
            "filtered_hit_count": len(filtered_sequences),
            "scoring_row_count": len(scoring_result.rows)
            if scoring_result is not None
            else None,
            "candidate_count": len(expected_candidates),
            "representative_count": len(representative_ids),
            "graph_node_count": len(graph_result.nodes)
            if graph_result is not None
            else None,
            "graph_edge_count": len(graph_result.edges)
            if graph_result is not None
            else None,
            "length_filter": [650, 700],
            "hmm_score_threshold": 200,
            "motif_rule_score_threshold_tenths": aox_motif.THRESHOLD_TENTHS,
            "motif_rule_score_threshold": aox_motif.THRESHOLD_DISPLAY,
            "similarity_threshold_ppm": aox_similarity.DEFAULT_THRESHOLD_PPM,
            "similarity_threshold": "0.850000",
            "hmmer_database": "refprot",
            "hmmer_score_filter_contract_id": aox_hmmer.CONTRACT_ID,
            "hmmer_score_filter_contract_digest": aox_hmmer.CONTRACT_DIGEST,
            "hmmer_score_filter_implementation_digest": (
                aox_hmmer.IMPLEMENTATION_DIGEST
            ),
            "hmmer_score_filter_input_digest": (
                score_filter_result.input_digest
                if score_filter_result is not None
                else None
            ),
            "hmmer_score_filter_output_digest": (
                score_filter_result.output_digest
                if score_filter_result is not None
                else None
            ),
            "sequence_length_join_contract_id": aox_sequence_join.CONTRACT_ID,
            "sequence_length_join_contract_digest": (
                aox_sequence_join.CONTRACT_DIGEST
            ),
            "sequence_length_join_implementation_digest": (
                aox_sequence_join.IMPLEMENTATION_DIGEST
            ),
            "sequence_length_join_hits_digest": _s15_aox_content_digest(
                artifact_text_by_path.get(
                    "aox_hmm/hits_len650_700_200.csv",
                    "",
                )
            ),
            "sequence_length_join_target_digest": _s15_aox_content_digest(
                target_text
            ),
            "hmm_reference_set_selection_contract_id": (
                aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_ID
            ),
            "hmm_reference_set_selection_contract_digest": (
                aox_reference.HMM_REFERENCE_SET_SELECTION_CONTRACT_DIGEST
            ),
            "hmm_reference_set_selection_implementation_digest": (
                aox_reference.HMM_REFERENCE_SET_SELECTION_IMPLEMENTATION_DIGEST
            ),
            "hmm_reference_set_input_digest": metadata_by_path.get(
                reference_path,
                {},
            ).get("input_digest"),
            "hmm_reference_set_output_digest": reference_digest,
            "scoring_reference_selection_contract_id": (
                aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_ID
            ),
            "scoring_reference_selection_contract_digest": (
                aox_reference.SCORING_REFERENCE_SELECTION_CONTRACT_DIGEST
            ),
            "scoring_reference_selection_implementation_digest": (
                aox_reference.SCORING_REFERENCE_SELECTION_IMPLEMENTATION_DIGEST
            ),
            "scoring_reference_selection_input_digest": metadata_by_path.get(
                scoring_reference_path,
                {},
            ).get("input_digest"),
            "scoring_reference_output_digest": scoring_reference_digest,
            "scoring_input_assembly_contract_id": (
                aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_ID
            ),
            "scoring_input_assembly_contract_digest": (
                aox_reference.SCORING_INPUT_ASSEMBLY_CONTRACT_DIGEST
            ),
            "scoring_input_assembly_implementation_digest": (
                aox_reference.SCORING_INPUT_ASSEMBLY_IMPLEMENTATION_DIGEST
            ),
            "scoring_reference_input_digest": (
                scoring_input_result.scoring_reference_input_digest
                if scoring_input_result is not None
                else None
            ),
            "post_uniprot_target_input_digest": (
                scoring_input_result.target_input_digest
                if scoring_input_result is not None
                else None
            ),
            "scoring_contract_id": aox_motif.CONTRACT_ID,
            "scoring_contract_digest": aox_motif.CONTRACT_DIGEST,
            "scoring_implementation_digest": aox_motif.IMPLEMENTATION_DIGEST,
            "scoring_reference_accession": aox_motif.REFERENCE_ACCESSION,
            "scoring_input_digest": (
                scoring_input_result.output_digest
                if scoring_input_result is not None
                else None
            ),
            "scoring_alignment_input_digest": (
                scoring_result.alignment.input_digest
                if scoring_result is not None
                else None
            ),
            "scoring_alignment_digest": (
                scoring_result.alignment.alignment_digest
                if scoring_result is not None
                else None
            ),
            "cdhit_membership_schema_id": "cdhit_cluster_membership@1",
            "similarity_calculation_id": aox_similarity.CALCULATION_ID,
            "similarity_calculation_digest": aox_similarity.CALCULATION_DIGEST,
            "similarity_implementation_digest": aox_similarity.IMPLEMENTATION_DIGEST,
            "candidate_graph_manifest_schema_id": aox_similarity.MANIFEST_SCHEMA_ID,
            "candidate_graph_node_schema_id": aox_similarity.NODE_SCHEMA_ID,
            "candidate_graph_edge_schema_id": aox_similarity.EDGE_SCHEMA_ID,
            "candidate_graph_manifest_digest": _s15_aox_content_digest(
                artifact_text_by_path.get("aox_hmm/similarity_graph_manifest.json", "")
            ),
            "scientific_outcome": "candidates_found"
            if expected_candidates
            else "empty",
            "scientific_branch": scientific_branch,
            "omitted_operation_roles": omitted_operation_roles,
        }
        for key, expected in expected_values.items():
            if expected is not None and execution_summary.get(key) != expected:
                _s15_aox_error(
                    errors,
                    "invalid_execution_summary_value",
                    path="aox_hmm/execution_summary.json",
                    field=key,
                    expected=expected,
                    actual=execution_summary.get(key),
                )
        for digest_field in (
            "hmm_reference_set_input_digest",
            "scoring_reference_selection_input_digest",
        ):
            if not _s15_is_digest(execution_summary.get(digest_field)):
                _s15_aox_error(
                    errors,
                    "invalid_execution_summary_digest",
                    path="aox_hmm/execution_summary.json",
                    field=digest_field,
                )
        upstream_skip_digest = execution_summary.get(
            "upstream_empty_skip_receipt_digest"
        )
        if scientific_branch == "hmmer_upstream_empty":
            if not _s15_is_digest(upstream_skip_digest):
                _s15_aox_error(
                    errors,
                    "upstream_empty_skip_receipt_digest_missing",
                    path="aox_hmm/execution_summary.json",
                )
        elif upstream_skip_digest is not None:
            _s15_aox_error(
                errors,
                "unexpected_upstream_empty_skip_receipt_digest",
                path="aox_hmm/execution_summary.json",
                scientific_branch=scientific_branch,
            )
        for count_field in (
            "accession_count",
            "ncbi_reference_accession_count",
            "filtered_hit_count",
            "scoring_row_count",
            "candidate_count",
            "representative_count",
            "graph_node_count",
            "graph_edge_count",
            "warning_count",
            "motif_rule_score_threshold_tenths",
            "similarity_threshold_ppm",
        ):
            value = execution_summary.get(count_field)
            if count_field in execution_summary and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                _s15_aox_error(
                    errors,
                    "invalid_execution_summary_type",
                    path="aox_hmm/execution_summary.json",
                    field=count_field,
                )
        normalized_paths = execution_summary.get("normalized_final_deliverable_paths")
        if (
            not isinstance(normalized_paths, list)
            or any(not isinstance(path, str) or not path for path in normalized_paths)
            or len(normalized_paths) != len(set(normalized_paths))
            or set(normalized_paths) != S15_AOX_HMM_FIXED_DELIVERABLES
        ):
            _s15_aox_error(
                errors,
                "invalid_normalized_final_deliverable_paths",
                path="aox_hmm/execution_summary.json",
            )
        artifact_ids = execution_summary.get("artifact_ids")
        if (
            not isinstance(artifact_ids, list)
            or len(artifact_ids) < len(S15_AOX_HMM_FIXED_DELIVERABLES) - 1
            or any(
                not isinstance(artifact_id, str) or not artifact_id
                for artifact_id in artifact_ids
            )
            or len(artifact_ids) != len(set(artifact_ids))
        ):
            _s15_aox_error(
                errors,
                "invalid_artifact_ids",
                path="aox_hmm/execution_summary.json",
            )
        if not execution_summary.get("provider_status") or not execution_summary.get(
            "tool_status"
        ):
            _s15_aox_error(
                errors,
                "invalid_execution_status_summary",
                path="aox_hmm/execution_summary.json",
            )
        if not expected_candidates:
            empty_result = execution_summary.get("empty_result")
            if (
                not isinstance(empty_result, dict)
                or empty_result.get("reason") != expected_empty_reason
                or empty_result.get("scientific_branch") != scientific_branch
                or empty_result.get("omitted_operation_roles")
                != omitted_operation_roles
            ):
                _s15_aox_error(
                    errors,
                    "empty_result_explanation_mismatch",
                    path="aox_hmm/execution_summary.json",
                    expected_reason=expected_empty_reason,
                    expected_scientific_branch=scientific_branch,
                    expected_omitted_operation_roles=omitted_operation_roles,
                )
            elif scientific_branch == "hmmer_upstream_empty" and empty_result.get(
                "skip_receipt_digest"
            ) != upstream_skip_digest:
                _s15_aox_error(
                    errors,
                    "upstream_empty_skip_receipt_digest_mismatch",
                    path="aox_hmm/execution_summary.json",
                )

    errors_digest = "sha256:" + hashlib.sha256(
        json.dumps(
            errors,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "passed": not errors,
        "missing_paths": missing,
        "legacy_paths": legacy_paths,
        "errors": errors,
        "errors_digest": errors_digest,
        "earliest_error": None if not errors else errors[0],
        "earliest_error_code": (
            None if not errors else str(errors[0].get("error_code") or "")
        ),
        "candidate_count": len(expected_candidates),
        "representative_count": len(representative_ids),
        "graph_node_count": 0 if graph_result is None else len(graph_result.nodes),
        "graph_edge_count": 0 if graph_result is None else len(graph_result.edges),
        "scientific_outcome": "discovered" if expected_candidates else "empty",
        "scientific_branch": scientific_branch,
        "omitted_operation_roles": omitted_operation_roles,
    }



validate_aox_final_artifacts = _s15_aox_validate_final_artifacts
aox_required_artifact_paths = _s15_aox_required_artifact_paths
aox_missing_required_paths = _s15_aox_missing_required_paths
aox_legacy_paths_present = _s15_aox_legacy_paths_present


__all__ = [
    "S15_AOX_HMM_FIXED_DELIVERABLES",
    "aox_legacy_paths_present",
    "aox_missing_required_paths",
    "aox_required_artifact_paths",
    "validate_aox_final_artifacts",
]
