from __future__ import annotations

from dataclasses import dataclass

import pytest

from openzyme_contracts import Session
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_kernel import DeploymentActivationGate
from openzyme_kernel import KernelContractError
from openzyme_kernel import SessionCompositionCreateCommand
from openzyme_kernel import SessionCompositionGuard
from openzyme_kernel import SessionCompositionGuardState
from openzyme_kernel import SessionCompositionService
from openzyme_kernel import SessionCompositionSurface
from openzyme_kernel import execute_guarded_session_operation

from composition_test_support import activate_gate
from composition_test_support import activated_composition
from composition_test_support import digest


@dataclass
class MemorySessionCompositionRepository:
    create_calls: int = 0
    session: Session | None = None
    pin: object | None = None
    binding: SessionCapabilityBindingRevision | None = None

    def create_session_with_composition(
        self,
        *,
        session: Session,
        pin: object,
        initial_capability_binding: SessionCapabilityBindingRevision,
    ) -> None:
        if self.create_calls:
            raise AssertionError("test repository only supports one atomic create")
        self.create_calls += 1
        self.session = session
        self.pin = pin
        self.binding = initial_capability_binding

    def get_pin(self, session_id: str) -> object | None:
        return self.pin if self.session and self.session.session_id == session_id else None

    def latest_capability_binding(
        self,
        session_id: str,
    ) -> SessionCapabilityBindingRevision | None:
        return (
            self.binding
            if self.session and self.session.session_id == session_id
            else None
        )


def _command() -> SessionCompositionCreateCommand:
    return SessionCompositionCreateCommand(
        session=Session.create(
            "session-1",
            "project-1",
            "Test session",
            "Prove exact composition pinning.",
        ),
        pin_id="pin-1",
        capability_binding_id="binding-1",
        inventory_bindings=(),
        actor_id="operator-1",
        created_at="2026-08-19T02:00:00+00:00",
    )


def _create_pinned_session() -> tuple:
    composition, release, _ = activated_composition()
    gate, epoch = activate_gate(composition, release)
    repository = MemorySessionCompositionRepository()
    pin, binding = SessionCompositionService(gate, repository).create(_command())
    return gate, epoch, repository, pin, binding


def test_session_create_cannot_write_before_deployment_activation() -> None:
    repository = MemorySessionCompositionRepository()
    service = SessionCompositionService(DeploymentActivationGate(), repository)

    with pytest.raises(KernelContractError) as raised:
        service.create(_command())

    assert raised.value.code == "deployment_not_active"
    assert repository.create_calls == 0


def test_session_pin_and_initial_binding_are_persisted_by_one_atomic_call() -> None:
    gate, epoch, repository, pin, binding = _create_pinned_session()

    assert gate.active_epoch == epoch
    assert repository.create_calls == 1
    assert repository.pin == pin
    assert repository.binding == binding
    assert pin.has_valid_digest()
    assert pin.composition_bundle_digest == epoch.composition_bundle_digest
    assert pin.release_identity == epoch.release_identity
    assert pin.initial_capability_binding_revision == 1
    assert pin.initial_capability_binding_digest == binding.binding_digest
    assert binding.extension_bundle_digest == epoch.release_identity.extension_bundle_digest
    assert binding.route_catalog_digest == epoch.release_identity.route_catalog_digest


def test_guard_allows_every_mutating_surface_under_exact_pin_and_binding() -> None:
    gate, _, _, pin, binding = _create_pinned_session()
    guard = SessionCompositionGuard(gate)

    for surface in SessionCompositionSurface:
        decision = guard.inspect(
            session_id="session-1",
            surface=surface,
            pin=pin,
            capability_binding=binding,
        )
        assert decision.state is SessionCompositionGuardState.ALLOWED


