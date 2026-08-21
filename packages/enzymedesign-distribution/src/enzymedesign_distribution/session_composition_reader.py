from __future__ import annotations

from dataclasses import dataclass

from openzyme_contracts import KernelRecordQueryPort
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import SessionCompositionPin
from openzyme_kernel import KernelContractError


@dataclass(frozen=True, slots=True)
class EnzymeDesignSessionCompositionReader:
    """Read exact Session pins/bindings from the selected Control Store."""

    records: KernelRecordQueryPort

    def get_pin(self, session_id: str) -> SessionCompositionPin | None:
        records = self.records.list_for_session(
            entity_type="session_composition_pin",
            session_id=session_id,
            max_items=2,
        )
        if not records:
            return None
        if len(records) != 1:
            raise KernelContractError(
                "session_composition_pin_ambiguous",
                "Session has more than one canonical composition pin",
                details={"session_id": session_id, "count": len(records)},
            )
        try:
            pin = SessionCompositionPin.from_dict(records[0].payload)
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "session_composition_pin_invalid",
                "Session composition pin violates its closed contract",
                details={"session_id": session_id},
            ) from exc
        if pin.session_id != session_id:
            raise KernelContractError(
                "session_composition_pin_session_mismatch",
                "Session composition pin belongs to another Session",
                details={"session_id": session_id},
            )
        return pin

    def latest_capability_binding(
        self,
        session_id: str,
    ) -> SessionCapabilityBindingRevision | None:
        records = self.records.list_for_session(
            entity_type="session_capability_binding_revision",
            session_id=session_id,
            max_items=64,
        )
        if not records:
            return None
        try:
            bindings = tuple(
                SessionCapabilityBindingRevision.from_dict(record.payload)
                for record in records
            )
        except (TypeError, ValueError) as exc:
            raise KernelContractError(
                "session_capability_binding_invalid",
                "Session capability binding violates its closed contract",
                details={"session_id": session_id},
            ) from exc
        latest_revision = max(binding.revision for binding in bindings)
        latest = tuple(
            binding for binding in bindings if binding.revision == latest_revision
        )
        if len(latest) != 1 or latest[0].session_id != session_id:
            raise KernelContractError(
                "session_capability_binding_ambiguous",
                "Latest Session capability binding is absent or ambiguous",
                details={
                    "session_id": session_id,
                    "latest_revision": latest_revision,
                    "count": len(latest),
                },
            )
        return latest[0]


__all__ = ["EnzymeDesignSessionCompositionReader"]
