from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
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
from openzyme_research import EvidenceQuorumResult
from openzyme_research import ProviderCallResult
from openzyme_research import ProviderOutcome
from openzyme_research import ProviderRequestError
from openzyme_research import ResearchArtifactManifest
from openzyme_research import ResearchObservation
from openzyme_research import ResearchUnit
from openzyme_research import literature_hits_to_findings
from openzyme_research import evaluate_literature_quorum
from openzyme_research import safe_literature_evidence_payload
from openzyme_research import safe_public_locator
from openzyme_research import structure_hits_to_findings

from .artifact_boundary import ArtifactBoundaryError
from .artifact_boundary import ArtifactBoundaryService
from .artifact_projection import sanitize_private_artifact_fields
from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .repositories import EngineDocumentRecord


def _new_artifact_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _content_digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _call_local_literature_quorum(
    *,
    provider: str,
    result: ProviderCallResult[Any],
) -> EvidenceQuorumResult:
    return evaluate_literature_quorum(
        pubmed=result if provider == "pubmed" else None,
        semantic_scholar=(
            result if provider == "semantic_scholar" else None
        ),
    )


def _safe_research_arguments(arguments: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in arguments.items():
        normalized = str(key).casefold()
        if normalized in {
            "api_key",
            "authorization",
            "cookie",
            "password",
            "secret",
            "token",
            "x-api-key",
        }:
            continue
        if normalized in {"url", "locator"}:
            public = safe_public_locator(str(value))
            safe[str(key)] = public if public is not None else "<redacted-private-url>"
            continue
        safe[str(key)] = value
    return safe


def _sealed_asset_metadata(
    asset: DownloadedResearchAsset,
    *,
    produced_by: str,
    retrieved_at: str,
) -> dict[str, Any]:
    digest = _content_digest(asset.content)
    provenance = {
        "provider": asset.provider,
        "external_id": asset.external_id,
        "source_locator": safe_public_locator(asset.locator),
        "format": asset.format,
        "retrieved_at": retrieved_at,
        "digest": digest,
    }
    return {
        **({} if asset.metadata is None else dict(asset.metadata)),
        "provider": asset.provider,
        "external_id": asset.external_id,
        "format": asset.format,
        "source_locator": safe_public_locator(asset.locator),
        "produced_by": produced_by,
        "content_digest": digest,
        "sealed_digest": digest,
        "retrieved_at": retrieved_at,
        "provenance": provenance,
    }


def _persist_asset(
    context: SessionRuntimeContext,
    invocation: ToolInvocation,
    *,
    asset: DownloadedResearchAsset,
    scope_label: str,
    invocation_id: str | None = None,
) -> SessionArtifactRecord:
    now = utc_now_iso()
    session_id = context.snapshot.session.session_id
    metadata = _sealed_asset_metadata(
        asset,
        produced_by=scope_label,
        retrieved_at=now,
    )
    request_digest = _content_digest(
        json.dumps(
            {
                "provider": asset.provider,
                "external_id": asset.external_id,
                "format": asset.format,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    result = ArtifactBoundaryService(
        context.repositories,
        blob_store_root=context.artifact_blob_root,
    ).seal_external_bytes(
        session_id=session_id,
        content=asset.content,
        filename=asset.filename,
        kind=asset.kind,
        format=asset.format,
        title=asset.title,
        description=asset.description,
        provider=asset.provider,
        provenance={
            "request_digest": request_digest,
            "response_digest": _content_digest(asset.content),
            "retrieved_at": now,
            "external_id": asset.external_id,
            "source_locator": safe_public_locator(asset.locator),
            "format": asset.format,
            "digest": _content_digest(asset.content),
        },
        metadata=metadata,
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        invocation_id=invocation_id,
    )
    artifact = result.artifact
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


def _persist_literature_evidence(
    context: SessionRuntimeContext,
    invocation: ToolInvocation,
    *,
    engine_invocation: EngineInvocation,
    result: ProviderCallResult[Any],
    quorum: EvidenceQuorumResult,
) -> SessionArtifactRecord:
    evidence = safe_literature_evidence_payload(result)
    evidence["call_local_literature_quorum"] = quorum.to_dict()
    content = json.dumps(
        evidence,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    provenance = result.provenance.to_dict()
    sealed = ArtifactBoundaryService(
        context.repositories,
        blob_store_root=context.artifact_blob_root,
    ).seal_external_bytes(
        session_id=engine_invocation.session_id,
        content=content,
        filename=f"{result.provenance.provider}_literature_evidence.json",
        kind="result",
        format="json",
        title=f"{result.provenance.provider} literature evidence",
        description="Safe citation metadata and provider call provenance.",
        provider=result.provenance.provider,
        provenance=provenance,
        metadata={
            "schema_version": "provider_literature_evidence@1",
            "provider_outcome": result.outcome.value,
            "citation_count": len(result.items),
            "cutover_eligible": quorum.cutover_eligible,
            "quorum_status": quorum.status.value,
        },
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        invocation_id=engine_invocation.invocation_id,
        license_scope="safe_citation_metadata",
    )
    artifact = sealed.artifact
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


def _provider_artifact_manifest(
    artifact: SessionArtifactRecord,
    *,
    provider: str,
) -> ResearchArtifactManifest:
    metadata = dict(artifact.metadata or {})
    provenance = dict(metadata.get("provenance") or {})
    return ResearchArtifactManifest(
        artifact_id=artifact.artifact_id,
        external_id=f"{provider}:literature_evidence",
        provider=provider,
        kind=artifact.kind,
        format=str(metadata.get("format") or "json"),
        filename=artifact.relative_path.rsplit("/", 1)[-1],
        title=str(artifact.title or f"{provider} literature evidence"),
        description=artifact.description,
        metadata=metadata,
        relative_path=artifact.relative_path,
        content_digest=_metadata_text(metadata, "content_digest"),
        sealed_digest=_metadata_text(metadata, "sealed_digest"),
        retrieved_at=None
        if provenance.get("retrieved_at") is None
        else str(provenance["retrieved_at"]),
        provenance=provenance,
    )


def _persist_web_evidence(
    context: SessionRuntimeContext,
    invocation: ToolInvocation,
    *,
    engine_invocation: EngineInvocation,
    result: ProviderCallResult[Any],
    findings: tuple[Any, ...],
) -> SessionArtifactRecord:
    citations: list[dict[str, Any]] = []
    for finding in findings:
        finding_payload = (
            finding.to_dict() if hasattr(finding, "to_dict") else dict(finding)
        )
        for source in list(finding_payload.get("sources") or []):
            source_payload = (
                source.to_dict() if hasattr(source, "to_dict") else dict(source)
            )
            locator = safe_public_locator(str(source_payload.get("locator") or ""))
            if locator is None:
                continue
            citations.append(
                {
                    "title": str(source_payload.get("title") or "Untitled source"),
                    "locator": locator,
                    "kind": str(source_payload.get("kind") or "web_page"),
                }
            )
    evidence = {
        "schema_version": "provider_web_evidence@1",
        "provider": result.provenance.provider,
        "outcome": result.outcome.value,
        "citations": citations,
        "provenance": result.provenance.to_dict(),
        "failure": None if result.failure is None else result.failure.to_dict(),
        "warnings": list(result.warnings),
    }
    content = json.dumps(
        evidence,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    sealed = ArtifactBoundaryService(
        context.repositories,
        blob_store_root=context.artifact_blob_root,
    ).seal_external_bytes(
        session_id=engine_invocation.session_id,
        content=content,
        filename="tavily_web_evidence.json",
        kind="result",
        format="json",
        title="Tavily web evidence",
        description="Safe public source metadata and provider call provenance.",
        provider=result.provenance.provider,
        provenance=result.provenance.to_dict(),
        metadata={
            "schema_version": "provider_web_evidence@1",
            "provider_outcome": result.outcome.value,
            "citation_count": len(citations),
        },
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        invocation_id=engine_invocation.invocation_id,
        license_scope="safe_public_source_metadata",
    )
    artifact = sealed.artifact
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
                "arguments": _safe_research_arguments(dict(invocation.arguments)),
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
    observation_payload = sanitize_private_artifact_fields(observation.to_dict())
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
        for source_index, source in enumerate(
            list(finding_payload.get("sources") or []), start=1
        ):
            source_payload = dict(source)
            provider_provenance = _safe_provider_provenance(
                source_payload.get("provider_provenance")
            )
            locator = safe_public_locator(
                str(source_payload.get("locator") or "")
            )
            context.repositories.research_source_refs.save(
                ResearchSourceRef(
                    source_ref_id=f"{evidence_id}:source:{source_index}",
                    session_id=engine_invocation.session_id,
                    task_id=tool_invocation.task_id,
                    lane_id=tool_invocation.lane_id,
                    invocation_id=engine_invocation.invocation_id,
                    evidence_id=evidence_id,
                    title=str(source_payload.get("title") or "Untitled source"),
                    locator=locator or "",
                    kind=_source_kind(source_payload.get("kind")),
                    snippet=None
                    if source_payload.get("snippet") is None
                    else str(source_payload["snippet"]),
                    created_at=now,
                    provider=_optional_text(source_payload.get("provider")),
                    external_id=_optional_text(
                        source_payload.get("external_id")
                    ),
                    pmid=_optional_text(source_payload.get("pmid")),
                    doi=_optional_text(source_payload.get("doi")),
                    authors=_safe_authors(source_payload.get("authors")),
                    venue=_optional_text(source_payload.get("venue")),
                    publication_date=_optional_text(
                        source_payload.get("publication_date")
                    ),
                    retrieved_at=_optional_text(
                        source_payload.get("retrieved_at")
                    ),
                    request_digest=_optional_text(
                        source_payload.get("request_digest")
                        or provider_provenance.get("request_digest")
                    ),
                    response_digest=_optional_text(
                        source_payload.get("response_digest")
                        or provider_provenance.get("response_digest")
                    ),
                    provider_provenance=provider_provenance,
                    evidence_artifact_id=_optional_text(
                        source_payload.get("evidence_artifact_id")
                    ),
                )
            )
    for index, gap in enumerate(
        list(observation.get("unresolved_gaps") or []), start=1
    ):
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


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_authors(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    authors: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            authors.append({"name": item.strip()})
            continue
        if not isinstance(item, dict):
            continue
        name = _optional_text(item.get("name"))
        if name is None:
            continue
        author: dict[str, Any] = {"name": name}
        author_type = _optional_text(
            item.get("author_type") or item.get("authtype")
        )
        if author_type is not None:
            author["author_type"] = author_type
        authors.append(author)
    return tuple(authors)


def _safe_provider_provenance(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {
        "provider",
        "operation",
        "endpoint_id",
        "request_digest",
        "response_digest",
        "retrieved_at",
        "response_status",
        "attempt_count",
        "attempts",
        "request_ids",
        "page_count",
        "release",
        "api_version",
        "truncated",
        "cache_status",
        "safe_response_headers",
        "provider_identity",
    }
    return sanitize_private_artifact_fields(
        {str(key): item for key, item in value.items() if str(key) in allowed}
    )


def _artifact_manifest(
    asset: DownloadedResearchAsset, artifact: SessionArtifactRecord
) -> ResearchArtifactManifest:
    metadata = dict(artifact.metadata or {})
    provenance = metadata.get("provenance")
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
        metadata=metadata,
        storage_uri=artifact.storage_uri,
        relative_path=artifact.relative_path,
        content_digest=_metadata_text(metadata, "content_digest"),
        sealed_digest=_metadata_text(metadata, "sealed_digest"),
        retrieved_at=_metadata_text(metadata, "retrieved_at"),
        provenance=None if not isinstance(provenance, dict) else dict(provenance),
    )


def _metadata_text(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return None if value is None else str(value)


@dataclass(frozen=True, slots=True)
class BioResearchToolRegistrar:
    service: BioResearchService

    def register(self, registry: ToolRegistry) -> None:
        def _payload_result(
            invocation: ToolInvocation,
            payload: dict[str, object],
            *,
            ok: bool = True,
            status: str | None = None,
            summary: str | None = None,
            error_code: str | None = None,
            details: dict[str, object] | None = None,
        ) -> ToolResult:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=ok,
                content=json.dumps(payload, sort_keys=True),
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
                status=status,
                summary=summary,
                error_code=error_code,
                details=details,
            )

        def _observation_result(
            context: SessionRuntimeContext,
            invocation: ToolInvocation,
            observation: ResearchObservation,
            *,
            engine_invocation: EngineInvocation | None = None,
        ) -> ToolResult:
            active_invocation = engine_invocation or _start_research_tool_invocation(
                context, invocation
            )
            return _payload_result(
                invocation,
                _finish_research_tool_invocation(
                    context, invocation, active_invocation, observation
                ),
            )

        def _failed_provider_result(
            context: SessionRuntimeContext,
            invocation: ToolInvocation,
            *,
            engine_invocation: EngineInvocation,
            provider: str,
            error_code: str,
            summary: str,
            raw_ref: dict[str, object],
            exception_type: str | None = None,
            artifacts: tuple[ResearchArtifactManifest, ...] = (),
        ) -> ToolResult:
            observation = ResearchObservation(
                status="failed",
                summary=summary,
                unresolved_gaps=(summary,),
                provider=provider,
                raw_ref=raw_ref,
                artifacts=artifacts,
            )
            payload = _finish_research_tool_invocation(
                context,
                invocation,
                engine_invocation,
                observation,
            )
            return _payload_result(
                invocation,
                payload,
                ok=False,
                status=error_code,
                summary=summary,
                error_code=error_code,
                details=(
                    None
                    if exception_type is None
                    else {"exception_type": exception_type}
                ),
            )

        def _literature_result(
            context: SessionRuntimeContext,
            invocation: ToolInvocation,
            *,
            provider: str,
            query: str,
            call: Any,
        ) -> ToolResult:
            engine_invocation = _start_research_tool_invocation(context, invocation)
            try:
                provider_result = call()
            except ProviderRequestError as exc:
                failure = exc.result.failure
                assert failure is not None
                quorum = _call_local_literature_quorum(
                    provider=provider,
                    result=exc.result,
                )
                try:
                    evidence_artifact = _persist_literature_evidence(
                        context,
                        invocation,
                        engine_invocation=engine_invocation,
                        result=exc.result,
                        quorum=quorum,
                    )
                except Exception as seal_exc:
                    return _failed_provider_result(
                        context,
                        invocation,
                        engine_invocation=engine_invocation,
                        provider=provider,
                        error_code="artifact_seal_failed",
                        summary=(
                            f"{provider} provider failure evidence could not be sealed"
                        ),
                        raw_ref={
                            "provider_call": exc.result.to_summary_dict(),
                            "evidence_sealed": False,
                        },
                        exception_type=seal_exc.__class__.__name__,
                    )
                return _failed_provider_result(
                    context,
                    invocation,
                    engine_invocation=engine_invocation,
                    provider=provider,
                    error_code=failure.error_code,
                    summary=failure.message,
                    raw_ref={
                        "provider_call": exc.result.to_summary_dict(),
                        "call_local_literature_quorum": quorum.to_dict(),
                    },
                    artifacts=(
                        _provider_artifact_manifest(
                            evidence_artifact,
                            provider=provider,
                        ),
                    ),
                )
            except Exception as exc:  # provider SDKs can raise non-standard transport errors
                summary = (
                    f"{provider} provider call failed before returning a typed outcome"
                )
                return _failed_provider_result(
                    context,
                    invocation,
                    engine_invocation=engine_invocation,
                    provider=provider,
                    error_code="provider_unavailable",
                    summary=summary,
                    raw_ref={
                        "provider": provider,
                        "outcome": "failed",
                        "error_code": "provider_unavailable",
                        "typed_provider_outcome": False,
                    },
                    exception_type=exc.__class__.__name__,
                )

            if isinstance(provider_result, ProviderCallResult):
                hits = provider_result.items
                provider_call = provider_result.to_summary_dict()
                outcome = provider_result.outcome
                quorum = _call_local_literature_quorum(
                    provider=provider,
                    result=provider_result,
                )
            else:
                hits = tuple(provider_result)
                provider_call = {
                    "provider": provider,
                    "outcome": "completed" if hits else "empty",
                    "typed_provider_outcome": False,
                    "cutover_eligible": False,
                }
                outcome = (
                    ProviderOutcome.COMPLETED if hits else ProviderOutcome.EMPTY
                )
                quorum = None
            if isinstance(provider_result, ProviderCallResult):
                try:
                    evidence_artifact = _persist_literature_evidence(
                        context,
                        invocation,
                        engine_invocation=engine_invocation,
                        result=provider_result,
                        quorum=quorum,
                    )
                except Exception as exc:
                    return _failed_provider_result(
                        context,
                        invocation,
                        engine_invocation=engine_invocation,
                        provider=provider,
                        error_code="artifact_seal_failed",
                        summary=f"{provider} provider evidence could not be sealed",
                        raw_ref={
                            "provider_call": provider_call,
                            "evidence_sealed": False,
                        },
                        exception_type=exc.__class__.__name__,
                    )
                evidence_artifacts = (
                    _provider_artifact_manifest(
                        evidence_artifact,
                        provider=provider,
                    ),
                )
            else:
                evidence_artifact = None
                evidence_artifacts = ()
            if outcome is ProviderOutcome.FAILED:
                failure = provider_result.failure
                assert failure is not None
                return _failed_provider_result(
                    context,
                    invocation,
                    engine_invocation=engine_invocation,
                    provider=provider,
                    error_code=failure.error_code,
                    summary=failure.message,
                    raw_ref={
                        "provider_call": provider_call,
                        "call_local_literature_quorum": quorum.to_dict(),
                    },
                    artifacts=evidence_artifacts,
                )
            if provider == "pubmed" and quorum is None:
                return _failed_provider_result(
                    context,
                    invocation,
                    engine_invocation=engine_invocation,
                    provider=provider,
                    error_code="untyped_provider_outcome",
                    summary=(
                        "required PubMed evidence lacks a typed provider outcome"
                    ),
                    raw_ref={
                        "provider_call": provider_call,
                        "call_local_literature_quorum": None,
                    },
                    artifacts=evidence_artifacts,
                )
            if provider == "pubmed" and not quorum.cutover_eligible:
                required_member = next(
                    member
                    for member in quorum.members
                    if member.provider == "pubmed"
                )
                if outcome is ProviderOutcome.EMPTY:
                    error_code = "required_provider_empty"
                    summary = "pubmed returned no records for the required query"
                else:
                    error_code = (
                        required_member.error_code
                        or "required_provider_unaccepted"
                    )
                    summary = (
                        required_member.warning
                        or "required PubMed evidence did not satisfy quorum"
                    )
                return _failed_provider_result(
                    context,
                    invocation,
                    engine_invocation=engine_invocation,
                    provider=provider,
                    error_code=error_code,
                    summary=summary,
                    raw_ref={
                        "provider_call": provider_call,
                        "call_local_literature_quorum": quorum.to_dict(),
                    },
                    artifacts=evidence_artifacts,
                )
            unresolved_gaps: tuple[str, ...] = ()
            observation_status = "completed"
            if outcome is ProviderOutcome.EMPTY:
                unresolved_gaps = (
                    f"{provider} returned no records for query: {query}",
                )
            elif outcome is ProviderOutcome.DEGRADED:
                observation_status = "partial"
                unresolved_gaps = (
                    f"{provider} enrichment is degraded for query: {query}",
                )
            findings = literature_hits_to_findings(hits, query=query)
            if evidence_artifact is not None:
                for finding in findings:
                    for source in list(finding.get("sources") or []):
                        source["evidence_artifact_id"] = evidence_artifact.artifact_id
            observation = ResearchObservation(
                status=observation_status,
                summary=f"Collected {len(hits)} {provider} hits for {query}.",
                findings=tuple(findings),
                unresolved_gaps=unresolved_gaps,
                artifacts=evidence_artifacts,
                provider=provider,
                raw_ref={
                    "query": query,
                    "provider_call": provider_call,
                    "call_local_literature_quorum": (
                        None if quorum is None else quorum.to_dict()
                    ),
                },
            )
            payload = _finish_research_tool_invocation(
                context,
                invocation,
                engine_invocation,
                observation,
            )
            return _payload_result(
                invocation,
                payload,
                ok=True,
                status=outcome.value,
                summary=observation.summary,
            )

        def _provider_observation_call(
            context: SessionRuntimeContext,
            invocation: ToolInvocation,
            *,
            provider: str,
            call: Any,
            build_observation: Any,
        ) -> ToolResult:
            engine_invocation = _start_research_tool_invocation(context, invocation)
            try:
                value = call()
                observation = build_observation(value, engine_invocation)
            except ProviderRequestError as exc:
                failure = exc.result.failure
                assert failure is not None
                return _failed_provider_result(
                    context,
                    invocation,
                    engine_invocation=engine_invocation,
                    provider=provider,
                    error_code=failure.error_code,
                    summary=failure.message,
                    raw_ref={"provider_call": exc.result.to_summary_dict()},
                )
            except ArtifactBoundaryError as exc:
                return _failed_provider_result(
                    context,
                    invocation,
                    engine_invocation=engine_invocation,
                    provider=provider,
                    error_code=exc.error_code,
                    summary=f"{provider} provider evidence could not be sealed",
                    raw_ref={
                        "provider": provider,
                        "outcome": "failed",
                        "evidence_sealed": False,
                    },
                    exception_type=exc.__class__.__name__,
                )
            except Exception as exc:
                return _failed_provider_result(
                    context,
                    invocation,
                    engine_invocation=engine_invocation,
                    provider=provider,
                    error_code="provider_unavailable",
                    summary=f"{provider} provider operation failed",
                    raw_ref={
                        "provider": provider,
                        "outcome": "failed",
                        "error_code": "provider_unavailable",
                        "typed_provider_outcome": False,
                    },
                    exception_type=exc.__class__.__name__,
                )
            return _observation_result(
                context,
                invocation,
                observation,
                engine_invocation=engine_invocation,
            )

        def pubmed_search(
            context: SessionRuntimeContext, invocation: ToolInvocation
        ) -> ToolResult:
            query = str(invocation.arguments["query"])
            limit = int(invocation.arguments.get("limit", 5))
            result_method = getattr(self.service, "search_pubmed_result", None)
            call = (
                (lambda: result_method(query=query, limit=limit))
                if callable(result_method)
                else (lambda: self.service.search_pubmed(query=query, limit=limit))
            )
            return _literature_result(
                context,
                invocation,
                provider="pubmed",
                query=query,
                call=call,
            )

        def semantic_scholar_search(
            context: SessionRuntimeContext, invocation: ToolInvocation
        ) -> ToolResult:
            query = str(invocation.arguments["query"])
            limit = int(invocation.arguments.get("limit", 5))
            result_method = getattr(
                self.service, "search_semantic_scholar_result", None
            )
            call = (
                (lambda: result_method(query=query, limit=limit))
                if callable(result_method)
                else (
                    lambda: self.service.search_semantic_scholar(
                        query=query, limit=limit
                    )
                )
            )
            return _literature_result(
                context,
                invocation,
                provider="semantic_scholar",
                query=query,
                call=call,
            )

        def uniprot_lookup(
            context: SessionRuntimeContext, invocation: ToolInvocation
        ) -> ToolResult:
            accession = str(invocation.arguments["accession"])
            return _provider_observation_call(
                context,
                invocation,
                provider="uniprot",
                call=lambda: self.service.lookup_uniprot(accession=accession),
                build_observation=lambda record, engine_invocation: (
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
                ),
            )

        def uniprot_download_fasta(
            context: SessionRuntimeContext, invocation: ToolInvocation
        ) -> ToolResult:
            accession = str(invocation.arguments["accession"])
            def build_observation(
                asset: DownloadedResearchAsset,
                engine_invocation: EngineInvocation,
            ) -> ResearchObservation:
                artifact = _persist_asset(
                    context,
                    invocation,
                    asset=asset,
                    scope_label="research_tool",
                    invocation_id=engine_invocation.invocation_id,
                )
                return ResearchObservation.completed(
                    summary=f"Downloaded FASTA for {accession}.",
                    artifacts=(_artifact_manifest(asset, artifact),),
                    provider="uniprot",
                    raw_ref={"accession": accession},
                )

            return _provider_observation_call(
                context,
                invocation,
                provider="uniprot",
                call=lambda: self.service.download_uniprot_fasta(
                    accession=accession
                ),
                build_observation=build_observation,
            )

        def rcsb_search(
            context: SessionRuntimeContext, invocation: ToolInvocation
        ) -> ToolResult:
            query = str(invocation.arguments["query"])
            limit = int(invocation.arguments.get("limit", 5))
            return _provider_observation_call(
                context,
                invocation,
                provider="rcsb_pdb",
                call=lambda: self.service.search_rcsb_pdb(
                    query=query, limit=limit
                ),
                build_observation=lambda hits, engine_invocation: (
                    ResearchObservation.completed(
                        summary=f"Collected {len(hits)} structure hits for {query}.",
                        findings=tuple(
                            structure_hits_to_findings(hits, query=query)
                        ),
                        provider="rcsb_pdb",
                        raw_ref={"query": query},
                    )
                ),
            )

        def rcsb_download_structure(
            context: SessionRuntimeContext, invocation: ToolInvocation
        ) -> ToolResult:
            pdb_id = str(invocation.arguments["pdb_id"])
            file_format = str(invocation.arguments.get("format", "pdb"))
            def build_observation(
                asset: DownloadedResearchAsset,
                engine_invocation: EngineInvocation,
            ) -> ResearchObservation:
                artifact = _persist_asset(
                    context,
                    invocation,
                    asset=asset,
                    scope_label="research_tool",
                    invocation_id=engine_invocation.invocation_id,
                )
                return ResearchObservation.completed(
                    summary=f"Downloaded structure file for {pdb_id}.",
                    artifacts=(_artifact_manifest(asset, artifact),),
                    provider="rcsb_pdb",
                    raw_ref={"pdb_id": pdb_id, "format": file_format},
                )

            return _provider_observation_call(
                context,
                invocation,
                provider="rcsb_pdb",
                call=lambda: self.service.download_rcsb_structure(
                    pdb_id=pdb_id,
                    file_format=file_format,
                ),
                build_observation=build_observation,
            )

        def interpro_query(
            context: SessionRuntimeContext, invocation: ToolInvocation
        ) -> ToolResult:
            accession = str(invocation.arguments["accession"])
            limit = int(invocation.arguments.get("limit", 10))
            def build_observation(record: Any, engine_invocation: Any) -> ResearchObservation:
                del engine_invocation
                summary = (
                    f"Loaded {len(record.entries)} InterPro annotations for {accession}."
                )
                return ResearchObservation.completed(
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
                                    "snippet": None
                                    if not record.entries
                                    else str(record.entries[0].get("name") or ""),
                                }
                            ],
                        },
                    ),
                    provider="interpro",
                    raw_ref={"record": record.to_dict()},
                )

            return _provider_observation_call(
                context,
                invocation,
                provider="interpro",
                call=lambda: self.service.query_interpro(
                    accession=accession,
                    limit=limit,
                ),
                build_observation=build_observation,
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
    if service is None:
        return
    BioResearchToolRegistrar(service).register(registry)


def _web_tool_enabled(adapter: object | None) -> bool:
    return (
        adapter is not None
        and callable(getattr(adapter, "web_search", None))
        and callable(getattr(adapter, "fetch_url", None))
    )


def _rcsb_structure_page_pdb_id(url: str) -> str | None:
    match = re.search(
        r"rcsb\.org/(?:structure|experimental)/([0-9A-Za-z]{4})(?:\b|[/?#])",
        url,
    )
    if match is None:
        match = re.search(
            r"data\.rcsb\.org/rest/v1/core/[A-Za-z0-9_/-]+/([0-9A-Za-z]{4})(?:\b|[/?#])",
            url,
        )
    if match is None:
        return None
    return match.group(1).upper()


def register_web_research_tools(
    registry: ToolRegistry,
    *,
    adapter: object | None = None,
) -> None:
    if not _web_tool_enabled(adapter):
        return

    def _payload_result(
        invocation: ToolInvocation, payload: dict[str, object], *, ok: bool = True
    ) -> ToolResult:
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
        *,
        ok: bool = True,
        engine_invocation: EngineInvocation | None = None,
    ) -> ToolResult:
        active_invocation = engine_invocation or _start_research_tool_invocation(
            context, invocation
        )
        return _payload_result(
            invocation,
            _finish_research_tool_invocation(
                context, invocation, active_invocation, observation
            ),
            ok=ok,
        )

    def _failed_result(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
        *,
        engine_invocation: EngineInvocation,
        error_code: str,
        summary: str,
        raw_ref: dict[str, Any],
        exception_type: str | None = None,
    ) -> ToolResult:
        payload = _finish_research_tool_invocation(
            context,
            invocation,
            engine_invocation,
            ResearchObservation(
                status="failed",
                summary=summary,
                unresolved_gaps=(summary,),
                provider="tavily",
                raw_ref=raw_ref,
            ),
        )
        result = _payload_result(invocation, payload, ok=False)
        return ToolResult(
            call_id=result.call_id,
            tool_name=result.tool_name,
            ok=False,
            content=result.content,
            task_id=result.task_id,
            lane_id=result.lane_id,
            status=error_code,
            summary=summary,
            error_code=error_code,
            details=(
                None
                if exception_type is None
                else {"exception_type": exception_type}
            ),
        )

    def web_search(
        context: SessionRuntimeContext, invocation: ToolInvocation
    ) -> ToolResult:
        query = str(invocation.arguments["query"])
        max_results = int(invocation.arguments.get("max_results", 3))
        topic = str(invocation.arguments.get("topic", "general"))
        if topic not in {"general", "news", "finance"}:
            raise ValueError(
                "topic must be one of 'general', 'news', or 'finance'; "
                "put the semantic research subject in query"
            )
        include_raw_content = bool(
            invocation.arguments.get("include_raw_content", True)
        )
        engine_invocation = _start_research_tool_invocation(context, invocation)
        unit = ResearchUnit(
            unit_id=f"web-search-{invocation.call_id}",
            topic=topic,
            query=query,
        )
        try:
            result_method = getattr(adapter, "web_search_result", None)
            normalize_result = getattr(adapter, "normalize_search_result", None)
            if callable(result_method) and callable(normalize_result):
                provider_result = result_method(
                    query=query,
                    max_results=max_results,
                    topic=topic,
                    include_raw_content=include_raw_content,
                )
                result = normalize_result(unit=unit, result=provider_result)
                evidence_artifact = _persist_web_evidence(
                    context,
                    invocation,
                    engine_invocation=engine_invocation,
                    result=provider_result,
                    findings=result.findings,
                )
                artifacts = (
                    _provider_artifact_manifest(
                        evidence_artifact,
                        provider="tavily",
                    ),
                )
            else:
                search = getattr(adapter, "web_search")
                normalize = getattr(adapter, "normalize_search_response")
                result = normalize(
                    unit=unit,
                    response=search(
                        query=query,
                        max_results=max_results,
                        topic=topic,
                        include_raw_content=include_raw_content,
                    ),
                )
                artifacts = ()
        except ProviderRequestError as exc:
            failure = exc.result.failure
            assert failure is not None
            return _failed_result(
                context,
                invocation,
                engine_invocation=engine_invocation,
                error_code=failure.error_code,
                summary=failure.message,
                raw_ref={"provider_call": exc.result.to_summary_dict()},
            )
        except Exception as exc:
            return _failed_result(
                context,
                invocation,
                engine_invocation=engine_invocation,
                error_code="provider_unavailable",
                summary="tavily provider operation failed",
                raw_ref={
                    "provider": "tavily",
                    "outcome": "failed",
                    "typed_provider_outcome": False,
                },
                exception_type=exc.__class__.__name__,
            )
        return _observation_result(
            context,
            invocation,
            ResearchObservation(
                status=result.status,
                summary=result.summary,
                findings=result.findings,
                unresolved_gaps=result.unresolved_gaps,
                artifacts=artifacts,
                provider="web",
                raw_ref={
                    "unit_id": result.unit_id,
                    "error_message": result.error_message,
                    "escalation_reason": result.escalation_reason,
                    "provider_outcome": result.provider_outcome,
                    "provider_call": result.provider_call,
                },
            ),
            ok=result.status != "failed",
            engine_invocation=engine_invocation,
        )

    def web_fetch(
        context: SessionRuntimeContext, invocation: ToolInvocation
    ) -> ToolResult:
        url = str(invocation.arguments["url"])
        public_url = safe_public_locator(url)
        if public_url is None:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content="web.fetch requires a public HTTP(S) URL.",
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
                status="private_url_forbidden",
                summary="Private or invalid URLs are not accepted by web.fetch.",
                error_code="private_url_forbidden",
            )
        url = public_url
        rcsb_pdb_id = _rcsb_structure_page_pdb_id(url)
        if rcsb_pdb_id is not None:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=(
                    "web.fetch only reads web page text and does not persist a "
                    "structure artifact. Use rcsb_pdb.download_structure with "
                    f"pdb_id={rcsb_pdb_id!r} for this RCSB structure."
                ),
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
                status="wrong_tool_for_structure_download",
                summary="Use rcsb_pdb.download_structure to persist this RCSB structure.",
                error_code="wrong_tool_for_structure_download",
                hint=(
                    "Call rcsb_pdb.download_structure with "
                    f"pdb_id={rcsb_pdb_id!r} and format='pdb'."
                ),
                details={"pdb_id": rcsb_pdb_id, "url": url},
            )
        query = (
            None
            if invocation.arguments.get("query") is None
            else str(invocation.arguments["query"])
        )
        extract_depth = str(invocation.arguments.get("extract_depth", "basic"))
        output_format = str(invocation.arguments.get("format", "markdown"))
        include_images = bool(invocation.arguments.get("include_images", False))
        engine_invocation = _start_research_tool_invocation(context, invocation)
        try:
            result_method = getattr(adapter, "fetch_url_result", None)
            if callable(result_method):
                provider_result = result_method(
                    url=url,
                    query=query,
                    extract_depth=extract_depth,
                    format=output_format,
                    include_images=include_images,
                )
                result = getattr(adapter, "normalize_fetch_response")(
                    url=url,
                    query=query,
                    response={
                        "results": [dict(item) for item in provider_result.items],
                        "provider_call": {
                            "outcome": provider_result.outcome.value,
                            "item_count": len(provider_result.items),
                            "provenance": provider_result.provenance.to_dict(),
                            "failure": None
                            if provider_result.failure is None
                            else provider_result.failure.to_dict(),
                            "warnings": list(provider_result.warnings),
                        },
                    },
                )
                evidence_artifact = _persist_web_evidence(
                    context,
                    invocation,
                    engine_invocation=engine_invocation,
                    result=provider_result,
                    findings=result.findings,
                )
                artifacts = (
                    _provider_artifact_manifest(
                        evidence_artifact,
                        provider="tavily",
                    ),
                )
            else:
                fetch = getattr(adapter, "fetch_url")
                normalize = getattr(adapter, "normalize_fetch_response")
                result = normalize(
                    url=url,
                    query=query,
                    response=fetch(
                        url=url,
                        query=query,
                        extract_depth=extract_depth,
                        format=output_format,
                        include_images=include_images,
                    ),
                )
                artifacts = ()
        except ProviderRequestError as exc:
            failure = exc.result.failure
            assert failure is not None
            return _failed_result(
                context,
                invocation,
                engine_invocation=engine_invocation,
                error_code=failure.error_code,
                summary=failure.message,
                raw_ref={"provider_call": exc.result.to_summary_dict()},
            )
        except Exception as exc:
            return _failed_result(
                context,
                invocation,
                engine_invocation=engine_invocation,
                error_code="provider_unavailable",
                summary="tavily provider operation failed",
                raw_ref={
                    "provider": "tavily",
                    "outcome": "failed",
                    "typed_provider_outcome": False,
                },
                exception_type=exc.__class__.__name__,
            )
        return _observation_result(
            context,
            invocation,
            ResearchObservation(
                status=result.status,
                summary=result.summary,
                findings=result.findings,
                unresolved_gaps=result.unresolved_gaps,
                artifacts=artifacts,
                provider="web",
                raw_ref={
                    "unit_id": result.unit_id,
                    "error_message": result.error_message,
                    "escalation_reason": result.escalation_reason,
                    "provider_outcome": result.provider_outcome,
                    "provider_call": result.provider_call,
                },
            ),
            ok=result.status != "failed",
            engine_invocation=engine_invocation,
        )

    registry.register("web.search", web_search)
    registry.register("web.fetch", web_fetch)


__all__ = [
    "persist_research_observation",
    "register_bio_research_tools",
    "register_web_research_tools",
]
