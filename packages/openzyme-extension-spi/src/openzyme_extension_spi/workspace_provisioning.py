from __future__ import annotations

from typing import Protocol

from openzyme_contracts import WorkspaceProvisioningReceipt
from openzyme_contracts import WorkspaceProvisioningReconciliationRequest
from openzyme_contracts import WorkspaceProvisioningRequest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier


class WorkspaceProvisionerPortError(RuntimeError):
    """Secret-safe Adapter mechanism failure; Kernel still owns settlement truth."""

    def __init__(self, *, code: str, diagnostic_id: str, summary: str) -> None:
        require_identifier(code, field_name="code")
        require_identifier(diagnostic_id, field_name="diagnostic_id")
        if not isinstance(summary, str) or not summary or len(summary) > 16_384:
            raise ValueError("summary must be non-empty and bounded")
        self.code = code
        self.diagnostic_id = diagnostic_id
        self.effect_certainty = "dispatch_in_doubt"
        self.mutation_applied = None
        self.fallback_performed = False
        self.reconcile_required = True
        super().__init__(
            f"{summary}; mutation_applied=unknown; fallback_performed=false; "
            "reconcile_required=true"
        )


class WorkspaceProvisionerPort(Protocol):
    """One exact selected workspace Adapter binding; never a provider selector."""

    provider_id: str
    adapter_binding_digest: str

    def provision(
        self,
        request: WorkspaceProvisioningRequest,
    ) -> WorkspaceProvisioningReceipt: ...

    def reconcile(
        self,
        request: WorkspaceProvisioningReconciliationRequest,
    ) -> WorkspaceProvisioningReceipt: ...


def validate_workspace_provisioner_identity(port: WorkspaceProvisionerPort) -> None:
    require_identifier(port.provider_id, field_name="provider_id")
    require_digest(port.adapter_binding_digest, field_name="adapter_binding_digest")


__all__ = [
    "WorkspaceProvisionerPort",
    "WorkspaceProvisionerPortError",
    "validate_workspace_provisioner_identity",
]
