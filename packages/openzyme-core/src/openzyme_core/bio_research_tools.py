from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import ResearchEvidence
from openzyme_domain import ResearchGap
from openzyme_domain import ResearchSourceRef
from openzyme_domain import ResearchSummary
from openzyme_domain import ResearchSummaryStatus
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SourceRefKind
from openzyme_domain.control_plane import utc_now_iso
from openzyme_research import BioResearchService
from openzyme_research import DownloadedResearchAsset
from openzyme_research import DeterministicBioResearchService
from openzyme_research import ResearchArtifactManifest
from openzyme_research import ResearchObservation
from openzyme_research import literature_hits_to_findings
from openzyme_research import structure_hits_to_findings

from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .repositories import EngineDocumentRecord


def _new_artifact_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _artifact_root() -> Path:
    root = Path("/tmp/openzyme-research-artifacts")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _persist_asset(
    context: SessionRuntimeContext,
    invocation: ToolInvocation,
    *,
    asset: DownloadedResearchAsset,
    scope_label: str,
    invocation_id: str | None = None,
) -> SessionArtifactRecord:
    now = utc_now_iso()
    artifact_id = _new_artifact_id("art")
    session_id = context.snapshot.session.session_id
    target_dir = _artifact_root() / session_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{artifact_id}_{asset.filename}"
    target_path.write_bytes(asset.content)
    artifact = SessionArtifactRecord(
        artifact_id=artifact_id,
        session_id=session_id,
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        invocation_id=invocation_id,
        run_id=None,
        kind=asset.kind,
        storage_uri=str(target_path),
        relative_path=target_path.name,
        title=asset.title,
        description=asset.description,
        metadata={
            "provider": asset.provider,
            "external_id": asset.external_id,
            "format": asset.format,
            "source_locator": asset.locator,
            "produced_by": scope_label,
            **({} if asset.metadata is None else dict(asset.metadata)),
        },
        created_at=now,
    )
    context.repositories.artifacts.save(artifact)
    context.emit(
        "artifact.recorded",
        {
            "artifact_id": artifact.artifact_id,
            "task_id": artifact.task_id,
            "lane_id": artifact.lane_id,
            "kind": artifact.kind.value,
        },
    )
    return artifact


def _start_research_tool_invocation(
    context: SessionRuntimeContext,
    invocation: ToolInvocation,
) -> EngineInvocation:
    now = utc_now_iso()
    engine_invocation_id = _new_artifact_id("inv_research_tool")
    input_document_id = f"{engine_invocation_id}:input"
    engine_invocation = EngineInvocation(
        invocation_id=engine_invocation_id,
        session_id=context.snapshot.session.session_id,
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        engine_name="research_tool",
        status=EngineInvocationStatus.RUNNING,
        input_ref=input_document_id,
        output_ref=None,
        approval_id=None,
        idempotency_key=f"{invocation.call_id}:{invocation.tool_name}:{engine_invocation_id}",
        started_at=now,
    )
    context.repositories.invocations.save(engine_invocation)
    context.repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id=input_document_id,
            session_id=engine_invocation.session_id,
            invocation_id=engine_invocation.invocation_id,
            document_kind="research_tool_input",
            payload={
                "tool_name": invocation.tool_name,
                "arguments": dict(invocation.arguments),
                "call_id": invocation.call_id,
            },
            created_at=now,
            updated_at=now,
        )
    )
    return engine_invocation


def _finish_research_tool_invocation(
    context: SessionRuntimeContext,
    invocation: ToolInvocation,
    engine_invocation: EngineInvocation,
    observation: ResearchObservation,
) -> dict[str, Any]:
    now = utc_now_iso()
    observation_payload = observation.to_dict()
    output_document_id = f"{engine_invocation.invocation_id}:output"
    terminal_status = (
        EngineInvocationStatus.FAILED
        if observation.status.lower() in {"failed", "error"}
        else EngineInvocationStatus.SUCCEEDED
    )
    context.repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id=output_document_id,
            session_id=engine_invocation.session_id,
            invocation_id=engine_invocation.invocation_id,
            document_kind="research_tool_observation",
            payload=observation_payload,
            created_at=now,
            updated_at=now,
        )
    )
    completed_invocation = EngineInvocation(
        invocation_id=engine_invocation.invocation_id,
        session_id=engine_invocation.session_id,
        task_id=engine_invocation.task_id,
        lane_id=engine_invocation.lane_id,
        engine_name=engine_invocation.engine_name,
        status=terminal_status,
        input_ref=engine_invocation.input_ref,
        output_ref=output_document_id,
        approval_id=engine_invocation.approval_id,
        idempotency_key=engine_invocation.idempotency_key,
        started_at=engine_invocation.started_at,
        finished_at=now,
    )
    context.repositories.invocations.save(completed_invocation)
    persist_research_observation(
        context,
        tool_invocation=invocation,
        engine_invocation=completed_invocation,
        observation=observation_payload,
    )
    return observation_payload


