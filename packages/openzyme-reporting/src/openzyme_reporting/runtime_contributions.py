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

from .lifecycle import ReportValidationStatus
from .lifecycle import ReportVersion
from .transaction import REPORTING_PLUGIN_ID
from .transaction import ReportingTransactionParticipant


REPORTING_PROJECTION_SECTION_ID = "openzyme.reporting@1"
REPORTING_FINISH_VALIDATOR_ID = "openzyme.reporting.finish-validator@1"
REPORTING_HTTP_ROUTE_ID = "openzyme.reporting.http.session-view@1"
REPORTING_RENDER_WORKER_ID = "openzyme.reporting.render-worker@1"
REPORTING_REPORT_EVIDENCE_CONTRACT_ID = "openzyme.reporting.report@1"

REPORTING_PROJECTION_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "schema_version": REPORTING_PROJECTION_SECTION_ID,
        "bounded_collections": ["drafts", "reports", "renders", "validations"],
        "content": "revision_path_ref_only",
        "pagination": "stable_entity_id_cursor",
        "forbidden": [
            "body",
            "bytes",
            "credential",
            "host_path",
            "private_path",
            "renderer_log",
            "storage_uri",
        ],
    }
)
REPORTING_RENDERER_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "schema_version": "openzyme_ui_renderer_contract@1",
        "renderer_id": "openzyme.reporting.renderer@1",
        "section_id": REPORTING_PROJECTION_SECTION_ID,
        "requires_exact_section_contract": REPORTING_PROJECTION_CONTRACT_DIGEST,
        "read_only": True,
        "mutates_core_state": False,
    }
)
REPORTING_FINISH_VALIDATOR_CONTRACT_DIGEST = canonical_sha256_digest(
    {
        "schema_version": "openzyme_task_evidence_validator@1",
        "validator_id": REPORTING_FINISH_VALIDATOR_ID,
        "evidence_contract_id": REPORTING_REPORT_EVIDENCE_CONTRACT_ID,
        "read_only": True,
        "external_io": False,
        "core_mutation": False,
    }
)
# This identity is frozen in the exact component manifest. Route mounting checks
# all constituent fields as well as this digest, so a stale runtime cannot be
# accepted merely by retaining the digest.
REPORTING_HTTP_ROUTE_CONTRACT_DIGEST = (
    "sha256:a69bdc0d3911c81533d1c713b556a4b2c2d63e102a3e52881ce3a03eb50c0bbf"
)

_CONTENT_REF_SCHEMA: dict[str, JsonValue] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "ref_id",
        "publication_id",
        "project_id",
        "session_id",
        "repository_binding_id",
        "repository_binding_version",
        "repository_id",
        "commit",
        "tree",
        "path",
        "entry_kind",
        "object_id",
        "size_bytes",
        "lfs_oid",
        "lfs_size_bytes",
        "path_manifest_digest",
        "created_at",
        "ref_digest",
    ],
    "properties": {
        "schema_version": {"const": "revision_path_ref@1"},
        "ref_id": {"type": "string", "minLength": 1},
        "publication_id": {"type": "string", "minLength": 1},
        "project_id": {"type": "string", "minLength": 1},
        "session_id": {"type": "string", "minLength": 1},
        "repository_binding_id": {"type": "string", "minLength": 1},
        "repository_binding_version": {"type": "integer", "minimum": 1},
        "repository_id": {"type": "string", "minLength": 1},
        "commit": {"type": "string"},
        "tree": {"type": "string"},
        "path": {"type": "string", "minLength": 1},
        "entry_kind": {"enum": ["file", "lfs_file"]},
        "object_id": {"type": "string"},
        "size_bytes": {"type": ["integer", "null"], "minimum": 0},
        "lfs_oid": {"type": ["string", "null"]},
        "lfs_size_bytes": {"type": ["integer", "null"], "minimum": 0},
        "path_manifest_digest": {"type": ["string", "null"]},
        "created_at": {"type": "string", "minLength": 1},
        "ref_digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    },
}

