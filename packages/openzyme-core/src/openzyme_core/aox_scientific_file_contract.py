from __future__ import annotations

from dataclasses import dataclass
import csv
import hashlib
import io
import json
import re
from collections.abc import Mapping

from .scientific_file_deliverables import ScientificFileDeliverableError


AOX_SCIENTIFIC_FILE_BUNDLE_CONTRACT_ID = "aox_scientific_file_bundle@1"
AOX_CONDITIONAL_EMPTY_FILE_SCHEMA_ID = "aox_conditional_empty_file@1"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class AoxScientificFileRole:
    role: str
    path: str
    format_contract_id: str


AOX_SCIENTIFIC_FILE_ROLES: tuple[AoxScientificFileRole, ...] = (
    AoxScientificFileRole(
        "candidates_fasta", "aox_hmm/AOX_candidates.fasta", "fasta@1"
    ),
    AoxScientificFileRole(
        "cdhit_clusters",
        "aox_hmm/AOX_candidates_cdhit85.clusters.csv",
        "csv@1",
    ),
    AoxScientificFileRole(
        "cdhit_candidates_fasta",
        "aox_hmm/AOX_candidates_cdhit85.fasta",
        "fasta@1",
    ),
    AoxScientificFileRole(
        "coordinate_reference_fasta",
        "aox_hmm/AOX_coordinate_reference_AAB57849.1.fasta",
        "fasta@1",
    ),
    AoxScientificFileRole("reference_hmm", "aox_hmm/AOX_ref.hmm", "hmmer3@1"),
    AoxScientificFileRole("reference_panel_fasta", "aox_hmm/AOX_ref21.fasta", "fasta@1"),
    AoxScientificFileRole("scoring_input_fasta", "aox_hmm/AOX_scoring_input.fasta", "fasta@1"),
    AoxScientificFileRole(
        "scoring_alignment_fasta",
        "aox_hmm/AOX_scoring_alignment.fasta",
        "aligned_fasta@1",
    ),
    AoxScientificFileRole("similarity_edges", "aox_hmm/edges_similarity.csv", "csv@1"),
    AoxScientificFileRole(
        "execution_summary",
        "aox_hmm/execution_summary.json",
        "aox_execution_summary@1",
    ),
    AoxScientificFileRole(
        "length_filtered_hits", "aox_hmm/hits_len650_700_200.csv", "csv@1"
    ),
    AoxScientificFileRole("raw_hits", "aox_hmm/hits_raw.csv", "csv@1"),
    AoxScientificFileRole(
        "score_filtered_accessions",
        "aox_hmm/hmmer_score_filtered_accessions.csv",
        "csv@1",
    ),
    AoxScientificFileRole("similarity_nodes", "aox_hmm/nodes.csv", "csv@1"),
    AoxScientificFileRole(
        "scored_reference_hits", "aox_hmm/scored_ref_plus_hits.csv", "csv@1"
    ),
    AoxScientificFileRole(
        "similarity_graph_manifest",
        "aox_hmm/similarity_graph_manifest.json",
        "aox_similarity_graph_manifest@1",
    ),
    AoxScientificFileRole("target_fasta", "aox_hmm/target.fasta", "fasta@1"),
)