def persist_research_observation(
    context: SessionRuntimeContext,
    *,
    tool_invocation: ToolInvocation,
    engine_invocation: EngineInvocation,
    observation: dict[str, Any],
) -> None:
    now = utc_now_iso()
    status = _summary_status(str(observation.get("status") or "completed"))
    summary_id = f"{engine_invocation.invocation_id}:summary"
    context.repositories.research_summaries.save(
        ResearchSummary(
            summary_id=summary_id,
            session_id=engine_invocation.session_id,
            task_id=tool_invocation.task_id,
            lane_id=tool_invocation.lane_id,
            invocation_id=engine_invocation.invocation_id,
            status=status,
            completion_reason=str(observation.get("status") or "completed"),
            research_brief=_research_brief(tool_invocation, observation),
            summary=str(observation.get("summary") or ""),
            clarification_question=None,
            created_at=now,
            updated_at=now,
        )
    )
    for index, finding in enumerate(list(observation.get("findings") or []), start=1):
        finding_payload = dict(finding)
        evidence_id = f"{engine_invocation.invocation_id}:evidence:{index}"
        context.repositories.research_evidence.save(
            ResearchEvidence(
                evidence_id=evidence_id,
                session_id=engine_invocation.session_id,
                task_id=tool_invocation.task_id,
                lane_id=tool_invocation.lane_id,
                invocation_id=engine_invocation.invocation_id,
                summary_id=summary_id,
                summary=str(finding_payload.get("summary") or ""),
                query=str(finding_payload.get("query") or ""),
                confidence_label=None
                if finding_payload.get("confidence_label") is None
                else str(finding_payload["confidence_label"]),
                created_at=now,
            )
        )
        for source_index, source in enumerate(list(finding_payload.get("sources") or []), start=1):
            source_payload = dict(source)
            context.repositories.research_source_refs.save(
                ResearchSourceRef(
                    source_ref_id=f"{evidence_id}:source:{source_index}",
                    session_id=engine_invocation.session_id,
                    task_id=tool_invocation.task_id,
                    lane_id=tool_invocation.lane_id,
                    invocation_id=engine_invocation.invocation_id,
                    evidence_id=evidence_id,
                    title=str(source_payload.get("title") or "Untitled source"),
                    locator=str(source_payload.get("locator") or ""),
                    kind=_source_kind(source_payload.get("kind")),
                    snippet=None if source_payload.get("snippet") is None else str(source_payload["snippet"]),
                    created_at=now,
                )
            )
    for index, gap in enumerate(list(observation.get("unresolved_gaps") or []), start=1):
        context.repositories.research_gaps.save(
            ResearchGap(
                gap_id=f"{engine_invocation.invocation_id}:gap:{index}",
                session_id=engine_invocation.session_id,
                task_id=tool_invocation.task_id,
                lane_id=tool_invocation.lane_id,
                invocation_id=engine_invocation.invocation_id,
                summary_id=summary_id,
                summary=str(gap),
                created_at=now,
            )
        )


def _summary_status(status: str) -> ResearchSummaryStatus:
    normalized = status.lower()
    if normalized in {"failed", "error"}:
        return ResearchSummaryStatus.FAILED
    if normalized in {"partial", "escalated"}:
        return ResearchSummaryStatus.PARTIAL
    if normalized in {"needs_clarification", "clarification_requested"}:
        return ResearchSummaryStatus.NEEDS_CLARIFICATION
    return ResearchSummaryStatus.COMPLETED


def _source_kind(value: object) -> SourceRefKind:
    try:
        return SourceRefKind(str(value))
    except ValueError:
        return SourceRefKind.OTHER