@pytest.mark.parametrize(
    "surface",
    tuple(
        surface
        for surface in SessionCompositionSurface
        if surface is not SessionCompositionSurface.SAFE_INSPECTION
    ),
)
def test_bundle_drift_blocks_every_entrypoint_before_callback(
    surface: SessionCompositionSurface,
) -> None:
    _, _, _, pin, binding = _create_pinned_session()
    new_composition, new_release, _ = activated_composition(include_plugin=False)
    new_gate, _ = activate_gate(
        new_composition,
        new_release,
        epoch_id="deployment-epoch-2",
    )
    guard = SessionCompositionGuard(new_gate)
    called = False

    def operation() -> str:
        nonlocal called
        called = True
        return "mutated"

    with pytest.raises(KernelContractError) as raised:
        execute_guarded_session_operation(
            guard,
            session_id="session-1",
            surface=surface,
            pin=pin,
            capability_binding=binding,
            operation=operation,
        )

    assert raised.value.code == "session_composition_upgrade_required"
    assert raised.value.mutation_applied is False
    assert called is False


def test_safe_inspection_returns_typed_upgrade_required_without_mutation() -> None:
    _, _, _, pin, binding = _create_pinned_session()
    new_composition, new_release, _ = activated_composition(include_plugin=False)
    new_gate, _ = activate_gate(new_composition, new_release, epoch_id="epoch-new")

    decision = SessionCompositionGuard(new_gate).inspect(
        session_id="session-1",
        surface=SessionCompositionSurface.SAFE_INSPECTION,
        pin=pin,
        capability_binding=binding,
    )

    assert decision.state is SessionCompositionGuardState.UPGRADE_REQUIRED
    assert "composition_bundle" in decision.drifted_fields
    assert decision.mutation_applied is False
    assert decision.fallback_performed is False


def test_monotonic_inventory_adoption_keeps_composition_pin_valid() -> None:
    gate, epoch, _, pin, binding = _create_pinned_session()
    revision_two = SessionCapabilityBindingRevision.create(
        binding_id="binding-2",
        session_id="session-1",
        revision=2,
        extension_bundle_digest=binding.extension_bundle_digest,
        route_catalog_digest=binding.route_catalog_digest,
        inventory_bindings=(),
        created_by_actor_id="operator-1",
        created_at="2026-08-19T03:00:00+00:00",
    )

    decision = SessionCompositionGuard(gate).require(
        session_id="session-1",
        surface=SessionCompositionSurface.TOOL_INVOCATION,
        pin=pin,
        capability_binding=revision_two,
    )

    assert decision.state is SessionCompositionGuardState.ALLOWED
    assert pin.composition_bundle_digest == epoch.composition_bundle_digest
    assert revision_two.binding_digest != pin.initial_capability_binding_digest


def test_same_composition_reactivation_does_not_hot_add_capability() -> None:
    _, _, _, pin, binding = _create_pinned_session()
    composition, release, _ = activated_composition()
    restarted_gate, restarted_epoch = activate_gate(
        composition,
        release,
        epoch_id="deployment-restart",
    )

    decision = SessionCompositionGuard(restarted_gate).require(
        session_id="session-1",
        surface=SessionCompositionSurface.RESTORE,
        pin=pin,
        capability_binding=binding,
    )

    assert decision.state is SessionCompositionGuardState.ALLOWED
    assert restarted_epoch.epoch_id != pin.deployment_epoch_id
    assert restarted_epoch.composition_bundle_digest == pin.composition_bundle_digest


def test_restore_rejects_capability_binding_from_another_bundle() -> None:
    gate, _, _, pin, binding = _create_pinned_session()
    drifted_binding = SessionCapabilityBindingRevision.create(
        binding_id="binding-drifted",
        session_id="session-1",
        revision=binding.revision + 1,
        extension_bundle_digest=digest("another-extension-bundle"),
        route_catalog_digest=binding.route_catalog_digest,
        inventory_bindings=(),
        created_by_actor_id="operator-1",
        created_at="2026-08-19T05:00:00+00:00",
    )

    with pytest.raises(KernelContractError) as raised:
        SessionCompositionGuard(gate).require(
            session_id="session-1",
            surface=SessionCompositionSurface.RESTORE,
            pin=pin,
            capability_binding=drifted_binding,
        )

    assert raised.value.code == "session_composition_upgrade_required"
    assert "capability_binding_extension_bundle" in raised.value.details[
        "drifted_fields"
    ]
