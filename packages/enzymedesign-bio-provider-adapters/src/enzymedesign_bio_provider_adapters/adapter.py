from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import re
from typing import Any
from urllib.parse import quote_plus
from urllib.request import Request
from urllib.request import urlopen

from enzymedesign_core import DownloadedProviderAsset
from enzymedesign_core import ProteinAnnotationRecord
from enzymedesign_core import ProteinMetadataRecord
from enzymedesign_core import StructureMetadataRecord


JsonReader = Callable[..., dict[str, Any]]
BytesReader = Callable[..., bytes]
_ACCESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_PDB_ID = re.compile(r"[A-Za-z0-9]{4}")
_RCSB_NOISE = frozenset(
    {
        "a",
        "active",
        "an",
        "and",
        "entries",
        "entry",
        "evidence",
        "experimental",
        "for",
        "functional",
        "high",
        "in",
        "of",
        "or",
        "pdb",
        "rcsb",
        "resolution",
        "site",
        "structure",
        "structures",
        "the",
        "verified",
        "well",
        "with",
    }
)
_RESIDUE_TOKEN = re.compile(r"^[A-Z][a-z]{2}\d+[A-Za-z]?$")


def _read_json_once(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    body: bytes | None = None,
    empty_ok: bool = False,
) -> dict[str, Any]:
    request = Request(url, headers=headers or {}, method=method, data=body)
    with urlopen(request, timeout=30) as response:  # noqa: S310
        raw = response.read()
        if not raw.strip() and empty_ok:
            return {}
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Provider response must be one JSON object")
        return payload


def _read_bytes_once(url: str, *, headers: dict[str, str] | None = None) -> bytes:
    request = Request(url, headers=headers or {}, method="GET")
    with urlopen(request, timeout=30) as response:  # noqa: S310
        return response.read()


def _identifier(value: str, *, field_name: str, pattern: re.Pattern[str]) -> str:
    normalized = value.strip()
    if pattern.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} is invalid")
    return normalized


def _limit(value: int) -> int:
    if not 1 <= value <= 100:
        raise ValueError("limit must be between 1 and 100")
    return value


def _rcsb_query_candidates(query: str) -> tuple[str, ...]:
    normalized_query = " ".join(query.split())
    if not normalized_query:
        raise ValueError("query must be non-empty")
    candidates = [normalized_query]
    seen = {normalized_query.casefold()}
    meaningful: list[str] = []
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", normalized_query):
        key = token.casefold()
        if key in _RCSB_NOISE or key in {item.casefold() for item in meaningful}:
            continue
        meaningful.append(token)
    for width in (6, 4, 3, 2):
        if len(meaningful) >= width:
            candidate = " ".join(meaningful[:width])
            if candidate.casefold() not in seen:
                seen.add(candidate.casefold())
                candidates.append(candidate)
    for token in meaningful:
        if _RESIDUE_TOKEN.match(token) or token.casefold() in {
            "apo",
            "bound",
            "enzyme",
            "ligand",
            "protein",
        }:
            continue
        if token.casefold() not in seen:
            seen.add(token.casefold())
            candidates.append(token)
    return tuple(candidates)


