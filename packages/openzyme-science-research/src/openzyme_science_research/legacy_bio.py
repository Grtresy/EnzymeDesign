from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
import hashlib
import json
import time
from typing import Any
from typing import Protocol
from urllib.parse import urlencode
from urllib.request import urlopen

from openzyme_research import BoundedHttpClient
from openzyme_research import ProviderAttempt
from openzyme_research import ProviderCallResult
from openzyme_research import ProviderProvenance
from openzyme_research import ProviderRequestError
from openzyme_research import SourceRefKind
from openzyme_research import combine_provenance
from openzyme_research import completed_result
from openzyme_research import degraded_result
from openzyme_research import provider_identity_digest
from openzyme_research import provider_schema_error
from openzyme_research import safe_public_locator

from .contracts import LiteratureHit


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _content_digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


class LiteratureResearchService(Protocol):
    def search_pubmed(
        self, *, query: str, limit: int = 5
    ) -> tuple[LiteratureHit, ...]: ...

    def search_pubmed_result(
        self, *, query: str, limit: int = 5
    ) -> ProviderCallResult[LiteratureHit]: ...

    def search_semantic_scholar(
        self, *, query: str, limit: int = 5
    ) -> tuple[LiteratureHit, ...]: ...

    def search_semantic_scholar_result(
        self, *, query: str, limit: int = 5
    ) -> ProviderCallResult[LiteratureHit]: ...


def _fixture_provider_provenance(
    *,
    provider: str,
    operation: str,
    endpoint_id: str,
    query: str,
) -> ProviderProvenance:
    timestamp = _utc_now_iso()
    request_digest = _content_digest(
        json.dumps(
            {"provider": provider, "operation": operation, "query": query},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return ProviderProvenance(
        provider=provider,
        operation=operation,
        endpoint_id=endpoint_id,
        request_digest=request_digest,
        retrieved_at=timestamp,
        attempt_count=1,
        attempts=(
            ProviderAttempt(
                attempt=1,
                started_at=timestamp,
                finished_at=timestamp,
                outcome="completed",
                status_code=200,
            ),
        ),
        cache_status="fixture_non_cutover",
    )


def _normalize_pubmed_authors(
    value: object,
    *,
    provenance: ProviderProvenance,
) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise provider_schema_error(
            provenance,
            "PubMed authors must be a list when present",
        )
    authors: list[dict[str, str]] = []
    for index, author in enumerate(value):
        if not isinstance(author, dict):
            raise provider_schema_error(
                provenance,
                f"PubMed authors[{index}] must be an object",
            )
        name = str(author.get("name") or "").strip()
        if not name:
            raise provider_schema_error(
                provenance,
                f"PubMed authors[{index}] requires name",
            )
        normalized = {"name": name}
        author_type = str(author.get("authtype") or "").strip()
        if author_type:
            normalized["author_type"] = author_type
        authors.append(normalized)
    return authors


def _pubmed_doi(
    value: object,
    *,
    provenance: ProviderProvenance,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise provider_schema_error(
            provenance,
            "PubMed articleids must be a list when present",
        )
    dois: list[str] = []
    for index, identifier in enumerate(value):
        if not isinstance(identifier, dict):
            raise provider_schema_error(
                provenance,
                f"PubMed articleids[{index}] must be an object",
            )
        if str(identifier.get("idtype") or "").casefold() != "doi":
            continue
        doi = str(identifier.get("value") or "").strip()
        if doi:
            dois.append(doi)
    if len(set(dois)) > 1:
        raise provider_schema_error(
            provenance,
            "PubMed supplied multiple conflicting DOI identifiers",
        )
    return None if not dois else dois[0]


@dataclass(frozen=True, slots=True)
class DeterministicLiteratureResearchService:
    @staticmethod
    def _fixture_metadata(**values: Any) -> dict[str, Any]:
        return {
            **values,
            "fixture": True,
            "synthetic_source": True,
            "cutover_eligible": False,
            "scientific_status": "fixture_non_cutover",
            "provider_status": "fixture_non_cutover",
        }

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
                metadata=self._fixture_metadata(query=query),
            ),
        )

    def search_pubmed_result(
        self, *, query: str, limit: int = 5
    ) -> ProviderCallResult[LiteratureHit]:
        hits = self.search_pubmed(query=query, limit=limit)
        return completed_result(
            hits,
            provenance=_fixture_provider_provenance(
                provider="pubmed",
                operation="literature.search",
                endpoint_id="fixture:pubmed",
                query=query,
            ),
            warnings=("fixture_non_cutover",),
        )

    def search_semantic_scholar(
        self, *, query: str, limit: int = 5
    ) -> tuple[LiteratureHit, ...]:
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
                metadata=self._fixture_metadata(query=query),
            ),
        )

    def search_semantic_scholar_result(
        self, *, query: str, limit: int = 5
    ) -> ProviderCallResult[LiteratureHit]:
        hits = self.search_semantic_scholar(query=query, limit=limit)
        return completed_result(
            hits,
            provenance=_fixture_provider_provenance(
                provider="semantic_scholar",
                operation="literature.enrich",
                endpoint_id="fixture:semantic_scholar",
                query=query,
            ),
            warnings=("fixture_non_cutover",),
        )


