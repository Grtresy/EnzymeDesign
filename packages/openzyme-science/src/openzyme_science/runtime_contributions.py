from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from openzyme_contracts import EvidenceKind
from openzyme_contracts import EvidenceRef
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import HttpRouteInvocation
from openzyme_extension_spi import ProjectionRequest
from openzyme_extension_spi import ProjectionResult
from openzyme_extension_spi import TaskEvidenceValidation
from openzyme_extension_spi import WorkerClaim
from openzyme_extension_spi import WorkerClaimRequest
from openzyme_extension_spi.application import KernelEntitySnapshot
from openzyme_extension_spi.application import KernelQueryContext

from .transaction import SCIENCE_PLUGIN_ID
from .transaction import ScienceTransactionParticipant


SCIENCE_PROJECTION_SECTION_ID = "openzyme.science@1"
SCIENCE_FINISH_VALIDATOR_ID = "openzyme.science.finish-validator@1"
SCIENCE_WORKER_ID = "openzyme.science.worker@1"
SCIENCE_HTTP_ROUTE_ID = "openzyme.science.http.session-view@1"
SCIENCE_CLOSURE_EVIDENCE_CONTRACT_ID = "openzyme.science.closure@1"
SCIENCE_PROJECTION_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "section_id": SCIENCE_PROJECTION_SECTION_ID,
        "collections": [
            "attempts",
            "selections",
            "dispositions",
            "adoptions",
            "deliverables",
            "closures",
        ],
        "pagination": "stable_entity_id_cursor",
        "forbidden": ["arti" + "fact_id", "host_path", "raw_log", "remote_path"],
    }
)
SCIENCE_RENDERER_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "renderer_id": "openzyme.science.renderer@1",
        "section_id": SCIENCE_PROJECTION_SECTION_ID,
        "section_contract_digest": SCIENCE_PROJECTION_CONTRACT_DIGEST,
        "read_only": True,
    }
)
SCIENCE_FINISH_VALIDATOR_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "validator_id": SCIENCE_FINISH_VALIDATOR_ID,
        "evidence_contract_id": SCIENCE_CLOSURE_EVIDENCE_CONTRACT_ID,
        "read_only": True,
        "external_io": False,
        "core_mutation": False,
    }
)
SCIENCE_HTTP_ROUTE_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "route_id": SCIENCE_HTTP_ROUTE_ID,
        "method": "GET",
        "path": "/v3/extensions/openzyme.science/sessions/{session_id}",
        "read_only": True,
        "projection_section_id": SCIENCE_PROJECTION_SECTION_ID,
        "projection_contract_digest": SCIENCE_PROJECTION_CONTRACT_DIGEST,
    }
)

_PRIVATE_PROJECTION_FIELDS = frozenset(
    {
        "arti" + "fact_id",
        "credential",
        "host_path",
        "raw_log",
        "remote_path",
        "storage_uri",
    }
)


def _reject_private_projection_fields(value: object) -> None:
    if isinstance(value, Mapping):
        forbidden = _PRIVATE_PROJECTION_FIELDS.intersection(str(key) for key in value)
        if forbidden:
            raise ValueError(
                "Science projection contains private or retired file-era fields"
            )
        for nested in value.values():
            _reject_private_projection_fields(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_private_projection_fields(nested)


def _object_schema(required: tuple[str, ...], properties: dict[str, JsonValue]):
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(required),
        "properties": properties,
    }


_ID = {"type": "string", "minLength": 1}
_SAFE_OUTPUT = _object_schema(
    ("state", "fallback_performed", "task_finished"),
    {
        "state": _ID,
        "fallback_performed": {"const": False},
        "task_finished": {"const": False},
        "entity_kind": _ID,
        "entity_id": _ID,
        "state_version": {"type": "integer", "minimum": 1},
        "record_digest": {
            "type": "string",
            "pattern": "^sha256:[0-9a-f]{64}$",
        },
    },
)

