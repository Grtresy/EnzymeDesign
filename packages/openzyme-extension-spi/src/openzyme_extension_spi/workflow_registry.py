from __future__ import annotations

from typing import Protocol

from openzyme_contracts import ResolvedWorkflowSelection
from openzyme_contracts import WorkflowSelectionRequest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier


class WorkflowRegistryResolutionError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        diagnostic_id: str,
        summary: str,
    ) -> None:
        require_identifier(code, field_name="code")
        require_identifier(diagnostic_id, field_name="diagnostic_id")
        if not isinstance(summary, str) or not summary or len(summary) > 16_384:
            raise ValueError("summary must be non-empty and bounded")
        self.code = code
        self.diagnostic_id = diagnostic_id
        self.effect_certainty = "no_effect"
        self.mutation_applied = False
        self.fallback_performed = False
        super().__init__(
            f"{summary}; mutation_applied=false; fallback_performed=false"
        )


class WorkflowRegistryResolverPort(Protocol):
    """Distribution-owned exact registry snapshot resolver."""

    distribution_id: str
    registry_id: str
    registry_snapshot_digest: str

    def resolve(
        self,
        request: WorkflowSelectionRequest,
    ) -> ResolvedWorkflowSelection: ...


def validate_workflow_registry_resolver_identity(
    resolver: WorkflowRegistryResolverPort,
) -> None:
    require_identifier(resolver.distribution_id, field_name="distribution_id")
    require_identifier(resolver.registry_id, field_name="registry_id")
    require_digest(
        resolver.registry_snapshot_digest,
        field_name="registry_snapshot_digest",
    )


__all__ = [
    "WorkflowRegistryResolutionError",
    "WorkflowRegistryResolverPort",
    "validate_workflow_registry_resolver_identity",
]
