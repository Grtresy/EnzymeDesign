from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openzyme_domain import SourceRefKind

from .adapters import ResearchFinding


@dataclass(frozen=True, slots=True)
class ResearchFileManifest:
    external_id: str
    provider: str
    kind: str
    format: str
    filename: str
    title: str
    description: str | None = None
    source_locator: str | None = None
    metadata: dict[str, Any] | None = None
    content_digest: str | None = None
    retrieved_at: str | None = None
    provenance: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "external_id": self.external_id,
            "provider": self.provider,
            "kind": self.kind,
            "format": self.format,
            "filename": self.filename,
            "title": self.title,
            "description": self.description,
            "source_locator": self.source_locator,
            "metadata": {} if self.metadata is None else dict(self.metadata),
            "content_digest": self.content_digest,
            "retrieved_at": self.retrieved_at,
            "provenance": {} if self.provenance is None else dict(self.provenance),
        }


@dataclass(frozen=True, slots=True)
class ResearchObservation:
    status: str
    summary: str
    findings: tuple[ResearchFinding | dict[str, Any], ...] = ()
    unresolved_gaps: tuple[str, ...] = ()
    files: tuple[ResearchFileManifest | dict[str, Any], ...] = ()
    provider: str | None = None
    raw_ref: str | dict[str, Any] | None = None

    @classmethod
    def completed(
        cls,
        *,
        summary: str,
        findings: tuple[ResearchFinding | dict[str, Any], ...] = (),
        unresolved_gaps: tuple[str, ...] = (),
        files: tuple[ResearchFileManifest | dict[str, Any], ...] = (),
        provider: str | None = None,
        raw_ref: str | dict[str, Any] | None = None,
    ) -> "ResearchObservation":
        return cls(
            status="completed",
            summary=summary,
            findings=findings,
            unresolved_gaps=unresolved_gaps,
            files=files,
            provider=provider,
            raw_ref=raw_ref,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "findings": [_serialize_finding(finding) for finding in self.findings],
            "unresolved_gaps": list(self.unresolved_gaps),
            "files": [_serialize_file(file) for file in self.files],
            "provider": self.provider,
            "raw_ref": self.raw_ref,
        }


def _serialize_finding(finding: ResearchFinding | dict[str, Any]) -> dict[str, Any]:
    if isinstance(finding, ResearchFinding):
        return finding.to_dict()
    payload = dict(finding)
    payload["sources"] = [_serialize_source(source) for source in payload.get("sources", [])]
    return payload


def _serialize_source(source: dict[str, Any]) -> dict[str, Any]:
    payload = dict(source)
    kind = payload.get("kind")
    if isinstance(kind, SourceRefKind):
        payload["kind"] = kind.value
    return payload


def _serialize_file(file: ResearchFileManifest | dict[str, Any]) -> dict[str, Any]:
    if isinstance(file, ResearchFileManifest):
        return file.to_dict()
    return dict(file)


__all__ = ["ResearchFileManifest", "ResearchObservation"]