SCIENCE_TOOL_SPECS = (
    ToolSpec(
        tool_name="scientific.attempt.inspect",
        description="Read one bounded Science projection without changing scientific or Task state.",
        input_schema=_object_schema(
            (),
            {
                "attempt_id": _ID,
                "selection_id": _ID,
                "cursor": _ID,
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
        ),
        output_schema=_SAFE_OUTPUT,
    ),
    ToolSpec(
        tool_name="scientific.selection.begin",
        description="Begin an explicit immutable selection revision within one admitted attempt.",
        input_schema=_object_schema(
            ("attempt_id", "idempotency_key"),
            {
                "attempt_id": _ID,
                "idempotency_key": _ID,
                "parent_selection_id": {"type": ["string", "null"]},
                "expected_head_state_version": {
                    "type": ["integer", "null"],
                    "minimum": 1,
                },
            },
        ),
        output_schema=_SAFE_OUTPUT,
    ),
    ToolSpec(
        tool_name="scientific.operation.disposition",
        description="Record the Agent-selected disposition of one exact scientific occurrence.",
        input_schema=_object_schema(
            ("selection_id", "operation_id", "kind", "reason_code", "idempotency_key"),
            {
                "selection_id": _ID,
                "operation_id": _ID,
                "kind": {"enum": ["superseded", "failed", "abandoned"]},
                "reason_code": _ID,
                "idempotency_key": _ID,
                "workflow_role": {"type": ["string", "null"]},
                "replacement_operation_id": {"type": ["string", "null"]},
            },
        ),
        output_schema=_SAFE_OUTPUT,
    ),
    ToolSpec(
        tool_name="scientific.operation.adopt",
        description=(
            "Explicitly adopt one settled successful operation for one workflow role. "
            "You choose the operation, role, and reason; the harness never infers a "
            "latest or successful candidate."
        ),
        input_schema=_object_schema(
            (
                "selection_id",
                "operation_id",
                "workflow_role",
                "reason_code",
                "idempotency_key",
            ),
            {
                "selection_id": _ID,
                "operation_id": _ID,
                "workflow_role": _ID,
                "reason_code": _ID,
                "idempotency_key": _ID,
            },
        ),
        output_schema=_SAFE_OUTPUT,
    ),
    ToolSpec(
        tool_name="scientific.selection.seal",
        description="Seal one exact selection only after all occurrence dispositions are explicit.",
        input_schema=_object_schema(
            ("selection_id", "expected_universe_digest", "idempotency_key"),
            {
                "selection_id": _ID,
                "expected_universe_digest": {
                    "type": "string",
                    "pattern": "^sha256:[0-9a-f]{64}$",
                },
                "idempotency_key": _ID,
            },
        ),
        output_schema=_SAFE_OUTPUT,
    ),
    ToolSpec(
        tool_name="scientific.attempt.close",
        description="Request explicit formal closure; closure never completes the owning Task.",
        input_schema=_object_schema(
            ("attempt_id", "selection_id", "idempotency_key"),
            {"attempt_id": _ID, "selection_id": _ID, "idempotency_key": _ID},
        ),
        output_schema=_SAFE_OUTPUT,
    ),
)


class ScienceToolApplication(Protocol):
    def invoke(self, *, invocation: ToolInvocation) -> Mapping[str, JsonValue]: ...


@dataclass(slots=True)
class ScienceToolRuntime:
    contract: ToolSpec
    application: ScienceToolApplication
    owner_plugin_id: str = SCIENCE_PLUGIN_ID

    @property
    def runtime_id(self) -> str:
        return f"openzyme.science.{self.contract.tool_name.replace('.', '-')}@1"

    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        if invocation.tool_name != self.contract.tool_name:
            return self._rejected(invocation, "science_tool_identity_mismatch")
        try:
            payload = dict(self.application.invoke(invocation=invocation))
        except (KeyError, TypeError, ValueError) as exc:
            return self._rejected(
                invocation,
                getattr(exc, "error_code", "science_request_invalid"),
                str(exc),
            )
        payload.update({"fallback_performed": False, "task_finished": False})
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            status="accepted",
            summary="Science accepted one explicit lifecycle command.",
            payload=payload,
        )

    @staticmethod
    def _rejected(
        invocation: ToolInvocation,
        code: str,
        summary: str = "Science rejected the tool invocation.",
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
                "task_finished": False,
            },
            error_code=code,
        )


