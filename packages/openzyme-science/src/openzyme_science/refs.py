from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


SCIENTIFIC_CLOSURE_REF_SCHEMA_VERSION = "scientific_closure_ref@1"


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


@dataclass(frozen=True, slots=True)
class ScientificClosureRef:
    closure_id: str
    project_id: str
    session_id: str
    task_id: str
    attempt_id: str
    selection_id: str
    closure_digest: str
    schema_version: str = SCIENTIFIC_CLOSURE_REF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCIENTIFIC_CLOSURE_REF_SCHEMA_VERSION:
            raise ValueError("unsupported scientific closure ref schema")
        for field_name in (
            "closure_id",
            "project_id",
            "session_id",
            "task_id",
            "attempt_id",
            "selection_id",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_digest(self.closure_digest, "closure_digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "closure_id": self.closure_id,
            "project_id": self.project_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "selection_id": self.selection_id,
            "closure_digest": self.closure_digest,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ScientificClosureRef":
        expected = {
            "schema_version",
            "closure_id",
            "project_id",
            "session_id",
            "task_id",
            "attempt_id",
            "selection_id",
            "closure_digest",
        }
        if set(value) != expected:
            raise ValueError("scientific closure ref has unknown or missing fields")
        return cls(
            schema_version=_strict_string(value["schema_version"], "schema_version"),
            closure_id=_strict_string(value["closure_id"], "closure_id"),
            project_id=_strict_string(value["project_id"], "project_id"),
            session_id=_strict_string(value["session_id"], "session_id"),
            task_id=_strict_string(value["task_id"], "task_id"),
            attempt_id=_strict_string(value["attempt_id"], "attempt_id"),
            selection_id=_strict_string(value["selection_id"], "selection_id"),
            closure_digest=_strict_string(value["closure_digest"], "closure_digest"),
        )


__all__ = ["SCIENTIFIC_CLOSURE_REF_SCHEMA_VERSION", "ScientificClosureRef"]
