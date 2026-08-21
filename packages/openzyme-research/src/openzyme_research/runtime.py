from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import ProjectionRequest
from openzyme_extension_spi import ProjectionResult
from openzyme_extension_spi import WorkerClaim
from openzyme_extension_spi import WorkerClaimRequest

from .contracts import ResearchRequest
from .contracts import ResearchUnitSpec
from .services import RESEARCH_PLUGIN_ID
from .services import ResearchOrchestrationService
from .services import ResearchRepository
from .services import utc_now_iso


RESEARCH_START_TOOL_SPEC = ToolSpec(
    tool_name="deep_research.start",
    description=(
        "Start one explicit, bounded Research invocation. Provider transcripts are "
        "not publications, scientific adoption, Task evidence, or Task completion."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["brief", "units"],
        "properties": {
            "brief": {"type": "string", "minLength": 1, "maxLength": 8192},
            "units": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["unit_id", "topic", "query"],
                    "properties": {
                        "unit_id": {"type": "string", "minLength": 1},
                        "topic": {"type": "string", "minLength": 1},
                        "query": {"type": "string", "minLength": 1},
                    },
                },
            },
        },
    },
    output_schema={
        "type": "object",
        "required": [
            "invocation_id",
            "request_digest",
            "status",
            "publication_created",
            "task_finished",
        ],
    },
    required_authorities=("ordinary_network",),
)

RESEARCH_PROJECTION_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "schema_version": "openzyme.research@1",
        "safe_fields": [
            "invocation_id",
            "request_digest",
            "provider_id",
            "route_id",
            "status",
            "source_count",
            "publication_ref",
            "task_finished",
            "sources",
        ],
        "source_safe_fields": [
            "source_id",
            "title",
            "locator",
            "kind",
            "content_digest",
            "retrieved_at",
        ],
        "forbidden": [
            "provider_transcript",
            "raw_response",
            "credential",
            "host_path",
            "private_path",
            "storage_uri",
        ],
        "pagination": "invocation_id_exclusive",
    }
)


@dataclass(slots=True)
class ResearchStartToolRuntime:
    service: ResearchOrchestrationService
    owner_plugin_id: str = RESEARCH_PLUGIN_ID
    runtime_id: str = "openzyme.research.deep-research-start@1"

    @property
    def contract(self) -> ToolSpec:
        return RESEARCH_START_TOOL_SPEC

    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        if invocation.tool_name != self.contract.tool_name:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                status="rejected",
                summary="Research runtime received a different tool contract.",
                payload={},
                error_code="research_tool_contract_mismatch",
            )
        try:
            units_value = invocation.arguments.get("units")
            if not isinstance(units_value, (list, tuple)):
                raise ValueError("units must be an array")
            units = tuple(
                ResearchUnitSpec(
                    unit_id=str(item["unit_id"]),
                    topic=str(item["topic"]),
                    query=str(item["query"]),
                )
                for item in units_value
                if isinstance(item, Mapping)
            )
            if len(units) != len(units_value):
                raise ValueError("every Research unit must be an object")
            request = ResearchRequest(
                request_id=f"request-{invocation.call_id}",
                session_id=invocation.session_id,
                actor_id=invocation.agent_member_id,
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
                brief=str(invocation.arguments.get("brief") or ""),
                units=units,
                created_at=utc_now_iso(),
            )
            record = self.service.admit(
                invocation_id=f"research-{invocation.call_id}",
                request=request,
            )
        except (KeyError, TypeError, ValueError) as exc:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                status="rejected",
                summary=str(exc),
                payload={"mutation_applied": False, "fallback_performed": False},
                error_code="research_request_invalid",
            )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            status="accepted",
            summary="Research invocation admitted for bounded worker execution.",
            payload={
                "invocation_id": record.invocation_id,
                "request_digest": record.request.request_digest,
                "status": record.status.value,
                "publication_created": False,
                "task_evidence_created": False,
                "task_finished": False,
            },
        )