class ScienceProjectionApplication(Protocol):
    def project(
        self,
        *,
        session_id: str,
        actor_id: str,
        max_items: int,
        cursor: str | None,
    ) -> tuple[Mapping[str, JsonValue], str | None]: ...


@dataclass(slots=True)
class ScienceProjectionContributor:
    application: ScienceProjectionApplication
    section_id: str = SCIENCE_PROJECTION_SECTION_ID
    section_contract_digest: str = SCIENCE_PROJECTION_CONTRACT_DIGEST

    def project(self, request: ProjectionRequest) -> ProjectionResult:
        payload, next_cursor = self.application.project(
            session_id=request.context.session_id,
            actor_id=request.context.actor_id,
            max_items=request.max_items,
            cursor=request.cursor,
        )
        bounded = dict(payload)
        _reject_private_projection_fields(bounded)
        if len(str(bounded).encode()) > request.max_bytes:
            raise ValueError("Science projection exceeds its byte budget")
        digest_payload = {
            "section_id": self.section_id,
            "section_contract_digest": self.section_contract_digest,
            "payload": bounded,
            "next_cursor": next_cursor,
        }
        return ProjectionResult(
            section_id=self.section_id,
            section_contract_digest=self.section_contract_digest,
            payload=bounded,
            next_cursor=next_cursor,
            projection_digest=canonical_sha256_digest(digest_payload),
        )


class ScienceHttpApplication(Protocol):
    def inspect_session(
        self,
        *,
        session_id: str,
        actor_id: str,
    ) -> Mapping[str, JsonValue]: ...


@dataclass(slots=True)
class ScienceHttpRouteRuntime:
    application: ScienceHttpApplication
    route_id: str = SCIENCE_HTTP_ROUTE_ID
    owner_plugin_id: str = SCIENCE_PLUGIN_ID
    method: str = "GET"
    path: str = "/v3/extensions/openzyme.science/sessions/{session_id}"
    contract_digest: str = SCIENCE_HTTP_ROUTE_CONTRACT_DIGEST

    def invoke(self, invocation: HttpRouteInvocation) -> ToolResult:
        if (
            invocation.route_id != self.route_id
            or invocation.method != self.method
            or invocation.path
            != self.path.format(session_id=invocation.context.session_id)
        ):
            raise ValueError("Science HTTP route method mismatch")
        payload = dict(
            self.application.inspect_session(
                session_id=invocation.context.session_id,
                actor_id=invocation.context.actor_id,
            )
        )
        _reject_private_projection_fields(payload)
        return ToolResult(
            call_id=invocation.context.correlation_id,
            tool_name=self.route_id,
            ok=True,
            status="observed",
            summary="Science returned one authorized bounded extension view.",
            payload=payload,
        )


class ScienceWorkerApplication(Protocol):
    def claim(self, request: WorkerClaimRequest) -> tuple[WorkerClaim, ...]: ...

    def run(self, claim: WorkerClaim) -> ToolResult: ...


@dataclass(slots=True)
class ScienceWorker:
    application: ScienceWorkerApplication
    worker_id: str = SCIENCE_WORKER_ID

    def claim(self, request: WorkerClaimRequest) -> tuple[WorkerClaim, ...]:
        return (
            ()
            if request.owner_plugin_id != SCIENCE_PLUGIN_ID
            else self.application.claim(request)
        )

    def run(self, claim: WorkerClaim) -> ToolResult:
        return self.application.run(claim)


class ScienceEvidenceReader(Protocol):
    def validate_closure(
        self,
        *,
        session_id: str,
        task_id: str,
        closure_ref: str,
        closure_digest: str,
    ) -> tuple[bool, tuple[str, ...]]: ...


