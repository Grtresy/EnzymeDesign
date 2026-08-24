"""Distribution-owned bounded entrypoint for asynchronous workspace provisioning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
class EnzymeDesignWorkspaceProvisioningWorkerAuthority:
    worker_id: str
    authority_id: str
    generation: int
    fence: int

    def __post_init__(self) -> None:
        require_identifier(self.worker_id, field_name="worker_id")
        require_identifier(self.authority_id, field_name="authority_id")
        if any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 1
            for value in (self.generation, self.fence)
        ):
            raise ValueError("workspace provisioning worker fences must be positive")


@dataclass(slots=True)
class EnzymeDesignWorkspaceProvisioningRunner:
    """Run one exact intent outside HTTP with explicit claim and retry policy."""

    worker: WorkspaceProvisioningWorker
    records: KernelRecordQueryPort
    authority: EnzymeDesignWorkspaceProvisioningWorkerAuthority
    ids: IdGeneratorPort

    def run(
        self,
        *,
        intent_id: str,
        expected_intent_version: int,
        claim_seconds: int,
    ) -> KernelMutationReceipt:
        """Provision one exact pending intent outside the delivery request."""

        return self._run(
            intent_id=intent_id,
            expected_intent_digest=None,
            expected_intent_version=expected_intent_version,
            claim_seconds=claim_seconds,
            expected_session_id=None,
            idempotency_key=None,
            correlation_id=None,
            requested_by_actor_id=None,
            reconcile=False,
        )

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
        """Admit one exact observation occurrence without invoking an Adapter."""

        require_identifier(session_id, field_name="session_id")
        require_digest(intent_digest, field_name="intent_digest")
        require_identifier(
            requested_by_actor_id,
            field_name="requested_by_actor_id",
        )
        require_identifier(idempotency_key, field_name="idempotency_key")
        require_identifier(correlation_id, field_name="correlation_id")
        intent, session_version = self._require_current_intent(
            intent_id=intent_id,
            expected_intent_digest=intent_digest,
            expected_intent_version=expected_intent_version,
            expected_session_id=session_id,
        )
        return self.worker.admit_reconciliation(
            context=self._context(
                session_id=intent.session_id,
                session_state_version=session_version,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                requested_by_actor_id=requested_by_actor_id,
            ),
            intent_id=intent.intent_id,
            expected_intent_version=expected_intent_version,
            claim_seconds=claim_seconds,
        )

    def run_admitted_reconciliation(
        self,
        reconciliation: WorkspaceProvisioningReconciliation,
    ) -> KernelMutationReceipt:
        """Claim and observe one already-admitted durable occurrence."""

        return self._run(
            intent_id=reconciliation.intent_id,
            expected_intent_digest=reconciliation.blocked_intent_digest,
            expected_intent_version=(
                reconciliation.blocked_intent_state_version
            ),
            claim_seconds=reconciliation.requested_claim_seconds,
            expected_session_id=reconciliation.session_id,
            idempotency_key=(
                f"workspace-reconciliation-{reconciliation.reconciliation_id}"
            ),
            correlation_id=reconciliation.reconciliation_id,
            requested_by_actor_id=None,
            reconcile=True,
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
        """Create one pending monotonic successor without invoking an Adapter."""

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
        snapshot = self.records.read(
            entity_type="workspace_provisioning_intent",
            entity_id=failed_intent_id,
        )
        if snapshot is None:
            raise KernelContractError(
                "workspace_provisioning_intent_not_found",
                "EnzymeDesign successor admission requires one exact failed intent",
            )
        try:
            failed = WorkspaceProvisioningIntent.from_dict(snapshot.payload)
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "workspace_provisioning_intent_invalid",
                "EnzymeDesign failed intent violates its closed contract",
            ) from exc
        if (
            failed.intent_id != snapshot.entity_id
            or failed.state_version != snapshot.state_version
        ):
            raise KernelContractError(
                "workspace_provisioning_intent_record_drift",
                "Failed intent identity/version differs from its record envelope",
            )
        if snapshot.state_version != expected_failed_intent_version:
            raise KernelContractError(
                "workspace_provisioning_intent_stale",
                "Failed intent changed before successor admission",
            )
        if failed.session_id != session_id:
            raise KernelContractError(
                "workspace_provisioning_intent_session_mismatch",
                "Failed intent belongs to another Session",
            )
        if failed.intent_digest != failed_intent_digest:
            raise KernelContractError(
                "workspace_provisioning_intent_digest_mismatch",
                "Failed intent digest changed before successor admission",
            )
        session = self.records.read(entity_type="session", entity_id=session_id)
        if session is None:
            raise KernelContractError(
                "session_not_found",
                "Failed provisioning intent Session is absent",
            )
        return self.worker.replace_failed_generation(
            context=self._context(
                session_id=session_id,
                session_state_version=session.state_version,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                requested_by_actor_id=requested_by_actor_id,
            ),
            failed_intent_id=failed_intent_id,
            expected_failed_intent_version=expected_failed_intent_version,
            resolved_reconciliation_id=resolved_reconciliation_id,
        )

    def _run(
        self,
        *,
        intent_id: str,
        expected_intent_digest: str | None,
        expected_intent_version: int,
        claim_seconds: int,
        expected_session_id: str | None,
        idempotency_key: str | None,
        correlation_id: str | None,
        requested_by_actor_id: str | None,
        reconcile: bool,
    ) -> KernelMutationReceipt:
        require_identifier(intent_id, field_name="intent_id")
        if (
            not isinstance(expected_intent_version, int)
            or isinstance(expected_intent_version, bool)
            or expected_intent_version < 1
        ):
            raise ValueError("expected_intent_version must be positive")
        intent, session_version = self._require_current_intent(
            intent_id=intent_id,
            expected_intent_digest=expected_intent_digest,
            expected_intent_version=expected_intent_version,
            expected_session_id=expected_session_id,
        )
        if (
            not isinstance(claim_seconds, int)
            or isinstance(claim_seconds, bool)
            or not 1 <= claim_seconds <= 86_400
        ):
            raise ValueError("claim_seconds must be between 1 and 86400")
        mode = "reconcile" if reconcile else "provision"
        resolved_idempotency_key = (
            idempotency_key
            if idempotency_key is not None
            else f"workspace-{mode}-{intent.intent_id}-v{expected_intent_version}"
        )
        resolved_correlation_id = (
            correlation_id if correlation_id is not None else intent.intent_id
        )
        return self.worker.run(
            context=self._context(
                session_id=intent.session_id,
                session_state_version=session_version,
                idempotency_key=resolved_idempotency_key,
                correlation_id=resolved_correlation_id,
                requested_by_actor_id=requested_by_actor_id,
            ),
            intent_id=intent.intent_id,
            expected_intent_version=expected_intent_version,
            claim_seconds=claim_seconds,
            reconcile=reconcile,
        )

    def _require_current_intent(
        self,
        *,
        intent_id: str,
        expected_intent_digest: str | None,
        expected_intent_version: int,
        expected_session_id: str | None,
    ) -> tuple[WorkspaceProvisioningIntent, int]:
        require_identifier(intent_id, field_name="intent_id")
        if (
            not isinstance(expected_intent_version, int)
            or isinstance(expected_intent_version, bool)
            or expected_intent_version < 1
        ):
            raise ValueError("expected_intent_version must be positive")
        snapshot = self.records.read(
            entity_type="workspace_provisioning_intent",
            entity_id=intent_id,
        )
        if snapshot is None:
            raise KernelContractError(
                "workspace_provisioning_intent_not_found",
                "EnzymeDesign provisioning runner requires one exact durable intent",
            )
        try:
            intent = WorkspaceProvisioningIntent.from_dict(snapshot.payload)
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "workspace_provisioning_intent_invalid",
                "EnzymeDesign provisioning intent violates its closed contract",
            ) from exc
        if (
            intent.intent_id != snapshot.entity_id
            or intent.state_version != snapshot.state_version
        ):
            raise KernelContractError(
                "workspace_provisioning_intent_record_drift",
                "Provisioning intent identity/version differs from its record envelope",
            )
        if expected_intent_version != snapshot.state_version:
            raise KernelContractError(
                "workspace_provisioning_intent_stale",
                "Provisioning intent changed before bounded worker admission",
            )
        if (
            expected_session_id is not None
            and intent.session_id != expected_session_id
        ):
            raise KernelContractError(
                "workspace_provisioning_intent_session_mismatch",
                "Provisioning reconciliation intent belongs to another Session",
            )
        if (
            expected_intent_digest is not None
            and intent.intent_digest != expected_intent_digest
        ):
            raise KernelContractError(
                "workspace_provisioning_intent_digest_mismatch",
                "Provisioning reconciliation intent digest changed before admission",
            )
        session = self.records.read(
            entity_type="session",
            entity_id=intent.session_id,
        )
        if session is None:
            raise KernelContractError(
                "session_not_found",
                "Provisioning intent Session is absent",
            )
        return intent, session.state_version

    def _context(
        self,
        *,
        session_id: str,
        session_state_version: int,
        idempotency_key: str,
        correlation_id: str,
        requested_by_actor_id: str | None,
    ) -> WorkspaceProvisioningWorkerContext:
        return WorkspaceProvisioningWorkerContext(
            command_id=self.ids.new_id(namespace="command"),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            session_id=session_id,
            worker_id=self.authority.worker_id,
            worker_authority_id=self.authority.authority_id,
            worker_authority_generation=self.authority.generation,
            worker_authority_fence=self.authority.fence,
            expected_session_version=session_state_version,
            requested_by_actor_id=requested_by_actor_id,
        )


@dataclass(frozen=True, slots=True)
class EnzymeDesignWorkspaceProvisioningLifecycleWorker:
    """Bounded scanner for durable provisioning and reconciliation work."""

    runner: EnzymeDesignWorkspaceProvisioningRunner
    records: KernelRecordQueryPort
    clock: ClockPort
    claim_seconds: int = 300

    def __post_init__(self) -> None:
        _require_claim_seconds(self.claim_seconds)

    def tick(
        self,
        *,
        session_id: str,
        maximum: int = 1,
    ) -> tuple[KernelMutationReceipt, ...]:
        require_identifier(session_id, field_name="session_id")
        if (
            not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or not 1 <= maximum <= 64
        ):
            raise ValueError("workspace provisioning maximum must be between 1 and 64")
        now = self.clock.now_iso()
        reconciliations = tuple(
            reconciliation
            for reconciliation in (
                _reconciliation(item.payload)
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
            )
            if _reconciliation_claimable(reconciliation, now=now)
        )[:maximum]
        receipts = [
            self.runner.run_admitted_reconciliation(reconciliation)
            for reconciliation in reconciliations
        ]
        remaining = maximum - len(receipts)
        if remaining == 0:
            return tuple(receipts)
        intents = tuple(
            snapshot
            for snapshot in sorted(
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
            if _intent_claimable(snapshot.payload, now=now)
        )[:remaining]
        receipts.extend(
            self.runner.run(
                intent_id=snapshot.entity_id,
                expected_intent_version=snapshot.state_version,
                claim_seconds=self.claim_seconds,
            )
            for snapshot in intents
        )
        return tuple(receipts)


def _require_claim_seconds(value: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= 86_400
    ):
        raise ValueError("claim_seconds must be between 1 and 86400")


def _intent_claimable(payload: object, *, now: str) -> bool:
    try:
        intent = WorkspaceProvisioningIntent.from_dict(payload)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise KernelContractError(
            "workspace_provisioning_intent_invalid",
            "Provisioning lifecycle encountered an invalid canonical intent",
        ) from exc
    if intent.status is WorkspaceProvisioningStatus.PENDING:
        return True
    return bool(
        intent.status is WorkspaceProvisioningStatus.CLAIMED
        and intent.claim_expires_at is not None
        and _instant(intent.claim_expires_at) <= _instant(now)
    )


def _reconciliation(payload: object) -> WorkspaceProvisioningReconciliation:
    try:
        return WorkspaceProvisioningReconciliation.from_dict(  # type: ignore[arg-type]
            payload
        )
    except (TypeError, ValueError) as exc:
        raise KernelContractError(
            "workspace_provisioning_reconciliation_invalid",
            "Provisioning lifecycle encountered an invalid reconciliation occurrence",
        ) from exc


def _reconciliation_claimable(
    reconciliation: WorkspaceProvisioningReconciliation,
    *,
    now: str,
) -> bool:
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


__all__ = [
    "EnzymeDesignWorkspaceProvisioningLifecycleWorker",
    "EnzymeDesignWorkspaceProvisioningRunner",
    "EnzymeDesignWorkspaceProvisioningWorkerAuthority",
]
