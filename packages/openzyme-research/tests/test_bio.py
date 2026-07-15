import json

from openzyme_domain import ArtifactKind
from openzyme_domain import SourceRefKind

from openzyme_research import DefaultBioResearchService
from openzyme_research import DeterministicBioResearchService
from openzyme_research import ResearchArtifactManifest
from openzyme_research import ResearchFinding
from openzyme_research import ResearchObservation
from openzyme_research import ResearchSource
from openzyme_research import bio


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
    assert pubmed_hits[0].metadata is not None
    assert pubmed_hits[0].metadata["scientific_status"] == "fixture_non_cutover"
    assert protein.metadata is not None
    assert protein.metadata["cutover_eligible"] is False
    assert fasta.metadata is not None
    assert fasta.metadata["synthetic_source"] is True
    assert structure.metadata is not None
    assert structure.metadata["provider_status"] == "fixture_non_cutover"
    assert annotations.entries[0]["scientific_status"] == "fixture_non_cutover"


def test_read_json_allows_empty_rcsb_no_content_response(monkeypatch) -> None:
    class EmptyResponse:
        status = 204
        headers = {"Content-Type": "application/json"}

        def __enter__(self) -> "EmptyResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b""

    monkeypatch.setattr(bio, "urlopen", lambda request, timeout: EmptyResponse())

    assert bio._read_json("https://search.rcsb.org/rcsbsearch/v2/query", empty_ok=True) == {}


def test_rcsb_search_falls_back_from_verbose_no_hit_query(monkeypatch) -> None:
    queries: list[str] = []

    def fake_read_json(
        url: str,
        *,
        headers: dict[str, str] | None = None,
        method: str = "GET",
        body: bytes | None = None,
        empty_ok: bool = False,
    ) -> dict[str, object]:
        del headers, method, empty_ok
        if "search.rcsb.org" in url:
            assert body is not None
            search_body = json.loads(body.decode("utf-8"))
            search_query = str(search_body["query"]["parameters"]["value"])
            queries.append(search_query)
            if search_query == "lysozyme":
                return {"result_set": [{"identifier": "1LYZ"}]}
            return {}
        if "data.rcsb.org" in url:
            return {
                "struct": {"title": "Hen egg-white lysozyme"},
                "rcsb_entry_info": {"resolution_combined": [1.5]},
            }
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(bio, "_read_json", fake_read_json)

    hits = DefaultBioResearchService().search_rcsb_pdb(
        query="RCSB PDB lysozyme high resolution structure active site functional evidence Glu35 Asp52",
        limit=3,
    )

    assert "lysozyme" in queries
    assert hits[0].structure_id == "1LYZ"
    assert hits[0].title == "Hen egg-white lysozyme"
    assert hits[0].resolution == 1.5
    assert hits[0].metadata == {
        "query": (
            "RCSB PDB lysozyme high resolution structure active site functional "
            "evidence Glu35 Asp52"
        ),
        "search_query": "lysozyme",
    }


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
