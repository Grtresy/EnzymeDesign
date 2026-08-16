from __future__ import annotations

from dataclasses import dataclass

from .scientific_file_deliverables import ScientificFileDeliverableError


AOX_SCIENTIFIC_FILE_BUNDLE_CONTRACT_ID = "aox_scientific_file_bundle@1"


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
    "AOX_SCIENTIFIC_FILE_ROLES",
    "AoxScientificFileRole",
    "require_exact_aox_scientific_file_manifest",
]
