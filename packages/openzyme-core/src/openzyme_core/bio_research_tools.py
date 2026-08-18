from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any
from uuid import uuid4

from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import SourceRefKind
from openzyme_domain.control_plane import utc_now_iso
from openzyme_research import BioResearchService
from openzyme_research import DownloadedResearchAsset
from openzyme_research import EvidenceQuorumResult
from openzyme_research import ProviderCallResult
from openzyme_research import ProviderOutcome
from openzyme_research import ProviderRequestError
from openzyme_research import ResearchObservation
from openzyme_research import ResearchUnit
from openzyme_research import literature_hits_to_findings
from openzyme_research import evaluate_literature_quorum
from openzyme_research import safe_literature_evidence_payload
from openzyme_research import safe_public_locator
from openzyme_research import structure_hits_to_findings

from openzyme_runtime import sanitize_public_diagnostic_payload
from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .repositories import EngineDocumentRecord
from .workspace_file_handoffs import WorkspaceFileHandoffError
from .workspace_file_handoffs import write_bytes_to_current_agent_workspace
from .workspace_file_handoffs import write_json_to_current_agent_workspace


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


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


def _safe_repository_component(value: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.")
    return (normalized or fallback)[:128]


def _research_file_path(
    *,
    invocation_id: str,
    category: str,
    filename: str,
) -> str:
    return "/".join(
        (
            "research",
            _safe_repository_component(invocation_id, fallback="invocation"),
            _safe_repository_component(category, fallback="files"),
            _safe_repository_component(filename, fallback="result.json"),
        )
    )


def _write_downloaded_asset(
    context: SessionRuntimeContext,
    *,
    asset: DownloadedResearchAsset,
    invocation_id: str,
) -> dict[str, object]:
    result = write_bytes_to_current_agent_workspace(
        context,
        repository_path=_research_file_path(
            invocation_id=invocation_id,
            category="downloads",
            filename=asset.filename,
        ),
        content=asset.content,
    )
    return {
        **result.to_dict(),
        "provider": asset.provider,
        "external_id": asset.external_id,
        "format": asset.format,
        "source_locator": safe_public_locator(asset.locator),
    }


def _write_literature_evidence(
    context: SessionRuntimeContext,
    *,
    engine_invocation: EngineInvocation,
    result: ProviderCallResult[Any],
    quorum: EvidenceQuorumResult,
) -> dict[str, object]:
    evidence = safe_literature_evidence_payload(result)
    evidence["call_local_literature_quorum"] = quorum.to_dict()
    return write_json_to_current_agent_workspace(
        context,
        repository_path=_research_file_path(
            invocation_id=engine_invocation.invocation_id,
            category="source-snapshots",
            filename=(
                f"{result.provenance.provider}-literature-evidence.json"
            ),
        ),
        payload=evidence,
    ).to_dict()


def _write_web_evidence(
    context: SessionRuntimeContext,
    *,
    engine_invocation: EngineInvocation,
    result: ProviderCallResult[Any],
    findings: tuple[Any, ...],
) -> dict[str, object]:
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
    return write_json_to_current_agent_workspace(
        context,
        repository_path=_research_file_path(
            invocation_id=engine_invocation.invocation_id,
            category="source-snapshots",
            filename="tavily-web-evidence.json",
        ),
        payload=evidence,
    ).to_dict()


def _start_research_tool_invocation(
    context: SessionRuntimeContext,
    invocation: ToolInvocation,
) -> EngineInvocation:
    now = utc_now_iso()
    safe_arguments = _safe_research_arguments(dict(invocation.arguments))
    if len(json.dumps(safe_arguments, ensure_ascii=False).encode("utf-8")) > 8_192:
        raise ValueError("research tool arguments exceed the bounded metadata limit")
    engine_invocation_id = _new_id("inv_research_tool")
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
    with context.repositories.atomic(prefix="research_tool_start"):
        context.repositories.invocations.save(engine_invocation)
        context.repositories.engine_documents.save(
            EngineDocumentRecord(
                document_id=input_document_id,
                session_id=engine_invocation.session_id,
                invocation_id=engine_invocation.invocation_id,
                document_kind="research_tool_input",
                payload={
                    "tool_name": invocation.tool_name,
                    "arguments": safe_arguments,
                    "call_id": invocation.call_id,
                },
                created_at=now,
                updated_at=now,
            )
        )
    return engine_invocation


def _fail_research_tool_invocation(
    context: SessionRuntimeContext,
    engine_invocation: EngineInvocation,
) -> EngineInvocation:
    failed = EngineInvocation(
        invocation_id=engine_invocation.invocation_id,
        session_id=engine_invocation.session_id,
        task_id=engine_invocation.task_id,
        lane_id=engine_invocation.lane_id,
        engine_name=engine_invocation.engine_name,
        status=EngineInvocationStatus.FAILED,
        input_ref=engine_invocation.input_ref,
        output_ref=None,
        approval_id=engine_invocation.approval_id,
        idempotency_key=engine_invocation.idempotency_key,
        started_at=engine_invocation.started_at,
        finished_at=utc_now_iso(),
    )
    context.repositories.invocations.save(failed)
    return failed


def _finish_research_tool_invocation(
    context: SessionRuntimeContext,
    invocation: ToolInvocation,
    engine_invocation: EngineInvocation,
    observation: ResearchObservation,
) -> dict[str, Any]:
    now = utc_now_iso()
    observation_payload = sanitize_public_diagnostic_payload(observation.to_dict())
    if not isinstance(observation_payload, dict):
        raise TypeError("research observation projection must be an object")
    write_result = write_json_to_current_agent_workspace(
        context,
        repository_path=_research_file_path(
            invocation_id=engine_invocation.invocation_id,
            category="observations",
            filename="observation.json",
        ),
        payload=observation_payload,
    )
    output_document_id = f"{engine_invocation.invocation_id}:output"
    terminal_status = (
        EngineInvocationStatus.FAILED
        if observation.status.lower() in {"failed", "error"}
        else EngineInvocationStatus.SUCCEEDED
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
    with context.repositories.atomic(prefix="research_tool_finish"):
        context.repositories.engine_documents.save(
            EngineDocumentRecord(
                document_id=output_document_id,
                session_id=engine_invocation.session_id,
                invocation_id=engine_invocation.invocation_id,
                document_kind="research_tool_file_index",
                payload={
                    "schema_version": "research_tool_file_index@1",
                    "tool_name": invocation.tool_name,
                    "workspace_file": write_result.to_dict(),
                },
                created_at=now,
                updated_at=now,
            )
        )
        context.repositories.invocations.save(completed_invocation)
    return {
        "schema_version": "research_tool_result@1",
        "status": observation.status,
        "summary": observation.summary,
        "provider": observation.provider,
        "finding_count": len(observation.findings),
        "unresolved_gap_count": len(observation.unresolved_gaps),
        "workspace_file": write_result.to_dict(),
        "publication_required_for_handoff": True,
    }


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
            private_diagnostic: object | None = None,
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
                private_diagnostic=private_diagnostic,
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
            try:
                payload = _finish_research_tool_invocation(
                    context, invocation, active_invocation, observation
                )
            except WorkspaceFileHandoffError as exc:
                _fail_research_tool_invocation(context, active_invocation)
                return _payload_result(
                    invocation,
                    {
                        "schema_version": "research_tool_result@1",
                        "status": "failed",
                        "workspace_file_written": False,
                        "publication_required_for_handoff": True,
                    },
                    ok=False,
                    status=exc.error_code,
                    summary="research observation could not be written",
                    error_code=exc.error_code,
                    details=exc.to_public_details(),
                    private_diagnostic=exc,
                )
            return _payload_result(invocation, payload)

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
            diagnostic_details: dict[str, object] | None = None,
            private_diagnostic: object | None = None,
            workspace_files: tuple[dict[str, object], ...] = (),
        ) -> ToolResult:
            observation = ResearchObservation(
                status="failed",
                summary=summary,
                unresolved_gaps=(summary,),
                provider=provider,
                raw_ref={**raw_ref, "workspace_files": list(workspace_files)},
            )
            try:
                payload = _finish_research_tool_invocation(
                    context,
                    invocation,
                    engine_invocation,
                    observation,
                )
            except WorkspaceFileHandoffError as write_exc:
                _fail_research_tool_invocation(context, engine_invocation)
                payload = {
                    "schema_version": "research_tool_result@1",
                    "status": "failed",
                    "provider": provider,
                    "workspace_file_written": False,
                    "publication_required_for_handoff": True,
                }
                error_code = write_exc.error_code
                summary = "research failure observation could not be written"
                exception_type = write_exc.__class__.__name__
                diagnostic_details = write_exc.to_public_details()
                private_diagnostic = write_exc
            return _payload_result(
                invocation,
                payload,
                ok=False,
                status=error_code,
                summary=summary,
                error_code=error_code,
                details={
                    **(diagnostic_details or {}),
                    **(
                        {}
                        if exception_type is None
                        else {"exception_type": exception_type}
                    ),
                },
                private_diagnostic=private_diagnostic,
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
                    evidence_file = _write_literature_evidence(
                        context,
                        engine_invocation=engine_invocation,
                        result=exc.result,
                        quorum=quorum,
                    )
                except WorkspaceFileHandoffError as write_exc:
                    return _failed_provider_result(
                        context,
                        invocation,
                        engine_invocation=engine_invocation,
                        provider=provider,
                        error_code="workspace_file_write_failed",
                        summary=(
                            f"{provider} provider failure evidence could not be written"
                        ),
                        raw_ref={
                            "provider_call": exc.result.to_summary_dict(),
                            "evidence_file_written": False,
                        },
                        exception_type=write_exc.__class__.__name__,
                        diagnostic_details=write_exc.to_public_details(),
                        private_diagnostic=write_exc,
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
                    workspace_files=(evidence_file,),
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
                    private_diagnostic=exc,
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
                    evidence_file = _write_literature_evidence(
                        context,
                        engine_invocation=engine_invocation,
                        result=provider_result,
                        quorum=quorum,
                    )
                except WorkspaceFileHandoffError as exc:
                    return _failed_provider_result(
                        context,
                        invocation,
                        engine_invocation=engine_invocation,
                        provider=provider,
                        error_code="workspace_file_write_failed",
                        summary=f"{provider} provider evidence could not be written",
                        raw_ref={
                            "provider_call": provider_call,
                            "evidence_file_written": False,
                        },
                        exception_type=exc.__class__.__name__,
                        diagnostic_details=exc.to_public_details(),
                        private_diagnostic=exc,
                    )
                evidence_files = (evidence_file,)
            else:
                evidence_files = ()
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
                    workspace_files=evidence_files,
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
                    workspace_files=evidence_files,
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
                    workspace_files=evidence_files,
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
            observation = ResearchObservation(
                status=observation_status,
                summary=f"Collected {len(hits)} {provider} hits for {query}.",
                findings=tuple(findings),
                unresolved_gaps=unresolved_gaps,
                provider=provider,
                raw_ref={
                    "query": query,
                    "provider_call": provider_call,
                    "call_local_literature_quorum": (
                        None if quorum is None else quorum.to_dict()
                    ),
                    "workspace_files": list(evidence_files),
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
            except WorkspaceFileHandoffError as exc:
                return _failed_provider_result(
                    context,
                    invocation,
                    engine_invocation=engine_invocation,
                    provider=provider,
                    error_code=exc.error_code,
                    summary=f"{provider} provider output could not be written",
                    raw_ref={
                        "provider": provider,
                        "outcome": "failed",
                        "workspace_file_written": False,
                    },
                    exception_type=exc.__class__.__name__,
                    diagnostic_details=exc.to_public_details(),
                    private_diagnostic=exc,
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
                    private_diagnostic=exc,
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
                    )
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
                workspace_file = _write_downloaded_asset(
                    context,
                    asset=asset,
                    invocation_id=engine_invocation.invocation_id,
                )
                return ResearchObservation.completed(
                    summary=f"Downloaded FASTA for {accession}.",
                    provider="uniprot",
                    raw_ref={
                        "accession": accession,
                        "workspace_files": [workspace_file],
                    },
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
                workspace_file = _write_downloaded_asset(
                    context,
                    asset=asset,
                    invocation_id=engine_invocation.invocation_id,
                )
                return ResearchObservation.completed(
                    summary=f"Downloaded structure file for {pdb_id}.",
                    provider="rcsb_pdb",
                    raw_ref={
                        "pdb_id": pdb_id,
                        "format": file_format,
                        "workspace_files": [workspace_file],
                    },
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
                evidence_file = _write_web_evidence(
                    context,
                    engine_invocation=engine_invocation,
                    result=provider_result,
                    findings=result.findings,
                )
                workspace_files = (evidence_file,)
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
                workspace_files = ()
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
                provider="web",
                raw_ref={
                    "unit_id": result.unit_id,
                    "error_message": result.error_message,
                    "escalation_reason": result.escalation_reason,
                    "provider_outcome": result.provider_outcome,
                    "provider_call": result.provider_call,
                    "workspace_files": list(workspace_files),
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
                    "structure file. Use rcsb_pdb.download_structure with "
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
                evidence_file = _write_web_evidence(
                    context,
                    engine_invocation=engine_invocation,
                    result=provider_result,
                    findings=result.findings,
                )
                workspace_files = (evidence_file,)
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
                workspace_files = ()
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
                provider="web",
                raw_ref={
                    "unit_id": result.unit_id,
                    "error_message": result.error_message,
                    "escalation_reason": result.escalation_reason,
                    "provider_outcome": result.provider_outcome,
                    "provider_call": result.provider_call,
                    "workspace_files": list(workspace_files),
                },
            ),
            ok=result.status != "failed",
            engine_invocation=engine_invocation,
        )

    registry.register("web.search", web_search)
    registry.register("web.fetch", web_fetch)


__all__ = [
    "register_bio_research_tools",
    "register_web_research_tools",
]
