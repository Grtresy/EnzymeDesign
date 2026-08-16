from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any

from .git_lfs_work_products import require_repository_path


REVISION_PATH_REF_SCHEMA_VERSION = "revision_path_ref@1"
TASK_EVIDENCE_REF_SCHEMA_VERSION = "task_evidence_ref@1"
PROTOCOL_FILE_HANDOFF_SCHEMA_VERSION = "protocol_file_handoff@1"
REPORT_REF_SCHEMA_VERSION = "report_ref@1"
CONTROLLED_OPERATION_RESULT_REF_SCHEMA_VERSION = "controlled_operation_result_ref@1"
SCIENTIFIC_DELIVERABLE_REF_SCHEMA_VERSION = "scientific_deliverable_ref@1"


class RevisionPathEntryKind(StrEnum):
    FILE = "file"
    LFS_FILE = "lfs_file"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    GITLINK = "gitlink"


class TaskEvidenceKind(StrEnum):
    REVISION_PATH = "revision_path"
    REPORT = "report"
    CONTROLLED_OPERATION_RESULT = "controlled_operation_result"
    SCIENTIFIC_DELIVERABLE = "scientific_deliverable"


def canonical_handoff_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


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


def _require_object_id(value: str, field_name: str) -> None:
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value) is None:
        raise ValueError(f"{field_name} must be a lowercase Git object id")


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


def _optional_strict_integer(value: Any, field_name: str) -> int | None:
    return None if value is None else _strict_integer(value, field_name)


