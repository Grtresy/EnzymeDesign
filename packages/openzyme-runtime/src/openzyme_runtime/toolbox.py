from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import CandidateSnapshot
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

    def load_candidate(self, episode_id: str, candidate_id: str) -> CandidateSnapshot | None:
        record = self.repositories.candidates.get(candidate_id)
        if record is None:
            return None
        return CandidateSnapshot(
            episode_id=episode_id,
            candidate_id=record.candidate_id,
            title=record.title,
            summary=record.summary,
            supporting_evidence_ids=list(record.supporting_evidence_ids),
        )

    def build_execution_request(
        self,
        *,
        candidate: CandidateSnapshot,
        execution_mode: str = "auto",
        command: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionRequestDraft:
        merged_metadata = dict(metadata or {})
        merged_metadata.setdefault("candidate_id", candidate.candidate_id)
        merged_metadata.setdefault("supporting_evidence_ids", list(candidate.supporting_evidence_ids))
        return ExecutionRequestDraft(
            tool_name="exec.run",
            runspec=ExecutionRunSpecDraft(
                name=f"execution-{candidate.candidate_id}",
                stage="execution",
                command=command or ["echo", candidate.title],
                execution_mode=execution_mode,
                metadata=merged_metadata,
            ),
        )


__all__ = ["OpenZymeHostToolbox"]