def _research_brief(invocation: ToolInvocation, observation: dict[str, Any]) -> str:
    if "query" in invocation.arguments:
        return str(invocation.arguments["query"])
    if "accession" in invocation.arguments:
        return str(invocation.arguments["accession"])
    if "pdb_id" in invocation.arguments:
        return str(invocation.arguments["pdb_id"])
    return str(observation.get("summary") or invocation.tool_name)


def _artifact_manifest(asset: DownloadedResearchAsset, artifact: SessionArtifactRecord) -> ResearchArtifactManifest:
    return ResearchArtifactManifest(
        artifact_id=artifact.artifact_id,
        external_id=asset.external_id,
        provider=asset.provider,
        kind=asset.kind,
        format=asset.format,
        filename=asset.filename,
        title=asset.title,
        description=asset.description,
        source_locator=asset.locator,
        metadata=asset.metadata,
        storage_uri=artifact.storage_uri,
        relative_path=artifact.relative_path,
    )


@dataclass(frozen=True, slots=True)
class BioResearchToolRegistrar:
    service: BioResearchService

    def register(self, registry: ToolRegistry) -> None:
        def _payload_result(invocation: ToolInvocation, payload: dict[str, object], *, ok: bool = True) -> ToolResult:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=ok,
                content=json.dumps(payload, sort_keys=True),
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
            )

        def _observation_result(
            context: SessionRuntimeContext,
            invocation: ToolInvocation,
            observation: ResearchObservation,
        ) -> ToolResult:
            engine_invocation = _start_research_tool_invocation(context, invocation)
            return _payload_result(
                invocation,
                _finish_research_tool_invocation(context, invocation, engine_invocation, observation),
            )

        def _failed_observation_result(
            context: SessionRuntimeContext,
            invocation: ToolInvocation,
            *,
            provider: str,
            summary: str,
            error: Exception,
            raw_ref: dict[str, object],
        ) -> ToolResult:
            observation = ResearchObservation(
                status="failed",
                summary=summary,
                unresolved_gaps=(str(error).strip() or error.__class__.__name__,),
                provider=provider,
                raw_ref={
                    **raw_ref,
                    "error_type": error.__class__.__name__,
                    "error": str(error),
                },
            )
            engine_invocation = _start_research_tool_invocation(context, invocation)
            return _payload_result(
                invocation,
                _finish_research_tool_invocation(context, invocation, engine_invocation, observation),
                ok=False,
            )

        def pubmed_search(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
            query = str(invocation.arguments["query"])
            limit = int(invocation.arguments.get("limit", 5))
            try:
                hits = self.service.search_pubmed(query=query, limit=limit)
            except Exception as exc:
                return _failed_observation_result(
                    context,
                    invocation,
                    provider="pubmed",
                    summary=f"PubMed search failed for {query}.",
                    error=exc,
                    raw_ref={"query": query, "limit": limit},
                )
            return _observation_result(
                context,
                invocation,
                ResearchObservation.completed(
                    summary=f"Collected {len(hits)} PubMed hits for {query}.",
                    findings=tuple(literature_hits_to_findings(hits, query=query)),
                    provider="pubmed",
                    raw_ref={"query": query},
                ),
            )

        def semantic_scholar_search(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
            query = str(invocation.arguments["query"])
            limit = int(invocation.arguments.get("limit", 5))
            try:
                hits = self.service.search_semantic_scholar(query=query, limit=limit)
            except Exception as exc:
                return _failed_observation_result(
                    context,
                    invocation,
                    provider="semantic_scholar",
                    summary=f"Semantic Scholar search failed for {query}.",
                    error=exc,
                    raw_ref={"query": query, "limit": limit},
                )
            return _observation_result(
                context,
                invocation,
                ResearchObservation.completed(
                    summary=f"Collected {len(hits)} Semantic Scholar hits for {query}.",
                    findings=tuple(literature_hits_to_findings(hits, query=query)),
                    provider="semantic_scholar",
                    raw_ref={"query": query},
                ),
            )

        def uniprot_lookup(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
            accession = str(invocation.arguments["accession"])
            record = self.service.lookup_uniprot(accession=accession)
            return _observation_result(
                context,
                invocation,
                ResearchObservation.completed(
                    summary=f"Loaded UniProt metadata for {accession}.",
                    findings=(
                        {
                            "summary": f"{record.name} ({record.accession})",
                            "query": accession,
                            "confidence_label": "high",
                            "sources": [
                                {
                                    "title": record.name,
                                    "locator": record.locator,
                                    "kind": SourceRefKind.DATASET.value,
                                    "snippet": record.organism,
                                }
                            ],
                        },
                    ),
                    provider="uniprot",
                    raw_ref={"record": record.to_dict()},
                ),
            )

        def uniprot_download_fasta(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
            accession = str(invocation.arguments["accession"])
            asset = self.service.download_uniprot_fasta(accession=accession)
            engine_invocation = _start_research_tool_invocation(context, invocation)
            artifact = _persist_asset(
                context,
                invocation,
                asset=asset,
                scope_label="research_tool",
                invocation_id=engine_invocation.invocation_id,
            )
            return _payload_result(
                invocation,
                _finish_research_tool_invocation(
                    context,
                    invocation,
                    engine_invocation,
                    ResearchObservation.completed(
                        summary=f"Downloaded FASTA for {accession}.",
                        artifacts=(_artifact_manifest(asset, artifact),),
                        provider="uniprot",
                        raw_ref={"accession": accession},
                    ),
                ),
            )

        def rcsb_search(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
            query = str(invocation.arguments["query"])
            limit = int(invocation.arguments.get("limit", 5))
            hits = self.service.search_rcsb_pdb(query=query, limit=limit)
            return _observation_result(
                context,
                invocation,
                ResearchObservation.completed(
                    summary=f"Collected {len(hits)} structure hits for {query}.",
                    findings=tuple(structure_hits_to_findings(hits, query=query)),
                    provider="rcsb_pdb",
                    raw_ref={"query": query},
                ),
            )

        def rcsb_download_structure(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
            pdb_id = str(invocation.arguments["pdb_id"])
            file_format = str(invocation.arguments.get("format", "pdb"))
            asset = self.service.download_rcsb_structure(pdb_id=pdb_id, file_format=file_format)
            engine_invocation = _start_research_tool_invocation(context, invocation)
            artifact = _persist_asset(
                context,
                invocation,
                asset=asset,
                scope_label="research_tool",
                invocation_id=engine_invocation.invocation_id,
            )
            return _payload_result(
                invocation,
                _finish_research_tool_invocation(
                    context,
                    invocation,
                    engine_invocation,
                    ResearchObservation.completed(
                        summary=f"Downloaded structure file for {pdb_id}.",
                        artifacts=(_artifact_manifest(asset, artifact),),
                        provider="rcsb_pdb",
                        raw_ref={"pdb_id": pdb_id, "format": file_format},
                    ),
                ),
            )

        def interpro_query(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
            accession = str(invocation.arguments["accession"])
            limit = int(invocation.arguments.get("limit", 10))
            record = self.service.query_interpro(accession=accession, limit=limit)
            summary = f"Loaded {len(record.entries)} InterPro annotations for {accession}."
            return _observation_result(
                context,
                invocation,
                ResearchObservation.completed(
                    summary=summary,
                    findings=(
                        {
                            "summary": summary,
                            "query": accession,
                            "confidence_label": "medium",
                            "sources": [
                                {
                                    "title": f"InterPro annotations for {accession}",
                                    "locator": record.locator,
                                    "kind": SourceRefKind.DATASET.value,
                                    "snippet": None if not record.entries else str(record.entries[0].get("name") or ""),
                                }
                            ],
                        },
                    ),
                    provider="interpro",
                    raw_ref={"record": record.to_dict()},
                ),
            )

        registry.register("pubmed.search", pubmed_search)
        registry.register("semantic_scholar.search", semantic_scholar_search)
        registry.register("uniprot.lookup", uniprot_lookup)
        registry.register("uniprot.download_fasta", uniprot_download_fasta)
        registry.register("rcsb_pdb.search", rcsb_search)
        registry.register("rcsb_pdb.download_structure", rcsb_download_structure)
        registry.register("interpro.query", interpro_query)


def register_bio_research_tools(
    registry: ToolRegistry,
    *,
    service: BioResearchService | None = None,
) -> None:
    BioResearchToolRegistrar(service or DeterministicBioResearchService()).register(registry)


__all__ = ["persist_research_observation", "register_bio_research_tools"]