_MUTATION_OUTPUT: dict[str, JsonValue] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "state",
        "workspace_publication_performed",
        "render_performed",
        "fallback_performed",
        "task_finished",
    ],
    "properties": {
        "state": {"type": "string", "minLength": 1},
        "entity_kind": {"type": "string", "minLength": 1},
        "entity_id": {"type": "string", "minLength": 1},
        "state_version": {"type": "integer", "minimum": 1},
        "record_digest": {
            "type": "string",
            "pattern": "^sha256:[0-9a-f]{64}$",
        },
        "task_id": {"type": "string", "minLength": 1},
        "title": {"type": "string", "minLength": 1, "maxLength": 1024},
        "summary": {"type": "string", "maxLength": 16384},
        "content_ref": _CONTENT_REF_SCHEMA,
        "report_id": {"type": "string", "minLength": 1},
        "report_version": {"type": "integer", "minimum": 1},
        "report_digest": {
            "type": "string",
            "pattern": "^sha256:[0-9a-f]{64}$",
        },
        "render_id": {"type": "string", "minLength": 1},
        "receipt_digest": {
            "type": "string",
            "pattern": "^sha256:[0-9a-f]{64}$",
        },
        "workspace_publication_performed": {"const": False},
        "render_performed": {"type": "boolean"},
        "fallback_performed": {"const": False},
        "task_finished": {"const": False},
    },
}

REPORTING_TOOL_SPECS = (
    ToolSpec(
        tool_name="report_draft.get",
        description=(
            "Read bounded Reporting draft metadata. Report bodies remain immutable "
            "workspace files and are never returned by this tool."
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "minProperties": 1,
            "maxProperties": 1,
            "properties": {
                "draft_id": {"type": "string", "minLength": 1},
                "task_id": {"type": "string", "minLength": 1},
            },
        },
        output_schema=_MUTATION_OUTPUT,
    ),
    ToolSpec(
        tool_name="report_draft.update",
        description=(
            "Create or update bounded draft metadata linked to an already published "
            "RevisionPathRef. It never writes, commits or publishes report bytes."
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["task_id", "title", "summary", "idempotency_key"],
            "properties": {
                "draft_id": {"type": "string", "minLength": 1},
                "task_id": {"type": "string", "minLength": 1},
                "title": {"type": "string", "minLength": 1, "maxLength": 1024},
                "summary": {"type": "string", "maxLength": 16384},
                "content_ref": _CONTENT_REF_SCHEMA,
                "expected_state_version": {
                    "type": ["integer", "null"],
                    "minimum": 1,
                },
                "idempotency_key": {"type": "string", "minLength": 1},
            },
        },
        output_schema=_MUTATION_OUTPUT,
        required_authorities=("workspace.fs.read",),
    ),
    ToolSpec(
        tool_name="report.publish",
        description=(
            "Register one immutable report version against an exact published "
            "RevisionPathRef. It does not publish workspace bytes or finish a Task."
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "report_id",
                "task_id",
                "report_contract_id",
                "report_version",
                "report_format",
                "title",
                "summary",
                "content_ref",
                "idempotency_key",
            ],
            "properties": {
                "report_id": {"type": "string", "minLength": 1},
                "task_id": {"type": "string", "minLength": 1},
                "report_contract_id": {"type": "string", "minLength": 1},
                "report_version": {"type": "integer", "minimum": 1},
                "report_format": {"enum": ["markdown", "html", "pdf"]},
                "title": {"type": "string", "minLength": 1, "maxLength": 1024},
                "summary": {"type": "string", "maxLength": 16384},
                "content_ref": _CONTENT_REF_SCHEMA,
                "supersedes_report_id": {"type": ["string", "null"]},
                "idempotency_key": {"type": "string", "minLength": 1},
            },
        },
        output_schema=_MUTATION_OUTPUT,
        required_authorities=("workspace.fs.read",),
    ),
    ToolSpec(
        tool_name="report.render.request",
        description=(
            "Queue an explicit render with one exact renderer and source report. "
            "Missing or drifted renderers fail without format fallback."
        ),
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "report_id",
                "report_digest",
                "renderer_id",
                "renderer_contract_digest",
                "output_format",
                "idempotency_key",
            ],
            "properties": {
                "report_id": {"type": "string", "minLength": 1},
                "report_digest": {
                    "type": "string",
                    "pattern": "^sha256:[0-9a-f]{64}$",
                },
                "renderer_id": {"type": "string", "minLength": 1},
                "renderer_contract_digest": {
                    "type": "string",
                    "pattern": "^sha256:[0-9a-f]{64}$",
                },
                "output_format": {"enum": ["html", "pdf"]},
                "idempotency_key": {"type": "string", "minLength": 1},
            },
        },
        output_schema=_MUTATION_OUTPUT,
        required_authorities=("workspace.process.exec",),
    ),
)

