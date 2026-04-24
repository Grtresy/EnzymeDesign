from openzyme_domain import ArtifactKind
from openzyme_domain import SourceRefKind

from openzyme_research import DeterministicBioResearchService
from openzyme_research import ResearchArtifactManifest
from openzyme_research import ResearchFinding
from openzyme_research import ResearchObservation
from openzyme_research import ResearchSource


def test_deterministic_bio_research_service_returns_provider_specific_records() -> None:
    service = DeterministicBioResearchService()

    pubmed_hits = service.search_pubmed(query="enzyme engineering", limit=3)
    semantic_hits = service.search_semantic_scholar(query="enzyme engineering", limit=3)
    protein = service.lookup_uniprot(accession="P12345")
    fasta = service.download_uniprot_fasta(accession="P12345")
    structure_hits = service.search_rcsb_pdb(query="thermostable lipase", limit=3)
    structure = service.download_rcsb_structure(pdb_id="1ABC", file_format="pdb")
    annotations = service.query_interpro(accession="P12345", limit=5)

    assert pubmed_hits[0].provider == "pubmed"
    assert semantic_hits[0].provider == "semantic_scholar"
    assert protein.provider == "uniprot"
    assert fasta.kind is ArtifactKind.SEQUENCE
    assert b">P12345" in fasta.content
    assert structure_hits[0].provider == "rcsb_pdb"
    assert structure.kind is ArtifactKind.STRUCTURE
    assert annotations.provider == "interpro"


def test_research_observation_serializes_stable_normalized_fields() -> None:
    observation = ResearchObservation.completed(
        summary="Collected evidence.",
        findings=(
            ResearchFinding(
                summary="Finding summary",
                query="enzyme query",
                confidence_label="high",
                sources=(
                    ResearchSource(
                        title="Paper A",
                        locator="https://example.org/a",
                        kind=SourceRefKind.PAPER,
                        snippet="Evidence snippet",
                    ),
                ),
            ),
            {
                "summary": "Dict finding",
                "query": "enzyme query",
                "confidence_label": "medium",
                "sources": [
                    {
                        "title": "Dataset A",
                        "locator": "https://example.org/dataset-a",
                        "kind": SourceRefKind.DATASET,
                    }
                ],
            },
        ),
        unresolved_gaps=("Need validation",),
        artifacts=(
            ResearchArtifactManifest(
                artifact_id="art_001",
                external_id="P12345",
                provider="uniprot",
                kind=ArtifactKind.SEQUENCE,
                format="fasta",
                filename="P12345.fasta",
                title="P12345 FASTA",
            ),
        ),
        provider="pubmed",
    )

    payload = observation.to_dict()

    assert list(payload.keys()) == [
        "status",
        "summary",
        "findings",
        "unresolved_gaps",
        "artifacts",
        "provider",
        "raw_ref",
    ]
    assert payload["findings"][0]["sources"][0]["kind"] == "paper"
    assert payload["findings"][1]["sources"][0]["kind"] == "dataset"
    assert payload["artifacts"][0]["kind"] == "sequence"