@dataclass(frozen=True, slots=True)
class RevisionPathRef:
    ref_id: str
    publication_id: str
    project_id: str
    session_id: str
    repository_binding_id: str
    repository_binding_version: int
    repository_id: str
    commit: str
    tree: str
    path: str
    entry_kind: RevisionPathEntryKind
    object_id: str
    size_bytes: int | None
    lfs_oid: str | None
    lfs_size_bytes: int | None
    path_manifest_digest: str | None
    created_at: str
    ref_digest: str
    schema_version: str = REVISION_PATH_REF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REVISION_PATH_REF_SCHEMA_VERSION:
            raise ValueError("unsupported revision path reference schema")
        for field_name in (
            "ref_id",
            "publication_id",
            "project_id",
            "session_id",
            "repository_binding_id",
            "repository_id",
            "created_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        if (
            not isinstance(self.repository_binding_version, int)
            or isinstance(self.repository_binding_version, bool)
            or self.repository_binding_version <= 0
        ):
            raise ValueError("repository_binding_version must be a positive integer")
        _require_object_id(self.commit, "commit")
        _require_object_id(self.tree, "tree")
        require_repository_path(self.path)
        if len(self.path.encode("utf-8")) > 1024:
            raise ValueError("path must be at most 1024 bytes")
        if not isinstance(self.entry_kind, RevisionPathEntryKind):
            raise TypeError("entry_kind must be a RevisionPathEntryKind")
        _require_object_id(self.object_id, "object_id")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        if self.entry_kind is RevisionPathEntryKind.LFS_FILE:
            if (
                self.size_bytes is None
                or self.lfs_oid is None
                or self.lfs_size_bytes is None
            ):
                raise ValueError(
                    "LFS file reference requires pointer size, LFS oid, and LFS size"
                )
            _require_digest(self.lfs_oid, "lfs_oid")
            if self.lfs_size_bytes < 0:
                raise ValueError("lfs_size_bytes must be non-negative")
            if self.path_manifest_digest is not None:
                raise ValueError("LFS file reference cannot carry path manifest")
        elif self.entry_kind is RevisionPathEntryKind.DIRECTORY:
            if self.path_manifest_digest is None:
                raise ValueError("directory reference requires path manifest digest")
            _require_digest(self.path_manifest_digest, "path_manifest_digest")
            if any(value is not None for value in (self.size_bytes, self.lfs_oid, self.lfs_size_bytes)):
                raise ValueError("directory reference cannot carry file size or LFS identity")
        else:
            if any(value is not None for value in (self.lfs_oid, self.lfs_size_bytes, self.path_manifest_digest)):
                raise ValueError("non-LFS file reference carries incompatible identity")
            if self.entry_kind in {RevisionPathEntryKind.FILE, RevisionPathEntryKind.SYMLINK} and self.size_bytes is None:
                raise ValueError("file reference requires byte size")
            if self.entry_kind is RevisionPathEntryKind.GITLINK and self.size_bytes is not None:
                raise ValueError("gitlink reference cannot carry byte size")
        _require_digest(self.ref_digest, "ref_digest")
        if self.ref_digest != canonical_handoff_digest(self.payload):
            raise ValueError("revision path reference digest mismatch")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ref_id": self.ref_id,
            "publication_id": self.publication_id,
            "project_id": self.project_id,
            "session_id": self.session_id,
            "repository_binding_id": self.repository_binding_id,
            "repository_binding_version": self.repository_binding_version,
            "repository_id": self.repository_id,
            "commit": self.commit,
            "tree": self.tree,
            "path": self.path,
            "entry_kind": self.entry_kind.value,
            "object_id": self.object_id,
            "size_bytes": self.size_bytes,
            "lfs_oid": self.lfs_oid,
            "lfs_size_bytes": self.lfs_size_bytes,
            "path_manifest_digest": self.path_manifest_digest,
            "created_at": self.created_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload, "ref_digest": self.ref_digest}

    @classmethod
    def create(cls, **values: Any) -> RevisionPathRef:
        payload = {
            "schema_version": REVISION_PATH_REF_SCHEMA_VERSION,
            **values,
            "entry_kind": values["entry_kind"].value,
        }
        return cls(**values, ref_digest=canonical_handoff_digest(payload))

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RevisionPathRef:
        expected = {
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
        }
        if set(value) != expected:
            raise ValueError("revision path reference has unknown or missing fields")
        return cls(
            ref_id=_strict_string(value["ref_id"], "ref_id"),
            publication_id=_strict_string(value["publication_id"], "publication_id"),
            project_id=_strict_string(value["project_id"], "project_id"),
            session_id=_strict_string(value["session_id"], "session_id"),
            repository_binding_id=_strict_string(
                value["repository_binding_id"], "repository_binding_id"
            ),
            repository_binding_version=_strict_integer(
                value["repository_binding_version"], "repository_binding_version"
            ),
            repository_id=_strict_string(value["repository_id"], "repository_id"),
            commit=_strict_string(value["commit"], "commit"),
            tree=_strict_string(value["tree"], "tree"),
            path=_strict_string(value["path"], "path"),
            entry_kind=RevisionPathEntryKind(
                _strict_string(value["entry_kind"], "entry_kind")
            ),
            object_id=_strict_string(value["object_id"], "object_id"),
            size_bytes=_optional_strict_integer(value["size_bytes"], "size_bytes"),
            lfs_oid=_optional_strict_string(value["lfs_oid"], "lfs_oid"),
            lfs_size_bytes=_optional_strict_integer(
                value["lfs_size_bytes"], "lfs_size_bytes"
            ),
            path_manifest_digest=_optional_strict_string(
                value["path_manifest_digest"], "path_manifest_digest"
            ),
            created_at=_strict_string(value["created_at"], "created_at"),
            ref_digest=_strict_string(value["ref_digest"], "ref_digest"),
            schema_version=_strict_string(value["schema_version"], "schema_version"),
        )


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