AOX_SCIENTIFIC_FILE_BUNDLE_CONTRACT_DIGEST = (
    "sha256:"
    + hashlib.sha256(
        json.dumps(
            [
                {
                    "role": entry.role,
                    "path": entry.path,
                    "format_contract_id": entry.format_contract_id,
                }
                for entry in AOX_SCIENTIFIC_FILE_ROLES
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
)


def aox_format_contract_digest(format_contract_id: str) -> str:
    if format_contract_id not in {
        entry.format_contract_id for entry in AOX_SCIENTIFIC_FILE_ROLES
    }:
        raise ScientificFileDeliverableError(
            f"AOX format contract is not installed: {format_contract_id}"
        )
    return "sha256:" + hashlib.sha256(format_contract_id.encode("utf-8")).hexdigest()


def validate_aox_scientific_file_bytes(
    files: Mapping[str, bytes],
) -> dict[str, object]:
    expected = {entry.path: entry for entry in AOX_SCIENTIFIC_FILE_ROLES}
    if set(files) != set(expected):
        raise ScientificFileDeliverableError(
            "AOX scientific bytes must contain the exact 17 published paths"
        )
    texts: dict[str, str] = {}
    for path, content in files.items():
        if not content:
            raise ScientificFileDeliverableError(
                f"AOX scientific file is zero-byte: {path}"
            )
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ScientificFileDeliverableError(
                f"AOX scientific file is not UTF-8: {path}"
            ) from exc
        texts[path] = text
    try:
        summary = json.loads(texts["aox_hmm/execution_summary.json"])
    except json.JSONDecodeError as exc:
        raise ScientificFileDeliverableError(
            "AOX execution summary is invalid JSON"
        ) from exc
    if not isinstance(summary, dict):
        raise ScientificFileDeliverableError(
            "AOX execution summary requires an object"
        )
    candidate_count = summary.get("candidate_count")
    if (
        not isinstance(candidate_count, int)
        or isinstance(candidate_count, bool)
        or candidate_count < 0
    ):
        raise ScientificFileDeliverableError(
            "AOX execution summary has an invalid candidate_count"
        )
    typed_empty_files: dict[str, dict[str, object]] = {}
    for path, text in texts.items():
        format_contract_id = expected[path].format_contract_id
        if format_contract_id == "csv@1":
            rows = csv.reader(io.StringIO(text))
            header = next(rows, None)
            if header is None or not header or any(not value.strip() for value in header):
                raise ScientificFileDeliverableError(
                    f"AOX CSV has no closed header: {path}"
                )
        elif format_contract_id in {"fasta@1", "aligned_fasta@1"}:
            meaningful = [line for line in text.splitlines() if line.strip()]
            if meaningful and meaningful[0].startswith(">"):
                continue
            try:
                empty_file = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ScientificFileDeliverableError(
                    f"AOX FASTA does not carry records or a typed empty contract: {path}"
                ) from exc
            if (
                candidate_count != 0
                or not isinstance(empty_file, dict)
                or set(empty_file)
                != {
                    "schema_id",
                    "calculation_id",
                    "empty_result_reason",
                    "source_output_digest",
                    "source_receipt_digest",
                }
                or empty_file.get("schema_id")
                != AOX_CONDITIONAL_EMPTY_FILE_SCHEMA_ID
                or not isinstance(empty_file.get("calculation_id"), str)
                or not str(empty_file["calculation_id"]).strip()
                or not isinstance(empty_file.get("empty_result_reason"), str)
                or not str(empty_file["empty_result_reason"]).strip()
                or _DIGEST.fullmatch(str(empty_file.get("source_output_digest")))
                is None
                or _DIGEST.fullmatch(str(empty_file.get("source_receipt_digest")))
                is None
            ):
                raise ScientificFileDeliverableError(
                    f"AOX typed empty file contract is invalid: {path}"
                )
            typed_empty_files[path] = empty_file
        elif format_contract_id == "hmmer3@1":
            if not text.startswith("HMMER3/"):
                raise ScientificFileDeliverableError(
                    "AOX HMM bytes do not match the HMMER3 contract"
                )
        elif format_contract_id in {
            "aox_execution_summary@1",
            "aox_similarity_graph_manifest@1",
        }:
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ScientificFileDeliverableError(
                    f"AOX JSON contract is invalid: {path}"
                ) from exc
            if not isinstance(value, dict):
                raise ScientificFileDeliverableError(
                    f"AOX JSON contract requires an object: {path}"
                )
    empty_result = summary.get("empty_result")
    if candidate_count == 0:
        if (
            not isinstance(empty_result, dict)
            or empty_result.get("schema_id") != "aox_conditional_empty_result@1"
            or not isinstance(empty_result.get("reason"), str)
            or not empty_result["reason"].strip()
            or not isinstance(empty_result.get("receipt_digest"), str)
            or _DIGEST.fullmatch(str(empty_result["receipt_digest"])) is None
            or not typed_empty_files
            or any(
                item["empty_result_reason"] != empty_result["reason"]
                for item in typed_empty_files.values()
            )
        ):
            raise ScientificFileDeliverableError(
                "AOX zero-result bundle lacks its typed empty-result receipt"
            )
    elif empty_result is not None or typed_empty_files:
        raise ScientificFileDeliverableError(
            "AOX non-empty bundle carries a typed empty-file contract"
        )
    return {
        "schema_version": "aox_scientific_file_validation@1",
        "candidate_count": candidate_count,
        "typed_empty_paths": sorted(typed_empty_files),
        "role_count": len(expected),
        "bytes_digest": "sha256:"
        + hashlib.sha256(
            b"".join(
                path.encode("utf-8")
                + b"\0"
                + hashlib.sha256(files[path]).digest()
                for path in sorted(files)
            )
        ).hexdigest(),
    }


def require_exact_aox_scientific_file_manifest(
    entries: tuple[tuple[str, str, str], ...],
) -> None:
    expected = tuple(
        (entry.role, entry.path, entry.format_contract_id)
        for entry in AOX_SCIENTIFIC_FILE_ROLES
    )
    if entries != expected:
        raise ScientificFileDeliverableError(
            "AOX scientific publication must declare the exact ordered 17-role manifest"
        )


__all__ = [
    "AOX_SCIENTIFIC_FILE_BUNDLE_CONTRACT_ID",
    "AOX_SCIENTIFIC_FILE_BUNDLE_CONTRACT_DIGEST",
    "AOX_CONDITIONAL_EMPTY_FILE_SCHEMA_ID",
    "AOX_SCIENTIFIC_FILE_ROLES",
    "AoxScientificFileRole",
    "require_exact_aox_scientific_file_manifest",
    "aox_format_contract_digest",
    "validate_aox_scientific_file_bytes",
]