@dataclass(slots=True)
class HttpBioProviderAdapter:
    json_reader: JsonReader = _read_json_once
    bytes_reader: BytesReader = _read_bytes_once

    def lookup_uniprot(self, *, accession: str) -> ProteinMetadataRecord:
        accession = _identifier(accession, field_name="accession", pattern=_ACCESSION)
        payload = self.json_reader(
            f"https://rest.uniprot.org/uniprotkb/{quote_plus(accession)}?format=json"
        )
        sequence = payload.get("sequence")
        description = payload.get("proteinDescription")
        organism_payload = payload.get("organism")
        if not isinstance(sequence, dict) or not isinstance(description, dict):
            raise ValueError(
                "UniProt response is missing sequence or proteinDescription"
            )
        recommended = description.get("recommendedName") or {}
        full_name = recommended.get("fullName") if isinstance(recommended, dict) else {}
        name = full_name.get("value") if isinstance(full_name, dict) else None
        organism = (
            organism_payload.get("scientificName")
            if isinstance(organism_payload, dict)
            else None
        )
        length = sequence.get("length")
        if length is not None and not isinstance(length, int):
            raise ValueError("UniProt sequence length must be an integer")
        return ProteinMetadataRecord(
            provider="uniprot",
            accession=accession,
            name=str(name or accession),
            organism=None if organism is None else str(organism),
            length=length,
            locator=f"https://rest.uniprot.org/uniprotkb/{accession}",
            metadata={"primary_accession": payload.get("primaryAccession")},
        )

    def download_uniprot_fasta(self, *, accession: str) -> DownloadedProviderAsset:
        accession = _identifier(accession, field_name="accession", pattern=_ACCESSION)
        content = self.bytes_reader(
            f"https://rest.uniprot.org/uniprotkb/{quote_plus(accession)}.fasta"
        )
        if not content:
            raise ValueError("UniProt FASTA response is empty")
        return DownloadedProviderAsset(
            provider="uniprot",
            external_id=accession,
            kind="sequence",
            filename=f"{accession}.fasta",
            format="fasta",
            locator=f"https://rest.uniprot.org/uniprotkb/{accession}.fasta",
            content=content,
            title=f"{accession} FASTA sequence",
            description="Downloaded protein FASTA from UniProt.",
            metadata={"accession": accession},
        )

    def search_rcsb_pdb(
        self, *, query: str, limit: int = 5
    ) -> tuple[StructureMetadataRecord, ...]:
        limit = _limit(limit)
        hits: list[StructureMetadataRecord] = []
        seen: set[str] = set()
        for search_query in _rcsb_query_candidates(query):
            search_body = {
                "query": {
                    "type": "terminal",
                    "service": "full_text",
                    "parameters": {"value": search_query},
                },
                "return_type": "entry",
                "request_options": {"paginate": {"start": 0, "rows": limit}},
            }
            payload = self.json_reader(
                "https://search.rcsb.org/rcsbsearch/v2/query",
                headers={"Content-Type": "application/json"},
                method="POST",
                body=json.dumps(search_body).encode("utf-8"),
                empty_ok=True,
            )
            result_set = payload.get("result_set", [])
            if not isinstance(result_set, list):
                raise ValueError("RCSB result_set must be an array")
            for item in result_set:
                if not isinstance(item, dict):
                    raise ValueError("RCSB result row must be an object")
                structure_id = str(item.get("identifier") or "").strip().upper()
                if not structure_id or structure_id in seen:
                    continue
                entry = self.json_reader(
                    f"https://data.rcsb.org/rest/v1/core/entry/{structure_id}"
                )
                struct = entry.get("struct") or {}
                info = entry.get("rcsb_entry_info") or {}
                resolutions = (
                    info.get("resolution_combined", [])
                    if isinstance(info, dict)
                    else []
                )
                resolution = None if not resolutions else float(resolutions[0])
                hits.append(
                    StructureMetadataRecord(
                        provider="rcsb_pdb",
                        structure_id=structure_id,
                        title=str(struct.get("title") or structure_id)
                        if isinstance(struct, dict)
                        else structure_id,
                        locator=f"https://www.rcsb.org/structure/{structure_id}",
                        resolution=resolution,
                        metadata={"query": query, "search_query": search_query},
                    )
                )
                seen.add(structure_id)
                if len(hits) >= limit:
                    return tuple(hits)
        return tuple(hits)

    def download_rcsb_structure(
        self, *, pdb_id: str, file_format: str = "pdb"
    ) -> DownloadedProviderAsset:
        pdb_id = _identifier(pdb_id, field_name="pdb_id", pattern=_PDB_ID).upper()
        if file_format not in {"pdb", "cif"}:
            raise ValueError("file_format must be pdb or cif")
        content = self.bytes_reader(
            f"https://files.rcsb.org/download/{pdb_id}.{file_format}"
        )
        if not content:
            raise ValueError("RCSB structure response is empty")
        return DownloadedProviderAsset(
            provider="rcsb_pdb",
            external_id=pdb_id,
            kind="structure",
            filename=f"{pdb_id}.{file_format}",
            format=file_format,
            locator=f"https://files.rcsb.org/download/{pdb_id}.{file_format}",
            content=content,
            title=f"{pdb_id} structure file",
            description="Downloaded structure file from RCSB PDB.",
            metadata={"pdb_id": pdb_id, "format": file_format},
        )

    def query_interpro(
        self, *, accession: str, limit: int = 10
    ) -> ProteinAnnotationRecord:
        accession = _identifier(accession, field_name="accession", pattern=_ACCESSION)
        limit = _limit(limit)
        payload = self.json_reader(
            "https://www.ebi.ac.uk/interpro/api/entry/InterPro/protein/uniprot/"
            f"{quote_plus(accession)}?page_size={limit}"
        )
        results = payload.get("results", [])
        if not isinstance(results, list):
            raise ValueError("InterPro results must be an array")
        entries: list[dict[str, Any]] = []
        for item in results:
            metadata = item.get("metadata") if isinstance(item, dict) else None
            if not isinstance(metadata, dict):
                raise ValueError("InterPro result metadata must be an object")
            entries.append(
                {
                    "entry_id": metadata.get("accession"),
                    "name": metadata.get("name"),
                    "type": metadata.get("type"),
                }
            )
        return ProteinAnnotationRecord(
            provider="interpro",
            accession=accession,
            entries=tuple(entries),
            locator=(
                "https://www.ebi.ac.uk/interpro/api/entry/InterPro/protein/"
                f"uniprot/{accession}"
            ),
        )


