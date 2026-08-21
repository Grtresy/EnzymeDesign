from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from types import SimpleNamespace

import pytest

from openzyme_extension_spi import AuthorityDecision
from openzyme_extension_spi import ExtensionStateCommand
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel import ExtensionStateKernelApplicationService
from openzyme_kernel import KernelContractError
from openzyme_kernel import MountedExtensionSurfaces
from openzyme_science import SCIENCE_STATE_NAMESPACE
from openzyme_science import ScienceStateMutationApplication
from openzyme_science import ScienceTransactionParticipant
from openzyme_store_sqlite import SQLiteExtensionTransactionCoordinator
from openzyme_store_sqlite import SQLiteUnitOfWorkError


DIGEST = "sha256:" + "1" * 64


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE openzyme_store_extension_state_records (
            namespace TEXT NOT NULL,
            entity_kind TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            state_version INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            record_digest TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (namespace, entity_kind, entity_id)
        );
        CREATE TABLE core_probe (
            command_id TEXT PRIMARY KEY
        );
        """
    )
    return connection


def _command() -> ExtensionStateCommand:
    participant = ScienceTransactionParticipant()
    return ExtensionStateCommand(
        context=KernelCommandContext(
            command_id="command-1",
            session_id="session-1",
            actor_id="agent-1",
            owner_plugin_id="openzyme.science",
            authority_lease_id="lease-1",
            authority_generation=2,
            authority_fence=3,
            expected_session_version=4,
            extension_bundle_digest=DIGEST,
            capability_binding_digest=DIGEST,
            idempotency_key="idempotency-1",
            correlation_id="correlation-1",
        ),
        participant_id=participant.participant_id,
        namespace=SCIENCE_STATE_NAMESPACE,
        operation="upsert_science_record",
        payload={
            "entity_kind": "attempt",
            "entity_id": "attempt-1",
            "expected_state_version": None,
            "record": {
                "session_id": "session-1",
                "attempt_id": "attempt-1",
                "attempt_generation": 1,
                "state": "open",
            },
        },
    )


class _FailingScienceParticipant(ScienceTransactionParticipant):
    def apply(self, plan, state):
        super().apply(plan, state)
        raise RuntimeError("forced participant failure after Science write")


@dataclass
class _Authority:
    current_generation: int = 2
    current_fence: int = 3
    calls: int = 0

    def authorize(self, request):
        self.calls += 1
        allowed = (
            request.expected_generation == self.current_generation
            and request.expected_fence == self.current_fence
        )
        return AuthorityDecision(
            allowed=allowed,
            operation=request.operation,
            scope_id=request.scope_id,
            authority_lease_id=request.context.authority_lease_id,
            generation=request.expected_generation,
            fence=request.expected_fence,
            denial_code=None if allowed else "authority_fence_stale",
        )


class _SessionGuard:
    def require(self, **_):
        return None


class _Clock:
    def now_iso(self) -> str:
        return "2026-08-21T00:00:00+00:00"


class _SessionRepository:
    def __init__(self) -> None:
        self.pin = SimpleNamespace(
            release_identity=SimpleNamespace(extension_bundle_digest=DIGEST)
        )
        self.binding = SimpleNamespace(binding_digest=DIGEST)

    def get_pin(self, session_id: str):
        return self.pin if session_id == "session-1" else None

    def latest_capability_binding(self, session_id: str):
        return self.binding if session_id == "session-1" else None


def _kernel_application(
    connection: sqlite3.Connection,
    authority: _Authority,
    *,
    include_science: bool = True,
) -> ScienceStateMutationApplication:
    participant = ScienceTransactionParticipant()
    plugin = SimpleNamespace(
        identity=SimpleNamespace(component_id="openzyme.science"),
        transaction_participants=(
            SimpleNamespace(contribution_id=participant.participant_id),
        ),
    )
    composition = SimpleNamespace(
        plugins=SimpleNamespace(
            contributing_manifests=(plugin,) if include_science else (),
            extension_bundle_digest=DIGEST,
        )
    )
    mounted = MountedExtensionSurfaces(
        epoch_id="epoch-1",
        activation_digest=DIGEST,
        tools=(),
        capability_routes=(),
        http_routes=(),
        projections=(),
        workers=(),
        finish_validators=(),
        transaction_participants=(
            ((participant.participant_id, participant),) if include_science else ()
        ),
        mount_digest="sha256:" + "0" * 64,
    )
    kernel = ExtensionStateKernelApplicationService(
        composition=composition,
        mounted=mounted,
        session_repository=_SessionRepository(),
        session_guard=_SessionGuard(),
        authority=authority,
        coordinator=SQLiteExtensionTransactionCoordinator(connection),
        clock=_Clock(),
    )
    return ScienceStateMutationApplication(kernel)


def test_science_participant_failure_rolls_back_core_and_science_state() -> None:
    connection = _connection()
    coordinator = SQLiteExtensionTransactionCoordinator(connection)

    with pytest.raises(SQLiteUnitOfWorkError) as raised:
        coordinator.execute(
            command=_command(),
            participant=_FailingScienceParticipant(),
            timestamp="2026-08-21T00:00:00+00:00",
            core_mutation=lambda current: current.execute(
                "INSERT INTO core_probe (command_id) VALUES (?)",
                ("command-1",),
            ),
        )

    assert raised.value.phase == "participant_execution"
    assert connection.execute("SELECT COUNT(*) FROM core_probe").fetchone()[0] == 0
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM openzyme_store_extension_state_records"
        ).fetchone()[0]
        == 0
    )


def test_science_mutation_reaches_sqlite_only_through_kernel_admission() -> None:
    connection = _connection()
    authority = _Authority()
    application = _kernel_application(connection, authority)

    result = application.upsert_record(
        context=_command().context,
        entity_kind="attempt",
        entity_id="attempt-1",
        expected_state_version=None,
        record={
            "session_id": "session-1",
            "attempt_id": "attempt-1",
            "attempt_generation": 1,
            "state": "open",
        },
    )

    assert result.mutation_applied is True
    assert result.changed_records[0].namespace == SCIENCE_STATE_NAMESPACE
    assert authority.calls == 1
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM openzyme_store_extension_state_records"
        ).fetchone()[0]
        == 1
    )


def test_stale_science_fence_is_rejected_before_sqlite_mutation() -> None:
    connection = _connection()
    authority = _Authority()
    application = _kernel_application(connection, authority)
    stale = _command().context
    stale = KernelCommandContext(
        command_id=stale.command_id,
        session_id=stale.session_id,
        actor_id=stale.actor_id,
        owner_plugin_id=stale.owner_plugin_id,
        authority_lease_id=stale.authority_lease_id,
        authority_generation=stale.authority_generation,
        authority_fence=stale.authority_fence - 1,
        expected_session_version=stale.expected_session_version,
        extension_bundle_digest=stale.extension_bundle_digest,
        capability_binding_digest=stale.capability_binding_digest,
        idempotency_key=stale.idempotency_key,
        correlation_id=stale.correlation_id,
    )

    with pytest.raises(KernelContractError) as raised:
        application.upsert_record(
            context=stale,
            entity_kind="attempt",
            entity_id="attempt-1",
            expected_state_version=None,
            record={
                "session_id": "session-1",
                "attempt_id": "attempt-1",
                "attempt_generation": 1,
                "state": "open",
            },
        )

    assert raised.value.code == "authority_fence_stale"
    assert authority.calls == 1
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM openzyme_store_extension_state_records"
        ).fetchone()[0]
        == 0
    )


def test_absent_science_extension_rejects_mutation_before_authority_and_store() -> None:
    connection = _connection()
    authority = _Authority()
    application = _kernel_application(
        connection,
        authority,
        include_science=False,
    )

    with pytest.raises(KernelContractError) as raised:
        application.upsert_record(
            context=_command().context,
            entity_kind="attempt",
            entity_id="attempt-1",
            expected_state_version=None,
            record={
                "session_id": "session-1",
                "attempt_id": "attempt-1",
                "attempt_generation": 1,
                "state": "open",
            },
        )

    assert raised.value.code == "extension_participant_not_activated"
    assert authority.calls == 0
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM openzyme_store_extension_state_records"
        ).fetchone()[0]
        == 0
    )
