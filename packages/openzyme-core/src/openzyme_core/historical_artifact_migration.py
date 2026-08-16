from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath
from typing import Protocol
import unicodedata

from openzyme_domain import HistoricalArtifactRef
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import canonical_historical_artifact_digest


class HistoricalArtifactMigrationError(RuntimeError):
    error_code = "historical_artifact_migration_blocked"


class HistoricalSourceReader(Protocol):
    """Read a frozen allowlisted source identity; no ambient-path fallback."""

    def read_exact(self, *, storage_uri: str) -> bytes: ...


class HistoricalGitLfsWriter(Protocol):
    def write_unit(
        self,
        *,
        historical_ref: str,
        files: tuple[tuple[str, bytes], ...],
        repository_binding_id: str,
        repository_binding_version: int,
    ) -> dict[str, object]: ...

    def fresh_readback(
        self,
        *,
        historical_ref: str,
        expected_commit: str,
        expected_tree: str,
        expected_paths: tuple[str, ...],
    ) -> tuple[bytes, ...]: ...


@dataclass(frozen=True, slots=True)
class HistoricalInventoryEntry:
    original_artifact_id: str
    project_id: str
    session_id: str
    original_kind: str
    storage_uri_digest: str
    relative_path: str
    content_digest: str
    size_bytes: int
    owner_identity_digest: str
    lineage_digest: str
    entry_digest: str


@dataclass(frozen=True, slots=True)
class HistoricalMigrationUnit:
    migration_unit_id: str
    project_id: str
    session_id: str
    repository_binding_id: str
    repository_binding_version: int
    historical_ref: str
    entries: tuple[HistoricalInventoryEntry, ...]
    identity_set_digest: str
    byte_total: int


def normalize_historical_target_path(
    *,
    session_id: str,
    artifact_id: str,
    relative_path: str,
) -> str:
    normalized = unicodedata.normalize("NFC", relative_path)
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or any(part in {"", ".", "..", ".git"} for part in path.parts)
        or "\\" in normalized
    ):
        raise HistoricalArtifactMigrationError("legacy path is unsafe")
    safe_session = hashlib.sha256(session_id.encode()).hexdigest()[:16]
    safe_artifact = hashlib.sha256(artifact_id.encode()).hexdigest()[:24]
    return f"legacy/{safe_session}/{safe_artifact}/{path.as_posix()}"


@dataclass(slots=True)
class HistoricalArtifactInventoryBuilder:
    reader: HistoricalSourceReader

    def inspect(
        self,
        *,
        project_id: str,
        records: tuple[SessionArtifactRecord, ...],
    ) -> tuple[HistoricalInventoryEntry, ...]:
        entries: list[HistoricalInventoryEntry] = []
        for record in sorted(records, key=lambda item: item.artifact_id):
            content = self.reader.read_exact(storage_uri=record.storage_uri)
            digest = "sha256:" + hashlib.sha256(content).hexdigest()
            declared_digest = str((record.metadata or {}).get("content_digest") or "")
            if declared_digest and declared_digest != digest:
                raise HistoricalArtifactMigrationError(
                    f"legacy bytes drifted for {record.artifact_id}"
                )
            owner_digest = canonical_historical_artifact_digest(
                {
                    "project_id": project_id,
                    "session_id": record.session_id,
                    "task_id": record.task_id,
                    "lane_id": record.lane_id,
                    "invocation_id": record.invocation_id,
                    "run_id": record.run_id,
                }
            )
            lineage_digest = canonical_historical_artifact_digest(
                {
                    "artifact_id": record.artifact_id,
                    "kind": record.kind.value,
                    "relative_path": record.relative_path,
                    "metadata": record.metadata or {},
                }
            )
            payload = {
                "original_artifact_id": record.artifact_id,
                "project_id": project_id,
                "session_id": record.session_id,
                "original_kind": record.kind.value,
                "storage_uri_digest": "sha256:"
                + hashlib.sha256(record.storage_uri.encode()).hexdigest(),
                "relative_path": record.relative_path,
                "content_digest": digest,
                "size_bytes": len(content),
                "owner_identity_digest": owner_digest,
                "lineage_digest": lineage_digest,
            }
            entries.append(
                HistoricalInventoryEntry(
                    **payload,
                    entry_digest=canonical_historical_artifact_digest(payload),
                )
            )
        return tuple(entries)


def plan_historical_migration_unit(
    *,
    project_id: str,
    session_id: str,
    repository_binding_id: str,
    repository_binding_version: int,
    entries: tuple[HistoricalInventoryEntry, ...],
) -> HistoricalMigrationUnit:
    if not entries or any(
        item.project_id != project_id or item.session_id != session_id for item in entries
    ):
        raise HistoricalArtifactMigrationError("migration unit ownership is ambiguous")
    entry_digests = tuple(sorted(item.entry_digest for item in entries))
    identity_set_digest = canonical_historical_artifact_digest(list(entry_digests))
    migration_unit_id = "historical_unit_" + identity_set_digest[-32:]
    return HistoricalMigrationUnit(
        migration_unit_id=migration_unit_id,
        project_id=project_id,
        session_id=session_id,
        repository_binding_id=repository_binding_id,
        repository_binding_version=repository_binding_version,
        historical_ref=f"refs/openzyme/history/{migration_unit_id}",
        entries=tuple(sorted(entries, key=lambda item: item.original_artifact_id)),
        identity_set_digest=identity_set_digest,
        byte_total=sum(item.size_bytes for item in entries),
    )


def reject_historical_adoption(ref: HistoricalArtifactRef) -> None:
    raise HistoricalArtifactMigrationError(
        f"{ref.historical_ref_id} is historical_import_non_adoptable"
    )


__all__ = [
    "HistoricalArtifactInventoryBuilder",
    "HistoricalArtifactMigrationError",
    "HistoricalGitLfsWriter",
    "HistoricalInventoryEntry",
    "HistoricalMigrationUnit",
    "HistoricalSourceReader",
    "normalize_historical_target_path",
    "plan_historical_migration_unit",
    "reject_historical_adoption",
]
