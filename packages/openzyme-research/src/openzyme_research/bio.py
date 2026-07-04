from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
import json
from pathlib import PurePosixPath
import re
import time
from typing import Any
from typing import Protocol
from urllib.error import URLError
from urllib.parse import quote_plus
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import urlopen

from openzyme_domain import ArtifactKind
from openzyme_domain import SourceRefKind

from .observations import ResearchArtifactManifest


@dataclass(frozen=True, slots=True)
class LiteratureHit:
    provider: str
    external_id: str
    title: str
    summary: str
    locator: str
    year: int | None = None
    citation_count: int | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SequenceRecord:
    provider: str
    accession: str
    name: str
    organism: str | None
    length: int | None
    locator: str
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StructureHit:
    provider: str
    structure_id: str
    title: str
    locator: str
    resolution: float | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AnnotationRecord:
    provider: str
    accession: str
    entries: tuple[dict[str, Any], ...]
    locator: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "accession": self.accession,
            "entries": [dict(entry) for entry in self.entries],
            "locator": self.locator,
        }


@dataclass(frozen=True, slots=True)
class DownloadedResearchAsset:
    provider: str
    external_id: str
    kind: ArtifactKind
    filename: str
    format: str
    locator: str
    content: bytes
    title: str
    description: str | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        payload["content"] = f"<{len(self.content)} bytes>"
        return payload


class BioResearchService(Protocol):
    def search_pubmed(self, *, query: str, limit: int = 5) -> tuple[LiteratureHit, ...]: ...

    def search_semantic_scholar(self, *, query: str, limit: int = 5) -> tuple[LiteratureHit, ...]: ...

    def lookup_uniprot(self, *, accession: str) -> SequenceRecord: ...

    def download_uniprot_fasta(self, *, accession: str) -> DownloadedResearchAsset: ...

    def search_rcsb_pdb(self, *, query: str, limit: int = 5) -> tuple[StructureHit, ...]: ...

    def download_rcsb_structure(self, *, pdb_id: str, file_format: str = "pdb") -> DownloadedResearchAsset: ...

    def query_interpro(self, *, accession: str, limit: int = 10) -> AnnotationRecord: ...


def _read_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    body: bytes | None = None,
    empty_ok: bool = False,
) -> dict[str, Any]:
    request = Request(url, headers=headers or {}, method=method, data=body)
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310
                raw_body = response.read()
                text = raw_body.decode("utf-8", errors="replace")
                if not text.strip():
                    if empty_ok:
                        return {}
                    status = getattr(response, "status", "unknown")
                    raise RuntimeError(
                        f"Expected JSON from {url}; got empty response with status {status}."
                    )
                try:
                    return json.loads(text)
                except json.JSONDecodeError as exc:
                    status = getattr(response, "status", "unknown")
                    content_type = response.headers.get("Content-Type", "unknown")
                    excerpt = text[:200].replace("\n", " ")
                    raise RuntimeError(
                        f"Expected JSON from {url}; got status {status}, content-type {content_type}, "
                        f"body prefix {excerpt!r}."
                    ) from exc
        except (TimeoutError, URLError) as exc:
            if attempt == 2:
                raise RuntimeError(f"Request to {url} failed after 3 attempts: {exc}") from exc
            time.sleep(0.5 * (attempt + 1))
    raise AssertionError("unreachable")


def _read_bytes(url: str, *, headers: dict[str, str] | None = None) -> bytes:
    request = Request(url, headers=headers or {}, method="GET")
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310
                return response.read()
        except (TimeoutError, URLError) as exc:
            if attempt == 2:
                raise RuntimeError(f"Request to {url} failed after 3 attempts: {exc}") from exc
            time.sleep(0.5 * (attempt + 1))
    raise AssertionError("unreachable")


_RCSB_SEARCH_NOISE_TERMS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "of",
    "or",
    "the",
    "with",
    "rcsb",
    "pdb",
    "structure",
    "structures",
    "entry",
    "entries",
    "evidence",
    "experimental",
    "functional",
    "high",
    "resolution",
    "site",
    "active",
    "well",
    "characterized",
    "verified",
}

_RCSB_RESIDUE_TOKEN_RE = re.compile(r"^[A-Z][a-z]{2}\d+[A-Za-z]?$")