@dataclass(slots=True)
class ResearchWorker:
    repository: ResearchRepository
    service: ResearchOrchestrationService
    worker_id: str = "openzyme.research.worker@1"

    def claim(self, request: WorkerClaimRequest) -> tuple[WorkerClaim, ...]:
        if request.owner_plugin_id != RESEARCH_PLUGIN_ID:
            return ()
        return tuple(
            WorkerClaim(
                claim_id=f"claim-{record.invocation_id}-{record.state_version}",
                work_item_id=record.invocation_id,
                source_version=record.state_version,
                fence=request.activation_epoch,
                bounded_payload={"status": record.status.value},
            )
            for record in self.repository.list_claimable(limit=request.max_items)
        )

    def run(self, claim: WorkerClaim) -> ToolResult:
        current = self.repository.get(claim.work_item_id)
        if current is None or current.state_version != claim.source_version:
            return ToolResult(
                call_id=claim.claim_id,
                tool_name="deep_research.start",
                ok=False,
                status="rejected",
                summary="Research worker claim is stale.",
                payload={"mutation_applied": False, "fallback_performed": False},
                error_code="research_worker_claim_stale",
            )
        updated = self.service.run(current.invocation_id)
        return ToolResult(
            call_id=claim.claim_id,
            tool_name="deep_research.start",
            ok=True,
            status=updated.status.value,
            summary="Research worker recorded the exact provider outcome.",
            payload={
                "invocation_id": updated.invocation_id,
                "status": updated.status.value,
                "source_count": len(updated.source_ids),
                "publication_created": updated.publication_ref is not None,
                "task_evidence_created": False,
                "task_finished": False,
                "fallback_performed": False,
            },
        )


@dataclass(slots=True)
class ResearchProjection:
    repository: ResearchRepository
    section_id: str = "openzyme.research@1"
    section_contract_digest: str = RESEARCH_PROJECTION_CONTRACT_DIGEST

    def project(self, request: ProjectionRequest) -> ProjectionResult:
        if not request.context.actor_id:
            raise ValueError("Research projection requires an authenticated actor")
        records = self.repository.list_session(request.context.session_id)
        start = 0
        if request.cursor is not None:
            matching = tuple(
                index
                for index, record in enumerate(records)
                if record.invocation_id == request.cursor
            )
            if len(matching) != 1:
                raise ValueError("Research projection cursor is stale or unknown")
            start = matching[0] + 1
        page = records[start : start + request.max_items]
        next_cursor = (
            page[-1].invocation_id
            if page and start + len(page) < len(records)
            else None
        )
        payload: dict[str, Any] = {
            "invocations": [
                {
                    "invocation_id": record.invocation_id,
                    "request_digest": record.request.request_digest,
                    "provider_id": record.provider_id,
                    "route_id": record.route_id,
                    "status": record.status.value,
                    "source_count": len(record.source_ids),
                    "publication_ref": (
                        None
                        if record.publication_ref is None
                        else record.publication_ref.to_dict()
                    ),
                    "task_finished": False,
                    "sources": [
                        {
                            "source_id": source.source_id,
                            "title": source.title,
                            "locator": source.locator,
                            "kind": source.kind.value,
                            "content_digest": source.content_digest,
                            "retrieved_at": source.retrieved_at,
                        }
                        for receipt in self.repository.provider_receipts(
                            record.operation_ids
                        )
                        for source in receipt.sources
                    ],
                }
                for record in page
            ]
        }
        digest_payload = {
            "section_id": self.section_id,
            "section_contract_digest": self.section_contract_digest,
            "payload": payload,
            "next_cursor": next_cursor,
        }
        return ProjectionResult(
            section_id=self.section_id,
            section_contract_digest=self.section_contract_digest,
            payload=payload,
            next_cursor=next_cursor,
            projection_digest=canonical_sha256_digest(digest_payload),
        )


@dataclass(frozen=True, slots=True)
class ResearchPluginRuntimeSurfaces:
    tools: tuple[ResearchStartToolRuntime, ...]
    projections: tuple[ResearchProjection, ...]
    workers: tuple[ResearchWorker, ...]


def build_research_plugin_runtime_surfaces(
    *,
    repository: ResearchRepository,
    service: ResearchOrchestrationService,
) -> ResearchPluginRuntimeSurfaces:
    """Build the exact runtime objects declared by ``openzyme.research``.

    Discovery remains manifest-only.  A Distribution must call this builder
    explicitly and pass the resulting objects through the Kernel mount gate.
    """

    return ResearchPluginRuntimeSurfaces(
        tools=(ResearchStartToolRuntime(service),),
        projections=(ResearchProjection(repository),),
        workers=(ResearchWorker(repository=repository, service=service),),
    )


__all__ = [
    "RESEARCH_START_TOOL_SPEC",
    "RESEARCH_PROJECTION_CONTRACT_DIGEST",
    "ResearchPluginRuntimeSurfaces",
    "ResearchProjection",
    "ResearchStartToolRuntime",
    "ResearchWorker",
    "build_research_plugin_runtime_surfaces",
]
