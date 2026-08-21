from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from types import SimpleNamespace

import pytest

from openzyme_contracts import RevisionPathEntryKind
from openzyme_contracts import RevisionPathRef
from openzyme_extension_spi import AuthorityDecision
from openzyme_extension_spi import ExtensionStateCommand
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel import ExtensionStateKernelApplicationService
from openzyme_kernel import KernelContractError
from openzyme_kernel import MountedExtensionSurfaces
from openzyme_reporting import REPORTING_STATE_NAMESPACE
from openzyme_reporting import ReportFormat
from openzyme_reporting import ReportVersion
from openzyme_reporting import ReportingStateMutationApplication
from openzyme_reporting import ReportingTransactionParticipant
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
        CREATE TABLE core_probe (command_id TEXT PRIMARY KEY);
        """
    )
    return connection


def _content_ref() -> RevisionPathRef:
    return RevisionPathRef.create(
        ref_id="ref-1",
        publication_id="publication-1",
        project_id="project-1",
        session_id="session-1",
        repository_binding_id="binding-1",
        repository_binding_version=1,
        repository_id="repository-1",
        commit="a" * 40,
        tree="b" * 40,
        path="reports/final.md",
        entry_kind=RevisionPathEntryKind.FILE,
        object_id="c" * 40,
        size_bytes=42,
        lfs_oid=None,
        lfs_size_bytes=None,
        path_manifest_digest=None,
        created_at="2026-08-21T00:00:00+00:00",
    )


def _report() -> ReportVersion:
    return ReportVersion.create(
        report_id="report-1",
        project_id="project-1",
        session_id="session-1",
        task_id="task-1",
        owner_agent_member_id="agent-1",
        report_contract_id="report.contract@1",
        report_version=1,
        report_format=ReportFormat.MARKDOWN,
        title="Report",
        summary="Metadata only.",
        content_ref=_content_ref(),
        supersedes_report_id=None,
        created_at="2026-08-21T00:00:00+00:00",
    )


def _context(*, fence: int = 3) -> KernelCommandContext:
    return KernelCommandContext(
        command_id="command-1",
        session_id="session-1",
        actor_id="agent-1",
        owner_plugin_id="openzyme.reporting",
        authority_lease_id="lease-1",
        authority_generation=2,
        authority_fence=fence,
        expected_session_version=4,
        extension_bundle_digest=DIGEST,
        capability_binding_digest=DIGEST,
        idempotency_key="idempotency-1",
        correlation_id="correlation-1",
    )


def _command() -> ExtensionStateCommand:
    participant = ReportingTransactionParticipant()
    return ExtensionStateCommand(
        context=_context(),
        participant_id=participant.participant_id,
        namespace=REPORTING_STATE_NAMESPACE,
        operation="upsert_reporting_records",
        payload={
            "records": [
                {
                    "entity_kind": "report_version",
                    "entity_id": "report-1",
                    "expected_state_version": None,
                    "record": _report().to_dict(),
                }
            ]
        },
    )


class _FailingParticipant(ReportingTransactionParticipant):
    def apply(self, plan, state):
        super().apply(plan, state)
        raise RuntimeError("forced participant failure after Reporting write")


@dataclass
class _Authority:
    calls: int = 0

    def authorize(self, request):
        self.calls += 1
        allowed = request.expected_generation == 2 and request.expected_fence == 3
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


def _application(
    connection: sqlite3.Connection,
    authority: _Authority,
    *,
    active: bool = True,
) -> ReportingStateMutationApplication:
    participant = ReportingTransactionParticipant()
    plugin = SimpleNamespace(
        identity=SimpleNamespace(component_id="openzyme.reporting"),
        transaction_participants=(
            SimpleNamespace(contribution_id=participant.participant_id),
        ),
    )
    composition = SimpleNamespace(
        plugins=SimpleNamespace(
            contributing_manifests=(plugin,) if active else (),
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
            ((participant.participant_id, participant),) if active else ()
        ),
        mount_digest="sha256:" + "0" * 64,
    )
    return ReportingStateMutationApplication(
        ExtensionStateKernelApplicationService(
            composition=composition,
            mounted=mounted,
            session_repository=_SessionRepository(),
            session_guard=_SessionGuard(),
            authority=authority,
            coordinator=SQLiteExtensionTransactionCoordinator(connection),
            clock=_Clock(),
        )
    )


def test_reporting_participant_failure_rolls_back_core_and_extension_state() -> None:
    connection = _connection()
    coordinator = SQLiteExtensionTransactionCoordinator(connection)

    with pytest.raises(SQLiteUnitOfWorkError):
        coordinator.execute(
            command=_command(),
            participant=_FailingParticipant(),
            timestamp="2026-08-21T00:00:00+00:00",
            core_mutation=lambda current: current.execute(
                "INSERT INTO core_probe (command_id) VALUES (?)",
                ("command-1",),
            ),
        )

    assert connection.execute("SELECT COUNT(*) FROM core_probe").fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_extension_state_records"
    ).fetchone()[0] == 0


def test_reporting_write_reaches_sqlite_only_after_kernel_admission() -> None:
    connection = _connection()
    authority = _Authority()
    result = _application(connection, authority).upsert_records(
        context=_context(),
        records=(
            {
                "entity_kind": "report_version",
                "entity_id": "report-1",
                "expected_state_version": None,
                "record": _report().to_dict(),
            },
        ),
    )

    assert result.mutation_applied is True
    assert authority.calls == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_extension_state_records"
    ).fetchone()[0] == 1


@pytest.mark.parametrize("active,fence,code", [(False, 3, "extension_participant_not_activated"), (True, 2, "authority_fence_stale")])
def test_reporting_inactive_or_stale_is_rejected_before_store(
    active: bool,
    fence: int,
    code: str,
) -> None:
    connection = _connection()
    authority = _Authority()
    with pytest.raises(KernelContractError) as raised:
        _application(connection, authority, active=active).upsert_records(
            context=_context(fence=fence),
            records=(
                {
                    "entity_kind": "report_version",
                    "entity_id": "report-1",
                    "expected_state_version": None,
                    "record": _report().to_dict(),
                },
            ),
        )

    assert raised.value.code == code
    assert connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_extension_state_records"
    ).fetchone()[0] == 0