def _rcsb_search_query_candidates(query: str) -> tuple[str, ...]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        normalized = " ".join(candidate.split())
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            candidates.append(normalized)

    add(query)
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", query)
    meaningful: list[str] = []
    token_keys: set[str] = set()
    for token in tokens:
        key = token.casefold()
        if key in _RCSB_SEARCH_NOISE_TERMS or key in token_keys:
            continue
        token_keys.add(key)
        meaningful.append(token)
    if meaningful:
        for width in (6, 4, 3, 2):
            if len(meaningful) >= width:
                add(" ".join(meaningful[:width]))
        for token in meaningful:
            if _RCSB_RESIDUE_TOKEN_RE.match(token):
                continue
            if token.casefold() in {"enzyme", "protein", "ligand", "bound", "apo"}:
                continue
            add(token)
    return tuple(candidates)


@dataclass(frozen=True, slots=True)
class DeterministicBioResearchService:
    def search_pubmed(self, *, query: str, limit: int = 5) -> tuple[LiteratureHit, ...]:
        del limit
        return (
            LiteratureHit(
                provider="pubmed",
                external_id="PMID:1001",
                title=f"PubMed result for {query}",
                summary="Deterministic PubMed literature hit for testing.",
                locator="https://pubmed.ncbi.nlm.nih.gov/1001/",
                year=2024,
                metadata={"query": query},
            ),
        )

    def search_semantic_scholar(self, *, query: str, limit: int = 5) -> tuple[LiteratureHit, ...]:
        del limit
        return (
            LiteratureHit(
                provider="semantic_scholar",
                external_id="S2:1001",
                title=f"Semantic Scholar result for {query}",
                summary="Deterministic Semantic Scholar hit for testing.",
                locator="https://www.semanticscholar.org/paper/S2:1001",
                year=2024,
                citation_count=42,
                metadata={"query": query},
            ),
        )

    def lookup_uniprot(self, *, accession: str) -> SequenceRecord:
        return SequenceRecord(
            provider="uniprot",
            accession=accession,
            name=f"Protein {accession}",
            organism="Escherichia coli",
            length=321,
            locator=f"https://rest.uniprot.org/uniprotkb/{accession}",
            metadata={"reviewed": True},
        )

    def download_uniprot_fasta(self, *, accession: str) -> DownloadedResearchAsset:
        content = f">{accession} deterministic protein\nMSEQUENCE{accession}\n".encode("utf-8")
        return DownloadedResearchAsset(
            provider="uniprot",
            external_id=accession,
            kind=ArtifactKind.SEQUENCE,
            filename=f"{accession}.fasta",
            format="fasta",
            locator=f"https://rest.uniprot.org/uniprotkb/{accession}.fasta",
            content=content,
            title=f"{accession} FASTA sequence",
            description="Downloaded protein FASTA from UniProt.",
            metadata={"accession": accession},
        )

    def search_rcsb_pdb(self, *, query: str, limit: int = 5) -> tuple[StructureHit, ...]:
        del limit
        return (
            StructureHit(
                provider="rcsb_pdb",
                structure_id="1ABC",
                title=f"Structure result for {query}",
                locator="https://www.rcsb.org/structure/1ABC",
                resolution=1.8,
                metadata={"query": query},
            ),
        )

    def download_rcsb_structure(self, *, pdb_id: str, file_format: str = "pdb") -> DownloadedResearchAsset:
        suffix = "cif" if file_format == "cif" else "pdb"
        content = f"HEADER    {pdb_id}\nEND\n".encode("utf-8")
        return DownloadedResearchAsset(
            provider="rcsb_pdb",
            external_id=pdb_id,
            kind=ArtifactKind.STRUCTURE,
            filename=f"{pdb_id}.{suffix}",
            format=suffix,
            locator=f"https://files.rcsb.org/download/{pdb_id}.{suffix}",
            content=content,
            title=f"{pdb_id} structure file",
            description="Downloaded structure file from RCSB PDB.",
            metadata={"pdb_id": pdb_id, "format": suffix},
        )

    def query_interpro(self, *, accession: str, limit: int = 10) -> AnnotationRecord:
        del limit
        return AnnotationRecord(
            provider="interpro",
            accession=accession,
            entries=(
                {
                    "entry_id": "IPR000001",
                    "name": "Deterministic domain",
                    "type": "domain",
                },
            ),
            locator=f"https://www.ebi.ac.uk/interpro/api/entry/InterPro/protein/uniprot/{accession}",
        )


