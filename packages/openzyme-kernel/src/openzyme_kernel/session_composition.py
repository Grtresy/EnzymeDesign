from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from typing import Protocol
from typing import TypeVar

from openzyme_contracts import DeploymentActivationEpoch
from openzyme_contracts import Session
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import SessionCompositionPin
from openzyme_contracts import TargetInventoryBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_identifier

from .deployment_activation import DeploymentActivationGate
from .deployment_activation import DeploymentSurface
from .errors import KernelContractError


SESSION_COMPOSITION_GUARD_DECISION_SCHEMA_VERSION = (
    "openzyme_session_composition_guard_decision@1"
)


class SessionCompositionSurface(StrEnum):
    SAFE_INSPECTION = "safe_inspection"
    MESSAGE = "message"
    RUNTIME_DRAIN = "runtime_drain"
    APPROVAL_RESOLUTION = "approval_resolution"
    TOOL_INVOCATION = "tool_invocation"
    WORKSPACE_MUTATION = "workspace_mutation"
    PUBLICATION = "publication"
    CONTROLLED_OPERATION = "controlled_operation"
    RESTORE = "restore"


class SessionCompositionGuardState(StrEnum):
    ALLOWED = "allowed"
    UPGRADE_REQUIRED = "upgrade_required"


@dataclass(frozen=True, slots=True)
class SessionCompositionGuardDecision:
    session_id: str
    surface: SessionCompositionSurface
    state: SessionCompositionGuardState
    drifted_fields: tuple[str, ...]
    active_composition_bundle_digest: str | None
    pinned_composition_bundle_digest: str | None
    capability_binding_digest: str | None
    mutation_applied: bool = False
    fallback_performed: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.session_id, field_name="session_id")
        if self.state is SessionCompositionGuardState.ALLOWED and self.drifted_fields:
            raise ValueError("allowed composition decision cannot contain drift")
        if (
            self.state is SessionCompositionGuardState.UPGRADE_REQUIRED
            and not self.drifted_fields
        ):
            raise ValueError("upgrade-required decision must explain bounded drift")
        if self.mutation_applied or self.fallback_performed:
            raise ValueError("composition guard must never mutate or perform fallback")
        object.__setattr__(self, "drifted_fields", tuple(sorted(self.drifted_fields)))

    @property
    def decision_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SESSION_COMPOSITION_GUARD_DECISION_SCHEMA_VERSION,
            "session_id": self.session_id,
            "surface": self.surface.value,
            "state": self.state.value,
            "drifted_fields": list(self.drifted_fields),
            "active_composition_bundle_digest": (
                self.active_composition_bundle_digest
            ),
            "pinned_composition_bundle_digest": (
                self.pinned_composition_bundle_digest
            ),
            "capability_binding_digest": self.capability_binding_digest,
            "mutation_applied": self.mutation_applied,
            "fallback_performed": self.fallback_performed,
        }


class SessionCompositionRepository(Protocol):
    """Atomic Session + pin + initial binding persistence boundary."""

    def create_session_with_composition(
        self,
        *,
        session: Session,
        pin: SessionCompositionPin,
        initial_capability_binding: SessionCapabilityBindingRevision,
    ) -> None: ...

    def get_pin(self, session_id: str) -> SessionCompositionPin | None: ...

    def latest_capability_binding(
        self,
        session_id: str,
    ) -> SessionCapabilityBindingRevision | None: ...


