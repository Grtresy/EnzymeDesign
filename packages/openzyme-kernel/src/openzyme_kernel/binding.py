from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import TargetInventoryBinding
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier

from .errors import KernelContractError


class CapabilityBindingActorKind(StrEnum):
    OPERATOR = "operator"
    ADMIN = "admin"
    AGENT = "agent"


class CapabilityBindingAction(StrEnum):
    PUBLISH = "publish"
    ADOPT = "adopt"
    REVOKE = "revoke"


@dataclass(frozen=True, slots=True)
class CapabilityBindingCommand:
    command_id: str
    action: CapabilityBindingAction
    session_id: str
    actor_id: str
    actor_kind: CapabilityBindingActorKind
    binding_id: str
    expected_previous_revision: int | None
    extension_bundle_digest: str
    route_catalog_digest: str
    created_at: str
    inventory_bindings: tuple[TargetInventoryBinding, ...] = ()
    target_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("command_id", "session_id", "actor_id", "binding_id"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(
            self.extension_bundle_digest,
            field_name="extension_bundle_digest",
        )
        require_digest(self.route_catalog_digest, field_name="route_catalog_digest")
        if self.expected_previous_revision is not None and (
            self.expected_previous_revision < 1
        ):
            raise ValueError("expected_previous_revision must be positive")
        target_ids = [binding.target_id for binding in self.inventory_bindings]
        if len(set(target_ids)) != len(target_ids):
            raise ValueError("inventory bindings must have unique target IDs")
        object.__setattr__(
            self,
            "inventory_bindings",
            tuple(sorted(self.inventory_bindings, key=lambda item: item.target_id)),
        )
        for target_id in self.target_ids:
            require_identifier(target_id, field_name="target_id")
        if len(set(self.target_ids)) != len(self.target_ids):
            raise ValueError("target_ids must be unique")
        object.__setattr__(self, "target_ids", tuple(sorted(self.target_ids)))
        if self.action is CapabilityBindingAction.PUBLISH:
            if self.expected_previous_revision is not None or self.target_ids:
                raise ValueError("publish creates the initial binding only")
        elif self.action is CapabilityBindingAction.ADOPT:
            if (
                self.expected_previous_revision is None
                or not self.inventory_bindings
                or self.target_ids
            ):
                raise ValueError("adopt requires prior revision and inventory bindings")
        elif (
            self.expected_previous_revision is None
            or self.inventory_bindings
            or not self.target_ids
        ):
            raise ValueError("revoke requires prior revision and target IDs")


class CapabilityBindingRepository(Protocol):
    def latest(
        self,
        session_id: str,
    ) -> SessionCapabilityBindingRevision | None: ...

    def append(
        self,
        binding: SessionCapabilityBindingRevision,
        *,
        expected_previous_revision: int | None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class SessionCapabilityBindingService:
    repository: CapabilityBindingRepository

    def execute(
        self,
        command: CapabilityBindingCommand,
    ) -> SessionCapabilityBindingRevision:
        if command.actor_kind not in {
            CapabilityBindingActorKind.OPERATOR,
            CapabilityBindingActorKind.ADMIN,
        }:
            raise KernelContractError(
                "capability_binding_actor_forbidden",
                "only an operator or admin may publish, adopt or revoke inventory bindings",
                details={
                    "session_id": command.session_id,
                    "actor_id": command.actor_id,
                    "action": command.action.value,
                },
            )
        previous = self.repository.latest(command.session_id)
        observed_revision = None if previous is None else previous.revision
        if observed_revision != command.expected_previous_revision:
            raise KernelContractError(
                "capability_binding_revision_conflict",
                "capability binding expected revision is stale",
                details={
                    "session_id": command.session_id,
                    "expected_previous_revision": command.expected_previous_revision,
                    "observed_previous_revision": observed_revision,
                },
            )
        if command.action is CapabilityBindingAction.PUBLISH:
            bindings = command.inventory_bindings
        else:
            if previous is None:
                raise KernelContractError(
                    "capability_binding_missing",
                    "the Session has no capability binding to update",
                    details={"session_id": command.session_id},
                )
            if (
                command.extension_bundle_digest
                != previous.extension_bundle_digest
                or command.route_catalog_digest != previous.route_catalog_digest
            ):
                raise KernelContractError(
                    "session_composition_hot_swap_forbidden",
                    "a Session capability binding cannot change its extension or route bundle",
                    details={"session_id": command.session_id},
                )
            current = {
                binding.target_id: binding
                for binding in previous.inventory_bindings
            }
            if command.action is CapabilityBindingAction.ADOPT:
                for binding in command.inventory_bindings:
                    old = current.get(binding.target_id)
                    if old is not None and (
                        binding.inventory_generation <= old.inventory_generation
                    ):
                        raise KernelContractError(
                            "inventory_generation_not_monotonic",
                            "adopted target inventory generation must increase",
                            details={
                                "target_id": binding.target_id,
                                "previous_generation": old.inventory_generation,
                                "requested_generation": binding.inventory_generation,
                            },
                        )
                    current[binding.target_id] = binding
            else:
                missing = sorted(set(command.target_ids).difference(current))
                if missing:
                    raise KernelContractError(
                        "inventory_binding_target_missing",
                        "cannot revoke a target absent from the current binding",
                        details={"target_ids": missing},
                    )
                for target_id in command.target_ids:
                    current.pop(target_id)
            bindings = tuple(current.values())

        binding = SessionCapabilityBindingRevision.create(
            binding_id=command.binding_id,
            session_id=command.session_id,
            revision=1 if previous is None else previous.revision + 1,
            extension_bundle_digest=command.extension_bundle_digest,
            route_catalog_digest=command.route_catalog_digest,
            inventory_bindings=bindings,
            created_by_actor_id=command.actor_id,
            created_at=command.created_at,
        )
        self.repository.append(
            binding,
            expected_previous_revision=command.expected_previous_revision,
        )
        return binding


__all__ = [
    "CapabilityBindingAction",
    "CapabilityBindingActorKind",
    "CapabilityBindingCommand",
    "CapabilityBindingRepository",
    "SessionCapabilityBindingService",
]