@dataclass(slots=True)
class ScienceFinishValidator:
    reader: ScienceEvidenceReader
    validator_id: str = SCIENCE_FINISH_VALIDATOR_ID

    def validate(
        self,
        context: KernelQueryContext,
        task: KernelEntitySnapshot,
        evidence_refs: tuple[EvidenceRef, ...],
    ) -> TaskEvidenceValidation:
        matches = [
            ref
            for ref in evidence_refs
            if ref.evidence_kind is EvidenceKind.EXTENSION
            and ref.owner_component_id == SCIENCE_PLUGIN_ID
            and ref.contract_id == SCIENCE_CLOSURE_EVIDENCE_CONTRACT_ID
            and ref.session_id == context.session_id
            and ref.task_id == task.entity.entity_id
        ]
        if len(matches) != 1:
            accepted, codes = False, ("scientific_closure_missing_or_ambiguous",)
        else:
            ref = matches[0]
            accepted, codes = self.reader.validate_closure(
                session_id=context.session_id,
                task_id=task.entity.entity_id,
                closure_ref=ref.subject_ref,
                closure_digest=ref.subject_digest,
            )
        codes = tuple(sorted(set(codes)))
        return TaskEvidenceValidation(
            accepted=accepted and not codes,
            validator_ids=(self.validator_id,),
            rejection_codes=codes,
            validation_digest=canonical_sha256_digest(
                {
                    "validator_id": self.validator_id,
                    "session_id": context.session_id,
                    "task_id": task.entity.entity_id,
                    "evidence_digests": sorted(
                        ref.evidence_digest for ref in evidence_refs
                    ),
                    "accepted": accepted and not codes,
                    "rejection_codes": list(codes),
                    "core_mutation_applied": False,
                    "external_io_performed": False,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class SciencePluginRuntimeSurfaces:
    tools: tuple[ScienceToolRuntime, ...]
    http_routes: tuple[ScienceHttpRouteRuntime, ...]
    projections: tuple[ScienceProjectionContributor, ...]
    workers: tuple[ScienceWorker, ...]
    finish_validators: tuple[ScienceFinishValidator, ...]
    transaction_participants: tuple[ScienceTransactionParticipant, ...]


def build_science_plugin_runtime_surfaces(
    *,
    tool_application: ScienceToolApplication,
    http_application: ScienceHttpApplication,
    projection_application: ScienceProjectionApplication,
    worker_application: ScienceWorkerApplication,
    evidence_reader: ScienceEvidenceReader,
) -> SciencePluginRuntimeSurfaces:
    return SciencePluginRuntimeSurfaces(
        tools=tuple(
            ScienceToolRuntime(spec, tool_application) for spec in SCIENCE_TOOL_SPECS
        ),
        http_routes=(ScienceHttpRouteRuntime(http_application),),
        projections=(ScienceProjectionContributor(projection_application),),
        workers=(ScienceWorker(worker_application),),
        finish_validators=(ScienceFinishValidator(evidence_reader),),
        transaction_participants=(ScienceTransactionParticipant(),),
    )


__all__ = [
    "SCIENCE_CLOSURE_EVIDENCE_CONTRACT_ID",
    "SCIENCE_FINISH_VALIDATOR_CONTRACT_DIGEST",
    "SCIENCE_FINISH_VALIDATOR_ID",
    "SCIENCE_HTTP_ROUTE_CONTRACT_DIGEST",
    "SCIENCE_HTTP_ROUTE_ID",
    "SCIENCE_PLUGIN_ID",
    "SCIENCE_PROJECTION_CONTRACT_DIGEST",
    "SCIENCE_PROJECTION_SECTION_ID",
    "SCIENCE_RENDERER_CONTRACT_DIGEST",
    "SCIENCE_TOOL_SPECS",
    "SCIENCE_WORKER_ID",
    "ScienceEvidenceReader",
    "ScienceFinishValidator",
    "ScienceHttpApplication",
    "ScienceHttpRouteRuntime",
    "SciencePluginRuntimeSurfaces",
    "ScienceProjectionApplication",
    "ScienceProjectionContributor",
    "ScienceToolApplication",
    "ScienceToolRuntime",
    "ScienceWorker",
    "ScienceWorkerApplication",
    "build_science_plugin_runtime_surfaces",
]