@dataclass(frozen=True, slots=True)
class SessionCompositionCreateCommand:
    session: Session
    pin_id: str
    capability_binding_id: str
    inventory_bindings: tuple[TargetInventoryBinding, ...]
    actor_id: str
    created_at: str

    def __post_init__(self) -> None:
        for field_name in ("pin_id", "capability_binding_id", "actor_id"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if not isinstance(self.created_at, str) or not self.created_at:
            raise ValueError("created_at must be a non-empty instant")


@dataclass(frozen=True, slots=True)
class SessionCompositionService:
    gate: DeploymentActivationGate
    repository: SessionCompositionRepository

    def create(
        self,
        command: SessionCompositionCreateCommand,
    ) -> tuple[SessionCompositionPin, SessionCapabilityBindingRevision]:
        authorization = self.gate.require_active(
            DeploymentSurface.REPOSITORY_WRITER
        )
        epoch = self.gate.validate_authorization(
            authorization,
            surface=DeploymentSurface.REPOSITORY_WRITER,
        )
        binding = SessionCapabilityBindingRevision.create(
            binding_id=command.capability_binding_id,
            session_id=command.session.session_id,
            revision=1,
            extension_bundle_digest=epoch.release_identity.extension_bundle_digest,
            route_catalog_digest=epoch.release_identity.route_catalog_digest,
            inventory_bindings=command.inventory_bindings,
            created_by_actor_id=command.actor_id,
            created_at=command.created_at,
        )
        pin = SessionCompositionPin.create(
            pin_id=command.pin_id,
            session_id=command.session.session_id,
            deployment_epoch=epoch,
            initial_capability_binding_id=binding.binding_id,
            initial_capability_binding_revision=binding.revision,
            initial_capability_binding_digest=binding.binding_digest,
            created_by_actor_id=command.actor_id,
            created_at=command.created_at,
        )
        self.repository.create_session_with_composition(
            session=command.session,
            pin=pin,
            initial_capability_binding=binding,
        )
        return pin, binding


@dataclass(frozen=True, slots=True)
class SessionCompositionGuard:
    gate: DeploymentActivationGate

    def inspect(
        self,
        *,
        session_id: str,
        surface: SessionCompositionSurface,
        pin: SessionCompositionPin | None,
        capability_binding: SessionCapabilityBindingRevision | None,
    ) -> SessionCompositionGuardDecision:
        active = self.gate.active_epoch
        drifted: list[str] = []
        if active is None:
            drifted.append("deployment_activation")
        if pin is None:
            drifted.append("session_composition_pin")
        elif not pin.has_valid_digest():
            drifted.append("session_composition_pin_digest")
        else:
            if pin.session_id != session_id:
                drifted.append("pin_session")
            if active is not None:
                drifted.extend(_epoch_pin_drift(active, pin))
        if capability_binding is None:
            drifted.append("capability_binding")
        elif not capability_binding.has_valid_digest():
            drifted.append("capability_binding_digest")
        else:
            if capability_binding.session_id != session_id:
                drifted.append("capability_binding_session")
            if pin is not None:
                if (
                    capability_binding.extension_bundle_digest
                    != pin.release_identity.extension_bundle_digest
                ):
                    drifted.append("capability_binding_extension_bundle")
                if (
                    capability_binding.route_catalog_digest
                    != pin.release_identity.route_catalog_digest
                ):
                    drifted.append("capability_binding_route_catalog")
                if (
                    capability_binding.revision
                    < pin.initial_capability_binding_revision
                ):
                    drifted.append("capability_binding_revision")

        state = (
            SessionCompositionGuardState.ALLOWED
            if not drifted
            else SessionCompositionGuardState.UPGRADE_REQUIRED
        )
        return SessionCompositionGuardDecision(
            session_id=session_id,
            surface=surface,
            state=state,
            drifted_fields=tuple(set(drifted)),
            active_composition_bundle_digest=(
                None if active is None else active.composition_bundle_digest
            ),
            pinned_composition_bundle_digest=(
                None if pin is None else pin.composition_bundle_digest
            ),
            capability_binding_digest=(
                None
                if capability_binding is None
                else capability_binding.binding_digest
            ),
        )

    def require(
        self,
        *,
        session_id: str,
        surface: SessionCompositionSurface,
        pin: SessionCompositionPin | None,
        capability_binding: SessionCapabilityBindingRevision | None,
    ) -> SessionCompositionGuardDecision:
        decision = self.inspect(
            session_id=session_id,
            surface=surface,
            pin=pin,
            capability_binding=capability_binding,
        )
        if decision.state is SessionCompositionGuardState.UPGRADE_REQUIRED:
            raise KernelContractError(
                "session_composition_upgrade_required",
                "Session composition differs from the active deployment",
                details={
                    "session_id": session_id,
                    "surface": surface.value,
                    "drifted_fields": list(decision.drifted_fields),
                    "decision_digest": decision.decision_digest,
                },
            )
        return decision


_T = TypeVar("_T")


def execute_guarded_session_operation(
    guard: SessionCompositionGuard,
    *,
    session_id: str,
    surface: SessionCompositionSurface,
    pin: SessionCompositionPin | None,
    capability_binding: SessionCapabilityBindingRevision | None,
    operation: Callable[[], _T],
) -> _T:
    """Common entrypoint wrapper; callback is unreachable under any pin drift."""

    if surface is SessionCompositionSurface.SAFE_INSPECTION:
        raise ValueError("safe inspection is a query and cannot execute an operation")
    guard.require(
        session_id=session_id,
        surface=surface,
        pin=pin,
        capability_binding=capability_binding,
    )
    return operation()


def _epoch_pin_drift(
    epoch: DeploymentActivationEpoch,
    pin: SessionCompositionPin,
) -> list[str]:
    mismatches = {
        "distribution": pin.distribution_id != epoch.distribution_id,
        "composition_bundle": (
            pin.composition_bundle_digest != epoch.composition_bundle_digest
        ),
        "release_identity": (
            pin.release_identity.release_digest
            != epoch.release_identity.release_digest
        ),
        "driver_bundle": pin.driver_bundle_digest != epoch.driver_bundle_digest,
        "http_route_catalog": (
            pin.http_route_catalog_digest != epoch.http_route_catalog_digest
        ),
        "contribution_catalogs": (
            pin.contribution_catalogs_digest != epoch.contribution_catalogs_digest
        ),
        "deployment_activation": (
            pin.deployment_activation_digest != epoch.activation_digest
            and pin.composition_bundle_digest != epoch.composition_bundle_digest
        ),
    }
    return sorted(field for field, mismatch in mismatches.items() if mismatch)


__all__ = [
    "SESSION_COMPOSITION_GUARD_DECISION_SCHEMA_VERSION",
    "SessionCompositionCreateCommand",
    "SessionCompositionGuard",
    "SessionCompositionGuardDecision",
    "SessionCompositionGuardState",
    "SessionCompositionRepository",
    "SessionCompositionService",
    "SessionCompositionSurface",
    "execute_guarded_session_operation",
]
