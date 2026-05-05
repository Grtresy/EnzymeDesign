from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openzyme_domain import ArtifactKind
from openzyme_domain import ArtifactRecord
from .contracts import CanonicalResearchSnapshot
from .contracts import ExecutionRequestDraft
from .contracts import ExecutionRunSpecDraft
from .repositories import PhaseBRepositories


@dataclass(frozen=True, slots=True)
class OpenZymeHostToolbox:
    repositories: PhaseBRepositories

    def load_canonical_research(self, episode_id: str) -> CanonicalResearchSnapshot:
        summary = self.repositories.research_summaries.get_by_episode(episode_id)
        evidence = self.repositories.evidence_records.list_by_episode(episode_id)
        unresolved_gaps = self.repositories.unresolved_gaps.list_by_episode(episode_id)
        return CanonicalResearchSnapshot(
            episode_id=episode_id,
            research_summary=None if summary is None else summary.to_dict(),
            evidence_refs=[record.to_dict() for record in evidence],
            unresolved_gaps=[record.to_dict() for record in unresolved_gaps],
        )

    def list_artifacts(self, episode_id: str) -> list[dict[str, Any]]:
        return [artifact.to_dict() for artifact in self.repositories.artifact_records.list_by_episode(episode_id)]

    def load_artifact(self, episode_id: str, artifact_id: str) -> dict[str, Any] | None:
        artifact = self.repositories.artifact_records.get(artifact_id)
        if artifact is None or artifact.episode_id != episode_id:
            return None
        return artifact.to_dict()

    def resolve_artifacts(self, episode_id: str, artifact_ids: list[str]) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        for artifact_id in artifact_ids:
            artifact = self.load_artifact(episode_id, artifact_id)
            if artifact is not None:
                resolved.append(artifact)
        return resolved

    def list_execution_ready_artifacts(self, episode_id: str) -> list[dict[str, Any]]:
        ready: list[dict[str, Any]] = []
        for artifact in self.list_artifacts(episode_id):
            availability = dict(artifact.get("availability") or {})
            if bool(availability.get("execution_input")) or artifact.get("kind") == ArtifactKind.STRUCTURE.value:
                ready.append(artifact)
        return ready

    def get_artifact_manifest(self, episode_id: str, artifact_id: str) -> dict[str, Any] | None:
        return self.load_artifact(episode_id, artifact_id)

    def read_artifact_content(self, episode_id: str, artifact_id: str) -> dict[str, Any] | None:
        artifact = self.load_artifact(episode_id, artifact_id)
        if artifact is None:
            return None
        return {
            "artifact_id": artifact_id,
            "storage_uri": artifact["storage_uri"],
            "title": artifact.get("title"),
            "description": artifact.get("description"),
            "metadata": dict(artifact.get("metadata") or {}),
            "availability": dict(artifact.get("availability") or {}),
        }

    def register_artifact_reference(
        self,
        *,
        artifact_id: str,
        episode_id: str,
        storage_uri: str,
        created_at: str,
        kind: ArtifactKind = ArtifactKind.RESULT,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        provenance: dict[str, Any] | None = None,
        availability: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.register_artifact(
            artifact_id=artifact_id,
            episode_id=episode_id,
            kind=kind,
            storage_uri=storage_uri,
            created_at=created_at,
            title=title,
            description=description,
            tags=tags,
            provenance=provenance,
            availability=availability,
            metadata=metadata,
        ).to_dict()

    def register_artifact(
        self,
        *,
        artifact_id: str,
        episode_id: str,
        kind: ArtifactKind,
        storage_uri: str,
        created_at: str,
        run_id: str | None = None,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        provenance: dict[str, Any] | None = None,
        availability: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRecord:
        record = ArtifactRecord(
            artifact_id=artifact_id,
            episode_id=episode_id,
            run_id=run_id,
            kind=kind,
            storage_uri=storage_uri,
            created_at=created_at,
            title=title,
            description=description,
            tags=tuple(tags or ()),
            provenance=None if provenance is None else dict(provenance),
            availability=None if availability is None else dict(availability),
            metadata=None if metadata is None else dict(metadata),
        )
        self.repositories.artifact_records.save(record)
        return record

    def annotate_artifact(
        self,
        *,
        episode_id: str,
        artifact_id: str,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        availability: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        existing = self.repositories.artifact_records.get(artifact_id)
        if existing is None or existing.episode_id != episode_id:
            return None
        updated = ArtifactRecord(
            artifact_id=existing.artifact_id,
            episode_id=existing.episode_id,
            run_id=existing.run_id,
            kind=existing.kind,
            storage_uri=existing.storage_uri,
            created_at=existing.created_at,
            title=existing.title if title is None else title,
            description=existing.description if description is None else description,
            tags=existing.tags if tags is None else tuple(tags),
            provenance=existing.provenance,
            availability=existing.availability if availability is None else dict(availability),
            metadata=existing.metadata if metadata is None else dict(metadata),
        )
        self.repositories.artifact_records.save(updated)
        return updated.to_dict()

    def build_execution_request(
        self,
        *,
        execution_subject_id: str,
        execution_subject_label: str,
        execution_mode: str = "auto",
        command: list[str] | None = None,
        runspec: ExecutionRunSpecDraft | dict[str, Any] | None = None,
        resources: dict[str, Any] | None = None,
        inputs: list[dict[str, Any]] | None = None,
        expected_outputs: list[dict[str, Any]] | None = None,
        success_checks: list[dict[str, Any]] | None = None,
        failure_signatures: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        tool_name: str = "exec.run",
    ) -> ExecutionRequestDraft:
        merged_metadata = dict(metadata or {})
        merged_metadata.setdefault("execution_subject_id", execution_subject_id)
        merged_metadata.setdefault("execution_subject_label", execution_subject_label)
        if runspec is not None:
            run_spec_draft = (
                runspec
                if isinstance(runspec, ExecutionRunSpecDraft)
                else ExecutionRunSpecDraft.model_validate(runspec)
            )
            run_spec_payload = run_spec_draft.model_dump()
            run_spec_payload["metadata"] = {
                **dict(run_spec_payload.get("metadata") or {}),
                **merged_metadata,
            }
            return ExecutionRequestDraft(
                tool_name=tool_name,
                runspec=ExecutionRunSpecDraft.model_validate(run_spec_payload),
            )
        return ExecutionRequestDraft(
            tool_name=tool_name,
            runspec=ExecutionRunSpecDraft(
                name=f"execution-{execution_subject_id}",
                stage="execution",
                command=command or ["echo", execution_subject_label],
                execution_mode=execution_mode,
                resources={} if resources is None else resources,
                inputs=[] if inputs is None else inputs,
                expected_outputs=[] if expected_outputs is None else expected_outputs,
                success_checks=[] if success_checks is None else success_checks,
                failure_signatures=[] if failure_signatures is None else failure_signatures,
                metadata=merged_metadata,
            ),
        )


__all__ = ["OpenZymeHostToolbox"]
