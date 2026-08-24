from __future__ import annotations

from dataclasses import dataclass

from enzymedesign_aox import AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_ID
from enzymedesign_aox import AOX_SELECTED_CHAIN_WORKFLOW_ID
from openzyme_contracts import ClockPort
from openzyme_contracts import ResolvedWorkflowSelection
from openzyme_contracts import WorkflowSelectionRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import WorkflowRegistryResolutionError


ENZYMEDESIGN_WORKFLOW_REGISTRY_ID = "enzymedesign.workflows.adopted@1"
ENZYMEDESIGN_ADOPTED_WORKFLOW_REFS = (AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_ID,)
ENZYMEDESIGN_COMPATIBILITY_SKILL_KEYS = {
    AOX_SELECTED_CHAIN_WORKFLOW_ID: AOX_SELECTED_CHAIN_WORKFLOW_CONTRACT_ID,
}
ENZYMEDESIGN_WORKFLOW_REGISTRY_SNAPSHOT_DIGEST = canonical_sha256_digest(
    {
        "schema_version": "enzymedesign_workflow_registry@1",
        "distribution_id": "enzymedesign",
        "registry_id": ENZYMEDESIGN_WORKFLOW_REGISTRY_ID,
        "workflow_refs": list(ENZYMEDESIGN_ADOPTED_WORKFLOW_REFS),
        "compatibility_skill_keys": ENZYMEDESIGN_COMPATIBILITY_SKILL_KEYS,
        "default_selection": None,
        "latest_resolution_permitted": False,
        "ambient_discovery_permitted": False,
    }
)


@dataclass(frozen=True, slots=True)
class EnzymeDesignExactWorkflowRegistry:
    """Resolve only the Distribution-adopted exact workflow identities.

    Empty input is an explicit empty selection.  Compatibility keys are request
    aliases only and are converted to the one frozen exact ref before the Kernel
    creates authority.  Installed packages, prose, historical entries and
    ``latest``/``all`` conventions are never consulted.
    """

    clock: ClockPort
    distribution_id: str = "enzymedesign"
    registry_id: str = ENZYMEDESIGN_WORKFLOW_REGISTRY_ID
    registry_snapshot_digest: str = ENZYMEDESIGN_WORKFLOW_REGISTRY_SNAPSHOT_DIGEST

    def resolve(
        self,
        request: WorkflowSelectionRequest,
    ) -> ResolvedWorkflowSelection:
        if request.distribution_id != self.distribution_id:
            self._reject(request, code="enzymedesign_workflow_distribution_mismatch")
        if request.requested_workflow_refs:
            unknown = set(request.requested_workflow_refs).difference(
                ENZYMEDESIGN_ADOPTED_WORKFLOW_REFS
            )
            if unknown:
                self._reject(request, code="enzymedesign_workflow_selection_unknown")
            selected = request.requested_workflow_refs
        elif request.compatibility_skill_keys:
            try:
                selected = tuple(
                    sorted(
                        {
                            ENZYMEDESIGN_COMPATIBILITY_SKILL_KEYS[key]
                            for key in request.compatibility_skill_keys
                        }
                    )
                )
            except KeyError as exc:
                self._reject(
                    request,
                    code="enzymedesign_workflow_compatibility_key_unknown",
                    cause=exc,
                )
        else:
            selected = ()
        return ResolvedWorkflowSelection(
            request_id=request.request_id,
            request_digest=request.request_digest,
            distribution_id=self.distribution_id,
            registry_id=self.registry_id,
            registry_snapshot_digest=self.registry_snapshot_digest,
            selected_workflow_refs=selected,
            resolved_at=self.clock.now_iso(),
        )

    def _reject(
        self,
        request: WorkflowSelectionRequest,
        *,
        code: str,
        cause: Exception | None = None,
    ) -> None:
        diagnostic_seed = canonical_sha256_digest(
            {
                "registry_snapshot_digest": self.registry_snapshot_digest,
                "request_digest": request.request_digest,
                "code": code,
            }
        ).removeprefix("sha256:")[:32]
        error = WorkflowRegistryResolutionError(
            code=code,
            diagnostic_id=f"diagnostic-workflow-{diagnostic_seed}",
            summary=(
                "The requested EnzymeDesign workflow selection is not present in "
                "the adopted exact registry snapshot"
            ),
        )
        if cause is not None:
            raise error from cause
        raise error


__all__ = [
    "ENZYMEDESIGN_ADOPTED_WORKFLOW_REFS",
    "ENZYMEDESIGN_COMPATIBILITY_SKILL_KEYS",
    "ENZYMEDESIGN_WORKFLOW_REGISTRY_ID",
    "ENZYMEDESIGN_WORKFLOW_REGISTRY_SNAPSHOT_DIGEST",
    "EnzymeDesignExactWorkflowRegistry",
]