@dataclass(frozen=True, slots=True)
class DeterministicBioProviderAdapter:
    @staticmethod
    def _metadata(**values: Any) -> dict[str, Any]:
        return {
            **values,
            "fixture": True,
            "synthetic_source": True,
            "cutover_eligible": False,
            "scientific_status": "fixture_non_cutover",
        }

    def lookup_uniprot(self, *, accession: str) -> ProteinMetadataRecord:
        return ProteinMetadataRecord(
            "uniprot",
            accession,
            f"Protein {accession}",
            "Escherichia coli",
            321,
            f"https://rest.uniprot.org/uniprotkb/{accession}",
            self._metadata(),
        )

    def download_uniprot_fasta(self, *, accession: str) -> DownloadedProviderAsset:
        return DownloadedProviderAsset(
            "uniprot",
            accession,
            "sequence",
            f"{accession}.fasta",
            "fasta",
            f"https://rest.uniprot.org/uniprotkb/{accession}.fasta",
            f">{accession} deterministic protein\nMSEQUENCE{accession}\n".encode(),
            f"{accession} FASTA sequence",
            metadata=self._metadata(),
        )

    def search_rcsb_pdb(
        self, *, query: str, limit: int = 5
    ) -> tuple[StructureMetadataRecord, ...]:
        _limit(limit)
        return (
            StructureMetadataRecord(
                "rcsb_pdb",
                "1ABC",
                f"Structure result for {query}",
                "https://www.rcsb.org/structure/1ABC",
                1.8,
                self._metadata(query=query),
            ),
        )

    def download_rcsb_structure(
        self, *, pdb_id: str, file_format: str = "pdb"
    ) -> DownloadedProviderAsset:
        if file_format not in {"pdb", "cif"}:
            raise ValueError("file_format must be pdb or cif")
        return DownloadedProviderAsset(
            "rcsb_pdb",
            pdb_id,
            "structure",
            f"{pdb_id}.{file_format}",
            file_format,
            f"https://files.rcsb.org/download/{pdb_id}.{file_format}",
            f"HEADER    {pdb_id}\nEND\n".encode(),
            f"{pdb_id} structure file",
            metadata=self._metadata(),
        )

    def query_interpro(
        self, *, accession: str, limit: int = 10
    ) -> ProteinAnnotationRecord:
        _limit(limit)
        return ProteinAnnotationRecord(
            "interpro",
            accession,
            (
                {
                    "entry_id": "IPR000001",
                    "name": "Deterministic domain",
                    "type": "domain",
                    **self._metadata(),
                },
            ),
            f"https://www.ebi.ac.uk/interpro/api/entry/InterPro/protein/uniprot/{accession}",
        )


__all__ = ["DeterministicBioProviderAdapter", "HttpBioProviderAdapter"]