_FORBIDDEN_TOOL_FIELDS = frozenset(
    {"body", "bytes", "content", "host_path", "markdown", "private_path", "url"}
)


class ReportingToolApplication(Protocol):
    def invoke(
        self,
        *,
        invocation: ToolInvocation,
    ) -> Mapping[str, JsonValue]: ...


class ReportingRendererCatalog(Protocol):
    """Read-only exact renderer identities from the activated Plugin bundle."""

    def contract_digest(self, renderer_id: str) -> str | None: ...


@dataclass(slots=True)
class ReportingToolRuntime:
    contract: ToolSpec
    application: ReportingToolApplication
    renderer_catalog: ReportingRendererCatalog | None = None
    owner_plugin_id: str = REPORTING_PLUGIN_ID

    @property
    def runtime_id(self) -> str:
        return f"openzyme.reporting.{self.contract.tool_name.replace('.', '-')}@1"

    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        if invocation.tool_name != self.contract.tool_name:
            return self._rejected(
                invocation,
                "reporting_tool_identity_mismatch",
                "Reporting runtime received another tool identity.",
            )
        forbidden = sorted(_FORBIDDEN_TOOL_FIELDS.intersection(invocation.arguments))
        if forbidden:
            return self._rejected(
                invocation,
                "report_body_inline_forbidden",
                "Report bytes and private locators are forbidden tool arguments.",
            )
        if self.contract.tool_name == "report.render.request":
            renderer_id = invocation.arguments.get("renderer_id")
            requested_digest = invocation.arguments.get("renderer_contract_digest")
            if (
                not isinstance(renderer_id, str)
                or self.renderer_catalog is None
                or self.renderer_catalog.contract_digest(renderer_id)
                != requested_digest
            ):
                return self._rejected(
                    invocation,
                    "report_renderer_missing_or_drifted",
                    "The exact renderer identity is absent or digest-mismatched.",
                )
        try:
            payload = dict(self.application.invoke(invocation=invocation))
        except (KeyError, TypeError, ValueError) as exc:
            return self._rejected(
                invocation,
                getattr(exc, "error_code", "reporting_request_invalid"),
                str(exc),
            )
        payload.update(
            {
                "workspace_publication_performed": False,
                "fallback_performed": False,
                "task_finished": False,
            }
        )
        payload.setdefault("render_performed", False)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            status="accepted",
            summary="Reporting accepted the explicit file-bound operation.",
            payload=payload,
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
                "workspace_publication_performed": False,
                "render_performed": False,
                "fallback_performed": False,
                "task_finished": False,
            },
            error_code=error_code,
        )


class ReportingProjectionApplication(Protocol):
    def project(
        self,
        *,
        session_id: str,
        actor_id: str,
        max_items: int,
        cursor: str | None,
    ) -> tuple[Mapping[str, JsonValue], str | None]: ...


