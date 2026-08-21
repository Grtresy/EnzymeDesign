from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from openzyme_contracts import canonical_handoff_digest


REPORT_REF_SCHEMA_VERSION = "report_ref@1"


def _require_identifier(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(character.isspace() for character in value)
        or len(value.encode("utf-8")) > 256
    ):
        raise ValueError(
            f"{field_name} must be an exact non-empty identifier of at most 256 bytes"
        )


def _require_digest(value: str, field_name: str) -> None:
    if re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")


def _strict_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _strict_integer(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _optional_strict_string(value: Any, field_name: str) -> str | None:
    return None if value is None else _strict_string(value, field_name)


@dataclass(frozen=True, slots=True)
class ReportRef:
    report_id: str
    project_id: str
    session_id: str
    task_id: str | None
    content_ref_id: str
    report_version: int
    supersedes_report_id: str | None
    report_digest: str
    schema_version: str = REPORT_REF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REPORT_REF_SCHEMA_VERSION:
            raise ValueError("unsupported report reference schema")
        for field_name in (
            "report_id",
            "project_id",
            "session_id",
            "content_ref_id",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        if self.task_id is not None:
            _require_identifier(self.task_id, "task_id")
        if self.supersedes_report_id is not None:
            _require_identifier(self.supersedes_report_id, "supersedes_report_id")
        if (
            not isinstance(self.report_version, int)
            or isinstance(self.report_version, bool)
            or self.report_version <= 0
        ):
            raise ValueError("report_version must be a positive integer")
        _require_digest(self.report_digest, "report_digest")
        if self.report_digest != canonical_handoff_digest(self.payload):
            raise ValueError("report reference digest mismatch")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "project_id": self.project_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "content_ref_id": self.content_ref_id,
            "report_version": self.report_version,
            "supersedes_report_id": self.supersedes_report_id,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload, "report_digest": self.report_digest}

    @classmethod
    def create(cls, **values: Any) -> ReportRef:
        payload = {"schema_version": REPORT_REF_SCHEMA_VERSION, **values}
        return cls(**values, report_digest=canonical_handoff_digest(payload))

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ReportRef:
        expected = {
            "schema_version",
            "report_id",
            "project_id",
            "session_id",
            "task_id",
            "content_ref_id",
            "report_version",
            "supersedes_report_id",
            "report_digest",
        }
        if set(value) != expected:
            raise ValueError("report reference has unknown or missing fields")
        return cls(
            report_id=_strict_string(value["report_id"], "report_id"),
            project_id=_strict_string(value["project_id"], "project_id"),
            session_id=_strict_string(value["session_id"], "session_id"),
            task_id=_optional_strict_string(value["task_id"], "task_id"),
            content_ref_id=_strict_string(value["content_ref_id"], "content_ref_id"),
            report_version=_strict_integer(value["report_version"], "report_version"),
            supersedes_report_id=_optional_strict_string(
                value["supersedes_report_id"], "supersedes_report_id"
            ),
            report_digest=_strict_string(value["report_digest"], "report_digest"),
            schema_version=_strict_string(value["schema_version"], "schema_version"),
        )



__all__ = ["REPORT_REF_SCHEMA_VERSION", "ReportRef"]
