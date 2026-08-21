from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import datetime

import pytest

from openzyme_contracts import Session
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import AuthorityDecision
from openzyme_extension_spi import ExtensionStateCommand
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel import ExtensionStateKernelApplicationService
from openzyme_kernel import KernelContractError
from openzyme_kernel import MountedExtensionSurfaces
from openzyme_kernel import SessionCompositionCreateCommand
from openzyme_kernel import SessionCompositionGuard
from openzyme_kernel import SessionCompositionService

from composition_test_support import activate_gate
from composition_test_support import activated_composition


@dataclass(frozen=True)
class FakeParticipant:
    participant_id: str
    state_namespace: str

    def prepare(self, command: object, state: object) -> object:
        raise AssertionError("Store Adapter owns participant execution")

    def apply(self, plan: object, state: object) -> object:
        raise AssertionError("Store Adapter owns participant execution")


@dataclass
class MemorySessionRepository:
    session: Session | None = None
    pin: object | None = None
    binding: object | None = None

    def create_session_with_composition(
        self,
        *,
        session: Session,
        pin: object,
        initial_capability_binding: object,
    ) -> None:
        self.session = session
        self.pin = pin
        self.binding = initial_capability_binding

    def get_pin(self, session_id: str) -> object | None:
        return self.pin if self.session and self.session.session_id == session_id else None

    def latest_capability_binding(self, session_id: str) -> object | None:
        return (
            self.binding
            if self.session and self.session.session_id == session_id
            else None
        )


@dataclass
class FakeAuthority:
    allowed: bool = True
    calls: int = 0

    def authorize(self, request: object) -> AuthorityDecision:
        self.calls += 1
        return AuthorityDecision(
            allowed=self.allowed,
            operation=request.operation,
            scope_id=request.scope_id,
            authority_lease_id=request.context.authority_lease_id,
            generation=request.expected_generation,
            fence=request.expected_fence,
            denial_code=None if self.allowed else "authority_operation_denied",
        )


@dataclass
class FakeCoordinator:
    calls: int = 0

    def execute(self, *, command: object, participant: object, timestamp: str) -> object:
        self.calls += 1
        return (command, participant, timestamp)


class FixedClock:
    def now_iso(self) -> str:
        return datetime(2026, 8, 21, 2, 0, tzinfo=UTC).isoformat()


def _fixture() -> tuple:
    composition, release, plugin = activated_composition()
    assert plugin is not None
    gate, epoch = activate_gate(composition, release)
    repository = MemorySessionRepository()
    session = Session.create(
        "session-1",
        "project-1",
        "Extension state",
        "Prove exact extension mutation admission.",
    )
    pin, binding = SessionCompositionService(gate, repository).create(
        SessionCompositionCreateCommand(
            session=session,
            pin_id="pin-1",
            capability_binding_id="binding-1",
            inventory_bindings=(),
            actor_id="agent-1",
            created_at="2026-08-21T02:00:00+00:00",
        )
    )
    participant = FakeParticipant(
        participant_id=plugin.transaction_participants[0].contribution_id,
        state_namespace=plugin.state_namespace,
    )
    mounted = MountedExtensionSurfaces(
        epoch_id=epoch.epoch_id,
        activation_digest=epoch.activation_digest,
        tools=(),
        capability_routes=(),
        http_routes=(),
        projections=(),
        workers=(),
        finish_validators=(),
        transaction_participants=((participant.participant_id, participant),),
        mount_digest="sha256:" + "0" * 64,
    )
    mounted = replace(
        mounted,
        mount_digest=canonical_sha256_digest(mounted.digest_payload()),
    )
    authority = FakeAuthority()
    coordinator = FakeCoordinator()
    service = ExtensionStateKernelApplicationService(
        composition=composition,
        mounted=mounted,
        session_repository=repository,
        session_guard=SessionCompositionGuard(gate),
        authority=authority,
        coordinator=coordinator,
        clock=FixedClock(),
    )
    context = KernelCommandContext(
        command_id="command-1",
        session_id=session.session_id,
        actor_id="agent-1",
        owner_plugin_id=plugin.identity.component_id,
        authority_lease_id="lease-1",
        authority_generation=2,
        authority_fence=3,
        expected_session_version=1,
        extension_bundle_digest=pin.release_identity.extension_bundle_digest,
        capability_binding_digest=binding.binding_digest,
        idempotency_key="extension-command-1",
        correlation_id="correlation-1",
    )
    command = ExtensionStateCommand(
        context=context,
        participant_id=participant.participant_id,
        namespace=participant.state_namespace,
        operation="upsert_test_record",
        payload={"record": {"session_id": session.session_id}},
    )
    return service, authority, coordinator, command


def test_exact_context_reaches_only_the_activated_participant() -> None:
    service, authority, coordinator, command = _fixture()

    result = service.execute(command)

    assert result[0] is command
    assert result[1].participant_id == command.participant_id
    assert result[2] == "2026-08-21T02:00:00+00:00"
    assert authority.calls == 1
    assert coordinator.calls == 1


def test_stale_bundle_is_rejected_before_authority_or_store() -> None:
    service, authority, coordinator, command = _fixture()
    stale = replace(
        command,
        context=replace(
            command.context,
            extension_bundle_digest="sha256:" + "f" * 64,
        ),
    )

    with pytest.raises(KernelContractError) as raised:
        service.execute(stale)

    assert raised.value.code == "extension_command_composition_stale"
    assert authority.calls == 0
    assert coordinator.calls == 0


def test_cross_plugin_owner_is_rejected_before_store() -> None:
    service, authority, coordinator, command = _fixture()
    crossed = replace(
        command,
        context=replace(command.context, owner_plugin_id="other.plugin"),
    )

    with pytest.raises(KernelContractError) as raised:
        service.execute(crossed)

    assert raised.value.code == "extension_participant_owner_mismatch"
    assert authority.calls == 0
    assert coordinator.calls == 0


def test_stale_or_denied_authority_never_reaches_store() -> None:
    service, authority, coordinator, command = _fixture()
    authority.allowed = False

    with pytest.raises(KernelContractError) as raised:
        service.execute(command)

    assert raised.value.code == "authority_operation_denied"
    assert authority.calls == 1
    assert coordinator.calls == 0