@dataclass(frozen=True, slots=True)
class DefaultLiteratureResearchService:
    semantic_scholar_api_key: str | None = None
    pubmed_api_key: str | None = None
    pubmed_email: str | None = None
    pubmed_tool: str = "openzyme"
    http_client: BoundedHttpClient = field(
        default_factory=lambda: BoundedHttpClient(opener=urlopen, sleeper=time.sleep)
    )

    def search_pubmed(self, *, query: str, limit: int = 5) -> tuple[LiteratureHit, ...]:
        return self.search_pubmed_result(query=query, limit=limit).items

    def search_pubmed_result(
        self, *, query: str, limit: int = 5
    ) -> ProviderCallResult[LiteratureHit]:
        ncbi_identity_digest = (
            None
            if not self.pubmed_email
            else provider_identity_digest(
                provider="ncbi",
                identity={
                    "tool": self.pubmed_tool,
                    "email": self.pubmed_email.strip().casefold(),
                    "api_key": self.pubmed_api_key or "",
                },
            )
        )
        params = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": str(limit),
            "tool": self.pubmed_tool,
        }
        if self.pubmed_email:
            params["email"] = self.pubmed_email
        if self.pubmed_api_key:
            params["api_key"] = self.pubmed_api_key
        esearch_response = self.http_client.request(
            provider="pubmed",
            operation="literature.search",
            endpoint_id="pubmed.esearch:v1",
            url=(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?"
                f"{urlencode(params)}"
            ),
            request_identity={
                "database": "pubmed",
                "query": query,
                "limit": limit,
                "tool": self.pubmed_tool,
                "identity_configured": bool(self.pubmed_email),
                "identity_digest": ncbi_identity_digest,
            },
            safe_provider_identity={
                "tool": self.pubmed_tool,
                "email_configured": bool(self.pubmed_email),
                "api_key_configured": bool(self.pubmed_api_key),
                **(
                    {}
                    if ncbi_identity_digest is None
                    else {"identity_digest": ncbi_identity_digest}
                ),
            },
        )
        esearch = esearch_response.json_object()
        esearch_result = esearch.get("esearchresult")
        if not isinstance(esearch_result, dict):
            raise provider_schema_error(
                esearch_response.provenance,
                "missing object field esearchresult",
            )
        raw_ids = esearch_result.get("idlist")
        if not isinstance(raw_ids, list) or not all(
            isinstance(item, str) and item.isdigit() for item in raw_ids
        ):
            raise provider_schema_error(
                esearch_response.provenance,
                "esearchresult.idlist must be a list of PMID strings",
            )
        ids = list(dict.fromkeys(raw_ids))
        if not ids:
            return completed_result((), provenance=esearch_response.provenance)
        summary_params = {
            "db": "pubmed",
            "id": ",".join(ids),
            "retmode": "json",
            "tool": self.pubmed_tool,
        }
        if self.pubmed_email:
            summary_params["email"] = self.pubmed_email
        if self.pubmed_api_key:
            summary_params["api_key"] = self.pubmed_api_key
        summary_response = self.http_client.request(
            provider="pubmed",
            operation="literature.search",
            endpoint_id="pubmed.esummary:v1",
            url=(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?"
                f"{urlencode(summary_params)}"
            ),
            request_identity={
                "database": "pubmed",
                "pmids": ids,
                "tool": self.pubmed_tool,
                "identity_configured": bool(self.pubmed_email),
                "identity_digest": ncbi_identity_digest,
            },
            safe_provider_identity={
                "tool": self.pubmed_tool,
                "email_configured": bool(self.pubmed_email),
                "api_key_configured": bool(self.pubmed_api_key),
                **(
                    {}
                    if ncbi_identity_digest is None
                    else {"identity_digest": ncbi_identity_digest}
                ),
            },
        )
        summaries = summary_response.json_object()
        summary_result = summaries.get("result")
        if not isinstance(summary_result, dict):
            raise provider_schema_error(
                summary_response.provenance,
                "missing object field result",
            )
        combined_provenance = combine_provenance(
            (esearch_response.provenance, summary_response.provenance),
            operation="literature.search",
            endpoint_id="pubmed.esearch+esummary:v1",
        )
        result_items: list[LiteratureHit] = []
        for item_id in ids:
            payload = summary_result.get(item_id)
            if not isinstance(payload, dict):
                raise provider_schema_error(
                    combined_provenance,
                    f"missing summary object for PMID {item_id}",
                )
            title_value = payload.get("title")
            if not isinstance(title_value, str) or not title_value.strip():
                raise provider_schema_error(
                    combined_provenance,
                    f"missing title for PMID {item_id}",
                )
            title = title_value.strip()
            year = None
            pubdate = str(payload.get("pubdate") or "")
            if pubdate[:4].isdigit():
                year = int(pubdate[:4])
            authors = _normalize_pubmed_authors(
                payload.get("authors"), provenance=combined_provenance
            )
            doi = _pubmed_doi(payload.get("articleids"), provenance=combined_provenance)
            venue = str(
                payload.get("fulljournalname") or payload.get("source") or ""
            ).strip()
            result_items.append(
                LiteratureHit(
                    provider="pubmed",
                    external_id=f"PMID:{item_id}",
                    title=title,
                    summary=title,
                    locator=f"https://pubmed.ncbi.nlm.nih.gov/{item_id}/",
                    year=year,
                    metadata={
                        "pmid": item_id,
                        "doi": doi,
                        "authors": authors,
                        "venue": venue or None,
                        "publication_date": pubdate or None,
                        "retrieved_at": combined_provenance.retrieved_at,
                        "response_digest": combined_provenance.response_digest,
                        "provider_provenance": combined_provenance.to_dict(),
                    },
                )
            )
        return completed_result(
            tuple(result_items),
            provenance=combined_provenance,
        )

    def search_semantic_scholar(
        self, *, query: str, limit: int = 5
    ) -> tuple[LiteratureHit, ...]:
        return self.search_semantic_scholar_result(query=query, limit=limit).items

    def search_semantic_scholar_result(
        self, *, query: str, limit: int = 5
    ) -> ProviderCallResult[LiteratureHit]:
        try:
            return self._search_semantic_scholar_result(query=query, limit=limit)
        except ProviderRequestError as exc:
            failure = exc.result.failure
            assert failure is not None
            return degraded_result(
                provenance=exc.result.provenance,
                error_code=failure.error_code,
                message=failure.message,
                retryable=failure.retryable,
                status_code=failure.status_code,
                warnings=("enrichment_provider_degraded",),
            )

    def _search_semantic_scholar_result(
        self, *, query: str, limit: int = 5
    ) -> ProviderCallResult[LiteratureHit]:
        params = {
            "query": query,
            "limit": str(limit),
            "fields": "title,abstract,year,citationCount,url,externalIds,authors,venue,publicationDate",
        }
        headers = {}
        if self.semantic_scholar_api_key:
            headers["x-api-key"] = self.semantic_scholar_api_key
        response = self.http_client.request(
            provider="semantic_scholar",
            operation="literature.enrich",
            endpoint_id="semantic_scholar.paper_search:v1",
            url=(
                "https://api.semanticscholar.org/graph/v1/paper/search?"
                f"{urlencode(params)}"
            ),
            request_identity={"query": query, "limit": limit},
            headers=headers,
            safe_provider_identity={
                "api_key_configured": bool(self.semantic_scholar_api_key),
            },
        )
        payload = response.json_object()
        data = payload.get("data")
        if not isinstance(data, list):
            raise provider_schema_error(
                response.provenance,
                "data must be a list",
            )
        hits: list[LiteratureHit] = []
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                raise provider_schema_error(
                    response.provenance,
                    f"data[{index}] must be an object",
                )
            paper_id = str(item.get("paperId") or "").strip()
            title = str(item.get("title") or "").strip()
            if not paper_id or not title:
                raise provider_schema_error(
                    response.provenance,
                    f"data[{index}] requires paperId and title",
                )
            canonical_locator = (
                safe_public_locator(str(item.get("url") or ""))
                or f"https://www.semanticscholar.org/paper/{paper_id}"
            )
            hits.append(
                LiteratureHit(
                    provider="semantic_scholar",
                    external_id=paper_id,
                    title=title,
                    summary=str(item.get("abstract") or title),
                    locator=canonical_locator,
                    year=item.get("year"),
                    citation_count=item.get("citationCount"),
                    metadata={
                        "external_ids": item.get("externalIds") or {},
                        "authors": item.get("authors") or [],
                        "venue": item.get("venue"),
                        "publication_date": item.get("publicationDate"),
                        "retrieved_at": response.provenance.retrieved_at,
                        "response_digest": response.provenance.response_digest,
                        "provider_provenance": response.provenance.to_dict(),
                    },
                )
            )
        if not hits:
            return degraded_result(
                provenance=response.provenance,
                error_code="provider_empty",
                message="semantic_scholar enrichment returned no results",
                retryable=False,
            )
        return completed_result(tuple(hits), provenance=response.provenance)


