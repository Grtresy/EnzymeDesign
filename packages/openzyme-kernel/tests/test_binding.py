from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace

import pytest

from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import TargetInventoryBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_kernel import CapabilityBindingAction
from openzyme_kernel import CapabilityBindingActorKind
from openzyme_kernel import CapabilityBindingCommand
from openzyme_kernel import KernelContractError
from openzyme_kernel import SessionCapabilityBindingService


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


@dataclass(slots=True)
class _MemoryBindingRepository:
    values: dict[str, list[SessionCapabilityBindingRevision]]

    def __init__(self) -> None:
        self.values = {}

    def latest(self, session_id: str) -> SessionCapabilityBindingRevision | None:
        values = self.values.get(session_id, [])
        return None if not values else values[-1]

    def append(
        self,
        binding: SessionCapabilityBindingRevision,
        *,
        expected_previous_revision: int | None,
    ) -> None:
        previous = self.latest(binding.session_id)
        observed = None if previous is None else previous.revision
        if observed != expected_previous_revision:
            raise AssertionError("repository CAS mismatch")
        self.values.setdefault(binding.session_id, []).append(binding)


def _inventory(target: str, generation: int) -> TargetInventoryBinding:
    return TargetInventoryBinding(
        target_id=target,
        inventory_generation=generation,
        inventory_digest=_digest(f"{target}:{generation}"),
        qualification_valid_until="2026-08-20T00:00:00Z",
    )


def _command(
    action: CapabilityBindingAction,
    *,
    actor_kind: CapabilityBindingActorKind = CapabilityBindingActorKind.OPERATOR,
    expected_previous_revision: int | None = None,
    inventory_bindings: tuple[TargetInventoryBinding, ...] = (),
    target_ids: tuple[str, ...] = (),
    binding_id: str = "binding-1",
) -> CapabilityBindingCommand:
    return CapabilityBindingCommand(
        command_id=f"command-{binding_id}",
        action=action,
        session_id="session-1",
        actor_id="operator-1",
        actor_kind=actor_kind,
        binding_id=binding_id,
        expected_previous_revision=expected_previous_revision,
        extension_bundle_digest=_digest("extensions"),
        route_catalog_digest=_digest("routes"),
        created_at="2026-08-19T00:00:00Z",
        inventory_bindings=inventory_bindings,
        target_ids=target_ids,
    )


def test_operator_publishes_then_adopts_monotonic_inventory_revision() -> None:
    repository = _MemoryBindingRepository()
    service = SessionCapabilityBindingService(repository)
    initial = service.execute(
        _command(
            CapabilityBindingAction.PUBLISH,
            inventory_bindings=(_inventory("hpc:primary", 7),),
        )
    )
    adopted = service.execute(
        _command(
            CapabilityBindingAction.ADOPT,
            expected_previous_revision=1,
            inventory_bindings=(_inventory("hpc:primary", 8),),
            binding_id="binding-2",
        )
    )

    assert initial.revision == 1
    assert adopted.revision == 2
    assert adopted.inventory_bindings[0].inventory_generation == 8
    assert repository.latest("session-1") is adopted


def test_agent_cannot_adopt_inventory_and_no_mutation_occurs() -> None:
    repository = _MemoryBindingRepository()
    service = SessionCapabilityBindingService(repository)

    with pytest.raises(KernelContractError) as forbidden:
        service.execute(
            _command(
                CapabilityBindingAction.PUBLISH,
                actor_kind=CapabilityBindingActorKind.AGENT,
            )
        )

    assert forbidden.value.code == "capability_binding_actor_forbidden"
    assert forbidden.value.mutation_applied is False
    assert repository.latest("session-1") is None


def test_binding_rejects_hot_swap_stale_revision_and_non_monotonic_inventory() -> None:
    repository = _MemoryBindingRepository()
    service = SessionCapabilityBindingService(repository)
    service.execute(
        _command(
            CapabilityBindingAction.PUBLISH,
            inventory_bindings=(_inventory("hpc:primary", 7),),
        )
    )

    with pytest.raises(KernelContractError) as stale:
        service.execute(
            _command(
                CapabilityBindingAction.ADOPT,
                expected_previous_revision=2,
                inventory_bindings=(_inventory("hpc:primary", 8),),
                binding_id="binding-stale",
            )
        )
    assert stale.value.code == "capability_binding_revision_conflict"

    with pytest.raises(KernelContractError) as generation:
        service.execute(
            _command(
                CapabilityBindingAction.ADOPT,
                expected_previous_revision=1,
                inventory_bindings=(_inventory("hpc:primary", 7),),
                binding_id="binding-generation",
            )
        )
    assert generation.value.code == "inventory_generation_not_monotonic"

    hot_swap = replace(
        _command(
            CapabilityBindingAction.ADOPT,
            expected_previous_revision=1,
            inventory_bindings=(_inventory("hpc:primary", 8),),
            binding_id="binding-hot-swap",
        ),
        extension_bundle_digest=_digest("other-extensions"),
    )
    with pytest.raises(KernelContractError) as forbidden:
        service.execute(hot_swap)
    assert forbidden.value.code == "session_composition_hot_swap_forbidden"
    assert repository.latest("session-1").revision == 1  # type: ignore[union-attr]


def test_revoke_creates_new_revision_without_deleting_history() -> None:
    repository = _MemoryBindingRepository()
    service = SessionCapabilityBindingService(repository)
    service.execute(
        _command(
            CapabilityBindingAction.PUBLISH,
            inventory_bindings=(
                _inventory("hpc:primary", 7),
                _inventory("hpc:secondary", 2),
            ),
        )
    )
    revoked = service.execute(
        _command(
            CapabilityBindingAction.REVOKE,
            expected_previous_revision=1,
            target_ids=("hpc:primary",),
            binding_id="binding-2",
        )
    )

    assert revoked.revision == 2
    assert tuple(item.target_id for item in revoked.inventory_bindings) == (
        "hpc:secondary",
    )
    assert len(repository.values["session-1"]) == 2
