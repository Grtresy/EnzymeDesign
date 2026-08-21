from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from enum import StrEnum
from typing import Any

from openzyme_contracts import RevisionPathEntryKind
from openzyme_contracts import RevisionPathRef
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier


REPORT_VERSION_SCHEMA_VERSION = "openzyme_reporting_report_version@1"
REPORT_RENDER_RECEIPT_SCHEMA_VERSION = "openzyme_reporting_render_receipt@1"
REPORT_VALIDATION_RECEIPT_SCHEMA_VERSION = "openzyme_reporting_validation_receipt@1"


class ReportFormat(StrEnum):
    MARKDOWN = "markdown"
    HTML = "html"
    PDF = "pdf"


class ReportRenderStatus(StrEnum):
    REQUESTED = "requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ReportValidationStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


def _require_report_file(ref: RevisionPathRef, *, session_id: str) -> None:
    if ref.session_id != session_id:
        raise ValueError("report content reference crossed its Session")
    if ref.entry_kind not in {
        RevisionPathEntryKind.FILE,
        RevisionPathEntryKind.LFS_FILE,
    }:
        raise ValueError("report content must reference one immutable file")


@dataclass(frozen=True, slots=True)
class ReportVersion:
    report_id: str
    project_id: str
    session_id: str
    task_id: str
    owner_agent_member_id: str
    report_contract_id: str
    report_version: int
    report_format: ReportFormat
    title: str
    summary: str
    content_ref: RevisionPathRef
    supersedes_report_id: str | None
    created_at: str
    report_digest: str
    schema_version: str = REPORT_VERSION_SCHEMA_VERSION

    @classmethod
    def create(cls, **values: Any) -> ReportVersion:
        provisional = cls(**values, report_digest="sha256:" + "0" * 64)
        return replace(
            provisional,
            report_digest=canonical_sha256_digest(provisional.identity_payload),
        )

    def __post_init__(self) -> None:
        if self.schema_version != REPORT_VERSION_SCHEMA_VERSION:
            raise ValueError("unsupported Reporting report version schema")
        for field_name in (
            "report_id",
            "project_id",
            "session_id",
            "task_id",
            "owner_agent_member_id",
            "report_contract_id",
            "created_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.supersedes_report_id is not None:
            require_identifier(
                self.supersedes_report_id,
                field_name="supersedes_report_id",
            )
        if self.report_version < 1:
            raise ValueError("report_version must be positive")
        if self.report_version == 1 and self.supersedes_report_id is not None:
            raise ValueError("first report version cannot supersede another report")
        if self.report_version > 1 and self.supersedes_report_id is None:
            raise ValueError("corrected report version requires an exact predecessor")
        if not self.title or len(self.title.encode("utf-8")) > 1_024:
            raise ValueError("report title must be non-empty and bounded")
        if len(self.summary.encode("utf-8")) > 16_384:
            raise ValueError("report summary exceeds the metadata budget")
        _require_report_file(self.content_ref, session_id=self.session_id)
        require_digest(self.report_digest, field_name="report_digest")
        placeholder = "sha256:" + "0" * 64
        if (
            self.report_digest != placeholder
            and self.report_digest != canonical_sha256_digest(self.identity_payload)
        ):
            raise ValueError("report version digest mismatch")

    @property
    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "project_id": self.project_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "owner_agent_member_id": self.owner_agent_member_id,
            "report_contract_id": self.report_contract_id,
            "report_version": self.report_version,
            "report_format": self.report_format.value,
            "title": self.title,
            "summary": self.summary,
            "content_ref": self.content_ref.to_dict(),
            "supersedes_report_id": self.supersedes_report_id,
            "created_at": self.created_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_payload, "report_digest": self.report_digest}

    @classmethod
    def from_dict(cls, value: object) -> ReportVersion:
        expected = {
            "schema_version",
            "report_id",
            "project_id",
            "session_id",
            "task_id",
            "owner_agent_member_id",
            "report_contract_id",
            "report_version",
            "report_format",
            "title",
            "summary",
            "content_ref",
            "supersedes_report_id",
            "created_at",
            "report_digest",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("Reporting report version fields are closed")
        return cls(
            schema_version=str(value["schema_version"]),
            report_id=str(value["report_id"]),
            project_id=str(value["project_id"]),
            session_id=str(value["session_id"]),
            task_id=str(value["task_id"]),
            owner_agent_member_id=str(value["owner_agent_member_id"]),
            report_contract_id=str(value["report_contract_id"]),
            report_version=int(value["report_version"]),
            report_format=ReportFormat(str(value["report_format"])),
            title=str(value["title"]),
            summary=str(value["summary"]),
            content_ref=RevisionPathRef.from_dict(dict(value["content_ref"])),
            supersedes_report_id=(
                None
                if value["supersedes_report_id"] is None
                else str(value["supersedes_report_id"])
            ),
            created_at=str(value["created_at"]),
            report_digest=str(value["report_digest"]),
        )


@dataclass(frozen=True, slots=True)
class ReportRenderReceipt:
    render_id: str
    report_id: str
    session_id: str
    source_report_digest: str
    renderer_id: str
    renderer_contract_digest: str
    status: ReportRenderStatus
    output_ref: RevisionPathRef | None
    failure_code: str | None
    created_at: str
    receipt_digest: str
    schema_version: str = REPORT_RENDER_RECEIPT_SCHEMA_VERSION

    @classmethod
    def create(cls, **values: Any) -> ReportRenderReceipt:
        provisional = cls(**values, receipt_digest="sha256:" + "0" * 64)
        return replace(
            provisional,
            receipt_digest=canonical_sha256_digest(provisional.identity_payload),
        )

    def __post_init__(self) -> None:
        if self.schema_version != REPORT_RENDER_RECEIPT_SCHEMA_VERSION:
            raise ValueError("unsupported Reporting render receipt schema")
        for field_name in (
            "render_id",
            "report_id",
            "session_id",
            "renderer_id",
            "created_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in ("source_report_digest", "renderer_contract_digest"):
            require_digest(getattr(self, field_name), field_name=field_name)
        if self.status is ReportRenderStatus.SUCCEEDED:
            if self.output_ref is None or self.failure_code is not None:
                raise ValueError("successful render requires only an immutable output ref")
            _require_report_file(self.output_ref, session_id=self.session_id)
        elif self.output_ref is not None:
            raise ValueError("non-successful render cannot expose an output ref")
        if self.status is ReportRenderStatus.FAILED and self.failure_code is None:
            raise ValueError("failed render requires a stable failure code")
        if self.failure_code is not None:
            require_identifier(self.failure_code, field_name="failure_code")
        require_digest(self.receipt_digest, field_name="receipt_digest")
        placeholder = "sha256:" + "0" * 64
        if (
            self.receipt_digest != placeholder
            and self.receipt_digest != canonical_sha256_digest(self.identity_payload)
        ):
            raise ValueError("render receipt digest mismatch")

    @property
    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "render_id": self.render_id,
            "report_id": self.report_id,
            "session_id": self.session_id,
            "source_report_digest": self.source_report_digest,
            "renderer_id": self.renderer_id,
            "renderer_contract_digest": self.renderer_contract_digest,
            "status": self.status.value,
            "output_ref": None if self.output_ref is None else self.output_ref.to_dict(),
            "failure_code": self.failure_code,
            "created_at": self.created_at,
            "fallback_performed": False,
            "task_finished": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_payload, "receipt_digest": self.receipt_digest}

    @classmethod
    def from_dict(cls, value: object) -> ReportRenderReceipt:
        expected = {
            "schema_version",
            "render_id",
            "report_id",
            "session_id",
            "source_report_digest",
            "renderer_id",
            "renderer_contract_digest",
            "status",
            "output_ref",
            "failure_code",
            "created_at",
            "fallback_performed",
            "task_finished",
            "receipt_digest",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("Reporting render receipt fields are closed")
        if value["fallback_performed"] is not False or value["task_finished"] is not False:
            raise ValueError("Reporting render receipt cannot imply fallback or Task finish")
        return cls(
            schema_version=str(value["schema_version"]),
            render_id=str(value["render_id"]),
            report_id=str(value["report_id"]),
            session_id=str(value["session_id"]),
            source_report_digest=str(value["source_report_digest"]),
            renderer_id=str(value["renderer_id"]),
            renderer_contract_digest=str(value["renderer_contract_digest"]),
            status=ReportRenderStatus(str(value["status"])),
            output_ref=(
                None
                if value["output_ref"] is None
                else RevisionPathRef.from_dict(dict(value["output_ref"]))
            ),
            failure_code=(
                None if value["failure_code"] is None else str(value["failure_code"])
            ),
            created_at=str(value["created_at"]),
            receipt_digest=str(value["receipt_digest"]),
        )


@dataclass(frozen=True, slots=True)
class ReportValidationReceipt:
    validation_id: str
    report_id: str
    session_id: str
    task_id: str
    report_contract_id: str
    report_version: int
    report_digest: str
    validator_id: str
    validator_contract_digest: str
    status: ReportValidationStatus
    rejection_codes: tuple[str, ...]
    created_at: str
    receipt_digest: str
    schema_version: str = REPORT_VALIDATION_RECEIPT_SCHEMA_VERSION

    @classmethod
    def create(cls, **values: Any) -> ReportValidationReceipt:
        provisional = cls(**values, receipt_digest="sha256:" + "0" * 64)
        return replace(
            provisional,
            receipt_digest=canonical_sha256_digest(provisional.identity_payload),
        )

    def __post_init__(self) -> None:
        if self.schema_version != REPORT_VALIDATION_RECEIPT_SCHEMA_VERSION:
            raise ValueError("unsupported Reporting validation receipt schema")
        for field_name in (
            "validation_id",
            "report_id",
            "session_id",
            "task_id",
            "report_contract_id",
            "validator_id",
            "created_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.report_version < 1:
            raise ValueError("report_version must be positive")
        for field_name in (
            "report_digest",
            "validator_contract_digest",
            "receipt_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        normalized = tuple(sorted(set(self.rejection_codes)))
        if normalized != self.rejection_codes:
            raise ValueError("rejection_codes must be unique and sorted")
        for code in self.rejection_codes:
            require_identifier(code, field_name="rejection_codes")
        if self.status is ReportValidationStatus.ACCEPTED and self.rejection_codes:
            raise ValueError("accepted validation cannot carry rejection codes")
        if self.status is ReportValidationStatus.REJECTED and not self.rejection_codes:
            raise ValueError("rejected validation requires a stable code")
        placeholder = "sha256:" + "0" * 64
        if (
            self.receipt_digest != placeholder
            and self.receipt_digest != canonical_sha256_digest(self.identity_payload)
        ):
            raise ValueError("validation receipt digest mismatch")

    @property
    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "validation_id": self.validation_id,
            "report_id": self.report_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "report_contract_id": self.report_contract_id,
            "report_version": self.report_version,
            "report_digest": self.report_digest,
            "validator_id": self.validator_id,
            "validator_contract_digest": self.validator_contract_digest,
            "status": self.status.value,
            "rejection_codes": list(self.rejection_codes),
            "created_at": self.created_at,
            "core_mutation_applied": False,
            "render_performed": False,
            "publication_performed": False,
            "task_finished": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_payload, "receipt_digest": self.receipt_digest}

    @classmethod
    def from_dict(cls, value: object) -> ReportValidationReceipt:
        expected = {
            "schema_version",
            "validation_id",
            "report_id",
            "session_id",
            "task_id",
            "report_contract_id",
            "report_version",
            "report_digest",
            "validator_id",
            "validator_contract_digest",
            "status",
            "rejection_codes",
            "created_at",
            "core_mutation_applied",
            "render_performed",
            "publication_performed",
            "task_finished",
            "receipt_digest",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("Reporting validation receipt fields are closed")
        if any(
            value[field_name] is not False
            for field_name in (
                "core_mutation_applied",
                "render_performed",
                "publication_performed",
                "task_finished",
            )
        ):
            raise ValueError("Reporting validation receipt cannot imply side effects")
        rejection_codes = value["rejection_codes"]
        if not isinstance(rejection_codes, list):
            raise ValueError("Reporting validation rejection codes must be a list")
        return cls(
            schema_version=str(value["schema_version"]),
            validation_id=str(value["validation_id"]),
            report_id=str(value["report_id"]),
            session_id=str(value["session_id"]),
            task_id=str(value["task_id"]),
            report_contract_id=str(value["report_contract_id"]),
            report_version=int(value["report_version"]),
            report_digest=str(value["report_digest"]),
            validator_id=str(value["validator_id"]),
            validator_contract_digest=str(value["validator_contract_digest"]),
            status=ReportValidationStatus(str(value["status"])),
            rejection_codes=tuple(str(item) for item in rejection_codes),
            created_at=str(value["created_at"]),
            receipt_digest=str(value["receipt_digest"]),
        )


__all__ = [
    "REPORT_RENDER_RECEIPT_SCHEMA_VERSION",
    "REPORT_VALIDATION_RECEIPT_SCHEMA_VERSION",
    "REPORT_VERSION_SCHEMA_VERSION",
    "ReportFormat",
    "ReportRenderReceipt",
    "ReportRenderStatus",
    "ReportValidationReceipt",
    "ReportValidationStatus",
    "ReportVersion",
]
