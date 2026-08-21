from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import ProjectionRequest
from openzyme_extension_spi import ProjectionResult
from openzyme_extension_spi import WorkerClaim
from openzyme_extension_spi import WorkerClaimRequest

from .transaction import ComputeTransactionParticipant


COMPUTE_PLUGIN_ID = "openzyme.compute"
COMPUTE_PROJECTION_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "schema_version": "openzyme.compute@1",
        "safe_fields": [
            "execution_id",
            "operation_id",
            "owner_agent_member_id",
            "workspace_id",
            "workspace_generation",
            "source_revision_id",
            "workload_id",
            "workload_digest",
            "route_id",
            "target_id",
            "inventory_generation",
            "provider_handle",
            "result_id",
            "result_state",
            "result_digest",
        ],
        "forbidden": [
            "host_path",
            "remote_root",
            "login_alias",
            "scheduler_job_id",
            "raw_log",
            "credential",
        ],
    }
)
COMPUTE_RENDERER_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "schema_version": "openzyme_ui_renderer_contract@1",
        "renderer_id": "openzyme.compute.renderer@1",
        "section_id": "openzyme.compute@1",
        "read_only": True,
        "requires_exact_section_contract": COMPUTE_PROJECTION_CONTRACT_DIGEST,
        "mutates_core_state": False,
    }
)


_SAFE_OUTPUT = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "execution_id",
        "operation_id",
        "state",
        "fallback_performed",
        "publication_created",
        "scientific_evidence_created",
        "task_finished",
    ],
    "properties": {
        "execution_id": {"type": "string", "minLength": 1},
        "operation_id": {"type": "string", "minLength": 1},
        "state": {"type": "string", "minLength": 1},
        "fallback_performed": {"type": "boolean"},
        "publication_created": {"type": "boolean"},
        "scientific_evidence_created": {"type": "boolean"},
        "task_finished": {"type": "boolean"},
    },
}


COMPUTE_TOOL_SPECS = (
    ToolSpec(
        tool_name="workspace_revision_job.submit",
        description=(
            "Submit one prevalidated, immutable-revision Compute request through the "
            "explicit selected route. No staging, publication, route fallback or Task "
            "completion is performed."
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "compute_request_id",
                "request_digest",
                "route_id",
                "affordance_snapshot_digest",
            ],
            "properties": {
                "compute_request_id": {"type": "string", "minLength": 1},
                "request_digest": {
                    "type": "string",
                    "pattern": "^sha256:[0-9a-f]{64}$",
                },
                "route_id": {"type": "string", "minLength": 1},
                "affordance_snapshot_digest": {
                    "type": "string",
                    "pattern": "^sha256:[0-9a-f]{64}$",
                },
            },
        },
        output_schema=_SAFE_OUTPUT,
        required_authorities=("external_compute",),
    ),
    ToolSpec(
        tool_name="workspace_revision_job.observe",
        description=(
            "Observe or reconcile the original opaque Compute occurrence without "
            "redispatch or route replacement."
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["execution_id", "operation_id"],
            "properties": {
                "execution_id": {"type": "string", "minLength": 1},
                "operation_id": {"type": "string", "minLength": 1},
            },
        },
        output_schema=_SAFE_OUTPUT,
        required_authorities=("external_compute",),
    ),
    ToolSpec(
        tool_name="workspace_revision_job.cancel",
        description=(
            "Record one durable cancellation intent for the original Compute occurrence. "
            "Lost responses are reconciled and never cause duplicate cancellation."
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["execution_id", "operation_id", "idempotency_key"],
            "properties": {
                "execution_id": {"type": "string", "minLength": 1},
                "operation_id": {"type": "string", "minLength": 1},
                "idempotency_key": {"type": "string", "minLength": 1},
            },
        },
        output_schema=_SAFE_OUTPUT,
        required_authorities=("external_compute",),
    ),
)


@dataclass(frozen=True, slots=True)
class ComputeToolContext:
    call_id: str
    session_id: str
    agent_member_id: str
    task_id: str | None
    lane_id: str | None
    route_id: str | None
    affordance_snapshot_digest: str | None


class ComputeToolApplication(Protocol):
    def invoke(
        self,
        *,
        tool_name: str,
        context: ComputeToolContext,
        arguments: Mapping[str, JsonValue],
    ) -> Mapping[str, JsonValue]: ...