def literature_hits_to_findings(
    hits: tuple[LiteratureHit, ...], *, query: str
) -> list[dict[str, Any]]:
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
                        "provider": hit.provider,
                        "external_id": hit.external_id,
                        "pmid": (hit.metadata or {}).get("pmid"),
                        "doi": (hit.metadata or {}).get("doi"),
                        "authors": list((hit.metadata or {}).get("authors") or []),
                        "venue": (hit.metadata or {}).get("venue"),
                        "publication_date": (hit.metadata or {}).get(
                            "publication_date"
                        ),
                        "retrieved_at": (hit.metadata or {}).get("retrieved_at"),
                        "request_digest": dict(
                            (hit.metadata or {}).get("provider_provenance") or {}
                        ).get("request_digest"),
                        "response_digest": (hit.metadata or {}).get("response_digest"),
                        "provider_provenance": dict(
                            (hit.metadata or {}).get("provider_provenance") or {}
                        ),
                    }
                ],
            }
        )
    return findings


def safe_literature_evidence_payload(
    result: ProviderCallResult[LiteratureHit],
) -> dict[str, Any]:
    """Build sealable citation evidence without abstracts, secrets, or raw URLs."""

    citations: list[dict[str, Any]] = []
    for hit in result.items:
        metadata = dict(hit.metadata or {})
        locator = safe_public_locator(hit.locator)
        citations.append(
            {
                "provider": hit.provider,
                "external_id": hit.external_id,
                "pmid": metadata.get("pmid"),
                "doi": metadata.get("doi"),
                "title": hit.title,
                "authors": list(metadata.get("authors") or []),
                "venue": metadata.get("venue"),
                "publication_date": metadata.get("publication_date"),
                "year": hit.year,
                "locator": locator,
            }
        )
    return {
        "schema_version": "provider_literature_evidence@1",
        "provider": result.provenance.provider,
        "outcome": result.outcome.value,
        "citations": citations,
        "provenance": result.provenance.to_dict(),
        "failure": None if result.failure is None else result.failure.to_dict(),
        "warnings": list(result.warnings),
    }


__all__ = [
    "DefaultLiteratureResearchService",
    "DeterministicLiteratureResearchService",
    "LiteratureHit",
    "LiteratureResearchService",
    "literature_hits_to_findings",
    "safe_literature_evidence_payload",
]
