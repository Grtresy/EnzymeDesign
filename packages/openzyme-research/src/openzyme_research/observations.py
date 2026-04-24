from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openzyme_domain import ArtifactKind
from openzyme_domain import SourceRefKind

from .adapters import ResearchFinding


@dataclass(frozen=True, slots=True)
class ResearchArtifactManifest:
    external_id: str
    provider: str
    kind: ArtifactKind | str
    format: str
    filename: str
    title: str
    description: str | None = None
    source_locator: str | None = None
    metadata: dict[str, Any] | None = None
    storage_uri: str | None = None
    relative_path: str | None = None
    artifact_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind.value if isinstance(self.kind, ArtifactKind) else str(self.kind)
        return {
            "external_id": self.external_id,
            "provider": self.provider,
            "kind": kind,
            "format": self.format,
            "filename": self.filename,
            "title": self.title,
            "description": self.description,
            "source_locator": self.source_locator,
            "metadata": {} if self.metadata is None else dict(self.metadata),
            "storage_uri": self.storage_uri,
            "relative_path": self.relative_path,
            "artifact_id": self.artifact_id,
        }


@dataclass(frozen=True, slots=True)
class ResearchObservation:
    status: str
    summary: str
    findings: tuple[ResearchFinding | dict[str, Any], ...] = ()
    unresolved_gaps: tuple[str, ...] = ()
    artifacts: tuple[ResearchArtifactManifest | dict[str, Any], ...] = ()
    provider: str | None = None
    raw_ref: str | dict[str, Any] | None = None

    @classmethod
    def completed(
        cls,
        *,
        summary: str,
        findings: tuple[ResearchFinding | dict[str, Any], ...] = (),
        unresolved_gaps: tuple[str, ...] = (),
        artifacts: tuple[ResearchArtifactManifest | dict[str, Any], ...] = (),
        provider: str | None = None,
        raw_ref: str | dict[str, Any] | None = None,
    ) -> "ResearchObservation":
        return cls(
            status="completed",
            summary=summary,
            findings=findings,
            unresolved_gaps=unresolved_gaps,
            artifacts=artifacts,
            provider=provider,
            raw_ref=raw_ref,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "findings": [_serialize_finding(finding) for finding in self.findings],
            "unresolved_gaps": list(self.unresolved_gaps),
            "artifacts": [_serialize_artifact(artifact) for artifact in self.artifacts],
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


def _serialize_artifact(artifact: ResearchArtifactManifest | dict[str, Any]) -> dict[str, Any]:
    if isinstance(artifact, ResearchArtifactManifest):
        return artifact.to_dict()
    payload = dict(artifact)
    kind = payload.get("kind")
    if isinstance(kind, ArtifactKind):
        payload["kind"] = kind.value
    return payload


__all__ = ["ResearchArtifactManifest", "ResearchObservation"]