@dataclass(slots=True)
class ComputeToolRuntime:
    contract: ToolSpec
    application: ComputeToolApplication
    owner_plugin_id: str = COMPUTE_PLUGIN_ID

    @property
    def runtime_id(self) -> str:
        return f"openzyme.compute.{self.contract.tool_name.replace('.', '-')}@1"

    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        if invocation.tool_name != self.contract.tool_name:
            return self._rejected(
                invocation,
                "compute_tool_identity_mismatch",
                "Compute runtime received another tool identity.",
            )
        if self.contract.tool_name.endswith(".submit") and (
            invocation.route_id is None
            or invocation.affordance_snapshot_digest is None
            or invocation.arguments.get("route_id") != invocation.route_id
            or invocation.arguments.get("affordance_snapshot_digest")
            != invocation.affordance_snapshot_digest
        ):
            return self._rejected(
                invocation,
                "compute_route_or_affordance_missing",
                "Compute submission requires the exact selected route and affordance snapshot.",
            )
        context = ComputeToolContext(
            call_id=invocation.call_id,
            session_id=invocation.session_id,
            agent_member_id=invocation.agent_member_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            route_id=invocation.route_id,
            affordance_snapshot_digest=invocation.affordance_snapshot_digest,
        )
        try:
            result = dict(
                self.application.invoke(
                    tool_name=self.contract.tool_name,
                    context=context,
                    arguments=invocation.arguments,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            return self._rejected(
                invocation,
                getattr(exc, "error_code", "compute_tool_request_invalid"),
                str(exc),
            )
        result.update(
            {
                "fallback_performed": False,
                "publication_created": False,
                "scientific_evidence_created": False,
                "task_finished": False,
            }
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            status="accepted",
            summary="Compute accepted the exact route-bound occurrence.",
            payload=result,
        )

    @staticmethod
    def _rejected(
        invocation: ToolInvocation,
        error_code: str,
        summary: str,
    ) -> ToolResult:
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=False,
            status="rejected",
            summary=summary,
            payload={
                "mutation_applied": False,
                "fallback_performed": False,
                "publication_created": False,
                "scientific_evidence_created": False,
                "task_finished": False,
            },
            error_code=error_code,
        )


class ComputeProjectionApplication(Protocol):
    def project(
        self,
        *,
        session_id: str,
        actor_id: str,
        max_items: int,
        cursor: str | None,
    ) -> tuple[Mapping[str, JsonValue], str | None]: ...


@dataclass(slots=True)
class ComputeProjectionContributor:
    application: ComputeProjectionApplication
    section_id: str = "openzyme.compute@1"
    section_contract_digest: str = COMPUTE_PROJECTION_CONTRACT_DIGEST

    def project(self, request: ProjectionRequest) -> ProjectionResult:
        payload, next_cursor = self.application.project(
            session_id=request.context.session_id,
            actor_id=request.context.actor_id,
            max_items=request.max_items,
            cursor=request.cursor,
        )
        bounded = dict(payload)
        observed_size = len(str(bounded).encode("utf-8"))
        if observed_size > request.max_bytes:
            raise ValueError("Compute projection exceeds the requested byte budget")
        return ProjectionResult(
            section_id=self.section_id,
            section_contract_digest=self.section_contract_digest,
            payload=bounded,
            next_cursor=next_cursor,
            projection_digest=canonical_sha256_digest(
                {
                    "section_id": self.section_id,
                    "section_contract_digest": self.section_contract_digest,
                    "payload": bounded,
                    "next_cursor": next_cursor,
                }
            ),
        )


class ComputeWorkerApplication(Protocol):
    def claim(self, request: WorkerClaimRequest) -> tuple[WorkerClaim, ...]: ...

    def run(self, claim: WorkerClaim) -> ToolResult: ...


@dataclass(slots=True)
class ComputeWorkerContributor:
    application: ComputeWorkerApplication
    worker_id: str = "openzyme.compute.worker@1"

    def claim(self, request: WorkerClaimRequest) -> tuple[WorkerClaim, ...]:
        if request.owner_plugin_id != COMPUTE_PLUGIN_ID:
            return ()
        return self.application.claim(request)

    def run(self, claim: WorkerClaim) -> ToolResult:
        return self.application.run(claim)


@dataclass(frozen=True, slots=True)
class ComputePluginRuntimeSurfaces:
    tools: tuple[ComputeToolRuntime, ...]
    projections: tuple[ComputeProjectionContributor, ...]
    workers: tuple[ComputeWorkerContributor, ...]
    transaction_participants: tuple[ComputeTransactionParticipant, ...]


def build_compute_plugin_runtime_surfaces(
    *,
    tool_application: ComputeToolApplication,
    projection_application: ComputeProjectionApplication,
    worker_application: ComputeWorkerApplication,
) -> ComputePluginRuntimeSurfaces:
    return ComputePluginRuntimeSurfaces(
        tools=tuple(
            ComputeToolRuntime(contract=contract, application=tool_application)
            for contract in COMPUTE_TOOL_SPECS
        ),
        projections=(ComputeProjectionContributor(projection_application),),
        workers=(ComputeWorkerContributor(worker_application),),
        transaction_participants=(ComputeTransactionParticipant(),),
    )


__all__ = [
    "COMPUTE_PLUGIN_ID",
    "COMPUTE_PROJECTION_CONTRACT_DIGEST",
    "COMPUTE_RENDERER_CONTRACT_DIGEST",
    "COMPUTE_TOOL_SPECS",
    "ComputePluginRuntimeSurfaces",
    "ComputeProjectionApplication",
    "ComputeProjectionContributor",
    "ComputeToolApplication",
    "ComputeToolContext",
    "ComputeToolRuntime",
    "ComputeWorkerApplication",
    "ComputeWorkerContributor",
    "build_compute_plugin_runtime_surfaces",
]