@dataclass(frozen=True, slots=True)
class ControlledOperationResultRef:
    result_handle_id: str
    project_id: str
    session_id: str
    task_id: str | None
    execution_id: str
    operation_id: str
    dispatch_generation: int
    terminal_outcome: str
    result_digest: str
    schema_version: str = CONTROLLED_OPERATION_RESULT_REF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CONTROLLED_OPERATION_RESULT_REF_SCHEMA_VERSION:
            raise ValueError("unsupported controlled-operation result reference schema")
        for field_name in (
            "result_handle_id",
            "project_id",
            "session_id",
            "execution_id",
            "operation_id",
            "terminal_outcome",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        if self.task_id is not None:
            _require_identifier(self.task_id, "task_id")
        if (
            not isinstance(self.dispatch_generation, int)
            or isinstance(self.dispatch_generation, bool)
            or self.dispatch_generation <= 0
        ):
            raise ValueError("dispatch_generation must be a positive integer")
        _require_digest(self.result_digest, "result_digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "result_handle_id": self.result_handle_id,
            "project_id": self.project_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "execution_id": self.execution_id,
            "operation_id": self.operation_id,
            "dispatch_generation": self.dispatch_generation,
            "terminal_outcome": self.terminal_outcome,
            "result_digest": self.result_digest,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ControlledOperationResultRef:
        expected = {
            "schema_version",
            "result_handle_id",
            "project_id",
            "session_id",
            "task_id",
            "execution_id",
            "operation_id",
            "dispatch_generation",
            "terminal_outcome",
            "result_digest",
        }
        if set(value) != expected:
            raise ValueError(
                "controlled-operation result reference has unknown or missing fields"
            )
        return cls(
            result_handle_id=_strict_string(
                value["result_handle_id"], "result_handle_id"
            ),
            project_id=_strict_string(value["project_id"], "project_id"),
            session_id=_strict_string(value["session_id"], "session_id"),
            task_id=_optional_strict_string(value["task_id"], "task_id"),
            execution_id=_strict_string(value["execution_id"], "execution_id"),
            operation_id=_strict_string(value["operation_id"], "operation_id"),
            dispatch_generation=_strict_integer(
                value["dispatch_generation"], "dispatch_generation"
            ),
            terminal_outcome=_strict_string(
                value["terminal_outcome"], "terminal_outcome"
            ),
            result_digest=_strict_string(value["result_digest"], "result_digest"),
            schema_version=_strict_string(value["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class TaskEvidenceRef:
    kind: TaskEvidenceKind
    project_id: str
    session_id: str
    task_id: str
    owner_id: str
    owner_digest: str
    revision_path_ref: RevisionPathRef | None = None
    report_ref: ReportRef | None = None
    controlled_operation_result_ref: ControlledOperationResultRef | None = None
    schema_version: str = TASK_EVIDENCE_REF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != TASK_EVIDENCE_REF_SCHEMA_VERSION:
            raise ValueError("unsupported task evidence reference schema")
        if not isinstance(self.kind, TaskEvidenceKind):
            raise TypeError("kind must be a TaskEvidenceKind")
        for field_name in ("project_id", "session_id", "task_id", "owner_id"):
            _require_identifier(getattr(self, field_name), field_name)
        _require_digest(self.owner_digest, "owner_digest")
        if self.kind is TaskEvidenceKind.REVISION_PATH:
            if self.revision_path_ref is None:
                raise ValueError("revision_path evidence requires a RevisionPathRef")
            if (
                self.revision_path_ref.ref_id != self.owner_id
                or self.revision_path_ref.ref_digest != self.owner_digest
                or self.revision_path_ref.project_id != self.project_id
                or self.revision_path_ref.session_id != self.session_id
            ):
                raise ValueError("revision_path evidence owner identity differs from its ref")
            if self.report_ref is not None or self.controlled_operation_result_ref is not None:
                raise ValueError("revision-path evidence carries another evidence variant")
        elif self.kind is TaskEvidenceKind.REPORT:
            if self.report_ref is None:
                raise ValueError("report evidence requires a ReportRef")
            if (
                self.report_ref.report_id != self.owner_id
                or self.report_ref.report_digest != self.owner_digest
                or self.report_ref.project_id != self.project_id
                or self.report_ref.session_id != self.session_id
                or self.report_ref.task_id != self.task_id
            ):
                raise ValueError("report evidence owner identity differs from its ref")
            if self.revision_path_ref is not None or self.controlled_operation_result_ref is not None:
                raise ValueError("report evidence carries another evidence variant")
        elif self.kind is TaskEvidenceKind.CONTROLLED_OPERATION_RESULT:
            if self.controlled_operation_result_ref is None:
                raise ValueError(
                    "controlled-operation evidence requires a ControlledOperationResultRef"
                )
            result_ref = self.controlled_operation_result_ref
            if (
                result_ref.result_handle_id != self.owner_id
                or result_ref.result_digest != self.owner_digest
                or result_ref.project_id != self.project_id
                or result_ref.session_id != self.session_id
                or result_ref.task_id != self.task_id
            ):
                raise ValueError(
                    "controlled-operation evidence owner identity differs from its ref"
                )
            if self.revision_path_ref is not None or self.report_ref is not None:
                raise ValueError(
                    "controlled-operation evidence carries another evidence variant"
                )
        else:
            raise ValueError(
                "scientific deliverable evidence is unavailable until its closed schema is installed"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind.value,
            "project_id": self.project_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "owner_id": self.owner_id,
            "owner_digest": self.owner_digest,
            "revision_path_ref": None if self.revision_path_ref is None else self.revision_path_ref.to_dict(),
            "report_ref": None if self.report_ref is None else self.report_ref.to_dict(),
            "controlled_operation_result_ref": (
                None
                if self.controlled_operation_result_ref is None
                else self.controlled_operation_result_ref.to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TaskEvidenceRef:
        expected = {
            "schema_version",
            "kind",
            "project_id",
            "session_id",
            "task_id",
            "owner_id",
            "owner_digest",
            "revision_path_ref",
            "report_ref",
            "controlled_operation_result_ref",
        }
        if set(value) != expected:
            raise ValueError("task evidence reference has unknown or missing fields")
        raw_revision = value["revision_path_ref"]
        if raw_revision is not None and not isinstance(raw_revision, dict):
            raise ValueError("revision_path_ref must be an object or null")
        raw_report = value["report_ref"]
        if raw_report is not None and not isinstance(raw_report, dict):
            raise ValueError("report_ref must be an object or null")
        raw_controlled_result = value["controlled_operation_result_ref"]
        if raw_controlled_result is not None and not isinstance(
            raw_controlled_result, dict
        ):
            raise ValueError(
                "controlled_operation_result_ref must be an object or null"
            )
        return cls(
            kind=TaskEvidenceKind(_strict_string(value["kind"], "kind")),
            project_id=_strict_string(value["project_id"], "project_id"),
            session_id=_strict_string(value["session_id"], "session_id"),
            task_id=_strict_string(value["task_id"], "task_id"),
            owner_id=_strict_string(value["owner_id"], "owner_id"),
            owner_digest=_strict_string(value["owner_digest"], "owner_digest"),
            revision_path_ref=None if raw_revision is None else RevisionPathRef.from_dict(raw_revision),
            report_ref=None if raw_report is None else ReportRef.from_dict(raw_report),
            controlled_operation_result_ref=(
                None
                if raw_controlled_result is None
                else ControlledOperationResultRef.from_dict(raw_controlled_result)
            ),
            schema_version=_strict_string(value["schema_version"], "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class ProtocolFileHandoff:
    handoff_id: str
    project_id: str
    session_id: str
    producer_agent_id: str
    recipient_agent_id: str
    purpose: str
    entries: tuple[RevisionPathRef, ...]
    created_at: str
    handoff_digest: str
    schema_version: str = PROTOCOL_FILE_HANDOFF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PROTOCOL_FILE_HANDOFF_SCHEMA_VERSION:
            raise ValueError("unsupported protocol file handoff schema")
        for field_name in (
            "handoff_id",
            "project_id",
            "session_id",
            "producer_agent_id",
            "recipient_agent_id",
            "created_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        if not self.purpose or self.purpose != self.purpose.strip() or len(self.purpose.encode("utf-8")) > 512:
            raise ValueError("handoff purpose must be non-empty and at most 512 bytes")
        if not self.entries or len(self.entries) > 32:
            raise ValueError("handoff must carry between 1 and 32 revision path refs")
        if len({entry.ref_id for entry in self.entries}) != len(self.entries):
            raise ValueError("handoff revision path refs must be unique")
        if any(entry.project_id != self.project_id or entry.session_id != self.session_id for entry in self.entries):
            raise ValueError("handoff entries must belong to the exact project and session")
        if len(
            json.dumps(
                self.payload,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ) > 131_072:
            raise ValueError("protocol file handoff exceeds 131072 bytes")
        _require_digest(self.handoff_digest, "handoff_digest")
        if self.handoff_digest != canonical_handoff_digest(self.payload):
            raise ValueError("protocol file handoff digest mismatch")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "handoff_id": self.handoff_id,
            "project_id": self.project_id,
            "session_id": self.session_id,
            "producer_agent_id": self.producer_agent_id,
            "recipient_agent_id": self.recipient_agent_id,
            "purpose": self.purpose,
            "entries": [entry.to_dict() for entry in self.entries],
            "created_at": self.created_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload, "handoff_digest": self.handoff_digest}

    @classmethod
    def create(cls, **values: Any) -> ProtocolFileHandoff:
        payload = {
            "schema_version": PROTOCOL_FILE_HANDOFF_SCHEMA_VERSION,
            **values,
            "entries": [entry.to_dict() for entry in values["entries"]],
        }
        return cls(**values, handoff_digest=canonical_handoff_digest(payload))

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ProtocolFileHandoff:
        expected = {
            "schema_version",
            "handoff_id",
            "project_id",
            "session_id",
            "producer_agent_id",
            "recipient_agent_id",
            "purpose",
            "entries",
            "created_at",
            "handoff_digest",
        }
        if set(value) != expected:
            raise ValueError("protocol file handoff has unknown or missing fields")
        entries = value["entries"]
        if not isinstance(entries, list):
            raise ValueError("protocol file handoff entries must be an array")
        if any(not isinstance(item, dict) for item in entries):
            raise ValueError(
                "protocol file handoff entries must contain only revision path objects"
            )
        return cls(
            handoff_id=_strict_string(value["handoff_id"], "handoff_id"),
            project_id=_strict_string(value["project_id"], "project_id"),
            session_id=_strict_string(value["session_id"], "session_id"),
            producer_agent_id=_strict_string(
                value["producer_agent_id"], "producer_agent_id"
            ),
            recipient_agent_id=_strict_string(
                value["recipient_agent_id"], "recipient_agent_id"
            ),
            purpose=_strict_string(value["purpose"], "purpose"),
            entries=tuple(
                RevisionPathRef.from_dict(item)
                for item in entries
            ),
            created_at=_strict_string(value["created_at"], "created_at"),
            handoff_digest=_strict_string(value["handoff_digest"], "handoff_digest"),
            schema_version=_strict_string(value["schema_version"], "schema_version"),
        )


__all__ = [
    "CONTROLLED_OPERATION_RESULT_REF_SCHEMA_VERSION",
    "ControlledOperationResultRef",
    "PROTOCOL_FILE_HANDOFF_SCHEMA_VERSION",
    "REPORT_REF_SCHEMA_VERSION",
    "ReportRef",
    "REVISION_PATH_REF_SCHEMA_VERSION",
    "SCIENTIFIC_DELIVERABLE_REF_SCHEMA_VERSION",
    "TASK_EVIDENCE_REF_SCHEMA_VERSION",
    "ProtocolFileHandoff",
    "RevisionPathEntryKind",
    "RevisionPathRef",
    "TaskEvidenceKind",
    "TaskEvidenceRef",
    "canonical_handoff_digest",
]
