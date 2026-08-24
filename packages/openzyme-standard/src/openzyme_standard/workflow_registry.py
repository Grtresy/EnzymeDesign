from __future__ import annotations

from dataclasses import dataclass

from openzyme_contracts import ClockPort
from openzyme_contracts import ResolvedWorkflowSelection
from openzyme_contracts import WorkflowSelectionRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import WorkflowRegistryResolutionError


STANDARD_WORKFLOW_REGISTRY_ID = "openzyme.standard.workflows.empty"
STANDARD_WORKFLOW_REGISTRY_SNAPSHOT_DIGEST = canonical_sha256_digest(
    {
        "schema_version": "openzyme_standard_workflow_registry@1",
        "distribution_id": "openzyme.standard",
        "registry_id": STANDARD_WORKFLOW_REGISTRY_ID,
        "workflow_refs": [],
        "compatibility_skill_keys": [],
        "default_selection": None,
    }
)


@dataclass(frozen=True, slots=True)
class StandardExplicitEmptyWorkflowRegistry:
    """Resolve only an explicit empty Standard workflow selection.

    Standard deliberately adopts no semantic workflow packs.  Missing selection
    metadata and an explicit empty array therefore resolve to the same *recorded
    empty authority*, while every non-empty canonical or compatibility request
    fails closed.  The resolver never scans installed packages or chooses a
    latest/default workflow.
    """

    clock: ClockPort
    distribution_id: str = "openzyme.standard"
    registry_id: str = STANDARD_WORKFLOW_REGISTRY_ID
    registry_snapshot_digest: str = STANDARD_WORKFLOW_REGISTRY_SNAPSHOT_DIGEST

    def resolve(
        self,
        request: WorkflowSelectionRequest,
    ) -> ResolvedWorkflowSelection:
        if request.distribution_id != self.distribution_id:
            self._reject(request, code="standard_workflow_distribution_mismatch")
        if request.requested_workflow_refs or request.compatibility_skill_keys:
            self._reject(request, code="standard_workflow_selection_unknown")
        return ResolvedWorkflowSelection(
            request_id=request.request_id,
            request_digest=request.request_digest,
            distribution_id=self.distribution_id,
            registry_id=self.registry_id,
            registry_snapshot_digest=self.registry_snapshot_digest,
            selected_workflow_refs=(),
            resolved_at=self.clock.now_iso(),
        )

    def _reject(self, request: WorkflowSelectionRequest, *, code: str) -> None:
        diagnostic_seed = canonical_sha256_digest(
            {
                "registry_snapshot_digest": self.registry_snapshot_digest,
                "request_digest": request.request_digest,
                "code": code,
            }
        ).removeprefix("sha256:")[:32]
        raise WorkflowRegistryResolutionError(
            code=code,
            diagnostic_id=f"diagnostic-workflow-{diagnostic_seed}",
            summary=(
                "OpenZyme Standard adopts an explicit-empty workflow registry; "
                "the requested selection is unavailable"
            ),
        )


__all__ = [
    "STANDARD_WORKFLOW_REGISTRY_ID",
    "STANDARD_WORKFLOW_REGISTRY_SNAPSHOT_DIGEST",
    "StandardExplicitEmptyWorkflowRegistry",
]
