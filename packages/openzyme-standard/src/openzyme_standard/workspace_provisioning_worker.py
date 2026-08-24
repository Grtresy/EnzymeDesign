"""Distribution-owned bounded driver for Kernel workspace provisioning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import ClockPort
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelRecordQueryPort
from openzyme_contracts import WorkspaceProvisioningIntent
from openzyme_contracts import WorkspaceProvisioningReconciliation
from openzyme_contracts import WorkspaceProvisioningReconciliationStatus
from openzyme_contracts import WorkspaceProvisioningStatus
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_kernel import KernelContractError
from openzyme_kernel import WorkspaceProvisioningWorker
from openzyme_kernel import WorkspaceProvisioningWorkerContext


@dataclass(frozen=True, slots=True)
class StandardWorkspaceProvisioningWorker:
    """Discover and advance only bounded intents within one exact Session."""

    worker: WorkspaceProvisioningWorker
    records: KernelRecordQueryPort
    clock: ClockPort
    ids: IdGeneratorPort
    worker_id: str = "openzyme-standard-workspace-provisioning-worker"
    claim_seconds: int = 300

    def __post_init__(self) -> None:
        if not self.worker_id:
            raise ValueError("workspace provisioning worker_id must be non-empty")
        if (
            not isinstance(self.claim_seconds, int)
            or isinstance(self.claim_seconds, bool)
            or self.claim_seconds < 1
        ):
            raise ValueError("workspace provisioning claim_seconds must be positive")

    def tick(
        self,
        *,
        session_id: str,
        maximum: int = 1,
    ) -> tuple[KernelMutationReceipt, ...]:
        if (
            not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or not 1 <= maximum <= 64
        ):
            raise ValueError("workspace provisioning maximum must be between 1 and 64")
        reconciliations = tuple(
            item
            for item in sorted(
                self.records.list_for_session(
                    entity_type="workspace_provisioning_reconciliation",
                    session_id=session_id,
                    max_items=128,
                ),
                key=lambda item: (
                    str(item.payload.get("created_at", "")),
                    item.entity_id,
                ),
            )
            if _reconciliation_claimable(item.payload, now=self.clock.now_iso())
        )[:maximum]
        receipts: list[KernelMutationReceipt] = []
        for snapshot in reconciliations:
            reconciliation = _reconciliation(snapshot.payload)
            context = self._context(
                session_id=session_id,
                intent_id=reconciliation.intent_id,
                idempotency_key=(
                    f"workspace-reconciliation-{reconciliation.reconciliation_id}"
                ),
                correlation_id=reconciliation.reconciliation_id,
                requested_by_actor_id=None,
            )
            receipts.append(
                self.worker.run(
                    context=context,
                    intent_id=reconciliation.intent_id,
                    expected_intent_version=(
                        reconciliation.blocked_intent_state_version
                    ),
                    claim_seconds=reconciliation.requested_claim_seconds,
                    reconcile=True,
                )
            )
        remaining = maximum - len(receipts)
        if remaining == 0:
            return tuple(receipts)
        intents = tuple(
            item
            for item in sorted(
                self.records.list_for_session(
                    entity_type="workspace_provisioning_intent",
                    session_id=session_id,
                    max_items=128,
                ),
                key=lambda item: (
                    str(item.payload.get("created_at", "")),
                    item.entity_id,
                ),
            )
            if _claimable(item.payload, now=self.clock.now_iso())
        )[:remaining]
        for snapshot in intents:
            context = self._context(
                session_id=session_id,
                intent_id=snapshot.entity_id,
                idempotency_key=f"workspace-provisioning-{snapshot.entity_id}",
                correlation_id=snapshot.entity_id,
                requested_by_actor_id=None,
            )
            receipts.append(
                self.worker.run(
                    context=context,
                    intent_id=snapshot.entity_id,
                    expected_intent_version=snapshot.state_version,
                    claim_seconds=self.claim_seconds,
                )
            )
        return tuple(receipts)

    def admit_reconciliation(
        self,
        *,
        session_id: str,
        intent_id: str,
        intent_digest: str,
        expected_intent_version: int,
        claim_seconds: int,
        requested_by_actor_id: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> KernelMutationReceipt:
        """Admit one durable observation occurrence without Adapter invocation."""

        for field_name, value in (
            ("session_id", session_id),
            ("intent_id", intent_id),
            ("requested_by_actor_id", requested_by_actor_id),
            ("idempotency_key", idempotency_key),
            ("correlation_id", correlation_id),
        ):
            require_identifier(value, field_name=field_name)
        require_digest(intent_digest, field_name="intent_digest")
        if (
            not isinstance(expected_intent_version, int)
            or isinstance(expected_intent_version, bool)
            or expected_intent_version < 1
            or not isinstance(claim_seconds, int)
            or isinstance(claim_seconds, bool)
            or not 1 <= claim_seconds <= 86_400
        ):
            raise ValueError(
                "workspace reconciliation version/claim bounds are invalid"
            )
        self._require_current_intent(
            session_id=session_id,
            intent_id=intent_id,
            intent_digest=intent_digest,
            expected_intent_version=expected_intent_version,
        )
        return self.worker.admit_reconciliation(
            context=self._context(
                session_id=session_id,
                intent_id=intent_id,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                requested_by_actor_id=requested_by_actor_id,
            ),
            intent_id=intent_id,
            expected_intent_version=expected_intent_version,
            claim_seconds=claim_seconds,
        )

    def create_successor(
        self,
        *,
        session_id: str,
        failed_intent_id: str,
        failed_intent_digest: str,
        expected_failed_intent_version: int,
        resolved_reconciliation_id: str | None,
        requested_by_actor_id: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> KernelMutationReceipt:
        """Create one explicit successor graph without provisioning or retry."""

        for field_name, value in (
            ("session_id", session_id),
            ("failed_intent_id", failed_intent_id),
            ("requested_by_actor_id", requested_by_actor_id),
            ("idempotency_key", idempotency_key),
            ("correlation_id", correlation_id),
        ):
            require_identifier(value, field_name=field_name)
        require_digest(
            failed_intent_digest,
            field_name="failed_intent_digest",
        )
        if resolved_reconciliation_id is not None:
            require_identifier(
                resolved_reconciliation_id,
                field_name="resolved_reconciliation_id",
            )
        if (
            not isinstance(expected_failed_intent_version, int)
            or isinstance(expected_failed_intent_version, bool)
            or expected_failed_intent_version < 1
        ):
            raise ValueError("expected_failed_intent_version must be positive")
        self._require_current_intent(
            session_id=session_id,
            intent_id=failed_intent_id,
            intent_digest=failed_intent_digest,
            expected_intent_version=expected_failed_intent_version,
        )
        return self.worker.replace_failed_generation(
            context=self._context(
                session_id=session_id,
                intent_id=failed_intent_id,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                requested_by_actor_id=requested_by_actor_id,
            ),
            failed_intent_id=failed_intent_id,
            expected_failed_intent_version=expected_failed_intent_version,
            resolved_reconciliation_id=resolved_reconciliation_id,
        )

    def _require_current_intent(
        self,
        *,
        session_id: str,
        intent_id: str,
        intent_digest: str,
        expected_intent_version: int,
    ) -> WorkspaceProvisioningIntent:
        snapshot = self.records.read(
            entity_type="workspace_provisioning_intent",
            entity_id=intent_id,
        )
        if snapshot is None:
            raise KernelContractError(
                "workspace_provisioning_intent_not_found",
                "Workspace operation requires one canonical provisioning intent",
            )
        try:
            intent = WorkspaceProvisioningIntent.from_dict(snapshot.payload)
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "workspace_provisioning_intent_invalid",
                "Workspace operation requires one valid canonical provisioning intent",
            ) from exc
        if intent.intent_id != intent_id or intent.session_id != session_id:
            raise KernelContractError(
                "workspace_provisioning_session_mismatch",
                "Provisioning occurrence belongs to another Session",
            )
        if (
            snapshot.state_version != expected_intent_version
            or intent.state_version != snapshot.state_version
            or intent.intent_digest != intent_digest
        ):
            raise KernelContractError(
                "workspace_provisioning_intent_stale",
                "Provisioning occurrence identity, digest or version is stale",
            )
        return intent

    def _context(
        self,
        *,
        session_id: str,
        intent_id: str,
        idempotency_key: str,
        correlation_id: str,
        requested_by_actor_id: str | None,
    ) -> WorkspaceProvisioningWorkerContext:
        session = self.records.read(entity_type="session", entity_id=session_id)
        members = self.records.list_for_session(
            entity_type="agent_member",
            session_id=session_id,
            max_items=64,
        )
        roots = tuple(
            item
            for item in members
            if item.payload.get("role") == "master"
            and item.payload.get("parent_agent_id") is None
            and item.payload.get("status") == "active"
        )
        if session is None or len(roots) != 1:
            raise KernelContractError(
                "workspace_provisioning_root_identity_missing",
                "Provisioning worker requires one canonical Session root Agent",
            )
        lease_id = roots[0].payload.get("active_authority_lease_id")
        lease_record = (
            None
            if not isinstance(lease_id, str)
            else self.records.read(
                entity_type="agent_authority_lease",
                entity_id=lease_id,
            )
        )
        try:
            if lease_record is None:
                raise ValueError("missing")
            lease = AgentAuthorityLease.from_dict(lease_record.payload)
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "workspace_provisioning_root_authority_invalid",
                "Provisioning worker requires the pending exact-generation root lease",
            ) from exc
        return WorkspaceProvisioningWorkerContext(
            command_id=self.ids.new_id(namespace="workspace-provisioning-command"),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            session_id=session_id,
            worker_id=self.worker_id,
            worker_authority_id=lease.lease_id,
            worker_authority_generation=lease.generation,
            worker_authority_fence=lease.fence,
            expected_session_version=session.state_version,
            requested_by_actor_id=requested_by_actor_id,
        )


def _claimable(payload, *, now: str) -> bool:  # noqa: ANN001
    try:
        intent = WorkspaceProvisioningIntent.from_dict(payload)
    except (TypeError, ValueError) as exc:
        raise KernelContractError(
            "workspace_provisioning_intent_invalid",
            "Provisioning worker encountered an invalid canonical intent",
        ) from exc
    if intent.status is WorkspaceProvisioningStatus.PENDING:
        return True
    return bool(
        intent.status is WorkspaceProvisioningStatus.CLAIMED
        and intent.claim_expires_at is not None
        and _instant(intent.claim_expires_at) <= _instant(now)
    )


def _reconciliation(payload) -> WorkspaceProvisioningReconciliation:  # noqa: ANN001
    try:
        return WorkspaceProvisioningReconciliation.from_dict(payload)
    except (TypeError, ValueError) as exc:
        raise KernelContractError(
            "workspace_provisioning_reconciliation_invalid",
            "Provisioning worker encountered an invalid reconciliation occurrence",
        ) from exc


def _reconciliation_claimable(payload, *, now: str) -> bool:  # noqa: ANN001
    reconciliation = _reconciliation(payload)
    if reconciliation.status is WorkspaceProvisioningReconciliationStatus.PENDING:
        return True
    return bool(
        reconciliation.status is WorkspaceProvisioningReconciliationStatus.CLAIMED
        and reconciliation.claim_expires_at is not None
        and _instant(reconciliation.claim_expires_at) <= _instant(now)
    )


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("workspace provisioning instant requires a timezone")
    return parsed


__all__ = ["StandardWorkspaceProvisioningWorker"]
