from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from dataclasses import dataclass
import hashlib
from typing import Any
from typing import Protocol

from openzyme_contracts import ToolInvocation
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts.identity import JsonValue


BIO_PROVIDER_PORT_ID = "enzymedesign.bio-provider@1"
BIO_PROVIDER_PORT_CONTRACT = {
    "schema_version": BIO_PROVIDER_PORT_ID,
    "providers": {
        "interpro": ["query"],
        "rcsb": ["download_structure", "search"],
        "uniprot": ["download_fasta", "lookup"],
    },
    "effect_policy": {
        "automatic_fallback": False,
        "automatic_retry": False,
        "downloads_are_private_until_published": True,
        "task_completion_inferred": False,
    },
}
BIO_PROVIDER_PORT_CONTRACT_DIGEST = canonical_sha256_digest(BIO_PROVIDER_PORT_CONTRACT)


@dataclass(frozen=True, slots=True)
class ProteinMetadataRecord:
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
class StructureMetadataRecord:
    provider: str
    structure_id: str
    title: str
    locator: str
    resolution: float | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProteinAnnotationRecord:
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
class DownloadedProviderAsset:
    provider: str
    external_id: str
    kind: str
    filename: str
    format: str
    locator: str
    content: bytes
    title: str
    description: str | None = None
    metadata: dict[str, Any] | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "external_id": self.external_id,
            "kind": self.kind,
            "filename": self.filename,
            "format": self.format,
            "locator": self.locator,
            "content_length": len(self.content),
            "content_digest": f"sha256:{hashlib.sha256(self.content).hexdigest()}",
            "title": self.title,
            "description": self.description,
            "metadata": None if self.metadata is None else dict(self.metadata),
        }


class BioProviderPort(Protocol):
    """Product contract implemented by one explicitly selected Provider Adapter."""

    def lookup_uniprot(self, *, accession: str) -> ProteinMetadataRecord: ...

    def download_uniprot_fasta(self, *, accession: str) -> DownloadedProviderAsset: ...

    def search_rcsb_pdb(
        self, *, query: str, limit: int = 5
    ) -> tuple[StructureMetadataRecord, ...]: ...

    def download_rcsb_structure(
        self, *, pdb_id: str, file_format: str = "pdb"
    ) -> DownloadedProviderAsset: ...

    def query_interpro(
        self, *, accession: str, limit: int = 10
    ) -> ProteinAnnotationRecord: ...


class SequenceProviderApplication(Protocol):
    """Composition bridge used by the Sequence Tool Pack runtime."""

    def invoke(self, *, invocation: ToolInvocation) -> Mapping[str, JsonValue]: ...


__all__ = [
    "BIO_PROVIDER_PORT_CONTRACT",
    "BIO_PROVIDER_PORT_CONTRACT_DIGEST",
    "BIO_PROVIDER_PORT_ID",
    "BioProviderPort",
    "DownloadedProviderAsset",
    "ProteinAnnotationRecord",
    "ProteinMetadataRecord",
    "SequenceProviderApplication",
    "StructureMetadataRecord",
]