def _reject_private_projection_fields(value: object) -> None:
    if isinstance(value, Mapping):
        forbidden = {
            "body",
            "bytes",
            "credential",
            "host_path",
            "private_path",
            "renderer_log",
            "storage_uri",
        }.intersection(str(key) for key in value)
        if forbidden:
            raise ValueError("Reporting projection contains private fields")
        for item in value.values():
            _reject_private_projection_fields(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_private_projection_fields(item)


@dataclass(slots=True)
class ReportingProjectionContributor:
    application: ReportingProjectionApplication
    section_id: str = REPORTING_PROJECTION_SECTION_ID
    section_contract_digest: str = REPORTING_PROJECTION_CONTRACT_DIGEST

    def project(self, request: ProjectionRequest) -> ProjectionResult:
        payload, next_cursor = self.application.project(
            session_id=request.context.session_id,
            actor_id=request.context.actor_id,
            max_items=request.max_items,
            cursor=request.cursor,
        )
        bounded = dict(payload)
        _reject_private_projection_fields(bounded)
        if len(str(bounded).encode("utf-8")) > request.max_bytes:
            raise ValueError("Reporting projection exceeds its byte budget")
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


class ReportingHttpApplication(Protocol):
    def inspect(
        self,
        invocation: HttpRouteInvocation,
    ) -> Mapping[str, JsonValue]: ...


@dataclass(slots=True)
class ReportingHttpRouteRuntime:
    application: ReportingHttpApplication
    route_id: str = REPORTING_HTTP_ROUTE_ID
    owner_plugin_id: str = REPORTING_PLUGIN_ID
    method: str = "GET"
    path: str = "/v3/extensions/openzyme.reporting/sessions/{session_id}"
    contract_digest: str = REPORTING_HTTP_ROUTE_CONTRACT_DIGEST

    def invoke(self, invocation: HttpRouteInvocation) -> ToolResult:
        payload = dict(self.application.inspect(invocation))
        _reject_private_projection_fields(payload)
        return ToolResult(
            call_id=invocation.context.correlation_id,
            tool_name=self.route_id,
            ok=True,
            status="observed",
            summary="Reporting returned one authorized bounded extension view.",
            payload=payload,
        )


class ReportingWorkerApplication(Protocol):
    def claim(self, request: WorkerClaimRequest) -> tuple[WorkerClaim, ...]: ...

    def run(self, claim: WorkerClaim) -> ToolResult: ...


@dataclass(slots=True)
class ReportingRenderWorker:
    application: ReportingWorkerApplication
    worker_id: str = REPORTING_RENDER_WORKER_ID

    def claim(self, request: WorkerClaimRequest) -> tuple[WorkerClaim, ...]:
        if request.owner_plugin_id != REPORTING_PLUGIN_ID:
            return ()
        return self.application.claim(request)

    def run(self, claim: WorkerClaim) -> ToolResult:
        return self.application.run(claim)


class ReportingEvidenceReader(Protocol):
    """Read-only Reporting namespace view used while Kernel validates finish."""

    def get_report(self, report_id: str) -> ReportVersion | None: ...

    def validation_status(
        self,
        *,
        report_id: str,
        report_version: int,
        report_digest: str,
    ) -> ReportValidationStatus | None: ...


@dataclass(slots=True)
class ReportingFinishValidator:
    reader: ReportingEvidenceReader
    validator_id: str = REPORTING_FINISH_VALIDATOR_ID

    def validate(
        self,
        context: KernelQueryContext,
        task: KernelEntitySnapshot,
        evidence_refs: tuple[EvidenceRef, ...],
    ) -> TaskEvidenceValidation:
        rejection_codes: set[str] = set()
        matching = [
            ref
            for ref in evidence_refs
            if ref.evidence_kind is EvidenceKind.EXTENSION
            and ref.owner_component_id == REPORTING_PLUGIN_ID
            and ref.contract_id == REPORTING_REPORT_EVIDENCE_CONTRACT_ID
            and ref.session_id == context.session_id
            and ref.task_id == task.entity.entity_id
        ]
        if len(matching) != 1:
            rejection_codes.add("report_evidence_missing_or_ambiguous")
        else:
            evidence = matching[0]
            report = self.reader.get_report(evidence.subject_ref)
            if report is None:
                rejection_codes.add("report_version_missing")
            else:
                expected_contract = task.payload.get("required_report_contract_id")
                expected_version = task.payload.get("required_report_version")
                if (
                    report.session_id != context.session_id
                    or report.task_id != task.entity.entity_id
                    or evidence.subject_digest != report.report_digest
                ):
                    rejection_codes.add("report_identity_mismatch")
                if (
                    expected_contract is not None
                    and expected_contract != report.report_contract_id
                ):
                    rejection_codes.add("report_contract_mismatch")
                if expected_version is not None and expected_version != report.report_version:
                    rejection_codes.add("report_version_mismatch")
                if (
                    self.reader.validation_status(
                        report_id=report.report_id,
                        report_version=report.report_version,
                        report_digest=report.report_digest,
                    )
                    is not ReportValidationStatus.ACCEPTED
                ):
                    rejection_codes.add("report_validation_missing")

        codes = tuple(sorted(rejection_codes))
        digest_payload = {
            "validator_id": self.validator_id,
            "session_id": context.session_id,
            "task_id": task.entity.entity_id,
            "evidence_digests": sorted(ref.evidence_digest for ref in evidence_refs),
            "accepted": not codes,
            "rejection_codes": list(codes),
            "core_mutation_applied": False,
            "render_performed": False,
            "publication_performed": False,
        }
        return TaskEvidenceValidation(
            accepted=not codes,
            validator_ids=(self.validator_id,),
            rejection_codes=codes,
            validation_digest=canonical_sha256_digest(digest_payload),
        )


@dataclass(frozen=True, slots=True)
class ReportingPluginRuntimeSurfaces:
    tools: tuple[ReportingToolRuntime, ...]
    http_routes: tuple[ReportingHttpRouteRuntime, ...]
    projections: tuple[ReportingProjectionContributor, ...]
    workers: tuple[ReportingRenderWorker, ...]
    finish_validators: tuple[ReportingFinishValidator, ...]
    transaction_participants: tuple[ReportingTransactionParticipant, ...]


def build_reporting_plugin_runtime_surfaces(
    *,
    tool_application: ReportingToolApplication,
    renderer_catalog: ReportingRendererCatalog,
    http_application: ReportingHttpApplication,
    projection_application: ReportingProjectionApplication,
    worker_application: ReportingWorkerApplication,
    evidence_reader: ReportingEvidenceReader,
) -> ReportingPluginRuntimeSurfaces:
    return ReportingPluginRuntimeSurfaces(
        tools=tuple(
            ReportingToolRuntime(
                contract=spec,
                application=tool_application,
                renderer_catalog=renderer_catalog,
            )
            for spec in REPORTING_TOOL_SPECS
        ),
        http_routes=(ReportingHttpRouteRuntime(http_application),),
        projections=(ReportingProjectionContributor(projection_application),),
        workers=(ReportingRenderWorker(worker_application),),
        finish_validators=(ReportingFinishValidator(evidence_reader),),
        transaction_participants=(ReportingTransactionParticipant(),),
    )


__all__ = [
    "REPORTING_FINISH_VALIDATOR_CONTRACT_DIGEST",
    "REPORTING_FINISH_VALIDATOR_ID",
    "REPORTING_HTTP_ROUTE_ID",
    "REPORTING_PLUGIN_ID",
    "REPORTING_PROJECTION_CONTRACT_DIGEST",
    "REPORTING_PROJECTION_SECTION_ID",
    "REPORTING_RENDERER_CONTRACT_DIGEST",
    "REPORTING_RENDER_WORKER_ID",
    "REPORTING_REPORT_EVIDENCE_CONTRACT_ID",
    "REPORTING_TOOL_SPECS",
    "ReportingEvidenceReader",
    "ReportingFinishValidator",
    "ReportingHttpApplication",
    "ReportingHttpRouteRuntime",
    "ReportingPluginRuntimeSurfaces",
    "ReportingProjectionApplication",
    "ReportingProjectionContributor",
    "ReportingRendererCatalog",
    "ReportingRenderWorker",
    "ReportingToolApplication",
    "ReportingToolRuntime",
    "ReportingWorkerApplication",
    "build_reporting_plugin_runtime_surfaces",
]