@dataclass(frozen=True, slots=True)
class DefaultBioResearchService:
    semantic_scholar_api_key: str | None = None
    pubmed_api_key: str | None = None
    pubmed_email: str | None = None

    def search_pubmed(self, *, query: str, limit: int = 5) -> tuple[LiteratureHit, ...]:
        params = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": str(limit),
        }
        if self.pubmed_api_key:
            params["api_key"] = self.pubmed_api_key
        esearch = _read_json(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{urlencode(params)}")
        ids = list((esearch.get("esearchresult") or {}).get("idlist") or [])
        if not ids:
            return ()
        summary_params = {"db": "pubmed", "id": ",".join(ids), "retmode": "json"}
        if self.pubmed_api_key:
            summary_params["api_key"] = self.pubmed_api_key
        summaries = _read_json(
            f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?{urlencode(summary_params)}"
        )
        result_items: list[LiteratureHit] = []
        for item_id in ids:
            payload = ((summaries.get("result") or {}).get(item_id) or {})
            title = str(payload.get("title") or f"PubMed record {item_id}")
            year = None
            pubdate = str(payload.get("pubdate") or "")
            if pubdate[:4].isdigit():
                year = int(pubdate[:4])
            result_items.append(
                LiteratureHit(
                    provider="pubmed",
                    external_id=f"PMID:{item_id}",
                    title=title,
                    summary=title,
                    locator=f"https://pubmed.ncbi.nlm.nih.gov/{item_id}/",
                    year=year,
                    metadata={"authors": payload.get("authors") or []},
                )
            )
        return tuple(result_items)

    def search_semantic_scholar(self, *, query: str, limit: int = 5) -> tuple[LiteratureHit, ...]:
        params = {
            "query": query,
            "limit": str(limit),
            "fields": "title,abstract,year,citationCount,url",
        }
        headers = {}
        if self.semantic_scholar_api_key:
            headers["x-api-key"] = self.semantic_scholar_api_key
        payload = _read_json(
            f"https://api.semanticscholar.org/graph/v1/paper/search?{urlencode(params)}",
            headers=headers,
        )
        hits: list[LiteratureHit] = []
        for item in payload.get("data", []):
            paper_id = str(item.get("paperId") or "")
            hits.append(
                LiteratureHit(
                    provider="semantic_scholar",
                    external_id=paper_id,
                    title=str(item.get("title") or "Semantic Scholar record"),
                    summary=str(item.get("abstract") or item.get("title") or ""),
                    locator=str(item.get("url") or f"https://www.semanticscholar.org/paper/{paper_id}"),
                    year=item.get("year"),
                    citation_count=item.get("citationCount"),
                )
            )
        return tuple(hits)

    def lookup_uniprot(self, *, accession: str) -> SequenceRecord:
        payload = _read_json(f"https://rest.uniprot.org/uniprotkb/{quote_plus(accession)}?format=json")
        sequence = payload.get("sequence") or {}
        protein_description = payload.get("proteinDescription") or {}
        recommended_name = (
            ((protein_description.get("recommendedName") or {}).get("fullName") or {}).get("value")
        )
        organism = ((payload.get("organism") or {}).get("scientificName"))
        return SequenceRecord(
            provider="uniprot",
            accession=accession,
            name=str(recommended_name or accession),
            organism=None if organism is None else str(organism),
            length=sequence.get("length"),
            locator=f"https://rest.uniprot.org/uniprotkb/{accession}",
            metadata={"primary_accession": payload.get("primaryAccession")},
        )

    def download_uniprot_fasta(self, *, accession: str) -> DownloadedResearchAsset:
        content = _read_bytes(f"https://rest.uniprot.org/uniprotkb/{quote_plus(accession)}.fasta")
        return DownloadedResearchAsset(
            provider="uniprot",
            external_id=accession,
            kind=ArtifactKind.SEQUENCE,
            filename=f"{accession}.fasta",
            format="fasta",
            locator=f"https://rest.uniprot.org/uniprotkb/{accession}.fasta",
            content=content,
            title=f"{accession} FASTA sequence",
            description="Downloaded protein FASTA from UniProt.",
            metadata={"accession": accession},
        )

    def search_rcsb_pdb(self, *, query: str, limit: int = 5) -> tuple[StructureHit, ...]:
        hits: list[StructureHit] = []
        seen_ids: set[str] = set()
        for search_query in _rcsb_search_query_candidates(query):
            if len(hits) >= limit:
                break
            search_body = {
                "query": {
                    "type": "terminal",
                    "service": "full_text",
                    "parameters": {"value": search_query},
                },
                "return_type": "entry",
                "request_options": {"paginate": {"start": 0, "rows": limit}},
            }
            payload = _read_json(
                "https://search.rcsb.org/rcsbsearch/v2/query",
                headers={"Content-Type": "application/json"},
                method="POST",
                body=json.dumps(search_body).encode("utf-8"),
                empty_ok=True,
            )
            for item in payload.get("result_set", []):
                structure_id = str(item.get("identifier") or "").strip()
                if not structure_id or structure_id in seen_ids:
                    continue
                seen_ids.add(structure_id)
                title = structure_id
                try:
                    entry = _read_json(f"https://data.rcsb.org/rest/v1/core/entry/{structure_id}")
                    title = str(
                        ((entry.get("struct") or {}).get("title"))
                        or structure_id
                    )
                    resolution_values = (((entry.get("rcsb_entry_info") or {}).get("resolution_combined")) or [])
                    resolution = None if not resolution_values else float(resolution_values[0])
                except Exception:
                    resolution = None
                hits.append(
                    StructureHit(
                        provider="rcsb_pdb",
                        structure_id=structure_id,
                        title=title,
                        locator=f"https://www.rcsb.org/structure/{structure_id}",
                        resolution=resolution,
                        metadata={"query": query, "search_query": search_query},
                    )
                )
                if len(hits) >= limit:
                    break
        return tuple(hits)

    def download_rcsb_structure(self, *, pdb_id: str, file_format: str = "pdb") -> DownloadedResearchAsset:
        normalized_format = "cif" if file_format == "cif" else "pdb"
        content = _read_bytes(f"https://files.rcsb.org/download/{pdb_id}.{normalized_format}")
        return DownloadedResearchAsset(
            provider="rcsb_pdb",
            external_id=pdb_id,
            kind=ArtifactKind.STRUCTURE,
            filename=f"{pdb_id}.{normalized_format}",
            format=normalized_format,
            locator=f"https://files.rcsb.org/download/{pdb_id}.{normalized_format}",
            content=content,
            title=f"{pdb_id} structure file",
            description="Downloaded structure file from RCSB PDB.",
            metadata={"pdb_id": pdb_id, "format": normalized_format},
        )

    def query_interpro(self, *, accession: str, limit: int = 10) -> AnnotationRecord:
        payload = _read_json(
            f"https://www.ebi.ac.uk/interpro/api/entry/InterPro/protein/uniprot/{quote_plus(accession)}?page_size={limit}"
        )
        entries: list[dict[str, Any]] = []
        for item in payload.get("results", []):
            metadata = item.get("metadata") or {}
            entry_id = metadata.get("accession")
            entries.append(
                {
                    "entry_id": entry_id,
                    "name": metadata.get("name"),
                    "type": metadata.get("type"),
                }
            )
        return AnnotationRecord(
            provider="interpro",
            accession=accession,
            entries=tuple(entries),
            locator=f"https://www.ebi.ac.uk/interpro/api/entry/InterPro/protein/uniprot/{accession}",
        )


def literature_hits_to_findings(hits: tuple[LiteratureHit, ...], *, query: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for hit in hits:
        findings.append(
            {
                "summary": hit.summary or hit.title,
                "query": query,
                "confidence_label": "medium",
                "sources": [
                    {
                        "title": hit.title,
                        "locator": hit.locator,
                        "kind": SourceRefKind.PAPER.value,
                        "snippet": hit.summary,
                    }
                ],
            }
        )
    return findings


def structure_hits_to_findings(hits: tuple[StructureHit, ...], *, query: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for hit in hits:
        findings.append(
            {
                "summary": hit.title,
                "query": query,
                "confidence_label": "medium",
                "sources": [
                    {
                        "title": hit.title,
                        "locator": hit.locator,
                        "kind": SourceRefKind.DATASET.value,
                        "snippet": f"Structure id {hit.structure_id}",
                    }
                ],
            }
        )
    return findings


def asset_manifest(asset: DownloadedResearchAsset) -> dict[str, Any]:
    return ResearchArtifactManifest(
        external_id=asset.external_id,
        provider=asset.provider,
        kind=asset.kind,
        format=asset.format,
        filename=PurePosixPath(asset.filename).name,
        title=asset.title,
        description=asset.description,
        source_locator=asset.locator,
        metadata=asset.metadata,
    ).to_dict()


__all__ = [
    "AnnotationRecord",
    "BioResearchService",
    "DefaultBioResearchService",
    "DeterministicBioResearchService",
    "DownloadedResearchAsset",
    "LiteratureHit",
    "SequenceRecord",
    "StructureHit",
    "asset_manifest",
    "literature_hits_to_findings",
    "structure_hits_to_findings",
]
